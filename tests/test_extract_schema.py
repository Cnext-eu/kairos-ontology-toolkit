# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for extract_schema module — JSON classification and YAML output."""

import pytest

from kairos_ontology.core.extract_schema import (
    ColumnInfo,
    JsonKeyInfo,
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
        # Samples are no longer written inline — they go to .samples.yaml
        assert "samples" not in table_data["columns"][1]


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
        from kairos_ontology.core.extract_schema import _detect_json_columns_databricks

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
        from kairos_ontology.core.extract_schema import _detect_json_columns_databricks

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
        from kairos_ontology.core.extract_schema import _connect_databricks

        try:
            from databricks import sql as _  # noqa: F401
        except ImportError:
            pytest.skip("databricks-sql-connector not installed")

        with pytest.raises(ValueError, match="host"):
            _connect_databricks({"http_path": "/sql/1.0/warehouses/abc", "token": "x"})

    def test_connect_databricks_missing_http_path(self):
        from kairos_ontology.core.extract_schema import _connect_databricks

        try:
            from databricks import sql as _  # noqa: F401
        except ImportError:
            pytest.skip("databricks-sql-connector not installed")

        with pytest.raises(ValueError, match="http_path"):
            _connect_databricks({"host": "adb-123.net", "token": "x"})


class TestSamplesYamlOutput:
    """Tests for per-table .samples.yaml file generation."""

    def test_writes_samples_yaml_when_rows_present(self, tmp_path):
        """extract-schema writes .samples.yaml alongside table YAML."""
        tables = [
            TableInfo(
                name="tblClient",
                schema="dbo",
                row_count=3,
                columns=[
                    ColumnInfo(name="id", data_type="int", ordinal_position=1),
                    ColumnInfo(name="name", data_type="varchar(100)", ordinal_position=2),
                ],
                sample_rows=[
                    {"id": "1", "name": "Acme NV"},
                    {"id": "2", "name": "Baker BV"},
                    {"id": "3", "name": "Charlie BVBA"},
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

        samples_path = result_dir / "tblClient.samples.yaml"
        assert samples_path.exists()

        import yaml
        with open(samples_path) as f:
            data = yaml.safe_load(f)

        assert data["table"] == "tblClient"
        assert data["schema"] == "dbo"
        assert "extracted_at" in data
        assert len(data["rows"]) == 3
        assert data["rows"][0]["id"] == "1"
        assert data["rows"][0]["name"] == "Acme NV"
        assert data["rows"][1]["name"] == "Baker BV"

    def test_no_samples_yaml_when_no_rows(self, tmp_path):
        """No .samples.yaml when table has no sample rows."""
        tables = [
            TableInfo(
                name="tblEmpty",
                schema="dbo",
                row_count=0,
                columns=[
                    ColumnInfo(name="id", data_type="int", ordinal_position=1),
                ],
                sample_rows=[],
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

        assert not (result_dir / "tblEmpty.samples.yaml").exists()

    def test_redacts_pii_and_records_source_datatype(self, tmp_path):
        tables = [
            TableInfo(
                name="contacts",
                schema="dbo",
                row_count=1,
                columns=[
                    ColumnInfo(
                        name="email",
                        data_type="nvarchar(255)",
                        ordinal_position=1,
                    ),
                    ColumnInfo(
                        name="status",
                        data_type="nvarchar(20)",
                        ordinal_position=2,
                    ),
                ],
                sample_rows=[
                    {"email": "person@example.com", "status": "active"}
                ],
            ),
        ]

        result_dir = write_extraction_output(
            output_dir=tmp_path,
            system_name="crm",
            platform="fabric-warehouse",
            database="warehouse",
            schema="dbo",
            tables=tables,
        )

        import yaml
        raw = (result_dir / "contacts.samples.yaml").read_text(encoding="utf-8")
        samples = yaml.safe_load(raw)
        assert "person@example.com" not in raw
        assert samples["rows"][0]["email"] == (
            "<redacted kind=email source=contacts.email datatype=nvarchar(255)>"
        )
        assert samples["rows"][0]["status"] == "active"
        assert samples["sample_privacy"]["policy"] == "redact-detected-pii"

    def test_redacts_json_structure_sample(self, tmp_path):
        tables = [
            TableInfo(
                name="events",
                schema="dbo",
                row_count=1,
                columns=[
                    ColumnInfo(
                        name="payload",
                        data_type="json",
                        ordinal_position=1,
                        json_detected=True,
                        json_classification="flat",
                        json_structure=[
                            JsonKeyInfo(
                                key="owner_email",
                                type="string",
                                sample="person@example.com",
                            )
                        ],
                    )
                ],
                sample_rows=[],
            ),
        ]

        result_dir = write_extraction_output(
            output_dir=tmp_path,
            system_name="events",
            platform="databricks",
            database="lakehouse",
            schema="bronze",
            tables=tables,
        )

        import yaml
        table_data = yaml.safe_load(
            (result_dir / "events.yaml").read_text(encoding="utf-8")
        )
        sample = table_data["columns"][0]["json_structure"][0]["sample"]
        assert sample == (
            "<redacted kind=email source=events.payload.owner_email datatype=string>"
        )

    def test_row_context_preserved_across_columns(self, tmp_path):
        """Verify that row[0] values for all columns belong to the same source row."""
        tables = [
            TableInfo(
                name="tblAddress",
                schema="dbo",
                row_count=2,
                columns=[
                    ColumnInfo(name="street", data_type="varchar(200)", ordinal_position=1),
                    ColumnInfo(name="city", data_type="varchar(100)", ordinal_position=2),
                ],
                sample_rows=[
                    {"street": "Rue Haute 123", "city": "Brussel"},
                    {"street": "Kerkstraat 45", "city": "Antwerpen"},
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

        import yaml
        with open(result_dir / "tblAddress.samples.yaml") as f:
            data = yaml.safe_load(f)

        # Row 0: street and city should be from the same row
        assert data["rows"][0]["street"] == "Rue Haute 123"
        assert data["rows"][0]["city"] == "Brussel"
        # Row 1: different row's values
        assert data["rows"][1]["street"] == "Kerkstraat 45"
        assert data["rows"][1]["city"] == "Antwerpen"


class TestImportSourceCwdGuard:
    """Tests for CWD context detection in import-source command."""

    def test_warns_when_in_dataplatform_repo(self, tmp_path, monkeypatch):
        """import-source warns if CWD looks like a dataplatform repo."""
        from click.testing import CliRunner
        from kairos_ontology.cli.main import cli

        # Set up a fake dataplatform CWD
        (tmp_path / "dbt_project.yml").write_text("name: test", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        # Create a minimal source YAML
        source_yaml = tmp_path / "source.yaml"
        source_yaml.write_text(
            'version: "1.0"\nsystem: "test"\ntables:\n'
            '  - name: "t1"\n    columns:\n'
            '      - name: "id"\n        data_type: "int"\n',
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["import-source", "--from", str(source_yaml)])

        assert "You appear to be in a dataplatform repo" in result.output or \
               "You appear to be in a dataplatform repo" in (result.stderr or "")

    def test_no_warning_when_in_hub_repo(self, tmp_path, monkeypatch):
        """No warning when CWD has model/ directory (hub repo)."""
        from click.testing import CliRunner
        from kairos_ontology.cli.main import cli

        # Set up a fake hub CWD (has model/ directory)
        (tmp_path / "model").mkdir()
        monkeypatch.chdir(tmp_path)

        # Create a minimal source YAML
        source_yaml = tmp_path / "source.yaml"
        source_yaml.write_text(
            'version: "1.0"\nsystem: "test"\ntables:\n'
            '  - name: "t1"\n    columns:\n'
            '      - name: "id"\n        data_type: "int"\n',
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["import-source", "--from", str(source_yaml)])

        assert "You appear to be in a dataplatform repo" not in (result.output + (result.stderr or ""))
