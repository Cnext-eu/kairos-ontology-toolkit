# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unit tests for the n8n projector."""

import json
from pathlib import Path

import pytest
from rdflib import Graph, Namespace, RDFS, Literal, URIRef
from rdflib.namespace import OWL, RDF, XSD

from kairos_ontology.projections.n8n_projector import (
    generate_n8n_artifacts,
    _build_n8n_workflow,
    _mapping_set_values,
    _node_id,
)

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


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------


class TestNodeId:
    def test_format(self):
        assert _node_id(0) == "node-0000"
        assert _node_id(42) == "node-0042"


class TestMappingSetValues:
    def test_builds_set_values(self):
        mapping = {
            "column_mappings": [
                {"source_column": "src_name", "target_property": "customerName"},
                {"source_column": "src_code", "target_property": "customerCode", "transform": "UPPER"},
            ]
        }
        values = _mapping_set_values(mapping)
        assert len(values) == 2
        assert values[0]["name"] == "customerName"
        assert "src_name" in values[0]["value"]


class TestBuildN8nWorkflow:
    def test_workflow_structure(self):
        mappings = [{
            "metadata": {"entity": "Customer"},
            "source": {"system": "erp", "table": "customers"},
            "target": {"silver_table": "silver_test.customer"},
            "column_mappings": [
                {"source_column": "name", "target_property": "customerName"},
            ],
        }]
        wf = _build_n8n_workflow("test", "erp", mappings)
        assert wf["name"] == "test — erp Integration"
        assert len(wf["nodes"]) >= 4  # webhook, router, set, postgres, response
        assert "connections" in wf
        assert wf["active"] is False

    def test_has_webhook_node(self):
        mappings = [{
            "metadata": {"entity": "Order"},
            "source": {"system": "billing", "table": "orders"},
            "target": {"silver_table": "silver_test.order"},
            "column_mappings": [],
        }]
        wf = _build_n8n_workflow("test", "billing", mappings)
        webhook_nodes = [n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.webhook"]
        assert len(webhook_nodes) == 1
        assert "billing" in webhook_nodes[0]["parameters"]["path"]


# ---------------------------------------------------------------------------
# Full generation tests
# ---------------------------------------------------------------------------


class TestN8nArtifacts:
    def test_produces_workflow_json(
        self, domain_graph, classes, mappings_dir, sources_dir
    ):
        artifacts = generate_n8n_artifacts(
            classes=classes,
            graph=domain_graph,
            template_dir=Path("."),
            namespace=NS,
            ontology_name="test",
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
        )
        wf_files = [k for k in artifacts if "/workflows/" in k and k.endswith(".json")]
        assert len(wf_files) >= 1

        # Validate JSON structure
        wf = json.loads(artifacts[wf_files[0]])
        assert "nodes" in wf
        assert "connections" in wf
        assert "name" in wf

    def test_produces_readme(
        self, domain_graph, classes, mappings_dir, sources_dir
    ):
        artifacts = generate_n8n_artifacts(
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
        assert "n8n" in artifacts[readme_files[0]]

    def test_includes_layer1_mappings(
        self, domain_graph, classes, mappings_dir, sources_dir
    ):
        artifacts = generate_n8n_artifacts(
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
        artifacts = generate_n8n_artifacts(
            classes=classes,
            graph=domain_graph,
            template_dir=Path("."),
            namespace=NS,
            ontology_name="test",
            mappings_dir=empty,
        )
        wf_files = [k for k in artifacts if k.endswith("-workflow.json")]
        assert len(wf_files) == 0

    def test_workflow_has_postgres_nodes(
        self, domain_graph, classes, mappings_dir, sources_dir
    ):
        artifacts = generate_n8n_artifacts(
            classes=classes,
            graph=domain_graph,
            template_dir=Path("."),
            namespace=NS,
            ontology_name="test",
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
        )
        wf_files = [k for k in artifacts if k.endswith("-workflow.json")]
        if wf_files:
            wf = json.loads(artifacts[wf_files[0]])
            pg_nodes = [n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.postgres"]
            assert len(pg_nodes) >= 1
