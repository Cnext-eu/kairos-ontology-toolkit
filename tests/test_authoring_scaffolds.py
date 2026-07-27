# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unit tests for deterministic authoring and recovery scaffolds."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS, XSD

from kairos_ontology.core.authoring_scaffolds import (
    AUTHORING,
    BRONZE,
    KMAP,
    AuthoringScaffoldError,
    build_mapping_scaffold,
    build_silver_scaffold,
    write_text,
)
from kairos_ontology.core.projections.dbt.mapping_bind import bind_mapping_graph
from kairos_ontology.cli.main import cli


def _hub_evidence(tmp_path: Path) -> tuple[Path, Path, str, str]:
    source_root = tmp_path / "integration" / "sources" / "crm"
    source_root.mkdir(parents=True)
    source = Namespace("https://example.com/source/crm#")
    graph = Graph()
    graph.add((source.Customers, RDF.type, BRONZE.SourceTable))
    graph.add((source.Customers, BRONZE.tableName, Literal("Customers")))
    for name, data_type, nullable in (
        ("customerId", "varchar", False),
        ("city", "varchar", True),
    ):
        column = source[name]
        graph.add((column, RDF.type, BRONZE.SourceColumn))
        graph.add((column, BRONZE.sourceTable, source.Customers))
        graph.add((column, BRONZE.columnName, Literal(name)))
        graph.add((column, BRONZE.dataType, Literal(data_type)))
        graph.add((column, BRONZE.nullable, Literal(nullable, datatype=XSD.boolean)))
    graph.serialize(source_root / "crm.vocabulary.ttl", format="turtle")

    ontology_path = tmp_path / "model" / "ontologies" / "customer.ttl"
    ontology_path.parent.mkdir(parents=True)
    domain = Namespace("https://example.com/domain/customer#")
    ontology = Graph()
    ontology.add((URIRef("https://example.com/domain/customer"), RDF.type, OWL.Ontology))
    ontology.add((URIRef("https://example.com/domain/customer"), RDFS.label, Literal("Customer")))
    ontology.add((URIRef("https://example.com/domain/customer"), OWL.versionInfo, Literal("1.0.0")))
    ontology.add((domain.Customer, RDF.type, OWL.Class))
    ontology.add((domain.Customer, RDFS.label, Literal("Customer")))
    ontology.add((domain.Customer, RDFS.comment, Literal("A customer.")))
    ontology.add((domain.customerId, RDF.type, OWL.DatatypeProperty))
    ontology.add((domain.customerId, RDFS.label, Literal("customer ID")))
    ontology.add((domain.customerId, RDFS.comment, Literal("Customer identifier.")))
    ontology.add((domain.customerId, RDFS.domain, domain.Customer))
    ontology.add((domain.customerId, RDFS.range, XSD.string))
    ontology.add((domain.Address, RDF.type, OWL.Class))
    ontology.add((domain.Address, RDFS.label, Literal("Address")))
    ontology.add((domain.Address, RDFS.comment, Literal("A postal address.")))
    ontology.add((domain.city, RDF.type, OWL.DatatypeProperty))
    ontology.add((domain.city, RDFS.label, Literal("city")))
    ontology.add((domain.city, RDFS.comment, Literal("Address city.")))
    ontology.add((domain.city, RDFS.domain, domain.Address))
    ontology.add((domain.city, RDFS.range, XSD.string))
    ontology.serialize(ontology_path, format="turtle")
    return source_root.parent, ontology_path, str(source.Customers), str(domain.Customer)


def test_mapping_scaffold_is_valid_named_and_non_authoritative(tmp_path: Path) -> None:
    source_root, ontology, source_table, target_class = _hub_evidence(tmp_path)

    scaffold = build_mapping_scaffold(
        source_root=source_root,
        ontology_path=ontology,
        source_table_uri=source_table,
        target_class_uri=target_class,
    )

    assert scaffold.validation["passed"] is True
    assert scaffold.proposals == 2
    assert scaffold.review_items == 1
    assert all(
        isinstance(item, URIRef) for item in scaffold.graph.subjects(RDF.type, KMAP.TableMapping)
    )
    assert len(bind_mapping_graph(scaffold.graph).tables) == 0
    assert len(bind_mapping_graph(scaffold.graph, include_proposals=True).tables) == 1
    assert (None, AUTHORING.reviewState, Literal("out-of-scope")) in scaffold.graph


def test_mapping_scaffold_rejects_unknown_source_table(tmp_path: Path) -> None:
    source_root, ontology, _, target_class = _hub_evidence(tmp_path)

    with pytest.raises(AuthoringScaffoldError, match="Unknown source table"):
        build_mapping_scaffold(
            source_root=source_root,
            ontology_path=ontology,
            source_table_uri="https://example.com/source/crm#Missing",
            target_class_uri=target_class,
        )


def test_mapping_scaffold_advises_denormalized_column_owned_by_mapped_entity(
    tmp_path: Path,
) -> None:
    source_root, ontology, source_table, target_class = _hub_evidence(tmp_path)
    existing = Graph()
    existing_table = URIRef("https://example.com/mapping#address-table")
    existing_column = URIRef("https://example.com/mapping#address-city")
    other_table = URIRef("https://example.com/source/address")
    other_column = URIRef("https://example.com/source/address/city")
    address = URIRef("https://example.com/domain/customer#Address")
    city = URIRef("https://example.com/domain/customer#city")
    existing.add((existing_table, RDF.type, KMAP.TableMapping))
    existing.add((existing_table, KMAP.sourceTable, other_table))
    existing.add((existing_table, KMAP.targetClass, address))
    existing.add((existing_table, KMAP.mappingType, Literal("direct")))
    existing.add((existing_table, KMAP.matchType, Literal("exactMatch")))
    existing.add((other_table, URIRef(str(SKOS.exactMatch)), address))
    existing.add((existing_column, RDF.type, KMAP.ColumnMapping))
    existing.add((existing_column, KMAP.sourceColumn, other_column))
    existing.add((existing_column, KMAP.targetProperty, city))
    existing.add((existing_column, KMAP.matchType, Literal("exactMatch")))
    existing.add((other_column, URIRef(str(SKOS.exactMatch)), city))
    existing_path = tmp_path / "address-mapping.ttl"
    existing.serialize(existing_path, format="turtle")

    scaffold = build_mapping_scaffold(
        source_root=source_root,
        ontology_path=ontology,
        source_table_uri=source_table,
        target_class_uri=target_class,
        existing_mapping_paths=(existing_path,),
    )

    assert scaffold.advisories == 1
    assert (
        len(tuple(scaffold.graph.subjects(RDF.type, AUTHORING.DenormalizedOwnershipAdvisory))) == 1
    )


def test_silver_scaffold_uses_evidence_and_leaves_governance_for_review(
    tmp_path: Path,
) -> None:
    source_root, ontology, source_table, target_class = _hub_evidence(tmp_path)
    mapping = build_mapping_scaffold(
        source_root=source_root,
        ontology_path=ontology,
        source_table_uri=source_table,
        target_class_uri=target_class,
    )
    mapping_path = tmp_path / "mapping.ttl"
    mapping.graph.serialize(mapping_path, format="turtle")
    shapes = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "kairos_ontology"
        / "scaffold"
        / "kairos-ext-shapes.shacl.ttl"
    )

    scaffold = build_silver_scaffold(
        source_root=source_root,
        ontology_path=ontology,
        mapping_paths=(mapping_path,),
        shapes_path=shapes,
    )

    assert scaffold.validation["passed"] is True
    assert scaffold.review_items == 9
    assert (
        URIRef(target_class),
        URIRef("https://kairos.cnext.eu/ext#silverTableName"),
        None,
    ) not in scaffold.graph
    assert (
        URIRef(target_class),
        URIRef("https://kairos.cnext.eu/ext#silverSourceRef"),
        URIRef(source_table),
    ) in scaffold.graph


def test_silver_scaffold_loads_import_closure_without_counting_imported_ontology(
    tmp_path: Path,
) -> None:
    source_root, ontology, source_table, target_class = _hub_evidence(tmp_path)
    imported_iri = URIRef("https://example.com/reference")
    ontology_graph = Graph().parse(ontology, format="turtle")
    ontology_resource = next(ontology_graph.subjects(RDF.type, OWL.Ontology))
    ontology_graph.add((ontology_resource, OWL.imports, imported_iri))
    ontology_graph.serialize(ontology, format="turtle")
    imported = ontology.parent / "reference.ttl"
    imported_graph = Graph()
    imported_graph.add((imported_iri, RDF.type, OWL.Ontology))
    imported_graph.serialize(imported, format="turtle")
    catalog = ontology.parent / "catalog-v001.xml"
    catalog.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
        f'  <uri name="{imported_iri}" uri="{imported.name}"/>\n'
        "</catalog>\n",
        encoding="utf-8",
    )
    mapping = build_mapping_scaffold(
        source_root=source_root,
        ontology_path=ontology,
        source_table_uri=source_table,
        target_class_uri=target_class,
        catalog_path=catalog,
    )
    mapping_path = tmp_path / "mapping.ttl"
    mapping.graph.serialize(mapping_path, format="turtle")
    shapes = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "kairos_ontology"
        / "scaffold"
        / "kairos-ext-shapes.shacl.ttl"
    )

    scaffold = build_silver_scaffold(
        source_root=source_root,
        ontology_path=ontology,
        mapping_paths=(mapping_path,),
        shapes_path=shapes,
        catalog_path=catalog,
    )

    assert scaffold.validation["passed"] is True


def test_write_text_requires_explicit_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "mapping.ttl"
    path.write_text("authored", encoding="utf-8")
    with pytest.raises(AuthoringScaffoldError, match="without --overwrite"):
        write_text(path, "generated")
    assert path.read_text(encoding="utf-8") == "authored"


def test_mapping_cli_previews_then_requires_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, source_table, target_class = _hub_evidence(tmp_path)
    monkeypatch.chdir(tmp_path)
    arguments = [
        "scaffold-mapping",
        "--domain",
        "customer",
        "--source-table",
        source_table,
        "--target-class",
        target_class,
    ]
    runner = CliRunner()

    preview = runner.invoke(cli, arguments, env={"KAIROS_SKILL_CONTEXT": "1"})
    assert preview.exit_code == 0, preview.output
    assert "TableMapping" in preview.output
    assert not (tmp_path / "model" / "mappings").exists()

    output = Path("model/mappings/crm-to-customer.ttl")
    created = runner.invoke(
        cli,
        [*arguments, "--output", str(output)],
        env={"KAIROS_SKILL_CONTEXT": "1"},
    )
    assert created.exit_code == 0, created.output
    blocked = runner.invoke(
        cli,
        [*arguments, "--output", str(output)],
        env={"KAIROS_SKILL_CONTEXT": "1"},
    )
    assert blocked.exit_code != 0
    assert "Refusing to overwrite" in blocked.output
