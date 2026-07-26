# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for safe dbt virtual-column IRIs and their explicit migration."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS

from kairos_ontology.cli.main import cli
from kairos_ontology.core.column_iri_migration import (
    ColumnIriMigrationError,
    migrate_column_iris,
)
from kairos_ontology.core.dbt_contract_sync import (
    KAIROS_BRONZE,
    KAIROS_DBT,
    column_iri,
)

KAIROS_MAP = Namespace("https://kairos.cnext.eu/mapping#")
TABLE = URIRef("https://example.com/virtual#orders")
LEGACY = URIRef(f"{TABLE}/order_id")
SAFE = URIRef(f"{TABLE}__order_id")
UNRELATED = URIRef("https://example.com/unrelated")


def _write_hub(tmp_path: Path, *, collision: bool = False) -> tuple[Path, Path, Path]:
    hub = tmp_path / "hub"
    source = hub / "integration" / "sources" / "custom-transformations" / "orders.ttl"
    mapping = hub / "model" / "mappings" / "orders.ttl"
    source.parent.mkdir(parents=True)
    mapping.parent.mkdir(parents=True)

    source_graph = Graph()
    source_graph.bind("virtual", "https://example.com/virtual#")
    source_graph.add((LEGACY, RDF.type, KAIROS_BRONZE.SourceColumn))
    source_graph.add((LEGACY, KAIROS_BRONZE.sourceTable, TABLE))
    source_graph.add((LEGACY, KAIROS_BRONZE.columnName, Literal("order_id")))
    source_graph.add((LEGACY, KAIROS_DBT.modelRef, Literal("orders")))
    source_graph.add((UNRELATED, RDFS.label, Literal("keep me")))
    if collision:
        source_graph.add((SAFE, RDF.type, KAIROS_BRONZE.SourceColumn))
    source_graph.serialize(source, format="turtle")

    mapping_graph = Graph()
    mapping_resource = URIRef("https://example.com/mapping#order_id")
    mapping_graph.add((mapping_resource, RDF.type, KAIROS_MAP.ColumnMapping))
    mapping_graph.add((mapping_resource, KAIROS_MAP.sourceColumn, LEGACY))
    mapping_graph.add((UNRELATED, RDFS.comment, Literal("also keep me")))
    mapping_graph.serialize(mapping, format="turtle")
    return hub, source, mapping


def test_new_column_iri_is_valid_as_turtle_prefixed_name() -> None:
    graph = Graph()
    graph.parse(
        data=(
            "@prefix virtual: <https://example.com/virtual#> .\n"
            "virtual:orders__order_id a "
            "<https://kairos.cnext.eu/bronze#SourceColumn> .\n"
        ),
        format="turtle",
    )

    assert column_iri(str(TABLE), "order_id") == SAFE
    assert (SAFE, RDF.type, KAIROS_BRONZE.SourceColumn) in graph
    unusual = column_iri(str(TABLE), "line total~€")
    unusual_graph = Graph().parse(
        data=(
            "@prefix virtual: <https://example.com/virtual#> .\n"
            f"virtual:{str(unusual).split('#', 1)[1]} a "
            "<https://kairos.cnext.eu/bronze#SourceColumn> .\n"
        ),
        format="turtle",
    )
    assert (unusual, RDF.type, KAIROS_BRONZE.SourceColumn) in unusual_graph


def test_preview_reports_changes_without_writing(tmp_path: Path) -> None:
    hub, source, mapping = _write_hub(tmp_path)
    before = {path: path.read_bytes() for path in (source, mapping)}

    report = migrate_column_iris(hub)

    assert not report.applied
    assert [(item.old_iri, item.new_iri) for item in report.changes] == [(str(LEGACY), str(SAFE))]
    assert set(report.changed_files) == {source, mapping}
    assert {path: path.read_bytes() for path in (source, mapping)} == before


def test_apply_backs_up_rewrites_and_preserves_unrelated_triples(tmp_path: Path) -> None:
    hub, source, mapping = _write_hub(tmp_path)
    backup = tmp_path / "backup"

    report = migrate_column_iris(hub, apply=True, backup_dir=backup)

    assert report.applied
    for path in (source, mapping):
        graph = Graph().parse(path, format="turtle")
        assert not any(LEGACY in triple for triple in graph)
        assert any(SAFE in triple for triple in graph)
        assert (backup / path.relative_to(hub)).is_file()
    source_graph = Graph().parse(source, format="turtle")
    mapping_graph = Graph().parse(mapping, format="turtle")
    assert (UNRELATED, RDFS.label, Literal("keep me")) in source_graph
    assert (UNRELATED, RDFS.comment, Literal("also keep me")) in mapping_graph

    second = migrate_column_iris(hub)
    assert second.changes == ()
    assert second.changed_files == ()


def test_collision_and_unsafe_apply_are_rejected(tmp_path: Path) -> None:
    hub, _, _ = _write_hub(tmp_path, collision=True)
    with pytest.raises(ColumnIriMigrationError, match="collision"):
        migrate_column_iris(hub)

    clean_hub, _, _ = _write_hub(tmp_path / "clean")
    with pytest.raises(ColumnIriMigrationError, match="requires an explicit"):
        migrate_column_iris(clean_hub, apply=True)
    existing_backup = tmp_path / "existing"
    existing_backup.mkdir()
    with pytest.raises(ColumnIriMigrationError, match="refusing overwrite"):
        migrate_column_iris(clean_hub, apply=True, backup_dir=existing_backup)


def test_cli_previews_and_requires_explicit_backup_for_apply(tmp_path: Path) -> None:
    hub, _, _ = _write_hub(tmp_path)
    runner = CliRunner()

    preview = runner.invoke(
        cli,
        ["migrate-column-iris", "--hub", str(hub)],
        env={"KAIROS_SKILL_CONTEXT": "1"},
    )
    assert preview.exit_code == 0, preview.output
    assert f"{LEGACY} -> {SAFE}" in preview.output
    assert "No files written" in preview.output

    refused = runner.invoke(
        cli,
        ["migrate-column-iris", "--hub", str(hub), "--apply"],
        env={"KAIROS_SKILL_CONTEXT": "1"},
    )
    assert refused.exit_code != 0
    assert "--apply requires an explicit --backup-dir" in refused.output
