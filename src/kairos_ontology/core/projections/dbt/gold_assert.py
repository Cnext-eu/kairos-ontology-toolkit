# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Semantic assertions over the emitted Power BI artifacts.

The two gates that already run are structural. `pbip_validate` checks the package JSON
against Microsoft's published schemas and never reads TMDL at all; `tmdl_validate` runs
the real TOM SDK but only calls `TmdlSerializer.DeserializeDatabaseFromFolder`, which
proves the TMDL *parses*, not that the engine will accept the model it describes.

Every defect in #619, #623 and #790-#794 passed both and was rejected downstream. This
module is the missing third gate: cheap checks on what was actually emitted, asserting
the handful of engine rules the serializer does not enforce. It deliberately reads the
rendered artifact text rather than the typed spec -- a spec-level check of "the model
sets `discourageImplicitMeasures` when it emits a calculation group" is tautological when
one flag drives both, and would keep passing while the emitted bytes drifted apart.

Checks are grouped one function per engine rule so a failure names the rule it broke.
"""

from __future__ import annotations

import re

from .gold_specs import GoldContractError

#: One tab, then `column `, which in TMDL is a column of the table opened by the
#: unindented `table` line. Columns nested deeper belong to something else.
_TABLE_COLUMN = re.compile(r"^\tcolumn\s", re.MULTILINE)
_CALCULATION_ITEM = re.compile(r"^\t\tcalculationItem\s+(?P<name>.+?)\s*=", re.MULTILINE)
_ITEM_ORDINAL = re.compile(r"^\t\t\tordinal:\s*\d+\s*$", re.MULTILINE)
_PARTITION = re.compile(r"^\tpartition\s", re.MULTILINE)

_RULE = "DD-113-gold-semantics"
_BPA_RULE = "DD-238-bpa-profile"

#: One object's property block: its header line at one tab, properties at two.
_TABLE_OBJECT = re.compile(r"^\t(?P<kind>column|measure)\s+(?P<name>.+?)(?:\s*=.*)?$")
_NUMERIC_TYPES = {"int64", "decimal", "double"}
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_RELATIONSHIP_END = re.compile(
    r"^\t(?P<side>from|to)Column:\s*(?P<table>'[^']+'|[^.\s]+)\.(?P<column>.+?)\s*$"
)


def assert_gold_semantics(artifacts: dict[str, str]) -> None:
    """Raise `GoldContractError` if the emitted model breaks an engine rule.

    *artifacts* is the full path -> content mapping `render_powerbi_artifacts` is about
    to return, so this sees exactly what ships.
    """
    calculation_groups = {
        path: content
        for path, content in artifacts.items()
        if "/calculationGroups/" in path and path.endswith(".tmdl")
    }
    for path, content in calculation_groups.items():
        _assert_calculation_group(path, content)
    if calculation_groups:
        _assert_discourages_implicit_measures(artifacts, calculation_groups)
    _assert_best_practice(artifacts)


def _assert_calculation_group(path: str, content: str) -> None:
    """A calculation group table needs 1-2 data columns, a sort order and a partition."""
    columns = _TABLE_COLUMN.findall(content)
    # The engine's own wording is "only supports 1 or 2 data columns", but Kairos always
    # emits exactly two -- the name column and the ordinal it sorts by. Asserting the
    # engine's looser bound would accept a single name column whose `sortByColumn`
    # dangles, which parses and then fails downstream for a different reason.
    if len(columns) != 2:
        raise GoldContractError(
            "gold.calculation-group-columns",
            (
                f"{path} declares {len(columns)} data column(s); a calculation group "
                "needs exactly the name column and its ordinal"
            ),
            rule_id=_RULE,
            resource_uri=path,
        )
    if "sortByColumn:" not in content:
        raise GoldContractError(
            "gold.calculation-group-unsorted",
            (
                f"{path} has no sortByColumn, so its items sort alphabetically rather "
                "than chronologically"
            ),
            rule_id=_RULE,
            resource_uri=path,
        )
    if not _PARTITION.search(content):
        raise GoldContractError(
            "gold.calculation-group-partition-missing",
            f"{path} declares no partition",
            rule_id=_RULE,
            resource_uri=path,
        )
    items = _CALCULATION_ITEM.findall(content)
    ordinals = _ITEM_ORDINAL.findall(content)
    if len(items) != len(ordinals):
        raise GoldContractError(
            "gold.calculation-group-ordinals",
            (
                f"{path} declares {len(items)} calculation item(s) but "
                f"{len(ordinals)} ordinal(s); every item needs one to sort deterministically"
            ),
            rule_id=_RULE,
            resource_uri=path,
        )


def _objects(content: str) -> list[tuple[str, str, list[str]]]:
    """``(kind, name, property lines)`` for each column and measure of one table file."""
    objects: list[tuple[str, str, list[str]]] = []
    for line in content.splitlines():
        match = _TABLE_OBJECT.match(line)
        if match is not None:
            objects.append((match.group("kind"), match.group("name").strip("'"), [line]))
        elif objects and line.startswith("\t\t"):
            objects[-1][2].append(line.strip())
        elif line.strip():
            objects.append(("", "", []))
    return [item for item in objects if item[0]]


def _property(lines: list[str], name: str) -> str | None:
    prefix = f"{name}:"
    for line in lines:
        if line == name:
            return ""
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return None


def _fail_bpa(code: str, message: str, path: str) -> None:
    raise GoldContractError(code, message, rule_id=_BPA_RULE, resource_uri=path)


def _assert_best_practice(artifacts: dict[str, str]) -> None:
    """Assert the profile's by-construction and render-assert rules on emitted text.

    DD-238. A by-construction rule is only as good as the construction, and the
    construction is spread over a renderer that keeps growing; asserting the rendered
    bytes is what keeps "cannot happen" true.
    """
    tables = {
        path: content
        for path, content in artifacts.items()
        if "/definition/tables/" in path and path.endswith(".tmdl")
    }
    column_types: dict[tuple[str, str], str] = {}
    for path, content in tables.items():
        table = path.rsplit("/", 1)[1].removesuffix(".tmdl")
        for line in content.splitlines():
            if line.lstrip("\t").startswith("///") and _CONTROL.search(line):
                _fail_bpa(
                    "gold.description-control-character",
                    f"{path} carries a control character in a description",
                    path,
                )
        for kind, name, lines in _objects(content):
            if kind == "column":
                column_types[(table, name)] = (_property(lines, "dataType") or "").casefold()
                if _property(lines, "sourceColumn") is None:
                    _fail_bpa(
                        "gold.column-source-missing",
                        f"{path}: column {name} names no sourceColumn",
                        path,
                    )
                if (
                    column_types[(table, name)] in _NUMERIC_TYPES
                    and _property(lines, "isHidden") is None
                    and _property(lines, "summarizeBy") != "none"
                ):
                    _fail_bpa(
                        "gold.column-summarized",
                        (
                            f"{path}: visible numeric column {name} is not summarizeBy: none, "
                            "so Power BI would sum it by default"
                        ),
                        path,
                    )
            else:
                header = lines[0].split("=", 1)
                if len(header) < 2 or not header[1].strip():
                    _fail_bpa(
                        "gold.measure-expression-missing",
                        f"{path}: measure {name} has no expression",
                        path,
                    )
                if not _property(lines, "formatString"):
                    _fail_bpa(
                        "gold.measure-format-missing",
                        f"{path}: measure {name} has no formatString",
                        path,
                    )
    date_table = next((c for p, c in tables.items() if p.endswith("/tables/dim_date.tmdl")), None)
    if date_table is not None:
        keyed = [
            name
            for kind, name, lines in _objects(date_table)
            if kind == "column"
            and _property(lines, "isKey") is not None
            and (_property(lines, "dataType") or "").casefold() == "datetime"
        ]
        if "\tdataCategory: Time" not in date_table or len(keyed) != 1:
            _fail_bpa(
                "gold.date-table-not-marked",
                (
                    "dim_date must carry dataCategory: Time and exactly one DateTime isKey "
                    "column, or Power BI does not treat it as a date table"
                ),
                "dim_date",
            )
        month = next(
            (lines for kind, name, lines in _objects(date_table) if name == "month_name"), None
        )
        if month is not None and _property(month, "sortByColumn") is None:
            _fail_bpa(
                "gold.calendar-unsorted",
                "dim_date.month_name has no sortByColumn, so months sort alphabetically",
                "dim_date",
            )
    for path, content in artifacts.items():
        if path.endswith("/definition/relationships.tmdl"):
            _assert_relationship_types(path, content, column_types)


def _assert_relationship_types(
    path: str, content: str, column_types: dict[tuple[str, str], str]
) -> None:
    """Direct Lake refuses, and DirectQuery silently casts, a join across types.

    Active relationships only. An inactive edge with mismatched types exists today where
    a #794 unproven key fell back to a non-key column; blocking it would fail hubs whose
    model loads and answers correctly through its active paths, so it is left to the
    post-deploy BPA run, which reports every relationship.
    """
    for block in content.split("\nrelationship "):
        if "\tisActive: false" in block:
            continue
        ends: dict[str, tuple[str, str]] = {}
        for line in block.splitlines():
            match = _RELATIONSHIP_END.match(line)
            if match is not None:
                ends[match.group("side")] = (
                    match.group("table").strip("'"),
                    match.group("column").strip("'"),
                )
        if set(ends) != {"from", "to"}:
            continue
        left, right = column_types.get(ends["from"]), column_types.get(ends["to"])
        if left and right and left != right:
            _fail_bpa(
                "gold.relationship-type-mismatch",
                (
                    f"{path}: {'.'.join(ends['from'])} ({left}) joins "
                    f"{'.'.join(ends['to'])} ({right}); relationship columns must share a "
                    "data type"
                ),
                path,
            )


def _assert_discourages_implicit_measures(
    artifacts: dict[str, str],
    calculation_groups: dict[str, str],
) -> None:
    """`DiscourageImplicitMeasures` is a precondition for creating any calculation group."""
    models = {path: content for path, content in artifacts.items() if path.endswith("/model.tmdl")}
    for path, content in models.items():
        if "discourageImplicitMeasures" not in content:
            group = sorted(calculation_groups)[0]
            raise GoldContractError(
                "gold.implicit-measures-not-discouraged",
                (
                    f"{path} emits a calculation group ({group}) without "
                    "discourageImplicitMeasures, which the engine requires before it "
                    "will create one"
                ),
                rule_id=_RULE,
                resource_uri=path,
            )
