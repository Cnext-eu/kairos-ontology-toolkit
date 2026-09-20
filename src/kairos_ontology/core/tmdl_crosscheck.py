# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Cross-check the hand-rolled TMDL parser against the TOM SDK (issue #879).

``import-tmdl`` reads Power BI models with a line-and-regex parser
(:mod:`kairos_ontology.core.tmdl_parser`). The toolkit already bundles the real
Microsoft Tabular Object Model SDK, but only on the *write* path, where it checks that
TMDL the toolkit generated will open. This module points the same engine at the export
being imported and compares what the two of them saw.

It does not replace the parser and it does not block an import. It answers one question
the toolkit could not previously ask at all: **did we read everything the engine Power BI
itself uses can see?**

The question is worth asking because the answer was "no" three times in one dogfood
session, each time silently:

- a flat-layout export (tables beside ``model.tmdl``, no ``definition/tables/``) read as
  zero tables, and the operator was told to re-export files that were already present;
- multi-line DAX in a fenced block was stored as fence text, so 53 of 59 measures
  reached the engineering pack with no definition;
- an export genuinely missing its table definitions was reported as a model with no
  tables, which is indistinguishable downstream from a model that has none.

All three are cases where the parser returned a confident, well-formed, wrong answer.
That is exactly the failure a second opinion catches and a test suite does not, because
nobody writes a fixture for the export shape they have never seen.

Advisory by construction. No dotnet, no cross-check; a cross-check that raises is worse
than none, so every failure path here returns "unavailable" rather than propagating.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .tmdl_parser import TmdlModel

__all__ = [
    "CrossCheckFinding",
    "CrossCheckReport",
    "STATUS_AGREED",
    "STATUS_DISAGREED",
    "STATUS_UNAVAILABLE",
    "crosscheck_parsed_model",
    "render_crosscheck_note",
]

#: The two readings match on every dimension compared.
STATUS_AGREED = "agreed"
#: They differ. The parser's output is still what the import used; this says so.
STATUS_DISAGREED = "disagreed"
#: No second opinion was obtainable (no dotnet, or the SDK could not run here).
STATUS_UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class CrossCheckFinding:
    """One dimension on which the two readings differ."""

    #: ``tables-missing`` | ``tables-extra`` | ``measures-missing`` | ``columns-missing``
    #: | ``relationships-missing`` | ``tom-rejected``
    kind: str
    #: What differs, in terms an operator can act on.
    detail: str


@dataclass(frozen=True, slots=True)
class CrossCheckReport:
    """What the parser saw, what the TOM SDK saw, and where they disagree."""

    status: str
    #: Why, when there is nothing to compare.
    reason: str = ""
    findings: tuple[CrossCheckFinding, ...] = field(default_factory=tuple)

    @property
    def disagreed(self) -> bool:
        return self.status == STATUS_DISAGREED


def _tom_inventory(payload: dict) -> dict[str, dict]:
    """Index the tool's table list by case-folded name.

    TMDL does not guarantee that a table's name and its filename agree on case, and the
    parser derives names from file contents while TOM derives them from the model. A
    case difference between the two is not a finding worth reporting -- reporting it
    would be the cross-check crying wolf on its first run.
    """
    tables = payload.get("tables")
    if not isinstance(tables, list):
        return {}
    indexed: dict[str, dict] = {}
    for entry in tables:
        if isinstance(entry, dict) and entry.get("name"):
            indexed[str(entry["name"]).casefold()] = entry
    return indexed


#: Cap on a TOM error message. Its dangling-link report names every broken endpoint,
#: which on one real export ran to four thousand characters listing the same fact about
#: thirty-four tables. A warning nobody can read is a warning nobody reads.
_MAX_MESSAGE = 400


def _truncate(message: str) -> str:
    """Keep the diagnosis, drop the enumeration."""
    collapsed = " ".join(message.split())
    if len(collapsed) <= _MAX_MESSAGE:
        return collapsed
    return f"{collapsed[:_MAX_MESSAGE].rstrip()}… (message truncated)"


def _sample(names: list[str], limit: int = 5) -> str:
    """Name the first few, count the rest. A wall of names is read as noise."""
    shown = ", ".join(sorted(names)[:limit])
    remainder = len(names) - limit
    return f"{shown}{f' … and {remainder} more' if remainder > 0 else ''}"


def crosscheck_parsed_model(model: TmdlModel, definition_dir: Path) -> CrossCheckReport:
    """Compare *model* against the TOM SDK's reading of *definition_dir*.

    Compares table names, and per shared table the column and measure counts. Names
    rather than totals, because a total that happens to match while the membership
    differs is the failure mode a count-only check would miss.

    A TOM ``fail`` is itself reported: the engine rejecting an export our parser read
    happily means the model will not open in Power BI Desktop either, which the operator
    would otherwise discover only when they tried.
    """
    from .projections.dbt.tmdl_validate import inspect_tmdl_folder

    payload = inspect_tmdl_folder(Path(definition_dir))
    status = str(payload.get("status") or "")

    if status == "unavailable":
        return CrossCheckReport(
            status=STATUS_UNAVAILABLE,
            reason=str(payload.get("message") or "the TOM SDK could not run here"),
        )
    if status == "fail":
        return CrossCheckReport(
            status=STATUS_DISAGREED,
            findings=(
                CrossCheckFinding(
                    kind="tom-rejected",
                    detail=_truncate(
                        "the TOM SDK refuses this export, so Power BI Desktop will "
                        f"refuse it too: {payload.get('error_type', 'error')}: "
                        f"{payload.get('message', '')}"
                    ),
                ),
            ),
        )
    if status != "pass":
        return CrossCheckReport(
            status=STATUS_UNAVAILABLE, reason=f"unrecognised validator status {status!r}"
        )

    tom_tables = _tom_inventory(payload)
    if not tom_tables and payload.get("table_count"):
        # An older build of the tool that reports a count and no inventory. Comparing
        # against a count we cannot attribute would produce findings nobody can act on.
        return CrossCheckReport(
            status=STATUS_UNAVAILABLE,
            reason="the validator reported no table inventory to compare against",
        )

    ours = {table.name.casefold(): table for table in model.tables}
    findings: list[CrossCheckFinding] = []

    missing = [tom_tables[key]["name"] for key in tom_tables.keys() - ours.keys()]
    if missing:
        findings.append(
            CrossCheckFinding(
                kind="tables-missing",
                detail=(
                    f"the TOM SDK reads {len(missing)} table(s) this import did not: "
                    f"{_sample(missing)}"
                ),
            )
        )

    extra = [ours[key].name for key in ours.keys() - tom_tables.keys()]
    if extra:
        findings.append(
            CrossCheckFinding(
                kind="tables-extra",
                detail=(
                    f"this import read {len(extra)} table(s) the TOM SDK does not: "
                    f"{_sample(extra)}"
                ),
            )
        )

    short_measures: list[str] = []
    short_columns: list[str] = []
    for key in tom_tables.keys() & ours.keys():
        entry, table = tom_tables[key], ours[key]
        their_measures = int(entry.get("measure_count") or 0)
        their_columns = int(entry.get("column_count") or 0)
        if len(table.measures) < their_measures:
            short_measures.append(f"{table.name} ({len(table.measures)} of {their_measures})")
        if len(table.columns) < their_columns:
            short_columns.append(f"{table.name} ({len(table.columns)} of {their_columns})")

    if short_measures:
        findings.append(
            CrossCheckFinding(
                kind="measures-missing",
                detail=(
                    f"{len(short_measures)} table(s) carry fewer measures than the TOM "
                    f"SDK reads: {_sample(short_measures)}"
                ),
            )
        )
    if short_columns:
        findings.append(
            CrossCheckFinding(
                kind="columns-missing",
                detail=(
                    f"{len(short_columns)} table(s) carry fewer columns than the TOM "
                    f"SDK reads: {_sample(short_columns)}"
                ),
            )
        )

    their_relationships = payload.get("relationship_count")
    if isinstance(their_relationships, int) and len(model.relationships) < their_relationships:
        findings.append(
            CrossCheckFinding(
                kind="relationships-missing",
                detail=(
                    f"this import read {len(model.relationships)} relationship(s); the "
                    f"TOM SDK reads {their_relationships}"
                ),
            )
        )

    if findings:
        return CrossCheckReport(status=STATUS_DISAGREED, findings=tuple(findings))
    return CrossCheckReport(status=STATUS_AGREED)


def render_crosscheck_note(report: CrossCheckReport, model_name: str) -> str:
    """The Markdown section an engineering pack carries when the two readings differ.

    Written into the artifact rather than only logged, for the same reason the DD-234
    enforcement block is: the operator who needs this is the one opening the pack later
    and wondering why it is thinner than the report they remember, not the one watching
    the terminal during the import.

    Empty string when the two agree or when there was no second opinion, so an
    unaffected pack is unchanged.
    """
    if not report.disagreed:
        return ""
    lines = [
        "## ⚠ Cross-check: this import read less than Power BI's own engine does",
        "",
        f"The Microsoft TOM SDK — the engine Power BI Desktop and Fabric use to open a "
        f"model — disagrees with how `{model_name}` was read here:",
        "",
    ]
    lines.extend(f"- {finding.detail}" for finding in report.findings)
    lines.extend(
        [
            "",
            "Everything below reflects **this import's** reading, which is the one that "
            "was used. Treat the pack as incomplete until the difference is explained: "
            "a measure or table missing here is missing from every artifact derived from "
            "it, and nothing downstream can tell that it was ever there.",
            "",
        ]
    )
    return "\n".join(lines)
