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
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

#: Alignment YAML ``schema_version`` that first stores ``source_sha256`` so a
#: freshness check is possible.  Older files (v1) are treated as *unverifiable*.
ALIGNMENT_HASH_SCHEMA_VERSION = 2

#: Issue #182 — alignment *algorithm / prompt-contract* version.  Bumped whenever
#: the alignment output semantics change (prompt hardening, null ``ref_property``
#: for unmatched columns, confidence-gated suggestions, canonical state model).
#: A file written by an older version is reported as *unverifiable* by
#: ``check-alignment`` so a pre-hardening alignment is never silently trusted.
ALIGNMENT_ALGORITHM_VERSION = 2


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


#: Canonical triage dispositions written back into a custom column by the
#: ``kairos-design-domain`` skill (issue #164).  Any other non-empty value is
#: still treated as *disposed* so the gate never blocks on a deliberate choice.
CUSTOM_DISPOSITIONS = ("model", "silver-passthrough", "skip")

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


def _is_disposed(entry: dict[str, Any]) -> bool:
    """True when a custom column carries an explicit, non-empty triage disposition."""
    disp = entry.get("disposition")
    return isinstance(disp, str) and disp.strip() != ""


@dataclass
class CustomColumn:
    """A source-evidenced custom column (no reference-model property) to triage."""

    system: str
    table: str
    column: str
    suggested_property: str = ""
    disposition: str | None = None
    operational: bool = False
    #: Issue #182 WS2 — advisory triage recommendation (``skip`` /
    #: ``silver-passthrough`` / ``""``). Never blocks on its own.
    recommended_disposition: str = ""
    #: Issue #182 WS2 — provenance of ``disposition``: ``human`` (a person triaged
    #: it), ``heuristic`` (auto-filled audit/technical), or ``""`` (undisposed).
    disposition_source: str = ""

    @property
    def disposed(self) -> bool:
        return isinstance(self.disposition, str) and self.disposition.strip() != ""

    def effective_disposed(self, accept_heuristics: bool = False) -> bool:
        """True when disposed, or — under ``accept_heuristics`` — when a non-empty
        ``recommended_disposition`` exists (issue #182 WS2)."""
        if self.disposed:
            return True
        return accept_heuristics and bool(self.recommended_disposition)

    @property
    def identity(self) -> str:
        return f"{self.system}.{self.table}.{self.column}"


def collect_custom_columns(data: dict[str, Any]) -> list[CustomColumn]:
    """Extract and classify every ``custom_columns`` entry from an alignment file."""
    out: list[CustomColumn] = []
    for tbl in data.get("tables", []) or []:
        if not isinstance(tbl, dict):
            continue
        system = tbl.get("system", "")
        table = tbl.get("table", "")
        for cc in tbl.get("custom_columns", []) or []:
            if not isinstance(cc, dict):
                continue
            column = cc.get("column", "")
            if not column:
                continue
            disposition = cc.get("disposition")
            stored_source = str(cc.get("disposition_source", "") or "")
            # A disposition with no recorded source is assumed human-authored.
            if disposition and not stored_source:
                stored_source = "human"
            # Recompute the advisory recommendation so legacy files (and files where
            # the heuristic vocabulary changed) surface the current guidance.
            recommended = str(
                cc.get("recommended_disposition", "") or ""
            ) or recommend_disposition(column)
            out.append(
                CustomColumn(
                    system=system,
                    table=table,
                    column=column,
                    suggested_property=cc.get("suggested_property", "") or "",
                    disposition=disposition,
                    operational=_is_operational_column(column),
                    recommended_disposition=recommended,
                    disposition_source=stored_source,
                )
            )
    return out


@dataclass
class ReviewColumn:
    """A mapped column flagged for human review by propose-alignment (DD-069).

    Carries the deterministic plausibility/address ``review_reason`` so
    ``check-alignment`` can surface implausible maps. Report-only — these never
    block the gate (issues #167/#168).
    """

    system: str
    table: str
    column: str
    ref_property: str = ""
    reason: str = ""

    @property
    def identity(self) -> str:
        return f"{self.system}.{self.table}.{self.column}"


def collect_review_columns(data: dict[str, Any]) -> list[ReviewColumn]:
    """Extract every column flagged with ``review: true`` from an alignment file."""
    out: list[ReviewColumn] = []
    for tbl in data.get("tables", []) or []:
        if not isinstance(tbl, dict):
            continue
        system = tbl.get("system", "")
        table = tbl.get("table", "")
        for col in tbl.get("columns", []) or []:
            if not isinstance(col, dict) or not col.get("review"):
                continue
            column = col.get("column", "")
            if not column:
                continue
            out.append(
                ReviewColumn(
                    system=system,
                    table=table,
                    column=column,
                    ref_property=col.get("ref_property", "") or "",
                    reason=col.get("review_reason", "") or "",
                )
            )
    return out


@dataclass
class AnchorIssue:
    """A hallucinated/unanchored reference class found in an alignment (issue #182).

    ``kind`` is one of:
      - ``hallucinated`` — a non-empty ``ref_class`` that is not in any reference
        model's class set (e.g. a ``Booking`` anchor that exists in no DCSA model);
      - ``rejected`` — the generator itself rejected the model's class pick and left
        the table unanchored (``ref_class_status: rejected``);
      - ``unmatched`` — the table has no anchor class at all.
    """

    system: str
    table: str
    kind: str
    ref_class: str = ""
    rejected_ref_class: str = ""

    @property
    def identity(self) -> str:
        return f"{self.system}.{self.table}"


def collect_anchor_issues(
    data: dict[str, Any],
    valid_ref_classes: set[str],
) -> list[AnchorIssue]:
    """Find hallucinated/unanchored table anchors in one alignment file (WS6).

    A table's ``ref_class`` is *hallucinated* when it is non-empty yet absent from
    ``valid_ref_classes`` (the union of every reference model's class names). Tables
    the generator already flagged ``rejected``/``unmatched`` (issue #182 WS6
    metadata) are surfaced too, even when their (blanked) ``ref_class`` is empty.
    """
    out: list[AnchorIssue] = []
    for tbl in data.get("tables", []) or []:
        if not isinstance(tbl, dict):
            continue
        system = tbl.get("system", "")
        table = tbl.get("table", "")
        ref_class = str(tbl.get("ref_class", "") or "")
        status = str(tbl.get("ref_class_status", "") or "")
        rejected = str(tbl.get("rejected_ref_class", "") or "")
        if ref_class and ref_class not in valid_ref_classes:
            out.append(AnchorIssue(
                system=system, table=table, kind="hallucinated",
                ref_class=ref_class, rejected_ref_class=rejected,
            ))
        elif status == "rejected":
            out.append(AnchorIssue(
                system=system, table=table, kind="rejected",
                ref_class=ref_class, rejected_ref_class=rejected,
            ))
        elif status == "unmatched" or not ref_class:
            out.append(AnchorIssue(
                system=system, table=table, kind="unmatched",
                ref_class=ref_class, rejected_ref_class=rejected,
            ))
    return out


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
    #: domain → all source-evidenced custom columns (issue #164), classified +
    #: carrying their triage disposition.  Drives the report and ``--strict`` gate.
    custom_columns: dict[str, list[CustomColumn]] = field(default_factory=dict)
    #: domain → columns flagged ``review: true`` by propose-alignment (DD-069,
    #: issues #167/#168). Report-only — never contributes to ``is_blocking``.
    review_columns: dict[str, list[ReviewColumn]] = field(default_factory=dict)
    #: domain → hallucinated/unanchored table anchors (issue #182 WS6). Populated
    #: only when ``check_anchors=True`` with a reference-class set. Blocks via
    #: ``has_hallucinated_anchors`` (separate from ``--strict``).
    anchor_issues: dict[str, list[AnchorIssue]] = field(default_factory=dict)

    @property
    def is_blocking(self) -> bool:
        """True when an alignment is missing, incomplete, or stale (hard failure)."""
        return bool(self.missing or self.incomplete or self.stale)

    @property
    def has_warnings(self) -> bool:
        """True when an unverifiable (no stored hash) or orphan alignment exists."""
        return bool(self.unverifiable or self.orphan)

    def undisposed_custom_columns(
        self, domain: str, *, accept_heuristics: bool = False
    ) -> list[CustomColumn]:
        """Custom columns for *domain* still lacking an effective disposition.

        Under ``accept_heuristics`` (issue #182 WS2) a column carrying a non-empty
        ``recommended_disposition`` counts as disposed.
        """
        return [
            c for c in self.custom_columns.get(domain, [])
            if not c.effective_disposed(accept_heuristics)
        ]

    def any_undisposed_custom_columns(self, *, accept_heuristics: bool = False) -> bool:
        """True when any domain has an untriaged custom column (issue #164/#182).

        ``accept_heuristics`` treats a column with a non-empty
        ``recommended_disposition`` as disposed (WS2).
        """
        return any(
            not c.effective_disposed(accept_heuristics)
            for cols in self.custom_columns.values()
            for c in cols
        )

    @property
    def has_undisposed_custom_columns(self) -> bool:
        """True when any domain has an undisposed custom column (no heuristics)."""
        return self.any_undisposed_custom_columns(accept_heuristics=False)

    @property
    def hallucinated_anchors(self) -> list[AnchorIssue]:
        """All issue-#182 ``hallucinated`` anchors across domains (flattened)."""
        return [
            ai
            for issues in self.anchor_issues.values()
            for ai in issues
            if ai.kind == "hallucinated"
        ]

    @property
    def has_hallucinated_anchors(self) -> bool:
        """True when any table anchors on a class absent from every reference model."""
        return bool(self.hallucinated_anchors)


def check_alignment_coverage(
    *,
    analysis_dir: Path,
    domains_filter: list[str] | None = None,
    check_anchors: bool = False,
    valid_ref_classes: set[str] | None = None,
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

        # Issue #164: collect custom columns whenever the file loads, regardless
        # of coverage/freshness state, so they surface even for incomplete domains.
        custom = collect_custom_columns(data)
        if custom:
            report.custom_columns[domain] = custom

        # DD-069: collect review-flagged maps (report-only; never blocks).
        flagged = collect_review_columns(data)
        if flagged:
            report.review_columns[domain] = flagged

        # Issue #182 (WS6): validate table anchor classes against the real
        # reference-model class set, surfacing hallucinated/unanchored anchors.
        if check_anchors and valid_ref_classes is not None:
            issues = collect_anchor_issues(data, valid_ref_classes)
            if issues:
                report.anchor_issues[domain] = issues

        aligned = _alignment_aligned_tables(data)
        gaps = expected - aligned
        if gaps:
            report.incomplete.append(domain)
            report.uncovered_tables[domain] = sorted(f"{s}.{t}" for s, t in gaps)
            continue

        schema_version = data.get("schema_version", 1)
        stored = data.get("source_sha256")
        algorithm_version = data.get("algorithm_version", 0)
        if (
            not stored
            or schema_version < ALIGNMENT_HASH_SCHEMA_VERSION
            or algorithm_version < ALIGNMENT_ALGORITHM_VERSION
        ):
            # Missing freshness hash, legacy schema, or produced by an older
            # alignment algorithm/prompt contract (issue #182) → cannot be trusted
            # as up to date; surface as a warning so it is regenerated.
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
