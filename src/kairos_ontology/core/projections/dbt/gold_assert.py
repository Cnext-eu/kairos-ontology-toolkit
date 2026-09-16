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
