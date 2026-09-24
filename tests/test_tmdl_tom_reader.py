# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""import-tmdl reads Power BI models through the TOM SDK (#879, DD-237).

The mapping from the SDK's reading onto the parser dataclasses is tested against a
synthetic payload, so it runs everywhere. The rest drives the real SDK and needs
``dotnet``: it pins the three export shapes the hand-rolled parser got wrong (#874, #875,
#807) and what happens to an export Power BI itself would refuse.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from kairos_ontology.core import tmdl_tom_reader
from kairos_ontology.core.tmdl_tom_reader import (
    TmdlRejectedError,
    TomUnavailableError,
    _to_model,
    read_model_folder,
    read_single_table_file,
)

requires_dotnet = pytest.mark.skipif(
    shutil.which("dotnet") is None, reason="needs the .NET SDK for the TOM reader"
)


def _expect_rejection(call):
    """Assert TOM refuses the export -- or skip where the SDK cannot report it.

    Same precedent as test_tmdl_validate's _skip_if_sdk_unavailable: on some Linux
    runners the SDK's native hosting fails to initialise while raising its own content
    error, which is an environment limitation, not a reader bug.
    """
    try:
        call()
    except TmdlRejectedError as exc:
        return exc
    except TomUnavailableError as exc:
        pytest.skip(f"TOM SDK could not report the rejection here: {exc}")
    raise AssertionError("expected the TOM SDK to refuse this export")

_PAYLOAD = {
    "status": "pass",
    "model": {
        "compatibility_level": 1604,
        "default_mode": "DirectLake",
        "tables": [
            {
                "name": "f_Sales",
                "lineage_tag": "t1",
                "description": "Sales facts.",
                "is_hidden": False,
                "annotations": {"Kairos_Binding": "sales"},
                "columns": [
                    {"name": "Amount", "data_type": "Double", "format_string": "0.00",
                     "source_column": "amt", "is_hidden": False, "is_key": False},
                    {"name": "When", "data_type": "DateTime", "is_hidden": True},
                ],
                "measures": [{"name": "Total", "expression": "SUM(f_Sales[Amount])"}],
                "partitions": [{"name": "p", "mode": "DirectLake", "source_type": "Entity"}],
            }
        ],
        "relationships": [
            {"name": "r", "from_table": "f_Sales", "from_column": "Key", "to_table": "d",
             "to_column": "Key", "from_cardinality": "Many", "to_cardinality": "One",
             "cross_filtering": "OneDirection", "is_active": False}
        ],
    },
}


class TestMapping:
    """TOM's enum names become the TMDL spellings every downstream artifact carries."""

    def test_values_are_mapped_to_tmdl_spellings(self):
        model = _to_model(_PAYLOAD, "Acme")
        (table,) = model.tables
        assert model.name == "Acme" and model.default_mode == "directLake"
        assert [c.data_type for c in table.columns] == ["double", "dateTime"]
        assert table.partitions[0].mode == "directlake"
        assert table.partitions[0].source_type == "entity"
        assert table.annotations == {"Kairos_Binding": "sales"}
        (rel,) = model.relationships
        assert (rel.from_cardinality, rel.to_cardinality, rel.is_active) == ("many", "one", False)

    def test_no_dotnet_is_an_actionable_error_not_a_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tmdl_tom_reader.shutil, "which", lambda _name: None)
        with pytest.raises(TomUnavailableError, match=".NET 8 SDK"):
            read_model_folder(tmp_path)

    def test_the_cli_reports_a_missing_sdk_cleanly(self, tmp_path, monkeypatch):
        from click.testing import CliRunner

        from kairos_ontology.cli.main import cli

        folder = tmp_path / "M.SemanticModel" / "definition"
        folder.mkdir(parents=True)
        (folder / "model.tmdl").write_text("model Model\n", encoding="utf-8")
        monkeypatch.setattr(tmdl_tom_reader.shutil, "which", lambda _name: None)

        result = CliRunner().invoke(
            cli, ["import-tmdl", str(tmp_path / "M.SemanticModel"), "-o", str(tmp_path / "o")]
        )
        assert result.exit_code == 1
        assert ".NET 8 SDK" in result.output


def _write(folder: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return folder


_TABLE = (
    "table Sales\n"
    "\tmeasure Total = ```\n"
    "\t\t\tCALCULATE(\n"
    "\t\t\t    SUM(Sales[Amount])\n"
    "\t\t\t)\n"
    "\t\t\t```\n"
    "\n"
    "\tcolumn Amount\n"
    "\t\tdataType: double\n"
    "\t\tsourceColumn: amt\n"
    "\n"
    "\tpartition SalesData = m\n"
    "\t\tmode: import\n"
    "\t\tsource = 1\n"
)


@requires_dotnet
class TestAgainstTheRealSdk:
    def test_fenced_dax_is_the_expression_not_the_fence(self, tmp_path):
        """#875: 53 of 59 measures reached the pack with the fence as their expression."""
        folder = _write(tmp_path / "M" / "definition", {
            "model.tmdl": "model Model\n", "tables/Sales.tmdl": _TABLE,
        })
        (measure,) = read_model_folder(folder).tables[0].measures
        assert "```" not in measure.expression
        assert "SUM(Sales[Amount])" in measure.expression

    def test_a_flat_export_is_read(self, tmp_path):
        """#874: table files beside model.tmdl, no tables/ folder -- read as zero tables."""
        folder = _write(tmp_path / "Flat", {"model.tmdl": "model Model\n", "Sales.tmdl": _TABLE})
        model = read_model_folder(folder)
        assert [t.name for t in model.tables] == ["Sales"]
        assert model.name == "Flat"

    def test_a_declared_but_absent_table_is_still_named(self, tmp_path):
        """#807: TOM accepts a dangling `ref table`, so the reader checks model.tmdl itself."""
        folder = _write(tmp_path / "M" / "definition", {
            "model.tmdl": "model Model\n\nref table Sales\nref table 'f Missing'\n",
            "tables/Sales.tmdl": _TABLE,
        })
        assert read_model_folder(folder).unresolved_table_refs == ["f Missing"]

    def test_an_export_tom_refuses_is_an_error_naming_the_engine(self, tmp_path):
        folder = _write(tmp_path / "M" / "definition", {
            "model.tmdl": "model Model\n",
            "tables/Sales.tmdl": _TABLE,
            "relationships.tmdl": (
                "relationship r\n\tfromColumn: Sales.Amount\n\ttoColumn: Ghost.Key\n"
            ),
        })
        exc = _expect_rejection(lambda: read_model_folder(folder))
        assert "Power BI Desktop refuses" in str(exc)

    def test_a_lone_table_file_is_read(self, tmp_path):
        path = tmp_path / "Sales.tmdl"
        path.write_text(_TABLE, encoding="utf-8")
        model = read_single_table_file(path)
        assert model.name == "Sales" and [t.name for t in model.tables] == ["Sales"]

    def test_one_refused_model_does_not_sink_a_batch(self, tmp_path):
        from kairos_ontology.core.import_tmdl import run_import_tmdl

        _write(tmp_path / "in" / "Good.SemanticModel" / "definition", {
            "model.tmdl": "model Model\n", "tables/Sales.tmdl": _TABLE,
        })
        _write(tmp_path / "in" / "Bad.SemanticModel" / "definition", {
            "model.tmdl": "model Model\n",
            "tables/Sales.tmdl": _TABLE,
            "relationships.tmdl": (
                "relationship r\n\tfromColumn: Sales.Amount\n\ttoColumn: Ghost.Key\n"
            ),
        })
        partial: list[str] = []
        _expect_rejection(
            lambda: read_model_folder(tmp_path / "in" / "Bad.SemanticModel" / "definition")
        )

        files = run_import_tmdl(tmp_path / "in", tmp_path / "out", partial)

        assert partial == ["Bad"]
        assert {f.name for f in files} >= {"Good-engineering-pack.md", "Good-concept-mapping.yaml"}
