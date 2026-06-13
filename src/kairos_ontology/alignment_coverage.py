# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Deterministic alignment-coverage gate (DD-061).

Pre-modeling counterpart to the reference-model inventory gate (DD-047,
``check-inventory``).  Where ``check-inventory`` verifies that every reference
model TTL has a fresh materialized inventory, this module verifies that every
data domain enumerated in the affinity reports (``_analysis/*-affinity.yaml``,
schema_version 2) has a fresh, *complete* ``{domain}-alignment.yaml`` produced by
``propose-alignment``.

This closes the asymmetry that let a modeler hand-read a handful of tables
instead of representing every table the affinity report assigns to a domain: the
``Source Evidence Table`` is unstructured session markdown and cannot be checked,
but the affinity and alignment YAML files are structured and committed, so
"did propose-alignment cover every domain table, and is it still fresh?" is a
deterministic, AI-free question.

Both sides are read deterministically; no LLM call is made here.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

#: Alignment YAML ``schema_version`` that first stores ``source_sha256`` so a
#: freshness check is possible.  Older files (v1) are treated as *unverifiable*.
ALIGNMENT_HASH_SCHEMA_VERSION = 2


def compute_affinity_hash(pairs: Iterable[tuple[str, str]]) -> str:
    """Return a deterministic SHA-256 over a domain's ``(system, table)`` set.

    The hash is order-independent and duplicate-insensitive so it reflects the
    *set* of tables the affinity report assigns to a domain.  ``propose-alignment``
    stores this digest in the alignment YAML as ``source_sha256``; the gate
    recomputes it from the current affinity reports to detect staleness.
    """
    items = sorted({f"{system}\t{table}" for system, table in pairs})
    h = hashlib.sha256()
    h.update("\n".join(items).encode("utf-8"))
    return h.hexdigest()


def load_affinity_domain_tables(analysis_dir: Path) -> dict[str, set[tuple[str, str]]]:
    """Map each domain to the set of ``(system, table)`` pairs assigned to it.

    Reads every ``*-affinity.yaml`` (schema_version 2) in *analysis_dir*.  Tables
    with no ``domain`` are ignored (they were not classified into a data domain).
    """
    domain_tables: dict[str, set[tuple[str, str]]] = {}
    if not analysis_dir.is_dir():
        return domain_tables

    for affinity_file in sorted(analysis_dir.glob("*-affinity.yaml")):
        try:
            with open(affinity_file, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("Could not read affinity file %s: %s", affinity_file, e)
            continue

        if not isinstance(data, dict) or data.get("schema_version") != 2:
            logger.debug("Skipping %s (not schema_version 2)", affinity_file.name)
            continue

        system = data.get("system", affinity_file.stem.replace("-affinity", ""))
        for tbl in data.get("tables", []):
            if not isinstance(tbl, dict):
                continue
            domain = tbl.get("domain", "")
            table = tbl.get("table", "")
            if not domain or not table:
                continue
            domain_tables.setdefault(domain, set()).add((system, table))

    return domain_tables


def _alignment_aligned_tables(data: dict[str, Any]) -> set[tuple[str, str]]:
    """Return the ``(system, table)`` set actually present in an alignment file."""
    aligned: set[tuple[str, str]] = set()
    for tbl in data.get("tables", []) or []:
        if not isinstance(tbl, dict):
            continue
        system = tbl.get("system", "")
        table = tbl.get("table", "")
        if system and table:
            aligned.add((system, table))
    return aligned


def load_alignment(path: Path) -> dict[str, Any]:
    """Load an alignment YAML file, raising on malformed content."""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Alignment file {path} does not contain a YAML mapping")
    return data


@dataclass
class AlignmentCheckReport:
    """Result of a deterministic alignment-coverage check (DD-061).

    Each list holds domain ids, except *orphan* which holds alignment file names.
    A domain is single-bucketed with priority
    ``missing > incomplete > stale > unverifiable > ok``.
    """

    missing: list[str] = field(default_factory=list)
    incomplete: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    unverifiable: list[str] = field(default_factory=list)
    ok: list[str] = field(default_factory=list)
    orphan: list[str] = field(default_factory=list)
    #: domain → sorted "system.table" strings that are affinity-assigned but not aligned
    uncovered_tables: dict[str, list[str]] = field(default_factory=dict)

    @property
    def is_blocking(self) -> bool:
        """True when an alignment is missing, incomplete, or stale (hard failure)."""
        return bool(self.missing or self.incomplete or self.stale)

    @property
    def has_warnings(self) -> bool:
        """True when an unverifiable (no stored hash) or orphan alignment exists."""
        return bool(self.unverifiable or self.orphan)


def check_alignment_coverage(
    *,
    analysis_dir: Path,
    domains_filter: list[str] | None = None,
) -> AlignmentCheckReport:
    """Verify per-domain ``{domain}-alignment.yaml`` completeness and freshness.

    For each domain in the affinity reports:
      - **missing**      — no ``{domain}-alignment.yaml`` → blocking.
      - **incomplete**   — alignment exists but does not cover every affinity
        table for the domain → blocking (``uncovered_tables`` lists the gaps).
      - **stale**        — alignment stores a ``source_sha256`` that differs from
        the current affinity table set → blocking.
      - **unverifiable** — alignment exists and is complete but predates hash
        storage (schema_version < 2 / no ``source_sha256``) → warn.
      - **ok**           — complete and fresh.
      - **orphan**       — alignment file for a domain absent from the affinity
        reports → warn.
    """
    report = AlignmentCheckReport()
    domain_tables = load_affinity_domain_tables(analysis_dir)

    lower_filter = [d.lower() for d in domains_filter] if domains_filter else None

    def in_scope(domain: str) -> bool:
        if lower_filter is None:
            return True
        return any(f in domain.lower() for f in lower_filter)

    seen_files: set[str] = set()

    for domain in sorted(domain_tables):
        if not in_scope(domain):
            continue
        expected = domain_tables[domain]
        fname = f"{domain}-alignment.yaml"
        seen_files.add(fname)
        path = analysis_dir / fname

        if not path.exists():
            report.missing.append(domain)
            report.uncovered_tables[domain] = sorted(
                f"{s}.{t}" for s, t in expected
            )
            continue

        try:
            data = load_alignment(path)
        except Exception:
            report.stale.append(domain)
            continue

        aligned = _alignment_aligned_tables(data)
        gaps = expected - aligned
        if gaps:
            report.incomplete.append(domain)
            report.uncovered_tables[domain] = sorted(f"{s}.{t}" for s, t in gaps)
            continue

        schema_version = data.get("schema_version", 1)
        stored = data.get("source_sha256")
        if not stored or schema_version < ALIGNMENT_HASH_SCHEMA_VERSION:
            report.unverifiable.append(domain)
            continue

        if stored != compute_affinity_hash(expected):
            report.stale.append(domain)
        else:
            report.ok.append(domain)

    if analysis_dir.is_dir():
        for align_file in sorted(analysis_dir.glob("*-alignment.yaml")):
            if align_file.name not in seen_files:
                report.orphan.append(align_file.name)

    return report
