# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the dbt projector — bronze parsing, SKOS mappings, and artifact generation."""

import logging
import textwrap
from pathlib import Path

import pytest
import yaml
from rdflib import Graph, Literal, URIRef

from kairos_ontology.core.projections.dbt.builders import (
    build_silver_registry,
    outcome_from_context,
)
from kairos_ontology.core.projections.medallion_dbt_projector import (
    _build_sk_iri_columns,
    _camel_to_snake,
    _parse_bronze,
    _parse_skos_mappings,
    _extract_shacl_tests,
    _silver_model_name_for_class,
    _source_record_key_expression,
    _source_type_to_databricks,
    _source_type_to_target,
    _xsd_to_target,
    _extract_fk_columns_and_joins,
    _build_merge_superset,
    _merge_pad_type,
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

    bronze-ap:tblClient_ModifiedDate a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-ap:tblClient ;
        kairos-bronze:columnName "ModifiedDate" ;
        kairos-bronze:dataType "datetime" ;
        kairos-bronze:nullable "false"^^xsd:boolean .
""")

SKOS_MAPPING_TTL = textwrap.dedent("""\
    @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
    @prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
    @prefix map: <https://example.com/mapping/adminpulse#> .
    @prefix bronze-ap: <https://example.com/bronze/adminpulse#> .
    @prefix party: <http://kairos.example/ontology/> .

    bronze-ap:tblClient skos:exactMatch party:Client .
    map:client a kairos-map:TableMapping ;
        kairos-map:sourceTable bronze-ap:tblClient ;
        kairos-map:targetClass party:Client ;
        kairos-map:mappingType "direct" ;
        kairos-map:matchType "exactMatch" .

    bronze-ap:tblClient_ClientID skos:exactMatch party:clientId .
    map:clientId a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze-ap:tblClient_ClientID ;
        kairos-map:targetProperty party:clientId ;
        kairos-map:matchType "exactMatch" .

    bronze-ap:tblClient_Name skos:closeMatch party:clientName .
    map:clientName a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze-ap:tblClient_Name ;
        kairos-map:targetProperty party:clientName ;
        kairos-map:matchType "closeMatch" .
""")

ONTOLOGY_TTL = textwrap.dedent("""\
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
    @prefix ex:   <http://kairos.example/ontology/> .
    @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

    <http://kairos.example/ontology> a owl:Ontology ;
        rdfs:label "Test Ontology" ;
        owl:versionInfo "1.0.0" .

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
    return [
        {
            "uri": "http://kairos.example/ontology/Client",
            "name": "Client",
            "label": "Client",
            "comment": "A client entity",
        }
    ]


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

    def test_source_type_to_fabric_datetime_has_precision(self):
        # Regression: Fabric SQL rejects bare DATETIME2 — must include precision (error 24597)
        assert _source_type_to_target("datetime", "fabric") == "DATETIME2(6)"
        assert _source_type_to_target("datetime2", "fabric") == "DATETIME2(6)"
        assert _source_type_to_target("datetime2(7)", "fabric") == "DATETIME2(6)"

    def test_xsd_datetime_to_fabric_has_precision(self):
        # Regression: xsd:dateTime must map to DATETIME2(6) for Fabric, not bare DATETIME2
        from rdflib.namespace import XSD

        assert _xsd_to_target(XSD.dateTime, "fabric") == "DATETIME2(6)"


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
        assert len(cols) == 4
        col_names = {c["name"] for c in cols}
        assert col_names == {"ClientID", "Name", "IsActive", "ModifiedDate"}

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

    def test_source_record_key_uses_declared_bronze_primary_key(self, bronze_dir):
        systems = _parse_bronze(bronze_dir)
        expression, generated_after_mapping = _source_record_key_expression(
            systems,
            ("adminpulse", "tbl_client", systems[0]["tables"][0]["uri"]),
            "src",
            "fabric",
        )
        assert expression == (
            "{{ dbt_utils.generate_surrogate_key([\"'tblClient'\", 'src.ClientID']) }}"
        )
        assert generated_after_mapping is False

    def test_source_record_key_rejects_missing_primary_key(self):
        systems = [
            {
                "tables": [
                    {
                        "uri": "https://example.org/bronze#rows",
                        "pk_columns": [],
                        "columns": [{"name": "value", "is_pk": False}],
                    }
                ]
            }
        ]
        with pytest.raises(
            ValueError,
            match="identity.source-record-key-missing.*DD-108-source-identity",
        ):
            _source_record_key_expression(
                systems,
                ("source", "rows", "https://example.org/bronze#rows"),
                "src",
                "fabric",
            )


# ---------------------------------------------------------------------------
# Unit tests: SKOS mapping parsing
# ---------------------------------------------------------------------------


class TestSkosMapping:
    def test_parse_skos_table_maps(self, mappings_dir):
        maps, _ = _parse_skos_mappings(mappings_dir)
        table_maps = maps["table_maps"]
        assert len(table_maps) == 1
        key = "https://example.com/bronze/adminpulse#tblClient"
        assert key in table_maps
        assert table_maps[key][0]["mapping_type"] == "direct"
        assert table_maps[key][0]["target_uri"] == "http://kairos.example/ontology/Client"

    def test_parse_skos_column_maps(self, mappings_dir):
        maps, _ = _parse_skos_mappings(mappings_dir)
        col_maps = maps["column_maps"]
        assert len(col_maps) == 2

        id_key = "https://example.com/bronze/adminpulse#tblClient_ClientID"
        assert id_key in col_maps
        assert col_maps[id_key][0]["expression_fact"] is None
        assert col_maps[id_key][0]["match_type"] == "exactMatch"

        name_key = "https://example.com/bronze/adminpulse#tblClient_Name"
        assert name_key in col_maps
        assert col_maps[name_key][0]["expression_fact"] is None
        assert col_maps[name_key][0]["match_type"] == "closeMatch"

    def test_parse_skos_empty_dir(self, tmp_path):
        empty = tmp_path / "empty_map"
        empty.mkdir()
        result, _ = _parse_skos_mappings(empty)
        assert result == {"table_maps": {}, "column_maps": {}}

    def test_parse_skos_subdirectory(self, tmp_path):
        """Mapping files in subdirectories are discovered (rglob)."""
        d = tmp_path / "mappings"
        sub = d / "adminpulse"
        sub.mkdir(parents=True)
        (sub / "adminpulse-to-client.ttl").write_text(SKOS_MAPPING_TTL, encoding="utf-8")
        maps, _ = _parse_skos_mappings(d)
        assert len(maps["table_maps"]) == 1
        assert len(maps["column_maps"]) == 2

    def test_parse_skos_split_pattern(self, tmp_path):
        """One bronze table mapping to multiple domain classes (1:N split)."""
        split_ttl = textwrap.dedent("""\
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
            @prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
            @prefix map: <https://example.com/mapping/contacts#> .
            @prefix bronze-ap: <https://example.com/bronze/adminpulse#> .
            @prefix party: <http://kairos.example/ontology/> .

            bronze-ap:tblContacts skos:exactMatch party:Client,
                                                     party:ContactPerson .
            map:client a kairos-map:TableMapping ;
                kairos-map:sourceTable bronze-ap:tblContacts ;
                kairos-map:targetClass party:Client ;
                kairos-map:mappingType "split" ;
                kairos-map:matchType "exactMatch" ;
                kairos-map:rowFilter map:isClient .
            map:contact a kairos-map:TableMapping ;
                kairos-map:sourceTable bronze-ap:tblContacts ;
                kairos-map:targetClass party:ContactPerson ;
                kairos-map:mappingType "split" ;
                kairos-map:matchType "exactMatch" ;
                kairos-map:rowFilter map:isContact .
            map:isClient a kairos-map:LiteralExpression ;
                kairos-map:literalValue true ;
                kairos-map:outputType "boolean" ;
                kairos-map:nullable false ;
                kairos-map:nullPolicy "never-null" ;
                kairos-map:determinism "deterministic" ;
                kairos-map:requiresCapability "typed-literal" .
            map:isContact a kairos-map:LiteralExpression ;
                kairos-map:literalValue true ;
                kairos-map:outputType "boolean" ;
                kairos-map:nullable false ;
                kairos-map:nullPolicy "never-null" ;
                kairos-map:determinism "deterministic" ;
                kairos-map:requiresCapability "typed-literal" .
        """)
        d = tmp_path / "mappings"
        d.mkdir()
        (d / "contacts-split.ttl").write_text(split_ttl, encoding="utf-8")
        maps, _ = _parse_skos_mappings(d)
        # One key (the bronze table URI), but TWO entries in the list
        key = "https://example.com/bronze/adminpulse#tblContacts"
        assert key in maps["table_maps"]
        assert len(maps["table_maps"][key]) == 2
        targets = {e["target_uri"] for e in maps["table_maps"][key]}
        assert "http://kairos.example/ontology/Client" in targets
        assert "http://kairos.example/ontology/ContactPerson" in targets

    def test_parse_skos_coalesce_contract(self, tmp_path):
        """A structured COALESCE AST is captured without SQL."""
        default_ttl = textwrap.dedent("""\
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
            @prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
            @prefix map: <https://example.com/mapping/default#> .
            @prefix bronze-ap: <https://example.com/bronze/adminpulse#> .
            @prefix party: <http://kairos.example/ontology/> .

            bronze-ap:tblClient skos:exactMatch party:Client .
            bronze-ap:tblClient_Email skos:exactMatch party:email .
            map:table a kairos-map:TableMapping ;
                kairos-map:sourceTable bronze-ap:tblClient ;
                kairos-map:targetClass party:Client ;
                kairos-map:mappingType "direct" ;
                kairos-map:matchType "exactMatch" .
            map:email a kairos-map:ColumnMapping ;
                kairos-map:sourceColumn bronze-ap:tblClient_Email ;
                kairos-map:targetProperty party:email ;
                kairos-map:matchType "exactMatch" ;
                kairos-map:expression map:coalesce .
            map:coalesce a kairos-map:FunctionExpression ;
                kairos-map:function "coalesce" ;
                kairos-map:arguments ( map:emailSource map:fallback ) ;
                kairos-map:outputType "string" ;
                kairos-map:nullable false ;
                kairos-map:nullPolicy "first-non-null" ;
                kairos-map:determinism "deterministic" ;
                kairos-map:requiresCapability "null-handling" .
            map:emailSource a kairos-map:SourceColumnExpression ;
                kairos-map:sourceColumn bronze-ap:tblClient_Email ;
                kairos-map:outputType "string" ;
                kairos-map:nullable true ;
                kairos-map:nullPolicy "propagate" ;
                kairos-map:determinism "deterministic" ;
                kairos-map:requiresCapability "source-column" .
            map:fallback a kairos-map:LiteralExpression ;
                kairos-map:literalValue "unknown@example.com" ;
                kairos-map:outputType "string" ;
                kairos-map:nullable false ;
                kairos-map:nullPolicy "never-null" ;
                kairos-map:determinism "deterministic" ;
                kairos-map:requiresCapability "typed-literal" .
        """)
        d = tmp_path / "mappings"
        d.mkdir()
        (d / "default-val.ttl").write_text(default_ttl, encoding="utf-8")
        maps, _ = _parse_skos_mappings(d)
        col = maps["column_maps"]["https://example.com/bronze/adminpulse#tblClient_Email"][0]
        assert col["expression_fact"].kind == "function"
        assert col["expression_fact"].operation == "coalesce"

    def test_parse_multi_target_column(self, tmp_path):
        """One source column → two target properties produces two entries."""
        multi_ttl = textwrap.dedent("""\
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
            @prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
            @prefix map: <https://example.com/mapping/multi#> .
            @prefix bronze-ap: <https://example.com/bronze/adminpulse#> .
            @prefix party: <http://kairos.example/ontology/> .

            bronze-ap:tblClient skos:exactMatch party:Client .
            bronze-ap:tblClient_Name skos:exactMatch party:clientName,
                                                            party:displayName .
            map:table a kairos-map:TableMapping ;
                kairos-map:sourceTable bronze-ap:tblClient ;
                kairos-map:targetClass party:Client ;
                kairos-map:mappingType "direct" ;
                kairos-map:matchType "exactMatch" .
            map:name a kairos-map:ColumnMapping ;
                kairos-map:sourceColumn bronze-ap:tblClient_Name ;
                kairos-map:targetProperty party:clientName ;
                kairos-map:matchType "exactMatch" .
            map:display a kairos-map:ColumnMapping ;
                kairos-map:sourceColumn bronze-ap:tblClient_Name ;
                kairos-map:targetProperty party:displayName ;
                kairos-map:matchType "exactMatch" .
        """)
        d = tmp_path / "mappings"
        d.mkdir()
        (d / "multi-target.ttl").write_text(multi_ttl, encoding="utf-8")
        maps, _ = _parse_skos_mappings(d)
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
        tests = _extract_shacl_tests(shapes_dir, "http://kairos.example/ontology/Client")
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
    def test_silver_models_generated(
        self, classes, ontology_graph, template_dir, bronze_dir, mappings_dir
    ):
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
        # #630-contracts: this class has no bronze mapping (no bound
        # EntityBinding), so its schema entry is ontology/SHACL-only with no
        # physical Silver plan to source a data_type from -- contracts must
        # stay off rather than emit an enforced-but-untyped contract.
        assert "config" not in models[0]
        cols = {c["name"]: c for c in models[0]["columns"]}
        assert "client_sk" in cols
        assert "not_null" in cols["client_sk"]["tests"]
        # SHACL not_null on client_name
        if "client_name" in cols and cols["client_name"].get("tests"):
            assert "not_null" in cols["client_name"]["tests"]
            complex_tests = [
                test for test in cols["client_name"]["tests"] if isinstance(test, dict)
            ]
            assert complex_tests
            assert all(len(test) == 1 for test in complex_tests)
            length_test = next(
                test
                for test in complex_tests
                if "dbt_expectations.expect_column_value_lengths_to_be_between" in test
            )
            assert (
                length_test["dbt_expectations.expect_column_value_lengths_to_be_between"][
                    "min_value"
                ]
                == 2
            )

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

        assert not any("models/staging/" in key for key in artifacts)

        # Should have silver model
        silver_files = [k for k in artifacts if "models/silver/" in k and k.endswith(".sql")]
        assert len(silver_files) >= 1

        # #630-contracts: a fully bound class (bronze + mappings, so the
        # physical Silver plan resolves a data_type for every column) gets
        # dbt model contracts enabled in its properties yml.
        schema_yml = yaml.safe_load(artifacts["models/silver/client/_client__models.yml"])
        client_model = next(m for m in schema_yml["models"] if m["name"] == "client")
        assert client_model["config"]["contract"]["enforced"] is True
        assert all("data_type" in column for column in client_model["columns"])

        # Should have dbt_project.yml
        assert "dbt_project.yml" in artifacts

        # Should have packages.yml
        assert "packages.yml" in artifacts

        # packages.yml must use the current metaplane namespace, not deprecated calogica
        packages_yml = artifacts["packages.yml"]
        assert "metaplane/dbt_expectations" in packages_yml
        assert "calogica" not in packages_yml

    def test_silver_model_reads_bronze_source_directly(
        self, classes, ontology_graph, template_dir, bronze_dir, mappings_dir
    ):
        """Silver reads the governed Bronze source without an intermediate prep model."""
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
            k
            for k in artifacts
            if "models/silver/" in k and k.endswith(".sql") and "_sources" not in k
        )
        content = artifacts[silver_key]
        assert "ref('stg_admin_pulse__tbl_client')" not in content
        assert "source('admin_pulse', 'tblClient')" in content

    def test_dbt_project_yml(self, classes, ontology_graph, template_dir, bronze_dir, mappings_dir):
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
        # DD-627: dbt_project.yml's folder-level cascade default is `table`, and
        # the emitted non-runtime ENTITY model no longer sets `materialized=`
        # inline, so this project-level default is what actually takes effect.
        assert proj["models"]["client_project"]["silver"]["+materialized"] == "table"
        client_sql = artifacts["models/silver/client/client.sql"]
        assert "materialized=" not in client_sql
        assert "config(" in client_sql

    def test_dbt_project_yml_has_seeds_config(
        self, classes, ontology_graph, template_dir, bronze_dir, mappings_dir
    ):
        """#596: dbt_project.yml declares a seeds: config block (schema, quoting, tags)
        instead of leaving seeds on the profile's default schema and adapter-inferred types."""
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
        seeds_config = proj["seeds"]["client_project"]
        assert seeds_config["+schema"] == "reference"
        assert seeds_config["+quote_columns"] is True
        assert seeds_config["+tags"] == ["reference"]

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
    @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

    <http://kairos.example/ontology> a owl:Ontology ;
        rdfs:label "Test Ontology" ;
        owl:versionInfo "1.0.0" ;
        kairos-ext:goldSchema "gold_sales" ;
        kairos-ext:goldProductProfile "dimensional-powerbi-v1" ;
        kairos-ext:calendarProfile ex:Calendar .

    ex:Customer a owl:Class ;
        rdfs:label "Customer" ;
        rdfs:comment "A customer entity" ;
        kairos-ext:naturalKey "customerId" ;
        kairos-ext:goldTableType "dimension" ;
        kairos-ext:goldSourceModel "customer" ;
        kairos-ext:goldSourceVersion "1.0.0" ;
        kairos-ext:dimensionExposure "current-only" ;
        kairos-ext:dimensionVersionBinding "current" .

    ex:Product a owl:Class ;
        rdfs:label "Product" ;
        rdfs:comment "A product entity" ;
        kairos-ext:naturalKey "productId" ;
        kairos-ext:goldTableType "dimension" ;
        kairos-ext:goldSourceModel "product" ;
        kairos-ext:goldSourceVersion "1.0.0" ;
        kairos-ext:dimensionExposure "current-only" ;
        kairos-ext:dimensionVersionBinding "current" .

    ex:Order a owl:Class ;
        rdfs:label "Order" ;
        rdfs:comment "An order entity" ;
        kairos-ext:naturalKey "orderId" ;
        kairos-ext:goldTableType "fact" ;
        kairos-ext:goldSourceModel "order" ;
        kairos-ext:goldSourceVersion "1.0.0" ;
        kairos-ext:factGrain "one order source record" ;
        kairos-ext:factType "transaction" ;
        kairos-ext:dimensionVersionBinding "current" ;
        kairos-ext:incrementalPolicy ex:OrderIncremental .

    ex:OrderIncremental a kairos-ext:IncrementalPolicy ;
        kairos-ext:mergeIdentity "_source_record_key" ;
        kairos-ext:cdcOperation "_cdc_operation" ;
        kairos-ext:sourceUpdateTimestamp "_loaded_at" ;
        kairos-ext:sourceEffectiveTimestamp "order_date" ;
        kairos-ext:ingestionTimestamp "_ingested_at" ;
        kairos-ext:totalOrderTieBreaker "_source_record_key" ;
        kairos-ext:lookbackWindow "7 days" ;
        kairos-ext:hardDeletePolicy "tombstone" ;
        kairos-ext:softDeletePolicy "apply-operation" ;
        kairos-ext:lateArrivalPolicy "reconcile-with-lookback" ;
        kairos-ext:correctionPolicy "replace-by-total-order" ;
        kairos-ext:replayPolicy "idempotent-merge" ;
        kairos-ext:backfillPolicy "full-rebuild-approved" ;
        kairos-ext:schemaChangePolicy "fail" .

    ex:Calendar a kairos-ext:CalendarProfile ;
        kairos-ext:calendarStartDate "2020-01-01"^^xsd:date ;
        kairos-ext:calendarEndDate "2030-12-31"^^xsd:date ;
        kairos-ext:fiscalYearStartMonth 1 ;
        kairos-ext:weekPattern "iso-8601-monday" ;
        kairos-ext:calendarLocale "en-US" ;
        kairos-ext:holidaySource "none-approved" ;
        kairos-ext:calendarTimeZone "UTC" ;
        kairos-ext:periodClosurePolicy "none-approved" ;
        kairos-ext:rolePlayingDate "OrderDate=Order.order_date" ;
        kairos-ext:calendarApprovalStatus "approved" .

    ex:customerId a owl:DatatypeProperty ;
        rdfs:label "customer ID" ;
        rdfs:domain ex:Customer ;
        rdfs:range xsd:string .

    ex:productId a owl:DatatypeProperty ;
        rdfs:label "product ID" ;
        rdfs:domain ex:Product ;
        rdfs:range xsd:string .

    ex:orderId a owl:DatatypeProperty ;
        rdfs:label "order ID" ;
        rdfs:domain ex:Order ;
        rdfs:range xsd:string .

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
    {
        "uri": "http://kairos.example/ontology/Customer",
        "name": "Customer",
        "label": "Customer",
        "comment": "A customer entity",
    },
    {
        "uri": "http://kairos.example/ontology/Product",
        "name": "Product",
        "label": "Product",
        "comment": "A product entity",
    },
    {
        "uri": "http://kairos.example/ontology/Order",
        "name": "Order",
        "label": "Order",
        "comment": "An order entity",
    },
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
    @prefix map: <https://example.com/mapping/sales#> .
    @prefix bronze-sales: <https://example.com/bronze/sales#> .
    @prefix ex: <http://kairos.example/ontology/> .

    bronze-sales:tblCustomer skos:exactMatch ex:Customer .
    bronze-sales:tblCustomer_CustomerID skos:exactMatch ex:customerId .
    bronze-sales:tblCustomer_Name skos:exactMatch ex:customerName .
    bronze-sales:tblProduct skos:exactMatch ex:Product .
    bronze-sales:tblProduct_ProductID skos:exactMatch ex:productId .
    bronze-sales:tblProduct_Name skos:exactMatch ex:productName .
    bronze-sales:tblOrder skos:exactMatch ex:Order .
    bronze-sales:tblOrder_OrderID skos:exactMatch ex:orderId .
    bronze-sales:tblOrder_OrderDate skos:exactMatch ex:orderDate .
    bronze-sales:tblOrder_Amount skos:exactMatch ex:orderAmount .

    map:customer a kairos-map:TableMapping ;
        kairos-map:sourceTable bronze-sales:tblCustomer ;
        kairos-map:targetClass ex:Customer ;
        kairos-map:mappingType "direct" ;
        kairos-map:matchType "exactMatch" .
    map:product a kairos-map:TableMapping ;
        kairos-map:sourceTable bronze-sales:tblProduct ;
        kairos-map:targetClass ex:Product ;
        kairos-map:mappingType "direct" ;
        kairos-map:matchType "exactMatch" .
    map:order a kairos-map:TableMapping ;
        kairos-map:sourceTable bronze-sales:tblOrder ;
        kairos-map:targetClass ex:Order ;
        kairos-map:mappingType "direct" ;
        kairos-map:matchType "exactMatch" .

    map:customerId a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze-sales:tblCustomer_CustomerID ;
        kairos-map:targetProperty ex:customerId ;
        kairos-map:matchType "exactMatch" .
    map:customerName a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze-sales:tblCustomer_Name ;
        kairos-map:targetProperty ex:customerName ;
        kairos-map:matchType "exactMatch" .
    map:productId a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze-sales:tblProduct_ProductID ;
        kairos-map:targetProperty ex:productId ;
        kairos-map:matchType "exactMatch" .
    map:productName a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze-sales:tblProduct_Name ;
        kairos-map:targetProperty ex:productName ;
        kairos-map:matchType "exactMatch" .
    map:orderId a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze-sales:tblOrder_OrderID ;
        kairos-map:targetProperty ex:orderId ;
        kairos-map:matchType "exactMatch" .
    map:orderDate a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze-sales:tblOrder_OrderDate ;
        kairos-map:targetProperty ex:orderDate ;
        kairos-map:matchType "exactMatch" .
    map:orderAmount a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze-sales:tblOrder_Amount ;
        kairos-map:targetProperty ex:orderAmount ;
        kairos-map:matchType "exactMatch" .
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

    def test_gold_models_generated(
        self, gold_ontology_graph, template_dir, gold_bronze_dir, gold_mappings_dir
    ):
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

    def test_gold_model_refs_silver(
        self, gold_ontology_graph, template_dir, gold_bronze_dir, gold_mappings_dir
    ):
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

    def test_gold_fact_model_content(
        self, gold_ontology_graph, template_dir, gold_bronze_dir, gold_mappings_dir
    ):
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
        assert "Explicit role: fact" in content

    def test_gold_dimension_scd2_framing(
        self, gold_ontology_graph, template_dir, gold_bronze_dir, gold_mappings_dir
    ):
        """Current filtering is not invented without an SCD2 Silver authority."""
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
        assert "is_current = 1" not in content

    def test_gold_schema_yaml(
        self, gold_ontology_graph, template_dir, gold_bronze_dir, gold_mappings_dir
    ):
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
                (c for c in model["columns"] if c["name"].endswith("_sk") and c.get("tests")),
                None,
            )
            if pk_col:
                assert "not_null" in pk_col["tests"]
                assert "unique" in pk_col["tests"]

    def test_dbt_project_yml_has_gold(
        self, gold_ontology_graph, template_dir, gold_bronze_dir, gold_mappings_dir
    ):
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

    def test_gold_dim_date_model(
        self, gold_ontology_graph, template_dir, gold_bronze_dir, gold_mappings_dir
    ):
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
    @prefix map: <https://example.com/mapping/cross-domain#> .
    @prefix bronze-ap: <https://example.com/bronze/adminpulse#> .
    @prefix ex: <http://kairos.example/ontology/> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

    bronze-ap:Relation skos:exactMatch ex:Client .
    bronze-ap:Relation_id skos:exactMatch ex:clientId,
                                                 ex:representsParty ;
        rdfs:comment "FK to party — resolved via join" .
    bronze-ap:Relation_Name skos:exactMatch ex:clientName .

    map:client a kairos-map:TableMapping ;
        kairos-map:sourceTable bronze-ap:Relation ;
        kairos-map:targetClass ex:Client ;
        kairos-map:mappingType "direct" ;
        kairos-map:matchType "exactMatch" .
    map:clientId a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze-ap:Relation_id ;
        kairos-map:targetProperty ex:clientId ;
        kairos-map:matchType "exactMatch" .
    map:clientName a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze-ap:Relation_Name ;
        kairos-map:targetProperty ex:clientName ;
        kairos-map:matchType "exactMatch" .
    map:party a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze-ap:Relation_id ;
        kairos-map:targetProperty ex:representsParty ;
        kairos-map:matchType "exactMatch" .
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
        (d / "adminpulse.vocabulary.ttl").write_text(CROSS_DOMAIN_BRONZE_TTL, encoding="utf-8")
        return tmp_path / "sources"

    @pytest.fixture
    def cross_domain_mappings_dir(self, tmp_path):
        d = tmp_path / "mappings" / "adminpulse"
        d.mkdir(parents=True)
        (d / "adminpulse-to-client.ttl").write_text(CROSS_DOMAIN_MAPPING_TTL, encoding="utf-8")
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
        self,
        cross_domain_classes,
        cross_domain_graph,
        template_dir,
        cross_domain_bronze_dir,
        cross_domain_mappings_dir,
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
        silver_key = next(k for k in artifacts if "client.sql" in k and "models/silver/" in k)
        content = artifacts[silver_key]

        # Should contain a party_sk FK column
        assert "party_sk" in content
        # Should contain a ref() join to the party model
        assert "ref('party')" in content
        # Should have a left join
        assert "left join" in content

    def test_fk_join_condition(
        self,
        cross_domain_classes,
        cross_domain_graph,
        template_dir,
        cross_domain_bronze_dir,
        cross_domain_mappings_dir,
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
        silver_key = next(k for k in artifacts if "client.sql" in k and "models/silver/" in k)
        content = artifacts[silver_key]

        # Join should reference the target natural key (party_id from naturalKey)
        assert "party_ref" in content
        assert "party_id" in content
        assert "[party_ref].[is_current] = 1" not in content

    def test_fk_change_never_creates_an_implicit_hash_contract(
        self,
        cross_domain_classes,
        cross_domain_graph,
        template_dir,
        cross_domain_bronze_dir,
        cross_domain_mappings_dir,
    ):
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
            key for key in artifacts if "client.sql" in key and "models/silver/" in key
        )
        assert "party_ref.party_sk as party_sk" in artifacts[silver_key]
        assert "kairos_canonical_hash_v1" not in artifacts[silver_key]

    def test_fk_change_can_be_excluded_from_scd2_hash(
        self,
        cross_domain_classes,
        cross_domain_graph,
        template_dir,
        cross_domain_bronze_dir,
        cross_domain_mappings_dir,
    ):
        prop = URIRef("http://kairos.example/ontology/representsParty")
        cross_domain_graph.add(
            (
                prop,
                URIRef("https://kairos.cnext.eu/ext#silverForeignKeyChangeDetection"),
                Literal(False),
            )
        )
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
            key for key in artifacts if "client.sql" in key and "models/silver/" in key
        )
        assert "party_ref.party_sk as party_sk" in artifacts[silver_key]
        assert "kairos_canonical_hash_v1" not in artifacts[silver_key]

    def test_nonportable_schema_override_is_rejected(
        self,
        cross_domain_classes,
        cross_domain_graph,
        template_dir,
        cross_domain_bronze_dir,
        cross_domain_mappings_dir,
    ):
        cross_domain_graph.add(
            (
                URIRef("http://kairos.example/ontology"),
                URIRef("https://kairos.cnext.eu/ext#silverSchema"),
                Literal("silver-logistics"),
            )
        )
        with pytest.raises(ValueError, match="portable SQL identifier"):
            generate_dbt_artifacts(
                classes=cross_domain_classes,
                graph=cross_domain_graph,
                template_dir=template_dir,
                namespace="http://kairos.example/ontology/",
                ontology_name="client",
                bronze_dir=cross_domain_bronze_dir,
                mappings_dir=cross_domain_mappings_dir,
            )

    def test_fk_column_in_schema_yaml(
        self,
        cross_domain_classes,
        cross_domain_graph,
        template_dir,
        cross_domain_bronze_dir,
        cross_domain_mappings_dir,
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
        client_model = next(m for m in schema["models"] if m["name"] == "client")
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
        return [
            {
                "system_label": "AdminPulse",
                "tables": [
                    {
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
                    }
                ],
            }
        ]

    @pytest.fixture
    def mappings_with_nk_column(self):
        """Mappings where tblClient_TypeCode → typeCode (NK of ClientType)."""
        return {
            "table_maps": {
                "https://example.com/bronze/adminpulse#tblClient": [
                    {
                        "target_uri": "http://kairos.example/ontology/Client",
                        "mapping_type": "direct",
                    }
                ],
            },
            "column_maps": {
                "https://example.com/bronze/adminpulse#tblClient_ClientID": [
                    {
                        "target_uri": "http://kairos.example/ontology/clientId",
                        "transform": "CAST(source.ClientID AS STRING)",
                        "match_type": "exactMatch",
                    }
                ],
                "https://example.com/bronze/adminpulse#tblClient_TypeCode": [
                    {
                        "target_uri": "http://kairos.example/ontology/typeCode",
                        "transform": "source.TypeCode",
                        "match_type": "exactMatch",
                    }
                ],
            },
        }

    def test_auto_infer_fk_from_nk(
        self, autoinfer_graph, systems_with_fk_column, mappings_with_nk_column
    ):
        """Auto-infer FK join when source column maps to NK of range class."""
        source_refs = [
            (
                "adminpulse",
                "tblClient",
                "https://example.com/bronze/adminpulse#tblClient",
            )
        ]
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

    def test_auto_infer_ignores_other_tables(self, autoinfer_graph):
        """Auto-inference only considers columns from the current source table."""
        # tblClientType has TypeCode, but it's a different table — should NOT
        # be used for auto-inference when building the Client model from tblClient
        systems = [
            {
                "system_label": "AdminPulse",
                "tables": [
                    {
                        "uri": "https://example.com/bronze/adminpulse#tblClient",
                        "name": "tblClient",
                        "columns": [
                            {
                                "uri": "https://example.com/bronze/adminpulse#tblClient_ClientID",
                                "name": "ClientID",
                                "data_type": "int",
                            }
                        ],
                    },
                    {
                        "uri": "https://example.com/bronze/adminpulse#tblClientType",
                        "name": "tblClientType",
                        "columns": [
                            {
                                "uri": "https://example.com/bronze/adminpulse#tblClientType_TypeCode",
                                "name": "TypeCode",
                                "data_type": "int",
                            }
                        ],
                    },
                ],
            }
        ]
        # Mapping: tblClientType_TypeCode → typeCode (wrong table)
        mappings = {
            "table_maps": {},
            "column_maps": {
                "https://example.com/bronze/adminpulse#tblClientType_TypeCode": [
                    {
                        "target_uri": "http://kairos.example/ontology/typeCode",
                        "transform": "source.TypeCode",
                        "match_type": "exactMatch",
                    }
                ],
            },
        }
        source_refs = [
            (
                "adminpulse",
                "tblClient",
                "https://example.com/bronze/adminpulse#tblClient",
            )
        ]
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
                "https://example.com/bronze/adminpulse#tblClient_TypeCode": [
                    {
                        "target_uri": "http://kairos.example/ontology/typeCode",
                        "transform": "source.TypeCode",
                        "match_type": "exactMatch",
                    }
                ],
            },
        }
        source_refs = [
            (
                "adminpulse",
                "tblClient",
                "https://example.com/bronze/adminpulse#tblClient",
            )
        ]
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
        source_refs = [
            (
                "adminpulse",
                "tblClient",
                "https://example.com/bronze/adminpulse#tblClient",
            )
        ]
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
# FK auto-inference ambiguity: multiple FK properties sharing the same range
# (regression for issue #174)
# ---------------------------------------------------------------------------

FK_SAME_RANGE_ONTOLOGY_TTL = textwrap.dedent("""\
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
    @prefix ex:   <http://kairos.example/ontology/> .
    @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

    <http://kairos.example/ontology> a owl:Ontology ;
        rdfs:label "Test Same-Range FK" ;
        owl:versionInfo "1.0.0" .

    ex:TradeParty a owl:Class ;
        rdfs:label "Trade Party" ;
        rdfs:comment "A trading party" ;
        kairos-ext:naturalKey "partyId" .

    ex:partyId a owl:DatatypeProperty ;
        rdfs:domain ex:TradeParty ;
        rdfs:range xsd:string .

    ex:Address a owl:Class ;
        rdfs:label "Address" ;
        rdfs:comment "A postal address" ;
        kairos-ext:naturalKey "addressCode" .

    ex:addressCode a owl:DatatypeProperty ;
        rdfs:domain ex:Address ;
        rdfs:range xsd:string .

    ex:hasBillingAddress a owl:ObjectProperty ;
        rdfs:label "has billing address" ;
        rdfs:domain ex:TradeParty ;
        rdfs:range ex:Address ;
        kairos-ext:silverForeignKey "true" ;
        kairos-ext:silverColumnName "billing_address_sk" .

    ex:hasShippingAddress a owl:ObjectProperty ;
        rdfs:label "has shipping address" ;
        rdfs:domain ex:TradeParty ;
        rdfs:range ex:Address ;
        kairos-ext:silverForeignKey "true" ;
        kairos-ext:silverColumnName "shipping_address_sk" .
""")


class TestAmbiguousSameRangeFK:
    """Regression tests for issue #174.

    When ≥2 FK properties on a class share the same range natural key, NK-based
    auto-inference cannot disambiguate roles and must be disabled — unmapped roles
    emit a NULL placeholder plus an explicit ambiguity warning, while explicitly
    mapped roles are unaffected.
    """

    PARTY_URI = "http://kairos.example/ontology/TradeParty"
    BILLING_PROP = "http://kairos.example/ontology/hasBillingAddress"
    SHIPPING_PROP = "http://kairos.example/ontology/hasShippingAddress"
    ADDRESS_CODE = "http://kairos.example/ontology/addressCode"
    TBL = "https://example.com/bronze/erp#tblParty"
    COL_BILLING = "https://example.com/bronze/erp#tblParty_BillingAddress"
    COL_SHIPPING = "https://example.com/bronze/erp#tblParty_ShippingAddress"

    @pytest.fixture
    def graph(self):
        g = Graph()
        g.parse(data=FK_SAME_RANGE_ONTOLOGY_TTL, format="turtle")
        return g

    @pytest.fixture
    def systems(self):
        return [
            {
                "system_label": "ERP",
                "tables": [
                    {
                        "uri": self.TBL,
                        "name": "tblParty",
                        "columns": [
                            {"uri": f"{self.TBL}_PartyID", "name": "PartyID", "data_type": "int"},
                            {
                                "uri": self.COL_BILLING,
                                "name": "BillingAddress",
                                "data_type": "varchar",
                            },
                            {
                                "uri": self.COL_SHIPPING,
                                "name": "ShippingAddress",
                                "data_type": "varchar",
                            },
                        ],
                    }
                ],
            }
        ]

    @property
    def source_refs(self):
        return [("erp", "tblParty", self.TBL)]

    def _fk_by_name(self, fk_columns, name):
        return next(c for c in fk_columns if c["target_name"] == name)

    def test_issue_174_unmapped_sibling_not_cross_contaminated(self, graph, systems):
        """Billing mapped explicitly; shipping unmapped → shipping is NULL, not joined."""
        # Billing column is mapped both to the FK property (explicit) and to the
        # Address natural key — the exact setup that previously mis-resolved shipping.
        mappings = {
            "table_maps": {},
            "column_maps": {
                self.COL_BILLING: [
                    {
                        "target_uri": self.BILLING_PROP,
                        "transform": "source.BillingAddress",
                        "match_type": "exactMatch",
                    },
                    {
                        "target_uri": self.ADDRESS_CODE,
                        "transform": "source.BillingAddress",
                        "match_type": "exactMatch",
                    },
                ],
            },
        }
        fk_columns, joins, warnings = _extract_fk_columns_and_joins(
            graph,
            self.PARTY_URI,
            mappings,
            self.source_refs,
            systems=systems,
        )

        billing = self._fk_by_name(fk_columns, "billing_address_sk")
        shipping = self._fk_by_name(fk_columns, "shipping_address_sk")

        # Billing resolves via explicit mapping
        assert "NULL" not in billing["expression"]
        # Shipping is NOT cross-contaminated — emitted as NULL placeholder
        assert "NULL" in shipping["expression"]

        # Only the billing join exists; shipping has none
        assert len(joins) == 1
        assert "BillingAddress" in joins[0]["condition"]

        # Exactly one ambiguity warning, naming the shipping role
        amb = [w for w in warnings if "ambiguous" in w.lower()]
        assert len(amb) == 1
        assert "shipping_address_sk" in amb[0]
        assert "hasShippingAddress" in amb[0]

    def test_both_mapped_resolve_without_warning(self, graph, systems):
        """Both same-range FKs explicitly mapped → both resolve, no ambiguity warning."""
        mappings = {
            "table_maps": {},
            "column_maps": {
                self.COL_BILLING: [
                    {
                        "target_uri": self.BILLING_PROP,
                        "transform": "source.BillingAddress",
                        "match_type": "exactMatch",
                    },
                ],
                self.COL_SHIPPING: [
                    {
                        "target_uri": self.SHIPPING_PROP,
                        "transform": "source.ShippingAddress",
                        "match_type": "exactMatch",
                    },
                ],
            },
        }
        fk_columns, joins, warnings = _extract_fk_columns_and_joins(
            graph,
            self.PARTY_URI,
            mappings,
            self.source_refs,
            systems=systems,
        )

        billing = self._fk_by_name(fk_columns, "billing_address_sk")
        shipping = self._fk_by_name(fk_columns, "shipping_address_sk")
        assert "NULL" not in billing["expression"]
        assert "NULL" not in shipping["expression"]
        assert len(joins) == 2
        assert not [w for w in warnings if "ambiguous" in w.lower()]

    def test_all_unmapped_both_ambiguous(self, graph, systems):
        """Both same-range FKs unmapped → both NULL with ambiguity warnings."""
        mappings = {"table_maps": {}, "column_maps": {}}
        fk_columns, joins, warnings = _extract_fk_columns_and_joins(
            graph,
            self.PARTY_URI,
            mappings,
            self.source_refs,
            systems=systems,
        )
        assert all("NULL" in c["expression"] for c in fk_columns)
        assert len(joins) == 0
        amb = [w for w in warnings if "ambiguous" in w.lower()]
        assert len(amb) == 2

    def test_single_range_fk_still_auto_infers(
        self, autoinfer_graph, systems_with_fk_column, mappings_with_nk_column
    ):
        """A lone FK property to a range still auto-infers (no false ambiguity)."""
        source_refs = [
            (
                "adminpulse",
                "tblClient",
                "https://example.com/bronze/adminpulse#tblClient",
            )
        ]
        fk_columns, joins, warnings = _extract_fk_columns_and_joins(
            autoinfer_graph,
            "http://kairos.example/ontology/Client",
            mappings_with_nk_column,
            source_refs,
            systems=systems_with_fk_column,
        )
        assert len(joins) == 1
        assert not [w for w in warnings if "ambiguous" in w.lower()]

    def test_discriminator_folded_subtypes_share_nk_are_ambiguous(self):
        """Two FK props to distinct subtypes sharing an inherited parent NK collide."""
        ttl = textwrap.dedent("""\
            @prefix owl:  <http://www.w3.org/2002/07/owl#> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
            @prefix ex:   <http://kairos.example/ontology/> .
            @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

            <http://kairos.example/ontology> a owl:Ontology ;
                rdfs:label "Folded" ; owl:versionInfo "1.0.0" .

            ex:Party a owl:Class ; rdfs:label "Party" ; rdfs:comment "p" ;
                kairos-ext:naturalKey "partyId" ;
                kairos-ext:inheritanceStrategy "discriminator" .
            ex:partyId a owl:DatatypeProperty ;
                rdfs:domain ex:Party ; rdfs:range xsd:string .
            ex:LegalEntity a owl:Class ; rdfs:subClassOf ex:Party ;
                rdfs:label "Legal Entity" ; rdfs:comment "le" .
            ex:NaturalPerson a owl:Class ; rdfs:subClassOf ex:Party ;
                rdfs:label "Natural Person" ; rdfs:comment "np" .

            ex:Invoice a owl:Class ; rdfs:label "Invoice" ; rdfs:comment "i" ;
                kairos-ext:naturalKey "invoiceId" .
            ex:invoiceId a owl:DatatypeProperty ;
                rdfs:domain ex:Invoice ; rdfs:range xsd:string .
            ex:billedToLegalEntity a owl:ObjectProperty ;
                rdfs:label "billed to legal entity" ;
                rdfs:domain ex:Invoice ; rdfs:range ex:LegalEntity ;
                kairos-ext:silverForeignKey "true" ;
                kairos-ext:silverColumnName "legal_party_sk" .
            ex:billedToNaturalPerson a owl:ObjectProperty ;
                rdfs:label "billed to natural person" ;
                rdfs:domain ex:Invoice ; rdfs:range ex:NaturalPerson ;
                kairos-ext:silverForeignKey "true" ;
                kairos-ext:silverColumnName "person_party_sk" .
        """)
        g = Graph()
        g.parse(data=ttl, format="turtle")
        tbl = "https://example.com/bronze/erp#tblInvoice"
        systems = [
            {
                "system_label": "ERP",
                "tables": [
                    {
                        "uri": tbl,
                        "name": "tblInvoice",
                        "columns": [
                            {"uri": f"{tbl}_InvoiceID", "name": "InvoiceID", "data_type": "int"},
                            {"uri": f"{tbl}_PartyRef", "name": "PartyRef", "data_type": "varchar"},
                        ],
                    }
                ],
            }
        ]
        # PartyRef mapped to the shared parent NK partyId — would mis-resolve both FKs
        mappings = {
            "table_maps": {},
            "column_maps": {
                f"{tbl}_PartyRef": [
                    {
                        "target_uri": "http://kairos.example/ontology/partyId",
                        "transform": "source.PartyRef",
                        "match_type": "exactMatch",
                    }
                ],
            },
        }
        fk_columns, joins, warnings = _extract_fk_columns_and_joins(
            g,
            "http://kairos.example/ontology/Invoice",
            mappings,
            [("erp", "tblInvoice", tbl)],
            systems=systems,
        )
        assert all("NULL" in c["expression"] for c in fk_columns)
        assert len(joins) == 0
        amb = [w for w in warnings if "ambiguous" in w.lower()]
        assert len(amb) == 2

    def test_silver_fk_on_duplicate_join_target_is_ambiguous(self):
        """Two silverForeignKeyOn props redirected onto the same class collide."""
        ttl = textwrap.dedent("""\
            @prefix owl:  <http://www.w3.org/2002/07/owl#> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
            @prefix ex:   <http://kairos.example/ontology/> .
            @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

            <http://kairos.example/ontology> a owl:Ontology ;
                rdfs:label "FKOn" ; owl:versionInfo "1.0.0" .

            ex:TradeParty a owl:Class ; rdfs:label "Trade Party" ; rdfs:comment "tp" ;
                kairos-ext:naturalKey "partyId" .
            ex:partyId a owl:DatatypeProperty ;
                rdfs:domain ex:TradeParty ; rdfs:range xsd:string .
            ex:Address a owl:Class ; rdfs:label "Address" ; rdfs:comment "a" ;
                kairos-ext:naturalKey "addressCode" .
            ex:addressCode a owl:DatatypeProperty ;
                rdfs:domain ex:Address ; rdfs:range xsd:string .

            ex:hasBillingAddress a owl:ObjectProperty ;
                rdfs:label "billing" ;
                rdfs:domain ex:TradeParty ; rdfs:range ex:Address ;
                kairos-ext:silverForeignKeyOn ex:Address ;
                kairos-ext:silverColumnName "billing_party_sk" .
            ex:hasShippingAddress a owl:ObjectProperty ;
                rdfs:label "shipping" ;
                rdfs:domain ex:TradeParty ; rdfs:range ex:Address ;
                kairos-ext:silverForeignKeyOn ex:Address ;
                kairos-ext:silverColumnName "shipping_party_sk" .
        """)
        g = Graph()
        g.parse(data=ttl, format="turtle")
        tbl = "https://example.com/bronze/erp#tblAddress"
        systems = [
            {
                "system_label": "ERP",
                "tables": [
                    {
                        "uri": tbl,
                        "name": "tblAddress",
                        "columns": [
                            {"uri": f"{tbl}_PartyRef", "name": "PartyRef", "data_type": "varchar"},
                        ],
                    }
                ],
            }
        ]
        # PartyRef mapped to the shared join-target NK partyId
        mappings = {
            "table_maps": {},
            "column_maps": {
                f"{tbl}_PartyRef": [
                    {
                        "target_uri": "http://kairos.example/ontology/partyId",
                        "transform": "source.PartyRef",
                        "match_type": "exactMatch",
                    }
                ],
            },
        }
        # Build the Address model — FK columns are redirected here via silverForeignKeyOn
        fk_columns, joins, warnings = _extract_fk_columns_and_joins(
            g,
            "http://kairos.example/ontology/Address",
            mappings,
            [("erp", "tblAddress", tbl)],
            systems=systems,
        )
        assert all("NULL" in c["expression"] for c in fk_columns)
        assert len(joins) == 0
        amb = [w for w in warnings if "ambiguous" in w.lower()]
        assert len(amb) == 2

    @pytest.fixture
    def autoinfer_graph(self):
        g = Graph()
        g.parse(data=FK_AUTOINFER_ONTOLOGY_TTL, format="turtle")
        return g

    @pytest.fixture
    def systems_with_fk_column(self):
        return [
            {
                "system_label": "AdminPulse",
                "tables": [
                    {
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
                    }
                ],
            }
        ]

    @pytest.fixture
    def mappings_with_nk_column(self):
        return {
            "table_maps": {
                "https://example.com/bronze/adminpulse#tblClient": [
                    {
                        "target_uri": "http://kairos.example/ontology/Client",
                        "mapping_type": "direct",
                    }
                ],
            },
            "column_maps": {
                "https://example.com/bronze/adminpulse#tblClient_ClientID": [
                    {
                        "target_uri": "http://kairos.example/ontology/clientId",
                        "transform": "CAST(source.ClientID AS STRING)",
                        "match_type": "exactMatch",
                    }
                ],
                "https://example.com/bronze/adminpulse#tblClient_TypeCode": [
                    {
                        "target_uri": "http://kairos.example/ontology/typeCode",
                        "transform": "source.TypeCode",
                        "match_type": "exactMatch",
                    }
                ],
            },
        }


# ---------------------------------------------------------------------------
# Multi-source merge: canonical superset padding (issue #175)
# ---------------------------------------------------------------------------


class TestMergeSupersetPadding:
    """Verify the merge superset builder produces positionally consistent,
    NULL-padded per-source column lists so the parent UNION ALL is valid."""

    def test_superset_is_union_of_all_sources(self):
        """Canonical order = all data cols (source order) then all FK cols."""
        src_a = [
            {"expression": "a_expr", "target_name": "client_id"},
            {"expression": "n_expr", "target_name": "client_name"},
            {"expression": "v_expr", "target_name": "vat_number"},
        ]
        src_b = [
            {"expression": "b_id", "target_name": "client_id"},
            {"expression": "b_name", "target_name": "client_name"},
            {"expression": "b_city", "target_name": "city"},
        ]
        fk_a = [{"expression": "ref.client_type_sk", "target_name": "client_type_sk"}]
        fk_b = [{"expression": "CAST(NULL AS x)", "target_name": "client_type_sk"}]
        type_map = {
            "client_id": "VARCHAR(255)",
            "client_name": "VARCHAR(255)",
            "vat_number": "VARCHAR(255)",
            "city": "VARCHAR(255)",
        }
        canonical, padded = _build_merge_superset([src_a, src_b], [fk_a, fk_b], type_map)
        names = [c["target_name"] for c in canonical]
        # Data columns first (source order, de-duplicated), then FK columns
        assert names == [
            "client_id",
            "client_name",
            "vat_number",
            "city",
            "client_type_sk",
        ]

    def test_all_sources_have_identical_column_count_and_order(self):
        src_a = [
            {"expression": "a", "target_name": "client_id"},
            {"expression": "v", "target_name": "vat_number"},
        ]
        src_b = [
            {"expression": "b", "target_name": "client_id"},
            {"expression": "c", "target_name": "city"},
        ]
        canonical, padded = _build_merge_superset(
            [src_a, src_b], [[], []], {"vat_number": "VARCHAR(255)", "city": "INT"}
        )
        names = [c["target_name"] for c in canonical]
        for cols in padded:
            assert [c["target_name"] for c in cols] == names

    def test_missing_column_is_null_padded_with_canonical_type(self):
        src_a = [{"expression": "v", "target_name": "vat_number"}]
        src_b = [{"expression": "c", "target_name": "city"}]
        type_map = {"vat_number": "VARCHAR(255)", "city": "INT"}
        _canonical, padded = _build_merge_superset([src_a, src_b], [[], []], type_map)
        # Source B is missing vat_number → CAST(NULL AS VARCHAR(255))
        b_by_name = {c["target_name"]: c["expression"] for c in padded[1]}
        assert b_by_name["vat_number"] == "CAST(NULL AS VARCHAR(255))"
        # Source A is missing city → CAST(NULL AS INT)
        a_by_name = {c["target_name"]: c["expression"] for c in padded[0]}
        assert a_by_name["city"] == "CAST(NULL AS INT)"
        # Mapped columns keep their real expression
        assert a_by_name["vat_number"] == "v"

    def test_label_and_sk_pads_use_string_macro(self):
        """_label and FK _sk pad columns use the portable dbt string macro."""
        assert _merge_pad_type("status_label", {}) == "{{ dbt.type_string() }}"
        assert _merge_pad_type("client_type_sk", {}) == "{{ dbt.type_string() }}"
        # Known datatype column uses its canonical type
        assert _merge_pad_type("vat_number", {"vat_number": "VARCHAR(50)"}) == "VARCHAR(50)"
        # Unknown plain column falls back to VARCHAR(255)
        assert _merge_pad_type("mystery", {}) == "VARCHAR(255)"

    def test_label_column_padded_when_only_one_source_has_enum(self):
        """A _label column present in one source is NULL-padded in the other."""
        src_a = [
            {"expression": "s", "target_name": "status"},
            {"expression": "case...", "target_name": "status_label"},
        ]
        src_b = [{"expression": "s2", "target_name": "status"}]
        _canonical, padded = _build_merge_superset(
            [src_a, src_b], [[], []], {"status": "VARCHAR(255)"}
        )
        b_by_name = {c["target_name"]: c["expression"] for c in padded[1]}
        assert b_by_name["status_label"] == "CAST(NULL AS {{ dbt.type_string() }})"


# ---------------------------------------------------------------------------
# Multi-source merge: per-source FK joins + union flow (issue #175)
# ---------------------------------------------------------------------------

MERGE_FK_ONTOLOGY_TTL = textwrap.dedent("""\
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
    @prefix ex:   <http://kairos.example/ontology/> .
    @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

    <http://kairos.example/ontology> a owl:Ontology ;
        rdfs:label "Merge FK" ; owl:versionInfo "1.0.0" .

    ex:Client a owl:Class ; rdfs:label "Client" ; rdfs:comment "c" ;
        kairos-ext:naturalKey "clientId" .
    ex:clientId a owl:DatatypeProperty ;
        rdfs:domain ex:Client ; rdfs:range xsd:string .
    ex:clientName a owl:DatatypeProperty ;
        rdfs:label "name" ; rdfs:comment "n" ;
        rdfs:domain ex:Client ; rdfs:range xsd:string .

    ex:ClientType a owl:Class ; rdfs:label "Client Type" ; rdfs:comment "ct" ;
        kairos-ext:naturalKey "typeCode" .
    ex:typeCode a owl:DatatypeProperty ;
        rdfs:domain ex:ClientType ; rdfs:range xsd:string .

    ex:hasType a owl:ObjectProperty ;
        rdfs:label "has type" ; rdfs:comment "ht" ;
        rdfs:domain ex:Client ; rdfs:range ex:ClientType ;
        kairos-ext:silverForeignKey "true" .
""")


class TestMergeFKPerSource:
    """Each per-source staging view is single-source, so FK joins resolve there
    and the _sk column flows through the union as a canonical column."""

    CLIENT_URI = "http://kairos.example/ontology/Client"

    @pytest.fixture
    def graph(self):
        g = Graph()
        g.parse(data=MERGE_FK_ONTOLOGY_TTL, format="turtle")
        return g

    @pytest.fixture
    def systems(self):
        ap = "https://example.com/bronze/ap#tblClient"
        crm = "https://example.com/bronze/crm#Customers"
        return [
            {
                "system_label": "ap",
                "tables": [
                    {
                        "uri": ap,
                        "name": "tblClient",
                        "columns": [
                            {"uri": f"{ap}_ClientID", "name": "ClientID", "data_type": "int"},
                            {"uri": f"{ap}_TypeCode", "name": "TypeCode", "data_type": "varchar"},
                        ],
                    }
                ],
            },
            {
                "system_label": "crm",
                "tables": [
                    {
                        "uri": crm,
                        "name": "Customers",
                        "columns": [
                            {"uri": f"{crm}_CustCode", "name": "CustCode", "data_type": "varchar"},
                        ],
                    }
                ],
            },
        ]

    def test_mapping_source_resolves_fk_join(self, graph, systems):
        """The source mapping the FK NK gets a real join + _sk column."""
        ap = "https://example.com/bronze/ap#tblClient"
        mappings = {
            "table_maps": {},
            "column_maps": {
                f"{ap}_TypeCode": [
                    {
                        "target_uri": "http://kairos.example/ontology/typeCode",
                        "transform": "source.TypeCode",
                        "match_type": "exactMatch",
                    }
                ],
            },
        }
        fk_columns, joins, warnings = _extract_fk_columns_and_joins(
            graph,
            self.CLIENT_URI,
            mappings,
            [("ap", "tblClient", ap)],
            systems=systems,
        )
        assert len(joins) == 1
        assert any(
            c["target_name"] == "client_type_sk" and "NULL" not in c["expression"]
            for c in fk_columns
        )

    def test_non_mapping_source_pads_null(self, graph, systems):
        """A source that does not map the FK NK emits a NULL placeholder, no join."""
        crm = "https://example.com/bronze/crm#Customers"
        mappings = {"table_maps": {}, "column_maps": {}}
        fk_columns, joins, warnings = _extract_fk_columns_and_joins(
            graph,
            self.CLIENT_URI,
            mappings,
            [("crm", "Customers", crm)],
            systems=systems,
        )
        assert len(joins) == 0
        assert all("NULL" in c["expression"] for c in fk_columns)
        assert any("client_type_sk" == c["target_name"] for c in fk_columns)

    def test_fk_sk_in_superset_from_one_source(self, graph, systems):
        """The FK _sk column is part of the canonical superset even if only one
        source resolves it — flows through the union, never silently dropped."""
        fk_a = [{"expression": "ref.client_type_sk", "target_name": "client_type_sk"}]
        fk_b = [{"expression": "CAST(NULL AS x)", "target_name": "client_type_sk"}]
        data_a = [{"expression": "id", "target_name": "client_id"}]
        data_b = [{"expression": "id2", "target_name": "client_id"}]
        canonical, padded = _build_merge_superset(
            [data_a, data_b], [fk_a, fk_b], {"client_id": "VARCHAR(255)"}
        )
        names = [c["target_name"] for c in canonical]
        assert "client_type_sk" in names
        # Both per-source views carry the FK column
        for cols in padded:
            assert any(c["target_name"] == "client_type_sk" for c in cols)


class TestMergeExplicitFKMappingScope:
    """Issue #178: an EXPLICIT FK column-mapping declared by one source must not
    leak into another source's per-source merge view (phantom join / columns).

    The projector is called once per source with the GLOBAL mappings dict, so the
    explicit-mapping branch must be scoped to the current source's columns."""

    CLIENT_URI = "http://kairos.example/ontology/Client"
    HAS_TYPE = "http://kairos.example/ontology/hasType"

    @pytest.fixture
    def graph(self):
        g = Graph()
        g.parse(data=MERGE_FK_ONTOLOGY_TTL, format="turtle")
        return g

    @pytest.fixture
    def systems(self):
        ap = "https://example.com/bronze/ap#tblClient"
        crm = "https://example.com/bronze/crm#Customers"
        return [
            {
                "system_label": "ap",
                "tables": [
                    {
                        "uri": ap,
                        "name": "tblClient",
                        "columns": [
                            {"uri": f"{ap}_ClientID", "name": "ClientID", "data_type": "int"},
                            {"uri": f"{ap}_TypeCode", "name": "TypeCode", "data_type": "varchar"},
                        ],
                    }
                ],
            },
            {
                "system_label": "crm",
                "tables": [
                    {
                        "uri": crm,
                        "name": "Customers",
                        "columns": [
                            {"uri": f"{crm}_CustCode", "name": "CustCode", "data_type": "varchar"},
                        ],
                    }
                ],
            },
        ]

    def _global_mappings(self):
        """GLOBAL mappings: ONLY source ap declares an explicit FK mapping."""
        ap = "https://example.com/bronze/ap#tblClient"
        return {
            "table_maps": {},
            "column_maps": {
                f"{ap}_TypeCode": [
                    {
                        "target_uri": self.HAS_TYPE,
                        "referenced_column_uris": (f"{ap}_TypeCode",),
                        "match_type": "exactMatch",
                    }
                ],
            },
        }

    def test_declaring_source_keeps_real_join(self, graph, systems):
        """Source ap (which declares the explicit FK mapping) keeps a real join."""
        ap = "https://example.com/bronze/ap#tblClient"
        fk_columns, joins, _ = _extract_fk_columns_and_joins(
            graph,
            self.CLIENT_URI,
            self._global_mappings(),
            [("ap", "tblClient", ap)],
            systems=systems,
        )
        assert len(joins) == 1
        assert any(
            c["target_name"] == "client_type_sk" and "NULL" not in c["expression"]
            for c in fk_columns
        )

    def test_non_declaring_source_does_not_leak(self, graph, systems):
        """Source crm (does NOT declare the FK) must NOT inherit ap's explicit
        mapping: no join, NULL placeholder, no reference to ap's TypeCode column."""
        crm = "https://example.com/bronze/crm#Customers"
        fk_columns, joins, _ = _extract_fk_columns_and_joins(
            graph,
            self.CLIENT_URI,
            self._global_mappings(),
            [("crm", "Customers", crm)],
            systems=systems,
        )
        assert len(joins) == 0
        type_cols = [c for c in fk_columns if c["target_name"] == "client_type_sk"]
        assert type_cols, "FK _sk column must still appear as a NULL pad"
        assert all("NULL" in c["expression"] for c in type_cols)
        assert all("TypeCode" not in c["expression"] for c in type_cols)

    def test_synthetic_subject_mapping_attributed_to_declaring_source(self, graph, systems):
        """A composite/synthetic-subject FK mapping (subject URI is not a declared
        bronze column) is attributed to the source whose physical columns it
        references — declaring source resolves, the other source does not leak."""
        ap = "https://example.com/bronze/ap#tblClient"
        crm = "https://example.com/bronze/crm#Customers"
        mappings = {
            "table_maps": {},
            "column_maps": {
                # Synthetic subject URI (not in any table's declared columns) but
                # references ap's physical TypeCode column.
                f"{ap}#synthetic_ClientType": [
                    {
                        "target_uri": self.HAS_TYPE,
                        "referenced_column_uris": (f"{ap}_TypeCode",),
                        "match_type": "exactMatch",
                    }
                ],
            },
        }
        # Declaring source (ap) attributes via physical-column fallback → join.
        _, joins_ap, _ = _extract_fk_columns_and_joins(
            graph,
            self.CLIENT_URI,
            mappings,
            [("ap", "tblClient", ap)],
            systems=systems,
        )
        assert len(joins_ap) == 1
        # Non-declaring source (crm) lacks TypeCode → no leak.
        fk_crm, joins_crm, _ = _extract_fk_columns_and_joins(
            graph,
            self.CLIENT_URI,
            mappings,
            [("crm", "Customers", crm)],
            systems=systems,
        )
        assert len(joins_crm) == 0
        assert all(
            "NULL" in c["expression"] for c in fk_crm if c["target_name"] == "client_type_sk"
        )


# ---------------------------------------------------------------------------
# Multi-source merge: natural-key coverage warning (issue #175)
# ---------------------------------------------------------------------------

_NK_ONTOLOGY_TTL = textwrap.dedent("""\
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
    @prefix ex:   <http://kairos.example/ontology/> .
    @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

    <http://kairos.example/ontology> a owl:Ontology ;
        rdfs:label "NK Coverage" ; owl:versionInfo "1.0.0" .

    ex:Client a owl:Class ; rdfs:label "Client" ; rdfs:comment "c" ;
        kairos-ext:naturalKey "clientId" .
    ex:clientId a owl:DatatypeProperty ;
        rdfs:label "client id" ; rdfs:comment "id" ;
        rdfs:domain ex:Client ; rdfs:range xsd:string .
    ex:clientName a owl:DatatypeProperty ;
        rdfs:label "client name" ; rdfs:comment "n" ;
        rdfs:domain ex:Client ; rdfs:range xsd:string .
""")

_NK_BRONZE_AP_TTL = textwrap.dedent("""\
    @prefix bronze-ap: <https://example.com/bronze/adminpulse#> .
    @prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .

    bronze-ap:AdminPulse a kairos-bronze:SourceSystem ; rdfs:label "AdminPulse" .
    bronze-ap:tblClient a kairos-bronze:SourceTable ;
        rdfs:label "tblClient" ;
        kairos-bronze:sourceSystem bronze-ap:AdminPulse ;
        kairos-bronze:tableName "tblClient" ;
        kairos-bronze:primaryKeyColumns "ClientID" .
    bronze-ap:tblClient_ClientID a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-ap:tblClient ;
        kairos-bronze:columnName "ClientID" ; kairos-bronze:dataType "int" .
    bronze-ap:tblClient_Name a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-ap:tblClient ;
        kairos-bronze:columnName "Name" ; kairos-bronze:dataType "nvarchar(255)" .
""")

_NK_BRONZE_CRM_TTL = textwrap.dedent("""\
    @prefix bronze-crm: <https://example.com/bronze/crm#> .
    @prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .

    bronze-crm:CrmSystem a kairos-bronze:SourceSystem ; rdfs:label "CrmSystem" .
    bronze-crm:Customers a kairos-bronze:SourceTable ;
        rdfs:label "Customers" ;
        kairos-bronze:sourceSystem bronze-crm:CrmSystem ;
        kairos-bronze:tableName "Customers" ;
        kairos-bronze:primaryKeyColumns "CustomerID" .
    bronze-crm:Customers_CustomerID a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-crm:Customers ;
        kairos-bronze:columnName "CustomerID" ;
        kairos-bronze:dataType "int" ;
        kairos-bronze:isPrimaryKey true .
    bronze-crm:Customers_CustName a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-crm:Customers ;
        kairos-bronze:columnName "CustName" ; kairos-bronze:dataType "nvarchar(255)" .
""")

# CRM maps clientName but NOT clientId (the natural key) → NK-coverage warning
_NK_MAPPING_TTL = textwrap.dedent("""\
    @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
    @prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
    @prefix map: <https://example.com/mapping/nk#> .
    @prefix bronze-ap: <https://example.com/bronze/adminpulse#> .
    @prefix bronze-crm: <https://example.com/bronze/crm#> .
    @prefix ex: <http://kairos.example/ontology/> .

    bronze-ap:tblClient skos:exactMatch ex:Client .
    bronze-ap:tblClient_ClientID skos:exactMatch ex:clientId .
    bronze-ap:tblClient_Name skos:exactMatch ex:clientName .

    bronze-crm:Customers skos:exactMatch ex:Client .
    bronze-crm:Customers_CustName skos:exactMatch ex:clientName .

    map:apTable a kairos-map:TableMapping ;
        kairos-map:sourceTable bronze-ap:tblClient ;
        kairos-map:targetClass ex:Client ;
        kairos-map:mappingType "direct" ;
        kairos-map:matchType "exactMatch" .
    map:crmTable a kairos-map:TableMapping ;
        kairos-map:sourceTable bronze-crm:Customers ;
        kairos-map:targetClass ex:Client ;
        kairos-map:mappingType "direct" ;
        kairos-map:matchType "exactMatch" .
    map:apId a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze-ap:tblClient_ClientID ;
        kairos-map:targetProperty ex:clientId ;
        kairos-map:matchType "exactMatch" .
    map:apName a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze-ap:tblClient_Name ;
        kairos-map:targetProperty ex:clientName ;
        kairos-map:matchType "exactMatch" .
    map:crmName a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze-crm:Customers_CustName ;
        kairos-map:targetProperty ex:clientName ;
        kairos-map:matchType "exactMatch" .
""")


class TestMergeNKCoverageWarning:
    """A source that does not map a natural-key column triggers a loud warning."""

    def test_missing_nk_in_one_source_keeps_branch_identities(
        self,
        tmp_path,
        template_dir,
        caplog,
    ):
        graph = Graph()
        graph.parse(data=_NK_ONTOLOGY_TTL, format="turtle")
        bronze = tmp_path / "bronze"
        bronze.mkdir()
        (bronze / "adminpulse.ttl").write_text(_NK_BRONZE_AP_TTL, encoding="utf-8")
        (bronze / "crm.ttl").write_text(_NK_BRONZE_CRM_TTL, encoding="utf-8")
        mappings = tmp_path / "mappings"
        mappings.mkdir()
        (mappings / "to-client.ttl").write_text(_NK_MAPPING_TTL, encoding="utf-8")

        classes = [
            {
                "uri": "http://kairos.example/ontology/Client",
                "name": "Client",
                "label": "Client",
                "comment": "c",
            }
        ]
        with caplog.at_level("WARNING"):
            artifacts = generate_dbt_artifacts(
                classes=classes,
                graph=graph,
                template_dir=template_dir,
                namespace="http://kairos.example/ontology/",
                ontology_name="client",
                bronze_dir=bronze,
                mappings_dir=mappings,
            )
        # Both per-source views generated → merge path was exercised
        assert any("corporate" not in k and "__from_" in k for k in artifacts)
        sql = next(value for key, value in artifacts.items() if key.endswith("/client.sql"))
        assert "_source_record_key" in sql
        assert "natural-key column" not in " ".join(
            record.getMessage() for record in caplog.records
        )


# ---------------------------------------------------------------------------
# Issue #179: table mapping to an unprojected class must not be silently dropped
# ---------------------------------------------------------------------------

_UNPROJECTED_ONTOLOGY_TTL = textwrap.dedent("""\
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
    @prefix ex:   <http://kairos.example/ontology/> .
    @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

    <http://kairos.example/ontology> a owl:Ontology ;
        rdfs:label "Unprojected" ; owl:versionInfo "1.0.0" .

    ex:Client a owl:Class ; rdfs:label "Client" ; rdfs:comment "c" ;
        kairos-ext:naturalKey "clientId" .
    ex:VipClient a owl:Class ; rdfs:label "Vip Client" ; rdfs:comment "v" ;
        rdfs:subClassOf ex:Client ;
        kairos-ext:naturalKey "clientId" .

    ex:clientId a owl:DatatypeProperty ;
        rdfs:label "client id" ; rdfs:comment "id" ;
        rdfs:domain ex:Client ; rdfs:range xsd:string .
    ex:clientName a owl:DatatypeProperty ;
        rdfs:label "client name" ; rdfs:comment "n" ;
        rdfs:domain ex:Client ; rdfs:range xsd:string .
""")

# Same as above but the parent uses the discriminator inheritance strategy, so the
# orphaned subtype's source folds onto the projected parent rather than warning.
_UNPROJECTED_DISCRIMINATOR_ONTOLOGY_TTL = _UNPROJECTED_ONTOLOGY_TTL.replace(
    'ex:Client a owl:Class ; rdfs:label "Client" ; rdfs:comment "c" ;\n'
    '    kairos-ext:naturalKey "clientId" .',
    'ex:Client a owl:Class ; rdfs:label "Client" ; rdfs:comment "c" ;\n'
    '    kairos-ext:naturalKey "clientId" ;\n'
    '    kairos-ext:inheritanceStrategy "discriminator" .',
)

_UNPROJECTED_BRONZE_TTL = textwrap.dedent("""\
    @prefix bronze-ap: <https://example.com/bronze/adminpulse#> .
    @prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

    bronze-ap:AdminPulse a kairos-bronze:SourceSystem ; rdfs:label "AdminPulse" .
    bronze-ap:tblVip a kairos-bronze:SourceTable ;
        rdfs:label "tblVip" ;
        kairos-bronze:sourceSystem bronze-ap:AdminPulse ;
        kairos-bronze:tableName "tblVip" ;
        kairos-bronze:primaryKeyColumns "VipID" .
    bronze-ap:tblVip_VipID a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-ap:tblVip ;
        kairos-bronze:columnName "VipID" ; kairos-bronze:dataType "int" .
    bronze-ap:tblVip_VipName a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-ap:tblVip ;
        kairos-bronze:columnName "VipName" ; kairos-bronze:dataType "nvarchar(255)" .
""")

_UNPROJECTED_MAPPING_TTL = textwrap.dedent("""\
    @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
    @prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
    @prefix map: <https://example.com/mapping/unprojected#> .
    @prefix bronze-ap: <https://example.com/bronze/adminpulse#> .
    @prefix ex: <http://kairos.example/ontology/> .

    bronze-ap:tblVip skos:exactMatch ex:VipClient .
    bronze-ap:tblVip_VipID skos:exactMatch ex:clientId .
    bronze-ap:tblVip_VipName skos:exactMatch ex:clientName .
    map:table a kairos-map:TableMapping ;
        kairos-map:sourceTable bronze-ap:tblVip ;
        kairos-map:targetClass ex:VipClient ;
        kairos-map:mappingType "direct" ;
        kairos-map:matchType "exactMatch" .
    map:id a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze-ap:tblVip_VipID ;
        kairos-map:targetProperty ex:clientId ;
        kairos-map:matchType "exactMatch" .
    map:name a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze-ap:tblVip_VipName ;
        kairos-map:targetProperty ex:clientName ;
        kairos-map:matchType "exactMatch" .
""")


class TestUnprojectedClassMapping:
    """Issue #179: a table mapping whose target class is not projected must surface
    a warning (never a silent drop), and fold onto a projected discriminator
    parent when one exists."""

    def _setup(self, tmp_path, ontology_ttl):
        graph = Graph()
        graph.parse(data=ontology_ttl, format="turtle")
        bronze = tmp_path / "bronze"
        bronze.mkdir()
        (bronze / "adminpulse.ttl").write_text(_UNPROJECTED_BRONZE_TTL, encoding="utf-8")
        mappings = tmp_path / "mappings"
        mappings.mkdir()
        (mappings / "to-client.ttl").write_text(_UNPROJECTED_MAPPING_TTL, encoding="utf-8")
        # Only the parent Client is projected; VipClient is unclaimed/unprojected.
        classes = [
            {
                "uri": "http://kairos.example/ontology/Client",
                "name": "Client",
                "label": "Client",
                "comment": "c",
            }
        ]
        return graph, bronze, mappings, classes

    def test_warns_when_no_projected_parent(self, tmp_path, template_dir, caplog):
        graph, bronze, mappings, classes = self._setup(tmp_path, _UNPROJECTED_ONTOLOGY_TTL)
        with caplog.at_level("WARNING"):
            artifacts = generate_dbt_artifacts(
                classes=classes,
                graph=graph,
                template_dir=template_dir,
                namespace="http://kairos.example/ontology/",
                ontology_name="client",
                bronze_dir=bronze,
                mappings_dir=mappings,
            )
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "VipClient" in msgs and "not" in msgs.lower(), (
            f"Expected a warning naming the unprojected class VipClient:\n{msgs}"
        )
        # No vip model and no rows folded into client (Client has no own mapping).
        assert not any("vip" in k.lower() for k in artifacts if k.startswith("models/silver/")), (
            f"Unprojected VipClient must not produce a model:\n{list(artifacts)}"
        )

    def test_folds_onto_projected_discriminator_parent(self, tmp_path, template_dir, caplog):
        graph, bronze, mappings, classes = self._setup(
            tmp_path, _UNPROJECTED_DISCRIMINATOR_ONTOLOGY_TTL
        )
        with caplog.at_level("WARNING"):
            artifacts = generate_dbt_artifacts(
                classes=classes,
                graph=graph,
                template_dir=template_dir,
                namespace="http://kairos.example/ontology/",
                ontology_name="client",
                bronze_dir=bronze,
                mappings_dir=mappings,
            )
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "folded" in msgs.lower() and "Client" in msgs, (
            f"Expected a fold warning mentioning the parent Client:\n{msgs}"
        )
        # The folded source (tblVip) drives the projected Client model.
        client_sql = "".join(
            v for k, v in artifacts.items() if k.endswith(".sql") and "client" in k.lower()
        )
        assert "tbl_vip" in client_sql.lower() or "tblvip" in client_sql.lower(), (
            f"Folded VipClient source (tblVip) missing from Client model:\n{client_sql}"
        )


# ---------------------------------------------------------------------------
# Issue #202: projected S3-folded subtype mappings must route to parent dbt model
# ---------------------------------------------------------------------------

_FOLDED_SUBTYPE_ONTOLOGY_TTL = textwrap.dedent("""\
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
    @prefix ex:   <http://kairos.example/ontology/booking/> .
    @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

    <http://kairos.example/ontology/booking> a owl:Ontology ;
        rdfs:label "Booking" ; owl:versionInfo "1.0.0" .

    ex:Booking a owl:Class ; rdfs:label "Booking" ; rdfs:comment "booking" ;
        kairos-ext:naturalKey "carrier_booking_reference" ;
        kairos-ext:inheritanceStrategy "discriminator" ;
        kairos-ext:discriminatorColumn "booking_type" .
    ex:BookingRequest a owl:Class ; rdfs:subClassOf ex:Booking ;
        rdfs:label "Booking Request" ; rdfs:comment "request" ;
        kairos-ext:conditionalOnType "request" .
    ex:ConfirmedBooking a owl:Class ; rdfs:subClassOf ex:Booking ;
        rdfs:label "Confirmed Booking" ; rdfs:comment "confirmed" .

    ex:carrierBookingReference a owl:DatatypeProperty ;
        rdfs:domain ex:Booking ; rdfs:range xsd:string ;
        kairos-ext:silverColumnName "carrier_booking_reference" .
    ex:confirmedAt a owl:DatatypeProperty ;
        rdfs:domain ex:ConfirmedBooking ; rdfs:range xsd:string ;
        kairos-ext:silverColumnName "confirmed_at" .
    ex:requestedAt a owl:DatatypeProperty ;
        rdfs:domain ex:BookingRequest ; rdfs:range xsd:string ;
        kairos-ext:silverColumnName "requested_at" .
""")

_FOLDED_SUBTYPE_BRONZE_TTL = textwrap.dedent("""\
    @prefix bronze-qargo: <https://example.com/bronze/qargo#> .
    @prefix bronze-qlik: <https://example.com/bronze/qlik#> .
    @prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

    bronze-qlik:Qlik a kairos-bronze:SourceSystem ;
        rdfs:label "Qlik" ;
        kairos-bronze:database "db" ;
        kairos-bronze:schema "dbo" .
    bronze-qlik:bookings a kairos-bronze:SourceTable ;
        rdfs:label "bookings" ;
        kairos-bronze:sourceSystem bronze-qlik:Qlik ;
        kairos-bronze:tableName "bookings" ;
        kairos-bronze:primaryKeyColumns "booking_ref" .
    bronze-qlik:bookings_booking_ref a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-qlik:bookings ;
        kairos-bronze:columnName "booking_ref" ;
        kairos-bronze:dataType "nvarchar(255)" .

    bronze-qargo:Qargo a kairos-bronze:SourceSystem ;
        rdfs:label "Qargo" ;
        kairos-bronze:database "db" ;
        kairos-bronze:schema "dbo" .
    bronze-qargo:bookings a kairos-bronze:SourceTable ;
        rdfs:label "bookings" ;
        kairos-bronze:sourceSystem bronze-qargo:Qargo ;
        kairos-bronze:tableName "bookings" ;
        kairos-bronze:primaryKeyColumns "booking_ref" .
    bronze-qargo:bookings_booking_ref a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-qargo:bookings ;
        kairos-bronze:columnName "booking_ref" ;
        kairos-bronze:dataType "nvarchar(255)" .
    bronze-qargo:bookings_confirmed_at a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-qargo:bookings ;
        kairos-bronze:columnName "confirmed_at" ;
        kairos-bronze:dataType "nvarchar(255)" .
    bronze-qargo:bookings_status a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-qargo:bookings ;
        kairos-bronze:columnName "status" ;
        kairos-bronze:dataType "nvarchar(30)" ;
        kairos-bronze:nullable false .

    bronze-qargo:orders a kairos-bronze:SourceTable ;
        rdfs:label "orders" ;
        kairos-bronze:sourceSystem bronze-qargo:Qargo ;
        kairos-bronze:tableName "orders" ;
        kairos-bronze:primaryKeyColumns "booking_ref" .
    bronze-qargo:orders_booking_ref a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-qargo:orders ;
        kairos-bronze:columnName "booking_ref" ;
        kairos-bronze:dataType "nvarchar(255)" .
    bronze-qargo:orders_requested_at a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-qargo:orders ;
        kairos-bronze:columnName "requested_at" ;
        kairos-bronze:dataType "nvarchar(255)" .
""")

_FOLDED_SUBTYPE_MAPPING_TTL = textwrap.dedent("""\
    @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
    @prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
    @prefix map: <https://example.com/mapping/folded#> .
    @prefix bronze-qargo: <https://example.com/bronze/qargo#> .
    @prefix bronze-qlik: <https://example.com/bronze/qlik#> .
    @prefix ex: <http://kairos.example/ontology/booking/> .

    bronze-qlik:bookings skos:exactMatch ex:Booking .
    bronze-qlik:bookings_booking_ref skos:exactMatch ex:carrierBookingReference .

    bronze-qargo:bookings skos:exactMatch ex:ConfirmedBooking .
    bronze-qargo:bookings_booking_ref skos:exactMatch ex:carrierBookingReference .
    bronze-qargo:bookings_confirmed_at skos:exactMatch ex:confirmedAt .

    bronze-qargo:orders skos:exactMatch ex:BookingRequest .
    bronze-qargo:orders_booking_ref skos:exactMatch ex:carrierBookingReference .
    bronze-qargo:orders_requested_at skos:exactMatch ex:requestedAt .

    map:qlik a kairos-map:TableMapping ;
        kairos-map:sourceTable bronze-qlik:bookings ;
        kairos-map:targetClass ex:Booking ;
        kairos-map:mappingType "direct" ;
        kairos-map:matchType "exactMatch" .
    map:qargoBooking a kairos-map:TableMapping ;
        kairos-map:sourceTable bronze-qargo:bookings ;
        kairos-map:targetClass ex:ConfirmedBooking ;
        kairos-map:mappingType "split" ;
        kairos-map:matchType "exactMatch" ;
        kairos-map:rowFilter map:confirmedFilter .
    map:qargoOrder a kairos-map:TableMapping ;
        kairos-map:sourceTable bronze-qargo:orders ;
        kairos-map:targetClass ex:BookingRequest ;
        kairos-map:mappingType "direct" ;
        kairos-map:matchType "exactMatch" .
    map:qlikRef a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze-qlik:bookings_booking_ref ;
        kairos-map:targetProperty ex:carrierBookingReference ;
        kairos-map:matchType "exactMatch" .
    map:qargoRef a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze-qargo:bookings_booking_ref ;
        kairos-map:targetProperty ex:carrierBookingReference ;
        kairos-map:matchType "exactMatch" .
    map:confirmedAt a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze-qargo:bookings_confirmed_at ;
        kairos-map:targetProperty ex:confirmedAt ;
        kairos-map:matchType "exactMatch" .
    map:orderRef a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze-qargo:orders_booking_ref ;
        kairos-map:targetProperty ex:carrierBookingReference ;
        kairos-map:matchType "exactMatch" .
    map:requestedAt a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze-qargo:orders_requested_at ;
        kairos-map:targetProperty ex:requestedAt ;
        kairos-map:matchType "exactMatch" .
    map:confirmedFilter a kairos-map:OperatorExpression ;
        kairos-map:operator "equal" ;
        kairos-map:arguments ( map:statusInput map:confirmedLiteral ) ;
        kairos-map:outputType "boolean" ;
        kairos-map:nullable false ;
        kairos-map:nullPolicy "three-valued" ;
        kairos-map:determinism "deterministic" ;
        kairos-map:requiresCapability "scalar-operator" .
    map:statusInput a kairos-map:SourceColumnExpression ;
        kairos-map:sourceColumn bronze-qargo:bookings_status ;
        kairos-map:outputType "string" ;
        kairos-map:nullable false ;
        kairos-map:nullPolicy "propagate" ;
        kairos-map:determinism "deterministic" ;
        kairos-map:requiresCapability "source-column" .
    map:confirmedLiteral a kairos-map:LiteralExpression ;
        kairos-map:literalValue "confirmed" ;
        kairos-map:outputType "string" ;
        kairos-map:nullable false ;
        kairos-map:nullPolicy "never-null" ;
        kairos-map:determinism "deterministic" ;
        kairos-map:requiresCapability "typed-literal" .
""")


class TestProjectedFoldedSubtypeMappings:
    """Issue #202: projected S3-folded subtype mappings feed the parent dbt model."""

    def _setup(
        self,
        tmp_path,
        ontology_ttl: str = _FOLDED_SUBTYPE_ONTOLOGY_TTL,
        mapping_ttl: str = _FOLDED_SUBTYPE_MAPPING_TTL,
        classes: list[dict] | None = None,
    ):
        graph = Graph()
        graph.parse(data=ontology_ttl, format="turtle")
        bronze = tmp_path / "bronze"
        bronze.mkdir()
        (bronze / "sources.ttl").write_text(_FOLDED_SUBTYPE_BRONZE_TTL, encoding="utf-8")
        mappings = tmp_path / "mappings"
        mappings.mkdir()
        (mappings / "to-booking.ttl").write_text(mapping_ttl, encoding="utf-8")
        if classes is None:
            classes = [
                {
                    "uri": "http://kairos.example/ontology/booking/Booking",
                    "name": "Booking",
                    "label": "Booking",
                    "comment": "booking",
                },
                {
                    "uri": "http://kairos.example/ontology/booking/ConfirmedBooking",
                    "name": "ConfirmedBooking",
                    "label": "Confirmed Booking",
                    "comment": "confirmed",
                },
                {
                    "uri": "http://kairos.example/ontology/booking/BookingRequest",
                    "name": "BookingRequest",
                    "label": "Booking Request",
                    "comment": "request",
                },
            ]
        return graph, bronze, mappings, classes

    def test_projected_folded_subtype_mappings_route_to_parent_union(self, tmp_path, template_dir):
        graph, bronze, mappings, classes = self._setup(tmp_path)
        artifacts = generate_dbt_artifacts(
            classes=classes,
            graph=graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/booking/",
            ontology_name="booking",
            bronze_dir=bronze,
            mappings_dir=mappings,
        )

        assert "models/silver/booking/booking.sql" in artifacts
        assert "models/silver/booking/booking__from_qlik.sql" in artifacts
        assert "models/silver/booking/booking__from_qargo__bookings.sql" in artifacts
        assert "models/silver/booking/booking__from_qargo__orders.sql" in artifacts
        assert "models/silver/booking/confirmed_booking.sql" not in artifacts
        assert "models/silver/booking/booking_request.sql" not in artifacts

    def test_folded_subtype_sources_preserve_discriminator_columns(self, tmp_path, template_dir):
        graph, bronze, mappings, classes = self._setup(tmp_path)
        artifacts = generate_dbt_artifacts(
            classes=classes,
            graph=graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/booking/",
            ontology_name="booking",
            bronze_dir=bronze,
            mappings_dir=mappings,
        )

        confirmed_sql = artifacts["models/silver/booking/booking__from_qargo__bookings.sql"]
        request_sql = artifacts["models/silver/booking/booking__from_qargo__orders.sql"]
        assert "'ConfirmedBooking' as booking_type" in confirmed_sql
        assert (
            "where ([bookings].[status] = CONVERT(VARCHAR(8000), 0x636F6E6669726D6564))"
            in confirmed_sql
        )
        assert "'request' as booking_type" in request_sql

    def test_folded_subtype_specific_columns_survive_parent_union(self, tmp_path, template_dir):
        graph, bronze, mappings, classes = self._setup(tmp_path)
        artifacts = generate_dbt_artifacts(
            classes=classes,
            graph=graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/booking/",
            ontology_name="booking",
            bronze_dir=bronze,
            mappings_dir=mappings,
        )

        confirmed_sql = artifacts["models/silver/booking/booking__from_qargo__bookings.sql"]
        request_sql = artifacts["models/silver/booking/booking__from_qargo__orders.sql"]
        union_sql = artifacts["models/silver/booking/booking.sql"]
        schema_yml = yaml.safe_load(artifacts["models/silver/booking/_booking__models.yml"])
        booking_model = next(m for m in schema_yml["models"] if m["name"] == "booking")
        schema_columns = {c["name"] for c in booking_model["columns"]}
        assert "[bookings].[confirmed_at] as confirmed_at" in confirmed_sql
        assert "[orders].[requested_at] as requested_at" in request_sql
        assert "confirmed_at" in union_sql
        assert "requested_at" in union_sql
        assert {"booking_type", "confirmed_at", "requested_at"} <= schema_columns

    def test_single_source_folded_subtype_generates_parent_model(self, tmp_path, template_dir):
        single_mapping = textwrap.dedent("""\
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
            @prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
            @prefix map: <https://example.com/mapping/single-folded#> .
            @prefix bronze-qargo: <https://example.com/bronze/qargo#> .
            @prefix ex: <http://kairos.example/ontology/booking/> .

            bronze-qargo:bookings skos:exactMatch ex:ConfirmedBooking .
            bronze-qargo:bookings_booking_ref skos:exactMatch ex:carrierBookingReference .
            bronze-qargo:bookings_confirmed_at skos:exactMatch ex:confirmedAt .
            map:table a kairos-map:TableMapping ;
                kairos-map:sourceTable bronze-qargo:bookings ;
                kairos-map:targetClass ex:ConfirmedBooking ;
                kairos-map:mappingType "split" ;
                kairos-map:matchType "exactMatch" ;
                kairos-map:rowFilter map:filter .
            map:reference a kairos-map:ColumnMapping ;
                kairos-map:sourceColumn bronze-qargo:bookings_booking_ref ;
                kairos-map:targetProperty ex:carrierBookingReference ;
                kairos-map:matchType "exactMatch" .
            map:confirmedAt a kairos-map:ColumnMapping ;
                kairos-map:sourceColumn bronze-qargo:bookings_confirmed_at ;
                kairos-map:targetProperty ex:confirmedAt ;
                kairos-map:matchType "exactMatch" .
            map:filter a kairos-map:OperatorExpression ;
                kairos-map:operator "equal" ;
                kairos-map:arguments ( map:status map:confirmed ) ;
                kairos-map:outputType "boolean" ;
                kairos-map:nullable false ;
                kairos-map:nullPolicy "three-valued" ;
                kairos-map:determinism "deterministic" ;
                kairos-map:requiresCapability "scalar-operator" .
            map:status a kairos-map:SourceColumnExpression ;
                kairos-map:sourceColumn bronze-qargo:bookings_status ;
                kairos-map:outputType "string" ;
                kairos-map:nullable false ;
                kairos-map:nullPolicy "propagate" ;
                kairos-map:determinism "deterministic" ;
                kairos-map:requiresCapability "source-column" .
            map:confirmed a kairos-map:LiteralExpression ;
                kairos-map:literalValue "confirmed" ;
                kairos-map:outputType "string" ;
                kairos-map:nullable false ;
                kairos-map:nullPolicy "never-null" ;
                kairos-map:determinism "deterministic" ;
                kairos-map:requiresCapability "typed-literal" .
        """)
        graph, bronze, mappings, classes = self._setup(tmp_path, mapping_ttl=single_mapping)
        artifacts = generate_dbt_artifacts(
            classes=classes,
            graph=graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/booking/",
            ontology_name="booking",
            bronze_dir=bronze,
            mappings_dir=mappings,
        )

        assert "models/silver/booking/booking.sql" in artifacts
        assert "models/silver/booking/confirmed_booking.sql" not in artifacts
        booking_sql = artifacts["models/silver/booking/booking.sql"]
        assert "'ConfirmedBooking' as booking_type" in booking_sql
        assert "confirmed_at" in booking_sql
        assert (
            "where ([bookings].[status] = CONVERT(VARCHAR(8000), 0x636F6E6669726D6564))"
            in booking_sql
        )

    def test_transitive_folded_subtype_mapping_routes_to_parent(self, tmp_path, template_dir):
        transitive_ontology = _FOLDED_SUBTYPE_ONTOLOGY_TTL.replace(
            "ex:ConfirmedBooking a owl:Class ; rdfs:subClassOf ex:Booking ;",
            "ex:BookedProduct a owl:Class ; rdfs:subClassOf ex:Booking ;\n"
            '        rdfs:label "Booked Product" ; rdfs:comment "intermediate" .\n'
            "    ex:ConfirmedBooking a owl:Class ; rdfs:subClassOf ex:BookedProduct ;",
        )
        graph, bronze, mappings, classes = self._setup(
            tmp_path,
            ontology_ttl=transitive_ontology,
        )
        artifacts = generate_dbt_artifacts(
            classes=classes,
            graph=graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/booking/",
            ontology_name="booking",
            bronze_dir=bronze,
            mappings_dir=mappings,
        )

        assert "models/silver/booking/booking__from_qargo__bookings.sql" in artifacts
        assert "models/silver/booking/confirmed_booking.sql" not in artifacts

    def test_class_per_table_subtype_mapping_stays_separate(self, tmp_path, template_dir):
        cpt_ontology = _FOLDED_SUBTYPE_ONTOLOGY_TTL.replace(
            'kairos-ext:inheritanceStrategy "discriminator" ;',
            'kairos-ext:inheritanceStrategy "class-per-table" ;',
        )
        cpt_ontology += """
            ex:ConfirmedBooking kairos-ext:naturalKey "carrier_booking_reference" .
            ex:BookingRequest kairos-ext:naturalKey "carrier_booking_reference" .
        """
        graph, bronze, mappings, classes = self._setup(
            tmp_path,
            ontology_ttl=cpt_ontology,
        )
        artifacts = generate_dbt_artifacts(
            classes=classes,
            graph=graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/booking/",
            ontology_name="booking",
            bronze_dir=bronze,
            mappings_dir=mappings,
        )

        assert "models/silver/booking/confirmed_booking.sql" in artifacts
        assert "models/silver/booking/booking_request.sql" in artifacts


# ---------------------------------------------------------------------------
# Characterization coverage for the fact-extraction refactor
# (medallion_dbt_projector: _extract_silver_model_facts /
# _extract_schema_model_facts decomposition). These pin ordering behaviour
# that is not already covered elsewhere, ahead of moving the corresponding
# code into smaller helpers.
# ---------------------------------------------------------------------------

_MISSING_MAPPING_ONTOLOGY_TTL = textwrap.dedent("""\
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
    @prefix ex:   <http://kairos.example/ontology/gap/> .

    <http://kairos.example/ontology/gap> a owl:Ontology ;
        rdfs:label "Gap" ; owl:versionInfo "1.0.0" .

    ex:Alpha a owl:Class ; rdfs:label "Alpha" ; rdfs:comment "alpha, unmapped" .
    ex:Bravo a owl:Class ; rdfs:label "Bravo" ; rdfs:comment "bravo, unmapped" .
    ex:Charlie a owl:Class ; rdfs:label "Charlie" ; rdfs:comment "charlie, unmapped" .
""")


class TestExtractionCharacterization:
    """Pins ordering facts the fact-extraction refactor must preserve exactly."""

    def test_multi_source_model_emission_order_stable(self, tmp_path, template_dir):
        """Per-source staging models are emitted before the union model, in the
        same order as ``source_refs`` (qlik, then qargo bookings, then qargo
        orders) — the exact emission order ``_extract_silver_model_facts``
        currently produces via its inline multi-source branch."""
        graph = Graph()
        graph.parse(data=_FOLDED_SUBTYPE_ONTOLOGY_TTL, format="turtle")
        bronze = tmp_path / "bronze"
        bronze.mkdir()
        (bronze / "sources.ttl").write_text(_FOLDED_SUBTYPE_BRONZE_TTL, encoding="utf-8")
        mappings = tmp_path / "mappings"
        mappings.mkdir()
        (mappings / "to-booking.ttl").write_text(_FOLDED_SUBTYPE_MAPPING_TTL, encoding="utf-8")
        classes = [
            {
                "uri": "http://kairos.example/ontology/booking/Booking",
                "name": "Booking",
                "label": "Booking",
                "comment": "booking",
            },
            {
                "uri": "http://kairos.example/ontology/booking/ConfirmedBooking",
                "name": "ConfirmedBooking",
                "label": "Confirmed Booking",
                "comment": "confirmed",
            },
            {
                "uri": "http://kairos.example/ontology/booking/BookingRequest",
                "name": "BookingRequest",
                "label": "Booking Request",
                "comment": "request",
            },
        ]
        artifacts = generate_dbt_artifacts(
            classes=classes,
            graph=graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/booking/",
            ontology_name="booking",
            bronze_dir=bronze,
            mappings_dir=mappings,
        )
        silver_sql_keys = [
            key
            for key in artifacts
            if key.startswith("models/silver/booking/") and key.endswith(".sql")
        ]
        expected_order = [
            "models/silver/booking/booking__from_qlik.sql",
            "models/silver/booking/booking__from_qargo__bookings.sql",
            "models/silver/booking/booking__from_qargo__orders.sql",
            "models/silver/booking/booking.sql",
        ]
        assert silver_sql_keys == expected_order, (
            f"Multi-source emission order changed:\n{silver_sql_keys}"
        )

    def test_missing_mapping_warning_order_matches_class_iteration_order(
        self, tmp_path, template_dir, caplog
    ):
        """Classes with no bronze mapping warn in the same order they appear
        in the ``classes`` input list — pinning the parent loop's append
        order ahead of any per-class decision extraction."""
        graph = Graph()
        graph.parse(data=_MISSING_MAPPING_ONTOLOGY_TTL, format="turtle")
        classes = [
            {
                "uri": "http://kairos.example/ontology/gap/Alpha",
                "name": "Alpha",
                "label": "Alpha",
                "comment": "alpha",
            },
            {
                "uri": "http://kairos.example/ontology/gap/Bravo",
                "name": "Bravo",
                "label": "Bravo",
                "comment": "bravo",
            },
            {
                "uri": "http://kairos.example/ontology/gap/Charlie",
                "name": "Charlie",
                "label": "Charlie",
                "comment": "charlie",
            },
        ]
        with caplog.at_level("WARNING"):
            generate_dbt_artifacts(
                classes=classes,
                graph=graph,
                template_dir=template_dir,
                namespace="http://kairos.example/ontology/gap/",
                ontology_name="gap",
            )
        skip_messages = [
            r.getMessage() for r in caplog.records if "No bronze mapping" in r.getMessage()
        ]
        skipped_names = [m.split("'")[1] for m in skip_messages]
        # The extraction runs once for artifact generation and once for coverage
        # data (generate_coverage_data reuses the same class-iteration warning
        # path), so the current behaviour is exactly two full passes over the
        # three classes, in class-iteration order, back to back.
        assert skipped_names == [
            "Alpha",
            "Bravo",
            "Charlie",
            "Alpha",
            "Bravo",
            "Charlie",
        ], f"Missing-mapping warning sequence changed:\n{skipped_names}"

    def test_single_source_folded_subtype_schema_column_order(self, tmp_path, template_dir):
        """The folded discriminator column precedes the folded-subtype's own
        datatype columns in the generated schema YAML, matching the current
        single-source assembly + SHACL-merge column ordering."""
        single_mapping = textwrap.dedent("""\
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
            @prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
            @prefix map: <https://example.com/mapping/single-folded-order#> .
            @prefix bronze-qargo: <https://example.com/bronze/qargo#> .
            @prefix ex: <http://kairos.example/ontology/booking/> .

            bronze-qargo:bookings skos:exactMatch ex:ConfirmedBooking .
            bronze-qargo:bookings_booking_ref skos:exactMatch ex:carrierBookingReference .
            bronze-qargo:bookings_confirmed_at skos:exactMatch ex:confirmedAt .
            map:table a kairos-map:TableMapping ;
                kairos-map:sourceTable bronze-qargo:bookings ;
                kairos-map:targetClass ex:ConfirmedBooking ;
                kairos-map:mappingType "direct" ;
                kairos-map:matchType "exactMatch" .
            map:reference a kairos-map:ColumnMapping ;
                kairos-map:sourceColumn bronze-qargo:bookings_booking_ref ;
                kairos-map:targetProperty ex:carrierBookingReference ;
                kairos-map:matchType "exactMatch" .
            map:confirmedAt a kairos-map:ColumnMapping ;
                kairos-map:sourceColumn bronze-qargo:bookings_confirmed_at ;
                kairos-map:targetProperty ex:confirmedAt ;
                kairos-map:matchType "exactMatch" .
        """)
        graph = Graph()
        graph.parse(data=_FOLDED_SUBTYPE_ONTOLOGY_TTL, format="turtle")
        bronze = tmp_path / "bronze"
        bronze.mkdir()
        (bronze / "sources.ttl").write_text(_FOLDED_SUBTYPE_BRONZE_TTL, encoding="utf-8")
        mappings = tmp_path / "mappings"
        mappings.mkdir()
        (mappings / "to-booking.ttl").write_text(single_mapping, encoding="utf-8")
        classes = [
            {
                "uri": "http://kairos.example/ontology/booking/Booking",
                "name": "Booking",
                "label": "Booking",
                "comment": "booking",
            },
            {
                "uri": "http://kairos.example/ontology/booking/ConfirmedBooking",
                "name": "ConfirmedBooking",
                "label": "Confirmed Booking",
                "comment": "confirmed",
            },
            {
                "uri": "http://kairos.example/ontology/booking/BookingRequest",
                "name": "BookingRequest",
                "label": "Booking Request",
                "comment": "request",
            },
        ]
        artifacts = generate_dbt_artifacts(
            classes=classes,
            graph=graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/booking/",
            ontology_name="booking",
            bronze_dir=bronze,
            mappings_dir=mappings,
        )
        schema_yml = yaml.safe_load(artifacts["models/silver/booking/_booking__models.yml"])
        booking_model = next(m for m in schema_yml["models"] if m["name"] == "booking")
        column_names = [c["name"] for c in booking_model["columns"]]
        assert column_names == [
            "booking_sk",
            "carrier_booking_reference",
            "confirmed_at",
            "booking_type",
            "_source_system",
            "_source_record_key",
            "_loaded_at",
        ], f"Schema column order changed:\n{column_names}"


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
    @prefix map: <https://example.com/mapping/split#> .
    @prefix bronze-ap: <https://example.com/bronze/adminpulse#> .
    @prefix ex: <http://kairos.example/ontology/> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

    bronze-ap:tblClient skos:exactMatch ex:CorporateClient,
                                               ex:SoleProprietorClient,
                                               ex:IndividualClient .
    bronze-ap:tblClient_ClientID skos:exactMatch ex:clientId .

    map:corporate a kairos-map:TableMapping ;
        kairos-map:sourceTable bronze-ap:tblClient ;
        kairos-map:targetClass ex:CorporateClient ;
        kairos-map:mappingType "split" ;
        kairos-map:matchType "exactMatch" ;
        kairos-map:rowFilter map:isCorporate .
    map:sole a kairos-map:TableMapping ;
        kairos-map:sourceTable bronze-ap:tblClient ;
        kairos-map:targetClass ex:SoleProprietorClient ;
        kairos-map:mappingType "split" ;
        kairos-map:matchType "exactMatch" ;
        kairos-map:rowFilter map:isSole .
    map:individual a kairos-map:TableMapping ;
        kairos-map:sourceTable bronze-ap:tblClient ;
        kairos-map:targetClass ex:IndividualClient ;
        kairos-map:mappingType "split" ;
        kairos-map:matchType "exactMatch" ;
        kairos-map:rowFilter map:isIndividual .
    map:clientId a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze-ap:tblClient_ClientID ;
        kairos-map:targetProperty ex:clientId ;
        kairos-map:matchType "exactMatch" .

    map:typeInput a kairos-map:SourceColumnExpression ;
        kairos-map:sourceColumn bronze-ap:tblClient_type ;
        kairos-map:outputType "int32" ;
        kairos-map:nullable false ;
        kairos-map:nullPolicy "propagate" ;
        kairos-map:determinism "deterministic" ;
        kairos-map:requiresCapability "source-column" .
    map:zero a kairos-map:LiteralExpression ;
        kairos-map:literalValue "0"^^xsd:int ;
        kairos-map:outputType "int32" ;
        kairos-map:nullable false ;
        kairos-map:nullPolicy "never-null" ;
        kairos-map:determinism "deterministic" ;
        kairos-map:requiresCapability "typed-literal" .
    map:one a kairos-map:LiteralExpression ;
        kairos-map:literalValue "1"^^xsd:int ;
        kairos-map:outputType "int32" ;
        kairos-map:nullable false ;
        kairos-map:nullPolicy "never-null" ;
        kairos-map:determinism "deterministic" ;
        kairos-map:requiresCapability "typed-literal" .
    map:two a kairos-map:LiteralExpression ;
        kairos-map:literalValue "2"^^xsd:int ;
        kairos-map:outputType "int32" ;
        kairos-map:nullable false ;
        kairos-map:nullPolicy "never-null" ;
        kairos-map:determinism "deterministic" ;
        kairos-map:requiresCapability "typed-literal" .
    map:isCorporate a kairos-map:OperatorExpression ;
        kairos-map:operator "equal" ;
        kairos-map:arguments ( map:typeInput map:zero ) ;
        kairos-map:outputType "boolean" ;
        kairos-map:nullable false ;
        kairos-map:nullPolicy "three-valued" ;
        kairos-map:determinism "deterministic" ;
        kairos-map:requiresCapability "scalar-operator" .
    map:isSole a kairos-map:OperatorExpression ;
        kairos-map:operator "equal" ;
        kairos-map:arguments ( map:typeInput map:one ) ;
        kairos-map:outputType "boolean" ;
        kairos-map:nullable false ;
        kairos-map:nullPolicy "three-valued" ;
        kairos-map:determinism "deterministic" ;
        kairos-map:requiresCapability "scalar-operator" .
    map:isIndividual a kairos-map:OperatorExpression ;
        kairos-map:operator "equal" ;
        kairos-map:arguments ( map:typeInput map:two ) ;
        kairos-map:outputType "boolean" ;
        kairos-map:nullable false ;
        kairos-map:nullPolicy "three-valued" ;
        kairos-map:determinism "deterministic" ;
        kairos-map:requiresCapability "scalar-operator" .
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
        (d / "adminpulse.vocabulary.ttl").write_text(SPLIT_BRONZE_TTL, encoding="utf-8")
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
            {
                "uri": "http://kairos.example/ontology/CorporateClient",
                "name": "CorporateClient",
                "label": "Corporate Client",
                "comment": "Corporate entity",
            },
            {
                "uri": "http://kairos.example/ontology/SoleProprietorClient",
                "name": "SoleProprietorClient",
                "label": "Sole Proprietor Client",
                "comment": "Sole proprietor entity",
            },
            {
                "uri": "http://kairos.example/ontology/IndividualClient",
                "name": "IndividualClient",
                "label": "Individual Client",
                "comment": "Individual entity",
            },
        ]

    def test_each_split_model_has_correct_filter(
        self,
        split_classes,
        split_graph,
        template_dir,
        split_bronze_dir,
        split_mappings_dir,
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

        # Corporate discriminator = 0
        corp_key = next(k for k in artifacts if "corporate_client.sql" in k)
        assert "[tbl_client].[type] = 0" in artifacts[corp_key]

        # Sole proprietor → type = 1
        sole_key = next(k for k in artifacts if "sole_proprietor_client.sql" in k)
        assert "[tbl_client].[type] = 1" in artifacts[sole_key]

        # Individual → type = 2
        indiv_key = next(k for k in artifacts if "individual_client.sql" in k)
        assert "[tbl_client].[type] = 2" in artifacts[indiv_key]

    def test_split_models_do_not_share_filter(
        self,
        split_classes,
        split_graph,
        template_dir,
        split_bronze_dir,
        split_mappings_dir,
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
        # Should NOT have the corporate discriminator.
        assert "[tbl_client].[type] = 0" not in content
        assert "[tbl_client].[type] = 1" in content


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
    @prefix map: <https://example.com/mapping/account#> .

    bronze-ap:tblAccount skos:exactMatch ex:Account .
    bronze-ap:tblAccount_Code skos:exactMatch ex:accountCode .
    map:table a kairos-map:TableMapping ;
        kairos-map:sourceTable bronze-ap:tblAccount ;
        kairos-map:targetClass ex:Account ;
        kairos-map:mappingType "direct" ;
        kairos-map:matchType "exactMatch" .
    map:code a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze-ap:tblAccount_Code ;
        kairos-map:targetProperty ex:accountCode ;
        kairos-map:matchType "exactMatch" .
""")

NK_MAPPING_WIDGET_TTL = textwrap.dedent("""\
    @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
    @prefix bronze-ap: <https://example.com/bronze/adminpulse#> .
    @prefix ex: <http://kairos.example/ontology/> .
    @prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
    @prefix map: <https://example.com/mapping/widget#> .

    bronze-ap:tblWidget skos:exactMatch ex:Widget .
    bronze-ap:tblWidget_Code skos:exactMatch ex:widgetCode .
    map:table a kairos-map:TableMapping ;
        kairos-map:sourceTable bronze-ap:tblWidget ;
        kairos-map:targetClass ex:Widget ;
        kairos-map:mappingType "direct" ;
        kairos-map:matchType "exactMatch" .
    map:code a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze-ap:tblWidget_Code ;
        kairos-map:targetProperty ex:widgetCode ;
        kairos-map:matchType "exactMatch" .
""")

NK_ONTOLOGY_FK_CHILD_TTL = textwrap.dedent("""\
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
    @prefix ex:   <http://kairos.example/ontology/> .
    @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

    <http://kairos.example/ontology> a owl:Ontology ;
        rdfs:label "NK Test Ontology" ;
        owl:versionInfo "1.0.0" .

    ex:Gadget a owl:Class ;
        rdfs:label "Gadget" ;
        rdfs:comment "A parent entity" ;
        kairos-ext:naturalKey "gadgetCode" .

    ex:Widget a owl:Class ;
        rdfs:label "Widget" ;
        rdfs:comment "A widget entity (FK-child, no naturalKey)" .

    ex:widgetCode a owl:DatatypeProperty ;
        rdfs:label "widget code" ;
        rdfs:domain ex:Widget ;
        rdfs:range xsd:string .

    ex:hasWidget a owl:ObjectProperty ;
        rdfs:label "has widget" ;
        rdfs:domain ex:Gadget ;
        rdfs:range ex:Widget ;
        kairos-ext:silverForeignKeyOn ex:Widget .
""")


class TestNaturalKeyWarning:
    """Tests that missing kairos-ext:naturalKey emits a warning."""

    @pytest.fixture
    def nk_sources_dir(self, tmp_path):
        d = tmp_path / "sources" / "adminpulse"
        d.mkdir(parents=True)
        (d / "adminpulse.vocabulary.ttl").write_text(NK_BRONZE_TTL, encoding="utf-8")
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
        self,
        template_dir,
        nk_sources_dir,
        nk_mappings_account,
        caplog,
    ):
        """Class WITH naturalKey annotation should NOT produce a warning."""
        g = Graph()
        g.parse(data=NK_ONTOLOGY_WITH_KEY_TTL, format="turtle")
        classes = [
            {
                "uri": "http://kairos.example/ontology/Account",
                "name": "Account",
                "label": "Account",
                "comment": "An account entity",
            }
        ]

        with caplog.at_level(
            logging.WARNING, logger="kairos_ontology.core.projections.medallion_dbt_projector"
        ):
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

    def test_bound_model_without_natural_key_uses_source_scoped_join_key(
        self,
        template_dir,
        nk_sources_dir,
        nk_mappings_widget,
        caplog,
    ):
        """A physical join key does not require an invented business natural key."""
        g = Graph()
        g.parse(data=NK_ONTOLOGY_WITHOUT_KEY_TTL, format="turtle")
        classes = [
            {
                "uri": "http://kairos.example/ontology/Widget",
                "name": "Widget",
                "label": "Widget",
                "comment": "A widget entity",
            }
        ]

        artifacts = generate_dbt_artifacts(
            classes=classes,
            graph=g,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="widget",
            sources_dir=nk_sources_dir,
            mappings_dir=nk_mappings_widget,
        )
        sql = next(value for key, value in artifacts.items() if key.endswith("/widget.sql"))
        assert "_source_record_key" in sql
        assert "widget_iri" not in sql

    def test_missing_natural_key_does_not_invent_business_identity(
        self,
        template_dir,
        nk_sources_dir,
        nk_mappings_widget,
    ):
        g = Graph()
        g.parse(data=NK_ONTOLOGY_WITHOUT_KEY_TTL, format="turtle")
        classes = [
            {
                "uri": "http://kairos.example/ontology/Widget",
                "name": "Widget",
                "label": "Widget",
                "comment": "A widget entity",
            }
        ]

        artifacts = generate_dbt_artifacts(
            classes=classes,
            graph=g,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="widget",
            sources_dir=nk_sources_dir,
            mappings_dir=nk_mappings_widget,
        )
        release = artifacts["__release_data__"]
        assert any(item["rule_id"] == "DD-108-identity" for item in release["blocking_reasons"])

    def test_fk_child_without_natural_key_keeps_source_identity(
        self,
        template_dir,
        nk_sources_dir,
        nk_mappings_widget,
    ):
        """Weak entities no longer force an invented natural key."""
        g = Graph()
        g.parse(data=NK_ONTOLOGY_FK_CHILD_TTL, format="turtle")
        classes = [
            {
                "uri": "http://kairos.example/ontology/Widget",
                "name": "Widget",
                "label": "Widget",
                "comment": "A widget entity",
            }
        ]

        artifacts = generate_dbt_artifacts(
            classes=classes,
            graph=g,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="widget",
            sources_dir=nk_sources_dir,
            mappings_dir=nk_mappings_widget,
        )
        sql = next(value for key, value in artifacts.items() if key.endswith("/widget.sql"))
        assert "_source_record_key" in sql

    def test_source_bound_model_has_non_null_physical_key(
        self,
        template_dir,
        nk_sources_dir,
        nk_mappings_widget,
    ):
        g = Graph()
        g.parse(data=NK_ONTOLOGY_WITHOUT_KEY_TTL, format="turtle")
        classes = [
            {
                "uri": "http://kairos.example/ontology/Widget",
                "name": "Widget",
                "label": "Widget",
                "comment": "A widget entity",
            }
        ]

        artifacts = generate_dbt_artifacts(
            classes=classes,
            graph=g,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="widget",
            sources_dir=nk_sources_dir,
            mappings_dir=nk_mappings_widget,
        )
        sql = next(value for key, value in artifacts.items() if key.endswith("/widget.sql"))
        assert "generate_surrogate_key" in sql
        assert "CAST(NULL" not in sql.split(" as widget_sk", 1)[0].splitlines()[-1]

    def test_scd2_sequences_multiple_source_versions_per_key(
        self,
        classes,
        ontology_graph,
        template_dir,
        bronze_dir,
        mappings_dir,
    ):
        artifacts = generate_dbt_artifacts(
            classes=classes,
            graph=ontology_graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="client",
            sources_dir=bronze_dir,
            mappings_dir=mappings_dir,
        )
        sql = artifacts["models/silver/client/client.sql"]
        assert "kairos_row_hash" not in sql
        assert "replay_deduplicated" not in sql
        # DD-627: non-runtime Silver models no longer hardcode `materialized=`
        # inline; the dbt_project.yml-level `+materialized: table` cascade
        # default applies instead, unlocking downstream override.
        assert "materialized=" not in sql
        assert "schema=" in sql
        release = artifacts["__release_data__"]
        assert any(item["rule_id"] == "DD-108-identity" for item in release["blocking_reasons"])


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
    @prefix map: <https://example.com/mapping/fk#> .
    @prefix bronze: <https://example.com/bronze/erp#> .
    @prefix ex: <http://kairos.example/ontology/> .

    bronze:Orders skos:exactMatch ex:Order .

    bronze:Orders_order_id skos:exactMatch ex:orderId .
    bronze:Orders_customer_id skos:exactMatch ex:placedBy .
    map:table a kairos-map:TableMapping ;
        kairos-map:sourceTable bronze:Orders ;
        kairos-map:targetClass ex:Order ;
        kairos-map:mappingType "direct" ;
        kairos-map:matchType "exactMatch" .
    map:orderId a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze:Orders_order_id ;
        kairos-map:targetProperty ex:orderId ;
        kairos-map:matchType "exactMatch" .
    map:customer a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze:Orders_customer_id ;
        kairos-map:targetProperty ex:placedBy ;
        kairos-map:matchType "exactMatch" .
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
        (d / "erp.vocabulary.ttl").write_text(SILVER_FK_ANNOTATION_BRONZE_TTL, encoding="utf-8")
        return tmp_path / "sources"

    @pytest.fixture
    def fk_mappings_dir(self, tmp_path):
        d = tmp_path / "mappings" / "erp"
        d.mkdir(parents=True)
        (d / "erp-to-order.ttl").write_text(SILVER_FK_ANNOTATION_MAPPING_TTL, encoding="utf-8")
        return tmp_path / "mappings"

    def test_silver_fk_annotation_generates_join(
        self,
        fk_graph,
        fk_sources_dir,
        fk_mappings_dir,
        template_dir,
    ):
        """silverForeignKey true must produce FK join even without FunctionalProperty."""
        classes = [
            {
                "uri": "http://kairos.example/ontology/Order",
                "name": "Order",
                "label": "Order",
                "comment": "An order",
            },
            {
                "uri": "http://kairos.example/ontology/Customer",
                "name": "Customer",
                "label": "Customer",
                "comment": "A customer",
            },
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
    """Tests for the typed Silver registry and registry-aware resolution."""

    @staticmethod
    def _registry(meta, relations=()):
        return build_silver_registry(
            tuple(outcome_from_context(item) for item in meta),
            relations,
        )

    def test_registry_maps_class_uri_to_model_name(self):
        """Registry maps class URIs from entity metadata to snake_case model names."""
        meta = [
            {
                "class_name": "TransportOrder",
                "class_uri": "http://ex.com/TransportOrder",
                "skipped": False,
                "column_names": ["order_name", "status"],
            },
            {
                "class_name": "Customer",
                "class_uri": "http://ex.com/Customer",
                "skipped": False,
                "column_names": ["customer_name"],
            },
        ]
        registry = self._registry(meta)
        name_reg = dict(registry.names)
        cols_reg = dict(registry.columns)
        assert name_reg["http://ex.com/TransportOrder"] == "transport_order"
        assert name_reg["http://ex.com/Customer"] == "customer"
        assert cols_reg["transport_order"] == {"order_name", "status"}
        assert cols_reg["customer"] == {"customer_name"}

    def test_registry_maps_parent_uri_to_child(self):
        """Parent class URI maps to child's model when single child extends it."""
        parent_uri = URIRef("http://refmodel.org/PurchaseOrder")
        child_uri = URIRef("http://ex.com/HubOrder")

        meta = [
            {
                "class_name": "HubOrder",
                "class_uri": str(child_uri),
                "skipped": False,
                "column_names": ["order_id"],
            },
        ]
        registry = self._registry(meta, ((str(child_uri), str(parent_uri)),))
        name_reg = dict(registry.names)
        # Parent resolves to child's model name
        assert name_reg[str(parent_uri)] == "hub_order"

    def test_registry_skips_ambiguous_parent(self):
        """Parent with multiple children is NOT registered (ambiguous)."""
        parent_uri = URIRef("http://refmodel.org/Party")
        child1_uri = URIRef("http://ex.com/Customer")
        child2_uri = URIRef("http://ex.com/Supplier")

        meta = [
            {
                "class_name": "Customer",
                "class_uri": str(child1_uri),
                "skipped": False,
                "column_names": [],
            },
            {
                "class_name": "Supplier",
                "class_uri": str(child2_uri),
                "skipped": False,
                "column_names": [],
            },
        ]
        registry = self._registry(
            meta,
            (
                (str(child1_uri), str(parent_uri)),
                (str(child2_uri), str(parent_uri)),
            ),
        )
        name_reg = dict(registry.names)
        # Parent should NOT be in registry (ambiguous)
        assert str(parent_uri) not in name_reg

    def test_registry_skips_skipped_classes(self):
        """Skipped classes (no mapping) are not registered."""
        meta = [
            {
                "class_name": "NoMapping",
                "class_uri": "http://ex.com/NoMapping",
                "skipped": True,
                "column_names": [],
            },
        ]
        name_reg = dict(self._registry(meta).names)
        assert "http://ex.com/NoMapping" not in name_reg

    def test_resolver_uses_registry_first(self):
        """_silver_model_name_for_class uses registry over classes list."""
        registry = {"http://refmodel.org/ImportedClass": "hub_entity"}
        classes = [
            {
                "uri": "http://refmodel.org/ImportedClass",
                "name": "ImportedClass",
                "label": "",
                "comment": "",
            },
        ]
        # Without registry, would return "imported_class"
        result = _silver_model_name_for_class(
            "http://refmodel.org/ImportedClass", classes, registry=registry
        )
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
        result = _silver_model_name_for_class("http://unknown.org/ont#SomeClass", [], registry={})
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
        g.parse(
            data="""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.com/ont#> .
ex:Orphan a owl:Class ; rdfs:label "Orphan" .
""",
            format="turtle",
        )
        result = _get_natural_key(g, "http://example.com/ont#Orphan")
        assert result == []

    def test_cyclic_subclass_does_not_loop(self):
        """Cyclic rdfs:subClassOf doesn't cause infinite recursion."""
        g = Graph()
        g.parse(
            data="""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.com/ont#> .
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
ex:A a owl:Class ; rdfs:subClassOf ex:B ; rdfs:label "A" .
ex:B a owl:Class ; rdfs:subClassOf ex:A ;
    kairos-ext:inheritanceStrategy "discriminator" ; rdfs:label "B" .
""",
            format="turtle",
        )
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


# ---------------------------------------------------------------------------
# CR-002: composite naturalKey parsing
# ---------------------------------------------------------------------------

COMPOSITE_NK_ONTOLOGY_TTL = textwrap.dedent("""\
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
    @prefix ex:   <http://kairos.example/ontology/> .
    @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

    <http://kairos.example/ontology> a owl:Ontology ;
        rdfs:label "Composite NK Test" ;
        owl:versionInfo "1.0.0" .

    ex:Address a owl:Class ;
        rdfs:label "Address" ;
        rdfs:comment "An address entity" ;
        kairos-ext:naturalKey "addressStreet,addressZipCode" .

    ex:AddressSpaced a owl:Class ;
        rdfs:label "Address Spaced" ;
        rdfs:comment "NK declared with space after comma" ;
        kairos-ext:naturalKey "addressStreet, addressZipCode" .

    ex:addressStreet a owl:DatatypeProperty ;
        rdfs:label "address street" ;
        rdfs:domain ex:Address ;
        rdfs:range xsd:string .

    ex:addressZipCode a owl:DatatypeProperty ;
        rdfs:label "address zip code" ;
        rdfs:domain ex:Address ;
        rdfs:range xsd:string .
""")


class TestCompositeNaturalKey:
    """CR-002 — composite naturalKey must split on commas, not only whitespace."""

    def _graph(self):
        g = Graph()
        g.parse(data=COMPOSITE_NK_ONTOLOGY_TTL, format="turtle")
        return g

    def test_comma_no_space_splits_into_two(self):
        """'addressStreet,addressZipCode' should yield two separate snake_case keys."""
        g = self._graph()
        result = _get_natural_key(g, "http://kairos.example/ontology/Address")
        assert result == [
            "address_street",
            "address_zip_code",
        ], f"Expected ['address_street', 'address_zip_code'], got {result}"

    def test_comma_with_space_splits_into_two(self):
        """'addressStreet, addressZipCode' (space after comma) should also split cleanly."""
        g = self._graph()
        result = _get_natural_key(g, "http://kairos.example/ontology/AddressSpaced")
        assert result == [
            "address_street",
            "address_zip_code",
        ], f"Expected ['address_street', 'address_zip_code'], got {result}"

    def test_composite_sk_has_two_quoted_elements(self):
        """Surrogate key expression should contain both NK columns as separate list items."""
        g = self._graph()
        nk = _get_natural_key(g, "http://kairos.example/ontology/Address")
        cols = _build_sk_iri_columns(
            g,
            "http://kairos.example/ontology/Address",
            "http://kairos.example/ontology/",
            nk,
        )
        sk_expr = next(c["expression"] for c in cols if c["target_name"] == "address_sk")
        assert "'address_street', 'address_zip_code'" in sk_expr, (
            f"SK expression should list both keys separately:\n{sk_expr}"
        )
        # Must NOT have a comma inside a single quoted string
        assert "'address_street,address_zip_code'" not in sk_expr

    def test_composite_iri_uses_underscore_separator(self):
        """IRI CONCAT for composite NK should join parts with '_', not '/'."""
        g = self._graph()
        nk = _get_natural_key(g, "http://kairos.example/ontology/Address")
        cols = _build_sk_iri_columns(
            g,
            "http://kairos.example/ontology/Address",
            "http://kairos.example/ontology/",
            nk,
        )
        iri_expr = next(c["expression"] for c in cols if c["target_name"] == "address_iri")
        assert "'_'" in iri_expr, (
            f"IRI CONCAT should separate composite NK parts with '_':\n{iri_expr}"
        )
        assert "address_street" in iri_expr
        assert "address_zip_code" in iri_expr


# ---------------------------------------------------------------------------
# CR-003: dbt.type_string() replaces dbt_utils.type_string()
# ---------------------------------------------------------------------------


class TestDbtTypeStringMacro:
    """CR-003 — NULL SK/IRI fallback must use dbt.type_string(), not dbt_utils.type_string()."""

    def test_null_sk_uses_dbt_type_string(self):
        """_build_sk_iri_columns with no natural key should emit dbt.type_string()."""
        g = Graph()
        g.parse(
            data=textwrap.dedent("""\
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            @prefix ex: <http://ex.com/> .
            <http://ex.com/> a owl:Ontology ; rdfs:label "t" ; owl:versionInfo "1.0" .
            ex:Foo a owl:Class ; rdfs:label "Foo" ; rdfs:comment "f" .
        """),
            format="turtle",
        )
        cols = _build_sk_iri_columns(g, "http://ex.com/Foo", "http://ex.com/", [])
        for col in cols:
            expr = col["expression"]
            assert "dbt_utils.type_string" not in expr, f"Should use dbt.type_string(), got: {expr}"
            assert "dbt.type_string()" in expr

    def test_null_sk_not_using_deprecated_macro(self, template_dir, tmp_path):
        """Full artifact generation: NULL SK should not reference dbt_utils.type_string()."""
        no_nk_ttl = textwrap.dedent("""\
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
            @prefix ex: <http://kairos.example/ontology/> .

            <http://kairos.example/ontology> a owl:Ontology ;
                rdfs:label "T" ; owl:versionInfo "1.0.0" .

            ex:Item a owl:Class ;
                rdfs:label "Item" ; rdfs:comment "An item with no naturalKey" .

            ex:itemCode a owl:DatatypeProperty ;
                rdfs:label "item code" ;
                rdfs:domain ex:Item ;
                rdfs:range xsd:string .
        """)
        g = Graph()
        g.parse(data=no_nk_ttl, format="turtle")
        classes = [
            {
                "uri": "http://kairos.example/ontology/Item",
                "name": "Item",
                "label": "Item",
                "comment": "An item",
            }
        ]
        artifacts = generate_dbt_artifacts(
            classes=classes,
            graph=g,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="item",
        )
        all_sql = "\n".join(
            value for value in artifacts.values() if isinstance(value, str) and value
        )
        assert "dbt_utils.type_string" not in all_sql, (
            "Generated SQL must not use deprecated dbt_utils.type_string()"
        )


# ---------------------------------------------------------------------------
# CR-004: dim_date.sql must not have nested duplicate CTE label
# ---------------------------------------------------------------------------


class TestDimDateNoDuplicateCte:
    """CR-004 — generated dim_date.sql must not embed a duplicate 'date_spine AS ('."""

    def test_no_duplicate_cte_label(
        self, gold_ontology_graph, template_dir, gold_bronze_dir, gold_mappings_dir
    ):
        """dim_date.sql must have exactly one occurrence of 'date_spine as (' (case-insensitive)."""
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
        content = artifacts[date_key].lower()
        count = content.count("date_spine as (")
        assert count == 1, (
            f"Expected exactly 1 'date_spine as (' in dim_date.sql, found {count}:\n"
            + artifacts[date_key]
        )

    def test_dim_date_select_is_top_level(
        self, gold_ontology_graph, template_dir, gold_bronze_dir, gold_mappings_dir
    ):
        """The SELECT inside the date_spine CTE must not be wrapped in another CTE body."""
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
        # Should NOT contain 'date_spine AS (' as a nested string inside the CTE
        # (i.e. the body after 'with date_spine as (' should start with SELECT)
        import re as _re

        match = _re.search(
            r"with\s+date_spine\s+as\s*\((.+?)^\)",
            content,
            _re.DOTALL | _re.MULTILINE | _re.IGNORECASE,
        )
        if match:
            inner = match.group(1)
            assert "date_spine as (" not in inner.lower(), (
                "CTE body must not start with another 'date_spine as (' wrapper"
            )


# ---------------------------------------------------------------------------
# CR-001: SK/IRI must use source expression, not alias (T-SQL alias-before-definition)
# ---------------------------------------------------------------------------

# Ontology: BankAccount with naturalKey "bankIBAN"
BANK_ACCOUNT_ONTOLOGY_TTL = textwrap.dedent("""\
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
    @prefix ex:   <http://kairos.example/ontology/> .
    @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

    <http://kairos.example/ontology> a owl:Ontology ;
        rdfs:label "Bank Test" ;
        owl:versionInfo "1.0.0" .

    ex:BankAccount a owl:Class ;
        rdfs:label "BankAccount" ;
        rdfs:comment "A bank account" ;
        kairos-ext:naturalKey "bankIBAN" .

    ex:bankIBAN a owl:DatatypeProperty ;
        rdfs:label "bank IBAN" ;
        rdfs:domain ex:BankAccount ;
        rdfs:range xsd:string .
""")

# Bronze: source table with bankIBAN column (using original camelCase name)
BANK_ACCOUNT_BRONZE_TTL = textwrap.dedent("""\
    @prefix bronze-ap: <https://example.com/bronze/adminpulse#> .
    @prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

    bronze-ap:AdminPulse a kairos-bronze:SourceSystem ;
        rdfs:label "AdminPulse" ;
        kairos-bronze:connectionType "jdbc" ;
        kairos-bronze:database "AP_Prod" ;
        kairos-bronze:schema "dbo" .

    bronze-ap:tblBankAccount a kairos-bronze:SourceTable ;
        rdfs:label "adminpulse_relations" ;
        kairos-bronze:sourceSystem bronze-ap:AdminPulse ;
        kairos-bronze:tableName "adminpulse_relations" ;
        kairos-bronze:primaryKeyColumns "bankIBAN" .

    bronze-ap:tblBankAccount_bankIBAN a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-ap:tblBankAccount ;
        kairos-bronze:columnName "bankIBAN" ;
        kairos-bronze:dataType "nvarchar" ;
        kairos-bronze:nullable "false"^^xsd:boolean ;
        kairos-bronze:isPrimaryKey "true"^^xsd:boolean .
""")

# SKOS mapping: source bankIBAN → domain bankIBAN property
BANK_ACCOUNT_MAPPING_TTL = textwrap.dedent("""\
    @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
    @prefix bronze-ap: <https://example.com/bronze/adminpulse#> .
    @prefix ex: <http://kairos.example/ontology/> .
    @prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
    @prefix map: <https://example.com/mapping/bank#> .

    bronze-ap:tblBankAccount skos:exactMatch ex:BankAccount .
    bronze-ap:tblBankAccount_bankIBAN skos:exactMatch ex:bankIBAN .
    map:table a kairos-map:TableMapping ;
        kairos-map:sourceTable bronze-ap:tblBankAccount ;
        kairos-map:targetClass ex:BankAccount ;
        kairos-map:mappingType "direct" ;
        kairos-map:matchType "exactMatch" .
    map:iban a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze-ap:tblBankAccount_bankIBAN ;
        kairos-map:targetProperty ex:bankIBAN ;
        kairos-map:matchType "exactMatch" .
""")


class TestSkIriUsesSourceExpression:
    """Runtime-neutral models keep generated identity expressions in source scope."""

    @pytest.fixture
    def bank_sources_dir(self, tmp_path):
        d = tmp_path / "sources" / "adminpulse"
        d.mkdir(parents=True)
        (d / "adminpulse.vocabulary.ttl").write_text(BANK_ACCOUNT_BRONZE_TTL, encoding="utf-8")
        return tmp_path / "sources"

    @pytest.fixture
    def bank_mappings_dir(self, tmp_path):
        d = tmp_path / "mappings"
        d.mkdir(parents=True)
        (d / "bank_account.ttl").write_text(BANK_ACCOUNT_MAPPING_TTL, encoding="utf-8")
        return d

    def _get_sql(self, template_dir, bank_sources_dir, bank_mappings_dir):
        g = Graph()
        g.parse(data=BANK_ACCOUNT_ONTOLOGY_TTL, format="turtle")
        classes = [
            {
                "uri": "http://kairos.example/ontology/BankAccount",
                "name": "BankAccount",
                "label": "BankAccount",
                "comment": "A bank account",
            }
        ]
        artifacts = generate_dbt_artifacts(
            classes=classes,
            graph=g,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/",
            ontology_name="bank",
            sources_dir=bank_sources_dir,
            mappings_dir=bank_mappings_dir,
        )
        sql_key = next(k for k in artifacts if "bank_account.sql" in k)
        return artifacts[sql_key]

    def test_mapped_cte_uses_source_expression(
        self, template_dir, bank_sources_dir, bank_mappings_dir
    ):
        """In the mapped CTE, the column expression must reference the source column
        (adminpulse_relations.bankIBAN), not the snake_case alias."""
        import re as _re

        sql = self._get_sql(template_dir, bank_sources_dir, bank_mappings_dir)
        assert "mapped as (" in sql
        mapped_block = _re.search(
            r"mapped\s+as\s+\((.+?)\)\s*\nselect",
            sql,
            _re.DOTALL,
        )
        assert mapped_block
        assert "[adminpulse_relations].[bankIBAN]" in mapped_block.group(1), (
            "mapped CTE must use the source column expression, got:\n" + mapped_block.group(1)
        )

    def test_no_source_data_stage_is_inferred_without_runtime_authority(
        self, template_dir, bank_sources_dir, bank_mappings_dir
    ):
        """An SCD annotation alone cannot create a parallel source_data runtime."""
        sql = self._get_sql(template_dir, bank_sources_dir, bank_mappings_dir)
        assert "source_data" not in sql
        assert "'adminpulse_relations.bankIBAN'" in sql
        assert "generate_surrogate_key(['bank_iban'])" not in sql

    def test_iri_expression_uses_source_column_in_mapped(
        self, template_dir, bank_sources_dir, bank_mappings_dir
    ):
        """The generated IRI remains in the source-scoped mapped stage."""
        sql = self._get_sql(template_dir, bank_sources_dir, bank_mappings_dir)
        # Source expression still appears somewhere (in the mapped CTE column expression)
        assert "[adminpulse_relations].[bankIBAN]" in sql, (
            "Source column expression must appear in the mapped CTE, got:\n" + sql
        )
        assert "source_data" not in sql

    def test_no_source_lookup_falls_back_to_alias(self):
        """Without a source lookup, _build_sk_iri_columns falls back to the alias (safe default)."""
        g = Graph()
        g.parse(data=BANK_ACCOUNT_ONTOLOGY_TTL, format="turtle")
        nk = _get_natural_key(g, "http://kairos.example/ontology/BankAccount")
        cols = _build_sk_iri_columns(
            g,
            "http://kairos.example/ontology/BankAccount",
            "http://kairos.example/ontology/",
            nk,
            nk_source_exprs=None,
        )
        sk_expr = next(c["expression"] for c in cols if c["target_name"] == "bank_account_sk")
        # Without source lookup, falls back to alias
        assert "bank_iban" in sk_expr


# ---------------------------------------------------------------------------
# CR-005: SCD2 source_data CTE must use aliased column names for SK/IRI
# ---------------------------------------------------------------------------

_CR005_PARTY_ONTOLOGY_TTL = textwrap.dedent("""\
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
    @prefix party: <http://kairos.example/ontology/party#> .
    @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

    <http://kairos.example/ontology/party> a owl:Ontology ;
        rdfs:label "Party Test" ;
        owl:versionInfo "1.0.0" .

    party:Party a owl:Class ;
        rdfs:label "Party" ;
        rdfs:comment "A party" ;
        kairos-ext:naturalKey "partyIdentifier" .

    party:partyIdentifier a owl:DatatypeProperty ;
        rdfs:label "party identifier" ;
        rdfs:domain party:Party ;
        rdfs:range xsd:string .

    party:remark a owl:DatatypeProperty ;
        rdfs:label "remark" ;
        rdfs:domain party:Party ;
        rdfs:range xsd:string .
""")

_CR005_PARTY_SILVER_EXT_TTL = textwrap.dedent("""\
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix party: <http://kairos.example/ontology/party#> .
    @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

    <http://kairos.example/ontology/party-silver-ext> a owl:Ontology ;
        rdfs:label "Party Silver Ext" ;
        owl:versionInfo "1.0.0" .

    party:Party kairos-ext:scdType "2" .
""")

_CR005_PARTY_BRONZE_TTL = textwrap.dedent("""\
    @prefix bronze-ap: <https://example.com/bronze/adminpulse#> .
    @prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

    bronze-ap:AdminPulse a kairos-bronze:SourceSystem ;
        rdfs:label "AdminPulse" ;
        kairos-bronze:connectionType "jdbc" .

    bronze-ap:tblRelations a kairos-bronze:SourceTable ;
        rdfs:label "adminpulse_relations" ;
        kairos-bronze:sourceSystem bronze-ap:AdminPulse ;
        kairos-bronze:tableName "adminpulse_relations" ;
        kairos-bronze:primaryKeyColumns "uniqueIdentifier" .

    bronze-ap:tblRelations_uniqueIdentifier a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-ap:tblRelations ;
        kairos-bronze:columnName "uniqueIdentifier" ;
        kairos-bronze:dataType "nvarchar" ;
        kairos-bronze:nullable "false"^^xsd:boolean ;
        kairos-bronze:isPrimaryKey true .

    bronze-ap:tblRelations_remark a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-ap:tblRelations ;
        kairos-bronze:columnName "remark" ;
        kairos-bronze:dataType "nvarchar" ;
        kairos-bronze:nullable "true"^^xsd:boolean .
""")

# uniqueIdentifier (source) → partyIdentifier (domain) — name mismatch triggers the bug
_CR005_PARTY_MAPPING_TTL = textwrap.dedent("""\
    @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
    @prefix bronze-ap: <https://example.com/bronze/adminpulse#> .
    @prefix party: <http://kairos.example/ontology/party#> .
    @prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
    @prefix map: <https://example.com/mapping/party#> .

    bronze-ap:tblRelations skos:exactMatch party:Party .

    bronze-ap:tblRelations_uniqueIdentifier skos:closeMatch party:partyIdentifier .

    bronze-ap:tblRelations_remark skos:exactMatch party:remark .
    map:table a kairos-map:TableMapping ;
        kairos-map:sourceTable bronze-ap:tblRelations ;
        kairos-map:targetClass party:Party ;
        kairos-map:mappingType "direct" ;
        kairos-map:matchType "exactMatch" .
    map:identifier a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze-ap:tblRelations_uniqueIdentifier ;
        kairos-map:targetProperty party:partyIdentifier ;
        kairos-map:matchType "closeMatch" .
    map:remark a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze-ap:tblRelations_remark ;
        kairos-map:targetProperty party:remark ;
        kairos-map:matchType "exactMatch" .
""")


class TestScd2SourceDataUsesAliasedColumns:
    """An isolated scdType annotation does not establish DD-109 runtime."""

    @pytest.fixture
    def party_sources_dir(self, tmp_path):
        d = tmp_path / "sources" / "adminpulse"
        d.mkdir(parents=True)
        (d / "adminpulse.vocabulary.ttl").write_text(_CR005_PARTY_BRONZE_TTL, encoding="utf-8")
        return tmp_path / "sources"

    @pytest.fixture
    def party_mappings_dir(self, tmp_path):
        d = tmp_path / "mappings"
        d.mkdir(parents=True)
        (d / "adminpulse-to-party.ttl").write_text(_CR005_PARTY_MAPPING_TTL, encoding="utf-8")
        return d

    @pytest.fixture
    def party_silver_ext_path(self, tmp_path):
        ext_file = tmp_path / "party-silver-ext.ttl"
        ext_file.write_text(_CR005_PARTY_SILVER_EXT_TTL, encoding="utf-8")
        return ext_file

    def _get_sql(self, template_dir, party_sources_dir, party_mappings_dir, party_silver_ext_path):
        g = Graph()
        g.parse(data=_CR005_PARTY_ONTOLOGY_TTL, format="turtle")
        classes = [
            {
                "uri": "http://kairos.example/ontology/party#Party",
                "name": "Party",
                "label": "Party",
                "comment": "A party",
            }
        ]
        artifacts = generate_dbt_artifacts(
            classes=classes,
            graph=g,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/party#",
            ontology_name="party",
            sources_dir=party_sources_dir,
            mappings_dir=party_mappings_dir,
            silver_ext_path=party_silver_ext_path,
        )
        sql_key = next(k for k in artifacts if "party.sql" in k)
        return artifacts[sql_key]

    def test_source_data_is_not_inferred(
        self, template_dir, party_sources_dir, party_mappings_dir, party_silver_ext_path
    ):
        """No source_data CTE exists without identity, incremental, and CDC facts."""
        sql = self._get_sql(
            template_dir, party_sources_dir, party_mappings_dir, party_silver_ext_path
        )
        assert "source_data" not in sql
        assert "'adminpulse_relations.uniqueIdentifier'" in sql
        assert "generate_surrogate_key(['party_identifier'])" not in sql

    def test_generated_iri_remains_source_scoped(
        self, template_dir, party_sources_dir, party_mappings_dir, party_silver_ext_path
    ):
        """The structural fallback does not invent a historical IRI stage."""
        sql = self._get_sql(
            template_dir, party_sources_dir, party_mappings_dir, party_silver_ext_path
        )
        assert "source_data" not in sql
        assert "uniqueIdentifier" in sql

    def test_mapped_cte_still_uses_source_expression(
        self, template_dir, party_sources_dir, party_mappings_dir, party_silver_ext_path
    ):
        """The mapped CTE must still use the source expression (not the alias) to
        avoid T-SQL alias-before-definition — this behaviour must not regress."""
        sql = self._get_sql(
            template_dir, party_sources_dir, party_mappings_dir, party_silver_ext_path
        )
        import re as _re

        mapped_block = _re.search(
            r"mapped\s+as\s+\((.+?)\)\s*\nselect",
            sql,
            _re.DOTALL,
        )
        assert mapped_block
        block = mapped_block.group(1)
        assert "uniqueIdentifier" in block, (
            "mapped CTE must use source column 'uniqueIdentifier' in its expression:\n" + block
        )


# ---------------------------------------------------------------------------
# Issue #194: SCD2 inherited FK joins must stay in CTE scope
# ---------------------------------------------------------------------------

_ISSUE_194_ONTOLOGY_TTL = textwrap.dedent("""\
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
    @prefix party: <http://kairos.example/ontology/party#> .
    @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

    <http://kairos.example/ontology/party> a owl:Ontology ;
        rdfs:label "Party FK Scope Test" ;
        owl:versionInfo "1.0.0" .

    party:TradeParty a owl:Class ;
        rdfs:label "Trade Party" ;
        rdfs:comment "A trading party" .

    party:CargoOperator a owl:Class ;
        rdfs:subClassOf party:TradeParty ;
        rdfs:label "Cargo Operator" ;
        rdfs:comment "A cargo operator" ;
        kairos-ext:naturalKey "partyIdentifier" .

    party:Address a owl:Class ;
        rdfs:label "Address" ;
        rdfs:comment "A postal address" ;
        kairos-ext:naturalKey "streetAddress" .

    party:partyIdentifier a owl:DatatypeProperty ;
        rdfs:label "party identifier" ;
        rdfs:domain party:CargoOperator ;
        rdfs:range xsd:string .

    party:partyName a owl:DatatypeProperty ;
        rdfs:label "party name" ;
        rdfs:domain party:TradeParty ;
        rdfs:range xsd:string .

    party:streetAddress a owl:DatatypeProperty ;
        rdfs:label "street address" ;
        rdfs:domain party:Address ;
        rdfs:range xsd:string .

    party:hasBillingAddress a owl:ObjectProperty ;
        rdfs:label "has billing address" ;
        rdfs:domain party:TradeParty ;
        rdfs:range party:Address ;
        kairos-ext:silverForeignKey "true" ;
        kairos-ext:silverColumnName "billing_address_sk" .
""")

_ISSUE_194_SILVER_EXT_TTL = textwrap.dedent("""\
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix party: <http://kairos.example/ontology/party#> .
    @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

    <http://kairos.example/ontology/party-silver-ext> a owl:Ontology ;
        rdfs:label "Party Silver Ext" ;
        owl:versionInfo "1.0.0" .

    party:CargoOperator kairos-ext:scdType "2" .
""")

_ISSUE_194_BRONZE_TTL = textwrap.dedent("""\
    @prefix bronze-qargo: <https://example.com/bronze/qargo#> .
    @prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

    bronze-qargo:Qargo a kairos-bronze:SourceSystem ;
        rdfs:label "Qargo" ;
        kairos-bronze:connectionType "jdbc" .

    bronze-qargo:companies a kairos-bronze:SourceTable ;
        rdfs:label "companies" ;
        kairos-bronze:sourceSystem bronze-qargo:Qargo ;
        kairos-bronze:tableName "companies" ;
        kairos-bronze:primaryKeyColumns "company_id" .

    bronze-qargo:companies_company_id a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-qargo:companies ;
        kairos-bronze:columnName "company_id" ;
        kairos-bronze:dataType "nvarchar" ;
        kairos-bronze:nullable "false"^^xsd:boolean ;
        kairos-bronze:isPrimaryKey true .

    bronze-qargo:companies_name a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-qargo:companies ;
        kairos-bronze:columnName "name" ;
        kairos-bronze:dataType "nvarchar" ;
        kairos-bronze:nullable "true"^^xsd:boolean .

    bronze-qargo:companies_billing_address a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable bronze-qargo:companies ;
        kairos-bronze:columnName "billing_address" ;
        kairos-bronze:dataType "nvarchar" ;
        kairos-bronze:nullable "true"^^xsd:boolean .
""")

_ISSUE_194_MAPPING_TTL = textwrap.dedent("""\
    @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
    @prefix bronze-qargo: <https://example.com/bronze/qargo#> .
    @prefix party: <http://kairos.example/ontology/party#> .
    @prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
    @prefix map: <https://example.com/mapping/issue194#> .

    bronze-qargo:companies skos:exactMatch party:CargoOperator .
    bronze-qargo:companies_company_id skos:exactMatch party:partyIdentifier .
    bronze-qargo:companies_name skos:exactMatch party:partyName .
    bronze-qargo:companies_billing_address skos:exactMatch party:hasBillingAddress .
    map:table a kairos-map:TableMapping ;
        kairos-map:sourceTable bronze-qargo:companies ;
        kairos-map:targetClass party:CargoOperator ;
        kairos-map:mappingType "direct" ;
        kairos-map:matchType "exactMatch" .
    map:id a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze-qargo:companies_company_id ;
        kairos-map:targetProperty party:partyIdentifier ;
        kairos-map:matchType "exactMatch" .
    map:name a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze-qargo:companies_name ;
        kairos-map:targetProperty party:partyName ;
        kairos-map:matchType "exactMatch" .
    map:address a kairos-map:ColumnMapping ;
        kairos-map:sourceColumn bronze-qargo:companies_billing_address ;
        kairos-map:targetProperty party:hasBillingAddress ;
        kairos-map:matchType "exactMatch" .
""")


class TestIssue194Scd2InheritedFkScope:
    """Issue #194 — inherited FK joins in SCD2 models must not leak out of scope."""

    @pytest.fixture
    def sources_dir(self, tmp_path):
        d = tmp_path / "sources" / "qargo"
        d.mkdir(parents=True)
        (d / "qargo.vocabulary.ttl").write_text(_ISSUE_194_BRONZE_TTL, encoding="utf-8")
        return tmp_path / "sources"

    @pytest.fixture
    def mappings_dir(self, tmp_path):
        d = tmp_path / "mappings"
        d.mkdir(parents=True)
        (d / "qargo-to-party.ttl").write_text(_ISSUE_194_MAPPING_TTL, encoding="utf-8")
        return d

    @pytest.fixture
    def silver_ext_path(self, tmp_path):
        ext_file = tmp_path / "party-silver-ext.ttl"
        ext_file.write_text(_ISSUE_194_SILVER_EXT_TTL, encoding="utf-8")
        return ext_file

    def _get_sql(self, template_dir, sources_dir, mappings_dir, silver_ext_path):
        graph = Graph()
        graph.parse(data=_ISSUE_194_ONTOLOGY_TTL, format="turtle")
        classes = [
            {
                "uri": "http://kairos.example/ontology/party#CargoOperator",
                "name": "CargoOperator",
                "label": "Cargo Operator",
                "comment": "A cargo operator",
            }
        ]
        artifacts = generate_dbt_artifacts(
            classes=classes,
            graph=graph,
            template_dir=template_dir,
            namespace="http://kairos.example/ontology/party#",
            ontology_name="party",
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
            silver_ext_path=silver_ext_path,
        )
        sql_key = next(k for k in artifacts if "cargo_operator.sql" in k)
        return artifacts[sql_key]

    def test_inherited_fk_lookup_is_selected_in_mapped_cte(
        self, template_dir, sources_dir, mappings_dir, silver_ext_path
    ):
        sql = self._get_sql(template_dir, sources_dir, mappings_dir, silver_ext_path)
        mapped_block = sql.split("mapped as (", 1)[1].split("\n)\nselect", 1)[0]

        assert "address_ref.address_sk as billing_address_sk" in mapped_block, (
            "FK lookup must be selected while address_ref is in scope:\n" + mapped_block
        )
        assert "source_data" not in sql
        assert "select *\nfrom mapped" in sql


class TestDuplicateGeneratedModelNames:
    """A duplicate dbt model name is never valid output (issue #685).

    A Gold product whose ``goldTableName`` equalled the Silver model it sources from emitted
    ``models/silver/<d>/x.sql`` and ``models/gold/<d>/x.sql``. dbt refuses to parse that, but
    ``compile --check`` passed and ``--emit`` wrote it, reporting only a ``self-referential
    ref(...)`` warning -- which named the symptom in the Gold SQL rather than the project-wide
    collision. The rendered project could then be committed and released.
    """

    def _check(self, artifacts):
        from kairos_ontology.core.projections.dbt.render import _check_duplicate_model_names

        _check_duplicate_model_names(artifacts)

    def test_silver_and_gold_claiming_one_name_is_blocking(self):
        from kairos_ontology.core.projections.dbt.render import DbtModelNameCollisionError

        artifacts = {
            "models/silver/party/frachtparty.sql": "select 1",
            "models/gold/party/frachtparty.sql": "select * from {{ ref('frachtparty') }}",
        }
        with pytest.raises(DbtModelNameCollisionError) as excinfo:
            self._check(artifacts)

        message = str(excinfo.value)
        # The issue asks for the colliding pair to be named, not just the condition.
        assert "frachtparty" in message
        assert "models/silver/party/frachtparty.sql" in message
        assert "models/gold/party/frachtparty.sql" in message
        # And it must point at the authoring fix.
        assert "goldTableName" in message

    def test_gold_table_colliding_with_a_dual_current_view_is_blocking(self):
        """`dimensionExposure "dual"` derives `<name>_current`, which is also a model.

        This name is produced during materialization, so an authored-name-only check never
        sees it -- and two artifacts on the same path silently overwrite one another.
        """
        from kairos_ontology.core.projections.dbt.render import DbtModelNameCollisionError

        with pytest.raises(DbtModelNameCollisionError):
            self._check(
                {
                    "models/gold/party/dim_customer.sql": "select 1",
                    "models/gold/party/dim_customer_current.sql": "select 1",
                    "models/gold/other/dim_customer_current.sql": "select 1",
                }
            )

    def test_collision_is_case_insensitive(self):
        """Matches emit._collision_key and compile's stem comparison.

        dbt's own duplicate-resource error is case-sensitive, but the adapters target
        case-insensitive warehouses and development happens on case-insensitive filesystems,
        so differing only by case is not a usable distinction.
        """
        from kairos_ontology.core.projections.dbt.render import DbtModelNameCollisionError

        with pytest.raises(DbtModelNameCollisionError):
            self._check(
                {
                    "models/silver/party/frachtparty.sql": "select 1",
                    "models/gold/party/FrachtParty.sql": "select 1",
                }
            )

    def test_macro_sharing_a_model_name_is_not_a_collision(self):
        """Macros are `.sql` too, but live in a separate dbt resource namespace."""
        self._check(
            {
                "macros/kairos_concat.sql": "{% macro kairos_concat() %}{% endmacro %}",
                "models/silver/party/kairos_concat.sql": "select 1",
            }
        )

    def test_distinct_names_across_layers_pass(self):
        self._check(
            {
                "models/silver/party/frachtparty.sql": "select 1",
                "models/gold/party/dim_frachtparty.sql": "select 1",
                "models/quality/party/frachtparty__dq_quarantine.sql": "select 1",
                "models/silver/party/_party__models.yml": "version: 2",
            }
        )
