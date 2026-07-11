# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Integration tests for the import-tmdl command and orchestration."""

import zipfile
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.import_tmdl import (
    detect_input_type,
    find_definition_dirs,
    generate_concept_mapping,
    generate_engineering_pack,
    run_import_tmdl,
)


# ---------------------------------------------------------------------------
# Test fixtures — synthetic TMDL content
# ---------------------------------------------------------------------------

MODEL_TMDL = """\
compatibilityLevel: 1604
defaultMode: directLake
culture: en-US
"""

TABLE_CUSTOMER = """\
table d_Customer
\tlineageTag: cust-001

\tcolumn CustomerKey
\t\tdataType: int64
\t\tsourceColumn: CustomerKey

\tcolumn CustomerName
\t\tdataType: string
\t\tsourceColumn: Name

\tpartition CustomerData
\t\tmode: directLake
\t\ttype: entity
"""

TABLE_SALES = """\
table f_Sales
\tlineageTag: sales-001

\tcolumn Amount
\t\tdataType: double
\t\tformatString: #,##0.00
\t\tsourceColumn: SalesAmount

\tcolumn CustomerKey
\t\tdataType: int64
\t\tsourceColumn: FK_Customer

\tmeasure TotalSales = SUM(f_Sales[Amount])
\t\tformatString: #,##0.00

\tpartition SalesData
\t\tmode: directLake
\t\ttype: entity
"""

RELATIONSHIPS_TMDL = """\
relationship rel_001
\tfromTable: f_Sales
\tfromColumn: CustomerKey
\ttoTable: d_Customer
\ttoColumn: CustomerKey
\tfromCardinality: many
\ttoCardinality: one
"""


def _create_semantic_model(base: Path, model_name: str = "TestModel") -> Path:
    """Create a synthetic SemanticModel folder structure."""
    sm_dir = base / f"{model_name}.SemanticModel"
    def_dir = sm_dir / "definition"
    tables_dir = def_dir / "tables"
    tables_dir.mkdir(parents=True)

    (def_dir / "model.tmdl").write_text(MODEL_TMDL, encoding="utf-8")
    (tables_dir / "d_Customer.tmdl").write_text(TABLE_CUSTOMER, encoding="utf-8")
    (tables_dir / "f_Sales.tmdl").write_text(TABLE_SALES, encoding="utf-8")
    (def_dir / "relationships.tmdl").write_text(RELATIONSHIPS_TMDL, encoding="utf-8")

    return sm_dir


def _create_zip(base: Path, model_name: str = "TestModel") -> Path:
    """Create a ZIP containing a synthetic SemanticModel."""
    sm_dir = _create_semantic_model(base / "content", model_name)
    zip_path = base / f"{model_name}.zip"

    with zipfile.ZipFile(zip_path, "w") as zf:
        for file in sm_dir.rglob("*"):
            if file.is_file():
                arcname = file.relative_to(base / "content")
                zf.write(file, arcname)

    return zip_path


# ---------------------------------------------------------------------------
# detect_input_type tests
# ---------------------------------------------------------------------------


class TestDetectInputType:
    def test_detect_zip(self, tmp_path):
        zip_path = _create_zip(tmp_path)
        assert detect_input_type(zip_path) == "zip"

    def test_detect_folder(self, tmp_path):
        sm_dir = _create_semantic_model(tmp_path)
        assert detect_input_type(sm_dir) == "folder"

    def test_detect_tmdl_file(self, tmp_path):
        tmdl_file = tmp_path / "test.tmdl"
        tmdl_file.write_text(TABLE_CUSTOMER, encoding="utf-8")
        assert detect_input_type(tmdl_file) == "file"

    def test_nonexistent_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            detect_input_type(tmp_path / "nonexistent")


# ---------------------------------------------------------------------------
# find_definition_dirs tests
# ---------------------------------------------------------------------------


class TestFindDefinitionDirs:
    def test_finds_definition_dir(self, tmp_path):
        _create_semantic_model(tmp_path)
        dirs = find_definition_dirs(tmp_path)
        assert len(dirs) == 1
        assert dirs[0].name == "definition"
        assert (dirs[0] / "model.tmdl").exists()

    def test_direct_definition_dir(self, tmp_path):
        sm_dir = _create_semantic_model(tmp_path)
        def_dir = sm_dir / "definition"
        dirs = find_definition_dirs(def_dir)
        assert len(dirs) == 1
        assert dirs[0] == def_dir

    def test_multiple_models(self, tmp_path):
        _create_semantic_model(tmp_path, "ModelA")
        _create_semantic_model(tmp_path, "ModelB")
        dirs = find_definition_dirs(tmp_path)
        assert len(dirs) == 2


# ---------------------------------------------------------------------------
# Engineering pack generation tests
# ---------------------------------------------------------------------------


class TestEngineeringPack:
    def test_pack_contains_sections(self, tmp_path):
        sm_dir = _create_semantic_model(tmp_path)
        from kairos_ontology.core.tmdl_parser import parse_model_folder

        model = parse_model_folder(sm_dir / "definition")
        pack = generate_engineering_pack(model, "test/source")

        assert "# TestModel — Ontology Engineering Pack" in pack
        assert "## Global Inventory" in pack
        assert "Tables: 2" in pack
        assert "## Table Summary" in pack
        assert "## Table and Column Inventory" in pack
        assert "## Relationships (Ontology Edges)" in pack
        assert "d_Customer" in pack
        assert "f_Sales" in pack
        assert "TotalSales" in pack

    def test_pack_shows_relationship(self, tmp_path):
        sm_dir = _create_semantic_model(tmp_path)
        from kairos_ontology.core.tmdl_parser import parse_model_folder

        model = parse_model_folder(sm_dir / "definition")
        pack = generate_engineering_pack(model)

        assert "f_Sales.CustomerKey → d_Customer.CustomerKey" in pack
        assert "many-to-one" in pack


# ---------------------------------------------------------------------------
# Concept mapping generation tests
# ---------------------------------------------------------------------------


class TestConceptMapping:
    def test_yaml_is_valid(self, tmp_path):
        sm_dir = _create_semantic_model(tmp_path)
        from kairos_ontology.core.tmdl_parser import parse_model_folder

        model = parse_model_folder(sm_dir / "definition")
        mapping_str = generate_concept_mapping(model)

        # Strip comment header for parsing
        data = yaml.safe_load(mapping_str)
        assert data is not None
        assert data["schema_version"] == "1"
        assert data["model_name"] == "TestModel"
        assert len(data["tables"]) == 2
        assert len(data["relationships"]) == 1

    def test_table_fields(self, tmp_path):
        sm_dir = _create_semantic_model(tmp_path)
        from kairos_ontology.core.tmdl_parser import parse_model_folder

        model = parse_model_folder(sm_dir / "definition")
        mapping_str = generate_concept_mapping(model)
        data = yaml.safe_load(mapping_str)

        customer = next(t for t in data["tables"] if t["tmdl_name"] == "d_Customer")
        assert customer["type"] == "dimension"
        assert "CustomerKey" in customer["columns"]
        assert customer["domain"] == ""
        assert customer["measures"] == []
        assert customer["reference_model_match"] == ""
        assert customer["action"] == ""

        sales = next(t for t in data["tables"] if t["tmdl_name"] == "f_Sales")
        assert sales["measures"][0]["name"] == "TotalSales"

    def test_relationship_fields(self, tmp_path):
        sm_dir = _create_semantic_model(tmp_path)
        from kairos_ontology.core.tmdl_parser import parse_model_folder

        model = parse_model_folder(sm_dir / "definition")
        mapping_str = generate_concept_mapping(model)
        data = yaml.safe_load(mapping_str)

        rel = data["relationships"][0]
        assert rel["from"] == "f_Sales.CustomerKey"
        assert rel["to"] == "d_Customer.CustomerKey"
        assert rel["cardinality"] == "many-to-one"
        assert rel["domain"] == ""


# ---------------------------------------------------------------------------
# Full pipeline (run_import_tmdl) tests
# ---------------------------------------------------------------------------


class TestRunImportTmdl:
    def test_from_folder(self, tmp_path):
        sm_dir = _create_semantic_model(tmp_path / "input")
        output = tmp_path / "output"

        files = run_import_tmdl(sm_dir, output)
        assert len(files) == 2
        assert any("engineering-pack.md" in str(f) for f in files)
        assert any("concept-mapping.yaml" in str(f) for f in files)
        assert all(f.exists() for f in files)

    def test_from_zip(self, tmp_path):
        zip_path = _create_zip(tmp_path / "zips")
        output = tmp_path / "output"

        files = run_import_tmdl(zip_path, output)
        assert len(files) == 2
        assert all(f.exists() for f in files)

    def test_from_single_file(self, tmp_path):
        tmdl_file = tmp_path / "tables.tmdl"
        tmdl_file.write_text(TABLE_CUSTOMER + "\n" + TABLE_SALES, encoding="utf-8")
        output = tmp_path / "output"

        files = run_import_tmdl(tmdl_file, output)
        assert len(files) == 2
        assert any("engineering-pack.md" in str(f) for f in files)

    def test_output_dir_created(self, tmp_path):
        sm_dir = _create_semantic_model(tmp_path / "input")
        output = tmp_path / "deep" / "nested" / "output"

        files = run_import_tmdl(sm_dir, output)
        assert output.exists()
        assert len(files) == 2

    def test_multiple_models_in_folder(self, tmp_path):
        base = tmp_path / "input"
        _create_semantic_model(base, "ModelA")
        _create_semantic_model(base, "ModelB")
        output = tmp_path / "output"

        files = run_import_tmdl(base, output)
        assert len(files) == 4  # 2 files per model


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


class TestCLI:
    def test_cli_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["import-tmdl", "--help"])
        assert result.exit_code == 0
        assert "Engineering Pack" in result.output

    def test_cli_from_folder(self, tmp_path):
        sm_dir = _create_semantic_model(tmp_path / "input")
        output = tmp_path / "output"
        runner = CliRunner()

        result = runner.invoke(cli, [
            "import-tmdl", str(sm_dir), "--output", str(output)
        ])
        assert result.exit_code == 0
        assert "Generated 2 file(s)" in result.output

    def test_cli_nonexistent_source(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["import-tmdl", "/nonexistent/path"])
        assert result.exit_code != 0
