# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unit tests for the mapping report projector."""

import textwrap
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from rdflib import Graph

from kairos_ontology.core.projections.report_projector import (
    ReportContractItem,
    _build_entity_view,
    _build_report_data,
    _extract_domain_prefix,
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
    @prefix map:   <http://example.com/mapping#> .
    @prefix src:   <http://example.com/source/> .
    @prefix onto:  <http://example.com/ontology#> .

    src:erp_customers skos:exactMatch onto:Customer .

    src:erp_customers_id skos:exactMatch onto:customerId .

    src:erp_customers_name skos:closeMatch onto:customerName .
    map:table a km:TableMapping ;
        km:sourceTable src:erp_customers ;
        km:targetClass onto:Customer ;
        km:mappingType "split" ;
        km:matchType "exactMatch" ;
        km:rowFilter map:filter .
    map:id a km:ColumnMapping ;
        km:sourceColumn src:erp_customers_id ;
        km:targetProperty onto:customerId ;
        km:matchType "exactMatch" .
    map:name a km:ColumnMapping ;
        km:sourceColumn src:erp_customers_name ;
        km:targetProperty onto:customerName ;
        km:matchType "closeMatch" ;
        km:expression map:upperName .
    map:filter a km:LiteralExpression ;
        km:literalValue true ;
        km:outputType "boolean" ;
        km:nullable false ;
        km:nullPolicy "never-null" ;
        km:determinism "deterministic" ;
        km:requiresCapability "typed-literal" .
    map:upperName a km:FunctionExpression ;
        km:function "upper" ;
        km:arguments ( map:nameInput ) ;
        km:outputType "string" ;
        km:nullable true ;
        km:nullPolicy "propagate" ;
        km:determinism "deterministic" ;
        km:requiresCapability "scalar-function" .
    map:nameInput a km:SourceColumnExpression ;
        km:sourceColumn src:erp_customers_name ;
        km:outputType "string" ;
        km:nullable true ;
        km:nullPolicy "propagate" ;
        km:determinism "deterministic" ;
        km:requiresCapability "source-column" .
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
        entries = result["table_maps"]["http://example.com/source/erp_customers"]
        assert len(entries) >= 1
        tm = entries[0]
        assert tm["match_type"] == "exactMatch"
        assert tm["target_uri"] == "http://example.com/ontology#Customer"

    def test_parses_column_mappings(self, mappings_dir):
        result = _parse_mappings(mappings_dir)
        cm = result["column_maps"]
        assert "http://example.com/source/erp_customers_id" in cm
        entries = cm["http://example.com/source/erp_customers_id"]
        assert entries[0]["match_type"] == "exactMatch"
        assert "http://example.com/source/erp_customers_name" in cm
        assert cm["http://example.com/source/erp_customers_name"][0]["match_type"] == "closeMatch"

    def test_unmapped_column_not_in_maps(self, mappings_dir):
        result = _parse_mappings(mappings_dir)
        assert "http://example.com/source/erp_customers_email" not in result["column_maps"]

    def test_extracts_expression_contract(self, mappings_dir):
        result = _parse_mappings(mappings_dir)
        cm = result["column_maps"]
        id_entry = cm["http://example.com/source/erp_customers_id"][0]
        assert id_entry["expression_contract"] == "direct source-column reference"
        name_entry = cm["http://example.com/source/erp_customers_name"][0]
        assert name_entry["expression_contract"] == "function upper"

    def test_extracts_row_filter_contract(self, mappings_dir):
        result = _parse_mappings(mappings_dir)
        table = result["table_maps"]["http://example.com/source/erp_customers"][0]
        assert table["filter_condition"] == "typed literal (boolean)"

    def test_extracts_mapping_type(self, mappings_dir):
        result = _parse_mappings(mappings_dir)
        tm = result["table_maps"]["http://example.com/source/erp_customers"]
        assert tm[0]["mapping_type"] == "split"


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


# ── Tests: _extract_domain_prefix ──────────────────────────────────────

class TestExtractDomainPrefix:
    def test_hash_namespace(self):
        assert _extract_domain_prefix("http://example.com/ont/client#something") == "client"

    def test_slash_namespace(self):
        assert _extract_domain_prefix("http://example.com/ont/party/something") == "party"


# ── Tests: _build_report_data ──────────────────────────────────────────

class TestBuildReportData:
    def test_contract_item_is_typed_and_immutable(self):
        item = ReportContractItem("mapping-route", "customers: split", "table mapping")

        with pytest.raises(FrozenInstanceError):
            item.value = "changed"

    def test_contract_payload_has_deterministic_lanes(
        self, sources_dir, mappings_dir, ontology_graph
    ):
        systems = _parse_source_systems(sources_dir)
        mappings = _parse_mappings(mappings_dir)
        classes = _extract_ontology_properties(ontology_graph, "http://example.com/ontology#")

        contract = _build_report_data(systems[0], mappings, classes)["report_contract"]

        assert list(contract) == ["schema_version", "lanes"]
        assert [lane["key"] for lane in contract["lanes"]] == [
            "normative-effective-policy",
            "implemented-generated-artifacts-checks",
            "approved-deviations-known-limitations",
            "downstream-runtime-observations",
        ]
        assert [section["key"] for section in contract["lanes"][0]["sections"]] == [
            "prep-routing-transformations",
            "identity-grain-lineage-multi-source",
            "cdc-scd-fk-hash-dq",
            "gold-product-contract",
            "governance-expectations",
            "adapter-capability-compile-evidence",
            "strict-release-blockers",
        ]

    def test_runtime_observations_are_explicitly_not_evaluated(
        self, sources_dir, mappings_dir, ontology_graph
    ):
        systems = _parse_source_systems(sources_dir)
        mappings = _parse_mappings(mappings_dir)
        classes = _extract_ontology_properties(ontology_graph, "http://example.com/ontology#")

        runtime = _build_report_data(systems[0], mappings, classes)["report_contract"]["lanes"][3]

        assert runtime["key"] == "downstream-runtime-observations"
        assert {section["status"] for section in runtime["sections"]} == {"not-evaluated"}
        assert all("does not observe" in section["reason"] for section in runtime["sections"])

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

    def test_match_distribution(self, sources_dir, mappings_dir, ontology_graph):
        systems = _parse_source_systems(sources_dir)
        mappings = _parse_mappings(mappings_dir)
        classes = _extract_ontology_properties(ontology_graph, "http://example.com/ontology#")
        report = _build_report_data(systems[0], mappings, classes)

        dist = report["match_distribution"]
        assert dist["exactMatch"] == 1
        assert dist["closeMatch"] == 1

    def test_domain_coverage(self, sources_dir, mappings_dir, ontology_graph):
        systems = _parse_source_systems(sources_dir)
        mappings = _parse_mappings(mappings_dir)
        classes = _extract_ontology_properties(ontology_graph, "http://example.com/ontology#")
        report = _build_report_data(systems[0], mappings, classes)

        assert report["total_domain_properties"] == 3
        assert report["covered_domain_properties"] == 2
        assert report["domain_coverage_pct"] == 67

    def test_action_item_counts(self, sources_dir, mappings_dir, ontology_graph):
        systems = _parse_source_systems(sources_dir)
        mappings = _parse_mappings(mappings_dir)
        classes = _extract_ontology_properties(ontology_graph, "http://example.com/ontology#")
        report = _build_report_data(systems[0], mappings, classes)

        assert report["error_count"] == 0
        assert report["warning_count"] == 1
        assert report["info_count"] == 1

    def test_expression_contract_in_column_report(
        self, sources_dir, mappings_dir, ontology_graph
    ):
        systems = _parse_source_systems(sources_dir)
        mappings = _parse_mappings(mappings_dir)
        classes = _extract_ontology_properties(ontology_graph, "http://example.com/ontology#")
        report = _build_report_data(systems[0], mappings, classes)

        tbl = report["tables"][0]
        mapped_cols = [c for c in tbl["columns"] if c["mapped"]]
        expressions = {
            c["source_name"]: c["expression_contract"] for c in mapped_cols
        }
        assert expressions["customer_id"] == "direct source-column reference"
        assert expressions["name"] == "function upper"

    def test_entity_view_present(self, sources_dir, mappings_dir, ontology_graph):
        systems = _parse_source_systems(sources_dir)
        mappings = _parse_mappings(mappings_dir)
        classes = _extract_ontology_properties(ontology_graph, "http://example.com/ontology#")
        report = _build_report_data(systems[0], mappings, classes)

        assert "entity_view" in report
        assert len(report["entity_view"]) >= 1
        entity = report["entity_view"][0]
        assert entity["name"] == "Customer"
        assert len(entity["column_mappings"]) == 2


# ── Tests: _build_entity_view ──────────────────────────────────────────

class TestBuildEntityView:
    def test_groups_by_target_entity(self, sources_dir, mappings_dir, ontology_graph):
        systems = _parse_source_systems(sources_dir)
        mappings = _parse_mappings(mappings_dir)
        classes = _extract_ontology_properties(ontology_graph, "http://example.com/ontology#")
        entities = _build_entity_view(systems[0], mappings, classes)

        assert len(entities) >= 1
        customer = next(e for e in entities if e["name"] == "Customer")
        assert customer["label"] == "Customer"
        assert customer["comment"] == "A customer entity"

    def test_entity_has_column_mappings(self, sources_dir, mappings_dir, ontology_graph):
        systems = _parse_source_systems(sources_dir)
        mappings = _parse_mappings(mappings_dir)
        classes = _extract_ontology_properties(ontology_graph, "http://example.com/ontology#")
        entities = _build_entity_view(systems[0], mappings, classes)

        customer = next(e for e in entities if e["name"] == "Customer")
        col_names = {cm["source_column"] for cm in customer["column_mappings"]}
        assert col_names == {"customer_id", "name"}

    def test_entity_has_source_tables(self, sources_dir, mappings_dir, ontology_graph):
        systems = _parse_source_systems(sources_dir)
        mappings = _parse_mappings(mappings_dir)
        classes = _extract_ontology_properties(ontology_graph, "http://example.com/ontology#")
        entities = _build_entity_view(systems[0], mappings, classes)

        customer = next(e for e in entities if e["name"] == "Customer")
        assert len(customer["source_tables"]) >= 1
        assert customer["source_tables"][0]["table_name"] == "customers"

    def test_entity_column_has_expression_contract(
        self, sources_dir, mappings_dir, ontology_graph
    ):
        systems = _parse_source_systems(sources_dir)
        mappings = _parse_mappings(mappings_dir)
        classes = _extract_ontology_properties(ontology_graph, "http://example.com/ontology#")
        entities = _build_entity_view(systems[0], mappings, classes)

        customer = next(e for e in entities if e["name"] == "Customer")
        name_map = next(
            cm
            for cm in customer["column_mappings"]
            if cm["source_column"] == "name"
        )
        assert name_map["expression_contract"] == "function upper"


# ── Tests: generate_mapping_report (integration) ──────────────────────

class TestGenerateMappingReport:
    def test_produces_html_and_markdown(self, sources_dir, mappings_dir, ontology_graph, template_dir):
        classes = _extract_ontology_properties(ontology_graph, "http://example.com/ontology#")
        result = generate_mapping_report(
            ontology_classes=classes,
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
            template_dir=template_dir,
        )
        assert len(result) == 2
        fnames = list(result.keys())
        assert any(f.endswith("-mapping-report.html") for f in fnames)
        assert any(f.endswith("-mapping-report.md") for f in fnames)

        html = result[next(f for f in fnames if f.endswith(".html"))]
        assert "<!DOCTYPE html>" in html
        assert "ERP System" in html

        md = result[next(f for f in fnames if f.endswith(".md"))]
        assert "ERP System" in md

    def test_html_contains_coverage(self, sources_dir, mappings_dir, ontology_graph, template_dir):
        classes = _extract_ontology_properties(ontology_graph, "http://example.com/ontology#")
        result = generate_mapping_report(
            ontology_classes=classes,
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
            template_dir=template_dir,
        )
        html = next(v for k, v in result.items() if k.endswith(".html"))
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
        html = next(v for k, v in result.items() if k.endswith(".html"))
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
        html = next(v for k, v in result.items() if k.endswith(".html"))
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
        assert len(result) == 2
        html = next(v for k, v in result.items() if k.endswith(".html"))
        assert "Customer" in html

    def test_html_contains_data_flow(
        self, sources_dir, mappings_dir, ontology_graph, template_dir
    ):
        classes = _extract_ontology_properties(ontology_graph, "http://example.com/ontology#")
        result = generate_mapping_report(
            ontology_classes=classes,
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
            template_dir=template_dir,
        )
        html = next(v for k, v in result.items() if k.endswith(".html"))
        assert "Data Flow Overview" in html
        assert "Bronze Layer" in html
        assert "Silver Layer" in html

    def test_html_contains_entity_view(
        self, sources_dir, mappings_dir, ontology_graph, template_dir
    ):
        classes = _extract_ontology_properties(ontology_graph, "http://example.com/ontology#")
        result = generate_mapping_report(
            ontology_classes=classes,
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
            template_dir=template_dir,
        )
        html = next(v for k, v in result.items() if k.endswith(".html"))
        assert "Domain Entity Details" in html

    def test_html_contains_expression_contract(
        self, sources_dir, mappings_dir, ontology_graph, template_dir
    ):
        classes = _extract_ontology_properties(ontology_graph, "http://example.com/ontology#")
        result = generate_mapping_report(
            ontology_classes=classes,
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
            template_dir=template_dir,
        )
        html = next(v for k, v in result.items() if k.endswith(".html"))
        assert "Expression Contract" in html
        assert "function upper" in html

    def test_html_contains_match_distribution(
        self, sources_dir, mappings_dir, ontology_graph, template_dir
    ):
        classes = _extract_ontology_properties(ontology_graph, "http://example.com/ontology#")
        result = generate_mapping_report(
            ontology_classes=classes,
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
            template_dir=template_dir,
        )
        html = next(v for k, v in result.items() if k.endswith(".html"))
        assert "Match Type Distribution" in html

    def test_outputs_distinguish_contract_lanes_and_runtime_boundary(
        self, sources_dir, mappings_dir, ontology_graph, template_dir
    ):
        classes = _extract_ontology_properties(ontology_graph, "http://example.com/ontology#")
        result = generate_mapping_report(
            ontology_classes=classes,
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
            template_dir=template_dir,
        )

        for content in result.values():
            assert "Normative / effective policy" in content
            assert "Implemented / generated artifacts and checks" in content
            assert "Approved deviations / known limitations" in content
            assert "Downstream runtime observations" in content
            assert "not-evaluated" in content
