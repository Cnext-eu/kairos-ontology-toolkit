# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Direct coverage for ``core/evidence_loaders.py``'s concept-mapping scan.

The scan had no test module of its own: it was only exercised indirectly through
``next`` and ``design-landscape``, neither of which ever fed it a row that was
*triaged* without carrying a ``reference_model_match``. That is exactly the case
issue #687 reported, so it is pinned directly here.
"""

from __future__ import annotations

from pathlib import Path

from kairos_ontology.core.evidence_loaders import (
    CONCEPT_MAPPING_ACTIONS,
    scan_concept_mapping_worksheets,
)


def _worksheet(hub: Path, body: str, name: str = "sales-concept-mapping.yaml") -> None:
    bi_dir = hub / "integration" / "discovery" / "bi"
    bi_dir.mkdir(parents=True, exist_ok=True)
    (bi_dir / name).write_text(
        "schema_version: '1'\nmodel_name: Sales\ntables:\n" + body, encoding="utf-8"
    )


def test_no_worksheet_directory_is_not_an_error(tmp_path: Path) -> None:
    scan = scan_concept_mapping_worksheets(tmp_path)
    assert scan.directories_found is False
    assert (scan.tables_total, scan.tables_unfilled, scan.tables_untriaged) == (0, 0, 0)
    assert scan.errors == ()


def test_a_blank_row_is_both_unfilled_and_untriaged(tmp_path: Path) -> None:
    _worksheet(
        tmp_path, "  - tmdl_name: FactSales\n    reference_model_match: ''\n    action: ''\n"
    )
    scan = scan_concept_mapping_worksheets(tmp_path)
    assert (scan.tables_total, scan.tables_unfilled, scan.tables_untriaged) == (1, 1, 1)


def test_skip_is_triaged_even_though_it_never_carries_a_match(tmp_path: Path) -> None:
    """The #687 case: a decided row must leave the backlog, not the evidence count.

    ``skip`` means "not relevant for ontology (e.g. measure-only table)" in the
    worksheet header ``import-tmdl`` itself generates, so an empty
    ``reference_model_match`` is the *correct terminal state* — counting it as
    outstanding work made the number unreachable.
    """
    _worksheet(
        tmp_path,
        "  - tmdl_name: Carrier_RP_Table\n"
        "    reference_model_match: ''\n"
        "    action: skip\n"
        "    notes: Derived responsible-party rollup used for report visuals.\n",
    )
    scan = scan_concept_mapping_worksheets(tmp_path)
    assert scan.tables_untriaged == 0, "a recorded decision is triage"
    assert scan.tables_unfilled == 1, "but it still supplies no BI weight evidence"


def test_new_class_is_triaged_too(tmp_path: Path) -> None:
    _worksheet(
        tmp_path,
        "  - tmdl_name: DimLocalThing\n    reference_model_match: ''\n    action: new_class\n",
    )
    scan = scan_concept_mapping_worksheets(tmp_path)
    assert (scan.tables_unfilled, scan.tables_untriaged) == (1, 0)


def test_every_documented_action_value_counts_as_triaged(tmp_path: Path) -> None:
    # Guards the constant against drifting from import_tmdl.py's generated header.
    assert CONCEPT_MAPPING_ACTIONS == {"use", "specialize", "new_class", "skip"}
    rows = "".join(
        f"  - tmdl_name: T{index}\n    reference_model_match: ''\n    action: {action}\n"
        for index, action in enumerate(sorted(CONCEPT_MAPPING_ACTIONS))
    )
    _worksheet(tmp_path, rows)
    scan = scan_concept_mapping_worksheets(tmp_path)
    assert scan.tables_total == len(CONCEPT_MAPPING_ACTIONS)
    assert scan.tables_untriaged == 0


def test_an_unrecognised_action_still_counts_as_untriaged(tmp_path: Path) -> None:
    """Fail toward reporting work: nothing downstream can act on an unknown value."""
    _worksheet(
        tmp_path, "  - tmdl_name: FactSales\n    reference_model_match: ''\n    action: maybe\n"
    )
    assert scan_concept_mapping_worksheets(tmp_path).tables_untriaged == 1


def test_a_matched_row_is_neither_unfilled_nor_untriaged(tmp_path: Path) -> None:
    _worksheet(
        tmp_path,
        "  - tmdl_name: DimCustomer\n    reference_model_match: 'Party'\n    action: use\n",
    )
    scan = scan_concept_mapping_worksheets(tmp_path)
    assert (scan.tables_total, scan.tables_unfilled, scan.tables_untriaged) == (1, 0, 0)


def test_an_unreadable_worksheet_is_reported_not_raised(tmp_path: Path) -> None:
    bi_dir = tmp_path / "integration" / "discovery" / "bi"
    bi_dir.mkdir(parents=True)
    (bi_dir / "broken-concept-mapping.yaml").write_text("tables: [unclosed\n", encoding="utf-8")
    scan = scan_concept_mapping_worksheets(tmp_path)
    assert len(scan.errors) == 1
    assert scan.tables_total == 0


def test_the_legacy_location_is_scanned_too(tmp_path: Path) -> None:
    legacy = tmp_path / "integration" / "sources"
    legacy.mkdir(parents=True)
    (legacy / "old-concept-mapping.yaml").write_text(
        "tables:\n  - tmdl_name: FactOld\n    reference_model_match: ''\n    action: ''\n",
        encoding="utf-8",
    )
    scan = scan_concept_mapping_worksheets(tmp_path)
    assert scan.directories_found is True
    assert (scan.tables_total, scan.tables_untriaged) == (1, 1)
