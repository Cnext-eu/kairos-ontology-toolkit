# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Regression tests for import-flatfile CLI documentation counts."""

import pytest
from click.testing import CliRunner

from kairos_ontology.cli.sources import import_flatfile


def test_import_flatfile_reports_current_run_table_count(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "customers.csv").write_text("id,name\n1,Alice\n", encoding="utf-8")
    (input_dir / "orders.csv").write_text("id,total\n1,99.5\n", encoding="utf-8")

    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / "stale.yaml").write_text("name: stale\n", encoding="utf-8")
    (output_dir / "stale.samples.yaml").write_text("rows: []\n", encoding="utf-8")

    result = CliRunner().invoke(
        import_flatfile,
        [
            "--from",
            str(input_dir),
            "--system",
            "legacy",
            "--output",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "📊 2 table(s) documented" in result.output
    assert "📋 2 sample file(s) created" in result.output
    # A clean run must not print the partial-failure warning at all.
    assert "could not be read" not in result.output


def _write_corrupt_parquet(path):
    path.write_bytes(b"not a parquet file at all")
    return path


def _write_parquet(path, columns):
    import pyarrow as pa
    import pyarrow.parquet as pq

    pq.write_table(pa.table(columns), path)
    return path


def test_partial_directory_failure_warns_and_exits_zero(tmp_path):
    """Directory mode: unreadable files are reported but the run still succeeds (#293)."""
    pytest.importorskip("pyarrow")
    import pyarrow as pa

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "customers.csv").write_text("id,name\n1,Alice\n", encoding="utf-8")
    _write_parquet(input_dir / "orders.parquet", {"id": pa.array([1], type=pa.int64())})
    _write_corrupt_parquet(input_dir / "broken.parquet")
    # Not a candidate file, so it must not inflate the "of K" denominator.
    (input_dir / "README.txt").write_text("ignore me", encoding="utf-8")

    output_dir = tmp_path / "out"

    result = CliRunner().invoke(
        import_flatfile,
        ["--from", str(input_dir), "--system", "legacy", "--output", str(output_dir)],
    )

    assert result.exit_code == 0, result.output
    assert "📊 2 table(s) documented" in result.output
    assert "1 of 3 file(s) could not be read — skipped:" in result.output
    assert "broken.parquet" in result.output
    # Partial success still points at the next step.
    assert "Next step" in result.output
    assert (output_dir / "customers.yaml").exists()
    assert (output_dir / "orders.yaml").exists()


def test_total_directory_failure_exits_one_and_writes_nothing(tmp_path):
    """Every file unreadable is a hard failure — no success line, no output (#293)."""
    pytest.importorskip("pyarrow")

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _write_corrupt_parquet(input_dir / "broken-a.parquet")
    _write_corrupt_parquet(input_dir / "broken-b.parquet")

    output_dir = tmp_path / "out"

    result = CliRunner().invoke(
        import_flatfile,
        ["--from", str(input_dir), "--system", "legacy", "--output", str(output_dir)],
    )

    assert result.exit_code == 1
    assert "✅ Written to" not in result.output
    assert "Next step" not in result.output
    assert not output_dir.exists()


def test_nested_directory_without_recursive_hints_at_flag(tmp_path):
    """Issue #407 item 2: a nested export tree must read as 'wrong shape', not
    'wrong path' — and must not be confused with the unreadable-files message."""
    input_dir = tmp_path / "input"
    nested_dir = input_dir / "2024"
    nested_dir.mkdir(parents=True)
    (nested_dir / "orders.csv").write_text("id,sku\n1,ABC\n", encoding="utf-8")

    output_dir = tmp_path / "out"

    result = CliRunner().invoke(
        import_flatfile,
        ["--from", str(input_dir), "--system", "legacy", "--output", str(output_dir)],
    )

    assert result.exit_code == 1
    assert "found 1 candidate file(s) in subdirectories" in result.output
    assert "--recursive" in result.output
    assert "could not be read" not in result.output
    assert not output_dir.exists()


def test_recursive_flag_imports_nested_directory(tmp_path):
    """Issue #407 item 2: --recursive opts into the nested tree and derives
    collision-safe table names from each file's path relative to --from."""
    input_dir = tmp_path / "input"
    (input_dir / "2024").mkdir(parents=True)
    (input_dir / "2025").mkdir(parents=True)
    (input_dir / "2024" / "orders.csv").write_text("id,sku\n1,A\n", encoding="utf-8")
    (input_dir / "2025" / "orders.csv").write_text("id,sku\n2,B\n", encoding="utf-8")

    output_dir = tmp_path / "out"

    result = CliRunner().invoke(
        import_flatfile,
        [
            "--from",
            str(input_dir),
            "--system",
            "legacy",
            "--output",
            str(output_dir),
            "--recursive",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "📊 2 table(s) documented" in result.output
    assert (output_dir / "2024-orders.yaml").exists()
    assert (output_dir / "2025-orders.yaml").exists()


def test_xlsx_missing_extra_preflight_fails_once_and_writes_nothing(tmp_path, monkeypatch):
    """Issue #407 item 1: 32 identical per-file warnings plus a huge aggregate
    ValueError becomes one precise, actionable failure, with nothing written."""
    import kairos_ontology.core.import_flatfile as flatfile_mod

    real_import_module = flatfile_mod.importlib.import_module

    def fake_import_module(name, *args, **kwargs):
        if name == "openpyxl":
            raise ImportError("simulated missing openpyxl")
        return real_import_module(name, *args, **kwargs)

    monkeypatch.setattr(flatfile_mod.importlib, "import_module", fake_import_module)

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    for i in range(3):
        (input_dir / f"sheet{i}.xlsx").write_bytes(b"not a real xlsx")

    output_dir = tmp_path / "out"

    result = CliRunner().invoke(
        import_flatfile,
        ["--from", str(input_dir), "--system", "legacy", "--output", str(output_dir)],
    )

    assert result.exit_code == 1
    assert result.output.count("pip install kairos-ontology-toolkit[flatfile]") == 1
    assert not output_dir.exists()


def test_single_file_xls_gives_clean_cli_error_not_a_traceback(tmp_path):
    """Issue #407 item 4: .xls in single-file mode used to escape as an unhandled
    InvalidFileException (not a ValueError/ImportError); now it's a clean exit 1."""
    xls_file = tmp_path / "legacy.xls"
    xls_file.write_bytes(b"not a real xls file")
    output_dir = tmp_path / "out"

    result = CliRunner().invoke(
        import_flatfile,
        ["--from", str(xls_file), "--system", "legacy", "--output", str(output_dir)],
    )

    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert "legacy .xls is not supported" in result.output
    assert not output_dir.exists()


def test_tz_aware_parquet_directory_imports_cleanly(tmp_path):
    """The real #293 symptom: a named-zone timestamp column lost its whole table."""
    pytest.importorskip("pyarrow")
    import datetime as dt

    import pyarrow as pa

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    naive = pa.array([dt.datetime(2024, 1, 15, 10, 30, 0)], type=pa.timestamp("us"))
    _write_parquet(
        input_dir / "shipments.parquet",
        {
            "id": pa.array([1], type=pa.int64()),
            "created_at": naive.cast(pa.timestamp("us", tz="America/New_York")),
        },
    )

    output_dir = tmp_path / "out"

    result = CliRunner().invoke(
        import_flatfile,
        ["--from", str(input_dir), "--system", "legacy", "--output", str(output_dir)],
    )

    assert result.exit_code == 0, result.output
    assert "📊 1 table(s) documented" in result.output
    assert "could not be read" not in result.output
    assert (output_dir / "shipments.yaml").exists()
