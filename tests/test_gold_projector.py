# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the gold layer projector (G1-G8 rules — Power BI star schema)."""

import textwrap
from pathlib import Path

import pytest
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD

from kairos_ontology.projections.gold_projector import (
    GoldColumnDef,
    GoldTableDef,
    _camel_to_snake,
    _classify_tables,
    _detect_ontology_uri,
    _generate_date_dimension,
    _mmd_type,
    _tmdl_guid,
    generate_gold_artifacts,
    generate_master_gold_erd,
    XSD_TO_GOLD_SQL,
    XSD_TO_TMDL,
    KAIROS_EXT,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE = "http://example.com/ont/test#"
EXT = Namespace("https://kairos.cnext.eu/ext#")
NS = Namespace(BASE)


def _make_graph(ttl: str) -> Graph:
    g = Graph()
    g.parse(data=textwrap.dedent(ttl), format="turtle")
    return g


def _simple_ontology() -> tuple[Graph, list[dict]]:
    """Minimal ontology: Customer (dimension), Order (fact) with FK to Customer."""
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:Customer a owl:Class ; rdfs:label "Customer"@en ; rdfs:comment "A customer."@en .
        ex:Product a owl:Class ; rdfs:label "Product"@en ; rdfs:comment "A product."@en .
        ex:Order a owl:Class ; rdfs:label "Order"@en ; rdfs:comment "An order."@en .

        ex:customerName a owl:DatatypeProperty ;
            rdfs:domain ex:Customer ;
            rdfs:range xsd:string ;
            rdfs:label "customer name"@en .

        ex:productName a owl:DatatypeProperty ;
            rdfs:domain ex:Product ;
            rdfs:range xsd:string ;
            rdfs:label "product name"@en .

        ex:orderDate a owl:DatatypeProperty ;
            rdfs:domain ex:Order ;
            rdfs:range xsd:date ;
            rdfs:label "order date"@en .

        ex:orderAmount a owl:DatatypeProperty ;
            rdfs:domain ex:Order ;
            rdfs:range xsd:decimal ;
            rdfs:label "order amount"@en .

        ex:hasCustomer a owl:ObjectProperty, owl:FunctionalProperty ;
            rdfs:domain ex:Order ;
            rdfs:range ex:Customer ;
            rdfs:label "has customer"@en .

        ex:hasProduct a owl:ObjectProperty, owl:FunctionalProperty ;
            rdfs:domain ex:Order ;
            rdfs:range ex:Product ;
            rdfs:label "has product"@en .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Customer", "name": "Customer", "label": "Customer", "comment": ""},
        {"uri": f"{BASE}Product", "name": "Product", "label": "Product", "comment": ""},
        {"uri": f"{BASE}Order", "name": "Order", "label": "Order", "comment": ""},
    ]
    return g, classes


def _ontology_with_reference() -> tuple[Graph, list[dict]]:
    """Ontology with reference data class."""
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:Country a owl:Class ; rdfs:label "Country"@en ; rdfs:comment "Country ref."@en .
        ex:Country kairos-ext:isReferenceData "true"^^xsd:boolean .

        ex:countryCode a owl:DatatypeProperty ;
            rdfs:domain ex:Country ;
            rdfs:range xsd:string ;
            rdfs:label "country code"@en .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Country", "name": "Country", "label": "Country", "comment": ""},
    ]
    return g, classes


# ---------------------------------------------------------------------------
# G1 — Star schema classification
# ---------------------------------------------------------------------------

class TestClassification:
    def test_fact_classification_by_fk_count(self):
        """G1: Class with ≥2 outgoing FK → fact."""
        g, classes = _simple_ontology()
        class_uris = {c["uri"] for c in classes}
        result = _classify_tables(g, classes, class_uris)
        assert result[f"{BASE}Order"] == "fact"

    def test_dimension_classification_no_fk(self):
        """G1: Class with no outgoing FK → dimension."""
        g, classes = _simple_ontology()
        class_uris = {c["uri"] for c in classes}
        result = _classify_tables(g, classes, class_uris)
        assert result[f"{BASE}Customer"] == "dimension"
        assert result[f"{BASE}Product"] == "dimension"

    def test_reference_data_always_dimension(self):
        """G6: isReferenceData → always dimension."""
        g, classes = _ontology_with_reference()
        class_uris = {c["uri"] for c in classes}
        result = _classify_tables(g, classes, class_uris)
        assert result[f"{BASE}Country"] == "dimension"

    def test_explicit_override(self):
        """G1: goldTableType override."""
        g, classes = _simple_ontology()
        # Force Customer to be a fact
        g.add((URIRef(f"{BASE}Customer"), KAIROS_EXT.goldTableType,
               Literal("fact")))
        class_uris = {c["uri"] for c in classes}
        result = _classify_tables(g, classes, class_uris)
        assert result[f"{BASE}Customer"] == "fact"


# ---------------------------------------------------------------------------
# G2 — dim_/fact_ prefixes
# ---------------------------------------------------------------------------

class TestGoldNaming:
    def test_fact_prefix(self):
        """G2: Fact tables get fact_ prefix."""
        g, classes = _simple_ontology()
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        ddl = result.get("test/test-gold-ddl.sql", "")
        assert "fact_order" in ddl

    def test_dimension_prefix(self):
        """G2: Dimension tables get dim_ prefix."""
        g, classes = _simple_ontology()
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        ddl = result.get("test/test-gold-ddl.sql", "")
        assert "dim_customer" in ddl

    def test_reference_gets_dim_prefix(self):
        """G6: Reference data gets dim_ prefix (not ref_ like silver)."""
        g, classes = _ontology_with_reference()
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        ddl = result.get("test/test-gold-ddl.sql", "")
        assert "dim_country" in ddl
        assert "ref_country" not in ddl


# ---------------------------------------------------------------------------
# G3 — SCD Type 2 on dimensions
# ---------------------------------------------------------------------------

class TestSCD2:
    def test_dimension_scd2_columns(self):
        """G3: Dimension tables with SCD2 get valid_from/valid_to/is_current."""
        g, classes = _simple_ontology()
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        ddl = result.get("test/test-gold-ddl.sql", "")
        # Customer dimension should have SCD2 columns
        assert "valid_from" in ddl
        assert "valid_to" in ddl
        assert "is_current" in ddl

    def test_fact_no_scd_columns(self):
        """G3: Fact tables never get SCD columns."""
        g, classes = _simple_ontology()
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        ddl = result.get("test/test-gold-ddl.sql", "")
        # Split by table creation to check fact specifically
        fact_section = ddl.split("fact_order")[1].split("CREATE TABLE")[0] \
            if "fact_order" in ddl else ""
        # valid_from should NOT be in the fact table section
        assert "valid_from" not in fact_section


# ---------------------------------------------------------------------------
# G8 — Power BI optimised types
# ---------------------------------------------------------------------------

class TestGoldTypes:
    def test_int_surrogate_keys(self):
        """G8: Surrogate keys are INT (not STRING like silver)."""
        g, classes = _simple_ontology()
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        ddl = result.get("test/test-gold-ddl.sql", "")
        assert "INT" in ddl
        # Should not have STRING surrogate keys
        assert "STRING NOT NULL  -- Surrogate key" not in ddl

    def test_boolean_maps_to_bit(self):
        """G8: BOOLEAN maps to BIT for Power BI."""
        assert XSD_TO_GOLD_SQL[str(XSD.boolean)] == "BIT"

    def test_tmdl_type_mapping(self):
        """G8: TMDL types map correctly."""
        assert XSD_TO_TMDL[str(XSD.string)] == "String"
        assert XSD_TO_TMDL[str(XSD.integer)] == "Int64"
        assert XSD_TO_TMDL[str(XSD.boolean)] == "Boolean"
        assert XSD_TO_TMDL[str(XSD.decimal)] == "Decimal"


# ---------------------------------------------------------------------------
# Date dimension
# ---------------------------------------------------------------------------

class TestDateDimension:
    def test_date_dim_generated_by_default(self):
        """Date dimension is generated by default."""
        g, classes = _simple_ontology()
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        ddl = result.get("test/test-gold-ddl.sql", "")
        assert "dim_date" in ddl
        assert "date_key" in ddl

    def test_date_dim_has_yyyymmdd_key(self):
        """Date dimension key is INT (YYYYMMDD format)."""
        dim = _generate_date_dimension("gold_test")
        assert dim.pk_column == "date_key"
        pk_col = [c for c in dim.columns if c.name == "date_key"][0]
        assert pk_col.sql_type == "INT"

    def test_date_dim_has_calendar_hierarchy(self):
        """Date dimension has Calendar hierarchy."""
        dim = _generate_date_dimension("gold_test")
        assert "Calendar" in dim.hierarchies

    def test_date_dim_disabled(self):
        """Date dimension can be disabled via annotation."""
        g, classes = _simple_ontology()
        onto_uri = URIRef(BASE.rstrip("#"))
        g.add((onto_uri, KAIROS_EXT.generateDateDimension,
               Literal("false", datatype=XSD.boolean)))
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        ddl = result.get("test/test-gold-ddl.sql", "")
        assert "dim_date" not in ddl


# ---------------------------------------------------------------------------
# Output artifacts
# ---------------------------------------------------------------------------

class TestOutputArtifacts:
    def test_ddl_file_generated(self):
        g, classes = _simple_ontology()
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        assert "test/test-gold-ddl.sql" in result

    def test_alter_file_generated(self):
        g, classes = _simple_ontology()
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        assert "test/test-gold-alter.sql" in result

    def test_erd_file_generated(self):
        g, classes = _simple_ontology()
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        assert "test/test-gold-erd.mmd" in result

    def test_tmdl_definition_generated(self):
        g, classes = _simple_ontology()
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        assert "test/semantic-model/definition.tmdl" in result

    def test_tmdl_tables_generated(self):
        g, classes = _simple_ontology()
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        tmdl_tables = [k for k in result if k.startswith("test/semantic-model/tables/")]
        assert len(tmdl_tables) >= 3  # dim_customer, dim_product, fact_order + dim_date

    def test_tmdl_relationships_generated(self):
        g, classes = _simple_ontology()
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        assert "test/semantic-model/relationships/relationships.tmdl" in result

    def test_views_for_scd2_dimensions(self):
        """SCD2 framing views generated for dimensions with SCD2."""
        g, classes = _simple_ontology()
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        views_key = "test/test-gold-views.sql"
        assert views_key in result
        views = result[views_key]
        assert "v_dim_customer" in views
        assert "WHERE is_current = 1" in views


# ---------------------------------------------------------------------------
# TMDL content validation
# ---------------------------------------------------------------------------

class TestTMDLContent:
    def test_tmdl_definition_has_direct_lake(self):
        g, classes = _simple_ontology()
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        defn = result["test/semantic-model/definition.tmdl"]
        assert "model Model" in defn
        assert "culture: en-US" in defn

    def test_tmdl_table_has_columns(self):
        g, classes = _simple_ontology()
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        # Find the customer dimension table TMDL
        cust_key = [k for k in result if "dim_customer" in k and k.endswith(".tmdl")]
        assert cust_key
        content = result[cust_key[0]]
        assert "table dim_customer" in content
        assert "column customer_sk" in content

    def test_tmdl_relationships_has_fk(self):
        g, classes = _simple_ontology()
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        rels = result["test/semantic-model/relationships/relationships.tmdl"]
        assert "relationship" in rels
        assert "fromColumn:" in rels
        assert "toColumn:" in rels

    def test_tmdl_partition_direct_lake(self):
        """TMDL tables use DirectLake mode."""
        g, classes = _simple_ontology()
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        cust_key = [k for k in result if "dim_customer" in k and k.endswith(".tmdl")]
        content = result[cust_key[0]]
        assert "directLake" in content


# ---------------------------------------------------------------------------
# G4 — GDPR satellite → secured dimension
# ---------------------------------------------------------------------------

class TestGDPR:
    def test_gdpr_satellite_generates_rls(self):
        """G4: GDPR satellite creates RLS role in TMDL."""
        ttl = f"""
            @prefix ex:  <{BASE}> .
            @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
            @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
            @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

            <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

            ex:Customer a owl:Class ; rdfs:label "Customer"@en ; rdfs:comment "Customer."@en .
            ex:CustomerPII a owl:Class ; rdfs:label "CustomerPII"@en ; rdfs:comment "PII."@en .
            ex:CustomerPII kairos-ext:gdprSatelliteOf ex:Customer .

            ex:customerName a owl:DatatypeProperty ;
                rdfs:domain ex:Customer ; rdfs:range xsd:string .
            ex:email a owl:DatatypeProperty ;
                rdfs:domain ex:CustomerPII ; rdfs:range xsd:string .
        """
        g = _make_graph(ttl)
        classes = [
            {"uri": f"{BASE}Customer", "name": "Customer", "label": "Customer", "comment": ""},
            {"uri": f"{BASE}CustomerPII", "name": "CustomerPII", "label": "CustomerPII", "comment": ""},
        ]
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        rls_key = "test/semantic-model/roles/rls-roles.tmdl"
        assert rls_key in result
        rls = result[rls_key]
        assert "role" in rls
        assert "Restrict_" in rls


# ---------------------------------------------------------------------------
# goldExclude
# ---------------------------------------------------------------------------

class TestGoldExclude:
    def test_excluded_class_not_in_output(self):
        g, classes = _simple_ontology()
        g.add((URIRef(f"{BASE}Product"), KAIROS_EXT.goldExclude,
               Literal("true", datatype=XSD.boolean)))
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        ddl = result.get("test/test-gold-ddl.sql", "")
        assert "dim_product" not in ddl


# ---------------------------------------------------------------------------
# Measures (DAX)
# ---------------------------------------------------------------------------

class TestMeasures:
    def test_measure_generates_dax_file(self):
        """Measures annotated with measureExpression generate DAX output."""
        ttl = f"""
            @prefix ex:  <{BASE}> .
            @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
            @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
            @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

            <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

            ex:Order a owl:Class ; rdfs:label "Order"@en ; rdfs:comment "Order."@en .
            ex:Order kairos-ext:goldTableType "fact" .

            ex:orderAmount a owl:DatatypeProperty ;
                rdfs:domain ex:Order ; rdfs:range xsd:decimal ;
                rdfs:label "order amount"@en ;
                kairos-ext:measureExpression "SUM([order_amount])" ;
                kairos-ext:measureFormatString "$#,##0.00" .
        """
        g = _make_graph(ttl)
        classes = [
            {"uri": f"{BASE}Order", "name": "Order", "label": "Order", "comment": ""},
        ]
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        dax_key = "test/measures/test-measures.dax"
        assert dax_key in result
        dax = result[dax_key]
        assert "SUM([order_amount])" in dax
        assert "$#,##0.00" in dax


# ---------------------------------------------------------------------------
# ERD content
# ---------------------------------------------------------------------------

class TestERD:
    def test_erd_star_schema_relationships(self):
        """ERD shows fact → dimension relationships."""
        g, classes = _simple_ontology()
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        erd = result.get("test/test-gold-erd.mmd", "")
        assert "erDiagram" in erd
        assert "FACT_ORDER" in erd
        assert "DIM_CUSTOMER" in erd


# ---------------------------------------------------------------------------
# Gold schema naming
# ---------------------------------------------------------------------------

class TestSchemaName:
    def test_default_schema(self):
        g, classes = _simple_ontology()
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        ddl = result.get("test/test-gold-ddl.sql", "")
        assert "gold_test" in ddl

    def test_custom_schema(self):
        g, classes = _simple_ontology()
        onto_uri = URIRef(BASE.rstrip("#"))
        g.add((onto_uri, KAIROS_EXT.goldSchema, Literal("custom_gold")))
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        ddl = result.get("test/test-gold-ddl.sql", "")
        assert "custom_gold" in ddl


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

class TestUtils:
    def test_tmdl_guid_deterministic(self):
        """TMDL GUID is deterministic for same input."""
        assert _tmdl_guid("test") == _tmdl_guid("test")

    def test_tmdl_guid_format(self):
        """TMDL GUID has correct format."""
        guid = _tmdl_guid("test")
        parts = guid.split("-")
        assert len(parts) == 5

    def test_mmd_type_sanitises(self):
        assert _mmd_type("DECIMAL(18,4)") == "DECIMAL_18_4"
        assert _mmd_type("VARCHAR(256)") == "VARCHAR_256"

    def test_camel_to_snake(self):
        assert _camel_to_snake("OrderLine") == "order_line"
        assert _camel_to_snake("hasCustomer") == "has_customer"


# ---------------------------------------------------------------------------
# Empty / edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_classes_returns_empty(self):
        g = Graph()
        result = generate_gold_artifacts([], g, BASE, ontology_name="test")
        assert result == {}

    def test_single_class_defaults_to_dimension(self):
        """A single class with no FK defaults to dimension."""
        ttl = f"""
            @prefix ex:  <{BASE}> .
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
            @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

            <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .
            ex:Widget a owl:Class ; rdfs:label "Widget"@en ; rdfs:comment "A widget."@en .
            ex:widgetName a owl:DatatypeProperty ;
                rdfs:domain ex:Widget ; rdfs:range xsd:string .
        """
        g = _make_graph(ttl)
        classes = [{"uri": f"{BASE}Widget", "name": "Widget", "label": "Widget", "comment": ""}]
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        ddl = result.get("test/test-gold-ddl.sql", "")
        assert "dim_widget" in ddl
        assert "fact_widget" not in ddl
