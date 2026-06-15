# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""One-way migration: ``{domain}-alignment.yaml`` → ``{domain}-claims.yaml``.

Deterministic and AI-free (decision log ``DD-EL-1``, schema doc §3). Converts the
retired alignment output into a Claim Registry of ``proposed`` claims so no prior
analysis is lost; a human then approves/curates. After migration the legacy
alignment file is rejected (no dual path) — callers use
:func:`legacy_alignment_error` to surface a clear message.

Field mapping (schema doc §3.2):

* table ``ref_class``            → one ``class`` claim per *distinct* ref class
  (evidence aggregates every source table that aligned to it).
* column ``ref_property``        → one ``property`` claim per distinct
  ``(ref_class, ref_property)`` (evidence aggregates the source columns).
* ``custom_columns[].disposition`` (``model`` | ``silver-passthrough`` | ``skip``)
  → ``specialize`` | ``passthrough`` | ``skip`` (untriaged → ``passthrough``,
  flagged in the rationale).
* ``source_sha256`` / ``alignment_params_sha256`` → ``freshness``.
* ``algorithm_version`` / ``generated_at`` → top-level fields.
* per-table column counts + ``ref_class_status`` → ``coverage``.

All migrated claims land as ``status: proposed`` — migration never fabricates an
approval. URIs stay unresolved (``class_uri`` / ``property_uri`` = null) until a
human approves the claim; coverage retains the ref-class name for context.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from .claim_registry import (
    TRIAGE_TO_DISPOSITION,
    Claim,
    ClaimRegistry,
    CoverageSystem,
    CoverageTable,
    EvidenceSource,
    Freshness,
)

logger = logging.getLogger(__name__)

LEGACY_ALIGNMENT_GLOB = "*-alignment.yaml"


def _slug(value: str) -> str:
    """Stable kebab-case slug for claim ids."""
    s = re.sub(r"[^0-9a-zA-Z]+", "-", str(value)).strip("-").lower()
    return s or "x"


def legacy_alignment_error(path: Path) -> str:
    """Return the standard message for a retired alignment file."""
    domain = path.name.replace("-alignment.yaml", "")
    return (
        f"{path.name} is retired (DD-EL-1). Run the one-shot migration to "
        f"model/claims/{domain}-claims.yaml:\n"
        f"    kairos-ontology migrate-claims --domain {domain}\n"
        f"The alignment YAML is no longer read."
    )


def find_legacy_alignment_files(search_dir: Path) -> list[Path]:
    """Return any legacy ``*-alignment.yaml`` files under *search_dir*."""
    if not search_dir.exists():
        return []
    return sorted(search_dir.glob(LEGACY_ALIGNMENT_GLOB))


def alignment_to_registry(data: dict[str, Any]) -> ClaimRegistry:
    """Convert a parsed alignment YAML mapping into a :class:`ClaimRegistry`.

    Pure function — deterministic for a given input. Claims and coverage are
    emitted in a stable (sorted) order so the output is byte-stable for golden
    tests.
    """
    domain = str(data.get("domain", "") or "")
    freshness = Freshness(
        affinity_sha256=data.get("source_sha256"),
        alignment_params_sha256=data.get("alignment_params_sha256"),
    )

    # Coverage grouped by system → table.
    coverage_by_system: dict[str, dict[str, CoverageTable]] = {}
    # Dedup concept claims; preserve aggregated evidence.
    class_claims: dict[str, Claim] = {}            # key: ref_class
    property_claims: dict[tuple[str, str], Claim] = {}  # key: (ref_class, ref_property)
    custom_claims: dict[tuple[str, str], Claim] = {}    # key: (system, table, column) flattened

    for table in data.get("tables", []) or []:
        system = str(table.get("system", "") or "")
        tname = str(table.get("table", "") or "")
        ref_class = str(table.get("ref_class", "") or "")
        columns = table.get("columns", []) or []
        custom_columns = table.get("custom_columns", []) or []
        anchor_state = str(table.get("ref_class_status", "") or "matched")

        coverage_by_system.setdefault(system, {})[tname] = CoverageTable(
            table=tname,
            total_columns=len(columns) + len(custom_columns),
            mapped_columns=len(columns),
            custom_columns=len(custom_columns),
            anchor_state=anchor_state if anchor_state in (
                "matched", "fallback", "rejected", "unmatched") else "matched",
            ref_class=ref_class or None,
        )

        # Class claim (one per distinct ref class).
        if ref_class:
            claim = class_claims.get(ref_class)
            if claim is None:
                claim = Claim(
                    id=f"{domain}-{_slug(ref_class)}",
                    type="class",
                    status="proposed",
                    disposition="claim",
                    origin="imported",
                    rationale=f"Migrated from alignment: source tables aligned to "
                              f"reference class '{ref_class}'.",
                )
                class_claims[ref_class] = claim
            claim.evidence_sources.append(
                EvidenceSource(type="source_table", system=system, table=tname)
            )

        # Property claims (one per distinct ref_class + ref_property).
        for col in columns:
            ref_prop = str(col.get("ref_property", "") or "")
            if not ref_prop:
                continue  # unmatched column — no concept to claim
            col_ref_class = str(col.get("ref_class", "") or ref_class)
            key = (col_ref_class, ref_prop)
            pclaim = property_claims.get(key)
            if pclaim is None:
                pclaim = Claim(
                    id=f"{domain}-{_slug(col_ref_class)}-{_slug(ref_prop)}",
                    type="property",
                    status="proposed",
                    disposition="claim",
                    origin="imported",
                    rationale=f"Migrated from alignment: maps to property "
                              f"'{ref_prop}' on '{col_ref_class}'.",
                )
                property_claims[key] = pclaim
            pclaim.evidence_sources.append(
                EvidenceSource(
                    type="source_column", system=system, table=tname,
                    column=str(col.get("column", "") or ""),
                )
            )

        # Custom-column claims (client-native; triage → disposition).
        for col in custom_columns:
            cname = str(col.get("column", "") or "")
            triage = col.get("disposition")
            disposition = TRIAGE_TO_DISPOSITION.get(triage) if triage else None
            untriaged = disposition is None
            if untriaged:
                disposition = "passthrough"
            rationale = str(col.get("rationale", "") or "").strip()
            note = (
                "Untriaged custom column — defaulted to passthrough; needs a "
                "disposition decision. " if untriaged else ""
            ) + rationale
            key = (system, tname, cname)
            custom_claims[key] = Claim(
                id=f"{domain}-custom-{_slug(system)}-{_slug(tname)}-{_slug(cname)}",
                type="property",
                status="proposed",
                disposition=disposition,
                origin="authored",
                rationale=note or None,
                evidence_sources=[
                    EvidenceSource(
                        type="source_column", system=system, table=tname, column=cname
                    )
                ],
            )

    coverage = [
        CoverageSystem(
            system=system,
            tables=[coverage_by_system[system][t] for t in sorted(coverage_by_system[system])],
        )
        for system in sorted(coverage_by_system)
    ]

    all_claims = list(class_claims.values()) + list(property_claims.values()) + \
        list(custom_claims.values())
    all_claims.sort(key=lambda c: c.id)

    return ClaimRegistry(
        domain=domain,
        generated_at=data.get("generated_at"),
        algorithm_version=data.get("algorithm_version"),
        freshness=freshness,
        coverage=coverage,
        claims=all_claims,
    )


def migrate_alignment_file(path: Path) -> ClaimRegistry:
    """Load an alignment YAML file and convert it to a :class:`ClaimRegistry`."""
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: alignment file is not a mapping")
    return alignment_to_registry(data)
