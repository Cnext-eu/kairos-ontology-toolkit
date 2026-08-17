# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Source-table disposition ledger (DD-164).

The blueprint deliberately scopes which domains exist, so a hub will always hold source
tables that no blueprint domain claims. Today that produces a silent fork: the table is
either dropped ("no canonical entity") or force-fitted by minting a local class in
whichever domain happened to be in scope. Both outcomes are unrecorded, and a real run
produced both *for the same table* — ``comments`` (3,149 rows) was dropped from
``claims`` as having no canonical home while a local ``Comment`` class appeared in four
other domains.

This module removes the silent fork by making the decision an artifact. Every source
table above :data:`DEFAULT_ROW_THRESHOLD` rows must be either bound or carry an explicit
disposition; an unbound, undisposed table is an error, not an omission.

The point is not to force every table into the ontology. ``not-business-data`` is a
perfectly good answer — it just has to be an answer someone wrote down, with a reason,
rather than the absence of one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SCHEMA_VERSION = 1

#: Tables smaller than this are not worth a human decision; below it an unbound table is
#: reported as informational only. Tuned to sit under the smallest table in the CLdN run
#: that was silently dropped while carrying real business content.
DEFAULT_ROW_THRESHOLD = 100

#: Where the ledger lives, relative to the hub root.
DISPOSITIONS_RELPATH = Path("integration") / "sources" / "_analysis" / "table-dispositions.yaml"

#: The closed set of answers. Each is a decision someone can defend in review.
DISPOSITIONS: dict[str, str] = {
    "bound": "An EntityBinding maps this table to a canonical class.",
    "registered-extension": (
        "Real business data outside the archetype catalog, registered as an in-scope "
        "concept with source evidence via 'kairos-ontology register-concept'."
    ),
    "deferred": ("In scope and modelled later; carries a reason and stays visible as a known gap."),
    "not-business-data": (
        "Metadata, schema-lookup, workflow, or scratch table with no canonical meaning."
    ),
    "blueprint-gap": (
        "Real business data the accelerator blueprint has no domain for — a reference-model "
        "defect to file upstream rather than a hub-side modelling choice."
    ),
}

#: Dispositions a human (or an attributed agent) must justify in prose.
_REQUIRES_RATIONALE = frozenset({"deferred", "not-business-data", "blueprint-gap"})

_ROW_COUNT_RE = re.compile(r"kairos-bronze:rowCount\s+(\d+)")
_TABLE_NAME_RE = re.compile(r'kairos-bronze:tableName\s+"((?:[^"\\]|\\.)*)"')
# One ``kairos-bronze:SourceTable`` block: everything from the type assertion to the
# statement-terminating " ." at the start of a line's end.
_SOURCE_TABLE_BLOCK_RE = re.compile(
    r"a\s+kairos-bronze:SourceTable\s*;(.*?)\.\s*$",
    re.MULTILINE | re.DOTALL,
)


@dataclass(frozen=True)
class DispositionDiagnostic:
    level: str  # "error" | "warning" | "info"
    code: str
    message: str
    system: str
    table: str
    remediation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "system": self.system,
            "table": self.table,
            "remediation": self.remediation,
        }


@dataclass
class DispositionReport:
    schema_version: int = SCHEMA_VERSION
    diagnostics: list[DispositionDiagnostic] = field(default_factory=list)
    tables_total: int = 0
    tables_bound: int = 0
    tables_disposed: int = 0
    tables_undecided: int = 0
    notices: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[DispositionDiagnostic]:
        return [d for d in self.diagnostics if d.level == "error"]

    @property
    def warnings(self) -> list[DispositionDiagnostic]:
        return [d for d in self.diagnostics if d.level == "warning"]

    @property
    def is_blocking(self) -> bool:
        return bool(self.errors)

    def coverage(self) -> float:
        """Fraction of tables with *any* recorded outcome — bound or explicitly disposed."""
        if not self.tables_total:
            return 1.0
        return round((self.tables_bound + self.tables_disposed) / self.tables_total, 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "totals": {
                "tables": self.tables_total,
                "bound": self.tables_bound,
                "disposed": self.tables_disposed,
                "undecided": self.tables_undecided,
            },
            "decision_coverage": self.coverage(),
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "notices": list(self.notices),
        }


def load_source_tables(sources_dir: Path) -> dict[tuple[str, str], int]:
    """Return ``{(system, table): row_count}`` for every imported source table.

    Row counts are read textually from the ``kairos-bronze:rowCount`` triple rather than
    through a graph parse: this is a size lookup used to rank human attention, not
    semantic access, and it must stay cheap enough to run inside ``validate``.
    A table with no recorded count is reported as ``-1`` (unknown) and always warrants a
    decision, since "we do not know how big it is" is not evidence that it is empty.
    """
    tables: dict[tuple[str, str], int] = {}
    if not sources_dir.is_dir():
        return tables
    for system_dir in sorted(sources_dir.iterdir()):
        if not system_dir.is_dir() or system_dir.name.startswith(("_", ".")):
            continue
        for path in sorted(system_dir.glob("*.ttl")):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for block in _SOURCE_TABLE_BLOCK_RE.finditer(text):
                body = block.group(1)
                # ``tableName`` is the physical name an EntityBinding's ``source.relation``
                # refers to ("qargo.companies"); the subject IRI is a PascalCase-ified
                # variant of it and would never match.
                name_match = _TABLE_NAME_RE.search(body)
                if name_match is None:
                    continue
                count_match = _ROW_COUNT_RE.search(body)
                tables[(system_dir.name, name_match.group(1))] = (
                    int(count_match.group(1)) if count_match else -1
                )
    return tables


def load_bound_relations(bindings_dir: Path) -> set[tuple[str, str]]:
    """Return ``{(system, table)}`` for every relation an EntityBinding already maps."""
    bound: set[tuple[str, str]] = set()
    if not bindings_dir.is_dir():
        return bound
    for path in sorted(bindings_dir.glob("*.yaml")):
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:  # defensive: a malformed binding is the compiler's problem
            continue
        if not isinstance(payload, dict):
            continue
        relation = ((payload.get("source") or {}) or {}).get("relation")
        if not isinstance(relation, str) or "." not in relation:
            continue
        system, _, table = relation.partition(".")
        bound.add((system.strip(), table.strip()))
    return bound


def load_dispositions(hub_root: Path) -> dict[tuple[str, str], dict[str, Any]]:
    """Read the disposition ledger, or ``{}`` when the hub has not written one yet."""
    path = Path(hub_root) / DISPOSITIONS_RELPATH
    if not path.is_file():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    recorded: dict[tuple[str, str, str], dict[str, Any]] = {}
    for entry in payload.get("tables") or []:
        if not isinstance(entry, dict):
            continue
        system = str(entry.get("system") or "").strip()
        table = str(entry.get("table") or "").strip()
        if system and table:
            recorded[(system, table, str(entry.get("column") or ""))] = entry
    return recorded


def audit_source_dispositions(
    *,
    hub_root: Path,
    row_threshold: int = DEFAULT_ROW_THRESHOLD,
) -> DispositionReport:
    """Require an explicit outcome for every source table of consequence."""
    hub_root = Path(hub_root)
    sources_dir = hub_root / "integration" / "sources"
    tables = load_source_tables(sources_dir)
    report = DispositionReport(tables_total=len(tables))
    if not tables:
        report.notices.append(
            f"No imported source tables found under {sources_dir}; nothing to decide."
        )
        return report

    bound = load_bound_relations(hub_root / "integration" / "bindings")
    recorded = load_dispositions(hub_root)

    for (system, table), row_count in sorted(tables.items()):
        key = (system, table)
        if key in bound:
            report.tables_bound += 1
            continue

        entry = recorded.get((*key, ""))
        if entry is not None:
            disposition = str(entry.get("disposition") or "").strip()
            if disposition not in DISPOSITIONS:
                report.diagnostics.append(
                    DispositionDiagnostic(
                        level="error",
                        code="disposition.unknown-value",
                        message=(
                            f"{system}.{table} records disposition '{disposition}', which is "
                            f"not one of: {', '.join(sorted(DISPOSITIONS))}."
                        ),
                        system=system,
                        table=table,
                        remediation="Use one of the closed disposition values.",
                    )
                )
                continue
            if disposition in _REQUIRES_RATIONALE and not str(entry.get("rationale") or "").strip():
                report.diagnostics.append(
                    DispositionDiagnostic(
                        level="error",
                        code="disposition.missing-rationale",
                        message=(
                            f"{system}.{table} is recorded as '{disposition}' with no rationale."
                        ),
                        system=system,
                        table=table,
                        remediation=(
                            "State why, in one sentence. A reviewer cannot tell a considered "
                            "skip from an overlooked table without it."
                        ),
                    )
                )
                continue
            report.tables_disposed += 1
            continue

        report.tables_undecided += 1
        size = "unknown size" if row_count < 0 else f"{row_count:,} rows"
        significant = row_count < 0 or row_count >= row_threshold
        report.diagnostics.append(
            DispositionDiagnostic(
                level="error" if significant else "warning",
                code="disposition.undecided-source-table",
                message=(
                    f"Source table {system}.{table} ({size}) is neither bound nor given an "
                    "explicit disposition."
                ),
                system=system,
                table=table,
                remediation=(
                    "Record the outcome with 'kairos-ontology source-disposition set "
                    f"--system {system} --table {table} --disposition <"
                    + "|".join(sorted(DISPOSITIONS))
                    + '> --rationale "..."\'. If it holds real business data the blueprint '
                    "has no home for, prefer 'registered-extension' (and run "
                    "'kairos-ontology register-concept') or 'blueprint-gap' over dropping it."
                ),
            )
        )

    return report


def clear_dispositions(
    hub_root: Path,
    *,
    tables: set[tuple[str, str]] | None = None,
    disposition: str | None = None,
    decided_by: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Remove matching disposition entries, returning what was (or would be) removed.

    Deferring a column is a decision, and so is undeferring it. A blanket
    ``deferred`` applied to a core operational table does clear the DD-169 gate,
    but it parks the very columns the hub exists to model — so there has to be a
    way to take it back that is as auditable as recording it was.

    Filters are conjunctive and all optional; ``decided_by`` is the important one
    in practice, because it lets an agent's blanket answers be withdrawn without
    touching a decision a human actually made.
    """
    path = Path(hub_root) / DISPOSITIONS_RELPATH
    if not path.is_file():
        return {"removed": 0, "kept": 0, "by_table": {}}

    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rows = payload.get("tables") or []

    def matches(entry: dict[str, Any]) -> bool:
        if not isinstance(entry, dict):
            return False
        if tables is not None:
            if (str(entry.get("system") or ""), str(entry.get("table") or "")) not in tables:
                return False
        if disposition is not None and str(entry.get("disposition") or "") != disposition:
            return False
        if decided_by is not None and str(entry.get("decided_by") or "") != decided_by:
            return False
        return True

    removed = [e for e in rows if matches(e)]
    kept = [e for e in rows if not matches(e)]
    by_table: dict[str, int] = {}
    for entry in removed:
        key = f"{entry.get('system')}.{entry.get('table')}"
        by_table[key] = by_table.get(key, 0) + 1

    if removed and not dry_run:
        payload["tables"] = kept
        path.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
    return {"removed": len(removed), "kept": len(kept), "by_table": by_table}


def record_disposition(
    *,
    hub_root: Path,
    system: str,
    table: str,
    disposition: str,
    rationale: str = "",
    decided_by: str = "user",
    evidence: tuple[str, ...] = (),
    column: str = "",
) -> Path:
    """Write or replace one disposition, returning the ledger path.

    Deliberately append-or-replace on a single YAML file rather than one file per table:
    the ledger's value is that a reviewer can read every skipped table in one place and
    see the shape of what the hub decided not to model.
    """
    if disposition not in DISPOSITIONS:
        raise ValueError(
            f"Unknown disposition {disposition!r}; expected one of {sorted(DISPOSITIONS)}."
        )
    if disposition in _REQUIRES_RATIONALE and not rationale.strip():
        raise ValueError(f"Disposition {disposition!r} requires a rationale.")

    path = Path(hub_root) / DISPOSITIONS_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "tables": []}
    if path.is_file():
        try:
            existing = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                payload = existing
                payload.setdefault("schema_version", SCHEMA_VERSION)
                payload.setdefault("tables", [])
        except Exception:
            pass

    entry = {
        "system": system,
        "table": table,
        # Column-grain entries sit in the same ledger as table-grain ones (DD-169): a
        # reviewer should see everything the hub decided not to model in one place, and
        # a second file would drift from the first.
        **({"column": column} if column else {}),
        "disposition": disposition,
        "rationale": rationale,
        "decided_by": decided_by,
    }
    if evidence:
        entry["evidence"] = list(evidence)

    # Replace only the entry at the SAME grain. The column must be part of the
    # identity: matching on (system, table) alone made every column-grain write
    # delete the table's previously recorded columns, so a run recording 224
    # column dispositions kept roughly one per table and silently lost the rest.
    # ``load_dispositions`` already keys on (system, table, column); this is the
    # writer catching up with it.
    rows = [
        item
        for item in payload.get("tables") or []
        if not (
            isinstance(item, dict)
            and item.get("system") == system
            and item.get("table") == table
            and str(item.get("column") or "") == column
        )
    ]
    rows.append(entry)
    payload["tables"] = sorted(
        rows,
        key=lambda item: (
            str(item.get("system")),
            str(item.get("table")),
            str(item.get("column") or ""),
        ),
    )

    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path
