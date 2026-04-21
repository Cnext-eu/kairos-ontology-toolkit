# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the silver layer projector (R1-R16)."""

import importlib.util
import textwrap
from pathlib import Path

import pytest
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD

# ---------------------------------------------------------------------------
# Load silver_projector from source (not installed site-packages)
# ---------------------------------------------------------------------------

def _load_silver_projector():
    src = Path(__file__).parent.parent / "src" / "kairos_ontology" / "projections" / "silver_projector.py"
    spec = importlib.util.spec_from_file_location("silver_projector_src", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_sp = _load_silver_projector()
ColumnDef = _sp.ColumnDef
TableDef = _sp.TableDef
_camel_to_snake = _sp._camel_to_snake
_mmd_type = _sp._mmd_type
_parse_audit_envelope = _sp._parse_audit_envelope
generate_silver_artifacts = _sp.generate_silver_artifacts
render_mermaid_svg = _sp.render_mermaid_svg

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
    tbl.columns.append(ColumnDef("party_sk", "NVARCHAR(36)", nullable=False))
    tbl.pk_column = "party_sk"
    sql = tbl.render_create()
    assert "CREATE TABLE silver_test.party" in sql
    assert "CONSTRAINT pk_party PRIMARY KEY (party_sk)" in sql


def test_table_def_render_alter_fk():
    tbl = TableDef("address", "silver_test")
    tbl.fk_constraints.append(("party_sk", "silver_test.party", "party_sk", "has_party"))
    stmts = tbl.render_alter()
    assert len(stmts) == 1
    assert "ADD CONSTRAINT fk_address_party_sk" in stmts[0]
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
    alter = next(v for k, v in result.items() if k.endswith("-alter.sql"))
    # Person table should not generate person_sk
    assert "person_sk" not in ddl
    # party_sk should appear in person table (as PK/FK)
    assert "party_sk" in ddl
    # FK constraint from person to party
    assert "REFERENCES" in alter
    assert "fk_person_party_sk" in alter
    # ERD uses descriptive label
    erd = next(v for k, v in result.items() if k.endswith("-erd.mmd"))
    assert '"inherits"' in erd


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
    generate_master_erd = _sp.generate_master_erd

    # Simulate two domain ERD files in output/silver/
    silver_out = tmp_path / "silver"
    (silver_out / "customer").mkdir(parents=True)
    (silver_out / "order").mkdir(parents=True)

    (silver_out / "customer" / "customer-erd.mmd").write_text(
        "erDiagram\n    %% Silver ERD: silver_customer / customer\n\n"
        "    CUSTOMER {\n        NVARCHAR(36) customer_sk\n    }\n",
        encoding="utf-8",
    )
    (silver_out / "order" / "order-erd.mmd").write_text(
        "erDiagram\n    %% Silver ERD: silver_order / order\n\n"
        "    ORDER {\n        NVARCHAR(36) order_sk\n    }\n",
        encoding="utf-8",
    )

    result = generate_master_erd(silver_out, hub_name="test-hub")
    assert result is not None
    assert result.startswith("erDiagram")
    assert "CUSTOMER" in result
    assert "ORDER" in result
    assert "Domain: customer" in result
    assert "Domain: order" in result
    assert result.count("erDiagram") == 1  # Only one header


def test_master_erd_returns_none_when_empty(tmp_path):
    generate_master_erd = _sp.generate_master_erd

    silver_out = tmp_path / "silver"
    silver_out.mkdir()
    assert generate_master_erd(silver_out) is None


def test_master_erd_excludes_own_previous_output(tmp_path):
    """Regression: master-erd.mmd must not be included in its own merge."""
    generate_master_erd = _sp.generate_master_erd

    silver_out = tmp_path / "silver"
    (silver_out / "customer").mkdir(parents=True)
    (silver_out / "customer" / "customer-erd.mmd").write_text(
        "erDiagram\n    %% Silver ERD: silver_customer / customer\n\n"
        "    CUSTOMER {\n        NVARCHAR_36 customer_sk\n    }\n",
        encoding="utf-8",
    )
    # Simulate a leftover master from a previous run
    (silver_out / "master-erd.mmd").write_text(
        "erDiagram\n    %% Master ERD — hub (all domains)\n\n"
        "    %% --- Domain: customer ---\n"
        "    CUSTOMER {\n        NVARCHAR_36 customer_sk\n    }\n",
        encoding="utf-8",
    )

    result = generate_master_erd(silver_out, hub_name="hub")
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
# R16 — Empty subtype suppression under discriminator strategy
# ---------------------------------------------------------------------------


def _r16_ontology() -> tuple[Graph, list[dict]]:
    """Ontology with discriminator parent, empty subtypes, and one non-empty subtype."""
    ttl = f"""
        @prefix ex:    <{BASE}> .
        @prefix owl:   <http://www.w3.org/2002/07/owl#> .
        @prefix rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
        @prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .
        @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

        <{BASE.rstrip('#')}> a owl:Ontology ; rdfs:label "R16 Test"@en ; owl:versionInfo "1.0" .

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

        # Empty subtype — should be folded
        ex:IndividualClient a owl:Class ;
            rdfs:subClassOf ex:Client ;
            rdfs:label "Individual Client"@en ;
            rdfs:comment "An individual client."@en ;
            kairos-ext:scdType "2" .

        # Empty subtype — should be folded
        ex:OrgClient a owl:Class ;
            rdfs:subClassOf ex:Client ;
            rdfs:label "Org Client"@en ;
            rdfs:comment "An org client."@en ;
            kairos-ext:scdType "2" .

        # Non-empty subtype — has its own property, should NOT be folded
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


def test_r16_empty_subtype_suppressed():
    """Empty subtypes under discriminator parent are not generated as tables."""
    g, classes = _r16_ontology()
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="r16test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    # Parent and non-empty subtype should exist
    assert "CREATE TABLE" in ddl
    assert "silver_r16test.client" in ddl.lower()
    assert "silver_r16test.special_client" in ddl.lower()
    # Empty subtypes should NOT exist
    assert "individual_client" not in ddl.lower()
    assert "org_client" not in ddl.lower()


def test_r16_folded_comment_in_ddl():
    """Parent DDL should contain R16 comment listing folded subtypes."""
    g, classes = _r16_ontology()
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="r16test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    assert "R16: subtypes folded into discriminator" in ddl
    assert "IndividualClient" in ddl
    assert "OrgClient" in ddl


def test_r16_nonempty_subtype_kept():
    """Subtypes with additional properties keep their own table."""
    g, classes = _r16_ontology()
    result = generate_silver_artifacts(classes, g, BASE, ontology_name="r16test")
    ddl = next(v for k, v in result.items() if k.endswith("-ddl.sql"))
    assert "special_client" in ddl.lower()
    assert "special_rating" in ddl.lower()


def test_r16_class_per_table_not_affected():
    """Subtypes under class-per-table strategy are NOT suppressed (even if empty)."""
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

        # Empty subtype under class-per-table — should still get a table
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
    assert "savings_account" in ddl.lower()


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
