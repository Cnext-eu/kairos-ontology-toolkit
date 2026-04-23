# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unit tests for the mapping report projector."""

import textwrap
from pathlib import Path

import pytest
from rdflib import Graph

from kairos_ontology.projections.mapping_report_projector import (
    _build_report_data,
    _extract_ontology_properties,
    _parse_mappings,
    _parse_source_systems,
    generate_mapping_report,
)

# ── Fixture data ───────────────────────────────────────────────────────

VOCAB_TTL = textwrap.dedent("""\
    @prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix kb:   <https://kairos.cnext.eu/bronze#> .
    @prefix src:  <http://example.com/source/> .

    src:erp a kb:SourceSystem ;
        rdfs:label "ERP System" ;
        kb:database "erp_db" ;
        kb:schema "dbo" ;
        kb:connectionType "jdbc" .

    src:erp_customers a kb:SourceTable ;
        kb:sourceSystem src:erp ;
        kb:tableName "customers" ;
        rdfs:label "Customers" .

    src:erp_customers_id a kb:SourceColumn ;
        kb:sourceTable src:erp_customers ;
        kb:columnName "customer_id" ;
        kb:dataType "int" .

    src:erp_customers_name a kb:SourceColumn ;
        kb:sourceTable src:erp_customers ;
        kb:columnName "name" ;
        kb:dataType "varchar" .

    src:erp_customers_email a kb:SourceColumn ;
        kb:sourceTable src:erp_customers ;
        kb:columnName "email" ;
        kb:dataType "varchar" .
""")

MAPPING_TTL = textwrap.dedent("""\
    @prefix skos:  <http://www.w3.org/2004/02/skos/core#> .
    @prefix km:    <https://kairos.cnext.eu/mapping#> .
    @prefix src:   <http://example.com/source/> .
    @prefix onto:  <http://example.com/ontology#> .

    src:erp_customers skos:exactMatch onto:Customer ;
        km:mappingType "table" .

    src:erp_customers_id skos:exactMatch onto:customerId .

    src:erp_customers_name skos:closeMatch onto:customerName .
""")

ONTOLOGY_TTL = textwrap.dedent("""\
    @prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix onto: <http://example.com/ontology#> .

    onto:Customer a owl:Class ;
        rdfs:label "Customer" ;
        rdfs:comment "A customer entity" .

    onto:customerId a owl:DatatypeProperty ;
        rdfs:domain onto:Customer ;
        rdfs:label "Customer ID" ;
        rdfs:comment "Unique identifier" .

    onto:customerName a owl:DatatypeProperty ;
        rdfs:domain onto:Customer ;
        rdfs:label "Customer Name" ;
        rdfs:comment "Full name" .

    onto:customerEmail a owl:DatatypeProperty ;
        rdfs:domain onto:Customer ;
        rdfs:label "Email Address" ;
        rdfs:comment "Primary email" .
""")


# ── Helpers ────────────────────────────────────────────────────────────

@pytest.fixture
def sources_dir(tmp_path):
    d = tmp_path / "integration" / "sources" / "erp"
    d.mkdir(parents=True)
    (d / "erp.vocabulary.ttl").write_text(VOCAB_TTL, encoding="utf-8")
    return tmp_path / "integration" / "sources"


@pytest.fixture
def mappings_dir(tmp_path):
    d = tmp_path / "model" / "mappings" / "erp"
    d.mkdir(parents=True)
    (d / "erp-mapping.ttl").write_text(MAPPING_TTL, encoding="utf-8")
    return tmp_path / "model" / "mappings"


@pytest.fixture
def ontology_graph():
    g = Graph()
    g.parse(data=ONTOLOGY_TTL, format="turtle")
    return g


@pytest.fixture
def template_dir():
    return Path(__file__).resolve().parent.parent / "src" / "kairos_ontology" / "templates"


# ── Tests: _parse_source_systems ───────────────────────────────────────

class TestParseSourceSystems:
    def test_returns_empty_when_no_dir(self):
        assert _parse_source_systems(Path("/nonexistent")) == []

    def test_parses_system(self, sources_dir):
        systems = _parse_source_systems(sources_dir)
        assert len(systems) == 1
        s = systems[0]
        assert s["system_label"] == "ERP System"
        assert s["database"] == "erp_db"
        assert len(s["tables"]) == 1

    def test_parses_columns(self, sources_dir):
        systems = _parse_source_systems(sources_dir)
        cols = systems[0]["tables"][0]["columns"]
        names = {c["name"] for c in cols}
        assert names == {"customer_id", "name", "email"}


# ── Tests: _parse_mappings ─────────────────────────────────────────────

class TestParseMappings:
    def test_returns_empty_when_no_dir(self):
        result = _parse_mappings(Path("/nonexistent"))
        assert result["table_maps"] == {}
        assert result["column_maps"] == {}

    def test_parses_table_mapping(self, mappings_dir):
        result = _parse_mappings(mappings_dir)
        assert "http://example.com/source/erp_customers" in result["table_maps"]
        tm = result["table_maps"]["http://example.com/source/erp_customers"]
        assert tm["match_type"] == "exactMatch"
        assert tm["target_uri"] == "http://example.com/ontology#Customer"

    def test_parses_column_mappings(self, mappings_dir):
        result = _parse_mappings(mappings_dir)
        cm = result["column_maps"]
        assert "http://example.com/source/erp_customers_id" in cm
        assert cm["http://example.com/source/erp_customers_id"]["match_type"] == "exactMatch"
        assert "http://example.com/source/erp_customers_name" in cm
        assert cm["http://example.com/source/erp_customers_name"]["match_type"] == "closeMatch"

    def test_unmapped_column_not_in_maps(self, mappings_dir):
        result = _parse_mappings(mappings_dir)
        assert "http://example.com/source/erp_customers_email" not in result["column_maps"]


# ── Tests: _extract_ontology_properties ────────────────────────────────

class TestExtractOntologyProperties:
    def test_extracts_class(self, ontology_graph):
        classes = _extract_ontology_properties(ontology_graph, "http://example.com/ontology#")
        assert "http://example.com/ontology#Customer" in classes

    def test_extracts_properties(self, ontology_graph):
        classes = _extract_ontology_properties(ontology_graph, "http://example.com/ontology#")
        customer = classes["http://example.com/ontology#Customer"]
        prop_names = {v["name"] for v in customer["properties"].values()}
        assert prop_names == {"customerId", "customerName", "customerEmail"}

    def test_filters_by_namespace(self, ontology_graph):
        classes = _extract_ontology_properties(ontology_graph, "http://other.ns/")
        assert len(classes) == 0


# ── Tests: _build_report_data ──────────────────────────────────────────

class TestBuildReportData:
    def test_coverage_calculation(self, sources_dir, mappings_dir, ontology_graph):
        systems = _parse_source_systems(sources_dir)
        mappings = _parse_mappings(mappings_dir)
        classes = _extract_ontology_properties(ontology_graph, "http://example.com/ontology#")
        report = _build_report_data(systems[0], mappings, classes)

        # 2 of 3 columns mapped
        assert report["total_columns"] == 3
        assert report["total_mapped"] == 2
        assert report["overall_coverage_pct"] == 67

    def test_action_items_include_unmapped(self, sources_dir, mappings_dir, ontology_graph):
        systems = _parse_source_systems(sources_dir)
        mappings = _parse_mappings(mappings_dir)
        classes = _extract_ontology_properties(ontology_graph, "http://example.com/ontology#")
        report = _build_report_data(systems[0], mappings, classes)

        unmapped = [a for a in report["action_items"] if a["type"] == "unmapped_column"]
        assert len(unmapped) == 1
        assert "email" in unmapped[0]["column"]

    def test_action_items_include_non_exact(self, sources_dir, mappings_dir, ontology_graph):
        systems = _parse_source_systems(sources_dir)
        mappings = _parse_mappings(mappings_dir)
        classes = _extract_ontology_properties(ontology_graph, "http://example.com/ontology#")
        report = _build_report_data(systems[0], mappings, classes)

        reviews = [a for a in report["action_items"] if a["type"] == "review_match"]
        assert len(reviews) == 1
        assert "name" in reviews[0]["column"]

    def test_uncovered_properties(self, sources_dir, mappings_dir, ontology_graph):
        systems = _parse_source_systems(sources_dir)
        mappings = _parse_mappings(mappings_dir)
        classes = _extract_ontology_properties(ontology_graph, "http://example.com/ontology#")
        report = _build_report_data(systems[0], mappings, classes)

        uncovered_names = {p["property"] for p in report["uncovered_properties"]}
        assert "customerEmail" in uncovered_names


# ── Tests: generate_mapping_report (integration) ──────────────────────

class TestGenerateMappingReport:
    def test_produces_html(self, sources_dir, mappings_dir, ontology_graph, template_dir):
        classes = _extract_ontology_properties(ontology_graph, "http://example.com/ontology#")
        result = generate_mapping_report(
            ontology_classes=classes,
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
            template_dir=template_dir,
        )
        assert len(result) == 1
        fname = list(result.keys())[0]
        assert fname.endswith("-mapping-report.html")

        html = list(result.values())[0]
        assert "<!DOCTYPE html>" in html
        assert "ERP System" in html

    def test_html_contains_coverage(self, sources_dir, mappings_dir, ontology_graph, template_dir):
        classes = _extract_ontology_properties(ontology_graph, "http://example.com/ontology#")
        result = generate_mapping_report(
            ontology_classes=classes,
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
            template_dir=template_dir,
        )
        html = list(result.values())[0]
        assert "67%" in html

    def test_html_contains_match_badges(
        self, sources_dir, mappings_dir, ontology_graph, template_dir
    ):
        classes = _extract_ontology_properties(ontology_graph, "http://example.com/ontology#")
        result = generate_mapping_report(
            ontology_classes=classes,
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
            template_dir=template_dir,
        )
        html = list(result.values())[0]
        assert "Exact" in html
        assert "Close" in html
        assert "Unmapped" in html

    def test_returns_empty_when_no_sources(self, tmp_path, template_dir):
        result = generate_mapping_report(
            ontology_classes={},
            sources_dir=tmp_path / "empty",
            mappings_dir=tmp_path / "empty",
            template_dir=template_dir,
        )
        assert result == {}

    def test_html_contains_action_items(
        self, sources_dir, mappings_dir, ontology_graph, template_dir
    ):
        classes = _extract_ontology_properties(ontology_graph, "http://example.com/ontology#")
        result = generate_mapping_report(
            ontology_classes=classes,
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
            template_dir=template_dir,
        )
        html = list(result.values())[0]
        assert "Action Items" in html
        assert "email" in html.lower()

    def test_extracts_from_graph_if_no_classes(
        self, sources_dir, mappings_dir, ontology_graph, template_dir
    ):
        result = generate_mapping_report(
            ontology_classes=None,
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
            template_dir=template_dir,
            namespace="http://example.com/ontology#",
            graph=ontology_graph,
        )
        assert len(result) == 1
        html = list(result.values())[0]
        assert "Customer" in html
