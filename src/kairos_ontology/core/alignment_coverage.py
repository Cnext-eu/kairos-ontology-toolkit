# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Deterministic affinity/freshness primitives reused by the claim gate.

Historically this module implemented the alignment-coverage gate
(``check-alignment``). That gate is retired (decision log ``DD-EL-1``); the Claim
Registry is now the single source of truth and :mod:`claim_coverage` provides the
``check-claims`` gate. What remains here are the deterministic, AI-free primitives
that gate (and ``propose-alignment``) still reuse:

* :func:`compute_affinity_hash` / :func:`load_affinity_domain_tables` — the
  ``(system, table)`` set and freshness digest a domain must cover (also used by
  :mod:`source_coverage`);
* the custom-column triage heuristics (:func:`recommend_disposition` /
  :func:`auto_disposition` / :func:`is_generic_vendor_slot`) used by
  ``propose-alignment`` to pre-classify source-evidenced custom columns.

Both sides are read deterministically; no LLM call is made here.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterable
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

#: Alignment hash ``schema_version`` that first stored ``source_sha256`` so a
#: freshness check is possible.  Carried into the Claim Registry as the minimum
#: verifiable algorithm version.
ALIGNMENT_HASH_SCHEMA_VERSION = 2

#: Issue #182 — affinity/proposal *algorithm / prompt-contract* version.  Bumped
#: whenever the proposal output semantics change (prompt hardening, null
#: ``ref_property`` for unmatched columns, confidence-gated suggestions, canonical
#: state model).  A registry written by an older version is reported as
#: *unverifiable* by ``check-claims`` so a pre-hardening proposal is never
#: silently trusted.
ALIGNMENT_ALGORITHM_VERSION = 2


def compute_affinity_hash(pairs: Iterable[tuple[str, str]]) -> str:
    """Return a deterministic SHA-256 over a domain's ``(system, table)`` set.

    The hash is order-independent and duplicate-insensitive so it reflects the
    *set* of tables the affinity report assigns to a domain.  ``propose-alignment``
    stores this digest in the Claim Registry as ``freshness.affinity_sha256``; the
    gate recomputes it from the current affinity reports to detect staleness.
    """
    items = sorted({f"{system}\t{table}" for system, table in pairs})
    h = hashlib.sha256()
    h.update("\n".join(items).encode("utf-8"))
    return h.hexdigest()


def load_affinity_domain_tables(
    analysis_dir: Path,
    *,
    excluded_systems: set[str] | None = None,
) -> dict[str, set[tuple[str, str]]]:
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
        if system in (excluded_systems or set()):
            logger.info(
                "Skipping generated affinity report %s for system %s",
                affinity_file.name,
                system,
            )
            continue
        for tbl in data.get("tables", []):
            if not isinstance(tbl, dict):
                continue
            domain = tbl.get("domain", "")
            table = tbl.get("table", "")
            if not domain or not table:
                continue
            domain_tables.setdefault(domain, set()).add((system, table))

    return domain_tables


def load_affinity_domain_table_columns(
    analysis_dir: Path,
    *,
    excluded_systems: set[str] | None = None,
) -> dict[str, dict[tuple[str, str], int]]:
    """Map each domain to ``{(system, table): total_columns}`` from affinity reports.

    F6 (toolkit-optimizations): the affinity/analysis stage records the *true*
    source-column count per table (``total_columns``). The Claim Registry, by
    contrast, only counts the columns that survived alignment (prompt truncation
    can drop some). ``check_claims_coverage`` compares the registry's covered
    column count against this trustworthy per-table count to detect columns that
    were silently dropped. Mirrors :func:`load_affinity_domain_tables`.
    """
    domain_table_cols: dict[str, dict[tuple[str, str], int]] = {}
    if not analysis_dir.is_dir():
        return domain_table_cols

    for affinity_file in sorted(analysis_dir.glob("*-affinity.yaml")):
        try:
            with open(affinity_file, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("Could not read affinity file %s: %s", affinity_file, e)
            continue

        if not isinstance(data, dict) or data.get("schema_version") != 2:
            continue

        system = data.get("system", affinity_file.stem.replace("-affinity", ""))
        if system in (excluded_systems or set()):
            continue
        for tbl in data.get("tables", []):
            if not isinstance(tbl, dict):
                continue
            domain = tbl.get("domain", "")
            table = tbl.get("table", "")
            if not domain or not table:
                continue
            try:
                total = int(tbl.get("total_columns", 0) or 0)
            except (TypeError, ValueError):
                total = 0
            domain_table_cols.setdefault(domain, {})[(system, table)] = total

    return domain_table_cols

#: Lower-cased substrings that mark a custom column as *likely operational/audit*
#: (ETL/technical) rather than a business attribute needing a modeling decision.
#: Used only to bucket the report so genuine business columns aren't buried — it
#: never excludes a column from triage.
_OPERATIONAL_PATTERNS = (
    "created_", "updated_", "modified_", "inserted_", "deleted_",
    "_created", "_updated", "_modified", "createdat", "updatedat",
    "_by", "createdby", "modifiedby", "timestamp", "rowversion",
    "row_version", "loaddate", "load_date", "load_ts", "loadts",
    "etl_", "_etl", "_dwh", "dwh_", "is_deleted", "isdeleted",
    "source_id", "sourceid", "source_system", "sourcesystem",
    "_guid", "guid", "uuid", "_uid", "_hash", "checksum",
)


def _is_operational_column(column: str) -> bool:
    """Heuristically flag audit/ETL/technical custom columns (bucketing only)."""
    name = (column or "").lower()
    return any(pat in name for pat in _OPERATIONAL_PATTERNS)


#: Generic vendor custom-field slot (e.g. Soloplan ``CFSTRING33``,
#: ``CFENUMERATION54``) — an opaque slot that should carry to silver as a
#: passthrough rather than be modeled as a domain property (issue #182 WS2).
_CF_SLOT_RE = re.compile(r"^cf[a-z]*\d+$", re.IGNORECASE)

#: Narrow, near-zero-ambiguity audit/technical patterns that are safe to
#: *auto-dispose* as ``skip`` without a human decision (issue #182 WS2). Kept
#: tighter than ``_OPERATIONAL_PATTERNS`` so a borderline business column is only
#: ever *recommended*, never silently disposed.
_AUDIT_AUTO_PATTERNS = (
    "created_", "_created", "createdon", "createdby", "createdat",
    "updated_", "_updated", "updatedon", "updatedby", "updatedat",
    "modified_", "_modified", "modifiedon", "modifiedby",
    "inserted_", "is_deleted", "isdeleted",
    "rowversion", "row_version",
    "loaddate", "load_date", "load_ts", "loadts", "last_ingest", "ingest_date",
    "etl_", "_etl", "_dwh", "dwh_",
    "tenant_id", "tenantid",
    "_hash", "checksum",
)


def is_generic_vendor_slot(column: str) -> bool:
    """True for opaque vendor custom-field slots (e.g. ``CFSTRING33``)."""
    return bool(_CF_SLOT_RE.match((column or "").strip()))


def recommend_disposition(column: str) -> str:
    """Advisory triage recommendation for a custom column (issue #182 WS2).

    Returns ``silver-passthrough`` for opaque vendor slots, ``skip`` for
    operational/audit columns, and ``""`` for everything else (a business column a
    human must decide on). This is *advisory only*; it never sets the final
    ``disposition`` by itself (see :func:`auto_disposition`).
    """
    if is_generic_vendor_slot(column):
        return "silver-passthrough"
    if _is_operational_column(column) or auto_disposition(column) == "skip":
        return "skip"
    return ""


def auto_disposition(column: str) -> str | None:
    """Final disposition auto-fillable without a human decision, or ``None``.

    Only narrow, near-zero-ambiguity audit/technical columns qualify (issue #182
    WS2). Generic vendor slots and business columns are deliberately excluded so
    they remain a conscious decision (or an explicit ``--accept-heuristics``).
    """
    name = (column or "").lower()
    if any(p in name for p in _AUDIT_AUTO_PATTERNS):
        return "skip"
    return None
