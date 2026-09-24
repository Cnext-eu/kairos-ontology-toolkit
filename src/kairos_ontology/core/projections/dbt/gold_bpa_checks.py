# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Compile-time BPA checks over a shaped Gold product (DD-238, issue #980).

The only semantic gate on the model used to be ``gold_assert``, which runs at render
time, in ``emit-gold`` and ``package-powerbi-release``. ``compile --check`` shapes Gold
but never renders it, so an author iterating on the design never saw a problem the
profile treats as a real defect. These run during shaping, so they appear in
``compile --check`` with stable codes.

Kept high-precision (DD-163). The two blocking checks only judge bracketed names the
measure *declares* -- a column dependency or a measure dependency -- after string
literals and comments are removed, so they cannot misread free text. Everything else
is a warning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .bpa_profile import BpaIgnore
from .gold_specs import GoldContractError, GoldMeasureSpec, GoldTableSpec
from .policy_specs import CanonicalTypeKind

_RULE = "DD-238-bpa-profile"

#: DAX string literals (a doubled quote escapes one) and both comment forms. Removed
#: before scanning so `"[not a column]"` or `// [old]` is never read as a reference.
_DAX_STRING = re.compile(r'"(?:[^"]|"")*"')
_DAX_COMMENT = re.compile(r"//[^\n]*|--[^\n]*|/\*.*?\*/", re.DOTALL)

#: A bracketed name, with the table immediately before it when there is one. No
#: whitespace is allowed between the two: `RETURN [Total]` is a keyword followed by an
#: unqualified reference, not a table named RETURN.
_DAX_BRACKET = re.compile(
    r"(?P<table>'(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_]*)?\[(?P<name>[^\]]+)\]"
)

#: The upstream USE_THE_DIVIDE_FUNCTION_FOR_DIVISION expression, verbatim.
_DAX_DIVISION = re.compile(r"\]\s*\/(?!\/)(?!\*)|\)\s*\/(?!\/)(?!\*)")

#: Rules these checks evaluate, so an exception naming one can be proven stale.
CHECKED_RULES = {
    "DAX_COLUMNS_FULLY_QUALIFIED": "measure",
    "DAX_MEASURES_UNQUALIFIED": "measure",
    "USE_THE_DIVIDE_FUNCTION_FOR_DIVISION": "measure",
    "AVOID_FLOATING_POINT_DATA_TYPES": "column",
    "OBJECTS_WITH_NO_DESCRIPTION": "column",
}


@dataclass(frozen=True, slots=True)
class GoldAdvisory:
    """A non-blocking finding ``compile --check`` reports as a warning."""

    code: str
    message: str
    resource_uri: str = ""


def _scannable(expression: str) -> str:
    return _DAX_COMMENT.sub(" ", _DAX_STRING.sub('""', expression))


def _references(expression: str) -> list[tuple[str, str]]:
    """``(table or "", name)`` for every bracketed reference outside strings and comments."""
    return [
        ((match.group("table") or "").strip("'").replace("''", "'"), match.group("name"))
        for match in _DAX_BRACKET.finditer(_scannable(expression))
    ]


def check_product(
    tables: tuple[GoldTableSpec, ...],
    measures: tuple[GoldMeasureSpec, ...],
    ignores: tuple[BpaIgnore, ...],
) -> tuple[GoldAdvisory, ...]:
    """Raise on a blocking finding; return the warnings; fail a stale exception."""
    ignored = {(item.rule_id, item.kind, item.target.casefold()) for item in ignores}
    found: set[tuple[str, str, str]] = set()

    def suppressed(rule: str, kind: str, target: str) -> bool:
        found.add((rule, kind, target.casefold()))
        return (rule, kind, target.casefold()) in ignored

    by_id = {item.measure_id: item for item in measures}
    advisories: list[GoldAdvisory] = []
    for measure in measures:
        if not measure.emitted:
            continue
        columns = {column.casefold() for _, column in measure.column_dependencies}
        names: set[str] = set()
        for dependency in measure.measure_dependencies:
            other = by_id.get(dependency)
            names.update(
                value.casefold()
                for value in (dependency, other.name if other is not None else "")
                if value
            )
        references = _references(measure.expression)
        unqualified = sorted(
            {name for table, name in references if not table and name.casefold() in columns}
        )
        if unqualified and not suppressed(
            "DAX_COLUMNS_FULLY_QUALIFIED", "measure", measure.measure_id
        ):
            raise GoldContractError(
                "gold.dax-column-unqualified",
                (
                    f"measure {measure.measure_id!r} references column(s) "
                    + ", ".join(f"[{name}]" for name in unqualified)
                    + " without their table; write "
                    + ", ".join(
                        f"{_table_of(measure, name)}[{name}]" for name in unqualified
                    )
                    + " (BPA DAX_COLUMNS_FULLY_QUALIFIED)"
                ),
                rule_id=_RULE,
                resource_uri=measure.resource_uri,
            )
        qualified = sorted(
            {
                f"{table}[{name}]"
                for table, name in references
                if table and name.casefold() in names and name.casefold() not in columns
            }
        )
        if qualified and not suppressed("DAX_MEASURES_UNQUALIFIED", "measure", measure.measure_id):
            raise GoldContractError(
                "gold.dax-measure-qualified",
                (
                    f"measure {measure.measure_id!r} qualifies measure reference(s) "
                    + ", ".join(qualified)
                    + " with a table; reference a measure by its bracketed name alone, so "
                    "it survives a change of home table (BPA DAX_MEASURES_UNQUALIFIED)"
                ),
                rule_id=_RULE,
                resource_uri=measure.resource_uri,
            )
        if _DAX_DIVISION.search(_scannable(measure.expression)) and not suppressed(
            "USE_THE_DIVIDE_FUNCTION_FOR_DIVISION", "measure", measure.measure_id
        ):
            advisories.append(
                GoldAdvisory(
                    "gold.dax-division-operator",
                    (
                        f"measure {measure.measure_id!r} divides with '/'; DIVIDE() returns "
                        "blank instead of an error when the denominator is zero (BPA "
                        "USE_THE_DIVIDE_FUNCTION_FOR_DIVISION)"
                    ),
                    measure.resource_uri,
                )
            )

    for table in tables:
        floats = [
            column.name
            for column in table.columns
            if column.canonical_type.kind is CanonicalTypeKind.FLOAT64
            and not suppressed(
                "AVOID_FLOATING_POINT_DATA_TYPES", "column", f"{table.name}.{column.name}"
            )
        ]
        if floats:
            advisories.append(
                GoldAdvisory(
                    "gold.float-column",
                    (
                        f"{table.name}: {', '.join(floats)} render as floating point "
                        "(Double); a decimal type stores exact values and compresses better "
                        "(BPA AVOID_FLOATING_POINT_DATA_TYPES)"
                    ),
                    table.resource_uri,
                )
            )
        # One finding per table, not per column: a hub with no rdfs:comment anywhere
        # would otherwise get a warning per column and learn to ignore all of them.
        undescribed = [
            column.name
            for column in table.columns
            if not column.hidden
            and not column.comment.strip()
            and not suppressed(
                "OBJECTS_WITH_NO_DESCRIPTION", "column", f"{table.name}.{column.name}"
            )
        ]
        if undescribed:
            advisories.append(
                GoldAdvisory(
                    "gold.description-missing",
                    (
                        f"{table.name}: visible column(s) {', '.join(undescribed)} have no "
                        "description; add an rdfs:comment to the ontology property, which is "
                        "what a report author reads in the field list (BPA "
                        "OBJECTS_WITH_NO_DESCRIPTION)"
                    ),
                    table.resource_uri,
                )
            )

    stale = sorted(
        (
            item
            for item in ignores
            # Only where the compiler evaluates that rule for that kind of object: an
            # exception on a table, say, may excuse a finding only the post-deploy run makes.
            if CHECKED_RULES.get(item.rule_id) == item.kind
            and (item.rule_id, item.kind, item.target.casefold()) not in found
        ),
        key=lambda item: (item.rule_id, item.kind, item.target),
    )
    if stale:
        item = stale[0]
        raise GoldContractError(
            "gold.bpa-ignore-unused",
            (
                f"bpaIgnoreRule {item.source!r} excuses a finding the compiler does not make: "
                f"{item.kind} {item.target!r} does not break {item.rule_id}. Remove it, so "
                "the exception cannot outlive the reason it was written"
            ),
            rule_id=_RULE,
        )
    return tuple(advisories)


def _table_of(measure: GoldMeasureSpec, column: str) -> str:
    for table, name in measure.column_dependencies:
        if name.casefold() == column.casefold():
            return table
    return measure.home_table
