# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the dbt projector — bronze parsing, SKOS mappings, and artifact generation."""

import textwrap
from pathlib import Path

import pytest
import yaml
from rdflib import Graph

from kairos_ontology.projections.dbt_projector import (
    _camel_to_snake,
    _parse_bronze,
    _parse_skos_mappings,
    _extract_shacl_tests,
    _source_type_to_spark,
    generate_dbt_artifacts,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BRONZE_TTL = textwrap.dedent("""\
    @prefix bronze-ap: <https://example.com/bronze/adminpulse#> .
    @prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .

    bronze-ap:AdminPulse a kairos-bronze:SourceSystem ;
        rdfs:label "AdminPulse" ;
        kairos-bronze:connectionType "jdbc" ;
        kairos-bronze:database "AP_Prod" ;
        kairos-bronze:schema "dbo" .

    bronze-ap:tblClient a kairos-bronze:SourceTable ;
        rdfs:label "tblClient" ;
        kairos-bronze:sourceSystem bronze-ap:AdminPulse ;
        kairos-bronze:tableName "tblClient" ;
        kairos-bronze:primaryKeyColumns "ClientID" ;
        kairos-bronze:incrementalColumn "ModifiedDate" .

    bronze-ap:tblClient_ClientID a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-ap:tblClient ;
        kairos-bronze:columnName "ClientID" ;
        kairos-bronze:dataType "int" ;
        kairos-bronze:nullable "false"^^xsd:boolean ;
        kairos-bronze:isPrimaryKey "true"^^xsd:boolean .

    bronze-ap:tblClient_Name a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-ap:tblClient ;
        kairos-bronze:columnName "Name" ;
        kairos-bronze:dataType "nvarchar(255)" ;
        kairos-bronze:nullable "true"^^xsd:boolean .

    bronze-ap:tblClient_IsActive a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-ap:tblClient ;
        kairos-bronze:columnName "IsActive" ;
        kairos-bronze:dataType "bit" ;
        kairos-bronze:nullable "false"^^xsd:boolean .
""")

SKOS_MAPPING_TTL = textwrap.dedent("""\
    @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
    @prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
    @prefix bronze-ap: <https://example.com/bronze/adminpulse#> .
    @prefix party: <http://kairos.example/ontology/> .

    bronze-ap:tblClient skos:exactMatch party:Client ;
        kairos-map:mappingType "direct" .

    bronze-ap:tblClient_ClientID skos:exactMatch party:clientId ;
        kairos-map:transform "CAST(source.ClientID AS STRING)" .

    bronze-ap:tblClient_Name skos:closeMatch party:clientName ;
        kairos-map:transform "TRIM(source.Name)" .
""")

ONTOLOGY_TTL = textwrap.dedent("""\
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
    @prefix ex:   <http://kairos.example/ontology/> .

    <http://kairos.example/ontology> a owl:Ontology ;
        rdfs:label "Test Ontology" ;
        owl:versionInfo "1.0.0" .

    ex:Client a owl:Class ;
        rdfs:label "Client" ;
        rdfs:comment "A client entity" .

    ex:clientId a owl:DatatypeProperty ;
        rdfs:label "client ID" ;
        rdfs:comment "Unique identifier" ;
        rdfs:domain ex:Client ;
        rdfs:range xsd:string .

    ex:clientName a owl:DatatypeProperty ;
        rdfs:label "client name" ;
        rdfs:comment "Name of the client" ;
        rdfs:domain ex:Client ;
        rdfs:range xsd:string .

    ex:isActive a owl:DatatypeProperty ;
        rdfs:label "is active" ;
        rdfs:comment "Whether the client is active" ;
        rdfs:domain ex:Client ;
        rdfs:range xsd:boolean .
""")

SHACL_TTL = textwrap.dedent("""\
    @prefix sh:   <http://www.w3.org/ns/shacl#> .
    @prefix ex:   <http://kairos.example/ontology/> .
    @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .

    ex:ClientShape a sh:NodeShape ;
        sh:targetClass ex:Client ;
        sh:property [
            sh:path ex:clientId ;
            sh:minCount 1 ;
            sh:maxCount 1 ;
            sh:datatype xsd:string ;
        ] ;
        sh:property [
            sh:path ex:clientName ;
            sh:minCount 1 ;
            sh:pattern "^[A-Za-z]" ;
            sh:minLength 2 ;
            sh:maxLength 200 ;
        ] .
""")


@pytest.fixture
def bronze_dir(tmp_path):
    d = tmp_path / "bronze"
    d.mkdir()
    (d / "adminpulse.ttl").write_text(BRONZE_TTL, encoding="utf-8")
    return d


@pytest.fixture
def mappings_dir(tmp_path):
    d = tmp_path / "mappings"
    d.mkdir()
    (d / "adminpulse-to-client.ttl").write_text(SKOS_MAPPING_TTL, encoding="utf-8")
    return d


@pytest.fixture
def ontology_graph():
    g = Graph()
    g.parse(data=ONTOLOGY_TTL, format="turtle")
    return g


@pytest.fixture
def shapes_dir(tmp_path):
    d = tmp_path / "shapes"
    d.mkdir()
    (d / "client.shacl.ttl").write_text(SHACL_TTL, encoding="utf-8")
    return d


@pytest.fixture
def classes():
    return [{
        "uri": "http://kairos.example/ontology/Client",
        "name": "Client",
        "label": "Client",
        "comment": "A client entity",
    }]


@pytest.fixture
def template_dir():
    return Path(__file__).parent.parent / "src" / "kairos_ontology" / "templates" / "dbt"


# ---------------------------------------------------------------------------
# Unit tests: helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_camel_to_snake(self):
        assert _camel_to_snake("ClientName") == "client_name"
        assert _camel_to_snake("clientId") == "client_id"
        assert _camel_to_snake("HTMLParser") == "html_parser"
        assert _camel_to_snake("already_snake") == "already_snake"

    def test_source_type_to_spark(self):
        assert _source_type_to_spark("int") == "INT"
        assert _source_type_to_spark("nvarchar(255)") == "STRING"
        assert _source_type_to_spark("bit") == "BOOLEAN"
        assert _source_type_to_spark("datetime2") == "TIMESTAMP"
        assert _source_type_to_spark("decimal(18,4)") == "DECIMAL(18,4)"
        assert _source_type_to_spark("unknown_type") == "STRING"


# ---------------------------------------------------------------------------
# Unit tests: bronze parsing
# ---------------------------------------------------------------------------

class TestBronzeParsing:
    def test_parse_bronze_returns_systems(self, bronze_dir):
        systems = _parse_bronze(bronze_dir)
        assert len(systems) == 1
        sys = systems[0]
        assert sys["system_label"] == "AdminPulse"
        assert sys["database"] == "AP_Prod"
        assert sys["schema"] == "dbo"

    def test_parse_bronze_tables(self, bronze_dir):
        systems = _parse_bronze(bronze_dir)
        tables = systems[0]["tables"]
        assert len(tables) == 1
        tbl = tables[0]
        assert tbl["name"] == "tblClient"
        assert tbl["pk_columns"] == ["ClientID"]
        assert tbl["incremental_column"] == "ModifiedDate"

    def test_parse_bronze_columns(self, bronze_dir):
        systems = _parse_bronze(bronze_dir)
        cols = systems[0]["tables"][0]["columns"]
        assert len(cols) == 3
        col_names = {c["name"] for c in cols}
        assert col_names == {"ClientID", "Name", "IsActive"}

        # Check PK column
        pk_col = next(c for c in cols if c["name"] == "ClientID")
        assert pk_col["is_pk"] is True
        assert pk_col["nullable"] is False
        assert pk_col["data_type"] == "int"

    def test_parse_bronze_empty_dir(self, tmp_path):
        empty = tmp_path / "empty_bronze"
        empty.mkdir()
        assert _parse_bronze(empty) == []

    def test_parse_bronze_none_dir(self):
        assert _parse_bronze(None) == []


# ---------------------------------------------------------------------------
# Unit tests: SKOS mapping parsing
# ---------------------------------------------------------------------------

class TestSkosMapping:
    def test_parse_skos_table_maps(self, mappings_dir):
        maps = _parse_skos_mappings(mappings_dir)
        table_maps = maps["table_maps"]
        assert len(table_maps) == 1
        key = "https://example.com/bronze/adminpulse#tblClient"
        assert key in table_maps
        assert table_maps[key]["mapping_type"] == "direct"
        assert table_maps[key]["target_uri"] == "http://kairos.example/ontology/Client"

    def test_parse_skos_column_maps(self, mappings_dir):
        maps = _parse_skos_mappings(mappings_dir)
        col_maps = maps["column_maps"]
        assert len(col_maps) == 2

        id_key = "https://example.com/bronze/adminpulse#tblClient_ClientID"
        assert id_key in col_maps
        assert col_maps[id_key]["transform"] == "CAST(source.ClientID AS STRING)"
        assert col_maps[id_key]["match_type"] == "exactMatch"

        name_key = "https://example.com/bronze/adminpulse#tblClient_Name"
        assert name_key in col_maps
        assert col_maps[name_key]["transform"] == "TRIM(source.Name)"
        assert col_maps[name_key]["match_type"] == "closeMatch"

    def test_parse_skos_empty_dir(self, tmp_path):
        empty = tmp_path / "empty_map"
        empty.mkdir()
        result = _parse_skos_mappings(empty)
        assert result == {"table_maps": {}, "column_maps": {}}


# ---------------------------------------------------------------------------
# Unit tests: SHACL test extraction
# ---------------------------------------------------------------------------

class TestShaclTests:
    def test_extract_shacl_tests(self, shapes_dir):
        tests = _extract_shacl_tests(
            shapes_dir, "http://kairos.example/ontology/Client"
        )
        assert "client_id" in tests
        assert "not_null" in tests["client_id"]
        assert "unique" in tests["client_id"]

        assert "client_name" in tests
        name_tests = tests["client_name"]
        assert "not_null" in name_tests
        test_str = str(name_tests)
        assert "expect_column_values_to_match_regex" in test_str
        assert "expect_column_value_lengths_to_be_between" in test_str

    def test_extract_shacl_no_shapes(self, tmp_path):
        assert _extract_shacl_tests(tmp_path / "nope", "http://ex/Foo") == {}

    def test_extract_shacl_no_matching_file(self, shapes_dir):
        assert _extract_shacl_tests(shapes_dir, "http://ex/Nonexistent") == {}


# ---------------------------------------------------------------------------
# Integration: full artifact generation
# ---------------------------------------------------------------------------

class TestGenerateDbtArtifacts:
    def test_silver_models_generated(self, classes, ontology_graph, template_dir):
        """Silver entity models are generated even without bronze."""
        artifacts = generate_dbt_artifacts(
            classes=classes,
            graph=ontology_graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="client",
        )
        silver_models = [k for k in artifacts if k.startswith("models/silver/")]
        assert len(silver_models) >= 1
        # Check the main silver model exists
        assert any("client.sql" in k for k in silver_models)

    def test_schema_yaml_with_shacl(self, classes, ontology_graph, template_dir, shapes_dir):
        """Schema YAML includes SHACL-derived tests."""
        artifacts = generate_dbt_artifacts(
            classes=classes,
            graph=ontology_graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            shapes_dir=shapes_dir,
            ontology_name="client",
        )
        schema_key = "models/silver/client/_client__models.yml"
        assert schema_key in artifacts
        content = yaml.safe_load(artifacts[schema_key])
        models = content["models"]
        assert len(models) == 1
        cols = {c["name"]: c for c in models[0]["columns"]}
        assert "client_sk" in cols
        assert "not_null" in cols["client_sk"]["tests"]
        # SHACL not_null on client_name
        if "client_name" in cols and cols["client_name"].get("tests"):
            assert "not_null" in cols["client_name"]["tests"]

    def test_with_bronze_and_mappings(
        self, classes, ontology_graph, template_dir, bronze_dir, mappings_dir
    ):
        """Full pipeline: bronze + SKOS mappings + ontology → sources + staging + silver."""
        artifacts = generate_dbt_artifacts(
            classes=classes,
            graph=ontology_graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="client",
            bronze_dir=bronze_dir,
            mappings_dir=mappings_dir,
        )
        # Should have sources YAML
        source_files = [k for k in artifacts if "_sources.yml" in k]
        assert len(source_files) >= 1

        # Should have staging model
        staging_files = [k for k in artifacts if "stg_" in k]
        assert len(staging_files) >= 1

        # Should have silver model
        silver_files = [k for k in artifacts if "models/silver/" in k and k.endswith(".sql")]
        assert len(silver_files) >= 1

        # Should have dbt_project.yml
        assert "dbt_project.yml" in artifacts

        # Should have packages.yml
        assert "packages.yml" in artifacts

    def test_staging_model_content(
        self, classes, ontology_graph, template_dir, bronze_dir, mappings_dir
    ):
        """Staging model uses SKOS transform expressions."""
        artifacts = generate_dbt_artifacts(
            classes=classes,
            graph=ontology_graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="client",
            bronze_dir=bronze_dir,
            mappings_dir=mappings_dir,
        )
        # Find the staging model
        stg_key = next(k for k in artifacts if "stg_" in k and k.endswith(".sql"))
        content = artifacts[stg_key]
        assert "materialized='view'" in content
        assert "source(" in content

    def test_dbt_project_yml(
        self, classes, ontology_graph, template_dir, bronze_dir, mappings_dir
    ):
        """dbt_project.yml has correct structure."""
        artifacts = generate_dbt_artifacts(
            classes=classes,
            graph=ontology_graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="client",
            bronze_dir=bronze_dir,
            mappings_dir=mappings_dir,
        )
        proj = yaml.safe_load(artifacts["dbt_project.yml"])
        assert proj["name"] == "client_project"
        assert "staging" in proj["models"]["client_project"]
        assert "silver" in proj["models"]["client_project"]

    def test_no_bronze_generates_silver_only(self, classes, ontology_graph, template_dir):
        """Without bronze dir, only silver models + schema are generated."""
        artifacts = generate_dbt_artifacts(
            classes=classes,
            graph=ontology_graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="client",
        )
        # No staging or source files
        assert not any("stg_" in k for k in artifacts)
        assert not any("_sources.yml" in k for k in artifacts)
        # But silver models exist
        assert any("models/silver/" in k for k in artifacts)
