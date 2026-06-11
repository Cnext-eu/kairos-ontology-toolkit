# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for dataplatform semantic-model packaging helper."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _script_path() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "src"
        / "kairos_ontology"
        / "scaffold"
        / "dataplatform"
        / "scripts"
        / "package_fabric_semantic_model.py"
    )


def test_packages_semantic_model_folder(tmp_path: Path) -> None:
    root = tmp_path / "semantic-model"
    definition = root / "Sample.SemanticModel" / "definition"
    table_tmdl = definition / "tables" / "sample.tmdl"
    table_tmdl.parent.mkdir(parents=True)
    (definition / "model.tmdl").write_text(
        "/// header line\n\nmodel Model\n\tculture: en-US\n",
        encoding="utf-8",
    )
    table_tmdl.write_text(
        "table sample\n\tpartition sample = m\n\t\tsource\n\t\t\tentityName: sample\n",
        encoding="utf-8",
    )

    subprocess.run(
        [sys.executable, str(_script_path()), "--input", str(root)],
        check=True,
        capture_output=True,
        text=True,
    )

    model_dir = root / "Sample.SemanticModel"
    assert (model_dir / ".platform").is_file()
    assert (model_dir / "definition.pbism").is_file()
    assert (definition / "database.tmdl").is_file()

    model_tmdl = (definition / "model.tmdl").read_text(encoding="utf-8")
    assert "///" not in model_tmdl

    updated_table = table_tmdl.read_text(encoding="utf-8")
    assert "partition sample = entity" in updated_table
