# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the gold layer projector (G1-G8 rules — Power BI star schema)."""

import textwrap
from pathlib import Path

import pytest
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD

from kairos_ontology.projections.medallion_gold_projector import (
    GoldColumnDef,
    GoldTableDef,
    _camel_to_snake,
    _classify_tables,
    _detect_ontology_uri,
    _generate_date_dimension,
    _mmd_type,
    _tmdl_guid,
    _to_pascal_case,
    build_gold_tables,
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
        sm = "test/Test.SemanticModel/definition"
        assert f"{sm}/model.tmdl" in result

    def test_tmdl_tables_generated(self):
        g, classes = _simple_ontology()
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        sm = "test/Test.SemanticModel/definition"
        tmdl_tables = [k for k in result if k.startswith(f"{sm}/tables/")]
        assert len(tmdl_tables) >= 3  # dim_customer, dim_product, fact_order + dim_date

    def test_tmdl_relationships_generated(self):
        g, classes = _simple_ontology()
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        sm = "test/Test.SemanticModel/definition"
        assert f"{sm}/relationships/relationships.tmdl" in result

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
        defn = result["test/Test.SemanticModel/definition/model.tmdl"]
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
        sm = "test/Test.SemanticModel/definition"
        rels = result[f"{sm}/relationships/relationships.tmdl"]
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
        rls_key = "test/Test.SemanticModel/definition/roles/rls-roles.tmdl"
        assert rls_key in result
        rls = result[rls_key]
        assert "role" in rls
        assert "Restrict_" in rls

    def test_ols_restricted_column_generates_role(self):
        """OLS: olsRestricted columns generate a RestrictedColumns role."""
        ttl = f"""
            @prefix ex:  <{BASE}> .
            @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
            @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
            @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

            <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

            ex:Employee a owl:Class ; rdfs:label "Employee"@en ; rdfs:comment "Employee."@en .

            ex:employeeName a owl:DatatypeProperty ;
                rdfs:domain ex:Employee ; rdfs:range xsd:string .
            ex:salary a owl:DatatypeProperty ;
                rdfs:domain ex:Employee ; rdfs:range xsd:decimal ;
                kairos-ext:olsRestricted "true"^^xsd:boolean .
        """
        g = _make_graph(ttl)
        classes = [
            {"uri": f"{BASE}Employee", "name": "Employee", "label": "Employee", "comment": ""},
        ]
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        rls_key = "test/Test.SemanticModel/definition/roles/rls-roles.tmdl"
        assert rls_key in result
        rls = result[rls_key]
        assert "RestrictedColumns" in rls
        assert "columnPermission" in rls
        assert "salary" in rls


# ---------------------------------------------------------------------------
# Perspectives
# ---------------------------------------------------------------------------

class TestPerspectives:
    def test_perspective_generates_tmdl(self):
        """Classes with kairos-ext:perspective generate a perspectives.tmdl file."""
        ttl = f"""
            @prefix ex:  <{BASE}> .
            @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
            @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
            @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

            <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

            ex:Customer a owl:Class ; rdfs:label "Customer"@en ; rdfs:comment "Customer."@en .
            ex:Customer kairos-ext:perspective "Sales" .

            ex:Product a owl:Class ; rdfs:label "Product"@en ; rdfs:comment "Product."@en .
            ex:Product kairos-ext:perspective "Sales" .

            ex:customerName a owl:DatatypeProperty ;
                rdfs:domain ex:Customer ; rdfs:range xsd:string .
            ex:productName a owl:DatatypeProperty ;
                rdfs:domain ex:Product ; rdfs:range xsd:string .
        """
        g = _make_graph(ttl)
        classes = [
            {"uri": f"{BASE}Customer", "name": "Customer", "label": "Customer", "comment": ""},
            {"uri": f"{BASE}Product", "name": "Product", "label": "Product", "comment": ""},
        ]
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        persp_key = "test/Test.SemanticModel/definition/perspectives/perspectives.tmdl"
        assert persp_key in result
        content = result[persp_key]
        assert "perspective 'Sales'" in content
        assert "perspectiveTable dim_customer" in content

    def test_no_perspective_no_file(self):
        """No perspective file generated when no annotations present."""
        g, classes = _simple_ontology()
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        persp_keys = [k for k in result if "perspectives" in k]
        assert len(persp_keys) == 0


# ---------------------------------------------------------------------------
# Calculation groups (time intelligence)
# ---------------------------------------------------------------------------

class TestCalculationGroups:
    def test_time_intelligence_generates_file(self):
        """generateTimeIntelligence = true creates a calculation group."""
        g, classes = _simple_ontology()
        onto_uri = URIRef(BASE.rstrip("#"))
        g.add((onto_uri, KAIROS_EXT.generateTimeIntelligence,
               Literal("true", datatype=XSD.boolean)))
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        cg_key = "test/Test.SemanticModel/definition/calculationGroups/time-intelligence.tmdl"
        assert cg_key in result
        content = result[cg_key]
        assert "calculationGroup" in content
        assert "YTD" in content
        assert "QTD" in content
        assert "MTD" in content
        assert "SAMEPERIODLASTYEAR" in content

    def test_no_time_intelligence_by_default(self):
        """No calculation group generated when annotation is absent."""
        g, classes = _simple_ontology()
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        cg_keys = [k for k in result if "calculationGroups" in k]
        assert len(cg_keys) == 0


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

    def test_to_pascal_case(self):
        assert _to_pascal_case("test") == "Test"
        assert _to_pascal_case("supply_chain") == "SupplyChain"
        assert _to_pascal_case("supply-chain") == "SupplyChain"
        assert _to_pascal_case("hr") == "Hr"


# ---------------------------------------------------------------------------
# TMDL folder structure (standard Power BI layout)
# ---------------------------------------------------------------------------

class TestTMDLFolderStructure:
    def test_semantic_model_folder_uses_pascal_case(self):
        """TMDL files live under {Domain}.SemanticModel/definition/."""
        g, classes = _simple_ontology()
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        sm = "test/Test.SemanticModel/definition"
        assert f"{sm}/model.tmdl" in result
        tables = [k for k in result if f"{sm}/tables/" in k]
        assert len(tables) >= 3
        rels = [k for k in result if f"{sm}/relationships/" in k]
        assert len(rels) == 1

    def test_model_tmdl_filename(self):
        """Root TMDL file is model.tmdl (not definition.tmdl)."""
        g, classes = _simple_ontology()
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        model_keys = [k for k in result if k.endswith("model.tmdl")]
        assert len(model_keys) == 1
        assert "definition.tmdl" not in " ".join(result.keys())


# ---------------------------------------------------------------------------
# Business-friendly display names (PBI_Description)
# ---------------------------------------------------------------------------

class TestBusinessFriendlyNames:
    def test_tmdl_column_has_pbi_description(self):
        """Columns with rdfs:label get PBI_Description annotation."""
        g, classes = _simple_ontology()
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        cust_key = [k for k in result if "dim_customer" in k and k.endswith(".tmdl")]
        assert cust_key
        content = result[cust_key[0]]
        assert "PBI_Description" in content

    def test_tmdl_measure_has_description(self):
        """Measures get a description property in TMDL."""
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

            ex:totalSales a owl:DatatypeProperty ;
                rdfs:domain ex:Order ; rdfs:range xsd:decimal ;
                rdfs:label "Total Sales"@en ;
                kairos-ext:measureExpression "SUM([order_amount])" ;
                kairos-ext:measureFormatString "$#,##0.00" .
        """
        g = _make_graph(ttl)
        classes = [
            {"uri": f"{BASE}Order", "name": "Order", "label": "Order", "comment": ""},
        ]
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        fact_key = [k for k in result if "fact_order" in k and k.endswith(".tmdl")]
        assert fact_key
        content = result[fact_key[0]]
        assert 'description:' in content


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


# ---------------------------------------------------------------------------
# G5 — Class-per-table inheritance (default)
# ---------------------------------------------------------------------------

def _ontology_with_subclasses(extra_onto_annotations: str = "") -> tuple[Graph, list[dict]]:
    """Ontology with Party (parent) → LegalEntity, SoleProprietorship (subtypes)."""
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        <{BASE.rstrip('#')}> a owl:Ontology ;
            rdfs:label "Test"@en ;
            owl:versionInfo "1.0" {extra_onto_annotations} .

        ex:Party a owl:Class ; rdfs:label "Party"@en ; rdfs:comment "A party."@en .
        ex:LegalEntity a owl:Class ;
            rdfs:subClassOf ex:Party ;
            rdfs:label "Legal Entity"@en ;
            rdfs:comment "A legal entity."@en .
        ex:SoleProprietorship a owl:Class ;
            rdfs:subClassOf ex:Party ;
            rdfs:label "Sole Proprietorship"@en ;
            rdfs:comment "A sole proprietorship."@en .

        ex:partyName a owl:DatatypeProperty ;
            rdfs:domain ex:Party ;
            rdfs:range xsd:string ;
            rdfs:label "party name"@en .

        ex:registrationNumber a owl:DatatypeProperty ;
            rdfs:domain ex:LegalEntity ;
            rdfs:range xsd:string ;
            rdfs:label "registration number"@en .

        ex:ownerName a owl:DatatypeProperty ;
            rdfs:domain ex:SoleProprietorship ;
            rdfs:range xsd:string ;
            rdfs:label "owner name"@en .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Party", "name": "Party", "label": "Party", "comment": ""},
        {"uri": f"{BASE}LegalEntity", "name": "LegalEntity",
         "label": "Legal Entity", "comment": ""},
        {"uri": f"{BASE}SoleProprietorship", "name": "SoleProprietorship",
         "label": "Sole Proprietorship", "comment": ""},
    ]
    return g, classes


class TestClassPerTable:
    """G5: Default class-per-table inheritance generates separate subtype tables."""

    def test_subtypes_get_separate_tables(self):
        """Each subclass produces its own gold table."""
        g, classes = _ontology_with_subclasses()
        tables = build_gold_tables(classes, g, BASE, ontology_name="test")
        table_names = {t.name for t in tables}
        assert "dim_party" in table_names
        assert "dim_legal_entity" in table_names
        assert "dim_sole_proprietorship" in table_names

    def test_subtype_pk_is_parent_sk(self):
        """Subtype table PK is the parent's surrogate key (shared PK)."""
        g, classes = _ontology_with_subclasses()
        tables = build_gold_tables(classes, g, BASE, ontology_name="test")
        by_name = {t.name: t for t in tables}
        le = by_name["dim_legal_entity"]
        assert le.pk_column == "party_sk"

    def test_subtype_has_fk_to_parent(self):
        """Subtype table has FK constraint referencing parent table."""
        g, classes = _ontology_with_subclasses()
        tables = build_gold_tables(classes, g, BASE, ontology_name="test")
        by_name = {t.name: t for t in tables}
        le = by_name["dim_legal_entity"]
        fk_targets = [fk[1] for fk in le.fk_constraints]
        assert any("dim_party" in t for t in fk_targets)

    def test_subtype_has_own_properties_only(self):
        """Subtype table contains only its own properties, not inherited ones."""
        g, classes = _ontology_with_subclasses()
        tables = build_gold_tables(classes, g, BASE, ontology_name="test")
        by_name = {t.name: t for t in tables}
        le = by_name["dim_legal_entity"]
        col_names = {c.name for c in le.columns}
        assert "registration_number" in col_names
        assert "party_name" not in col_names

    def test_parent_has_shared_properties(self):
        """Parent table retains its own (shared) properties."""
        g, classes = _ontology_with_subclasses()
        tables = build_gold_tables(classes, g, BASE, ontology_name="test")
        by_name = {t.name: t for t in tables}
        party = by_name["dim_party"]
        col_names = {c.name for c in party.columns}
        assert "party_name" in col_names

    def test_parent_has_no_discriminator(self):
        """Parent table does NOT have a discriminator column in class-per-table mode."""
        g, classes = _ontology_with_subclasses()
        tables = build_gold_tables(classes, g, BASE, ontology_name="test")
        by_name = {t.name: t for t in tables}
        party = by_name["dim_party"]
        col_names = {c.name for c in party.columns}
        assert "party_type" not in col_names

    def test_ddl_contains_subtype_tables(self):
        """DDL output includes CREATE TABLE for subtype tables."""
        g, classes = _ontology_with_subclasses()
        result = generate_gold_artifacts(classes, g, BASE, ontology_name="test")
        ddl = result.get("test/test-gold-ddl.sql", "")
        assert "dim_legal_entity" in ddl
        assert "dim_sole_proprietorship" in ddl


class TestDiscriminatorOptIn:
    """G5: Explicit discriminator strategy preserves old flattening behaviour."""

    def test_discriminator_flattens_subtypes(self):
        """With goldInheritanceStrategy 'discriminator', subtypes fold into parent."""
        g, classes = _ontology_with_subclasses(
            '; kairos-ext:goldInheritanceStrategy "discriminator"')
        tables = build_gold_tables(classes, g, BASE, ontology_name="test")
        table_names = {t.name for t in tables}
        assert "dim_party" in table_names
        assert "dim_legal_entity" not in table_names
        assert "dim_sole_proprietorship" not in table_names

    def test_discriminator_adds_discriminator_col(self):
        """Discriminator strategy adds a type column on the parent."""
        g, classes = _ontology_with_subclasses(
            '; kairos-ext:goldInheritanceStrategy "discriminator"')
        tables = build_gold_tables(classes, g, BASE, ontology_name="test")
        by_name = {t.name: t for t in tables}
        party = by_name["dim_party"]
        col_names = {c.name for c in party.columns}
        assert "party_type" in col_names

    def test_discriminator_merges_subtype_props(self):
        """Discriminator strategy merges subtype properties into parent table."""
        g, classes = _ontology_with_subclasses(
            '; kairos-ext:goldInheritanceStrategy "discriminator"')
        tables = build_gold_tables(classes, g, BASE, ontology_name="test")
        by_name = {t.name: t for t in tables}
        party = by_name["dim_party"]
        col_names = {c.name for c in party.columns}
        assert "registration_number" in col_names
        assert "owner_name" in col_names
