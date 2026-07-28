# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Regression tests for flatfile table naming collisions."""

import pytest
import yaml
from openpyxl import Workbook

from kairos_ontology.core.import_flatfile import run_import_flatfile


def _write_workbook(path, sheet_names):
    wb = Workbook()
    for index, sheet_name in enumerate(sheet_names):
        ws = wb.active if index == 0 else wb.create_sheet()
        ws.title = sheet_name
        ws.append(["id", "name"])
        ws.append([index + 1, sheet_name])
    wb.save(path)


def test_xlsx_table_names_include_file_stem_when_needed(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _write_workbook(input_dir / "single.xlsx", ["Sheet1"])
    _write_workbook(input_dir / "multi.xlsx", ["Sheet1", "Other"])

    result_dir = run_import_flatfile(input_dir, system_name="legacy", output_dir=tmp_path / "out")

    manifest = yaml.safe_load((result_dir / "_manifest.yaml").read_text(encoding="utf-8"))
    assert sorted(manifest["tables"]) == ["multi__Other", "multi__Sheet1", "single"]
    assert (result_dir / "single.yaml").exists()
    assert (result_dir / "multi__Sheet1.yaml").exists()
    assert not (result_dir / "Sheet1.yaml").exists()


def test_duplicate_final_table_names_raise_before_writing(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "orders.csv").write_text("id,name\n1,Alice\n", encoding="utf-8")
    _write_workbook(input_dir / "orders.xlsx", ["Sheet1"])
    output_dir = tmp_path / "out"

    with pytest.raises(ValueError, match=r"Duplicate final table name.*orders"):
        run_import_flatfile(input_dir, system_name="legacy", output_dir=output_dir)

    assert not (output_dir / "_manifest.yaml").exists()
