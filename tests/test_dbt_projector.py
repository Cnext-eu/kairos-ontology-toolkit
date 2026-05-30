# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the dbt projector — bronze parsing, SKOS mappings, and artifact generation."""

import logging
import textwrap
from pathlib import Path

import pytest
import yaml
from rdflib import Graph, URIRef
from rdflib.namespace import RDFS

from kairos_ontology.projections.medallion_dbt_projector import (
    _build_silver_model_registry,
    _camel_to_snake,
    _parse_bronze,
    _parse_skos_mappings,
    _extract_shacl_tests,
    _silver_model_name_for_class,
    _source_type_to_databricks,
    _extract_fk_columns_and_joins,
    _get_natural_key,
    _get_nk_property_uris,
    _get_raw_natural_key,
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

    def test_source_type_to_databricks(self):
        assert _source_type_to_databricks("int") == "INT"
        assert _source_type_to_databricks("nvarchar(255)") == "STRING"
        assert _source_type_to_databricks("bit") == "BOOLEAN"
        assert _source_type_to_databricks("datetime2") == "TIMESTAMP"
        assert _source_type_to_databricks("decimal(18,4)") == "DECIMAL(18,4)"
        assert _source_type_to_databricks("unknown_type") == "STRING"


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
        assert table_maps[key][0]["mapping_type"] == "direct"
        assert table_maps[key][0]["target_uri"] == "http://kairos.example/ontology/Client"

    def test_parse_skos_column_maps(self, mappings_dir):
        maps = _parse_skos_mappings(mappings_dir)
        col_maps = maps["column_maps"]
        assert len(col_maps) == 2

        id_key = "https://example.com/bronze/adminpulse#tblClient_ClientID"
        assert id_key in col_maps
        assert col_maps[id_key][0]["transform"] == "CAST(source.ClientID AS STRING)"
        assert col_maps[id_key][0]["match_type"] == "exactMatch"

        name_key = "https://example.com/bronze/adminpulse#tblClient_Name"
        assert name_key in col_maps
        assert col_maps[name_key][0]["transform"] == "TRIM(source.Name)"
        assert col_maps[name_key][0]["match_type"] == "closeMatch"

    def test_parse_skos_empty_dir(self, tmp_path):
        empty = tmp_path / "empty_map"
        empty.mkdir()
        result = _parse_skos_mappings(empty)
        assert result == {"table_maps": {}, "column_maps": {}}

    def test_parse_skos_subdirectory(self, tmp_path):
        """Mapping files in subdirectories are discovered (rglob)."""
        d = tmp_path / "mappings"
        sub = d / "adminpulse"
        sub.mkdir(parents=True)
        (sub / "adminpulse-to-client.ttl").write_text(SKOS_MAPPING_TTL, encoding="utf-8")
        maps = _parse_skos_mappings(d)
        assert len(maps["table_maps"]) == 1
        assert len(maps["column_maps"]) == 2

    def test_parse_skos_split_pattern(self, tmp_path):
        """One bronze table mapping to multiple domain classes (1:N split)."""
        split_ttl = textwrap.dedent("""\
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
            @prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
            @prefix bronze-ap: <https://example.com/bronze/adminpulse#> .
            @prefix party: <http://kairos.example/ontology/> .

            bronze-ap:tblContacts skos:exactMatch party:Client ;
                kairos-map:mappingType "split" ;
                kairos-map:filterCondition "source.ContactType = 'CLIENT'" .

            bronze-ap:tblContacts skos:exactMatch party:ContactPerson ;
                kairos-map:mappingType "split" ;
                kairos-map:filterCondition "source.ContactType = 'CONTACT'" .
        """)
        d = tmp_path / "mappings"
        d.mkdir()
        (d / "contacts-split.ttl").write_text(split_ttl, encoding="utf-8")
        maps = _parse_skos_mappings(d)
        # One key (the bronze table URI), but TWO entries in the list
        key = "https://example.com/bronze/adminpulse#tblContacts"
        assert key in maps["table_maps"]
        assert len(maps["table_maps"][key]) == 2
        targets = {e["target_uri"] for e in maps["table_maps"][key]}
        assert "http://kairos.example/ontology/Client" in targets
        assert "http://kairos.example/ontology/ContactPerson" in targets


    def test_parse_skos_default_value(self, tmp_path):
        """kairos-map:defaultValue is captured in column_maps."""
        default_ttl = textwrap.dedent("""\
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
            @prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
            @prefix bronze-ap: <https://example.com/bronze/adminpulse#> .
            @prefix party: <http://kairos.example/ontology/> .

            bronze-ap:tblClient skos:exactMatch party:Client ;
                kairos-map:mappingType "direct" .

            bronze-ap:tblClient_Email skos:exactMatch party:email ;
                kairos-map:transform "source.Email" ;
                kairos-map:defaultValue "'unknown@example.com'" .
        """)
        d = tmp_path / "mappings"
        d.mkdir()
        (d / "default-val.ttl").write_text(default_ttl, encoding="utf-8")
        maps = _parse_skos_mappings(d)
        col = maps["column_maps"]["https://example.com/bronze/adminpulse#tblClient_Email"][0]
        assert col["default_value"] == "'unknown@example.com'"
        assert col["transform"] == "source.Email"

    def test_parse_multi_target_column(self, tmp_path):
        """One source column → two target properties produces two entries."""
        multi_ttl = textwrap.dedent("""\
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
            @prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
            @prefix bronze-ap: <https://example.com/bronze/adminpulse#> .
            @prefix party: <http://kairos.example/ontology/> .

            bronze-ap:tblClient skos:exactMatch party:Client ;
                kairos-map:mappingType "direct" .

            bronze-ap:tblClient_Name skos:exactMatch party:clientName ;
                kairos-map:transform "source.Name" .

            bronze-ap:tblClient_Name skos:exactMatch party:displayName ;
                kairos-map:transform "source.Name" .
        """)
        d = tmp_path / "mappings"
        d.mkdir()
        (d / "multi-target.ttl").write_text(multi_ttl, encoding="utf-8")
        maps = _parse_skos_mappings(d)
        col_key = "https://example.com/bronze/adminpulse#tblClient_Name"
        assert col_key in maps["column_maps"]
        targets = maps["column_maps"][col_key]
        assert len(targets) == 2, f"Expected 2 targets, got {len(targets)}"
        target_uris = {t["target_uri"] for t in targets}
        assert "http://kairos.example/ontology/clientName" in target_uris
        assert "http://kairos.example/ontology/displayName" in target_uris


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
    def test_silver_models_generated(self, classes, ontology_graph, template_dir,
                                       bronze_dir, mappings_dir):
        """Silver entity models are generated when bronze + mappings exist."""
        artifacts = generate_dbt_artifacts(
            classes=classes,
            graph=ontology_graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="client",
            bronze_dir=bronze_dir,
            mappings_dir=mappings_dir,
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
        """Full pipeline: bronze + SKOS mappings + ontology → sources + silver."""
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

        # No staging models (staging layer removed — silver reads bronze directly)
        staging_files = [k for k in artifacts if "stg_" in k]
        assert len(staging_files) == 0

        # Should have silver model
        silver_files = [k for k in artifacts if "models/silver/" in k and k.endswith(".sql")]
        assert len(silver_files) >= 1

        # Should have dbt_project.yml
        assert "dbt_project.yml" in artifacts

        # Should have packages.yml
        assert "packages.yml" in artifacts

    def test_silver_model_uses_source(
        self, classes, ontology_graph, template_dir, bronze_dir, mappings_dir
    ):
        """Silver model uses source() to read from bronze (no staging ref)."""
        artifacts = generate_dbt_artifacts(
            classes=classes,
            graph=ontology_graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="client",
            bronze_dir=bronze_dir,
            mappings_dir=mappings_dir,
        )
        # Find the silver model
        silver_key = next(
            k for k in artifacts
            if "models/silver/" in k and k.endswith(".sql") and "_sources" not in k
        )
        content = artifacts[silver_key]
        # Silver reads from bronze via source()
        assert "source(" in content
        # No ref to staging models
        assert "stg_" not in content

    def test_dbt_project_yml(
        self, classes, ontology_graph, template_dir, bronze_dir, mappings_dir
    ):
        """dbt_project.yml has correct structure (no staging section)."""
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
        # No staging section in the new architecture
        assert "staging" not in proj["models"]["client_project"]
        assert "silver" in proj["models"]["client_project"]
        assert proj.get("docs-paths") == ["docs"]

    def test_no_bronze_generates_silver_only(self, classes, ontology_graph, template_dir):
        """Without bronze dir, schema YAML is generated but no SQL models."""
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
        # Schema YAML is generated (no systems = no filtering)
        assert any("_models.yml" in k for k in artifacts)
        # But no .sql silver models (no bronze mapping → no model generated)
        silver_sql = [k for k in artifacts if "models/silver/" in k and k.endswith(".sql")]
        assert not silver_sql


# ---------------------------------------------------------------------------
# Gold dbt model generation (thick gold — pre-materialized star schema)
# ---------------------------------------------------------------------------

# Ontology with fact + dimensions for gold tests
GOLD_ONTOLOGY_TTL = textwrap.dedent("""\
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
    @prefix ex:   <http://kairos.example/ontology/> .

    <http://kairos.example/ontology> a owl:Ontology ;
        rdfs:label "Test Ontology" ;
        owl:versionInfo "1.0.0" .

    ex:Customer a owl:Class ;
        rdfs:label "Customer" ;
        rdfs:comment "A customer entity" .

    ex:Product a owl:Class ;
        rdfs:label "Product" ;
        rdfs:comment "A product entity" .

    ex:Order a owl:Class ;
        rdfs:label "Order" ;
        rdfs:comment "An order entity" .

    ex:customerName a owl:DatatypeProperty ;
        rdfs:label "customer name" ;
        rdfs:domain ex:Customer ;
        rdfs:range xsd:string .

    ex:productName a owl:DatatypeProperty ;
        rdfs:label "product name" ;
        rdfs:domain ex:Product ;
        rdfs:range xsd:string .

    ex:orderDate a owl:DatatypeProperty ;
        rdfs:label "order date" ;
        rdfs:domain ex:Order ;
        rdfs:range xsd:date .

    ex:orderAmount a owl:DatatypeProperty ;
        rdfs:label "order amount" ;
        rdfs:domain ex:Order ;
        rdfs:range xsd:decimal .

    ex:hasCustomer a owl:ObjectProperty, owl:FunctionalProperty ;
        rdfs:domain ex:Order ;
        rdfs:range ex:Customer ;
        rdfs:label "has customer" .

    ex:hasProduct a owl:ObjectProperty, owl:FunctionalProperty ;
        rdfs:domain ex:Order ;
        rdfs:range ex:Product ;
        rdfs:label "has product" .
""")

GOLD_CLASSES = [
    {"uri": "http://kairos.example/ontology/Customer",
     "name": "Customer", "label": "Customer", "comment": "A customer entity"},
    {"uri": "http://kairos.example/ontology/Product",
     "name": "Product", "label": "Product", "comment": "A product entity"},
    {"uri": "http://kairos.example/ontology/Order",
     "name": "Order", "label": "Order", "comment": "An order entity"},
]

GOLD_BRONZE_TTL = textwrap.dedent("""\
    @prefix bronze-sales: <https://example.com/bronze/sales#> .
    @prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .

    bronze-sales:SalesDB a kairos-bronze:SourceSystem ;
        rdfs:label "SalesDB" ;
        kairos-bronze:connectionType "jdbc" ;
        kairos-bronze:database "Sales_Prod" ;
        kairos-bronze:schema "dbo" .

    bronze-sales:tblCustomer a kairos-bronze:SourceTable ;
        rdfs:label "tblCustomer" ;
        kairos-bronze:sourceSystem bronze-sales:SalesDB ;
        kairos-bronze:tableName "tblCustomer" ;
        kairos-bronze:primaryKeyColumns "CustomerID" .

    bronze-sales:tblCustomer_CustomerID a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-sales:tblCustomer ;
        kairos-bronze:columnName "CustomerID" ;
        kairos-bronze:dataType "int" ;
        kairos-bronze:nullable "false"^^xsd:boolean ;
        kairos-bronze:isPrimaryKey "true"^^xsd:boolean .

    bronze-sales:tblCustomer_Name a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-sales:tblCustomer ;
        kairos-bronze:columnName "Name" ;
        kairos-bronze:dataType "nvarchar(255)" ;
        kairos-bronze:nullable "true"^^xsd:boolean .

    bronze-sales:tblProduct a kairos-bronze:SourceTable ;
        rdfs:label "tblProduct" ;
        kairos-bronze:sourceSystem bronze-sales:SalesDB ;
        kairos-bronze:tableName "tblProduct" ;
        kairos-bronze:primaryKeyColumns "ProductID" .

    bronze-sales:tblProduct_ProductID a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-sales:tblProduct ;
        kairos-bronze:columnName "ProductID" ;
        kairos-bronze:dataType "int" ;
        kairos-bronze:nullable "false"^^xsd:boolean ;
        kairos-bronze:isPrimaryKey "true"^^xsd:boolean .

    bronze-sales:tblProduct_Name a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-sales:tblProduct ;
        kairos-bronze:columnName "Name" ;
        kairos-bronze:dataType "nvarchar(255)" ;
        kairos-bronze:nullable "true"^^xsd:boolean .

    bronze-sales:tblOrder a kairos-bronze:SourceTable ;
        rdfs:label "tblOrder" ;
        kairos-bronze:sourceSystem bronze-sales:SalesDB ;
        kairos-bronze:tableName "tblOrder" ;
        kairos-bronze:primaryKeyColumns "OrderID" .

    bronze-sales:tblOrder_OrderID a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-sales:tblOrder ;
        kairos-bronze:columnName "OrderID" ;
        kairos-bronze:dataType "int" ;
        kairos-bronze:nullable "false"^^xsd:boolean ;
        kairos-bronze:isPrimaryKey "true"^^xsd:boolean .

    bronze-sales:tblOrder_OrderDate a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-sales:tblOrder ;
        kairos-bronze:columnName "OrderDate" ;
        kairos-bronze:dataType "date" ;
        kairos-bronze:nullable "true"^^xsd:boolean .

    bronze-sales:tblOrder_Amount a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-sales:tblOrder ;
        kairos-bronze:columnName "Amount" ;
        kairos-bronze:dataType "decimal(18,2)" ;
        kairos-bronze:nullable "true"^^xsd:boolean .
""")

GOLD_MAPPING_TTL = textwrap.dedent("""\
    @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
    @prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
    @prefix bronze-sales: <https://example.com/bronze/sales#> .
    @prefix ex: <http://kairos.example/ontology/> .

    bronze-sales:tblCustomer skos:exactMatch ex:Customer ;
        kairos-map:mappingType "direct" .
    bronze-sales:tblCustomer_CustomerID skos:exactMatch ex:customerId .
    bronze-sales:tblCustomer_Name skos:exactMatch ex:customerName .

    bronze-sales:tblProduct skos:exactMatch ex:Product ;
        kairos-map:mappingType "direct" .
    bronze-sales:tblProduct_ProductID skos:exactMatch ex:productId .
    bronze-sales:tblProduct_Name skos:exactMatch ex:productName .

    bronze-sales:tblOrder skos:exactMatch ex:Order ;
        kairos-map:mappingType "direct" .
    bronze-sales:tblOrder_OrderID skos:exactMatch ex:orderId .
    bronze-sales:tblOrder_OrderDate skos:exactMatch ex:orderDate .
    bronze-sales:tblOrder_Amount skos:exactMatch ex:orderAmount .
""")


@pytest.fixture
def gold_ontology_graph():
    g = Graph()
    g.parse(data=GOLD_ONTOLOGY_TTL, format="turtle")
    return g


@pytest.fixture
def gold_bronze_dir(tmp_path):
    d = tmp_path / "gold_bronze"
    d.mkdir()
    (d / "sales.ttl").write_text(GOLD_BRONZE_TTL, encoding="utf-8")
    return d


@pytest.fixture
def gold_mappings_dir(tmp_path):
    d = tmp_path / "gold_mappings"
    d.mkdir()
    (d / "sales-to-sales.ttl").write_text(GOLD_MAPPING_TTL, encoding="utf-8")
    return d


class TestGoldDbtModels:
    """Tests for gold dbt model generation (thick gold — DirectLake optimized)."""

    def test_gold_models_generated(self, gold_ontology_graph, template_dir,
                                   gold_bronze_dir, gold_mappings_dir):
        """Gold models are generated alongside silver when bronze sources exist."""
        artifacts = generate_dbt_artifacts(
            classes=GOLD_CLASSES,
            graph=gold_ontology_graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="sales",
            bronze_dir=gold_bronze_dir,
            mappings_dir=gold_mappings_dir,
        )
        gold_models = [k for k in artifacts if k.startswith("models/gold/")]
        assert len(gold_models) >= 3  # at least dim_date, dim_customer, fact_order
        # Check specific gold model paths
        assert any("dim_customer.sql" in k for k in gold_models)
        assert any("fact_order.sql" in k for k in gold_models)
        assert any("dim_date.sql" in k for k in gold_models)

    def test_gold_model_refs_silver(self, gold_ontology_graph, template_dir,
                                    gold_bronze_dir, gold_mappings_dir):
        """Gold models use ref() to reference silver models."""
        artifacts = generate_dbt_artifacts(
            classes=GOLD_CLASSES,
            graph=gold_ontology_graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="sales",
            bronze_dir=gold_bronze_dir,
            mappings_dir=gold_mappings_dir,
        )
        dim_key = next(k for k in artifacts if "dim_customer.sql" in k)
        content = artifacts[dim_key]
        assert "ref('customer')" in content
        assert "materialized='table'" in content

    def test_gold_fact_model_content(self, gold_ontology_graph, template_dir,
                                     gold_bronze_dir, gold_mappings_dir):
        """Fact table gold model has correct structure."""
        artifacts = generate_dbt_artifacts(
            classes=GOLD_CLASSES,
            graph=gold_ontology_graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="sales",
            bronze_dir=gold_bronze_dir,
            mappings_dir=gold_mappings_dir,
        )
        fact_key = next(k for k in artifacts if "fact_order.sql" in k)
        content = artifacts[fact_key]
        assert "materialized='table'" in content
        assert "gold_sales" in content
        # Fact table should reference silver model
        assert "ref(" in content
        # Should mention it's a fact table
        assert "Fact table" in content

    def test_gold_dimension_scd2_framing(self, gold_ontology_graph, template_dir,
                                         gold_bronze_dir, gold_mappings_dir):
        """SCD2 dimension gold model applies is_current = 1 framing."""
        artifacts = generate_dbt_artifacts(
            classes=GOLD_CLASSES,
            graph=gold_ontology_graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="sales",
            bronze_dir=gold_bronze_dir,
            mappings_dir=gold_mappings_dir,
        )
        dim_key = next(k for k in artifacts if "dim_customer.sql" in k)
        content = artifacts[dim_key]
        # SCD2 framing should be applied
        assert "is_current = 1" in content

    def test_gold_schema_yaml(self, gold_ontology_graph, template_dir,
                              gold_bronze_dir, gold_mappings_dir):
        """Gold schema YAML has correct structure with tests."""
        artifacts = generate_dbt_artifacts(
            classes=GOLD_CLASSES,
            graph=gold_ontology_graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="sales",
            bronze_dir=gold_bronze_dir,
            mappings_dir=gold_mappings_dir,
        )
        schema_key = "models/gold/sales/_sales__gold_models.yml"
        assert schema_key in artifacts
        content = yaml.safe_load(artifacts[schema_key])
        models = content["models"]
        # Should have multiple gold models
        assert len(models) >= 3
        # Check that PK SK columns have not_null + unique tests
        for model in models:
            # Only the first SK column (PK) should have tests — FK SK cols may be nullable
            pk_col = next(
                (c for c in model["columns"]
                 if c["name"].endswith("_sk") and c.get("tests")),
                None,
            )
            if pk_col:
                assert "not_null" in pk_col["tests"]
                assert "unique" in pk_col["tests"]

    def test_dbt_project_yml_has_gold(self, gold_ontology_graph, template_dir,
                                      gold_bronze_dir, gold_mappings_dir):
        """dbt_project.yml includes gold section."""
        artifacts = generate_dbt_artifacts(
            classes=GOLD_CLASSES,
            graph=gold_ontology_graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="sales",
            bronze_dir=gold_bronze_dir,
            mappings_dir=gold_mappings_dir,
        )
        proj = yaml.safe_load(artifacts["dbt_project.yml"])
        assert "gold" in proj["models"]["sales_project"]
        gold_config = proj["models"]["sales_project"]["gold"]
        assert "+materialized" in gold_config
        assert gold_config["+materialized"] == "table"

    def test_gold_dim_date_model(self, gold_ontology_graph, template_dir,
                                 gold_bronze_dir, gold_mappings_dir):
        """dim_date is auto-generated as a gold model."""
        artifacts = generate_dbt_artifacts(
            classes=GOLD_CLASSES,
            graph=gold_ontology_graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="sales",
            bronze_dir=gold_bronze_dir,
            mappings_dir=gold_mappings_dir,
        )
        date_key = next(k for k in artifacts if "dim_date.sql" in k)
        content = artifacts[date_key]
        assert "materialized='table'" in content
        assert "date_key" in content


# ---------------------------------------------------------------------------
# Cross-domain FK projection tests
# ---------------------------------------------------------------------------

# Ontology with a cross-domain FK: Client has representsParty → Party
CROSS_DOMAIN_ONTOLOGY_TTL = textwrap.dedent("""\
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
    @prefix ex:   <http://kairos.example/ontology/> .
    @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

    <http://kairos.example/ontology> a owl:Ontology ;
        rdfs:label "Test Ontology" ;
        owl:versionInfo "1.0.0" .

    ex:Party a owl:Class ;
        rdfs:label "Party" ;
        rdfs:comment "A party entity" ;
        kairos-ext:naturalKey "partyId" .

    ex:partyId a owl:DatatypeProperty ;
        rdfs:label "party ID" ;
        rdfs:comment "Party identifier" ;
        rdfs:domain ex:Party ;
        rdfs:range xsd:string .

    ex:Client a owl:Class ;
        rdfs:label "Client" ;
        rdfs:comment "A client entity" ;
        kairos-ext:naturalKey "clientId" .

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

    ex:representsParty a owl:ObjectProperty, owl:FunctionalProperty ;
        rdfs:label "represents party" ;
        rdfs:comment "FK to party entity" ;
        rdfs:domain ex:Client ;
        rdfs:range ex:Party .
""")

# Bronze vocab for the FK source column
CROSS_DOMAIN_BRONZE_TTL = textwrap.dedent("""\
    @prefix bronze-ap: <https://example.com/bronze/adminpulse#> .
    @prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .

    bronze-ap:AdminPulse a kairos-bronze:SourceSystem ;
        rdfs:label "AdminPulse" ;
        kairos-bronze:connectionType "jdbc" ;
        kairos-bronze:database "AP_Prod" ;
        kairos-bronze:schema "dbo" .

    bronze-ap:Relation a kairos-bronze:SourceTable ;
        rdfs:label "Relation" ;
        kairos-bronze:sourceSystem bronze-ap:AdminPulse ;
        kairos-bronze:tableName "Relation" ;
        kairos-bronze:primaryKeyColumns "id" .

    bronze-ap:Relation_id a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-ap:Relation ;
        kairos-bronze:columnName "id" ;
        kairos-bronze:dataType "int" ;
        kairos-bronze:nullable "false"^^xsd:boolean ;
        kairos-bronze:isPrimaryKey "true"^^xsd:boolean .

    bronze-ap:Relation_Name a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-ap:Relation ;
        kairos-bronze:columnName "Name" ;
        kairos-bronze:dataType "nvarchar(255)" ;
        kairos-bronze:nullable "true"^^xsd:boolean .
""")

# SKOS mapping that maps bronze table → Client and includes an FK mapping
CROSS_DOMAIN_MAPPING_TTL = textwrap.dedent("""\
    @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
    @prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
    @prefix bronze-ap: <https://example.com/bronze/adminpulse#> .
    @prefix ex: <http://kairos.example/ontology/> .

    bronze-ap:Relation skos:exactMatch ex:Client ;
        kairos-map:mappingType "direct" .

    bronze-ap:Relation_id skos:exactMatch ex:clientId ;
        kairos-map:transform "CAST(source.id AS STRING)" .

    bronze-ap:Relation_Name skos:exactMatch ex:clientName ;
        kairos-map:transform "source.Name" .

    bronze-ap:Relation_id skos:exactMatch ex:representsParty ;
        kairos-map:transform "source.id" ;
        rdfs:comment "FK to party — resolved via join" .
""")


class TestCrossDomainFK:
    """Tests for cross-domain FK column and join generation."""

    @pytest.fixture
    def cross_domain_graph(self):
        g = Graph()
        g.parse(data=CROSS_DOMAIN_ONTOLOGY_TTL, format="turtle")
        return g

    @pytest.fixture
    def cross_domain_bronze_dir(self, tmp_path):
        d = tmp_path / "sources" / "adminpulse"
        d.mkdir(parents=True)
        (d / "adminpulse.vocabulary.ttl").write_text(
            CROSS_DOMAIN_BRONZE_TTL, encoding="utf-8"
        )
        return tmp_path / "sources"

    @pytest.fixture
    def cross_domain_mappings_dir(self, tmp_path):
        d = tmp_path / "mappings" / "adminpulse"
        d.mkdir(parents=True)
        (d / "adminpulse-to-client.ttl").write_text(
            CROSS_DOMAIN_MAPPING_TTL, encoding="utf-8"
        )
        return tmp_path / "mappings"

    @pytest.fixture
    def cross_domain_classes(self):
        return [
            {
                "uri": "http://kairos.example/ontology/Client",
                "name": "Client",
                "label": "Client",
                "comment": "A client entity",
            },
            {
                "uri": "http://kairos.example/ontology/Party",
                "name": "Party",
                "label": "Party",
                "comment": "A party entity",
            },
        ]

    def test_fk_column_generated(
        self, cross_domain_classes, cross_domain_graph, template_dir,
        cross_domain_bronze_dir, cross_domain_mappings_dir,
    ):
        """Cross-domain FK generates a _sk column with a join."""
        artifacts = generate_dbt_artifacts(
            classes=cross_domain_classes,
            graph=cross_domain_graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="client",
            bronze_dir=cross_domain_bronze_dir,
            mappings_dir=cross_domain_mappings_dir,
        )
        # Find client silver model
        silver_key = next(
            k for k in artifacts
            if "client.sql" in k and "models/silver/" in k
        )
        content = artifacts[silver_key]

        # Should contain a party_sk FK column
        assert "party_sk" in content
        # Should contain a ref() join to the party model
        assert "ref('party')" in content
        # Should have a left join
        assert "left join" in content

    def test_fk_join_condition(
        self, cross_domain_classes, cross_domain_graph, template_dir,
        cross_domain_bronze_dir, cross_domain_mappings_dir,
    ):
        """FK join condition references the source column and target NK."""
        artifacts = generate_dbt_artifacts(
            classes=cross_domain_classes,
            graph=cross_domain_graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="client",
            bronze_dir=cross_domain_bronze_dir,
            mappings_dir=cross_domain_mappings_dir,
        )
        silver_key = next(
            k for k in artifacts
            if "client.sql" in k and "models/silver/" in k
        )
        content = artifacts[silver_key]

        # Join should reference the target natural key (party_id from naturalKey)
        assert "party_ref" in content
        assert "party_id" in content

    def test_fk_column_in_schema_yaml(
        self, cross_domain_classes, cross_domain_graph, template_dir,
        cross_domain_bronze_dir, cross_domain_mappings_dir,
    ):
        """FK column appears in the schema YAML with is_fk metadata."""
        artifacts = generate_dbt_artifacts(
            classes=cross_domain_classes,
            graph=cross_domain_graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="client",
            bronze_dir=cross_domain_bronze_dir,
            mappings_dir=cross_domain_mappings_dir,
        )
        schema_key = next(k for k in artifacts if "_models.yml" in k)
        schema = yaml.safe_load(artifacts[schema_key])
        # Find client model columns
        client_model = next(
            m for m in schema["models"] if m["name"] == "client"
        )
        col_names = [c["name"] for c in client_model["columns"]]
        assert "party_sk" in col_names
        fk_col = next(c for c in client_model["columns"] if c["name"] == "party_sk")
        assert fk_col["meta"]["is_fk"] == "true"
        assert fk_col["meta"]["references"] == "party"

    def test_fk_no_mapping_emits_null(self, cross_domain_graph, template_dir):
        """FK with no SKOS mapping emits NULL placeholder."""
        # Use the graph but empty mappings (no SKOS mapping for the FK)
        source_refs = [("adminpulse", "Relation", "https://example.com/bronze/adminpulse#Relation")]
        mappings = {"table_maps": {}, "column_maps": {}}

        fk_columns, joins, warnings = _extract_fk_columns_and_joins(
            cross_domain_graph,
            "http://kairos.example/ontology/Client",
            mappings,
            source_refs,
            systems=None,
        )

        # Should still produce a FK column (NULL placeholder)
        assert len(fk_columns) == 1
        assert fk_columns[0]["target_name"] == "party_sk"
        assert "NULL" in fk_columns[0]["expression"]
        # No joins since no mapping
        assert len(joins) == 0
        # Should have a warning with remediation guidance
        assert len(warnings) == 1
        assert "no mapping" in warnings[0].lower()
        assert "auto-inference" in warnings[0].lower() or "natural key" in warnings[0].lower()

    def test_fk_multi_source_skipped(self, cross_domain_graph):
        """FK joins are not generated for multi-source models."""
        source_refs = [
            ("sys1", "T1", "uri:t1"),
            ("sys2", "T2", "uri:t2"),
        ]
        mappings = {"table_maps": {}, "column_maps": {}}

        fk_columns, joins, warnings = _extract_fk_columns_and_joins(
            cross_domain_graph,
            "http://kairos.example/ontology/Client",
            mappings,
            source_refs,
            systems=None,
        )

        # Multi-source: no FK columns or joins generated
        assert len(fk_columns) == 0
        assert len(joins) == 0


# ---------------------------------------------------------------------------
# FK auto-inference via natural key matching
# ---------------------------------------------------------------------------

FK_AUTOINFER_ONTOLOGY_TTL = textwrap.dedent("""\
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
    @prefix ex:   <http://kairos.example/ontology/> .
    @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

    <http://kairos.example/ontology> a owl:Ontology ;
        rdfs:label "Test FK Inference" ;
        owl:versionInfo "1.0.0" .

    ex:Client a owl:Class ;
        rdfs:label "Client" ;
        rdfs:comment "A client entity" ;
        kairos-ext:naturalKey "clientId" .

    ex:clientId a owl:DatatypeProperty ;
        rdfs:domain ex:Client ;
        rdfs:range xsd:string .

    ex:clientName a owl:DatatypeProperty ;
        rdfs:domain ex:Client ;
        rdfs:range xsd:string .

    ex:ClientType a owl:Class ;
        rdfs:label "Client Type" ;
        rdfs:comment "Reference data for type classification" ;
        kairos-ext:naturalKey "typeCode" .

    ex:typeCode a owl:DatatypeProperty ;
        rdfs:domain ex:ClientType ;
        rdfs:range xsd:string .

    ex:typeLabel a owl:DatatypeProperty ;
        rdfs:domain ex:ClientType ;
        rdfs:range xsd:string .

    ex:hasType a owl:ObjectProperty, owl:FunctionalProperty ;
        rdfs:label "has type" ;
        rdfs:domain ex:Client ;
        rdfs:range ex:ClientType .
""")


class TestFKAutoInference:
    """Tests for FK auto-inference from natural key matching."""

    @pytest.fixture
    def autoinfer_graph(self):
        g = Graph()
        g.parse(data=FK_AUTOINFER_ONTOLOGY_TTL, format="turtle")
        return g

    @pytest.fixture
    def systems_with_fk_column(self):
        """Bronze systems with a TypeCode column on tblClient."""
        return [{
            "system_label": "AdminPulse",
            "tables": [{
                "uri": "https://example.com/bronze/adminpulse#tblClient",
                "name": "tblClient",
                "columns": [
                    {
                        "uri": "https://example.com/bronze/adminpulse#tblClient_ClientID",
                        "name": "ClientID",
                        "data_type": "int",
                    },
                    {
                        "uri": "https://example.com/bronze/adminpulse#tblClient_TypeCode",
                        "name": "TypeCode",
                        "data_type": "int",
                    },
                ],
            }],
        }]

    @pytest.fixture
    def mappings_with_nk_column(self):
        """Mappings where tblClient_TypeCode → typeCode (NK of ClientType)."""
        return {
            "table_maps": {
                "https://example.com/bronze/adminpulse#tblClient": [{
                    "target_uri": "http://kairos.example/ontology/Client",
                    "mapping_type": "direct",
                }],
            },
            "column_maps": {
                "https://example.com/bronze/adminpulse#tblClient_ClientID": [{
                    "target_uri": "http://kairos.example/ontology/clientId",
                    "transform": "CAST(source.ClientID AS STRING)",
                    "match_type": "exactMatch",
                }],
                "https://example.com/bronze/adminpulse#tblClient_TypeCode": [{
                    "target_uri": "http://kairos.example/ontology/typeCode",
                    "transform": "source.TypeCode",
                    "match_type": "exactMatch",
                }],
            },
        }

    def test_auto_infer_fk_from_nk(
        self, autoinfer_graph, systems_with_fk_column, mappings_with_nk_column
    ):
        """Auto-infer FK join when source column maps to NK of range class."""
        source_refs = [(
            "adminpulse", "tblClient",
            "https://example.com/bronze/adminpulse#tblClient",
        )]
        fk_columns, joins, warnings = _extract_fk_columns_and_joins(
            autoinfer_graph,
            "http://kairos.example/ontology/Client",
            mappings_with_nk_column,
            source_refs,
            systems=systems_with_fk_column,
        )

        # Should generate a proper FK join, not NULL
        assert len(fk_columns) == 1
        assert fk_columns[0]["target_name"] == "client_type_sk"
        assert "NULL" not in fk_columns[0]["expression"]
        assert "client_type_ref" in fk_columns[0]["expression"]

        # Should have a join
        assert len(joins) == 1
        assert "ref('client_type')" in joins[0]["ref"]
        assert "TypeCode" in joins[0]["condition"]
        assert "type_code" in joins[0]["condition"]

        # No warnings for auto-inferred FK
        assert len(warnings) == 0

    def test_auto_infer_ignores_other_tables(
        self, autoinfer_graph
    ):
        """Auto-inference only considers columns from the current source table."""
        # tblClientType has TypeCode, but it's a different table — should NOT
        # be used for auto-inference when building the Client model from tblClient
        systems = [{
            "system_label": "AdminPulse",
            "tables": [
                {
                    "uri": "https://example.com/bronze/adminpulse#tblClient",
                    "name": "tblClient",
                    "columns": [{
                        "uri": "https://example.com/bronze/adminpulse#tblClient_ClientID",
                        "name": "ClientID",
                        "data_type": "int",
                    }],
                },
                {
                    "uri": "https://example.com/bronze/adminpulse#tblClientType",
                    "name": "tblClientType",
                    "columns": [{
                        "uri": "https://example.com/bronze/adminpulse#tblClientType_TypeCode",
                        "name": "TypeCode",
                        "data_type": "int",
                    }],
                },
            ],
        }]
        # Mapping: tblClientType_TypeCode → typeCode (wrong table)
        mappings = {
            "table_maps": {},
            "column_maps": {
                "https://example.com/bronze/adminpulse#tblClientType_TypeCode": [{
                    "target_uri": "http://kairos.example/ontology/typeCode",
                    "transform": "source.TypeCode",
                    "match_type": "exactMatch",
                }],
            },
        }
        source_refs = [(
            "adminpulse", "tblClient",
            "https://example.com/bronze/adminpulse#tblClient",
        )]
        fk_columns, joins, warnings = _extract_fk_columns_and_joins(
            autoinfer_graph,
            "http://kairos.example/ontology/Client",
            mappings,
            source_refs,
            systems=systems,
        )

        # Should NOT infer — the TypeCode mapping is from tblClientType, not tblClient
        assert len(fk_columns) == 1
        assert "NULL" in fk_columns[0]["expression"]
        assert len(joins) == 0
        assert len(warnings) == 1

    def test_auto_infer_no_systems_emits_null(self, autoinfer_graph):
        """Auto-inference gracefully degrades to NULL when systems is None."""
        mappings = {
            "table_maps": {},
            "column_maps": {
                "https://example.com/bronze/adminpulse#tblClient_TypeCode": [{
                    "target_uri": "http://kairos.example/ontology/typeCode",
                    "transform": "source.TypeCode",
                    "match_type": "exactMatch",
                }],
            },
        }
        source_refs = [(
            "adminpulse", "tblClient",
            "https://example.com/bronze/adminpulse#tblClient",
        )]
        fk_columns, joins, warnings = _extract_fk_columns_and_joins(
            autoinfer_graph,
            "http://kairos.example/ontology/Client",
            mappings,
            source_refs,
            systems=None,
        )

        # Without systems we cannot scope columns → should emit NULL
        assert len(fk_columns) == 1
        assert "NULL" in fk_columns[0]["expression"]
        assert len(warnings) == 1

    def test_improved_warning_includes_remediation(self, autoinfer_graph):
        """Warning message includes actionable remediation guidance."""
        mappings = {"table_maps": {}, "column_maps": {}}
        source_refs = [(
            "adminpulse", "tblClient",
            "https://example.com/bronze/adminpulse#tblClient",
        )]
        fk_columns, joins, warnings = _extract_fk_columns_and_joins(
            autoinfer_graph,
            "http://kairos.example/ontology/Client",
            mappings,
            source_refs,
            systems=None,
        )

        assert len(warnings) == 1
        # Warning should include remediation guidance
        assert "natural key" in warnings[0].lower() or "mapping" in warnings[0].lower()
        assert "ClientType" in warnings[0] or "client_type" in warnings[0]


# ---------------------------------------------------------------------------
# Split pattern filter condition tests
# ---------------------------------------------------------------------------

SPLIT_ONTOLOGY_TTL = textwrap.dedent("""\
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
    @prefix ex:   <http://kairos.example/ontology/> .
    @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

    <http://kairos.example/ontology> a owl:Ontology ;
        rdfs:label "Test Ontology" ;
        owl:versionInfo "1.0.0" .

    ex:CorporateClient a owl:Class ;
        rdfs:label "Corporate Client" ;
        rdfs:comment "Corporate entity" ;
        kairos-ext:naturalKey "clientId" .

    ex:SoleProprietorClient a owl:Class ;
        rdfs:label "Sole Proprietor Client" ;
        rdfs:comment "Sole proprietor entity" ;
        kairos-ext:naturalKey "clientId" .

    ex:IndividualClient a owl:Class ;
        rdfs:label "Individual Client" ;
        rdfs:comment "Individual entity" ;
        kairos-ext:naturalKey "clientId" .

    ex:clientId a owl:DatatypeProperty ;
        rdfs:label "client ID" ;
        rdfs:comment "Unique identifier" ;
        rdfs:domain ex:CorporateClient ;
        rdfs:range xsd:string .
""")

SPLIT_BRONZE_TTL = textwrap.dedent("""\
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
        kairos-bronze:primaryKeyColumns "ClientID" .

    bronze-ap:tblClient_ClientID a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-ap:tblClient ;
        kairos-bronze:columnName "ClientID" ;
        kairos-bronze:dataType "int" ;
        kairos-bronze:nullable "false"^^xsd:boolean .

    bronze-ap:tblClient_type a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-ap:tblClient ;
        kairos-bronze:columnName "type" ;
        kairos-bronze:dataType "int" ;
        kairos-bronze:nullable "false"^^xsd:boolean .
""")

SPLIT_MAPPING_TTL = textwrap.dedent("""\
    @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
    @prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
    @prefix bronze-ap: <https://example.com/bronze/adminpulse#> .
    @prefix ex: <http://kairos.example/ontology/> .

    bronze-ap:tblClient skos:exactMatch ex:CorporateClient ;
        kairos-map:mappingType "split" ;
        kairos-map:filterCondition "source.type = 0" .

    bronze-ap:tblClient skos:exactMatch ex:SoleProprietorClient ;
        kairos-map:mappingType "split" ;
        kairos-map:filterCondition "source.type = 1" .

    bronze-ap:tblClient skos:exactMatch ex:IndividualClient ;
        kairos-map:mappingType "split" ;
        kairos-map:filterCondition "source.type = 2" .

    bronze-ap:tblClient_ClientID skos:exactMatch ex:clientId ;
        kairos-map:transform "CAST(source.ClientID AS STRING)" .
""")


class TestSplitFilterCondition:
    """Tests for split pattern where each target class has a different filter."""

    @pytest.fixture
    def split_graph(self):
        g = Graph()
        g.parse(data=SPLIT_ONTOLOGY_TTL, format="turtle")
        return g

    @pytest.fixture
    def split_bronze_dir(self, tmp_path):
        d = tmp_path / "sources" / "adminpulse"
        d.mkdir(parents=True)
        (d / "adminpulse.vocabulary.ttl").write_text(
            SPLIT_BRONZE_TTL, encoding="utf-8"
        )
        return tmp_path / "sources"

    @pytest.fixture
    def split_mappings_dir(self, tmp_path):
        d = tmp_path / "mappings" / "adminpulse"
        d.mkdir(parents=True)
        (d / "client-split.ttl").write_text(SPLIT_MAPPING_TTL, encoding="utf-8")
        return tmp_path / "mappings"

    @pytest.fixture
    def split_classes(self):
        return [
            {"uri": "http://kairos.example/ontology/CorporateClient",
             "name": "CorporateClient", "label": "Corporate Client",
             "comment": "Corporate entity"},
            {"uri": "http://kairos.example/ontology/SoleProprietorClient",
             "name": "SoleProprietorClient", "label": "Sole Proprietor Client",
             "comment": "Sole proprietor entity"},
            {"uri": "http://kairos.example/ontology/IndividualClient",
             "name": "IndividualClient", "label": "Individual Client",
             "comment": "Individual entity"},
        ]

    def test_each_split_model_has_correct_filter(
        self, split_classes, split_graph, template_dir,
        split_bronze_dir, split_mappings_dir,
    ):
        """Each split model must have its own discriminator filter, not the first."""
        artifacts = generate_dbt_artifacts(
            classes=split_classes,
            graph=split_graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="client",
            bronze_dir=split_bronze_dir,
            mappings_dir=split_mappings_dir,
        )

        # Corporate → type = 0
        corp_key = next(k for k in artifacts if "corporate_client.sql" in k)
        assert "type = 0" in artifacts[corp_key]

        # Sole proprietor → type = 1
        sole_key = next(k for k in artifacts if "sole_proprietor_client.sql" in k)
        assert "type = 1" in artifacts[sole_key]

        # Individual → type = 2
        indiv_key = next(k for k in artifacts if "individual_client.sql" in k)
        assert "type = 2" in artifacts[indiv_key]

    def test_split_models_do_not_share_filter(
        self, split_classes, split_graph, template_dir,
        split_bronze_dir, split_mappings_dir,
    ):
        """No split model should contain another model's filter condition."""
        artifacts = generate_dbt_artifacts(
            classes=split_classes,
            graph=split_graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="client",
            bronze_dir=split_bronze_dir,
            mappings_dir=split_mappings_dir,
        )

        sole_key = next(k for k in artifacts if "sole_proprietor_client.sql" in k)
        content = artifacts[sole_key]
        # Should NOT have type = 0 (that's CorporateClient's filter)
        assert "type = 0" not in content
        # Should have type = 1
        assert "type = 1" in content


# ---------------------------------------------------------------------------
# Natural-key warning tests
# ---------------------------------------------------------------------------

NK_ONTOLOGY_WITH_KEY_TTL = textwrap.dedent("""\
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
    @prefix ex:   <http://kairos.example/ontology/> .
    @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

    <http://kairos.example/ontology> a owl:Ontology ;
        rdfs:label "NK Test Ontology" ;
        owl:versionInfo "1.0.0" .

    ex:Account a owl:Class ;
        rdfs:label "Account" ;
        rdfs:comment "An account entity" ;
        kairos-ext:naturalKey "accountCode" .

    ex:accountCode a owl:DatatypeProperty ;
        rdfs:label "account code" ;
        rdfs:domain ex:Account ;
        rdfs:range xsd:string .
""")

NK_ONTOLOGY_WITHOUT_KEY_TTL = textwrap.dedent("""\
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
    @prefix ex:   <http://kairos.example/ontology/> .

    <http://kairos.example/ontology> a owl:Ontology ;
        rdfs:label "NK Test Ontology" ;
        owl:versionInfo "1.0.0" .

    ex:Widget a owl:Class ;
        rdfs:label "Widget" ;
        rdfs:comment "A widget entity" .

    ex:widgetCode a owl:DatatypeProperty ;
        rdfs:label "widget code" ;
        rdfs:domain ex:Widget ;
        rdfs:range xsd:string .
""")

NK_BRONZE_TTL = textwrap.dedent("""\
    @prefix bronze-ap: <https://example.com/bronze/adminpulse#> .
    @prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

    bronze-ap:AdminPulse a kairos-bronze:SourceSystem ;
        rdfs:label "AdminPulse" ;
        kairos-bronze:connectionType "jdbc" ;
        kairos-bronze:database "AP_Prod" ;
        kairos-bronze:schema "dbo" .

    bronze-ap:tblAccount a kairos-bronze:SourceTable ;
        rdfs:label "tblAccount" ;
        kairos-bronze:sourceSystem bronze-ap:AdminPulse ;
        kairos-bronze:tableName "tblAccount" ;
        kairos-bronze:primaryKeyColumns "Code" .

    bronze-ap:tblAccount_Code a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-ap:tblAccount ;
        kairos-bronze:columnName "Code" ;
        kairos-bronze:dataType "nvarchar" ;
        kairos-bronze:nullable "false"^^xsd:boolean ;
        kairos-bronze:isPrimaryKey "true"^^xsd:boolean .

    bronze-ap:tblWidget a kairos-bronze:SourceTable ;
        rdfs:label "tblWidget" ;
        kairos-bronze:sourceSystem bronze-ap:AdminPulse ;
        kairos-bronze:tableName "tblWidget" ;
        kairos-bronze:primaryKeyColumns "Code" .

    bronze-ap:tblWidget_Code a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-ap:tblWidget ;
        kairos-bronze:columnName "Code" ;
        kairos-bronze:dataType "nvarchar" ;
        kairos-bronze:nullable "false"^^xsd:boolean ;
        kairos-bronze:isPrimaryKey "true"^^xsd:boolean .
""")

NK_MAPPING_ACCOUNT_TTL = textwrap.dedent("""\
    @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
    @prefix bronze-ap: <https://example.com/bronze/adminpulse#> .
    @prefix ex: <http://kairos.example/ontology/> .
    @prefix kairos-map: <https://kairos.cnext.eu/mapping#> .

    bronze-ap:tblAccount skos:exactMatch ex:Account ;
        kairos-map:mappingType "direct" .

    bronze-ap:tblAccount_Code skos:exactMatch ex:accountCode ;
        kairos-map:transform "source.Code" .
""")

NK_MAPPING_WIDGET_TTL = textwrap.dedent("""\
    @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
    @prefix bronze-ap: <https://example.com/bronze/adminpulse#> .
    @prefix ex: <http://kairos.example/ontology/> .
    @prefix kairos-map: <https://kairos.cnext.eu/mapping#> .

    bronze-ap:tblWidget skos:exactMatch ex:Widget ;
        kairos-map:mappingType "direct" .

    bronze-ap:tblWidget_Code skos:exactMatch ex:widgetCode ;
        kairos-map:transform "source.Code" .
""")


class TestNaturalKeyWarning:
    """Tests that missing kairos-ext:naturalKey emits a warning."""

    @pytest.fixture
    def nk_sources_dir(self, tmp_path):
        d = tmp_path / "sources" / "adminpulse"
        d.mkdir(parents=True)
        (d / "adminpulse.vocabulary.ttl").write_text(
            NK_BRONZE_TTL, encoding="utf-8"
        )
        return tmp_path / "sources"

    @pytest.fixture
    def nk_mappings_account(self, tmp_path):
        d = tmp_path / "mappings"
        d.mkdir(parents=True)
        (d / "account.ttl").write_text(NK_MAPPING_ACCOUNT_TTL, encoding="utf-8")
        return d

    @pytest.fixture
    def nk_mappings_widget(self, tmp_path):
        d = tmp_path / "mappings"
        d.mkdir(parents=True)
        (d / "widget.ttl").write_text(NK_MAPPING_WIDGET_TTL, encoding="utf-8")
        return d

    def test_no_warning_when_natural_key_present(
        self, template_dir, nk_sources_dir, nk_mappings_account, caplog,
    ):
        """Class WITH naturalKey annotation should NOT produce a warning."""
        g = Graph()
        g.parse(data=NK_ONTOLOGY_WITH_KEY_TTL, format="turtle")
        classes = [{"uri": "http://kairos.example/ontology/Account",
                     "name": "Account", "label": "Account",
                     "comment": "An account entity"}]

        with caplog.at_level(logging.WARNING, logger="kairos_ontology.projections.medallion_dbt_projector"):
            generate_dbt_artifacts(
                classes=classes,
                graph=g,
                template_dir=template_dir,
                namespace="http://kairos.example/ontology/",
                ontology_name="account",
                sources_dir=nk_sources_dir,
                mappings_dir=nk_mappings_account,
            )
        assert "no kairos-ext:naturalKey" not in caplog.text

    def test_warning_when_natural_key_missing(
        self, template_dir, nk_sources_dir, nk_mappings_widget, caplog,
    ):
        """Class WITHOUT naturalKey annotation should produce a warning."""
        g = Graph()
        g.parse(data=NK_ONTOLOGY_WITHOUT_KEY_TTL, format="turtle")
        classes = [{"uri": "http://kairos.example/ontology/Widget",
                     "name": "Widget", "label": "Widget",
                     "comment": "A widget entity"}]

        with caplog.at_level(logging.WARNING, logger="kairos_ontology.projections.medallion_dbt_projector"):
            generate_dbt_artifacts(
                classes=classes,
                graph=g,
                template_dir=template_dir,
                namespace="http://kairos.example/ontology/",
                ontology_name="widget",
                sources_dir=nk_sources_dir,
                mappings_dir=nk_mappings_widget,
            )
        assert "no kairos-ext:naturalKey" in caplog.text
        assert "Widget" in caplog.text

    def test_warning_includes_remediation_guidance(
        self, template_dir, nk_sources_dir, nk_mappings_widget, caplog,
    ):
        """Warning message should include actionable remediation guidance."""
        g = Graph()
        g.parse(data=NK_ONTOLOGY_WITHOUT_KEY_TTL, format="turtle")
        classes = [{"uri": "http://kairos.example/ontology/Widget",
                     "name": "Widget", "label": "Widget",
                     "comment": "A widget entity"}]

        with caplog.at_level(logging.WARNING, logger="kairos_ontology.projections.medallion_dbt_projector"):
            generate_dbt_artifacts(
                classes=classes,
                graph=g,
                template_dir=template_dir,
                namespace="http://kairos.example/ontology/",
                ontology_name="widget",
                sources_dir=nk_sources_dir,
                mappings_dir=nk_mappings_widget,
            )
        # Warning should guide user to the correct design skill
        assert "kairos-design-silver" in caplog.text


# ---------------------------------------------------------------------------
# DD-022: silverForeignKey annotation tests for dbt projector
# ---------------------------------------------------------------------------

SILVER_FK_ANNOTATION_TTL = textwrap.dedent("""\
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
    @prefix ex:   <http://kairos.example/ontology/> .
    @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

    <http://kairos.example/ontology> a owl:Ontology ;
        rdfs:label "Test Ontology" ;
        owl:versionInfo "1.0.0" .

    ex:Customer a owl:Class ;
        rdfs:label "Customer" ;
        rdfs:comment "A customer" ;
        kairos-ext:naturalKey "customerId" .

    ex:customerId a owl:DatatypeProperty ;
        rdfs:label "customer ID" ;
        rdfs:domain ex:Customer ;
        rdfs:range xsd:string .

    ex:Order a owl:Class ;
        rdfs:label "Order" ;
        rdfs:comment "An order" ;
        kairos-ext:naturalKey "orderId" .

    ex:orderId a owl:DatatypeProperty ;
        rdfs:label "order ID" ;
        rdfs:domain ex:Order ;
        rdfs:range xsd:string .

    ex:placedBy a owl:ObjectProperty ;
        rdfs:label "placed by" ;
        rdfs:domain ex:Order ;
        rdfs:range ex:Customer ;
        kairos-ext:silverForeignKey "true"^^xsd:boolean .
""")

SILVER_FK_ANNOTATION_BRONZE_TTL = textwrap.dedent("""\
    @prefix bronze: <https://example.com/bronze/erp#> .
    @prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .

    bronze:ERP a kairos-bronze:SourceSystem ;
        rdfs:label "ERP" ;
        kairos-bronze:database "ERP_Prod" ;
        kairos-bronze:schema "dbo" .

    bronze:Orders a kairos-bronze:SourceTable ;
        rdfs:label "Orders" ;
        kairos-bronze:sourceSystem bronze:ERP ;
        kairos-bronze:tableName "Orders" ;
        kairos-bronze:primaryKeyColumns "order_id" .

    bronze:Orders_order_id a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze:Orders ;
        kairos-bronze:columnName "order_id" ;
        kairos-bronze:dataType "int" .

    bronze:Orders_customer_id a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze:Orders ;
        kairos-bronze:columnName "customer_id" ;
        kairos-bronze:dataType "int" .
""")

SILVER_FK_ANNOTATION_MAPPING_TTL = textwrap.dedent("""\
    @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
    @prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
    @prefix bronze: <https://example.com/bronze/erp#> .
    @prefix ex: <http://kairos.example/ontology/> .

    bronze:Orders skos:exactMatch ex:Order ;
        kairos-map:mappingType "direct" .

    bronze:Orders_order_id skos:exactMatch ex:orderId .
    bronze:Orders_customer_id skos:exactMatch ex:placedBy .
""")


class TestSilverForeignKeyAnnotation:
    """DD-022: silverForeignKey true should qualify a property as FK in dbt projector."""

    @pytest.fixture
    def fk_graph(self):
        g = Graph()
        g.parse(data=SILVER_FK_ANNOTATION_TTL, format="turtle")
        return g

    @pytest.fixture
    def fk_sources_dir(self, tmp_path):
        d = tmp_path / "sources" / "erp"
        d.mkdir(parents=True)
        (d / "erp.vocabulary.ttl").write_text(
            SILVER_FK_ANNOTATION_BRONZE_TTL, encoding="utf-8"
        )
        return tmp_path / "sources"

    @pytest.fixture
    def fk_mappings_dir(self, tmp_path):
        d = tmp_path / "mappings" / "erp"
        d.mkdir(parents=True)
        (d / "erp-to-order.ttl").write_text(
            SILVER_FK_ANNOTATION_MAPPING_TTL, encoding="utf-8"
        )
        return tmp_path / "mappings"

    def test_silver_fk_annotation_generates_join(
        self, fk_graph, fk_sources_dir, fk_mappings_dir, template_dir,
    ):
        """silverForeignKey true must produce FK join even without FunctionalProperty."""
        classes = [
            {"uri": "http://kairos.example/ontology/Order",
             "name": "Order", "label": "Order", "comment": "An order"},
            {"uri": "http://kairos.example/ontology/Customer",
             "name": "Customer", "label": "Customer", "comment": "A customer"},
        ]
        artifacts = generate_dbt_artifacts(
            classes=classes,
            graph=fk_graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="sales",
            sources_dir=fk_sources_dir,
            mappings_dir=fk_mappings_dir,
        )
        silver_key = next(
            (k for k in artifacts if "order.sql" in k and "models/silver/" in k),
            None,
        )
        assert silver_key is not None, "order.sql not generated"
        content = artifacts[silver_key]
        assert "customer_sk" in content, (
            "silverForeignKey true should generate customer_sk FK column"
        )
        assert "ref('customer')" in content, (
            "silverForeignKey true should generate a join to customer model"
        )


# ---------------------------------------------------------------------------
# Silver model registry tests (DD-027)
# ---------------------------------------------------------------------------


class TestSilverModelRegistry:
    """Tests for _build_silver_model_registry and registry-aware resolution."""

    def test_registry_maps_class_uri_to_model_name(self):
        """Registry maps class URIs from entity metadata to snake_case model names."""
        g = Graph()
        meta = [
            {"class_name": "TransportOrder", "class_uri": "http://ex.com/TransportOrder",
             "skipped": False, "column_names": ["order_name", "status"]},
            {"class_name": "Customer", "class_uri": "http://ex.com/Customer",
             "skipped": False, "column_names": ["customer_name"]},
        ]
        classes = [
            {"uri": "http://ex.com/TransportOrder", "name": "TransportOrder",
             "label": "TO", "comment": ""},
            {"uri": "http://ex.com/Customer", "name": "Customer",
             "label": "C", "comment": ""},
        ]
        name_reg, cols_reg = _build_silver_model_registry(meta, classes, g)
        assert name_reg["http://ex.com/TransportOrder"] == "transport_order"
        assert name_reg["http://ex.com/Customer"] == "customer"
        assert cols_reg["transport_order"] == {"order_name", "status"}
        assert cols_reg["customer"] == {"customer_name"}

    def test_registry_maps_parent_uri_to_child(self):
        """Parent class URI maps to child's model when single child extends it."""
        g = Graph()
        parent_uri = URIRef("http://refmodel.org/PurchaseOrder")
        child_uri = URIRef("http://ex.com/HubOrder")
        g.add((child_uri, RDFS.subClassOf, parent_uri))

        meta = [
            {"class_name": "HubOrder", "class_uri": str(child_uri),
             "skipped": False, "column_names": ["order_id"]},
        ]
        classes = [
            {"uri": str(child_uri), "name": "HubOrder", "label": "HO", "comment": ""},
        ]
        name_reg, _ = _build_silver_model_registry(meta, classes, g)
        # Parent resolves to child's model name
        assert name_reg[str(parent_uri)] == "hub_order"

    def test_registry_skips_ambiguous_parent(self):
        """Parent with multiple children is NOT registered (ambiguous)."""
        g = Graph()
        parent_uri = URIRef("http://refmodel.org/Party")
        child1_uri = URIRef("http://ex.com/Customer")
        child2_uri = URIRef("http://ex.com/Supplier")
        g.add((child1_uri, RDFS.subClassOf, parent_uri))
        g.add((child2_uri, RDFS.subClassOf, parent_uri))

        meta = [
            {"class_name": "Customer", "class_uri": str(child1_uri),
             "skipped": False, "column_names": []},
            {"class_name": "Supplier", "class_uri": str(child2_uri),
             "skipped": False, "column_names": []},
        ]
        classes = [
            {"uri": str(child1_uri), "name": "Customer", "label": "", "comment": ""},
            {"uri": str(child2_uri), "name": "Supplier", "label": "", "comment": ""},
        ]
        name_reg, _ = _build_silver_model_registry(meta, classes, g)
        # Parent should NOT be in registry (ambiguous)
        assert str(parent_uri) not in name_reg

    def test_registry_skips_skipped_classes(self):
        """Skipped classes (no mapping) are not registered."""
        g = Graph()
        meta = [
            {"class_name": "NoMapping", "class_uri": "http://ex.com/NoMapping",
             "skipped": True, "column_names": []},
        ]
        classes = [{"uri": "http://ex.com/NoMapping", "name": "NoMapping",
                    "label": "", "comment": ""}]
        name_reg, _ = _build_silver_model_registry(meta, classes, g)
        assert "http://ex.com/NoMapping" not in name_reg

    def test_resolver_uses_registry_first(self):
        """_silver_model_name_for_class uses registry over classes list."""
        registry = {"http://refmodel.org/ImportedClass": "hub_entity"}
        classes = [
            {"uri": "http://refmodel.org/ImportedClass",
             "name": "ImportedClass", "label": "", "comment": ""},
        ]
        # Without registry, would return "imported_class"
        result = _silver_model_name_for_class(
            "http://refmodel.org/ImportedClass", classes, registry=registry)
        assert result == "hub_entity"

    def test_resolver_falls_back_without_registry(self):
        """Without registry, resolver uses classes list as before."""
        classes = [
            {"uri": "http://ex.com/Order", "name": "Order", "label": "", "comment": ""},
        ]
        result = _silver_model_name_for_class("http://ex.com/Order", classes)
        assert result == "order"

    def test_resolver_returns_none_when_not_in_registry(self):
        """When registry is present but URI not in it, returns None."""
        result = _silver_model_name_for_class(
            "http://unknown.org/ont#SomeClass", [], registry={})
        assert result is None


# ---------------------------------------------------------------------------
# Natural Key Inheritance (discriminator hierarchy)
# ---------------------------------------------------------------------------

NK_DISCRIMINATOR_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.com/ont#> .
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

ex:Client a owl:Class ;
    rdfs:label "Client" ;
    kairos-ext:naturalKey "clientId" ;
    kairos-ext:inheritanceStrategy "discriminator" .

ex:CorporateClient a owl:Class ;
    rdfs:subClassOf ex:Client ;
    rdfs:label "Corporate Client" .

ex:SoleProprietorClient a owl:Class ;
    rdfs:subClassOf ex:Client ;
    rdfs:label "Sole Proprietor Client" .

ex:clientId a owl:DatatypeProperty ;
    rdfs:domain ex:Client ;
    rdfs:label "clientId" .
"""

NK_CLASS_PER_TABLE_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.com/ont#> .
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

ex:Asset a owl:Class ;
    rdfs:label "Asset" ;
    kairos-ext:naturalKey "assetCode" ;
    kairos-ext:inheritanceStrategy "class-per-table" .

ex:Vehicle a owl:Class ;
    rdfs:subClassOf ex:Asset ;
    rdfs:label "Vehicle" .
"""

NK_MULTILEVEL_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.com/ont#> .
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

ex:Party a owl:Class ;
    rdfs:label "Party" ;
    kairos-ext:naturalKey "partyId" ;
    kairos-ext:inheritanceStrategy "discriminator" .

ex:LegalEntity a owl:Class ;
    rdfs:subClassOf ex:Party ;
    rdfs:label "Legal Entity" ;
    kairos-ext:inheritanceStrategy "discriminator" .

ex:Corporation a owl:Class ;
    rdfs:subClassOf ex:LegalEntity ;
    rdfs:label "Corporation" .
"""

NK_SUBCLASS_OVERRIDE_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.com/ont#> .
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

ex:Account a owl:Class ;
    rdfs:label "Account" ;
    kairos-ext:naturalKey "accountId" ;
    kairos-ext:inheritanceStrategy "discriminator" .

ex:SavingsAccount a owl:Class ;
    rdfs:subClassOf ex:Account ;
    rdfs:label "Savings Account" ;
    kairos-ext:naturalKey "savingsAccountNumber" .
"""


class TestNaturalKeyInheritance:
    """Test _get_natural_key walks up discriminator hierarchies."""

    def test_inherits_from_discriminator_parent(self):
        """Subclass inherits naturalKey when parent uses discriminator strategy."""
        g = Graph()
        g.parse(data=NK_DISCRIMINATOR_TTL, format="turtle")
        result = _get_natural_key(g, "http://example.com/ont#CorporateClient")
        assert result == ["client_id"]

    def test_does_not_inherit_from_class_per_table_parent(self):
        """Subclass does NOT inherit when parent uses class-per-table strategy."""
        g = Graph()
        g.parse(data=NK_CLASS_PER_TABLE_TTL, format="turtle")
        result = _get_natural_key(g, "http://example.com/ont#Vehicle")
        assert result == []

    def test_direct_annotation_wins(self):
        """Direct annotation on subclass takes precedence over parent."""
        g = Graph()
        g.parse(data=NK_SUBCLASS_OVERRIDE_TTL, format="turtle")
        result = _get_natural_key(g, "http://example.com/ont#SavingsAccount")
        assert result == ["savings_account_number"]

    def test_multilevel_hierarchy(self):
        """Multi-level discriminator hierarchy: grandchild inherits from grandparent."""
        g = Graph()
        g.parse(data=NK_MULTILEVEL_TTL, format="turtle")
        result = _get_natural_key(g, "http://example.com/ont#Corporation")
        # Corporation → LegalEntity (discriminator, no NK) → Party (discriminator, has NK)
        assert result == ["party_id"]

    def test_no_key_anywhere_returns_empty(self):
        """Class with no NK in hierarchy returns empty list."""
        g = Graph()
        g.parse(data="""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.com/ont#> .
ex:Orphan a owl:Class ; rdfs:label "Orphan" .
""", format="turtle")
        result = _get_natural_key(g, "http://example.com/ont#Orphan")
        assert result == []

    def test_cyclic_subclass_does_not_loop(self):
        """Cyclic rdfs:subClassOf doesn't cause infinite recursion."""
        g = Graph()
        g.parse(data="""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.com/ont#> .
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
ex:A a owl:Class ; rdfs:subClassOf ex:B ; rdfs:label "A" .
ex:B a owl:Class ; rdfs:subClassOf ex:A ;
    kairos-ext:inheritanceStrategy "discriminator" ; rdfs:label "B" .
""", format="turtle")
        # Should not raise RecursionError; returns [] since no NK declared
        result = _get_natural_key(g, "http://example.com/ont#A")
        assert result == []


class TestRawNaturalKeyInheritance:
    """Test _get_raw_natural_key returns the raw camelCase value."""

    def test_returns_raw_value_from_parent(self):
        """Returns the raw camelCase string when inherited from parent."""
        g = Graph()
        g.parse(data=NK_DISCRIMINATOR_TTL, format="turtle")
        result = _get_raw_natural_key(g, "http://example.com/ont#CorporateClient")
        assert result == "clientId"

    def test_returns_none_for_class_per_table(self):
        """Returns None when parent uses class-per-table."""
        g = Graph()
        g.parse(data=NK_CLASS_PER_TABLE_TTL, format="turtle")
        result = _get_raw_natural_key(g, "http://example.com/ont#Vehicle")
        assert result is None


class TestNKPropertyURIsInheritance:
    """Test _get_nk_property_uris handles inherited naturalKey."""

    def test_resolves_property_uri_from_inherited_nk(self):
        """NK inherited from parent resolves to correct property URI."""
        g = Graph()
        g.parse(data=NK_DISCRIMINATOR_TTL, format="turtle")
        result = _get_nk_property_uris(g, "http://example.com/ont#CorporateClient")
        assert result == ["http://example.com/ont#clientId"]

    def test_returns_empty_for_class_per_table(self):
        """No NK inheritance for class-per-table → empty result."""
        g = Graph()
        g.parse(data=NK_CLASS_PER_TABLE_TTL, format="turtle")
        result = _get_nk_property_uris(g, "http://example.com/ont#Vehicle")
        assert result == []
