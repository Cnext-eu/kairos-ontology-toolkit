# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Cross-domain alignment coverage, with a reason code per unmapped column (DD-168).

``propose-alignment`` already records, per table, which columns aligned to a
reference-model property and which fell through to ``custom_columns`` — with a rationale
and a recommended disposition on each. It records it *per domain file*, though, so the
question a reviewer actually asks has no answer anywhere: **across the whole hub, which
real business signal is still not represented in the domain model?**

Counting unmapped columns is not that answer. Most unmapped columns *should* be
unmapped: a ``created_at`` audit stamp, a ``Column7`` vendor placeholder, an all-null
field. Reporting 1,400 unmapped columns is as unhelpful as reporting none, because it
buries the fifty that matter. So every unmapped column is bucketed by *why*, and only
one bucket is a gap in the domain model:

* :data:`REASON_OPERATIONAL` — audit/system column. Correctly unmapped.
* :data:`REASON_VENDOR_SLOT` — generic placeholder (``Column7``). Correctly unmapped.
* :data:`REASON_NO_EVIDENCE` — no sample values, so nothing could be judged.
* :data:`REASON_LOW_CONFIDENCE` — a property was suggested but not trusted.
* :data:`REASON_NO_REFERENCE_PROPERTY` — **the gap.** Real, populated business data that
  the reference model has no home for. These are the columns that force a decision:
  extend the hub locally, register the concept (DD-164), or file a blueprint gap.

Classification reuses ``propose_alignment``'s own operational/vendor-slot predicates
rather than a bespoke list, so a column this report calls operational is the same one
the aligner declined to map for that reason.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1

REASON_OPERATIONAL = "operational"
REASON_VENDOR_SLOT = "vendor-slot"
REASON_NO_EVIDENCE = "no-sample-evidence"
REASON_LOW_CONFIDENCE = "low-confidence-suggestion"
REASON_NO_REFERENCE_PROPERTY = "no-reference-property"

#: Ordered worst-last so a report reads from "needs a decision" down to "expected".
REASON_ORDER: tuple[str, ...] = (
    REASON_NO_REFERENCE_PROPERTY,
    REASON_LOW_CONFIDENCE,
    REASON_NO_EVIDENCE,
    REASON_VENDOR_SLOT,
    REASON_OPERATIONAL,
)

#: Human-facing explanation and the action each bucket implies.
REASON_GUIDANCE: dict[str, str] = {
    REASON_NO_REFERENCE_PROPERTY: (
        "Real business data with no reference-model property. Close the gap: model it "
        "in the owning domain, register it with 'register-concept', or record it as a "
        "blueprint-gap disposition."
    ),
    REASON_LOW_CONFIDENCE: (
        "A property was suggested but not trusted. Cheapest to review by hand — the "
        "candidate is already named."
    ),
    REASON_NO_EVIDENCE: (
        "No sample values, so neither the model nor a human can judge it. Re-import "
        "with samples, or accept that the column carries no observable signal."
    ),
    REASON_VENDOR_SLOT: (
        "Generic vendor placeholder (Column1, Field3). Carry to Silver as a "
        "passthrough; there is nothing canonical to map."
    ),
    REASON_OPERATIONAL: ("Audit/system column (created, updated, guid, hash). Correctly unmapped."),
}

#: Buckets that represent a genuine hole in the domain model.
GAP_REASONS: frozenset[str] = frozenset({REASON_NO_REFERENCE_PROPERTY, REASON_LOW_CONFIDENCE})


@dataclass(frozen=True)
class UnmappedColumn:
    system: str
    table: str
    column: str
    data_type: str
    reason: str
    suggestion: str = ""
    recommended_disposition: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "system": self.system,
            "table": self.table,
            "column": self.column,
            "data_type": self.data_type,
            "reason": self.reason,
            "suggestion": self.suggestion,
            "recommended_disposition": self.recommended_disposition,
        }


@dataclass
class DomainCoverage:
    domain: str
    tables: int = 0
    columns: int = 0
    mapped: int = 0
    by_alignment: dict[str, int] = field(default_factory=dict)
    unmapped: list[UnmappedColumn] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        return round(self.mapped / self.columns, 4) if self.columns else 1.0

    def reason_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for column in self.unmapped:
            counts[column.reason] = counts.get(column.reason, 0) + 1
        return counts

    @property
    def gap_columns(self) -> list[UnmappedColumn]:
        return [c for c in self.unmapped if c.reason in GAP_REASONS]


@dataclass
class AlignmentReport:
    schema_version: int = SCHEMA_VERSION
    domains: list[DomainCoverage] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)

    @property
    def columns(self) -> int:
        return sum(d.columns for d in self.domains)

    @property
    def mapped(self) -> int:
        return sum(d.mapped for d in self.domains)

    @property
    def coverage(self) -> float:
        return round(self.mapped / self.columns, 4) if self.columns else 1.0

    def reason_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for domain in self.domains:
            for reason, count in domain.reason_counts().items():
                counts[reason] = counts.get(reason, 0) + count
        return counts

    @property
    def gap_columns(self) -> list[UnmappedColumn]:
        return [c for d in self.domains for c in d.gap_columns]

    def gaps_by_table(self) -> list[tuple[str, int]]:
        """Tables ranked by how much unmapped real signal they hold."""
        counts: dict[str, int] = {}
        for column in self.gap_columns:
            key = f"{column.system}.{column.table}"
            counts[key] = counts.get(key, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "totals": {
                "domains": len(self.domains),
                "columns": self.columns,
                "mapped": self.mapped,
                "unmapped": self.columns - self.mapped,
                "coverage": self.coverage,
                "gap_columns": len(self.gap_columns),
            },
            "by_reason": self.reason_counts(),
            "domains": [
                {
                    "domain": d.domain,
                    "tables": d.tables,
                    "columns": d.columns,
                    "mapped": d.mapped,
                    "coverage": d.coverage,
                    "by_alignment": d.by_alignment,
                    "by_reason": d.reason_counts(),
                }
                for d in self.domains
            ],
            "gap_columns": [c.to_dict() for c in self.gap_columns],
            "notices": list(self.notices),
        }


#: Positional placeholder names: ``Column7``, ``Field12``, ``col_3``, ``unnamed_4``.
#:
#: Broader than ``propose_alignment.is_generic_vendor_slot``, which matches only
#: ``cf``-prefixed vendor custom-field slots (``cf1``, ``cfx12``). That predicate does
#: not cover the shape a real hub actually produced — a CWEB checklist export whose
#: columns are literally ``Column2`` through ``Column18``. Left un-detected they land in
#: the ``no-reference-property`` bucket and read as unmapped business signal, which is
#: precisely the noise this report exists to remove.
#:
#: Kept local rather than widening the shared predicate: that one also drives
#: ``recommend_disposition`` inside the aligner, and broadening it would change mapping
#: behaviour as a side effect of adding a report.
_POSITIONAL_PLACEHOLDER_RE = re.compile(
    r"^(?:column|col|field|fld|unnamed|untitled)[\s_-]*\d+$", re.IGNORECASE
)


def classify_unmapped(entry: dict[str, Any], column_name: str) -> str:
    """Return the reason code for one unmapped column.

    Order matters: a column can be both operational and evidence-free, and the
    operational answer is the more useful one because it needs no action.
    """
    from .propose_alignment import _is_operational_column, is_generic_vendor_slot

    if _is_operational_column(column_name) or (entry.get("recommended_disposition") == "skip"):
        return REASON_OPERATIONAL
    if is_generic_vendor_slot(column_name) or _POSITIONAL_PLACEHOLDER_RE.match(
        (column_name or "").strip()
    ):
        return REASON_VENDOR_SLOT
    if entry.get("suggested_property"):
        return REASON_LOW_CONFIDENCE
    if not (entry.get("example_values") or entry.get("samples")):
        return REASON_NO_EVIDENCE
    return REASON_NO_REFERENCE_PROPERTY


def build_alignment_report(analysis_dir: Path) -> AlignmentReport:
    """Aggregate every ``*-alignment.yaml`` into one cross-domain coverage picture."""
    import yaml

    report = AlignmentReport()
    directory = Path(analysis_dir)
    if not directory.is_dir():
        report.notices.append(f"No analysis directory at {directory}.")
        return report

    files = sorted(directory.glob("*-alignment.yaml"))
    if not files:
        report.notices.append(
            f"No alignment files in {directory}. Run 'kairos-ontology propose-alignment' first."
        )
        return report

    for path in files:
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:  # defensive: one broken file must not sink the report
            report.notices.append(f"Could not read {path.name}; skipped.")
            continue
        if not isinstance(document, dict):
            continue

        coverage = DomainCoverage(domain=str(document.get("domain") or path.stem))
        for table in document.get("tables") or ():
            if not isinstance(table, dict):
                continue
            coverage.tables += 1
            system = str(table.get("system") or "")
            name = str(table.get("table") or "")

            for column in table.get("columns") or ():
                if not isinstance(column, dict):
                    continue
                coverage.columns += 1
                kind = str(column.get("alignment") or "custom")
                coverage.by_alignment[kind] = coverage.by_alignment.get(kind, 0) + 1
                if column.get("ref_property"):
                    coverage.mapped += 1

            for entry in table.get("custom_columns") or ():
                if not isinstance(entry, dict):
                    continue
                column_name = str(entry.get("column") or "")
                coverage.columns += 1
                reason = classify_unmapped(entry, column_name)
                coverage.unmapped.append(
                    UnmappedColumn(
                        system=system,
                        table=name,
                        column=column_name,
                        data_type=str(entry.get("data_type") or ""),
                        reason=reason,
                        suggestion=str(entry.get("suggested_property") or ""),
                        recommended_disposition=str(entry.get("recommended_disposition") or ""),
                    )
                )
        report.domains.append(coverage)

    report.domains.sort(key=lambda d: (-len(d.gap_columns), d.domain))
    return report


def render_markdown(report: AlignmentReport, *, gap_limit: int = 40) -> str:
    """Render the short report a reviewer reads before a design session."""
    lines: list[str] = ["# Source alignment coverage", ""]
    lines.append(
        f"**{report.mapped:,} of {report.columns:,} source columns** aligned to a "
        f"reference-model property ({report.coverage:.0%}). "
        f"**{len(report.gap_columns):,}** carry real signal with no canonical home."
    )
    lines.append("")

    lines.append("## Why columns are unmapped")
    lines.append("")
    lines.append("| Reason | Columns | What it means |")
    lines.append("|---|---:|---|")
    counts = report.reason_counts()
    for reason in REASON_ORDER:
        if reason in counts:
            lines.append(f"| `{reason}` | {counts[reason]:,} | {REASON_GUIDANCE[reason]} |")
    lines.append("")

    lines.append("## Coverage by domain")
    lines.append("")
    lines.append("| Domain | Tables | Columns | Mapped | Coverage | Gap columns |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for domain in report.domains:
        lines.append(
            f"| {domain.domain} | {domain.tables} | {domain.columns} | {domain.mapped} "
            f"| {domain.coverage:.0%} | {len(domain.gap_columns)} |"
        )
    lines.append("")

    gaps = report.gaps_by_table()
    if gaps:
        lines.append("## Where the unmapped signal is concentrated")
        lines.append("")
        for table, count in gaps[:15]:
            lines.append(f"- **{table}** — {count} column(s)")
        lines.append("")

    if report.gap_columns:
        lines.append("## Columns needing a decision")
        lines.append("")
        lines.append("| Table | Column | Type | Reason | Suggested |")
        lines.append("|---|---|---|---|---|")
        for column in report.gap_columns[:gap_limit]:
            lines.append(
                f"| {column.system}.{column.table} | `{column.column}` | {column.data_type} "
                f"| `{column.reason}` | {column.suggestion or '—'} |"
            )
        if len(report.gap_columns) > gap_limit:
            lines.append("")
            lines.append(
                f"_…and {len(report.gap_columns) - gap_limit:,} more; "
                "use `--format json` for the full list._"
            )
        lines.append("")

    for notice in report.notices:
        lines.append(f"> {notice}")
    return "\n".join(lines)


#: What a reviewer must choose between for each undecided gap column. Rendered into the
#: gate's failure output, because a hard stop that does not say how to clear it is an
#: obstacle rather than a control.
GAP_RESOLUTIONS: tuple[str, ...] = (
    "model it in the domain that owns it (the reference model lacks it, the business "
    "has it, and a sibling domain is the right home)",
    "register it with 'kairos-ontology register-concept' — real business data outside "
    "the archetype catalog, recorded with its source evidence",
    "record a disposition: 'source-disposition set --system <s> --table <t> --column "
    "<c> --disposition <blueprint-gap|not-business-data|deferred> --rationale \"...\"'",
)


def undecided_gap_columns(
    hub_root: Path, *, domains: Iterable[str] | None = None
) -> list[UnmappedColumn]:
    """Return gap columns that carry real signal and have no recorded decision (DD-169).

    This is the pre-binding gate. Alignment is the first stage that can say "this column
    holds business data and the canonical model has nowhere to put it", and Stage 4 is
    where that becomes permanent: an EntityBinding either maps a column or silently
    leaves it behind, and by then the omission looks like a completed mapping.

    Only :data:`GAP_REASONS` columns count. Audit stamps, vendor placeholders and
    evidence-free columns are excluded by construction, so clearing this gate means
    deciding about real signal, not clicking through noise.
    """
    from .source_disposition import load_dispositions

    report = build_alignment_report(
        Path(hub_root) / "integration" / "sources" / "_analysis"
    )
    scope = set(domains) if domains is not None else None
    recorded = load_dispositions(Path(hub_root))
    decided = {
        (str(entry.get("system") or ""), str(entry.get("table") or ""), str(entry.get("column") or ""))
        for entry in recorded.values()
    }

    undecided: list[UnmappedColumn] = []
    for domain in report.domains:
        if scope is not None and domain.domain not in scope:
            continue
        for column in domain.gap_columns:
            # A table-grain disposition covers every column in it: deciding a whole
            # table is out of scope also decides its columns.
            if (column.system, column.table, "") in decided:
                continue
            if (column.system, column.table, column.column) in decided:
                continue
            undecided.append(column)
    return undecided


def iter_gap_columns(report: AlignmentReport) -> Iterable[UnmappedColumn]:
    """Yield gap columns worst-table-first, for callers driving a review."""
    ranked = {table: index for index, (table, _) in enumerate(report.gaps_by_table())}
    return sorted(
        report.gap_columns,
        key=lambda c: (ranked.get(f"{c.system}.{c.table}", 1 << 30), c.column),
    )
