# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Regression tests for import-flatfile CLI documentation counts."""

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
