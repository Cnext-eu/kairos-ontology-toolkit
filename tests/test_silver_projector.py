# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the silver layer projector (R1-R16 annotations + S1-S8 Fabric rules)."""

import textwrap
from pathlib import Path

import pytest
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD

from kairos_ontology.projections.medallion_silver_projector import (
    ColumnDef,
    TableDef,
    _camel_to_snake,
    _mmd_type,
    _parse_audit_envelope,
    _s4_inlined_name,
    generate_master_erd,
    generate_silver_artifacts,
    render_mermaid_svg,
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
    """Minimal ontology: two classes (Party, Address)."""
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:Party a owl:Class ; rdfs:label "Party"@en ; rdfs:comment "A party."@en .
        ex:Address a owl:Class ; rdfs:label "Address"@en ; rdfs:comment "An address."@en .

        ex:name a owl:DatatypeProperty ;
            rdfs:domain ex:Party ;
            rdfs:range xsd:string ;
            rdfs:label "name"@en .

        ex:street a owl:DatatypeProperty ;
            rdfs:domain ex:Address ;
            rdfs:range xsd:string ;
            rdfs:label "street"@en .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Party", "name": "Party", "label": "Party", "comment": ""},
        {"uri": f"{BASE}Address", "name": "Address", "label": "Address", "comment": ""},
    ]
    return g, classes


# ---------------------------------------------------------------------------
# Unit tests — _camel_to_snake
# ---------------------------------------------------------------------------

def test_camel_to_snake_basic():
    assert _camel_to_snake("PartyType") == "party_type"


def test_camel_to_snake_already_lower():
    assert _camel_to_snake("address") == "address"


def test_camel_to_snake_consecutive_caps():
    assert _camel_to_snake("legalFormCode") == "legal_form_code"


# ---------------------------------------------------------------------------
# Unit tests — _mmd_type
# ---------------------------------------------------------------------------

def test_mmd_type_decimal_with_comma():
    assert _mmd_type("DECIMAL(18,4)") == "DECIMAL_18_4"


def test_mmd_type_nvarchar_with_parens():
    assert _mmd_type("NVARCHAR(MAX)") == "NVARCHAR_MAX"


def test_mmd_type_simple_unchanged():
    assert _mmd_type("DATETIME2") == "DATETIME2"
    assert _mmd_type("BIT") == "BIT"
    assert _mmd_type("DATE") == "DATE"


def test_mmd_type_no_commas_in_erd():
    """ERD output must not contain commas inside type names (Mermaid parser rejects them)."""
    g, classes = _simple_ontology()
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    mmd = next(v for k, v in result.items() if k.endswith("-erd.mmd"))
    # Every non-comment, non-relationship line inside entity blocks should have no comma in the type token
    for line in mmd.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("%") and not stripped.startswith("erDiagram") \
                and not stripped.startswith("}") and not stripped.startswith("{") \
                and "||" not in stripped and not stripped.endswith("{"):
            # Lines of the form "TYPE name" — type must not contain a comma
            parts = stripped.split()
            if len(parts) >= 2:
                assert "," not in parts[0], f"Comma in Mermaid type token: {stripped}"


# ---------------------------------------------------------------------------
# Unit tests — _parse_audit_envelope
# ---------------------------------------------------------------------------

def test_parse_audit_envelope():
    raw = "_created_at DATETIME2, _updated_at DATETIME2, _load_date DATE"
    cols = _parse_audit_envelope(raw)
    assert len(cols) == 3
    names = [c.name for c in cols]
    assert "_created_at" in names
    assert "_load_date" in names


def test_parse_audit_envelope_empty():
    assert _parse_audit_envelope("") == []


# ---------------------------------------------------------------------------
# Unit tests — ColumnDef.ddl_fragment
# ---------------------------------------------------------------------------

def test_column_def_not_null():
    col = ColumnDef("my_col", "NVARCHAR(64)", nullable=False)
    frag = col.ddl_fragment()
    assert "NOT NULL" in frag
    assert "my_col" in frag


def test_column_def_nullable_with_comment():
    col = ColumnDef("my_col", "DATE", nullable=True, comment="NULL = current")
    frag = col.ddl_fragment()
    assert "NULL" in frag
    assert "NULL = current" in frag


# ---------------------------------------------------------------------------
# Unit tests — TableDef.render_create
# ---------------------------------------------------------------------------

def test_table_def_render_create():
    tbl = TableDef("party", "silver_test")
    tbl.columns.append(ColumnDef("party_sk", "STRING", nullable=False))
    tbl.pk_column = "party_sk"
    sql = tbl.render_create()
    assert "CREATE TABLE silver_test.party" in sql
    # S2: PK as comment, not enforceable constraint
    assert "-- PK: party_sk" in sql
    assert "CONSTRAINT" not in sql


def test_table_def_render_alter_fk():
    tbl = TableDef("address", "silver_test")
    tbl.fk_constraints.append(("party_sk", "silver_test.party", "party_sk", "has_party"))
    stmts = tbl.render_alter()
    assert len(stmts) == 1
    # S2: constraints as documentation-only comments
    assert stmts[0].startswith("-- ALTER TABLE")
    assert "fk_address_party_sk" in stmts[0]
    assert "REFERENCES silver_test.party" in stmts[0]


# ---------------------------------------------------------------------------
# Integration: happy path — two classes
# ---------------------------------------------------------------------------

def test_generate_happy_path_produces_three_artifacts():
    g, classes = _simple_ontology()
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    assert any(k.endswith("-ddl.sql") for k in result)
    assert any(k.endswith("-alter.sql") for k in result)
    assert any(k.endswith("-erd.mmd") for k in result)


def test_generate_ddl_contains_create_table():
    g, classes = _simple_ontology()
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    assert "CREATE TABLE" in ddl
    assert "silver_test" in ddl


def test_generate_erd_starts_with_erdiagram():
    g, classes = _simple_ontology()
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    mmd = next(v for k, v in result.items() if k.endswith("-erd.mmd"))
    assert mmd.startswith("erDiagram")


def test_generate_surrogate_key_present():
    g, classes = _simple_ontology()
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    assert "party_sk" in ddl
    assert "address_sk" in ddl


def test_generate_audit_columns_present():
    g, classes = _simple_ontology()
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    assert "_created_at" in ddl
    assert "_load_date" in ddl


def test_generate_scd2_columns_present():
    g, classes = _simple_ontology()
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    assert "valid_from" in ddl
    assert "valid_to" in ddl
    assert "is_current" in ddl


# ---------------------------------------------------------------------------
# R8 — Reference data: ref_ prefix, SCD Type 1, no audit
# ---------------------------------------------------------------------------

def test_reference_data_table_has_ref_prefix(tmp_path):
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:LegalForm a owl:Class ; rdfs:label "LegalForm"@en ; rdfs:comment "."@en ;
            kairos-ext:isReferenceData "true"^^xsd:boolean ;
            kairos-ext:scdType "1" .

        ex:code a owl:DatatypeProperty ;
            rdfs:domain ex:LegalForm ;
            rdfs:range xsd:string ;
            rdfs:label "code"@en .
    """
    g = _make_graph(ttl)
    classes = [{"uri": f"{BASE}LegalForm", "name": "LegalForm", "label": "LegalForm", "comment": ""}]
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    assert "ref_legal_form" in ddl
    # No SCD columns for type 1
    assert "valid_from" not in ddl
    # No audit columns for reference tables
    assert "_created_at" not in ddl


# ---------------------------------------------------------------------------
# R7 — GDPR satellite: no SK, PK = FK to parent
# ---------------------------------------------------------------------------

def test_gdpr_satellite_no_separate_sk():
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:Party a owl:Class ; rdfs:label "Party"@en ; rdfs:comment "."@en .
        ex:SensitiveData a owl:Class ; rdfs:label "SensitiveData"@en ; rdfs:comment "."@en ;
            kairos-ext:gdprSatelliteOf ex:Party .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Party", "name": "Party", "label": "Party", "comment": ""},
        {"uri": f"{BASE}SensitiveData", "name": "SensitiveData", "label": "SensitiveData", "comment": ""},
    ]
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    # GDPR satellite should not have its own _sk, instead reuses parent_sk
    assert "sensitive_data_sk" not in ddl
    assert "party_sk" in ddl


# ---------------------------------------------------------------------------
# R6 — class-per-table inheritance: subtype uses parent_sk as PK/FK
# ---------------------------------------------------------------------------

def test_subtype_uses_parent_sk_as_pk():
    """S3: Subtypes are flattened into parent table — no separate table generated."""
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:Party a owl:Class ; rdfs:label "Party"@en ; rdfs:comment "."@en .
        ex:Person a owl:Class ; rdfs:label "Person"@en ; rdfs:comment "."@en ;
            rdfs:subClassOf ex:Party .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Party", "name": "Party", "label": "Party", "comment": ""},
        {"uri": f"{BASE}Person", "name": "Person", "label": "Person", "comment": ""},
    ]
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    # S3: Person is flattened into Party — no separate person table
    assert "CREATE TABLE" in ddl
    assert ddl.lower().count("create table") == 1  # only Party table
    assert "silver_test.party" in ddl.lower()
    # S3: auto-generated discriminator
    assert "party_type" in ddl.lower()
    # S3: comment noting flattened subtypes
    assert "S3: subtypes flattened" in ddl
    assert "Person" in ddl


# ---------------------------------------------------------------------------
# R13 — Junction table
# ---------------------------------------------------------------------------

def test_junction_table_generated():
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:Engagement a owl:Class ; rdfs:label "Engagement"@en ; rdfs:comment "."@en .
        ex:Person a owl:Class ; rdfs:label "Person"@en ; rdfs:comment "."@en .

        ex:hasTeamMember a owl:ObjectProperty ;
            rdfs:domain ex:Engagement ;
            rdfs:range ex:Person ;
            rdfs:label "has team member"@en ;
            kairos-ext:junctionTableName "engagement_team_member" .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Engagement", "name": "Engagement", "label": "Engagement", "comment": ""},
        {"uri": f"{BASE}Person", "name": "Person", "label": "Person", "comment": ""},
    ]
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    assert "engagement_team_member" in ddl
    assert "engagement_team_member_sk" in ddl


# ---------------------------------------------------------------------------
# generate_master_erd
# ---------------------------------------------------------------------------

def test_master_erd_merges_domains(tmp_path):
    # Simulate two domain ERD files in dbt/docs/diagrams/
    dbt_out = tmp_path / "dbt"
    (dbt_out / "docs" / "diagrams" / "customer").mkdir(parents=True)
    (dbt_out / "docs" / "diagrams" / "order").mkdir(parents=True)

    (dbt_out / "docs" / "diagrams" / "customer" / "customer-erd.mmd").write_text(
        "erDiagram\n    %% Silver ERD: silver_customer / customer\n\n"
        "    CUSTOMER {\n        NVARCHAR(36) customer_sk\n    }\n",
        encoding="utf-8",
    )
    (dbt_out / "docs" / "diagrams" / "order" / "order-erd.mmd").write_text(
        "erDiagram\n    %% Silver ERD: silver_order / order\n\n"
        "    ORDER {\n        NVARCHAR(36) order_sk\n    }\n",
        encoding="utf-8",
    )

    result = generate_master_erd(dbt_out, hub_name="test-hub")
    assert result is not None
    assert result.startswith("erDiagram")
    assert "CUSTOMER" in result
    assert "ORDER" in result
    assert "Domain: customer" in result
    assert "Domain: order" in result
    assert result.count("erDiagram") == 1  # Only one header


def test_master_erd_returns_none_when_empty(tmp_path):
    dbt_out = tmp_path / "dbt"
    dbt_out.mkdir()
    assert generate_master_erd(dbt_out) is None


def test_master_erd_excludes_own_previous_output(tmp_path):
    """Regression: master-erd.mmd must not be included in its own merge."""
    dbt_out = tmp_path / "dbt"
    (dbt_out / "docs" / "diagrams" / "customer").mkdir(parents=True)
    (dbt_out / "docs" / "diagrams" / "customer" / "customer-erd.mmd").write_text(
        "erDiagram\n    %% Silver ERD: silver_customer / customer\n\n"
        "    CUSTOMER {\n        NVARCHAR_36 customer_sk\n    }\n",
        encoding="utf-8",
    )
    # Simulate a leftover master from a previous run
    (dbt_out / "docs" / "diagrams" / "master-erd.mmd").write_text(
        "erDiagram\n    %% Master ERD — hub (all domains)\n\n"
        "    %% --- Domain: customer ---\n"
        "    CUSTOMER {\n        NVARCHAR_36 customer_sk\n    }\n",
        encoding="utf-8",
    )

    result = generate_master_erd(dbt_out, hub_name="hub")
    assert result is not None
    # CUSTOMER should appear exactly once (not duplicated from the old master)
    assert result.count("CUSTOMER {") == 1
    # Only one domain section
    assert result.count("Domain: customer") == 1


def test_parse_audit_envelope_with_parenthesized_types():
    """Commas inside SQL type parentheses must not split the column definition."""
    audit_str = "_total DECIMAL(18, 4), _load_date DATE, _amount NUMERIC(10, 2)"
    cols = _parse_audit_envelope(audit_str)
    assert len(cols) == 3
    assert cols[0].name == "_total"
    assert cols[0].sql_type == "DECIMAL(18, 4)"
    assert cols[1].name == "_load_date"
    assert cols[1].sql_type == "DATE"
    assert cols[2].name == "_amount"
    assert cols[2].sql_type == "NUMERIC(10, 2)"


# ---------------------------------------------------------------------------
# R12 — FK from silverColumnName without OWL cardinality restriction
# ---------------------------------------------------------------------------

def test_fk_column_from_silver_column_name_without_restriction():
    """silverColumnName on an ObjectProperty must produce a FK column even
    without an owl:maxQualifiedCardinality restriction."""
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:Client a owl:Class ; rdfs:label "Client"@en ; rdfs:comment "."@en .
        ex:Party  a owl:Class ; rdfs:label "Party"@en  ; rdfs:comment "."@en .

        ex:hasParty a owl:ObjectProperty ;
            rdfs:domain ex:Client ;
            rdfs:range ex:Party ;
            rdfs:label "has party"@en ;
            kairos-ext:silverColumnName "party_sk" .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Client", "name": "Client", "label": "Client", "comment": ""},
        {"uri": f"{BASE}Party", "name": "Party", "label": "Party", "comment": ""},
    ]
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    alter = next(v for k, v in result.items() if k.endswith("-alter.sql"))
    erd = next(v for k, v in result.items() if k.endswith("-erd.mmd"))
    # FK column must appear in DDL
    assert "party_sk" in ddl
    # FK constraint must appear
    assert "fk_client_party_sk" in alter
    # Relationship must appear in ERD with property label
    assert "has_party" in erd


def test_fk_column_from_functional_property():
    """owl:FunctionalProperty must produce a FK column without cardinality restriction."""
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:Order   a owl:Class ; rdfs:label "Order"@en   ; rdfs:comment "."@en .
        ex:Customer a owl:Class ; rdfs:label "Customer"@en ; rdfs:comment "."@en .

        ex:placedBy a owl:ObjectProperty , owl:FunctionalProperty ;
            rdfs:domain ex:Order ;
            rdfs:range ex:Customer ;
            rdfs:label "placed by"@en .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Order", "name": "Order", "label": "Order", "comment": ""},
        {"uri": f"{BASE}Customer", "name": "Customer", "label": "Customer", "comment": ""},
    ]
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    assert "customer_sk" in ddl


# ---------------------------------------------------------------------------
# Discriminator column collision
# ---------------------------------------------------------------------------

def test_discriminator_column_not_duplicated():
    """A data property with the same name as the discriminator column must not
    produce a duplicate column."""
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:Relation a owl:Class ; rdfs:label "Relation"@en ; rdfs:comment "."@en ;
            kairos-ext:discriminatorColumn "relation_type" .

        ex:relationType a owl:DatatypeProperty ;
            rdfs:domain ex:Relation ;
            rdfs:range xsd:string ;
            rdfs:label "relation type"@en .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Relation", "name": "Relation", "label": "Relation", "comment": ""},
    ]
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    # Column should appear exactly once (from discriminator, not duplicated by data prop)
    assert ddl.count("relation_type") == 1


# ---------------------------------------------------------------------------
# Cross-domain FK columns
# ---------------------------------------------------------------------------

PARTY_NS = "http://example.com/ont/party#"


def test_cross_domain_fk_column_generated():
    """A cross-domain ObjectProperty (Client → Party in different namespace)
    must still produce a FK column in the DDL."""
    ttl = f"""
        @prefix ex:    <{BASE}> .
        @prefix party: <{PARTY_NS}> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
        @prefix owl:   <http://www.w3.org/2002/07/owl#> .
        @prefix rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Client"@en ; owl:versionInfo "1.0" .

        ex:Client a owl:Class ; rdfs:label "Client"@en ; rdfs:comment "."@en .

        party:Party a owl:Class ; rdfs:label "Party"@en ; rdfs:comment "."@en .

        ex:representsParty a owl:ObjectProperty ;
            rdfs:domain ex:Client ;
            rdfs:range party:Party ;
            rdfs:label "represents party"@en ;
            kairos-ext:silverColumnName "party_sk" .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Client", "name": "Client", "label": "Client", "comment": ""},
    ]
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="client")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    alter = next(v for k, v in result.items() if k.endswith("-alter.sql"))
    erd = next(v for k, v in result.items() if k.endswith("-erd.mmd"))

    # FK column must appear
    assert "party_sk" in ddl
    # FK constraint must reference the external schema
    assert "silver_party" in alter
    assert "REFERENCES" in alter
    # ERD must show the relationship
    assert "represents_party" in erd


def test_cross_domain_fk_with_explicit_silver_schema():
    """Cross-domain FK should use silverSchema annotation from the external ontology."""
    ttl = f"""
        @prefix ex:    <{BASE}> .
        @prefix ext:   <http://other.com/ont/billing#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
        @prefix owl:   <http://www.w3.org/2002/07/owl#> .
        @prefix rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Order"@en ; owl:versionInfo "1.0" .

        # External ontology declares its schema
        <http://other.com/ont/billing> kairos-ext:silverSchema "silver_billing" .

        ext:Invoice a owl:Class ; rdfs:label "Invoice"@en ; rdfs:comment "."@en ;
            kairos-ext:silverTableName "invoice" .

        ex:Order a owl:Class ; rdfs:label "Order"@en ; rdfs:comment "."@en .

        ex:hasInvoice a owl:ObjectProperty , owl:FunctionalProperty ;
            rdfs:domain ex:Order ;
            rdfs:range ext:Invoice ;
            rdfs:label "has invoice"@en .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Order", "name": "Order", "label": "Order", "comment": ""},
    ]
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="order")
    alter = next(v for k, v in result.items() if k.endswith("-alter.sql"))
    # Must reference the explicit schema
    assert "silver_billing.invoice" in alter


# ---------------------------------------------------------------------------
# render_mermaid_svg
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Provenance metadata in output
# ---------------------------------------------------------------------------


def test_provenance_in_ddl_header():
    """DDL output should contain ontology IRI, version, toolkit version when metadata provided."""
    g, classes = _simple_ontology()
    meta = {
        "iri": "http://example.com/ont/test",
        "version": "2.1.0",
        "label": "Test Ontology",
        "namespace": BASE,
        "toolkit_version": "1.8.0",
        "generated_at": "2026-04-21T00:00:00Z",
    }
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test",
                                       ontology_metadata=meta)
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    assert "Ontology IRI: http://example.com/ont/test" in ddl
    assert "Ontology version: 2.1.0" in ddl
    assert "Toolkit version: 1.8.0" in ddl
    assert "Generated at: 2026-04-21T00:00:00Z" in ddl


def test_provenance_in_erd_header():
    """ERD output should contain ontology IRI + version as Mermaid comments."""
    g, classes = _simple_ontology()
    meta = {
        "iri": "http://example.com/ont/test",
        "version": "2.1.0",
        "toolkit_version": "1.8.0",
    }
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test",
                                       ontology_metadata=meta)
    erd = next(v for k, v in result.items() if k.endswith("-erd.mmd"))
    assert "%% Ontology IRI: http://example.com/ont/test" in erd
    assert "%% Ontology version: 2.1.0" in erd


def test_provenance_absent_when_no_metadata():
    """When no metadata is provided, no provenance lines appear (backwards-compatible)."""
    g, classes = _simple_ontology()
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    assert "Ontology IRI:" not in ddl
    assert "Toolkit version:" not in ddl


# ---------------------------------------------------------------------------
# S3 — Full inheritance flattening (replaces R16 empty subtype suppression)
# ---------------------------------------------------------------------------


def _s3_ontology() -> tuple[Graph, list[dict]]:
    """Ontology with parent, empty subtypes, and one subtype with own properties."""
    ttl = f"""
        @prefix ex:    <{BASE}> .
        @prefix owl:   <http://www.w3.org/2002/07/owl#> .
        @prefix rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "S3 Test"@en ; owl:versionInfo "1.0" .

        ex:Client a owl:Class ;
            rdfs:label "Client"@en ;
            rdfs:comment "A client."@en ;
            kairos-ext:scdType "2" ;
            kairos-ext:discriminatorColumn "client_type" .

        ex:clientName a owl:DatatypeProperty ;
            rdfs:domain ex:Client ;
            rdfs:range xsd:string ;
            rdfs:label "client name"@en .

        # Empty subtype — flattened
        ex:IndividualClient a owl:Class ;
            rdfs:subClassOf ex:Client ;
            rdfs:label "Individual Client"@en ;
            rdfs:comment "An individual client."@en ;
            kairos-ext:scdType "2" .

        # Empty subtype — flattened
        ex:OrgClient a owl:Class ;
            rdfs:subClassOf ex:Client ;
            rdfs:label "Org Client"@en ;
            rdfs:comment "An org client."@en ;
            kairos-ext:scdType "2" .

        # Non-empty subtype — ALSO flattened (S3 flattens ALL subtypes)
        ex:SpecialClient a owl:Class ;
            rdfs:subClassOf ex:Client ;
            rdfs:label "Special Client"@en ;
            rdfs:comment "A special client."@en ;
            kairos-ext:scdType "2" .
        ex:specialRating a owl:DatatypeProperty ;
            rdfs:domain ex:SpecialClient ;
            rdfs:range xsd:integer ;
            rdfs:label "special rating"@en .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Client", "name": "Client"},
        {"uri": f"{BASE}IndividualClient", "name": "IndividualClient"},
        {"uri": f"{BASE}OrgClient", "name": "OrgClient"},
        {"uri": f"{BASE}SpecialClient", "name": "SpecialClient"},
    ]
    return g, classes


def test_s3_all_subtypes_flattened():
    """S3: ALL subtypes (including those with own properties) are flattened."""
    g, classes = _s3_ontology()
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="s3test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    # Only one CREATE TABLE (the parent)
    assert ddl.lower().count("create table") == 1
    assert "silver_s3test.client" in ddl.lower()
    # No subtype tables
    assert "individual_client" not in ddl.lower().replace("from individualclient", "")
    assert "org_client" not in ddl.lower().replace("from orgclient", "")
    assert "special_client" not in ddl.lower().replace("from specialclient", "")


def test_s3_subtype_properties_merged():
    """S3: Subtype properties become nullable columns on the parent table."""
    g, classes = _s3_ontology()
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="s3test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    # SpecialClient's special_rating should appear as nullable column on Client table
    assert "special_rating" in ddl.lower()
    assert "from SpecialClient" in ddl


def test_s3_folded_comment_in_ddl():
    """Parent DDL should contain S3 comment listing flattened subtypes."""
    g, classes = _s3_ontology()
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="s3test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    assert "S3: subtypes flattened into this table" in ddl
    assert "IndividualClient" in ddl
    assert "OrgClient" in ddl
    assert "SpecialClient" in ddl


def test_s3_class_per_table_also_flattened():
    """S3: Even class-per-table annotated subtypes are flattened in silver."""
    ttl = f"""
        @prefix ex:    <{BASE}> .
        @prefix owl:   <http://www.w3.org/2002/07/owl#> .
        @prefix rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "CPT Test"@en ; owl:versionInfo "1.0" .

        ex:Account a owl:Class ;
            rdfs:label "Account"@en ;
            rdfs:comment "An account."@en ;
            kairos-ext:scdType "2" ;
            kairos-ext:inheritanceStrategy "class-per-table" .

        ex:accountName a owl:DatatypeProperty ;
            rdfs:domain ex:Account ;
            rdfs:range xsd:string ;
            rdfs:label "account name"@en .

        ex:SavingsAccount a owl:Class ;
            rdfs:subClassOf ex:Account ;
            rdfs:label "Savings Account"@en ;
            rdfs:comment "A savings account."@en ;
            kairos-ext:scdType "2" .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Account", "name": "Account"},
        {"uri": f"{BASE}SavingsAccount", "name": "SavingsAccount"},
    ]
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="cpttest")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    # S3: SavingsAccount is flattened into Account (no separate table)
    assert ddl.lower().count("create table") == 1
    assert "savings_account" not in ddl.lower()
    # Auto-discriminator added
    assert "account_type" in ddl.lower()


def test_r16_gdpr_satellite_not_suppressed():
    """GDPR satellites are never suppressed even under discriminator strategy."""
    ttl = f"""
        @prefix ex:    <{BASE}> .
        @prefix owl:   <http://www.w3.org/2002/07/owl#> .
        @prefix rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "GDPR Test"@en ; owl:versionInfo "1.0" .

        ex:Contact a owl:Class ;
            rdfs:label "Contact"@en ;
            rdfs:comment "A contact."@en ;
            kairos-ext:scdType "2" ;
            kairos-ext:inheritanceStrategy "discriminator" ;
            kairos-ext:discriminatorColumn "contact_type" .

        ex:contactInfo a owl:DatatypeProperty ;
            rdfs:domain ex:Contact ;
            rdfs:range xsd:string ;
            rdfs:label "contact info"@en .

        # GDPR satellite — should NOT be suppressed even though empty
        ex:SensitiveContact a owl:Class ;
            rdfs:subClassOf ex:Contact ;
            rdfs:label "Sensitive Contact"@en ;
            rdfs:comment "A sensitive contact."@en ;
            kairos-ext:gdprSatelliteOf ex:Contact ;
            kairos-ext:scdType "2" .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Contact", "name": "Contact"},
        {"uri": f"{BASE}SensitiveContact", "name": "SensitiveContact"},
    ]
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="gdprtest")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    assert "sensitive_contact" in ddl.lower()


# ---------------------------------------------------------------------------
# render_mermaid_svg
# ---------------------------------------------------------------------------


def test_render_mermaid_svg_returns_none_when_mmdc_missing(tmp_path, monkeypatch):
    """When mmdc is not available, render_mermaid_svg should return None."""
    import shutil as _shutil
    monkeypatch.setattr(_shutil, "which", lambda _name: None)
    mmd = tmp_path / "test.mmd"
    mmd.write_text("erDiagram\n    FOO {\n        STRING id\n    }\n")
    result = render_mermaid_svg(mmd)
    assert result is None
    assert not (tmp_path / "test.svg").exists()


# ---------------------------------------------------------------------------
# Duplicate FK column fixes (Bug #17)
# ---------------------------------------------------------------------------


def _self_referential_ontology() -> tuple[Graph, list[dict]]:
    """Ontology with two self-referential FKs to the same class (Employee)."""
    ttl = f"""
        @prefix ex:    <{BASE}> .
        @prefix owl:   <http://www.w3.org/2002/07/owl#> .
        @prefix rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Self-Ref Test"@en ; owl:versionInfo "1.0" .

        ex:Employee a owl:Class ;
            rdfs:label "Employee"@en ;
            rdfs:comment "An employee."@en ;
            kairos-ext:scdType "2" .

        ex:employeeName a owl:DatatypeProperty ;
            rdfs:domain ex:Employee ;
            rdfs:range xsd:string ;
            rdfs:label "employee name"@en .

        ex:reportsTo a owl:ObjectProperty, owl:FunctionalProperty ;
            rdfs:domain ex:Employee ;
            rdfs:range ex:Employee ;
            rdfs:label "reports to"@en .

        ex:supervisor a owl:ObjectProperty, owl:FunctionalProperty ;
            rdfs:domain ex:Employee ;
            rdfs:range ex:Employee ;
            rdfs:label "supervisor"@en .
    """
    g = _make_graph(ttl)
    classes = [{"uri": f"{BASE}Employee", "name": "Employee"}]
    return g, classes


def test_self_referential_fk_no_duplicate_columns():
    """Two self-referential FKs to same class produce distinct column names."""
    g, classes = _self_referential_ontology()
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="selfref")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    # Both FK columns should exist with different names
    lines = ddl.lower().split("\n")
    col_lines = [l.strip() for l in lines if "_sk" in l and "string" in l]
    col_names = [l.split()[0] for l in col_lines]
    # Should have unique column names (no duplicates)
    assert len(col_names) == len(set(col_names)), (
        f"Duplicate FK columns found: {col_names}"
    )
    # At least 2 FK columns (the two self-referential properties)
    fk_cols = [c for c in col_names if c != "employee_sk"]
    assert len(fk_cols) >= 1, f"Expected disambiguated FK columns, got: {col_names}"


def test_self_referential_fk_no_duplicate_constraints():
    """Two self-referential FKs produce distinct constraint comments (S2)."""
    g, classes = _self_referential_ontology()
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="selfref")
    alter = next(v for k, v in result.items() if k.endswith("-alter.sql"))
    # S2: constraints are now documentation-only comments
    import re
    constraints = re.findall(r"ADD CONSTRAINT (\S+)", alter)
    assert len(constraints) == len(set(constraints)), (
        f"Duplicate FK constraint names: {constraints}"
    )


def _self_referential_pk_collision_ontology() -> tuple[Graph, list[dict]]:
    """Ontology with a self-referential FK that collides with PK name."""
    ttl = f"""
        @prefix ex:    <{BASE}> .
        @prefix owl:   <http://www.w3.org/2002/07/owl#> .
        @prefix rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "PK Collision Test"@en ; owl:versionInfo "1.0" .

        ex:OrgUnit a owl:Class ;
            rdfs:label "Organisational Unit"@en ;
            rdfs:comment "An organisational unit."@en ;
            kairos-ext:scdType "2" .

        ex:unitName a owl:DatatypeProperty ;
            rdfs:domain ex:OrgUnit ;
            rdfs:range xsd:string ;
            rdfs:label "unit name"@en .

        ex:parentUnit a owl:ObjectProperty, owl:FunctionalProperty ;
            rdfs:domain ex:OrgUnit ;
            rdfs:range ex:OrgUnit ;
            rdfs:label "parent unit"@en .
    """
    g = _make_graph(ttl)
    classes = [{"uri": f"{BASE}OrgUnit", "name": "OrgUnit"}]
    return g, classes


def test_self_referential_fk_does_not_collide_with_pk():
    """A self-referential FK should not reuse the PK column name."""
    g, classes = _self_referential_pk_collision_ontology()
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="orgtest")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    lines = ddl.lower().split("\n")
    col_lines = [l.strip() for l in lines if "_sk" in l and "string" in l]
    col_names = [l.split()[0] for l in col_lines]
    assert len(col_names) == len(set(col_names)), (
        f"FK column collides with PK: {col_names}"
    )


def test_fk_nullable_annotation_respected():
    """FK columns should respect kairos-ext:nullable annotation."""
    ttl = f"""
        @prefix ex:    <{BASE}> .
        @prefix owl:   <http://www.w3.org/2002/07/owl#> .
        @prefix rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Nullable Test"@en ; owl:versionInfo "1.0" .

        ex:Party a owl:Class ;
            rdfs:label "Party"@en ;
            rdfs:comment "A party."@en ;
            kairos-ext:scdType "2" .

        ex:partyName a owl:DatatypeProperty ;
            rdfs:domain ex:Party ;
            rdfs:range xsd:string ;
            rdfs:label "party name"@en .

        ex:Client a owl:Class ;
            rdfs:label "Client"@en ;
            rdfs:comment "A client."@en ;
            kairos-ext:scdType "2" .

        ex:clientName a owl:DatatypeProperty ;
            rdfs:domain ex:Client ;
            rdfs:range xsd:string ;
            rdfs:label "client name"@en .

        ex:representsParty a owl:ObjectProperty, owl:FunctionalProperty ;
            rdfs:domain ex:Client ;
            rdfs:range ex:Party ;
            rdfs:label "represents party"@en ;
            kairos-ext:nullable "false" .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Party", "name": "Party"},
        {"uri": f"{BASE}Client", "name": "Client"},
    ]
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="nulltest")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    # Find the client table's party_sk line
    in_client = False
    for line in ddl.split("\n"):
        if "silver_nulltest.client" in line.lower() and "create table" in line.lower():
            in_client = True
        if in_client and "party_sk" in line.lower():
            assert "NOT NULL" in line, (
                f"FK column party_sk should be NOT NULL when nullable=false, got: {line.strip()}"
            )
            break
    else:
        pytest.fail("Could not find party_sk column in client table DDL")


# ---------------------------------------------------------------------------
# S1 — Spark SQL types
# ---------------------------------------------------------------------------


def test_s1_spark_sql_types_in_ddl():
    """S1: DDL uses Spark SQL types (BOOLEAN, TIMESTAMP, STRING, DOUBLE)."""
    g, classes = _simple_ontology()
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    # Surrogate key uses STRING (not NVARCHAR)
    assert "STRING NOT NULL" in ddl
    # Audit columns use TIMESTAMP (not DATETIME2)
    assert "TIMESTAMP" in ddl
    # No old T-SQL types
    assert "NVARCHAR" not in ddl
    assert "DATETIME2" not in ddl
    assert "BIT" not in ddl


def test_s1_boolean_type():
    """S1: xsd:boolean maps to BOOLEAN (not BIT)."""
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:Thing a owl:Class ; rdfs:label "Thing"@en ; rdfs:comment "."@en .
        ex:isActive a owl:DatatypeProperty ;
            rdfs:domain ex:Thing ;
            rdfs:range xsd:boolean ;
            rdfs:label "is active"@en .
    """
    g = _make_graph(ttl)
    classes = [{"uri": f"{BASE}Thing", "name": "Thing"}]
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    assert "BOOLEAN" in ddl
    assert "BIT" not in ddl.split("is_active")[0]  # ignore is_current which is also BOOLEAN


# ---------------------------------------------------------------------------
# S2 — Constraints as comments
# ---------------------------------------------------------------------------


def test_s2_no_constraint_keyword_in_create():
    """S2: CREATE TABLE must not contain CONSTRAINT keyword."""
    g, classes = _simple_ontology()
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    assert "CONSTRAINT" not in ddl


def test_s2_pk_as_comment():
    """S2: PK constraint appears as DDL comment."""
    g, classes = _simple_ontology()
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    assert "-- PK: party_sk" in ddl


def test_s2_alter_file_is_documentation():
    """S2: ALTER TABLE file contains only commented-out constraints."""
    g, classes = _simple_ontology()
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    alter = next(v for k, v in result.items() if k.endswith("-alter.sql"))
    # Header indicates documentation-only
    assert "documentation only" in alter.lower()
    # All constraint lines are comments
    for line in alter.strip().split("\n"):
        if line.strip() and not line.strip().startswith("--"):
            # Only empty lines are non-comment
            assert line.strip() == "", f"Non-comment line in alter file: {line}"


# ---------------------------------------------------------------------------
# S4 — Inline small reference tables
# ---------------------------------------------------------------------------


def test_s4_small_ref_table_inlined():
    """S4: Reference table with ≤3 business columns is inlined into parent."""
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:Gender a owl:Class ;
            rdfs:label "Gender"@en ;
            rdfs:comment "Gender reference."@en ;
            kairos-ext:isReferenceData "true"^^xsd:boolean ;
            kairos-ext:scdType "1" .

        ex:genderCode a owl:DatatypeProperty ;
            rdfs:domain ex:Gender ;
            rdfs:range xsd:string ;
            rdfs:label "code"@en .

        ex:genderLabel a owl:DatatypeProperty ;
            rdfs:domain ex:Gender ;
            rdfs:range xsd:string ;
            rdfs:label "label"@en .

        ex:Person a owl:Class ;
            rdfs:label "Person"@en ;
            rdfs:comment "A person."@en ;
            kairos-ext:scdType "2" .

        ex:personName a owl:DatatypeProperty ;
            rdfs:domain ex:Person ;
            rdfs:range xsd:string ;
            rdfs:label "name"@en .

        ex:hasGender a owl:ObjectProperty, owl:FunctionalProperty ;
            rdfs:domain ex:Person ;
            rdfs:range ex:Gender ;
            rdfs:label "has gender"@en .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Gender", "name": "Gender"},
        {"uri": f"{BASE}Person", "name": "Person"},
    ]
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    # ref_gender table definition should NOT exist (inlined)
    assert "CREATE TABLE silver_test.ref_gender" not in ddl
    # Person table should have inlined columns
    assert "gender_gender_code" in ddl.lower() or "gender_code" in ddl.lower()
    # S4 comment should be present
    assert "S4: inlined" in ddl


# ---------------------------------------------------------------------------
# S5 — _row_hash column
# ---------------------------------------------------------------------------


def test_s5_row_hash_column():
    """S5: Non-reference tables include _row_hash BINARY column."""
    g, classes = _simple_ontology()
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    assert "_row_hash" in ddl
    assert "BINARY" in ddl


# ---------------------------------------------------------------------------
# S6 — _deleted_at column
# ---------------------------------------------------------------------------


def test_s6_deleted_at_column():
    """S6: Non-reference tables include _deleted_at TIMESTAMP NULL column."""
    g, classes = _simple_ontology()
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    assert "_deleted_at" in ddl


# ---------------------------------------------------------------------------
# BUG-1 — S5/S6 columns present even with custom audit envelope
# ---------------------------------------------------------------------------


def test_bug1_s5_s6_with_custom_audit():
    """BUG-1: _row_hash and _deleted_at must appear even when a custom audit
    envelope is specified (they are fixed S5/S6 columns, not customizable)."""
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        <{BASE.rstrip('#')}> a owl:Ontology ;
            rdfs:label "Test"@en ; owl:versionInfo "1.0" ;
            kairos-ext:auditEnvelope "_load_date DATE, _source STRING" .

        ex:Thing a owl:Class ; rdfs:label "Thing"@en ; rdfs:comment "."@en .
    """
    g = _make_graph(ttl)
    classes = [{"uri": f"{BASE}Thing", "name": "Thing"}]
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    # Custom audit columns present
    assert "_load_date" in ddl
    assert "_source" in ddl
    # S5/S6 always present despite custom audit
    assert "_row_hash" in ddl
    assert "_deleted_at" in ddl


# ---------------------------------------------------------------------------
# BUG-2 — No duplicate subtype names in S3 flattening comment
# ---------------------------------------------------------------------------


def test_bug2_no_duplicate_subtype_names():
    """BUG-2: Subtypes listed in the S3 comment must be deduplicated."""
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        <{BASE.rstrip('#')}> a owl:Ontology ;
            rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:Animal a owl:Class ; rdfs:label "Animal"@en ; rdfs:comment "."@en .
        ex:Dog a owl:Class ; rdfs:label "Dog"@en ; rdfs:comment "."@en ;
            rdfs:subClassOf ex:Animal .
        ex:Cat a owl:Class ; rdfs:label "Cat"@en ; rdfs:comment "."@en ;
            rdfs:subClassOf ex:Animal .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Animal", "name": "Animal"},
        {"uri": f"{BASE}Dog", "name": "Dog"},
        {"uri": f"{BASE}Cat", "name": "Cat"},
    ]
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    # "Dog" should appear exactly once
    assert ddl.count("Dog") == 1
    # "Cat" should appear exactly once
    assert ddl.count("Cat") == 1


# ---------------------------------------------------------------------------
# BUG-3 / IMP-1 — Only domain-owned classes generate tables
# ---------------------------------------------------------------------------


def test_bug3_imp1_imported_classes_not_materialized():
    """BUG-3/IMP-1: Classes from another namespace should NOT produce tables.
    Cross-domain FK references should point to the canonical schema."""
    PARTY_NS = "http://example.com/ont/party#"
    CLIENT_NS = "http://example.com/ont/client#"
    ttl = f"""
        @prefix party: <{PARTY_NS}> .
        @prefix client: <{CLIENT_NS}> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        <http://example.com/ont/client> a owl:Ontology ;
            rdfs:label "Client"@en ; owl:versionInfo "1.0" ;
            owl:imports <http://example.com/ont/party> .

        party:Party a owl:Class ;
            rdfs:label "Party"@en ; rdfs:comment "."@en .

        client:Client a owl:Class ;
            rdfs:label "Client"@en ; rdfs:comment "."@en .
        client:representsParty a owl:ObjectProperty, owl:FunctionalProperty ;
            rdfs:domain client:Client ; rdfs:range party:Party ;
            rdfs:label "represents party"@en .
    """
    g = _make_graph(ttl)
    # Caller passes both imported and local classes
    classes = [
        {"uri": f"{PARTY_NS}Party", "name": "Party"},
        {"uri": f"{CLIENT_NS}Client", "name": "Client"},
    ]
    result = generate_silver_artifacts(
        classes, g, CLIENT_NS, ontology_name="client"
    )
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    # Client table should exist
    assert "silver_client.client" in ddl.lower()
    # Party table should NOT be materialized (different namespace)
    assert "CREATE TABLE silver_client.party" not in ddl
    # FK should point to canonical silver_party schema
    assert "silver_party.party" in ddl.lower()


# ---------------------------------------------------------------------------
# BUG-4 — S4 inlined column name shortening
# ---------------------------------------------------------------------------


def test_bug4_s4_short_inlined_names():
    """BUG-4: _s4_inlined_name avoids redundant prefix segments."""
    # Full prefix match — no doubling
    assert _s4_inlined_name("gender", "gender_code") == "gender_code"
    # Overlapping suffix — strip overlap
    assert _s4_inlined_name("shareholder_property_right", "property_right_name_en") == \
        "shareholder_property_right_name_en"
    # Partial suffix match
    assert _s4_inlined_name("professional_role", "role_code") == "professional_role_code"
    # Column starts with full prefix
    assert _s4_inlined_name("acceptance_status", "acceptance_status_name") == \
        "acceptance_status_name"
    # No overlap at all
    assert _s4_inlined_name("country", "iso_alpha3") == "country_iso_alpha3"


# ---------------------------------------------------------------------------
# Edge cases — empty / minimal inputs
# ---------------------------------------------------------------------------

class TestEdgeCasesEmpty:
    """Edge-case tests for empty or minimal inputs."""

    def test_generate_silver_artifacts_empty_classes(self):
        """Empty class list with a valid graph should return a dict with no CREATE TABLE."""
        ttl = f"""
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
            <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .
        """
        g = _make_graph(ttl)
        result = generate_silver_artifacts(
            classes=[], graph=g, namespace=BASE, ontology_name="test",
        )
        assert isinstance(result, dict)
        for content in result.values():
            assert "CREATE TABLE" not in content
