# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for extract_schema module — JSON classification and YAML output."""

import pytest

from kairos_ontology.extract_schema import (
    ColumnInfo,
    TableInfo,
    classify_json_column,
    extract_json_structure,
    write_extraction_output,
    parse_dbt_profile,
)


class TestJsonClassification:
    """Tests for JSON column classification heuristics."""

    def test_flat_json(self):
        samples = [
            '{"phone": "+32 2 123", "email": "a@b.com"}',
            '{"phone": "+32 3 456", "email": "c@d.com"}',
            '{"phone": "+32 9 789", "email": "e@f.com"}',
        ]
        assert classify_json_column(samples) == "flat"

    def test_nested_json(self):
        samples = [
            '{"address": {"street": "Main St", "city": "Brussels"}}',
            '{"address": {"street": "Oak Ave", "city": "Ghent"}}',
        ]
        assert classify_json_column(samples) == "nested"

    def test_array_object(self):
        samples = [
            '[{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]',
            '[{"id": 3, "name": "C"}]',
        ]
        assert classify_json_column(samples) == "array_object"

    def test_array_primitive(self):
        samples = [
            '["tag1", "tag2", "tag3"]',
            '["x", "y"]',
        ]
        assert classify_json_column(samples) == "array_primitive"

    def test_polymorphic_varied_keys(self):
        samples = [
            '{"a": 1, "b": 2}',
            '{"x": 10, "y": 20, "z": 30}',
            '{"p": 100}',
        ]
        assert classify_json_column(samples) == "polymorphic"

    def test_empty_samples(self):
        assert classify_json_column([]) == "polymorphic"
        assert classify_json_column(["", "  "]) == "polymorphic"

    def test_invalid_json(self):
        samples = ["not json", "also not json"]
        assert classify_json_column(samples) == "polymorphic"


class TestJsonStructureExtraction:
    """Tests for extracting key structure from JSON samples."""

    def test_flat_structure(self):
        samples = ['{"name": "Acme", "code": 42}']
        structure = extract_json_structure(samples, "flat")
        assert len(structure) == 2
        keys = {s.key: s.type for s in structure}
        assert keys["name"] == "string"
        assert keys["code"] == "integer"

    def test_array_object_structure(self):
        samples = ['[{"street": "Main", "city": "Brussels"}]']
        structure = extract_json_structure(samples, "array_object")
        assert len(structure) == 2
        keys = {s.key for s in structure}
        assert "street" in keys
        assert "city" in keys


class TestYamlOutput:
    """Tests for writing extraction results to YAML files."""

    def test_writes_manifest_and_tables(self, tmp_path):
        tables = [
            TableInfo(
                name="tblClient",
                schema="dbo",
                row_count=100,
                columns=[
                    ColumnInfo(name="id", data_type="int", ordinal_position=1, nullable=False),
                    ColumnInfo(
                        name="name", data_type="varchar(200)",
                        ordinal_position=2, nullable=True,
                        samples=["Acme", "Baker"],
                    ),
                ],
            ),
            TableInfo(
                name="tblInvoice",
                schema="dbo",
                row_count=500,
                columns=[
                    ColumnInfo(name="id", data_type="int", ordinal_position=1, nullable=False),
                ],
            ),
        ]

        result_dir = write_extraction_output(
            output_dir=tmp_path,
            system_name="testapp",
            platform="fabric-warehouse",
            database="mydb",
            schema="dbo",
            tables=tables,
        )

        assert result_dir == tmp_path / "testapp"
        assert (result_dir / "_manifest.yaml").exists()
        assert (result_dir / "tblClient.yaml").exists()
        assert (result_dir / "tblInvoice.yaml").exists()

        # Check manifest content
        import yaml
        with open(result_dir / "_manifest.yaml") as f:
            manifest = yaml.safe_load(f)
        assert manifest["version"] == "1.1"
        assert manifest["system"] == "testapp"
        assert manifest["tables"] == ["tblClient", "tblInvoice"]

        # Check table content
        with open(result_dir / "tblClient.yaml") as f:
            table_data = yaml.safe_load(f)
        assert table_data["name"] == "tblClient"
        assert table_data["row_count"] == 100
        assert len(table_data["columns"]) == 2
        assert table_data["columns"][1]["samples"] == ["Acme", "Baker"]


class TestProfileParsing:
    """Tests for dbt profile parsing."""

    def test_parse_valid_profile(self, tmp_path):
        profiles_content = {
            "myproject": {
                "target": "dev",
                "outputs": {
                    "dev": {
                        "type": "fabric",
                        "server": "myworkspace.datawarehouse.fabric.microsoft.com",
                        "database": "mydb",
                        "schema": "dbo",
                        "authentication": "CLI",
                    }
                }
            }
        }
        import yaml
        (tmp_path / "profiles.yml").write_text(
            yaml.dump(profiles_content), encoding="utf-8"
        )

        result = parse_dbt_profile(tmp_path, "myproject", "dev")
        assert result["type"] == "fabric"
        assert result["database"] == "mydb"

    def test_profile_not_found(self, tmp_path):
        import yaml
        (tmp_path / "profiles.yml").write_text(
            yaml.dump({"other": {"target": "dev", "outputs": {"dev": {}}}}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="not found"):
            parse_dbt_profile(tmp_path, "missing", "dev")

    def test_profiles_file_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            parse_dbt_profile(tmp_path, "any", "dev")

    def test_parse_databricks_profile(self, tmp_path):
        import yaml
        profiles_content = {
            "myproject": {
                "target": "dev",
                "outputs": {
                    "dev": {
                        "type": "databricks",
                        "host": "adb-123.azuredatabricks.net",
                        "http_path": "/sql/1.0/warehouses/abc",
                        "catalog": "main",
                        "schema": "bronze",
                        "token": "dapiXYZ",
                    }
                }
            }
        }
        (tmp_path / "profiles.yml").write_text(
            yaml.dump(profiles_content), encoding="utf-8"
        )

        result = parse_dbt_profile(tmp_path, "myproject", "dev")
        assert result["type"] == "databricks"
        assert result["host"] == "adb-123.azuredatabricks.net"
        assert result["http_path"] == "/sql/1.0/warehouses/abc"
        assert result["catalog"] == "main"


class TestDatabricksIntrospection:
    """Tests for Databricks-specific introspection logic."""

    def test_detect_json_in_string_columns(self):
        from kairos_ontology.extract_schema import _detect_json_columns_databricks

        cols = [
            ColumnInfo(
                name="payload",
                data_type="string",
                samples=['{"key": "val"}', '{"key": "val2"}', '{"key": "val3"}'],
            ),
            ColumnInfo(
                name="id",
                data_type="bigint",
                samples=["1", "2", "3"],
            ),
        ]
        _detect_json_columns_databricks(cols)

        assert cols[0].json_detected is True
        assert cols[0].json_classification == "flat"
        assert cols[1].json_detected is False

    def test_no_detection_for_non_string_columns(self):
        from kairos_ontology.extract_schema import _detect_json_columns_databricks

        cols = [
            ColumnInfo(
                name="amount",
                data_type="decimal(10,2)",
                samples=["100.50", "200.00"],
            ),
        ]
        _detect_json_columns_databricks(cols)
        assert cols[0].json_detected is False

    def test_connect_databricks_missing_host(self):
        from kairos_ontology.extract_schema import _connect_databricks

        try:
            from databricks import sql as _  # noqa: F401
        except ImportError:
            pytest.skip("databricks-sql-connector not installed")

        with pytest.raises(ValueError, match="host"):
            _connect_databricks({"http_path": "/sql/1.0/warehouses/abc", "token": "x"})

    def test_connect_databricks_missing_http_path(self):
        from kairos_ontology.extract_schema import _connect_databricks

        try:
            from databricks import sql as _  # noqa: F401
        except ImportError:
            pytest.skip("databricks-sql-connector not installed")

        with pytest.raises(ValueError, match="http_path"):
            _connect_databricks({"host": "adb-123.net", "token": "x"})
