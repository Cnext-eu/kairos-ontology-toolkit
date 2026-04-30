# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the dbt projector — bronze parsing, SKOS mappings, and artifact generation."""

import textwrap
from pathlib import Path

import pytest
import yaml
from rdflib import Graph

from kairos_ontology.projections.medallion_dbt_projector import (
    _camel_to_snake,
    _parse_bronze,
    _parse_skos_mappings,
    _extract_shacl_tests,
    _source_type_to_databricks,
    _extract_fk_columns_and_joins,
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


@pytest.fixture
def gold_ontology_graph():
    g = Graph()
    g.parse(data=GOLD_ONTOLOGY_TTL, format="turtle")
    return g


class TestGoldDbtModels:
    """Tests for gold dbt model generation (thick gold — DirectLake optimized)."""

    def test_gold_models_generated(self, gold_ontology_graph, template_dir, bronze_dir,
                                   mappings_dir):
        """Gold models are generated alongside silver when bronze sources exist."""
        artifacts = generate_dbt_artifacts(
            classes=GOLD_CLASSES,
            graph=gold_ontology_graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="sales",
            bronze_dir=bronze_dir,
            mappings_dir=mappings_dir,
        )
        gold_models = [k for k in artifacts if k.startswith("models/gold/")]
        assert len(gold_models) >= 3  # at least dim_date, dim_customer, fact_order
        # Check specific gold model paths
        assert any("dim_customer.sql" in k for k in gold_models)
        assert any("fact_order.sql" in k for k in gold_models)
        assert any("dim_date.sql" in k for k in gold_models)

    def test_gold_model_refs_silver(self, gold_ontology_graph, template_dir, bronze_dir,
                                    mappings_dir):
        """Gold models use ref() to reference silver models."""
        artifacts = generate_dbt_artifacts(
            classes=GOLD_CLASSES,
            graph=gold_ontology_graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="sales",
            bronze_dir=bronze_dir,
            mappings_dir=mappings_dir,
        )
        dim_key = next(k for k in artifacts if "dim_customer.sql" in k)
        content = artifacts[dim_key]
        assert "ref('customer')" in content
        assert "materialized='table'" in content

    def test_gold_fact_model_content(self, gold_ontology_graph, template_dir, bronze_dir,
                                     mappings_dir):
        """Fact table gold model has correct structure."""
        artifacts = generate_dbt_artifacts(
            classes=GOLD_CLASSES,
            graph=gold_ontology_graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="sales",
            bronze_dir=bronze_dir,
            mappings_dir=mappings_dir,
        )
        fact_key = next(k for k in artifacts if "fact_order.sql" in k)
        content = artifacts[fact_key]
        assert "materialized='table'" in content
        assert "gold_sales" in content
        # Fact table should reference silver model
        assert "ref(" in content
        # Should mention it's a fact table
        assert "Fact table" in content

    def test_gold_dimension_scd2_framing(self, gold_ontology_graph, template_dir, bronze_dir,
                                         mappings_dir):
        """SCD2 dimension gold model applies is_current = 1 framing."""
        artifacts = generate_dbt_artifacts(
            classes=GOLD_CLASSES,
            graph=gold_ontology_graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="sales",
            bronze_dir=bronze_dir,
            mappings_dir=mappings_dir,
        )
        dim_key = next(k for k in artifacts if "dim_customer.sql" in k)
        content = artifacts[dim_key]
        # SCD2 framing should be applied
        assert "is_current = 1" in content

    def test_gold_schema_yaml(self, gold_ontology_graph, template_dir, bronze_dir,
                              mappings_dir):
        """Gold schema YAML has correct structure with tests."""
        artifacts = generate_dbt_artifacts(
            classes=GOLD_CLASSES,
            graph=gold_ontology_graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="sales",
            bronze_dir=bronze_dir,
            mappings_dir=mappings_dir,
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

    def test_dbt_project_yml_has_gold(self, gold_ontology_graph, template_dir, bronze_dir,
                                      mappings_dir):
        """dbt_project.yml includes gold section."""
        artifacts = generate_dbt_artifacts(
            classes=GOLD_CLASSES,
            graph=gold_ontology_graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="sales",
            bronze_dir=bronze_dir,
            mappings_dir=mappings_dir,
        )
        proj = yaml.safe_load(artifacts["dbt_project.yml"])
        assert "gold" in proj["models"]["sales_project"]
        gold_config = proj["models"]["sales_project"]["gold"]
        assert "+materialized" in gold_config
        assert gold_config["+materialized"] == "table"

    def test_gold_dim_date_model(self, gold_ontology_graph, template_dir, bronze_dir,
                                 mappings_dir):
        """dim_date is auto-generated as a gold model."""
        artifacts = generate_dbt_artifacts(
            classes=GOLD_CLASSES,
            graph=gold_ontology_graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="sales",
            bronze_dir=bronze_dir,
            mappings_dir=mappings_dir,
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
        # Should have a warning
        assert len(warnings) == 1
        assert "no skos mapping" in warnings[0].lower()

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
