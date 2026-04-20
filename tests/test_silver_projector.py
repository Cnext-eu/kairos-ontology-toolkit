"""Tests for the silver layer projector (R1-R15)."""

import textwrap
from pathlib import Path

import pytest
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD

from kairos_ontology.projections.silver_projector import (
    ColumnDef,
    TableDef,
    _camel_to_snake,
    _parse_audit_envelope,
    generate_silver_artifacts,
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
    tbl.fk_constraints.append(("party_sk", "silver_test.party", "party_sk"))
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

def _load_silver_projector():
    """Load silver_projector from source, not from installed site-packages."""
    import importlib.util, sys
    src = Path(__file__).parent.parent / "src" / "kairos_ontology" / "projections" / "silver_projector.py"
    spec = importlib.util.spec_from_file_location("silver_projector_src", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_master_erd_merges_domains(tmp_path):
    generate_master_erd = _load_silver_projector().generate_master_erd

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
    generate_master_erd = _load_silver_projector().generate_master_erd

    silver_out = tmp_path / "silver"
    silver_out.mkdir()
    assert generate_master_erd(silver_out) is None
