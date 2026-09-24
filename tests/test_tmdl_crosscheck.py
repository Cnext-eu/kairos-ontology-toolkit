# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The TMDL parser cross-checked against the TOM SDK (issue #879).

The comparison logic is tested against synthetic validator payloads, so the suite runs
everywhere. One test at the bottom drives the real SDK and is skipped without ``dotnet``,
matching this suite's existing pattern — because a cross-check whose only evidence is a
mock of the thing it is checking would be checking nothing.
"""

from __future__ import annotations

import shutil

import pytest

from kairos_ontology.core.tmdl_crosscheck import (
    STATUS_AGREED,
    STATUS_DISAGREED,
    STATUS_UNAVAILABLE,
    crosscheck_parsed_model,
    render_crosscheck_note,
)
from kairos_ontology.core.tmdl_parser import (
    TmdlColumn,
    TmdlMeasure,
    TmdlModel,
    TmdlRelationship,
    TmdlTable,
)

_HAS_DOTNET = shutil.which("dotnet") is not None


def _table(name, *, columns=0, measures=0):
    table = TmdlTable(name=name)
    table.columns = [TmdlColumn(name=f"c{i}") for i in range(columns)]
    table.measures = [TmdlMeasure(name=f"m{i}") for i in range(measures)]
    return table


def _model(*tables, relationships=0):
    model = TmdlModel(name="Model")
    model.tables = list(tables)
    model.relationships = [TmdlRelationship(name=f"r{i}") for i in range(relationships)]
    return model


def _payload(*tables, relationship_count=0):
    return {
        "status": "pass",
        "table_count": len(tables),
        "tables": list(tables),
        "relationship_count": relationship_count,
    }


def _tom(name, *, columns=0, measures=0):
    return {"name": name, "column_count": columns, "measure_count": measures}


@pytest.fixture
def stub_sdk(monkeypatch):
    """Replace the subprocess round-trip with a payload the test controls."""

    def _install(payload):
        # Patched on the defining module, because crosscheck_parsed_model imports it
        # inside the function body -- the import is deferred so that core.tmdl_crosscheck
        # does not pull the projections package in at module scope.
        monkeypatch.setattr(
            "kairos_ontology.core.projections.dbt.tmdl_validate.inspect_tmdl_folder",
            lambda _folder: payload,
        )

    return _install


class TestTheTwoReadingsAgree:
    def test_identical_inventories_report_agreed(self, tmp_path, stub_sdk):
        stub_sdk(_payload(_tom("Sales", columns=4, measures=2), relationship_count=1))

        report = crosscheck_parsed_model(
            _model(_table("Sales", columns=4, measures=2), relationships=1), tmp_path
        )

        assert report.status == STATUS_AGREED
        assert report.findings == ()

    def test_a_case_difference_in_a_table_name_is_not_a_finding(self, tmp_path, stub_sdk):
        """TMDL does not promise the name and the filename agree on case.

        Reporting that as a discrepancy would have the cross-check crying wolf on its
        first run, which is how a check gets switched off.
        """
        stub_sdk(_payload(_tom("SALES", columns=1)))

        assert crosscheck_parsed_model(_model(_table("Sales", columns=1)), tmp_path).status == (
            STATUS_AGREED
        )

    def test_reading_more_than_the_sdk_on_a_shared_table_is_not_reported(
        self, tmp_path, stub_sdk
    ):
        """Only a shortfall matters. The parser is the reader; this warns when it missed."""
        stub_sdk(_payload(_tom("Sales", columns=2, measures=1)))

        report = crosscheck_parsed_model(_model(_table("Sales", columns=5, measures=9)), tmp_path)

        assert report.status == STATUS_AGREED


class TestTheTwoReadingsDiffer:
    def test_a_table_the_parser_never_saw_is_named(self, tmp_path, stub_sdk):
        """The flat-layout case: the parser read zero tables from files it could see."""
        stub_sdk(_payload(_tom("Sales"), _tom("Calendar")))

        report = crosscheck_parsed_model(_model(_table("Sales")), tmp_path)

        assert report.disagreed
        assert [f.kind for f in report.findings] == ["tables-missing"]
        assert "Calendar" in report.findings[0].detail

    def test_a_table_only_the_parser_saw_is_named(self, tmp_path, stub_sdk):
        stub_sdk(_payload(_tom("Sales")))

        report = crosscheck_parsed_model(_model(_table("Sales"), _table("Ghost")), tmp_path)

        assert [f.kind for f in report.findings] == ["tables-extra"]
        assert "Ghost" in report.findings[0].detail

    def test_measures_read_short_are_reported_with_both_counts(self, tmp_path, stub_sdk):
        """The DAX-fence case: 53 of 59 measures reached the pack definition-free."""
        stub_sdk(_payload(_tom("Sales", measures=59)))

        report = crosscheck_parsed_model(_model(_table("Sales", measures=6)), tmp_path)

        assert [f.kind for f in report.findings] == ["measures-missing"]
        assert "6 of 59" in report.findings[0].detail

    def test_columns_read_short_are_reported(self, tmp_path, stub_sdk):
        stub_sdk(_payload(_tom("Sales", columns=40)))

        report = crosscheck_parsed_model(_model(_table("Sales", columns=3)), tmp_path)

        assert [f.kind for f in report.findings] == ["columns-missing"]

    def test_relationships_read_short_are_reported(self, tmp_path, stub_sdk):
        stub_sdk(_payload(_tom("Sales"), relationship_count=12))

        report = crosscheck_parsed_model(_model(_table("Sales"), relationships=2), tmp_path)

        assert [f.kind for f in report.findings] == ["relationships-missing"]

    def test_every_dimension_is_reported_not_only_the_first(self, tmp_path, stub_sdk):
        stub_sdk(
            _payload(_tom("Sales", columns=9, measures=9), _tom("Calendar"), relationship_count=3)
        )

        report = crosscheck_parsed_model(
            _model(_table("Sales", columns=1, measures=1), _table("Ghost")), tmp_path
        )

        assert {f.kind for f in report.findings} == {
            "tables-missing",
            "tables-extra",
            "measures-missing",
            "columns-missing",
            "relationships-missing",
        }


class TestTheSdkRejectsTheExport:
    def test_a_rejection_is_a_disagreement_in_its_own_right(self, tmp_path, stub_sdk):
        """Our parser read it happily; the engine Power BI uses will not open it."""
        stub_sdk(
            {
                "status": "fail",
                "error_type": "TmdlSerializationException",
                "message": "Cannot resolve all the paths while de-serializing Database.",
            }
        )

        report = crosscheck_parsed_model(_model(_table("Sales")), tmp_path)

        assert report.disagreed
        assert [f.kind for f in report.findings] == ["tom-rejected"]
        assert "Power BI Desktop will refuse it too" in report.findings[0].detail

    def test_a_very_long_rejection_is_truncated(self, tmp_path, stub_sdk):
        """On one real export the dangling-link list ran to four thousand characters,
        naming the same fact about thirty-four tables. A warning nobody can read is a
        warning nobody reads.
        """
        stub_sdk({"status": "fail", "error_type": "TmdlSerializationException", "message": "x" * 5000})

        detail = crosscheck_parsed_model(_model(), tmp_path).findings[0].detail

        assert len(detail) < 600
        assert detail.endswith("(message truncated)")


class TestNoSecondOpinionIsNotADisagreement:
    def test_no_dotnet_reports_unavailable(self, tmp_path, stub_sdk):
        stub_sdk({"status": "unavailable", "message": "dotnet SDK not found on PATH"})

        report = crosscheck_parsed_model(_model(_table("Sales")), tmp_path)

        assert report.status == STATUS_UNAVAILABLE
        assert not report.disagreed
        assert "dotnet" in report.reason

    def test_a_payload_with_a_count_but_no_inventory_is_unavailable(self, tmp_path, stub_sdk):
        """An older build of the tool. Findings nobody can attribute are worse than none."""
        stub_sdk({"status": "pass", "table_count": 7})

        report = crosscheck_parsed_model(_model(), tmp_path)

        assert report.status == STATUS_UNAVAILABLE

    def test_an_unrecognised_status_is_unavailable_not_a_failure(self, tmp_path, stub_sdk):
        stub_sdk({"status": "something-new"})

        assert crosscheck_parsed_model(_model(), tmp_path).status == STATUS_UNAVAILABLE


class TestTheNoteInTheEngineeringPack:
    def test_agreement_renders_nothing(self, tmp_path, stub_sdk):
        """So an unaffected pack is byte-identical to what the previous version wrote."""
        stub_sdk(_payload(_tom("Sales")))

        report = crosscheck_parsed_model(_model(_table("Sales")), tmp_path)

        assert render_crosscheck_note(report, "Model") == ""

    def test_an_unavailable_check_renders_nothing(self, tmp_path, stub_sdk):
        """Absence of a second opinion is not evidence of a problem."""
        stub_sdk({"status": "unavailable", "message": "no dotnet"})

        report = crosscheck_parsed_model(_model(), tmp_path)

        assert render_crosscheck_note(report, "Model") == ""

    def test_a_disagreement_says_which_reading_the_pack_reflects(self, tmp_path, stub_sdk):
        """The pack is still the parser's output; the note must not imply otherwise."""
        stub_sdk(_payload(_tom("Sales"), _tom("Calendar")))

        note = render_crosscheck_note(crosscheck_parsed_model(_model(_table("Sales")), tmp_path), "M")

        assert "this import's" in note
        assert "Calendar" in note

    def test_the_pack_carries_the_note_above_the_inventory_it_qualifies(self, tmp_path):
        """Read before the numbers, not after them."""
        from kairos_ontology.core.import_tmdl import generate_engineering_pack

        pack = generate_engineering_pack(
            _model(_table("Sales")), "src", "## ⚠ Cross-check: something is missing"
        )

        assert pack.index("Cross-check") < pack.index("## Global Inventory")

    def test_the_note_is_separated_from_the_next_heading(self, tmp_path):
        """#905: splitlines() ate the note's trailing blank line, so it ran into the
        heading below it."""
        from kairos_ontology.core.import_tmdl import generate_engineering_pack

        note = render_crosscheck_note(crosscheck_parsed_model(_model(_table("Sales")), tmp_path), "M")
        pack = generate_engineering_pack(_model(_table("Sales")), "src", note or "## Note\ntext\n")

        assert "\n\n## Global Inventory" in pack

    def test_a_pack_with_no_note_is_unchanged(self, tmp_path):
        from kairos_ontology.core.import_tmdl import generate_engineering_pack

        assert "Cross-check" not in generate_engineering_pack(_model(_table("Sales")), "src")


@pytest.mark.skipif(not _HAS_DOTNET, reason="dotnet SDK not installed; the cross-check is best-effort")
class TestAgainstTheRealSdk:
    """One end-to-end pass, because a cross-check evidenced only by a mock of the thing
    it cross-checks has evidenced nothing.
    """

    def test_a_flat_layout_export_agrees_with_the_engine(self, tmp_path):
        """The shape that read as zero tables before the parser was fixed."""
        (tmp_path / "database.tmdl").write_text(
            'database\n\tcompatibilityLevel: 1550\n', encoding="utf-8"
        )
        (tmp_path / "model.tmdl").write_text(
            "model Model\n"
            "\tculture: en-US\n"
            "\tdefaultPowerBIDataSourceVersion: powerBI_V3\n"
            "\n"
            "\tref table Sales\n",
            encoding="utf-8",
        )
        (tmp_path / "Sales.tmdl").write_text(
            "table Sales\n"
            "\n"
            "\tcolumn Amount\n"
            "\t\tdataType: double\n"
            "\t\tsourceColumn: Amount\n"
            "\n"
            "\tpartition Sales = m\n"
            "\t\tmode: import\n"
            "\t\tsource = \n"
            "\t\t\t\tlet Source = #table({}, {}) in Source\n",
            encoding="utf-8",
        )

        from kairos_ontology.core.tmdl_parser import parse_model_folder

        model = parse_model_folder(tmp_path)
        report = crosscheck_parsed_model(model, tmp_path)

        # If the SDK cannot run on this machine the cross-check says so rather than
        # inventing a verdict, and that is itself the contract worth asserting.
        # UNAVAILABLE is tolerated because dotnet on PATH does not guarantee the SDK
        # can initialise here (see tmdl_validate's TypeInitializationException note);
        # what must never happen is a verdict invented without it.
        assert report.status in {STATUS_AGREED, STATUS_UNAVAILABLE}
        assert [t.name for t in model.tables] == ["Sales"]
        if report.status == STATUS_AGREED:
            assert report.findings == ()

    def test_an_export_missing_its_table_files_is_rejected_by_the_engine(self, tmp_path):
        """Measured on a real export: the parser reported a model with zero tables and
        thirty-three relationships, which downstream cannot tell from a model that
        genuinely has none. The engine says the export will not open at all.
        """
        (tmp_path / "database.tmdl").write_text(
            "database\n\tcompatibilityLevel: 1550\n", encoding="utf-8"
        )
        (tmp_path / "model.tmdl").write_text(
            "model Model\n\tculture: en-US\n\n\tref table Sales\n", encoding="utf-8"
        )
        (tmp_path / "relationships.tmdl").write_text(
            "relationship abc\n"
            "\tfromColumn: Sales.Key\n"
            "\ttoColumn: Calendar.Key\n",
            encoding="utf-8",
        )

        from kairos_ontology.core.tmdl_parser import parse_model_folder

        model = parse_model_folder(tmp_path)
        report = crosscheck_parsed_model(model, tmp_path)

        assert model.tables == []
        assert report.status in {STATUS_DISAGREED, STATUS_UNAVAILABLE}
        if report.disagreed:
            assert [f.kind for f in report.findings] == ["tom-rejected"]
