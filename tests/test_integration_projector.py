# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unit tests for the integration mapping projector."""

import json
from pathlib import Path
from unittest import mock

import pytest
from rdflib import Graph, Namespace, RDFS, Literal, URIRef
from rdflib.namespace import OWL, RDF, XSD

from kairos_ontology.projections.integration_projector import (
    generate_integration_artifacts,
    _extract_properties,
    _extract_silver_metadata,
    _xsd_to_simple_type,
    _column_belongs_to_table,
    _extract_system_name,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NS = "https://example.com/test#"
KAIROS_EXT = Namespace("https://kairos.cnext.eu/ext#")
KAIROS_BRONZE = Namespace("https://kairos.cnext.eu/bronze#")
KAIROS_MAP = Namespace("https://kairos.cnext.eu/mapping#")


@pytest.fixture
def domain_graph():
    """Build a simple domain ontology with one class + properties."""
    g = Graph()
    g.bind("ex", Namespace(NS))
    g.bind("kairos-ext", KAIROS_EXT)

    cls = URIRef(f"{NS}Customer")
    g.add((cls, RDF.type, OWL.Class))
    g.add((cls, RDFS.label, Literal("Customer")))
    g.add((cls, RDFS.comment, Literal("A customer entity")))

    # Data properties
    name_prop = URIRef(f"{NS}customerName")
    g.add((name_prop, RDF.type, OWL.DatatypeProperty))
    g.add((name_prop, RDFS.domain, cls))
    g.add((name_prop, RDFS.range, XSD.string))
    g.add((name_prop, RDFS.label, Literal("Customer Name")))

    code_prop = URIRef(f"{NS}customerCode")
    g.add((code_prop, RDF.type, OWL.DatatypeProperty))
    g.add((code_prop, RDFS.domain, cls))
    g.add((code_prop, RDFS.range, XSD.string))
    g.add((code_prop, RDFS.label, Literal("Customer Code")))

    # Silver extensions
    g.add((cls, KAIROS_EXT.naturalKey, Literal("customerCode")))
    g.add((cls, KAIROS_EXT.scdType, Literal("SCD2")))

    return g


@pytest.fixture
def classes():
    return [
        {
            "uri": f"{NS}Customer",
            "name": "Customer",
            "label": "Customer",
            "comment": "A customer entity",
        }
    ]


@pytest.fixture
def mappings_dir(tmp_path):
    """Create a SKOS mapping file."""
    maps_dir = tmp_path / "mappings"
    maps_dir.mkdir()
    mapping_ttl = f"""
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
@prefix ex: <{NS}> .
@prefix erp: <https://kairos.cnext.eu/bronze/erp#> .

erp:customers
    skos:exactMatch ex:Customer ;
    kairos-map:mappingType "direct" .

erp:customers_name
    skos:exactMatch ex:customerName .

erp:customers_code
    skos:exactMatch ex:customerCode .
"""
    (maps_dir / "erp-mapping.ttl").write_text(mapping_ttl, encoding="utf-8")
    return maps_dir


@pytest.fixture
def sources_dir(tmp_path):
    """Create a source vocabulary file."""
    src_dir = tmp_path / "sources" / "erp"
    src_dir.mkdir(parents=True)
    vocab_ttl = """
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix erp: <https://kairos.cnext.eu/bronze/erp#> .

erp:customers
    rdf:type kairos-bronze:SourceTable ;
    kairos-bronze:tableName "customers" .

erp:customers_name
    rdf:type kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "name" ;
    kairos-bronze:belongsToTable erp:customers .

erp:customers_code
    rdf:type kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "code" ;
    kairos-bronze:belongsToTable erp:customers .

erp:customers_email
    rdf:type kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "email" ;
    kairos-bronze:belongsToTable erp:customers .
"""
    (src_dir / "erp.vocabulary.ttl").write_text(vocab_ttl, encoding="utf-8")
    return tmp_path / "sources"


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestXsdToSimpleType:
    def test_known_types(self):
        assert _xsd_to_simple_type(str(XSD.string)) == "string"
        assert _xsd_to_simple_type(str(XSD.integer)) == "integer"
        assert _xsd_to_simple_type(str(XSD.boolean)) == "boolean"
        assert _xsd_to_simple_type(str(XSD.dateTime)) == "dateTime"

    def test_unknown_type_defaults_to_string(self):
        assert _xsd_to_simple_type("http://example.com/Unknown") == "string"


class TestExtractProperties:
    def test_extracts_data_properties(self, domain_graph):
        props = _extract_properties(domain_graph, f"{NS}Customer")
        names = {p["name"] for p in props}
        assert "customerName" in names
        assert "customerCode" in names

    def test_identifies_property_types(self, domain_graph):
        props = _extract_properties(domain_graph, f"{NS}Customer")
        for p in props:
            assert p["type"] == "string"
            assert p["is_object_property"] is False


class TestExtractSilverMetadata:
    def test_extracts_natural_key_and_scd(self, domain_graph):
        meta = _extract_silver_metadata(domain_graph, f"{NS}Customer")
        assert meta["natural_key"] == ["customerCode"]
        assert meta["scd_type"] == "SCD2"

    def test_defaults_for_missing_annotations(self):
        g = Graph()
        cls = URIRef(f"{NS}Empty")
        g.add((cls, RDF.type, OWL.Class))
        meta = _extract_silver_metadata(g, f"{NS}Empty")
        assert meta["natural_key"] == []
        assert meta["scd_type"] == "SCD1"


class TestColumnBelongsToTable:
    def test_same_namespace(self):
        assert _column_belongs_to_table(
            "https://kairos.cnext.eu/bronze/erp#customers_name",
            "https://kairos.cnext.eu/bronze/erp#customers",
            {},
        )

    def test_different_namespace(self):
        assert not _column_belongs_to_table(
            "https://kairos.cnext.eu/bronze/other#col1",
            "https://kairos.cnext.eu/bronze/erp#customers",
            {},
        )


class TestExtractSystemName:
    def test_from_lookup(self):
        tables = {"erp": {"https://kairos.cnext.eu/bronze/erp#customers": []}}
        assert _extract_system_name(
            "https://kairos.cnext.eu/bronze/erp#customers", tables
        ) == "erp"

    def test_fallback_from_uri(self):
        assert _extract_system_name(
            "https://kairos.cnext.eu/bronze/erp#erp_customers", {}
        ) == "erp"


# ---------------------------------------------------------------------------
# Integration artifact generation
# ---------------------------------------------------------------------------


class TestGenerateIntegrationArtifacts:
    def test_produces_mapping_json(
        self, domain_graph, classes, mappings_dir, sources_dir
    ):
        artifacts = generate_integration_artifacts(
            classes=classes,
            graph=domain_graph,
            template_dir=Path("."),
            namespace=NS,
            ontology_name="test",
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
        )
        mapping_files = [k for k in artifacts if k.endswith("-mapping.json")]
        assert len(mapping_files) >= 1

        # Validate JSON structure
        content = json.loads(artifacts[mapping_files[0]])
        assert content["$schema"].startswith("https://kairos.cnext.eu/schemas/")
        assert content["metadata"]["entity"] == "Customer"
        assert content["metadata"]["domain"] == "test"
        assert content["source"]["mapping_type"] == "direct"
        assert content["target"]["scd_type"] == "SCD2"
        assert content["target"]["natural_key"] == ["customerCode"]

    def test_column_mappings_populated(
        self, domain_graph, classes, mappings_dir, sources_dir
    ):
        artifacts = generate_integration_artifacts(
            classes=classes,
            graph=domain_graph,
            template_dir=Path("."),
            namespace=NS,
            ontology_name="test",
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
        )
        mapping_files = [k for k in artifacts if k.endswith("-mapping.json")]
        content = json.loads(artifacts[mapping_files[0]])
        col_names = {cm["target_property"] for cm in content["column_mappings"]}
        assert "customerName" in col_names or "customerCode" in col_names

    def test_produces_manifest(
        self, domain_graph, classes, mappings_dir, sources_dir
    ):
        artifacts = generate_integration_artifacts(
            classes=classes,
            graph=domain_graph,
            template_dir=Path("."),
            namespace=NS,
            ontology_name="test",
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
        )
        manifest_files = [k for k in artifacts if k.endswith("manifest.json")]
        assert len(manifest_files) == 1
        manifest = json.loads(artifacts[manifest_files[0]])
        assert manifest["domain"] == "test"
        assert manifest["summary"]["total_entities"] >= 1

    def test_no_mappings_produces_empty(self, domain_graph, classes, tmp_path):
        """No SKOS mapping files → empty artifacts."""
        empty_maps = tmp_path / "empty_maps"
        empty_maps.mkdir()
        artifacts = generate_integration_artifacts(
            classes=classes,
            graph=domain_graph,
            template_dir=Path("."),
            namespace=NS,
            ontology_name="test",
            mappings_dir=empty_maps,
        )
        assert artifacts == {}

    def test_unmapped_columns_tracked(
        self, domain_graph, classes, mappings_dir, sources_dir
    ):
        artifacts = generate_integration_artifacts(
            classes=classes,
            graph=domain_graph,
            template_dir=Path("."),
            namespace=NS,
            ontology_name="test",
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
        )
        mapping_files = [k for k in artifacts if k.endswith("-mapping.json")]
        if mapping_files:
            content = json.loads(artifacts[mapping_files[0]])
            assert "unmapped_source_columns" in content
            assert "unmapped_target_properties" in content
