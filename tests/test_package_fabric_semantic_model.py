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


def test_m_partition_keyword_is_preserved(tmp_path: Path) -> None:
    """A genuine Power Query partition must keep ``= m``.

    ``= m`` is the correct TMDL source-type keyword for an M partition; the
    Direct Lake rewrite previously ran unconditionally and would leave an
    entity-partition header over a ``let ... in`` body.
    """
    root = tmp_path / "semantic-model"
    definition = root / "Sample.SemanticModel" / "definition"
    table_tmdl = definition / "tables" / "sample.tmdl"
    table_tmdl.parent.mkdir(parents=True)
    (definition / "model.tmdl").write_text("model Model\n\tculture: en-US\n", encoding="utf-8")
    table_tmdl.write_text(
        "table sample\n"
        "\tpartition sample = m\n"
        "\t\tmode: directQuery\n"
        "\t\tsource =\n"
        "\t\t\tlet\n"
        '\t\t\t\tSource = Databricks.Catalogs("host", "path")\n'
        '\t\t\tin Source{[Name="gold.sample"]}[Data]\n',
        encoding="utf-8",
    )

    subprocess.run(
        [sys.executable, str(_script_path()), "--input", str(root)],
        check=True,
        capture_output=True,
        text=True,
    )

    updated = table_tmdl.read_text(encoding="utf-8")
    assert "partition sample = m" in updated
    assert "= entity" not in updated


def test_projector_owned_wrapper_files_are_not_overwritten(tmp_path: Path) -> None:
    """The projector owns the wrapper; the helper only backfills what is missing.

    Overwriting would re-diverge the two writers and reset a logicalId that
    Fabric may already have assigned.
    """
    root = tmp_path / "semantic-model"
    model_dir = root / "Sample.SemanticModel"
    definition = model_dir / "definition"
    definition.mkdir(parents=True)
    (definition / "model.tmdl").write_text("model Model\n\tculture: en-US\n", encoding="utf-8")
    platform = model_dir / ".platform"
    pbism = model_dir / "definition.pbism"
    platform.write_text('{"config": {"logicalId": "real-fabric-id"}}\n', encoding="utf-8")
    pbism.write_text('{"version": "4.2", "settings": {"marker": true}}\n', encoding="utf-8")

    subprocess.run(
        [sys.executable, str(_script_path()), "--input", str(root)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "real-fabric-id" in platform.read_text(encoding="utf-8")
    assert "marker" in pbism.read_text(encoding="utf-8")


def test_wrapper_files_are_still_backfilled_when_absent(tmp_path: Path) -> None:
    """Hand-authored / imported models with no wrapper still get one."""
    root = tmp_path / "semantic-model"
    definition = root / "Sample.SemanticModel" / "definition"
    definition.mkdir(parents=True)
    (definition / "model.tmdl").write_text("model Model\n\tculture: en-US\n", encoding="utf-8")

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


def test_package_helper_is_idempotent_on_clean_projector_output(tmp_path: Path) -> None:
    root = tmp_path / "semantic-model"
    definition = root / "Sample.SemanticModel" / "definition"
    table_tmdl = definition / "tables" / "sample.tmdl"
    table_tmdl.parent.mkdir(parents=True)
    (root / "Sample.SemanticModel" / ".platform").write_text("{}", encoding="utf-8")
    (root / "Sample.SemanticModel" / "definition.pbism").write_text("{}", encoding="utf-8")
    (definition / "database.tmdl").write_text(
        "database\n\tcompatibilityLevel: 1604\n",
        encoding="utf-8",
    )
    (definition / "model.tmdl").write_text(
        "model Model\n\tculture: en-US\n",
        encoding="utf-8",
    )
    table_tmdl.write_text(
        "table sample\n\tpartition sample = entity\n\t\tmode: directLake\n",
        encoding="utf-8",
    )
    before_table = table_tmdl.read_text(encoding="utf-8")
    before_database = (definition / "database.tmdl").read_text(encoding="utf-8")

    subprocess.run(
        [sys.executable, str(_script_path()), "--input", str(root)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert table_tmdl.read_text(encoding="utf-8") == before_table
    assert (definition / "database.tmdl").read_text(encoding="utf-8") == before_database
