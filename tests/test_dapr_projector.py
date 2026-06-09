# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unit tests for the Dapr projector."""

import json
from pathlib import Path

import pytest
from rdflib import Graph, Namespace, RDFS, Literal, URIRef
from rdflib.namespace import OWL, RDF, XSD

from kairos_ontology.projections.dapr_projector import generate_dapr_artifacts

NS = "https://example.com/test#"
KAIROS_EXT = Namespace("https://kairos.cnext.eu/ext#")


@pytest.fixture
def domain_graph():
    g = Graph()
    cls = URIRef(f"{NS}Customer")
    g.add((cls, RDF.type, OWL.Class))
    g.add((cls, RDFS.label, Literal("Customer")))
    g.add((cls, RDFS.comment, Literal("A customer entity")))

    prop = URIRef(f"{NS}customerName")
    g.add((prop, RDF.type, OWL.DatatypeProperty))
    g.add((prop, RDFS.domain, cls))
    g.add((prop, RDFS.range, XSD.string))
    g.add((prop, RDFS.label, Literal("Customer Name")))

    g.add((cls, KAIROS_EXT.naturalKey, Literal("customerName")))
    return g


@pytest.fixture
def classes():
    return [{"uri": f"{NS}Customer", "name": "Customer", "label": "Customer", "comment": "A customer"}]


@pytest.fixture
def mappings_dir(tmp_path):
    maps_dir = tmp_path / "mappings"
    maps_dir.mkdir()
    mapping_ttl = f"""
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
@prefix ex: <{NS}> .
@prefix erp: <https://kairos.cnext.eu/bronze/erp#> .

erp:customers skos:exactMatch ex:Customer ; kairos-map:mappingType "direct" .
erp:customers_name skos:exactMatch ex:customerName .
"""
    (maps_dir / "erp-mapping.ttl").write_text(mapping_ttl, encoding="utf-8")
    return maps_dir


@pytest.fixture
def sources_dir(tmp_path):
    src_dir = tmp_path / "sources" / "erp"
    src_dir.mkdir(parents=True)
    vocab = """
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix erp: <https://kairos.cnext.eu/bronze/erp#> .

erp:customers rdf:type kairos-bronze:SourceTable .
erp:customers_name rdf:type kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "name" ;
    kairos-bronze:belongsToTable erp:customers .
"""
    (src_dir / "erp.vocabulary.ttl").write_text(vocab, encoding="utf-8")
    return tmp_path / "sources"


class TestDaprArtifacts:
    def test_produces_dapr_components(
        self, domain_graph, classes, mappings_dir, sources_dir
    ):
        artifacts = generate_dapr_artifacts(
            classes=classes,
            graph=domain_graph,
            template_dir=Path("."),
            namespace=NS,
            ontology_name="test",
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
        )
        component_files = [k for k in artifacts if "/components/" in k]
        assert any("binding-" in f for f in component_files)
        assert any("statestore" in f for f in component_files)
        assert any("pubsub" in f for f in component_files)

    def test_produces_app_files(
        self, domain_graph, classes, mappings_dir, sources_dir
    ):
        artifacts = generate_dapr_artifacts(
            classes=classes,
            graph=domain_graph,
            template_dir=Path("."),
            namespace=NS,
            ontology_name="test",
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
        )
        app_files = [k for k in artifacts if "/app/" in k]
        assert any("app.py" in f for f in app_files)
        assert any("mapper.py" in f for f in app_files)
        assert any("requirements.txt" in f for f in app_files)
        assert any("Dockerfile" in f for f in app_files)

    def test_produces_readme(
        self, domain_graph, classes, mappings_dir, sources_dir
    ):
        artifacts = generate_dapr_artifacts(
            classes=classes,
            graph=domain_graph,
            template_dir=Path("."),
            namespace=NS,
            ontology_name="test",
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
        )
        readme_files = [k for k in artifacts if k.endswith("README.md")]
        assert len(readme_files) == 1
        assert "Run locally" in artifacts[readme_files[0]]

    def test_produces_docker_compose(
        self, domain_graph, classes, mappings_dir, sources_dir
    ):
        artifacts = generate_dapr_artifacts(
            classes=classes,
            graph=domain_graph,
            template_dir=Path("."),
            namespace=NS,
            ontology_name="test",
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
        )
        assert any("docker-compose" in k for k in artifacts)

    def test_includes_layer1_mappings(
        self, domain_graph, classes, mappings_dir, sources_dir
    ):
        artifacts = generate_dapr_artifacts(
            classes=classes,
            graph=domain_graph,
            template_dir=Path("."),
            namespace=NS,
            ontology_name="test",
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
        )
        mapping_files = [k for k in artifacts if "/mappings/" in k and k.endswith(".json")]
        assert len(mapping_files) >= 1

    def test_empty_without_mappings(self, domain_graph, classes, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        artifacts = generate_dapr_artifacts(
            classes=classes,
            graph=domain_graph,
            template_dir=Path("."),
            namespace=NS,
            ontology_name="test",
            mappings_dir=empty,
        )
        # Should still have components + app (structural files)
        # but no mapping JSON files
        mapping_json = [k for k in artifacts if k.endswith("-mapping.json")]
        assert len(mapping_json) == 0

    def test_app_references_entities(
        self, domain_graph, classes, mappings_dir, sources_dir
    ):
        artifacts = generate_dapr_artifacts(
            classes=classes,
            graph=domain_graph,
            template_dir=Path("."),
            namespace=NS,
            ontology_name="test",
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
        )
        app_key = [k for k in artifacts if k.endswith("app.py")][0]
        assert "Customer" in artifacts[app_key]

    def test_sanitizes_source_system_in_handler_name(self, domain_graph, classes, tmp_path):
        maps_dir = tmp_path / "mappings"
        maps_dir.mkdir()
        src_dir = tmp_path / "sources" / "erp_core"
        src_dir.mkdir(parents=True)

        vocab = """
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix erp: <https://kairos.cnext.eu/bronze/erp-core#> .

erp:customers rdf:type kairos-bronze:SourceTable .
erp:customers_name rdf:type kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "name" ;
    kairos-bronze:belongsToTable erp:customers .
"""
        (src_dir / "erp_core.vocabulary.ttl").write_text(vocab, encoding="utf-8")

        mapping_ttl = f"""
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
@prefix ex: <{NS}> .
@prefix erp: <https://kairos.cnext.eu/bronze/erp-core#> .

erp:customers skos:exactMatch ex:Customer ; kairos-map:mappingType "direct" .
erp:customers_name skos:exactMatch ex:customerName .
"""
        (maps_dir / "erp-core-mapping.ttl").write_text(mapping_ttl, encoding="utf-8")

        artifacts = generate_dapr_artifacts(
            classes=classes,
            graph=domain_graph,
            template_dir=Path("."),
            namespace=NS,
            ontology_name="test",
            sources_dir=tmp_path / "sources",
            mappings_dir=maps_dir,
        )

        app_key = [k for k in artifacts if k.endswith("app.py")][0]
        assert "def on_erp_core_data" in artifacts[app_key]
