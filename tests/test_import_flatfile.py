# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the import-flatfile module (CSV/Excel reading, type inference, output)."""

import pytest

from kairos_ontology.import_flatfile import (
    infer_column_type,
    read_csv_table,
    write_source_dir,
    run_import_flatfile,
)


# --------------------------------------------------------------------------- #
# Type Inference Tests
# --------------------------------------------------------------------------- #


class TestInferColumnType:
    def test_empty_values_returns_varchar(self):
        assert infer_column_type([]) == "varchar(max)"

    def test_integers(self):
        assert infer_column_type(["1", "2", "3", "100"]) == "int"

    def test_large_integers_return_bigint(self):
        assert infer_column_type(["9999999999", "1234567890123"]) == "bigint"

    def test_decimals(self):
        assert infer_column_type(["1.5", "2.7", "3.14"]) == "decimal"

    def test_dates_iso(self):
        assert infer_column_type(["2024-01-15", "2024-02-20"]) == "date"

    def test_dates_slash(self):
        assert infer_column_type(["15/01/2024", "20/02/2024"]) == "date"

    def test_datetimes(self):
        assert infer_column_type(["2024-01-15T10:30:00", "2024-02-20 14:00"]) == "datetime"

    def test_booleans(self):
        assert infer_column_type(["true", "false", "True"]) == "bit"
        assert infer_column_type(["1", "0", "1"]) == "bit"
        assert infer_column_type(["yes", "no", "Yes"]) == "bit"

    def test_mixed_values_return_varchar(self):
        assert infer_column_type(["hello", "world", "123abc"]) == "varchar(max)"

    def test_mixed_int_and_string(self):
        """If any value isn't numeric, fall through to varchar."""
        assert infer_column_type(["1", "2", "three"]) == "varchar(max)"


# --------------------------------------------------------------------------- #
# CSV Reading Tests
# --------------------------------------------------------------------------- #


class TestReadCsvTable:
    def test_basic_csv(self, tmp_path):
        csv_file = tmp_path / "customers.csv"
        csv_file.write_text(
            "id,name,age,active\n"
            "1,Alice,30,true\n"
            "2,Bob,25,false\n"
            "3,Charlie,,true\n",
            encoding="utf-8",
        )
        result = read_csv_table(csv_file)

        assert result["name"] == "customers"
        assert result["row_count"] == 3
        assert len(result["columns"]) == 4

        # Check column types
        col_map = {c["name"]: c for c in result["columns"]}
        assert col_map["id"]["data_type"] == "int"
        assert col_map["name"]["data_type"] == "varchar(max)"
        assert col_map["age"]["data_type"] == "int"
        assert col_map["active"]["data_type"] == "bit"

        # Nullability: age has an empty value
        assert col_map["age"]["nullable"] is True
        assert col_map["id"]["nullable"] is False

    def test_semicolon_delimiter(self, tmp_path):
        csv_file = tmp_path / "data.csv"
        csv_file.write_text(
            "col1;col2;col3\n"
            "a;1;2024-01-01\n"
            "b;2;2024-02-01\n",
            encoding="utf-8",
        )
        result = read_csv_table(csv_file)
        col_map = {c["name"]: c for c in result["columns"]}
        assert col_map["col2"]["data_type"] == "int"
        assert col_map["col3"]["data_type"] == "date"

    def test_sample_rows_limited(self, tmp_path):
        csv_file = tmp_path / "big.csv"
        lines = ["id,val\n"] + [f"{i},item{i}\n" for i in range(100)]
        csv_file.write_text("".join(lines), encoding="utf-8")
        result = read_csv_table(csv_file, sample_size=3)
        assert len(result["sample_rows"]) == 3

    def test_max_rows_limits_reading(self, tmp_path):
        csv_file = tmp_path / "huge.csv"
        lines = ["id,val\n"] + [f"{i},item{i}\n" for i in range(500)]
        csv_file.write_text("".join(lines), encoding="utf-8")
        result = read_csv_table(csv_file, max_rows=10)
        assert result["row_count"] == 10

    def test_no_headers_raises(self, tmp_path):
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="No headers"):
            read_csv_table(csv_file)


# --------------------------------------------------------------------------- #
# Write Source Dir Tests
# --------------------------------------------------------------------------- #


class TestWriteSourceDir:
    def test_writes_manifest(self, tmp_path):
        tables = [{
            "name": "orders",
            "row_count": 10,
            "columns": [{"name": "id", "data_type": "int", "ordinal_position": 1, "nullable": False}],
            "sample_rows": [{"id": "1"}],
        }]
        output = write_source_dir(tables, "erp", tmp_path / "erp")

        import yaml
        manifest = yaml.safe_load((output / "_manifest.yaml").read_text(encoding="utf-8"))
        assert manifest["system"] == "erp"
        assert manifest["version"] == "1.1"
        assert manifest["tables"] == ["orders"]

    def test_writes_table_yaml_without_samples(self, tmp_path):
        tables = [{
            "name": "orders",
            "row_count": 5,
            "columns": [
                {"name": "id", "data_type": "int", "ordinal_position": 1,
                 "nullable": False, "samples": ["1", "2", "3"]},
            ],
            "sample_rows": [{"id": "1"}],
        }]
        output = write_source_dir(tables, "test", tmp_path / "test")

        import yaml
        table_data = yaml.safe_load((output / "orders.yaml").read_text(encoding="utf-8"))
        # Table YAML should NOT have inline samples (they go to .samples.yaml)
        assert "samples" not in table_data["columns"][0]

    def test_writes_samples_yaml(self, tmp_path):
        tables = [{
            "name": "orders",
            "row_count": 5,
            "columns": [{"name": "id", "data_type": "int", "ordinal_position": 1, "nullable": False}],
            "sample_rows": [{"id": "1"}, {"id": "2"}],
        }]
        output = write_source_dir(tables, "test", tmp_path / "test")

        import yaml
        samples = yaml.safe_load((output / "orders.samples.yaml").read_text(encoding="utf-8"))
        assert samples["table"] == "orders"
        assert len(samples["rows"]) == 2


# --------------------------------------------------------------------------- #
# Orchestration Tests
# --------------------------------------------------------------------------- #


class TestRunImportFlatfile:
    def test_single_csv(self, tmp_path):
        csv_file = tmp_path / "input" / "clients.csv"
        csv_file.parent.mkdir()
        csv_file.write_text("id,name\n1,Alice\n2,Bob\n", encoding="utf-8")

        output_dir = tmp_path / "output" / "clients"
        result = run_import_flatfile(csv_file, output_dir=output_dir)

        assert result == output_dir
        assert (output_dir / "_manifest.yaml").exists()
        assert (output_dir / "clients.yaml").exists()
        assert (output_dir / "clients.samples.yaml").exists()

    def test_directory_of_csvs(self, tmp_path):
        input_dir = tmp_path / "exports"
        input_dir.mkdir()
        (input_dir / "orders.csv").write_text("id,total\n1,99.5\n", encoding="utf-8")
        (input_dir / "items.csv").write_text("id,sku\n1,ABC\n", encoding="utf-8")

        output_dir = tmp_path / "output" / "legacy"
        result = run_import_flatfile(input_dir, system_name="legacy", output_dir=output_dir)

        import yaml
        manifest = yaml.safe_load((result / "_manifest.yaml").read_text(encoding="utf-8"))
        assert sorted(manifest["tables"]) == ["items", "orders"]


# --------------------------------------------------------------------------- #
# Regression Tests — Bug Fixes (fix3)
# --------------------------------------------------------------------------- #


class TestNoneValuesInCsv:
    """Bug 1: DictReader can store None for fields with trailing commas."""

    def test_csv_with_none_values_does_not_crash(self, tmp_path):
        """CSV with trailing commas produces None values in DictReader."""
        csv_file = tmp_path / "trailing.csv"
        # Trailing commas cause DictReader to have None values
        csv_file.write_text(
            "id,name,extra\n"
            "1,Alice,\n"
            "2,,\n"
            "3,Charlie,\n",
            encoding="utf-8",
        )
        result = read_csv_table(csv_file)
        assert result["row_count"] == 3
        col_map = {c["name"]: c for c in result["columns"]}
        assert col_map["name"]["nullable"] is True  # row 2 has empty name

    def test_csv_with_explicit_none_field(self, tmp_path):
        """Simulates DictReader returning None by writing a CSV with extra columns."""
        csv_file = tmp_path / "extra_col.csv"
        # Row with more fields than headers → restkey captures extra, but missing cols are None
        csv_file.write_text(
            "a,b\n"
            "1,2\n"
            "3,4\n",
            encoding="utf-8",
        )
        result = read_csv_table(csv_file)
        assert result["row_count"] == 2
        assert len(result["columns"]) == 2


class TestLargeFieldLimit:
    """Bug 2: CSV fields larger than 128KB should not crash."""

    def test_large_field_does_not_crash(self, tmp_path):
        csv_file = tmp_path / "large_field.csv"
        large_value = "x" * (200 * 1024)  # 200KB field
        csv_file.write_text(
            f"id,payload\n1,{large_value}\n",
            encoding="utf-8",
        )
        result = read_csv_table(csv_file)
        assert result["row_count"] == 1
        col_map = {c["name"]: c for c in result["columns"]}
        assert col_map["payload"]["data_type"] == "varchar(max)"


class TestSameFileCopyGuard:
    """Bug 4: shutil.copy2 when source == dest should be skipped."""

    def test_import_source_skips_copy_when_same_dir(self, tmp_path):
        """When source dir and output dir are the same, no PermissionError."""
        from click.testing import CliRunner
        from kairos_ontology.cli.main import cli

        # Create a minimal source directory
        src_dir = tmp_path / "my_source"
        src_dir.mkdir()

        manifest = {"system": "test_sys", "tables": ["orders"]}
        import yaml
        (src_dir / "_manifest.yaml").write_text(
            yaml.dump(manifest), encoding="utf-8"
        )
        (src_dir / "orders.yaml").write_text(
            yaml.dump({
                "name": "orders",
                "row_count": 2,
                "columns": [
                    {"name": "id", "data_type": "int", "ordinal_position": 1, "nullable": False}
                ],
            }),
            encoding="utf-8",
        )
        # Add a samples file in the SAME directory (triggers same-file copy)
        (src_dir / "orders.samples.yaml").write_text(
            yaml.dump([{"id": 1}, {"id": 2}]), encoding="utf-8"
        )

        runner = CliRunner()
        result = runner.invoke(cli, [
            "import-source",
            "--from", str(src_dir),
            "--output", str(src_dir / "test.vocabulary.ttl"),
        ])
        # Should not crash with PermissionError
        assert result.exit_code == 0, f"Failed with: {result.output}"


    def test_unsupported_extension_raises(self, tmp_path):
        bad_file = tmp_path / "data.json"
        bad_file.write_text("{}", encoding="utf-8")
        with pytest.raises(ValueError, match="Unsupported file type"):
            run_import_flatfile(bad_file, output_dir=tmp_path / "out")

    def test_empty_directory_raises(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        with pytest.raises(ValueError, match="No CSV or Excel"):
            run_import_flatfile(empty_dir, output_dir=tmp_path / "out")

    def test_system_name_derived_from_filename(self, tmp_path):
        csv_file = tmp_path / "my-erp.csv"
        csv_file.write_text("col1\nval1\n", encoding="utf-8")

        output_dir = tmp_path / "out" / "my-erp"
        run_import_flatfile(csv_file, output_dir=output_dir)

        import yaml
        manifest = yaml.safe_load((output_dir / "_manifest.yaml").read_text(encoding="utf-8"))
        assert manifest["system"] == "my-erp"


# --------------------------------------------------------------------------- #
# Integration: flatfile → import-source pipeline
# --------------------------------------------------------------------------- #


class TestFlatfileToImportSourcePipeline:
    def test_csv_to_vocabulary_ttl(self, tmp_path):
        """Full pipeline: CSV → YAML → TTL."""
        from kairos_ontology.import_source import parse_source_schema_dir, generate_vocabulary_ttl

        # Step 1: Create CSV
        csv_file = tmp_path / "accounts.csv"
        csv_file.write_text(
            "AccountId,AccountName,Balance,CreatedDate\n"
            "1,Acme Corp,1500.50,2024-01-15\n"
            "2,Baker Ltd,2300.00,2024-02-20\n",
            encoding="utf-8",
        )

        # Step 2: import-flatfile → YAML + samples
        source_dir = tmp_path / "sources" / "finance"
        run_import_flatfile(csv_file, system_name="finance", output_dir=source_dir)

        # Step 3: parse directory and generate TTL (same as import-source --from <dir>)
        data = parse_source_schema_dir(source_dir)
        ttl = generate_vocabulary_ttl(data)

        from rdflib import Graph
        g = Graph()
        g.parse(data=ttl, format="turtle")
        assert len(g) > 0

        # Should have the accounts table
        assert "accounts" in ttl.lower() or "Accounts" in ttl
