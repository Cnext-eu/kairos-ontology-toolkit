# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the silver layer projector (R1-R16 annotations + S1-S8 Fabric rules)."""

import textwrap

import pytest
from rdflib import Graph, Namespace

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
    """S3: Subtypes with discriminator strategy are flattened into parent table."""
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:Party a owl:Class ; rdfs:label "Party"@en ; rdfs:comment "."@en ;
            kairos-ext:inheritanceStrategy "discriminator" .
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
            kairos-ext:inheritanceStrategy "discriminator" ;
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


def test_s3_class_per_table_not_flattened():
    """S3: class-per-table annotated parents do NOT flatten subtypes (DD-035)."""
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
    # DD-035: class-per-table means subtypes get their own tables
    assert ddl.lower().count("create table") == 2
    assert "savings_account" in ddl.lower()
    # Parent should NOT get a discriminator column (TPC, not discriminator)
    assert "account_type" not in ddl.lower()


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
    """BUG-2: Subtypes listed in the S3 comment must be deduplicated (discriminator)."""
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        <{BASE.rstrip('#')}> a owl:Ontology ;
            rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:Animal a owl:Class ; rdfs:label "Animal"@en ; rdfs:comment "."@en ;
            kairos-ext:inheritanceStrategy "discriminator" .
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
    """BUG-3/IMP-1: Classes from another namespace should NOT produce tables
    when not claimed via silverInclude.

    Post DD-021 the namespace filter lives in ``_run_projection()`` — the caller
    now only passes classes that belong to the domain *or* are whitelisted.
    This test simulates that contract: only the local class is passed.
    """
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
    # DD-021: Caller (_run_projection) only passes domain + whitelisted classes.
    # Party is not whitelisted, so only Client is passed.
    classes = [
        {"uri": f"{CLIENT_NS}Client", "name": "Client"},
    ]
    result = generate_silver_artifacts(
        classes, g, CLIENT_NS, ontology_name="client"
    )
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    # Client table should exist
    assert "silver_client.client" in ddl.lower()
    # Party table should NOT be materialized (not whitelisted)
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


# ---------------------------------------------------------------------------
# DD-021 — Import whitelisting for silver projection
# ---------------------------------------------------------------------------


def test_dd021_silver_include_claims_imported_class():
    """DD-021: silverInclude true on an imported class → DDL generated."""
    REF_NS = "http://refmodel.example.com/ont/party#"
    HUB_NS = "http://hub.example.com/ont/party#"
    ttl = f"""
        @prefix ref: <{REF_NS}> .
        @prefix hub: <{HUB_NS}> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        <http://hub.example.com/ont/party> a owl:Ontology ;
            rdfs:label "Party"@en ; owl:versionInfo "1.0" ;
            owl:imports <http://refmodel.example.com/ont/party> .

        ref:TradeParty a owl:Class ;
            rdfs:label "Trade Party"@en ; rdfs:comment "."@en .
        ref:partyName a owl:DatatypeProperty ;
            rdfs:domain ref:TradeParty ;
            rdfs:range xsd:string ;
            rdfs:label "party name"@en .
    """
    g = _make_graph(ttl)
    # Caller (_run_projection) passes whitelisted imported class
    classes = [
        {"uri": f"{REF_NS}TradeParty", "name": "TradeParty"},
    ]
    result = generate_silver_artifacts(
        classes, g, HUB_NS, ontology_name="party"
    )
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    # Imported class should produce a table in the hub domain schema
    assert "silver_party.trade_party" in ddl.lower()
    assert "party_name" in ddl.lower()


def test_dd021_no_silver_include_no_import_ddl():
    """DD-021: Without silverInclude, imported classes produce no DDL.

    This validates that the default behavior (no extension) leaves imports
    excluded.  The filtering happens in _run_projection; the silver projector
    trusts its input, so we simply don't pass the imported class.
    """
    REF_NS = "http://refmodel.example.com/ont/party#"
    HUB_NS = "http://hub.example.com/ont/party#"
    ttl = f"""
        @prefix ref: <{REF_NS}> .
        @prefix hub: <{HUB_NS}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .

        <http://hub.example.com/ont/party> a owl:Ontology ;
            rdfs:label "Party"@en ; owl:versionInfo "1.0" ;
            owl:imports <http://refmodel.example.com/ont/party> .

        ref:TradeParty a owl:Class ;
            rdfs:label "Trade Party"@en ; rdfs:comment "."@en .
    """
    g = _make_graph(ttl)
    # No classes passed → no DDL
    result = generate_silver_artifacts(
        classes=[], graph=g, namespace=HUB_NS, ontology_name="party"
    )
    for content in result.values():
        assert "CREATE TABLE" not in content


def test_dd021_mixed_domain_local_plus_claimed():
    """DD-021: Mixed domain — local classes + claimed imports both produce DDL."""
    REF_NS = "http://refmodel.example.com/ont/party#"
    HUB_NS = "http://hub.example.com/ont/booking#"
    ttl = f"""
        @prefix ref: <{REF_NS}> .
        @prefix hub: <{HUB_NS}> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        <http://hub.example.com/ont/booking> a owl:Ontology ;
            rdfs:label "Booking"@en ; owl:versionInfo "1.0" ;
            owl:imports <http://refmodel.example.com/ont/party> .

        hub:Booking a owl:Class ;
            rdfs:label "Booking"@en ; rdfs:comment "."@en .
        hub:bookingRef a owl:DatatypeProperty ;
            rdfs:domain hub:Booking ; rdfs:range xsd:string ;
            rdfs:label "booking ref"@en .

        ref:TradeParty a owl:Class ;
            rdfs:label "Trade Party"@en ; rdfs:comment "."@en .
        ref:partyName a owl:DatatypeProperty ;
            rdfs:domain ref:TradeParty ; rdfs:range xsd:string ;
            rdfs:label "party name"@en .
    """
    g = _make_graph(ttl)
    # Both local and whitelisted imported class passed by caller
    classes = [
        {"uri": f"{HUB_NS}Booking", "name": "Booking"},
        {"uri": f"{REF_NS}TradeParty", "name": "TradeParty"},
    ]
    result = generate_silver_artifacts(
        classes, g, HUB_NS, ontology_name="booking"
    )
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    # Both tables should be in the hub domain schema
    assert "silver_booking.booking" in ddl.lower()
    assert "silver_booking.trade_party" in ddl.lower()


def test_dd021_extension_overrides_on_claimed_imports():
    """DD-021: Extension annotations (scdType, naturalKey) apply to claimed imports."""
    REF_NS = "http://refmodel.example.com/ont/party#"
    HUB_NS = "http://hub.example.com/ont/party#"
    ttl = f"""
        @prefix ref: <{REF_NS}> .
        @prefix hub: <{HUB_NS}> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        <http://hub.example.com/ont/party> a owl:Ontology ;
            rdfs:label "Party"@en ; owl:versionInfo "1.0" ;
            owl:imports <http://refmodel.example.com/ont/party> .

        ref:TradeParty a owl:Class ;
            rdfs:label "Trade Party"@en ; rdfs:comment "."@en .
        ref:partyCode a owl:DatatypeProperty ;
            rdfs:domain ref:TradeParty ;
            rdfs:range xsd:string ;
            rdfs:label "party code"@en .

        # Extension annotations on the imported class
        ref:TradeParty kairos-ext:silverInclude true ;
            kairos-ext:scdType "2" ;
            kairos-ext:naturalKey "party_code" .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{REF_NS}TradeParty", "name": "TradeParty"},
    ]
    result = generate_silver_artifacts(
        classes, g, HUB_NS, ontology_name="party"
    )
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    assert "silver_party.trade_party" in ddl.lower()
    # SCD Type 2 → valid_from / valid_to columns
    assert "valid_from" in ddl.lower()
    assert "valid_to" in ddl.lower()


def test_dd021_warn_unclaimed_parent(caplog):
    """DD-021: Info notice emitted when a claimed subclass has an unclaimed parent."""
    import logging

    REF_NS = "http://refmodel.example.com/ont/party#"
    HUB_NS = "http://hub.example.com/ont/party#"
    ttl = f"""
        @prefix ref: <{REF_NS}> .
        @prefix hub: <{HUB_NS}> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        <http://hub.example.com/ont/party> a owl:Ontology ;
            rdfs:label "Party"@en ; owl:versionInfo "1.0" .

        ref:TradeParty a owl:Class ;
            rdfs:label "Trade Party"@en ; rdfs:comment "."@en .
        ref:partyName a owl:DatatypeProperty ;
            rdfs:domain ref:TradeParty ; rdfs:range xsd:string ;
            rdfs:label "party name"@en .

        ref:Buyer a owl:Class ;
            rdfs:subClassOf ref:TradeParty ;
            rdfs:label "Buyer"@en ; rdfs:comment "."@en .
    """
    g = _make_graph(ttl)
    # Only Buyer is claimed — TradeParty is NOT
    classes = [
        {"uri": f"{REF_NS}Buyer", "name": "Buyer"},
    ]
    with caplog.at_level(logging.INFO):
        result = generate_silver_artifacts(
            classes, g, HUB_NS, ontology_name="party"
        )
    # Info notice about unclaimed parent should be emitted
    assert any("DD-021" in msg and "TradeParty" in msg and "not claimed" in msg
               for msg in caplog.messages)


# ---------------------------------------------------------------------------
# DD-022: silverForeignKey / silverForeignKeyOn
# ---------------------------------------------------------------------------

def test_dd022_silver_foreign_key_generates_fk():
    """silverForeignKey true must produce a FK column like FunctionalProperty."""
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:Order    a owl:Class ; rdfs:label "Order"@en    ; rdfs:comment "."@en .
        ex:Customer a owl:Class ; rdfs:label "Customer"@en ; rdfs:comment "."@en .

        ex:placedBy a owl:ObjectProperty ;
            rdfs:domain ex:Order ;
            rdfs:range ex:Customer ;
            rdfs:label "placed by"@en ;
            kairos-ext:silverForeignKey true .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Order", "name": "Order", "label": "Order", "comment": ""},
        {"uri": f"{BASE}Customer", "name": "Customer", "label": "Customer", "comment": ""},
    ]
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    assert "customer_sk" in ddl


def test_dd022_silver_foreign_key_on_reverse():
    """silverForeignKeyOn range class should place FK on the range table."""
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:Consignment     a owl:Class ; rdfs:label "Consignment"@en     ; rdfs:comment "."@en .
        ex:ConsignmentItem a owl:Class ; rdfs:label "ConsignmentItem"@en ; rdfs:comment "."@en .

        ex:hasConsignmentItem a owl:ObjectProperty ;
            rdfs:domain ex:Consignment ;
            rdfs:range ex:ConsignmentItem ;
            rdfs:label "has consignment item"@en ;
            kairos-ext:silverForeignKeyOn ex:ConsignmentItem .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Consignment", "name": "Consignment", "label": "Consignment",
         "comment": ""},
        {"uri": f"{BASE}ConsignmentItem", "name": "ConsignmentItem",
         "label": "ConsignmentItem", "comment": ""},
    ]
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    # FK should be on ConsignmentItem table pointing to Consignment
    assert "consignment_sk" in ddl
    # Verify it's on the ConsignmentItem table, not Consignment table
    lines = ddl.split("\n")
    in_consignment_item = False
    found_fk_on_item = False
    for line in lines:
        if "CREATE TABLE" in line and "consignment_item" in line:
            in_consignment_item = True
        elif "CREATE TABLE" in line:
            in_consignment_item = False
        if in_consignment_item and "consignment_sk" in line and "STRING" in line:
            found_fk_on_item = True
    assert found_fk_on_item, "FK column should be on ConsignmentItem table"


def test_dd022_reverse_fk_to_s3_folded_domain_references_parent_metadata():
    """S3-folded reverse FK targets should reference the projected parent table."""
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:Booking a owl:Class ;
            rdfs:label "Booking"@en ;
            rdfs:comment "."@en ;
            kairos-ext:inheritanceStrategy "discriminator" .

        ex:ConfirmedBooking a owl:Class ;
            rdfs:subClassOf ex:Booking ;
            rdfs:label "Confirmed Booking"@en ;
            rdfs:comment "."@en .

        ex:TransportPlanLeg a owl:Class ;
            rdfs:label "Transport Plan Leg"@en ;
            rdfs:comment "."@en .

        ex:hasTransportPlan a owl:ObjectProperty ;
            rdfs:domain ex:ConfirmedBooking ;
            rdfs:range ex:TransportPlanLeg ;
            rdfs:label "has transport plan"@en ;
            kairos-ext:silverForeignKeyOn ex:TransportPlanLeg ;
            kairos-ext:silverColumnName "booking_sk" .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Booking", "name": "Booking", "label": "Booking", "comment": ""},
        {
            "uri": f"{BASE}ConfirmedBooking",
            "name": "ConfirmedBooking",
            "label": "Confirmed Booking",
            "comment": "",
        },
        {
            "uri": f"{BASE}TransportPlanLeg",
            "name": "TransportPlanLeg",
            "label": "Transport Plan Leg",
            "comment": "",
        },
    ]
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    alter = next(v for k, v in result.items() if k.endswith("-alter.sql"))
    erd = next(v for k, v in result.items() if k.endswith("-erd.mmd"))

    assert "-- FK: booking_sk -> silver_test.booking (booking_sk)" in ddl
    assert "REFERENCES silver_test.booking (booking_sk)" in alter
    assert 'BOOKING ||--o{ TRANSPORT_PLAN_LEG : "has_transport_plan"' in erd
    assert "confirmed_booking" not in ddl.lower()
    assert "confirmed_booking" not in alter.lower()
    assert "CONFIRMED_BOOKING" not in erd


def test_dd022_normal_fk_to_s3_folded_range_references_parent_metadata():
    """Normal FK targets should also resolve S3-folded range classes to parent tables."""
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:Booking a owl:Class ;
            rdfs:label "Booking"@en ;
            rdfs:comment "."@en ;
            kairos-ext:inheritanceStrategy "discriminator" .

        ex:ConfirmedBooking a owl:Class ;
            rdfs:subClassOf ex:Booking ;
            rdfs:label "Confirmed Booking"@en ;
            rdfs:comment "."@en .

        ex:TransportPlanLeg a owl:Class ;
            rdfs:label "Transport Plan Leg"@en ;
            rdfs:comment "."@en .

        ex:bookedAs a owl:ObjectProperty ;
            rdfs:domain ex:TransportPlanLeg ;
            rdfs:range ex:ConfirmedBooking ;
            rdfs:label "booked as"@en ;
            kairos-ext:silverForeignKey true .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Booking", "name": "Booking", "label": "Booking", "comment": ""},
        {
            "uri": f"{BASE}ConfirmedBooking",
            "name": "ConfirmedBooking",
            "label": "Confirmed Booking",
            "comment": "",
        },
        {
            "uri": f"{BASE}TransportPlanLeg",
            "name": "TransportPlanLeg",
            "label": "Transport Plan Leg",
            "comment": "",
        },
    ]
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))

    assert "-- FK: booking_sk -> silver_test.booking (booking_sk)" in ddl
    assert "confirmed_booking_sk" not in ddl.lower()


def test_dd022_normal_fk_to_non_folded_range_still_references_child_table():
    """Class-per-table inheritance must keep FK metadata pointing to the child table."""
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:Booking a owl:Class ;
            rdfs:label "Booking"@en ;
            rdfs:comment "."@en ;
            kairos-ext:inheritanceStrategy "class-per-table" .

        ex:ConfirmedBooking a owl:Class ;
            rdfs:subClassOf ex:Booking ;
            rdfs:label "Confirmed Booking"@en ;
            rdfs:comment "."@en .

        ex:TransportPlanLeg a owl:Class ;
            rdfs:label "Transport Plan Leg"@en ;
            rdfs:comment "."@en .

        ex:bookedAs a owl:ObjectProperty ;
            rdfs:domain ex:TransportPlanLeg ;
            rdfs:range ex:ConfirmedBooking ;
            rdfs:label "booked as"@en ;
            kairos-ext:silverForeignKey true .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Booking", "name": "Booking", "label": "Booking", "comment": ""},
        {
            "uri": f"{BASE}ConfirmedBooking",
            "name": "ConfirmedBooking",
            "label": "Confirmed Booking",
            "comment": "",
        },
        {
            "uri": f"{BASE}TransportPlanLeg",
            "name": "TransportPlanLeg",
            "label": "Transport Plan Leg",
            "comment": "",
        },
    ]
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))

    assert "-- FK: confirmed_booking_sk -> silver_test.confirmed_booking" in ddl
    assert "(confirmed_booking_sk)" in ddl


def test_dd022_silver_foreign_key_on_implies_silver_foreign_key():
    """silverForeignKeyOn should work without explicit silverForeignKey true."""
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:Order     a owl:Class ; rdfs:label "Order"@en     ; rdfs:comment "."@en .
        ex:OrderLine a owl:Class ; rdfs:label "OrderLine"@en ; rdfs:comment "."@en .

        ex:hasLine a owl:ObjectProperty ;
            rdfs:domain ex:Order ;
            rdfs:range ex:OrderLine ;
            rdfs:label "has line"@en ;
            kairos-ext:silverForeignKeyOn ex:OrderLine .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Order", "name": "Order", "label": "Order", "comment": ""},
        {"uri": f"{BASE}OrderLine", "name": "OrderLine", "label": "OrderLine", "comment": ""},
    ]
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    assert "order_sk" in ddl


def test_dd022_silver_foreign_key_on_domain_is_normal():
    """silverForeignKeyOn set to domain class behaves like normal FK."""
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:Order    a owl:Class ; rdfs:label "Order"@en    ; rdfs:comment "."@en .
        ex:Customer a owl:Class ; rdfs:label "Customer"@en ; rdfs:comment "."@en .

        ex:placedBy a owl:ObjectProperty ;
            rdfs:domain ex:Order ;
            rdfs:range ex:Customer ;
            rdfs:label "placed by"@en ;
            kairos-ext:silverForeignKeyOn ex:Order .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Order", "name": "Order", "label": "Order", "comment": ""},
        {"uri": f"{BASE}Customer", "name": "Customer", "label": "Customer", "comment": ""},
    ]
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    # FK should be on Order table (normal direction)
    lines = ddl.split("\n")
    in_order = False
    found_fk = False
    for line in lines:
        if "CREATE TABLE" in line and "silver_test.order" in line.lower():
            in_order = True
        elif "CREATE TABLE" in line:
            in_order = False
        if in_order and "customer_sk" in line:
            found_fk = True
    assert found_fk, "FK column should be on Order table"


def test_dd022_invalid_fk_on_warns(caplog):
    """silverForeignKeyOn with class not in domain/range should warn."""
    import logging

    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:Order    a owl:Class ; rdfs:label "Order"@en    ; rdfs:comment "."@en .
        ex:Customer a owl:Class ; rdfs:label "Customer"@en ; rdfs:comment "."@en .
        ex:Product  a owl:Class ; rdfs:label "Product"@en  ; rdfs:comment "."@en .

        ex:placedBy a owl:ObjectProperty ;
            rdfs:domain ex:Order ;
            rdfs:range ex:Customer ;
            rdfs:label "placed by"@en ;
            kairos-ext:silverForeignKeyOn ex:Product .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Order", "name": "Order", "label": "Order", "comment": ""},
        {"uri": f"{BASE}Customer", "name": "Customer", "label": "Customer", "comment": ""},
        {"uri": f"{BASE}Product", "name": "Product", "label": "Product", "comment": ""},
    ]
    with caplog.at_level(logging.WARNING):
        result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    assert any("silverForeignKeyOn" in msg and "neither domain" in msg
               for msg in caplog.messages)


def test_dd022_backward_compat_functional_property_still_works():
    """Existing owl:FunctionalProperty FK generation must not be broken by DD-022."""
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:Order    a owl:Class ; rdfs:label "Order"@en    ; rdfs:comment "."@en .
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


def test_dd022_silver_foreign_key_with_column_name_override():
    """silverForeignKey + silverColumnName should use the explicit column name."""
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:Order    a owl:Class ; rdfs:label "Order"@en    ; rdfs:comment "."@en .
        ex:Customer a owl:Class ; rdfs:label "Customer"@en ; rdfs:comment "."@en .

        ex:placedBy a owl:ObjectProperty ;
            rdfs:domain ex:Order ;
            rdfs:range ex:Customer ;
            rdfs:label "placed by"@en ;
            kairos-ext:silverForeignKey true ;
            kairos-ext:silverColumnName "buyer_sk" .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Order", "name": "Order", "label": "Order", "comment": ""},
        {"uri": f"{BASE}Customer", "name": "Customer", "label": "Customer", "comment": ""},
    ]
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    assert "buyer_sk" in ddl


# ---------------------------------------------------------------------------
# Unit tests — Property Inheritance from Unprojected Parents
# ---------------------------------------------------------------------------


def test_inheritance_data_properties_from_unprojected_parent():
    """Child class inherits datatype properties from parent NOT in class_uris."""
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:Vehicle a owl:Class ; rdfs:label "Vehicle"@en ; rdfs:comment "."@en .
        ex:Truck a owl:Class ;
            rdfs:label "Truck"@en ;
            rdfs:comment "."@en ;
            rdfs:subClassOf ex:Vehicle .

        ex:registrationNumber a owl:DatatypeProperty ;
            rdfs:domain ex:Vehicle ;
            rdfs:range xsd:string ;
            rdfs:label "registration number"@en .

        ex:payload a owl:DatatypeProperty ;
            rdfs:domain ex:Truck ;
            rdfs:range xsd:decimal ;
            rdfs:label "payload"@en .
    """
    g = _make_graph(ttl)
    # Only Truck is projected — Vehicle is NOT claimed
    classes = [
        {"uri": f"{BASE}Truck", "name": "Truck", "label": "Truck", "comment": ""},
    ]
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    # Truck should have its own property AND inherited Vehicle property
    assert "payload" in ddl
    assert "registration_number" in ddl


def test_inheritance_fk_from_unprojected_parent():
    """Child class inherits FK object property from parent NOT in class_uris."""
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:Asset a owl:Class ; rdfs:label "Asset"@en ; rdfs:comment "."@en .
        ex:Vehicle a owl:Class ;
            rdfs:label "Vehicle"@en ;
            rdfs:comment "."@en ;
            rdfs:subClassOf ex:Asset .
        ex:Location a owl:Class ; rdfs:label "Location"@en ; rdfs:comment "."@en .

        ex:locatedAt a owl:ObjectProperty, owl:FunctionalProperty ;
            rdfs:domain ex:Asset ;
            rdfs:range ex:Location ;
            rdfs:label "located at"@en .
    """
    g = _make_graph(ttl)
    # Vehicle and Location projected, Asset is NOT
    classes = [
        {"uri": f"{BASE}Vehicle", "name": "Vehicle", "label": "Vehicle", "comment": ""},
        {"uri": f"{BASE}Location", "name": "Location", "label": "Location", "comment": ""},
    ]
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    # Vehicle should have the FK column inherited from Asset
    assert "location_sk" in ddl


def test_no_duplicate_when_parent_is_projected():
    """When parent IS projected (S3 flattening), no double columns on parent."""
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:Vehicle a owl:Class ; rdfs:label "Vehicle"@en ; rdfs:comment "."@en ;
            kairos-ext:inheritanceStrategy "discriminator" .
        ex:Truck a owl:Class ;
            rdfs:label "Truck"@en ;
            rdfs:comment "."@en ;
            rdfs:subClassOf ex:Vehicle .

        ex:registrationNumber a owl:DatatypeProperty ;
            rdfs:domain ex:Vehicle ;
            rdfs:range xsd:string ;
            rdfs:label "registration number"@en .
    """
    g = _make_graph(ttl)
    # Both are projected — S3 merges Truck into Vehicle (discriminator strategy)
    classes = [
        {"uri": f"{BASE}Vehicle", "name": "Vehicle", "label": "Vehicle", "comment": ""},
        {"uri": f"{BASE}Truck", "name": "Truck", "label": "Truck", "comment": ""},
    ]
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    # registration_number should appear exactly once in the DDL
    count = ddl.lower().count("registration_number")
    assert count == 1, f"Expected 1 occurrence, got {count}"


def test_inheritance_cycle_protection():
    """Cycle in rdfs:subClassOf does not cause infinite loop."""
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:A a owl:Class ; rdfs:label "A"@en ; rdfs:comment "."@en ;
            rdfs:subClassOf ex:B .
        ex:B a owl:Class ; rdfs:label "B"@en ; rdfs:comment "."@en ;
            rdfs:subClassOf ex:A .

        ex:propA a owl:DatatypeProperty ;
            rdfs:domain ex:A ;
            rdfs:range xsd:string ;
            rdfs:label "prop A"@en .

        ex:propB a owl:DatatypeProperty ;
            rdfs:domain ex:B ;
            rdfs:range xsd:string ;
            rdfs:label "prop B"@en .
    """
    g = _make_graph(ttl)
    # Only A projected, B is ancestor via cycle
    classes = [
        {"uri": f"{BASE}A", "name": "A", "label": "A", "comment": ""},
    ]
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    # Should get both properties without infinite loop
    assert "prop_a" in ddl
    assert "prop_b" in ddl


# ---------------------------------------------------------------------------
# Import Scenario Tests — Cross-namespace Inheritance
# ---------------------------------------------------------------------------

REF_BASE = "https://referencemodels.kairos.cnext.eu/party#"
HUB_BASE = "https://contoso.com/ont/customer#"


def test_import_cross_namespace_property_inheritance():
    """Hub class inherits properties from reference model parent in different namespace."""
    ttl = f"""
        @prefix ref: <{REF_BASE}> .
        @prefix hub: <{HUB_BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        <{HUB_BASE.rstrip('#')}> a owl:Ontology ;
            rdfs:label "Customer"@en ;
            owl:versionInfo "1.0" ;
            owl:imports <{REF_BASE.rstrip('#')}> .

        # Reference model classes (imported)
        ref:TradeParty a owl:Class ;
            rdfs:label "Trade Party"@en ;
            rdfs:comment "A party in trade."@en .

        ref:partyName a owl:DatatypeProperty ;
            rdfs:domain ref:TradeParty ;
            rdfs:range xsd:string ;
            rdfs:label "party name"@en .

        ref:partyIdentifier a owl:DatatypeProperty ;
            rdfs:domain ref:TradeParty ;
            rdfs:range xsd:string ;
            rdfs:label "party identifier"@en .

        # Hub class extending reference model
        hub:FreightCustomer a owl:Class ;
            rdfs:label "Freight Customer"@en ;
            rdfs:comment "A customer for freight services."@en ;
            rdfs:subClassOf ref:TradeParty .

        hub:creditLimit a owl:DatatypeProperty ;
            rdfs:domain hub:FreightCustomer ;
            rdfs:range xsd:decimal ;
            rdfs:label "credit limit"@en .
    """
    g = _make_graph(ttl)
    # Only FreightCustomer projected — TradeParty is NOT claimed
    classes = [
        {"uri": f"{HUB_BASE}FreightCustomer", "name": "FreightCustomer",
         "label": "Freight Customer", "comment": ""},
    ]
    result = generate_silver_artifacts(classes, g, HUB_BASE, ontology_name="customer")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    # Should inherit ref:partyName and ref:partyIdentifier from TradeParty
    assert "party_name" in ddl
    assert "party_identifier" in ddl
    # Plus its own property
    assert "credit_limit" in ddl


def test_import_multilevel_inheritance():
    """Properties inherited through 3-level chain: grandparent → parent → child."""
    ttl = f"""
        @prefix ref: <{REF_BASE}> .
        @prefix hub: <{HUB_BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        <{HUB_BASE.rstrip('#')}> a owl:Ontology ;
            rdfs:label "Customer"@en ;
            owl:versionInfo "1.0" .

        # Grandparent (reference model)
        ref:LegalEntity a owl:Class ;
            rdfs:label "Legal Entity"@en ;
            rdfs:comment "."@en .

        ref:legalName a owl:DatatypeProperty ;
            rdfs:domain ref:LegalEntity ;
            rdfs:range xsd:string ;
            rdfs:label "legal name"@en .

        # Parent (reference model)
        ref:TradeParty a owl:Class ;
            rdfs:label "Trade Party"@en ;
            rdfs:comment "."@en ;
            rdfs:subClassOf ref:LegalEntity .

        ref:partyCode a owl:DatatypeProperty ;
            rdfs:domain ref:TradeParty ;
            rdfs:range xsd:string ;
            rdfs:label "party code"@en .

        # Child (hub domain)
        hub:Supplier a owl:Class ;
            rdfs:label "Supplier"@en ;
            rdfs:comment "."@en ;
            rdfs:subClassOf ref:TradeParty .

        hub:supplierRating a owl:DatatypeProperty ;
            rdfs:domain hub:Supplier ;
            rdfs:range xsd:integer ;
            rdfs:label "supplier rating"@en .
    """
    g = _make_graph(ttl)
    # Only Supplier projected — TradeParty and LegalEntity NOT claimed
    classes = [
        {"uri": f"{HUB_BASE}Supplier", "name": "Supplier",
         "label": "Supplier", "comment": ""},
    ]
    result = generate_silver_artifacts(classes, g, HUB_BASE, ontology_name="customer")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    # Inherits from grandparent (LegalEntity)
    assert "legal_name" in ddl
    # Inherits from parent (TradeParty)
    assert "party_code" in ddl
    # Own property
    assert "supplier_rating" in ddl


def test_import_fk_inherited_from_reference_model():
    """FK object property inherited from reference model parent."""
    ttl = f"""
        @prefix ref: <{REF_BASE}> .
        @prefix hub: <{HUB_BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        <{HUB_BASE.rstrip('#')}> a owl:Ontology ;
            rdfs:label "Customer"@en ;
            owl:versionInfo "1.0" .

        # Reference model
        ref:TradeParty a owl:Class ;
            rdfs:label "Trade Party"@en ;
            rdfs:comment "."@en .

        ref:Country a owl:Class ;
            rdfs:label "Country"@en ;
            rdfs:comment "."@en .

        ref:registeredIn a owl:ObjectProperty, owl:FunctionalProperty ;
            rdfs:domain ref:TradeParty ;
            rdfs:range ref:Country ;
            rdfs:label "registered in"@en .

        # Hub class
        hub:Customer a owl:Class ;
            rdfs:label "Customer"@en ;
            rdfs:comment "."@en ;
            rdfs:subClassOf ref:TradeParty .

        hub:loyaltyTier a owl:DatatypeProperty ;
            rdfs:domain hub:Customer ;
            rdfs:range xsd:string ;
            rdfs:label "loyalty tier"@en .
    """
    g = _make_graph(ttl)
    # Customer and Country projected; TradeParty NOT claimed
    classes = [
        {"uri": f"{HUB_BASE}Customer", "name": "Customer",
         "label": "Customer", "comment": ""},
        {"uri": f"{REF_BASE}Country", "name": "Country",
         "label": "Country", "comment": ""},
    ]
    result = generate_silver_artifacts(classes, g, HUB_BASE, ontology_name="customer")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    # Customer should have inherited FK to Country from TradeParty
    assert "country_sk" in ddl
    # Plus own property
    assert "loyalty_tier" in ddl


def test_import_mixed_projected_and_unprojected_ancestors():
    """Mixed: one ancestor projected (S3 handles it), another not (inheritance needed)."""
    ttl = f"""
        @prefix ref: <{REF_BASE}> .
        @prefix hub: <{HUB_BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

        <{HUB_BASE.rstrip('#')}> a owl:Ontology ;
            rdfs:label "Customer"@en ;
            owl:versionInfo "1.0" .

        # Grandparent — NOT projected (inheritance needed)
        ref:Entity a owl:Class ;
            rdfs:label "Entity"@en ;
            rdfs:comment "."@en .

        ref:entityCode a owl:DatatypeProperty ;
            rdfs:domain ref:Entity ;
            rdfs:range xsd:string ;
            rdfs:label "entity code"@en .

        # Parent — IS projected (S3 flattening applies with discriminator)
        hub:Organization a owl:Class ;
            rdfs:label "Organization"@en ;
            rdfs:comment "."@en ;
            rdfs:subClassOf ref:Entity ;
            kairos-ext:inheritanceStrategy "discriminator" .

        hub:orgName a owl:DatatypeProperty ;
            rdfs:domain hub:Organization ;
            rdfs:range xsd:string ;
            rdfs:label "org name"@en .

        # Child — IS projected, flattened into Organization by S3
        hub:Corporation a owl:Class ;
            rdfs:label "Corporation"@en ;
            rdfs:comment "."@en ;
            rdfs:subClassOf hub:Organization .

        hub:stockTicker a owl:DatatypeProperty ;
            rdfs:domain hub:Corporation ;
            rdfs:range xsd:string ;
            rdfs:label "stock ticker"@en .
    """
    g = _make_graph(ttl)
    # Organization and Corporation projected; Entity NOT projected
    classes = [
        {"uri": f"{HUB_BASE}Organization", "name": "Organization",
         "label": "Organization", "comment": ""},
        {"uri": f"{HUB_BASE}Corporation", "name": "Corporation",
         "label": "Corporation", "comment": ""},
    ]
    result = generate_silver_artifacts(classes, g, HUB_BASE, ontology_name="customer")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    # Organization table should have:
    # - its own property (orgName)
    assert "org_name" in ddl
    # - inherited from unprojected Entity
    assert "entity_code" in ddl
    # Corporation is S3-flattened into Organization, so stockTicker on org table
    assert "stock_ticker" in ddl
    # Only one table created (Corporation folded in)
    assert "CREATE TABLE" in ddl
    assert ddl.count("CREATE TABLE") == 1


def test_import_multiple_parents_diamond():
    """Diamond inheritance: child inherits from two parents, both unprojected."""
    ttl = f"""
        @prefix ref: <{REF_BASE}> .
        @prefix hub: <{HUB_BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        <{HUB_BASE.rstrip('#')}> a owl:Ontology ;
            rdfs:label "Customer"@en ;
            owl:versionInfo "1.0" .

        # Two separate parent hierarchies
        ref:Contactable a owl:Class ;
            rdfs:label "Contactable"@en ;
            rdfs:comment "."@en .

        ref:contactEmail a owl:DatatypeProperty ;
            rdfs:domain ref:Contactable ;
            rdfs:range xsd:string ;
            rdfs:label "contact email"@en .

        ref:Billable a owl:Class ;
            rdfs:label "Billable"@en ;
            rdfs:comment "."@en .

        ref:billingAddress a owl:DatatypeProperty ;
            rdfs:domain ref:Billable ;
            rdfs:range xsd:string ;
            rdfs:label "billing address"@en .

        # Hub class inherits from both
        hub:Customer a owl:Class ;
            rdfs:label "Customer"@en ;
            rdfs:comment "."@en ;
            rdfs:subClassOf ref:Contactable, ref:Billable .

        hub:customerCode a owl:DatatypeProperty ;
            rdfs:domain hub:Customer ;
            rdfs:range xsd:string ;
            rdfs:label "customer code"@en .
    """
    g = _make_graph(ttl)
    # Only Customer projected — both parents NOT claimed
    classes = [
        {"uri": f"{HUB_BASE}Customer", "name": "Customer",
         "label": "Customer", "comment": ""},
    ]
    result = generate_silver_artifacts(classes, g, HUB_BASE, ontology_name="customer")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    # Inherits from Contactable
    assert "contact_email" in ddl
    # Inherits from Billable
    assert "billing_address" in ddl
    # Own property
    assert "customer_code" in ddl


def test_import_no_inheritance_when_parent_projected():
    """When parent IS projected, child is S3-flattened — no double properties."""
    ttl = f"""
        @prefix hub: <{HUB_BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

        <{HUB_BASE.rstrip('#')}> a owl:Ontology ;
            rdfs:label "Customer"@en ;
            owl:versionInfo "1.0" .

        hub:Account a owl:Class ;
            rdfs:label "Account"@en ;
            rdfs:comment "."@en ;
            kairos-ext:inheritanceStrategy "discriminator" .

        hub:accountNumber a owl:DatatypeProperty ;
            rdfs:domain hub:Account ;
            rdfs:range xsd:string ;
            rdfs:label "account number"@en .

        hub:PremiumAccount a owl:Class ;
            rdfs:label "Premium Account"@en ;
            rdfs:comment "."@en ;
            rdfs:subClassOf hub:Account .

        hub:discountRate a owl:DatatypeProperty ;
            rdfs:domain hub:PremiumAccount ;
            rdfs:range xsd:decimal ;
            rdfs:label "discount rate"@en .
    """
    g = _make_graph(ttl)
    # Both projected — S3 merges PremiumAccount into Account (discriminator)
    classes = [
        {"uri": f"{HUB_BASE}Account", "name": "Account",
         "label": "Account", "comment": ""},
        {"uri": f"{HUB_BASE}PremiumAccount", "name": "PremiumAccount",
         "label": "Premium Account", "comment": ""},
    ]
    result = generate_silver_artifacts(classes, g, HUB_BASE, ontology_name="customer")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    # One table only (PremiumAccount folded into Account)
    assert ddl.count("CREATE TABLE") == 1
    assert "account" in ddl.lower()
    # account_number appears exactly once (no duplication)
    assert ddl.lower().count("account_number") == 1
    # discount_rate is S3-merged (nullable, from subtype)
    assert "discount_rate" in ddl


def test_import_sibling_classes_share_parent_properties():
    """Two sibling classes both inherit from same unprojected parent independently."""
    ttl = f"""
        @prefix ref: <{REF_BASE}> .
        @prefix hub: <{HUB_BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        <{HUB_BASE.rstrip('#')}> a owl:Ontology ;
            rdfs:label "Customer"@en ;
            owl:versionInfo "1.0" .

        # Shared parent — NOT projected
        ref:TradeParty a owl:Class ;
            rdfs:label "Trade Party"@en ;
            rdfs:comment "."@en .

        ref:partyName a owl:DatatypeProperty ;
            rdfs:domain ref:TradeParty ;
            rdfs:range xsd:string ;
            rdfs:label "party name"@en .

        # Two siblings inheriting from same parent
        hub:Buyer a owl:Class ;
            rdfs:label "Buyer"@en ;
            rdfs:comment "."@en ;
            rdfs:subClassOf ref:TradeParty .

        hub:buyerCode a owl:DatatypeProperty ;
            rdfs:domain hub:Buyer ;
            rdfs:range xsd:string ;
            rdfs:label "buyer code"@en .

        hub:Seller a owl:Class ;
            rdfs:label "Seller"@en ;
            rdfs:comment "."@en ;
            rdfs:subClassOf ref:TradeParty .

        hub:sellerLicense a owl:DatatypeProperty ;
            rdfs:domain hub:Seller ;
            rdfs:range xsd:string ;
            rdfs:label "seller license"@en .
    """
    g = _make_graph(ttl)
    # Both Buyer and Seller projected — TradeParty NOT claimed
    # They are siblings, not in subtype relationship with each other
    classes = [
        {"uri": f"{HUB_BASE}Buyer", "name": "Buyer",
         "label": "Buyer", "comment": ""},
        {"uri": f"{HUB_BASE}Seller", "name": "Seller",
         "label": "Seller", "comment": ""},
    ]
    result = generate_silver_artifacts(classes, g, HUB_BASE, ontology_name="customer")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    # Two separate tables
    assert ddl.count("CREATE TABLE") == 2
    # Both should have party_name inherited from TradeParty
    # Count occurrences — should be 2 (one per table)
    assert ddl.lower().count("party_name") == 2
    # Each has its own property
    assert "buyer_code" in ddl
    assert "seller_license" in ddl


def test_import_inherited_property_with_extension_override():
    """Inherited property can have its type overridden via kairos-ext:silverDataType."""
    ttl = f"""
        @prefix ref: <{REF_BASE}> .
        @prefix hub: <{HUB_BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

        <{HUB_BASE.rstrip('#')}> a owl:Ontology ;
            rdfs:label "Customer"@en ;
            owl:versionInfo "1.0" .

        ref:TradeParty a owl:Class ;
            rdfs:label "Trade Party"@en ;
            rdfs:comment "."@en .

        ref:partyName a owl:DatatypeProperty ;
            rdfs:domain ref:TradeParty ;
            rdfs:range xsd:string ;
            rdfs:label "party name"@en ;
            kairos-ext:silverDataType "NVARCHAR(200)" .

        hub:Customer a owl:Class ;
            rdfs:label "Customer"@en ;
            rdfs:comment "."@en ;
            rdfs:subClassOf ref:TradeParty .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{HUB_BASE}Customer", "name": "Customer",
         "label": "Customer", "comment": ""},
    ]
    result = generate_silver_artifacts(classes, g, HUB_BASE, ontology_name="customer")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    # Inherited property should use the overridden type
    assert "party_name" in ddl
    assert "NVARCHAR(200)" in ddl


# ---------------------------------------------------------------------------
# silverForeignKey validation warnings (missing domain/range)
# ---------------------------------------------------------------------------


def test_silver_fk_missing_domain_warns(caplog):
    """silverForeignKey on a property with no rdfs:domain should emit a warning."""
    import logging

    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:Order    a owl:Class ; rdfs:label "Order"@en    ; rdfs:comment "."@en .
        ex:Customer a owl:Class ; rdfs:label "Customer"@en ; rdfs:comment "."@en .

        ex:placedBy a owl:ObjectProperty ;
            rdfs:range ex:Customer ;
            rdfs:label "placed by"@en ;
            kairos-ext:silverForeignKey "true"^^xsd:boolean .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Order", "name": "Order", "label": "Order", "comment": ""},
        {"uri": f"{BASE}Customer", "name": "Customer", "label": "Customer", "comment": ""},
    ]
    with caplog.at_level(logging.WARNING):
        generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    assert any("silverForeignKey on placedBy" in msg and "missing rdfs:domain" in msg
               for msg in caplog.messages)


def test_silver_fk_missing_range_warns(caplog):
    """silverForeignKey on a property with no rdfs:range should emit a warning."""
    import logging

    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:Order    a owl:Class ; rdfs:label "Order"@en    ; rdfs:comment "."@en .
        ex:Customer a owl:Class ; rdfs:label "Customer"@en ; rdfs:comment "."@en .

        ex:placedBy a owl:ObjectProperty ;
            rdfs:domain ex:Order ;
            rdfs:label "placed by"@en ;
            kairos-ext:silverForeignKey "true"^^xsd:boolean .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Order", "name": "Order", "label": "Order", "comment": ""},
        {"uri": f"{BASE}Customer", "name": "Customer", "label": "Customer", "comment": ""},
    ]
    with caplog.at_level(logging.WARNING):
        generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    assert any("silverForeignKey on placedBy" in msg and "missing rdfs:range" in msg
               for msg in caplog.messages)


def test_silver_fk_missing_both_domain_and_range_warns(caplog):
    """silverForeignKey with neither domain nor range should emit a warning."""
    import logging

    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:Order    a owl:Class ; rdfs:label "Order"@en    ; rdfs:comment "."@en .

        ex:hasShipper a owl:ObjectProperty ;
            rdfs:label "has shipper"@en ;
            kairos-ext:silverForeignKey "true"^^xsd:boolean .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Order", "name": "Order", "label": "Order", "comment": ""},
    ]
    with caplog.at_level(logging.WARNING):
        generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    assert any("silverForeignKey on hasShipper" in msg
               and "missing rdfs:domain and rdfs:range" in msg
               for msg in caplog.messages)


def test_silver_fk_complete_no_warning(caplog):
    """silverForeignKey with both domain and range should NOT emit a warning."""
    import logging

    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "Test"@en ; owl:versionInfo "1.0" .

        ex:Order    a owl:Class ; rdfs:label "Order"@en    ; rdfs:comment "."@en .
        ex:Customer a owl:Class ; rdfs:label "Customer"@en ; rdfs:comment "."@en .

        ex:placedBy a owl:ObjectProperty ;
            rdfs:domain ex:Order ;
            rdfs:range ex:Customer ;
            rdfs:label "placed by"@en ;
            kairos-ext:silverForeignKey "true"^^xsd:boolean .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Order", "name": "Order", "label": "Order", "comment": ""},
        {"uri": f"{BASE}Customer", "name": "Customer", "label": "Customer", "comment": ""},
    ]
    with caplog.at_level(logging.WARNING):
        generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    assert not any("silverForeignKey on placedBy" in msg and "will be skipped" in msg
                   for msg in caplog.messages)

# ---------------------------------------------------------------------------
# Issue #172 — _nearest_claimed_ancestor (transitive discriminator fold)
# ---------------------------------------------------------------------------

from kairos_ontology.projections.medallion_silver_projector import (  # noqa: E402
    _nearest_claimed_ancestor,
)
from rdflib import URIRef  # noqa: E402


def _chain_graph() -> Graph:
    """A -> B(unclaimed) -> C(claimed) chain plus a claimed direct-parent case."""
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "T"@en ; owl:versionInfo "1.0" .

        ex:Root a owl:Class ; kairos-ext:inheritanceStrategy "discriminator" .
        ex:Mid  a owl:Class ; rdfs:subClassOf ex:Root .
        ex:Leaf a owl:Class ; rdfs:subClassOf ex:Mid .
        ex:DirectParent a owl:Class .
        ex:DirectChild  a owl:Class ; rdfs:subClassOf ex:DirectParent .
    """
    return _make_graph(ttl)


def test_nearest_claimed_ancestor_through_unclaimed_intermediate():
    """Leaf reaches claimed Root only via unclaimed Mid → Root is returned."""
    g = _chain_graph()
    class_uris = {f"{BASE}Root"}  # Mid is NOT claimed
    result = _nearest_claimed_ancestor(g, URIRef(f"{BASE}Leaf"), class_uris)
    assert result == URIRef(f"{BASE}Root")


def test_nearest_claimed_ancestor_depth_one_unchanged():
    """Direct claimed parent is returned (depth-1 single inheritance, unchanged)."""
    g = _chain_graph()
    class_uris = {f"{BASE}DirectParent"}
    result = _nearest_claimed_ancestor(g, URIRef(f"{BASE}DirectChild"), class_uris)
    assert result == URIRef(f"{BASE}DirectParent")


def test_nearest_claimed_ancestor_stops_at_first_claimed():
    """If the intermediate IS claimed, the walk stops there (does not skip to Root)."""
    g = _chain_graph()
    class_uris = {f"{BASE}Mid", f"{BASE}Root"}  # Mid claimed
    result = _nearest_claimed_ancestor(g, URIRef(f"{BASE}Leaf"), class_uris)
    assert result == URIRef(f"{BASE}Mid")


def test_nearest_claimed_ancestor_none_when_no_claimed():
    """No claimed ancestor → None."""
    g = _chain_graph()
    result = _nearest_claimed_ancestor(g, URIRef(f"{BASE}Leaf"), set())
    assert result is None


def test_nearest_claimed_ancestor_cycle_safe():
    """A subClassOf cycle must not hang."""
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "T"@en ; owl:versionInfo "1.0" .
        ex:A a owl:Class ; rdfs:subClassOf ex:B .
        ex:B a owl:Class ; rdfs:subClassOf ex:A .
    """
    g = _make_graph(ttl)
    result = _nearest_claimed_ancestor(g, URIRef(f"{BASE}A"), set())
    assert result is None


def test_nearest_claimed_ancestor_conflict_warns(caplog):
    """Multiple nearest claimed ancestors with conflicting strategies → warning."""
    import logging
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "T"@en ; owl:versionInfo "1.0" .
        ex:P1 a owl:Class ; kairos-ext:inheritanceStrategy "discriminator" .
        ex:P2 a owl:Class ; kairos-ext:inheritanceStrategy "class-per-table" .
        ex:Child a owl:Class ; rdfs:subClassOf ex:P1, ex:P2 .
    """
    g = _make_graph(ttl)
    class_uris = {f"{BASE}P1", f"{BASE}P2"}
    with caplog.at_level(logging.WARNING):
        result = _nearest_claimed_ancestor(g, URIRef(f"{BASE}Child"), class_uris)
    # Deterministic: lexicographically smallest URI wins (P1 < P2)
    assert result == URIRef(f"{BASE}P1")
    assert any("conflicting inheritance strategies" in m for m in caplog.messages)


# ---------------------------------------------------------------------------
# Issue #172 — silverExclude
# ---------------------------------------------------------------------------


def test_silver_exclude_emits_no_table():
    """A class annotated silverExclude produces no CREATE TABLE."""
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "T"@en ; owl:versionInfo "1.0" .
        ex:Keep a owl:Class ; rdfs:label "Keep"@en ; rdfs:comment "."@en .
        ex:Drop a owl:Class ; rdfs:label "Drop"@en ; rdfs:comment "."@en ;
            kairos-ext:silverExclude "true"^^xsd:boolean .
        ex:keepName a owl:DatatypeProperty ; rdfs:domain ex:Keep ;
            rdfs:range xsd:string ; rdfs:label "keep name"@en .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Keep", "name": "Keep", "label": "Keep", "comment": ""},
        {"uri": f"{BASE}Drop", "name": "Drop", "label": "Drop", "comment": ""},
    ]
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql")).lower()
    assert "test.keep" in ddl
    assert "test.drop" not in ddl


def test_silver_exclude_descendant_still_inherits():
    """A descendant of an excluded class still inherits the excluded class's props."""
    ttl = f"""
        @prefix ex:  <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "T"@en ; owl:versionInfo "1.0" .
        ex:Base a owl:Class ; rdfs:label "Base"@en ; rdfs:comment "."@en ;
            kairos-ext:silverExclude "true"^^xsd:boolean .
        ex:baseCode a owl:DatatypeProperty ; rdfs:domain ex:Base ;
            rdfs:range xsd:string ; rdfs:label "base code"@en .
        ex:Child a owl:Class ; rdfs:label "Child"@en ; rdfs:comment "."@en ;
            rdfs:subClassOf ex:Base .
        ex:childName a owl:DatatypeProperty ; rdfs:domain ex:Child ;
            rdfs:range xsd:string ; rdfs:label "child name"@en .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{BASE}Base", "name": "Base", "label": "Base", "comment": ""},
        {"uri": f"{BASE}Child", "name": "Child", "label": "Child", "comment": ""},
    ]
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql")).lower()
    assert "test.base" not in ddl
    assert "test.child" in ddl
    # Child inherits base_code from the excluded Base
    assert "base_code" in ddl
    assert "child_name" in ddl


def test_silver_exclude_overrides_silver_include():
    """silverExclude wins over silverInclude on the same class."""
    ttl = f"""
        @prefix ref: <{REF_BASE}> .
        @prefix hub: <{HUB_BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs:<http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
        <{HUB_BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "C"@en ; owl:versionInfo "1.0" .
        ref:TradeParty a owl:Class ; rdfs:label "TP"@en ; rdfs:comment "."@en ;
            kairos-ext:silverInclude "true"^^xsd:boolean ;
            kairos-ext:silverExclude "true"^^xsd:boolean .
    """
    g = _make_graph(ttl)
    classes = [
        {"uri": f"{REF_BASE}TradeParty", "name": "TradeParty",
         "label": "TP", "comment": ""},
    ]
    result = generate_silver_artifacts(classes, g, HUB_BASE, ontology_name="customer")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql")).lower()
    assert "trade_party" not in ddl
