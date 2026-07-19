# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the import-flatfile module (CSV/Excel reading, type inference, output)."""

import pytest

from kairos_ontology.core.import_flatfile import (
    infer_column_type,
    read_csv_table,
    read_parquet_table,
    write_source_dir,
    run_import_flatfile,
    detect_technical_columns,
    exclude_columns_from_tables,
    _arrow_type_to_sql,
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

    def test_redacts_detected_pii_before_writing(self, tmp_path):
        tables = [{
            "name": "contacts",
            "row_count": 1,
            "columns": [
                {
                    "name": "email",
                    "data_type": "varchar(255)",
                    "ordinal_position": 1,
                    "nullable": False,
                },
                {
                    "name": "status",
                    "data_type": "varchar(20)",
                    "ordinal_position": 2,
                    "nullable": False,
                },
            ],
            "sample_rows": [
                {"email": "person@example.com", "status": "active"}
            ],
        }]

        output = write_source_dir(tables, "crm", tmp_path / "crm")

        import yaml
        raw = (output / "contacts.samples.yaml").read_text(encoding="utf-8")
        samples = yaml.safe_load(raw)
        assert "person@example.com" not in raw
        assert samples["rows"][0]["email"] == (
            "<redacted kind=email source=contacts.email datatype=varchar(255)>"
        )
        assert samples["rows"][0]["status"] == "active"
        assert samples["sample_privacy"]["policy"] == "redact-detected-pii"

        manifest = yaml.safe_load(
            (output / "_manifest.yaml").read_text(encoding="utf-8")
        )
        assert manifest["sample_privacy"]["version"] == "1"

    def test_removes_stale_samples_when_rerun_has_no_rows(self, tmp_path):
        output_dir = tmp_path / "erp"
        output_dir.mkdir()
        stale = output_dir / "empty.samples.yaml"
        stale.write_text("rows:\n  - email: person@example.com\n", encoding="utf-8")
        tables = [{
            "name": "empty",
            "row_count": 0,
            "columns": [{"name": "email", "data_type": "varchar(255)"}],
            "sample_rows": [],
        }]

        write_source_dir(tables, "erp", output_dir)

        assert not stale.exists()


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


# --------------------------------------------------------------------------- #
# Fix 1: Windows csv.field_size_limit — no OverflowError on import
# --------------------------------------------------------------------------- #


class TestCsvFieldSizeLimitWindows:
    """Fix 1: Importing the module must not raise OverflowError on Windows."""

    def test_import_does_not_raise_overflow(self):
        """csv.field_size_limit(min(sys.maxsize, 2**31-1)) should never overflow."""
        import importlib
        import kairos_ontology.core.import_flatfile as mod
        # Re-import should succeed without OverflowError
        importlib.reload(mod)


# --------------------------------------------------------------------------- #
# Fix 2: Hub-root detection — ontology-hub/ dir without model/ontologies/
# --------------------------------------------------------------------------- #


class TestHubRootDetection:
    """Fix 2: detect ontology-hub/ even without model/ontologies/."""

    def test_detects_ontology_hub_dir(self, tmp_path, monkeypatch):
        """When ontology-hub/ exists but model/ontologies/ doesn't, use it."""
        hub_dir = tmp_path / "ontology-hub"
        hub_dir.mkdir()
        # Need at least one hub marker directory for detection
        (hub_dir / "model").mkdir()
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("id,name\n1,Alice\n", encoding="utf-8")

        monkeypatch.chdir(tmp_path)
        result = run_import_flatfile(csv_file, system_name="test")

        expected = hub_dir / "integration" / "sources" / "test"
        assert result == expected
        assert (expected / "_manifest.yaml").exists()


# --------------------------------------------------------------------------- #
# Fix 6: Column exclusion (explicit + auto-detect)
# --------------------------------------------------------------------------- #


class TestDetectTechnicalColumns:
    """Fix 6: Auto-detect lakehouse metadata columns."""

    def test_detects_known_technical_columns(self):
        tables = [
            {"columns": [
                {"name": "id", "distinct_count": 100},
                {"name": "volume", "distinct_count": 1},
                {"name": "subfolder", "distinct_count": 1},
            ]},
            {"columns": [
                {"name": "id", "distinct_count": 50},
                {"name": "volume", "distinct_count": 1},
                {"name": "subfolder", "distinct_count": 1},
            ]},
        ]
        result = detect_technical_columns(tables)
        assert result == {"volume", "subfolder"}

    def test_skips_non_universal_columns(self):
        """Column appearing in only one table is not flagged."""
        tables = [
            {"columns": [
                {"name": "volume", "distinct_count": 1},
            ]},
            {"columns": [
                {"name": "id", "distinct_count": 50},
            ]},
        ]
        result = detect_technical_columns(tables)
        assert result == set()

    def test_skips_non_singleton_columns(self):
        """Column with distinctCount > 1 is not flagged."""
        tables = [
            {"columns": [{"name": "volume", "distinct_count": 5}]},
            {"columns": [{"name": "volume", "distinct_count": 3}]},
        ]
        result = detect_technical_columns(tables)
        assert result == set()

    def test_empty_tables(self):
        assert detect_technical_columns([]) == set()


class TestExcludeColumns:
    """Fix 6: Explicit column exclusion."""

    def test_excludes_columns_from_tables(self):
        tables = [
            {
                "columns": [
                    {"name": "id", "data_type": "int"},
                    {"name": "volume", "data_type": "varchar(max)"},
                ],
                "sample_rows": [{"id": "1", "volume": "vol1"}],
            },
        ]
        exclude_columns_from_tables(tables, {"volume"})
        assert len(tables[0]["columns"]) == 1
        assert tables[0]["columns"][0]["name"] == "id"
        assert "volume" not in tables[0]["sample_rows"][0]

    def test_case_insensitive_exclusion(self):
        tables = [
            {
                "columns": [
                    {"name": "ID", "data_type": "int"},
                    {"name": "Volume", "data_type": "varchar(max)"},
                ],
                "sample_rows": [],
            },
        ]
        exclude_columns_from_tables(tables, {"volume"})
        assert len(tables[0]["columns"]) == 1

    def test_no_exclusion_when_empty(self):
        tables = [{"columns": [{"name": "id"}], "sample_rows": []}]
        exclude_columns_from_tables(tables, set())
        assert len(tables[0]["columns"]) == 1


class TestRunImportFlatfileExclusion:
    """Fix 6: End-to-end exclusion via run_import_flatfile."""

    def test_explicit_exclude_columns(self, tmp_path):
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("id,volume,name\n1,vol1,Alice\n", encoding="utf-8")
        output_dir = tmp_path / "output"

        result = run_import_flatfile(
            csv_file, output_dir=output_dir, exclude_columns={"volume"},
        )
        import yaml
        tbl = yaml.safe_load((result / "data.yaml").read_text(encoding="utf-8"))
        col_names = [c["name"] for c in tbl["columns"]]
        assert "volume" not in col_names
        assert "id" in col_names

    def test_keep_technical_flag(self, tmp_path):
        """With --keep-technical, auto-detected columns are kept."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / "a.csv").write_text("id,volume\n1,vol1\n", encoding="utf-8")
        (input_dir / "b.csv").write_text("id,volume\n2,vol1\n", encoding="utf-8")
        output_dir = tmp_path / "output"

        result = run_import_flatfile(
            input_dir, system_name="test", output_dir=output_dir, keep_technical=True,
        )
        import yaml
        tbl = yaml.safe_load((result / "a.yaml").read_text(encoding="utf-8"))
        col_names = [c["name"] for c in tbl["columns"]]
        assert "volume" in col_names


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
        with pytest.raises(ValueError, match="No CSV, Excel, or Parquet"):
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
        from kairos_ontology.core.import_source import parse_source_schema_dir, generate_vocabulary_ttl

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


# --------------------------------------------------------------------------- #
# Parquet Reading Tests
# --------------------------------------------------------------------------- #

pa = pytest.importorskip("pyarrow")


def _write_parquet(path, columns: dict):
    """Helper: write a dict of column -> pyarrow array/list to a parquet file."""
    import pyarrow.parquet as pq

    table = pa.table(columns)
    pq.write_table(table, path)
    return path


class TestArrowTypeToSql:
    def test_bool_maps_to_bit(self):
        assert _arrow_type_to_sql(pa.bool_()) == "bit"

    def test_int32_maps_to_int(self):
        assert _arrow_type_to_sql(pa.int32()) == "int"

    def test_int16_maps_to_int(self):
        assert _arrow_type_to_sql(pa.int16()) == "int"

    def test_int64_maps_to_bigint(self):
        assert _arrow_type_to_sql(pa.int64()) == "bigint"

    def test_uint32_maps_to_bigint(self):
        assert _arrow_type_to_sql(pa.uint32()) == "bigint"

    def test_float_maps_to_decimal(self):
        assert _arrow_type_to_sql(pa.float64()) == "decimal"

    def test_decimal_maps_to_decimal(self):
        assert _arrow_type_to_sql(pa.decimal128(10, 2)) == "decimal"

    def test_date_maps_to_date(self):
        assert _arrow_type_to_sql(pa.date32()) == "date"

    def test_timestamp_maps_to_datetime(self):
        assert _arrow_type_to_sql(pa.timestamp("s")) == "datetime"

    def test_string_maps_to_varchar(self):
        assert _arrow_type_to_sql(pa.string()) == "varchar(max)"


class TestReadParquetTable:
    def test_basic_parquet(self, tmp_path):
        pq_file = tmp_path / "customers.parquet"
        _write_parquet(pq_file, {
            "id": pa.array([1, 2, 3], type=pa.int64()),
            "name": pa.array(["Alice", "Bob", "Carol"], type=pa.string()),
            "active": pa.array([True, False, True], type=pa.bool_()),
            "score": pa.array([1.5, 2.5, 3.5], type=pa.float64()),
        })

        table = read_parquet_table(pq_file)

        assert table["name"] == "customers"
        assert table["row_count"] == 3
        by_name = {c["name"]: c for c in table["columns"]}
        assert by_name["id"]["data_type"] == "bigint"
        assert by_name["name"]["data_type"] == "varchar(max)"
        assert by_name["active"]["data_type"] == "bit"
        assert by_name["score"]["data_type"] == "decimal"
        assert by_name["id"]["ordinal_position"] == 1
        assert by_name["name"]["distinct_count"] == 3
        assert "Alice" in by_name["name"]["samples"]
        assert len(table["sample_rows"]) == 3

    def test_nullable_column(self, tmp_path):
        pq_file = tmp_path / "data.parquet"
        _write_parquet(pq_file, {
            "id": pa.array([1, 2, 3], type=pa.int64()),
            "email": pa.array(["a@x.com", None, "c@x.com"], type=pa.string()),
        })

        table = read_parquet_table(pq_file)
        by_name = {c["name"]: c for c in table["columns"]}
        assert by_name["id"]["nullable"] is False
        assert by_name["email"]["nullable"] is True

    def test_max_rows_caps_sampling(self, tmp_path):
        """Only sample data is read — never the whole file."""
        pq_file = tmp_path / "huge.parquet"
        _write_parquet(pq_file, {
            "id": pa.array(list(range(5000)), type=pa.int64()),
        })

        table = read_parquet_table(pq_file, max_rows=100)
        assert table["row_count"] == 100

    def test_sample_rows_limited(self, tmp_path):
        pq_file = tmp_path / "big.parquet"
        _write_parquet(pq_file, {
            "id": pa.array(list(range(50)), type=pa.int64()),
        })

        table = read_parquet_table(pq_file, sample_size=3)
        assert len(table["sample_rows"]) == 3

    def test_date_and_timestamp_columns(self, tmp_path):
        import datetime as dt

        pq_file = tmp_path / "events.parquet"
        _write_parquet(pq_file, {
            "d": pa.array([dt.date(2024, 1, 15)], type=pa.date32()),
            "ts": pa.array([dt.datetime(2024, 1, 15, 10, 30)], type=pa.timestamp("s")),
        })

        table = read_parquet_table(pq_file)
        by_name = {c["name"]: c for c in table["columns"]}
        assert by_name["d"]["data_type"] == "date"
        assert by_name["ts"]["data_type"] == "datetime"

    def test_missing_pyarrow_raises_importerror(self, tmp_path, monkeypatch):
        pq_file = tmp_path / "x.parquet"
        _write_parquet(pq_file, {"id": pa.array([1], type=pa.int64())})

        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "pyarrow.parquet":
                raise ImportError("no pyarrow")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(ImportError, match=r"\[parquet\]"):
            read_parquet_table(pq_file)


class TestRunImportFlatfileParquet:
    def test_single_parquet(self, tmp_path):
        pq_file = tmp_path / "input" / "orders.parquet"
        pq_file.parent.mkdir()
        _write_parquet(pq_file, {
            "id": pa.array([1, 2], type=pa.int64()),
            "total": pa.array([99.5, 12.0], type=pa.float64()),
        })

        output_dir = tmp_path / "output" / "orders"
        result = run_import_flatfile(pq_file, output_dir=output_dir)

        assert result == output_dir
        assert (output_dir / "_manifest.yaml").exists()
        assert (output_dir / "orders.yaml").exists()
        assert (output_dir / "orders.samples.yaml").exists()

    def test_directory_mixed_csv_and_parquet(self, tmp_path):
        input_dir = tmp_path / "exports"
        input_dir.mkdir()
        (input_dir / "items.csv").write_text("id,sku\n1,ABC\n", encoding="utf-8")
        _write_parquet(input_dir / "orders.parquet", {
            "id": pa.array([1], type=pa.int64()),
        })

        output_dir = tmp_path / "output" / "legacy"
        result = run_import_flatfile(input_dir, system_name="legacy", output_dir=output_dir)

        import yaml
        manifest = yaml.safe_load((result / "_manifest.yaml").read_text(encoding="utf-8"))
        assert sorted(manifest["tables"]) == ["items", "orders"]
