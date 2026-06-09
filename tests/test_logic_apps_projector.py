# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unit tests for the Logic Apps projector."""

import json
from pathlib import Path

import pytest
from rdflib import Graph, Namespace, RDFS, Literal, URIRef
from rdflib.namespace import OWL, RDF, XSD

from kairos_ontology.projections.logic_apps_projector import generate_logic_apps_artifacts

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


class TestLogicAppsArtifacts:
    def test_produces_workflow_json(self, domain_graph, classes, mappings_dir, sources_dir):
        artifacts = generate_logic_apps_artifacts(
            classes=classes,
            graph=domain_graph,
            template_dir=Path("."),
            namespace=NS,
            ontology_name="test",
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
        )
        workflow_files = [k for k in artifacts if k.endswith("workflow.json")]
        assert len(workflow_files) >= 1

    def test_workflow_json_is_valid(self, domain_graph, classes, mappings_dir, sources_dir):
        artifacts = generate_logic_apps_artifacts(
            classes=classes,
            graph=domain_graph,
            template_dir=Path("."),
            namespace=NS,
            ontology_name="test",
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
        )
        workflow_files = [k for k in artifacts if k.endswith("workflow.json")]
        for key in workflow_files:
            parsed = json.loads(artifacts[key])
            assert "definition" in parsed
            assert "triggers" in parsed["definition"]
            assert "actions" in parsed["definition"]
            assert parsed["kind"] == "Stateful"

    def test_produces_connections_json(self, domain_graph, classes, mappings_dir, sources_dir):
        artifacts = generate_logic_apps_artifacts(
            classes=classes,
            graph=domain_graph,
            template_dir=Path("."),
            namespace=NS,
            ontology_name="test",
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
        )
        assert any(k.endswith("connections.json") for k in artifacts)

    def test_produces_host_json(self, domain_graph, classes, mappings_dir, sources_dir):
        artifacts = generate_logic_apps_artifacts(
            classes=classes,
            graph=domain_graph,
            template_dir=Path("."),
            namespace=NS,
            ontology_name="test",
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
        )
        host_files = [k for k in artifacts if k.endswith("host.json")]
        assert len(host_files) == 1
        parsed = json.loads(artifacts[host_files[0]])
        assert "extensionBundle" in parsed

    def test_produces_local_settings(self, domain_graph, classes, mappings_dir, sources_dir):
        artifacts = generate_logic_apps_artifacts(
            classes=classes,
            graph=domain_graph,
            template_dir=Path("."),
            namespace=NS,
            ontology_name="test",
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
        )
        assert any(k.endswith("local.settings.json") for k in artifacts)

    def test_produces_readme(self, domain_graph, classes, mappings_dir, sources_dir):
        artifacts = generate_logic_apps_artifacts(
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
        assert "Local dry run" in artifacts[readme_files[0]]

    def test_includes_layer1_mappings(self, domain_graph, classes, mappings_dir, sources_dir):
        artifacts = generate_logic_apps_artifacts(
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

    def test_workflow_has_http_trigger(self, domain_graph, classes, mappings_dir, sources_dir):
        artifacts = generate_logic_apps_artifacts(
            classes=classes,
            graph=domain_graph,
            template_dir=Path("."),
            namespace=NS,
            ontology_name="test",
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
        )
        workflow_files = [k for k in artifacts if k.endswith("workflow.json")]
        for key in workflow_files:
            parsed = json.loads(artifacts[key])
            triggers = parsed["definition"]["triggers"]
            trigger_types = [t.get("type") for t in triggers.values()]
            assert "Request" in trigger_types

    def test_workflow_has_transform_actions(self, domain_graph, classes, mappings_dir, sources_dir):
        artifacts = generate_logic_apps_artifacts(
            classes=classes,
            graph=domain_graph,
            template_dir=Path("."),
            namespace=NS,
            ontology_name="test",
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
        )
        workflow_files = [k for k in artifacts if k.endswith("workflow.json")]
        for key in workflow_files:
            parsed = json.loads(artifacts[key])
            actions = parsed["definition"]["actions"]
            assert any("Transform_" in name for name in actions)

    def test_workflow_has_silver_write_action(self, domain_graph, classes, mappings_dir, sources_dir):
        artifacts = generate_logic_apps_artifacts(
            classes=classes,
            graph=domain_graph,
            template_dir=Path("."),
            namespace=NS,
            ontology_name="test",
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
        )
        workflow_files = [k for k in artifacts if k.endswith("workflow.json")]
        for key in workflow_files:
            parsed = json.loads(artifacts[key])
            actions = parsed["definition"]["actions"]
            assert any("Write_" in name for name in actions)

    def test_empty_without_mappings(self, domain_graph, classes, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        artifacts = generate_logic_apps_artifacts(
            classes=classes,
            graph=domain_graph,
            template_dir=Path("."),
            namespace=NS,
            ontology_name="test",
            mappings_dir=empty,
        )
        workflow_files = [k for k in artifacts if k.endswith("workflow.json")]
        assert len(workflow_files) == 0
        assert any(k.endswith("host.json") for k in artifacts)

    def test_workflow_scoped_per_source_system(self, domain_graph, classes, tmp_path):
        maps_dir = tmp_path / "mappings"
        maps_dir.mkdir()
        src_dir = tmp_path / "sources"

        for system in ("erp", "crm"):
            sys_dir = src_dir / system
            sys_dir.mkdir(parents=True)
            vocab = f"""
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix {system}: <https://kairos.cnext.eu/bronze/{system}#> .

{system}:customers rdf:type kairos-bronze:SourceTable .
{system}:customers_name rdf:type kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "name" ;
    kairos-bronze:belongsToTable {system}:customers .
"""
            (sys_dir / f"{system}.vocabulary.ttl").write_text(vocab, encoding="utf-8")
            mapping_ttl = f"""
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
@prefix ex: <{NS}> .
@prefix {system}: <https://kairos.cnext.eu/bronze/{system}#> .

{system}:customers skos:exactMatch ex:Customer ; kairos-map:mappingType "direct" .
{system}:customers_name skos:exactMatch ex:customerName .
"""
            (maps_dir / f"{system}-mapping.ttl").write_text(mapping_ttl, encoding="utf-8")

        artifacts = generate_logic_apps_artifacts(
            classes=classes,
            graph=domain_graph,
            template_dir=Path("."),
            namespace=NS,
            ontology_name="test",
            sources_dir=src_dir,
            mappings_dir=maps_dir,
        )
        workflow_files = [k for k in artifacts if k.endswith("workflow.json")]
        assert len(workflow_files) == 2
