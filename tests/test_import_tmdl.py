# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Integration tests for the import-tmdl command and orchestration."""

import json
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
    resolve_pbip_pointer,
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


def _create_zip(base: Path, model_name: str = "TestModel", suffix: str = ".zip") -> Path:
    """Create a ZIP containing a synthetic SemanticModel.

    ``suffix`` defaults to ``.zip`` but can be set to ``.pbip`` to build a
    legacy zip-format PBIP archive — the case ``detect_input_type`` already
    handled correctly before issue #387's JSON-pointer-sniffing addition.
    """
    sm_dir = _create_semantic_model(base / "content", model_name)
    zip_path = base / f"{model_name}{suffix}"

    with zipfile.ZipFile(zip_path, "w") as zf:
        for file in sm_dir.rglob("*"):
            if file.is_file():
                arcname = file.relative_to(base / "content")
                zf.write(file, arcname)

    return zip_path


def _create_pbip_pointer(
    base: Path,
    model_name: str = "TestModel",
    include_report: bool = True,
    include_dataset: bool = True,
) -> Path:
    """Create a Fabric git-integration-style ``.pbip`` JSON pointer file.

    Builds the pointer file plus real sibling ``<name>.Report/`` and
    ``<name>.SemanticModel/`` folders under ``base``, mirroring what a modern
    Fabric git-integration PBIP project looks like on disk (issue #387).
    """
    sm_dir = _create_semantic_model(base, model_name)

    report_dir = base / f"{model_name}.Report"
    (report_dir / "definition").mkdir(parents=True, exist_ok=True)
    (report_dir / "definition" / "report.json").write_text("{}", encoding="utf-8")
    (report_dir / ".platform").write_text("{}", encoding="utf-8")

    artifact: dict = {}
    if include_report:
        artifact["report"] = {"path": f"{model_name}.Report"}
    if include_dataset:
        artifact["dataset"] = {"path": sm_dir.name}

    pointer_data = {
        "version": "1.0",
        "artifacts": [artifact],
        "settings": {"enableAutoRecovery": True},
    }
    pointer_path = base / f"{model_name}.pbip"
    pointer_path.write_text(json.dumps(pointer_data), encoding="utf-8")
    return pointer_path


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

    def test_detect_pbip_pointer_file(self, tmp_path):
        """Issue #387: a modern Fabric git-integration .pbip is JSON, not a zip."""
        pointer_path = _create_pbip_pointer(tmp_path)
        assert detect_input_type(pointer_path) == "pointer"

    def test_legacy_zip_format_pbip_is_unaffected(self, tmp_path):
        """Regression: JSON-sniffing must never change legacy zip .pbip handling."""
        zip_pbip_path = _create_zip(tmp_path, suffix=".pbip")
        assert detect_input_type(zip_pbip_path) == "zip"


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

    def test_from_pbip_pointer(self, tmp_path):
        """Issue #387: end-to-end parse of a modern Fabric JSON pointer .pbip."""
        pointer_path = _create_pbip_pointer(tmp_path / "input")
        output = tmp_path / "output"

        files = run_import_tmdl(pointer_path, output)
        assert len(files) == 2
        assert any("engineering-pack.md" in str(f) for f in files)
        assert any("concept-mapping.yaml" in str(f) for f in files)
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

        result = runner.invoke(cli, ["import-tmdl", str(sm_dir), "--output", str(output)])
        assert result.exit_code == 0
        assert "Generated 2 file(s)" in result.output

    def test_cli_nonexistent_source(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["import-tmdl", "/nonexistent/path"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Issue #296 — output is resolved against the hub root, and only the two
# derived artifacts are written
# ---------------------------------------------------------------------------


def _make_hub(root: Path) -> Path:
    """Create a repo root containing a scaffolded-shaped ontology-hub/."""
    hub = root / "ontology-hub"
    (hub / "model" / "ontologies").mkdir(parents=True)
    (hub / "integration" / "discovery" / "bi").mkdir(parents=True)
    return hub


def _bi_dir(hub: Path) -> Path:
    return hub / "integration" / "discovery" / "bi"


class TestHubRootResolution:
    def test_default_output_lands_inside_the_hub_not_at_the_repo_root(self, tmp_path, monkeypatch):
        """The reported bug: run from the repo root, get a stray top-level integration/."""
        hub = _make_hub(tmp_path)
        sm_dir = _create_semantic_model(tmp_path / "raw")
        monkeypatch.chdir(tmp_path)

        result = CliRunner().invoke(cli, ["import-tmdl", str(sm_dir)])

        assert result.exit_code == 0, result.output
        assert sorted(p.name for p in _bi_dir(hub).iterdir()) == [
            "TestModel-concept-mapping.yaml",
            "TestModel-engineering-pack.md",
        ]
        assert not (tmp_path / "integration").exists(), "stray top-level integration/ was created"

    def test_default_output_announces_the_destination_before_writing(self, tmp_path, monkeypatch):
        hub = _make_hub(tmp_path)
        sm_dir = _create_semantic_model(tmp_path / "raw")
        monkeypatch.chdir(tmp_path)

        result = CliRunner().invoke(cli, ["import-tmdl", str(sm_dir)])

        assert "📂 Writing to:" in result.output
        assert str(_bi_dir(hub)) in result.output

    def test_run_from_inside_the_hub_does_not_nest(self, tmp_path, monkeypatch):
        hub = _make_hub(tmp_path)
        sm_dir = _create_semantic_model(tmp_path / "raw")
        monkeypatch.chdir(hub)

        result = CliRunner().invoke(cli, ["import-tmdl", str(sm_dir)])

        assert result.exit_code == 0, result.output
        assert list(_bi_dir(hub).glob("*-engineering-pack.md"))
        assert not (hub / "ontology-hub").exists()

    def test_run_from_a_deep_subdirectory_resolves_upward(self, tmp_path, monkeypatch):
        """From ontology-hub/integration/, a cwd-relative path would produce
        ontology-hub/integration/integration/discovery/bi (DD-064 nesting)."""
        hub = _make_hub(tmp_path)
        sm_dir = _create_semantic_model(tmp_path / "raw")
        monkeypatch.chdir(hub / "integration")

        result = CliRunner().invoke(cli, ["import-tmdl", str(sm_dir)])

        assert result.exit_code == 0, result.output
        assert list(_bi_dir(hub).glob("*-engineering-pack.md"))
        assert not (hub / "integration" / "integration").exists()

    def test_explicit_output_is_used_verbatim(self, tmp_path, monkeypatch):
        """Pins that an explicit path is never re-anchored to the hub root.

        This passes against the unfixed code too — it is a guard against a future
        over-correction, not coverage of the bug.
        """
        hub = _make_hub(tmp_path)
        sm_dir = _create_semantic_model(tmp_path / "raw")
        monkeypatch.chdir(tmp_path)
        explicit = tmp_path / "somewhere" / "else"

        result = CliRunner().invoke(cli, ["import-tmdl", str(sm_dir), "--output", str(explicit)])

        assert result.exit_code == 0, result.output
        assert list(explicit.glob("*-engineering-pack.md"))
        assert not list(_bi_dir(hub).iterdir())

    def test_no_hub_detected_warns_loudly_and_still_writes(self, tmp_path, monkeypatch):
        """No hub is not a hard failure, but it must not be silent."""
        sm_dir = _create_semantic_model(tmp_path / "raw")
        workdir = tmp_path / "not-a-hub"
        workdir.mkdir()
        monkeypatch.chdir(workdir)

        result = CliRunner().invoke(cli, ["import-tmdl", str(sm_dir)])

        assert result.exit_code == 0, result.output
        assert "No ontology-hub root detected" in result.output
        assert list((workdir / "integration" / "discovery" / "bi").glob("*-engineering-pack.md"))

    def test_core_resolves_the_hub_root_when_output_dir_is_none(self, tmp_path, monkeypatch):
        """The resolution lives in core, so non-CLI callers get it too."""
        hub = _make_hub(tmp_path)
        sm_dir = _create_semantic_model(tmp_path / "raw")
        monkeypatch.chdir(tmp_path)

        files = run_import_tmdl(sm_dir)

        assert len(files) == 2
        assert all(f.resolve().is_relative_to(_bi_dir(hub).resolve()) for f in files)


class TestZipExtractionStaysOutOfTheHub:
    def test_zip_writes_only_the_two_derived_artifacts(self, tmp_path, monkeypatch):
        """A PBIP archive carries report definitions and connection strings.

        Only the engineering pack and concept mapping may enter the hub; the raw
        archive members must not be committed alongside them.
        """
        hub = _make_hub(tmp_path)
        zip_path = _create_zip(tmp_path / "raw")
        monkeypatch.chdir(tmp_path)

        result = CliRunner().invoke(cli, ["import-tmdl", str(zip_path)])

        assert result.exit_code == 0, result.output
        written = sorted(p.relative_to(_bi_dir(hub)).as_posix() for p in _bi_dir(hub).rglob("*"))
        assert written == [
            "TestModel-concept-mapping.yaml",
            "TestModel-engineering-pack.md",
        ]

    def test_zip_leaves_no_extraction_tree_anywhere_in_the_hub(self, tmp_path, monkeypatch):
        hub = _make_hub(tmp_path)
        zip_path = _create_zip(tmp_path / "raw")
        monkeypatch.chdir(tmp_path)

        CliRunner().invoke(cli, ["import-tmdl", str(zip_path)])

        assert not list(hub.rglob("*.SemanticModel"))
        assert not list(hub.rglob("model.tmdl"))

    def test_zip_import_is_repeatable_without_accumulating_files(self, tmp_path, monkeypatch):
        """extractall never prunes, so in-place extraction accumulated stale members."""
        hub = _make_hub(tmp_path)
        zip_path = _create_zip(tmp_path / "raw")
        monkeypatch.chdir(tmp_path)

        CliRunner().invoke(cli, ["import-tmdl", str(zip_path)])
        first = sorted(p.name for p in _bi_dir(hub).rglob("*"))
        CliRunner().invoke(cli, ["import-tmdl", str(zip_path)])
        second = sorted(p.name for p in _bi_dir(hub).rglob("*"))

        assert first == second


# ---------------------------------------------------------------------------
# Issue #387 — modern Fabric git-integration .pbip is a JSON pointer file, not
# a zip archive; resolving it to its sibling .Report/.SemanticModel folders
# ---------------------------------------------------------------------------


class TestResolvePbipPointer:
    def test_resolves_dataset_and_report_folders(self, tmp_path):
        pointer_path = _create_pbip_pointer(tmp_path)

        resolved = resolve_pbip_pointer(pointer_path)

        assert len(resolved) == 2
        names = sorted(p.name for p in resolved)
        assert names == ["TestModel.Report", "TestModel.SemanticModel"]
        assert all(p.is_dir() for p in resolved)

    def test_resolves_relative_to_pointer_file_not_cwd(self, tmp_path, monkeypatch):
        """The pointer's paths are relative to its own directory, not the cwd."""
        project_dir = tmp_path / "project"
        pointer_path = _create_pbip_pointer(project_dir)

        # Run from an unrelated cwd — resolution must still find the siblings.
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)

        resolved = resolve_pbip_pointer(pointer_path)

        assert len(resolved) == 2
        assert all(p.resolve().is_relative_to(project_dir.resolve()) for p in resolved)

    def test_skips_a_single_missing_artifact_folder(self, tmp_path):
        """Partial exports are tolerated — one present, one missing is not fatal."""
        pointer_path = _create_pbip_pointer(tmp_path, include_report=False)

        resolved = resolve_pbip_pointer(pointer_path)

        assert len(resolved) == 1
        assert resolved[0].name == "TestModel.SemanticModel"

    def test_no_artifacts_resolve_raises_clear_actionable_error(self, tmp_path):
        """The exact scenario hit during this session's dogfood run: the pointer
        file shipped without the actual .Report/.SemanticModel folder contents.

        Must surface a clear, actionable message — not an unhandled exception
        or a raw zipfile.BadZipFile-style traceback.
        """
        pointer_data = {
            "version": "1.0",
            "artifacts": [
                {
                    "report": {"path": "Missing.Report"},
                    "dataset": {"path": "Missing.SemanticModel"},
                }
            ],
        }
        pointer_path = tmp_path / "Missing.pbip"
        pointer_path.write_text(json.dumps(pointer_data), encoding="utf-8")

        with pytest.raises(ValueError, match="Missing.Report|Missing.SemanticModel"):
            resolve_pbip_pointer(pointer_path)

    def test_run_import_tmdl_raises_clear_error_when_siblings_missing(self, tmp_path):
        """End-to-end: run_import_tmdl must not crash with a raw traceback."""
        pointer_data = {
            "version": "1.0",
            "artifacts": [{"dataset": {"path": "Ghost.SemanticModel"}}],
        }
        pointer_path = tmp_path / "input" / "Ghost.pbip"
        pointer_path.parent.mkdir(parents=True)
        pointer_path.write_text(json.dumps(pointer_data), encoding="utf-8")
        output = tmp_path / "output"

        with pytest.raises(ValueError, match="Ghost.SemanticModel"):
            run_import_tmdl(pointer_path, output)


class TestRunImportTmdlFromPbipPointer:
    def test_pointer_end_to_end_matches_folder_result(self, tmp_path):
        """A pointer .pbip must parse to the same shape as importing the
        .SemanticModel folder directly — the pipeline is reused, not duplicated.
        """
        pointer_path = _create_pbip_pointer(tmp_path / "project")
        output = tmp_path / "output"

        files = run_import_tmdl(pointer_path, output)

        assert len(files) == 2
        mapping_path = next(f for f in files if f.name.endswith("concept-mapping.yaml"))
        data = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))
        assert data["model_name"] == "TestModel"
        assert len(data["tables"]) == 2
        assert len(data["relationships"]) == 1
