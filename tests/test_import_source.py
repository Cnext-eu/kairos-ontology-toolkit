# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the import-source module (YAML parsing, TTL generation, merge)."""

import pytest
from rdflib import Graph, Namespace
from rdflib.namespace import RDF, OWL

from kairos_ontology.import_source import (
    validate_source_schema,
    parse_source_schema,
    generate_vocabulary_ttl,
    merge_with_existing,
    run_import_source,
    ChangeReport,
    KAIROS_BRONZE,
)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

VALID_YAML_DATA = {
    "version": "1.0",
    "system": "testapp",
    "platform": "fabric-lakehouse",
    "environment": "dev",
    "extracted_at": "2026-06-01T10:00:00Z",
    "connection": {
        "database": "bronze_db",
        "schema": "raw_testapp",
    },
    "tables": [
        {
            "name": "tblClient",
            "incremental_column": "ModifiedDate",
            "columns": [
                {"name": "ClientId", "data_type": "int", "nullable": False, "is_primary_key": True},
                {"name": "ClientName", "data_type": "string", "nullable": True},
                {"name": "Email", "data_type": "string", "nullable": True},
                {"name": "ModifiedDate", "data_type": "datetime", "nullable": False},
            ],
        },
        {
            "name": "tblInvoice",
            "columns": [
                {"name": "InvoiceId", "data_type": "int", "nullable": False, "is_primary_key": True},
                {"name": "ClientId", "data_type": "int", "nullable": False},
                {"name": "Amount", "data_type": "decimal(18,2)", "nullable": False},
            ],
        },
    ],
}


@pytest.fixture
def valid_yaml_file(tmp_path):
    """Create a valid source-schema YAML file."""
    import yaml

    yaml_path = tmp_path / "testapp-schema.yaml"
    yaml_path.write_text(yaml.dump(VALID_YAML_DATA), encoding="utf-8")
    return yaml_path


@pytest.fixture
def existing_vocab_file(tmp_path):
    """Create an existing vocabulary TTL to test merge."""
    ttl_content = """\
@prefix testapp: <https://kairos.cnext.eu/source/testapp#> .
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

testapp:testapp a kairos-bronze:SourceSystem ;
    rdfs:label "testapp" ;
    kairos-bronze:connectionType "jdbc" ;
    kairos-bronze:database "old_db" ;
    kairos-bronze:schema "old_schema" .

testapp:tblClient a kairos-bronze:SourceTable ;
    rdfs:label "tblClient" ;
    kairos-bronze:sourceSystem testapp:testapp ;
    kairos-bronze:tableName "tblClient" ;
    kairos-bronze:primaryKeyColumns "ClientId" ;
    kairos-bronze:incrementalColumn "ModifiedDate" .

testapp:tblClient_ClientId a kairos-bronze:SourceColumn ;
    kairos-bronze:sourceTable testapp:tblClient ;
    kairos-bronze:columnName "ClientId" ;
    kairos-bronze:dataType "int" ;
    kairos-bronze:nullable "false"^^xsd:boolean ;
    kairos-bronze:isPrimaryKey "true"^^xsd:boolean .

testapp:tblClient_ClientName a kairos-bronze:SourceColumn ;
    kairos-bronze:sourceTable testapp:tblClient ;
    kairos-bronze:columnName "ClientName" ;
    kairos-bronze:dataType "nvarchar(255)" ;
    kairos-bronze:nullable "true"^^xsd:boolean .

testapp:tblClient_OldColumn a kairos-bronze:SourceColumn ;
    kairos-bronze:sourceTable testapp:tblClient ;
    kairos-bronze:columnName "OldColumn" ;
    kairos-bronze:dataType "string" ;
    kairos-bronze:nullable "true"^^xsd:boolean .

testapp:tblOldTable a kairos-bronze:SourceTable ;
    rdfs:label "tblOldTable" ;
    kairos-bronze:sourceSystem testapp:testapp ;
    kairos-bronze:tableName "tblOldTable" .

testapp:tblOldTable_Id a kairos-bronze:SourceColumn ;
    kairos-bronze:sourceTable testapp:tblOldTable ;
    kairos-bronze:columnName "Id" ;
    kairos-bronze:dataType "int" ;
    kairos-bronze:nullable "false"^^xsd:boolean .
"""
    vocab_path = tmp_path / "testapp.vocabulary.ttl"
    vocab_path.write_text(ttl_content, encoding="utf-8")
    return vocab_path


# --------------------------------------------------------------------------- #
# Validation Tests
# --------------------------------------------------------------------------- #


class TestValidation:
    def test_valid_schema(self):
        errors = validate_source_schema(VALID_YAML_DATA)
        assert errors == []

    def test_missing_version(self):
        data = {**VALID_YAML_DATA, "version": None}
        errors = validate_source_schema(data)
        assert any("version" in e for e in errors)

    def test_unsupported_version(self):
        data = {**VALID_YAML_DATA, "version": "99.0"}
        errors = validate_source_schema(data)
        assert any("Unsupported" in e for e in errors)

    def test_missing_system(self):
        data = {**VALID_YAML_DATA}
        del data["system"]
        errors = validate_source_schema(data)
        assert any("system" in e for e in errors)

    def test_missing_tables(self):
        data = {**VALID_YAML_DATA, "tables": []}
        errors = validate_source_schema(data)
        assert any("tables" in e for e in errors)

    def test_missing_column_name(self):
        data = {
            "version": "1.0",
            "system": "test",
            "tables": [{"name": "t1", "columns": [{"data_type": "int"}]}],
        }
        errors = validate_source_schema(data)
        assert any("name" in e for e in errors)

    def test_missing_data_type(self):
        data = {
            "version": "1.0",
            "system": "test",
            "tables": [{"name": "t1", "columns": [{"name": "col1"}]}],
        }
        errors = validate_source_schema(data)
        assert any("data_type" in e for e in errors)

    def test_not_a_dict(self):
        errors = validate_source_schema("not a dict")
        assert errors == ["Root element must be a mapping"]


class TestParseSourceSchema:
    def test_parse_valid(self, valid_yaml_file):
        data = parse_source_schema(valid_yaml_file)
        assert data["system"] == "testapp"
        assert len(data["tables"]) == 2

    def test_parse_invalid_raises(self, tmp_path):
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("version: '99.0'\nsystem: test\n", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid source schema"):
            parse_source_schema(bad_file)

    def test_parse_empty_raises(self, tmp_path):
        empty_file = tmp_path / "empty.yaml"
        empty_file.write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="empty"):
            parse_source_schema(empty_file)


# --------------------------------------------------------------------------- #
# TTL Generation Tests
# --------------------------------------------------------------------------- #


class TestGenerateVocabularyTtl:
    def test_generates_valid_turtle(self):
        ttl = generate_vocabulary_ttl(VALID_YAML_DATA)
        # Should be parseable
        g = Graph()
        g.parse(data=ttl, format="turtle")
        assert len(g) > 0

    def test_contains_source_system(self):
        ttl = generate_vocabulary_ttl(VALID_YAML_DATA)
        g = Graph()
        g.parse(data=ttl, format="turtle")
        systems = list(g.subjects(RDF.type, KAIROS_BRONZE.SourceSystem))
        assert len(systems) == 1

    def test_contains_tables(self):
        ttl = generate_vocabulary_ttl(VALID_YAML_DATA)
        g = Graph()
        g.parse(data=ttl, format="turtle")
        tables = list(g.subjects(RDF.type, KAIROS_BRONZE.SourceTable))
        assert len(tables) == 2

    def test_contains_columns(self):
        ttl = generate_vocabulary_ttl(VALID_YAML_DATA)
        g = Graph()
        g.parse(data=ttl, format="turtle")
        columns = list(g.subjects(RDF.type, KAIROS_BRONZE.SourceColumn))
        assert len(columns) == 7  # 4 + 3

    def test_primary_key_columns(self):
        ttl = generate_vocabulary_ttl(VALID_YAML_DATA)
        g = Graph()
        g.parse(data=ttl, format="turtle")
        # Check tblClient has PK
        ns = Namespace("https://kairos.cnext.eu/source/testapp#")
        pk_val = str(g.value(ns["tblClient"], KAIROS_BRONZE.primaryKeyColumns))
        assert "ClientId" in pk_val

    def test_content_type_annotation(self):
        """JSON content_type should generate contentType triple."""
        data = {
            "version": "1.0",
            "system": "jsontest",
            "tables": [{
                "name": "t1",
                "columns": [{
                    "name": "payload",
                    "data_type": "string",
                    "content_type": "json-object",
                }],
            }],
        }
        ttl = generate_vocabulary_ttl(data)
        g = Graph()
        g.parse(data=ttl, format="turtle")
        ns = Namespace("https://kairos.cnext.eu/source/jsontest#")
        ct = str(g.value(ns["t1_payload"], KAIROS_BRONZE.contentType))
        assert ct == "json-object"

    def test_incremental_column(self):
        ttl = generate_vocabulary_ttl(VALID_YAML_DATA)
        g = Graph()
        g.parse(data=ttl, format="turtle")
        ns = Namespace("https://kairos.cnext.eu/source/testapp#")
        inc = str(g.value(ns["tblClient"], KAIROS_BRONZE.incrementalColumn))
        assert inc == "ModifiedDate"


# --------------------------------------------------------------------------- #
# Merge Tests
# --------------------------------------------------------------------------- #


class TestMergeWithExisting:
    def test_detects_added_table(self, existing_vocab_file):
        """tblInvoice is new (not in existing vocab)."""
        _, report = merge_with_existing(VALID_YAML_DATA, existing_vocab_file)
        assert "tblInvoice" in report.added_tables

    def test_detects_removed_table(self, existing_vocab_file):
        """tblOldTable is in existing but not in new YAML."""
        _, report = merge_with_existing(VALID_YAML_DATA, existing_vocab_file)
        assert "tblOldTable" in report.removed_tables

    def test_detects_added_column(self, existing_vocab_file):
        """Email and ModifiedDate are new columns in tblClient."""
        _, report = merge_with_existing(VALID_YAML_DATA, existing_vocab_file)
        added_names = [(c.table, c.column) for c in report.added_columns]
        assert ("tblClient", "Email") in added_names
        assert ("tblClient", "ModifiedDate") in added_names

    def test_detects_removed_column(self, existing_vocab_file):
        """OldColumn is in existing tblClient but not in new YAML."""
        _, report = merge_with_existing(VALID_YAML_DATA, existing_vocab_file)
        removed_names = [(c.table, c.column) for c in report.removed_columns]
        assert ("tblClient", "OldColumn") in removed_names

    def test_detects_type_change(self, existing_vocab_file):
        """ClientName type changed from nvarchar(255) to string."""
        _, report = merge_with_existing(VALID_YAML_DATA, existing_vocab_file)
        type_changes = [(c.table, c.column) for c in report.type_changes]
        assert ("tblClient", "ClientName") in type_changes

    def test_preserves_unknown_triples(self, existing_vocab_file):
        """Manual annotations not managed by introspection should be preserved."""
        ttl, _ = merge_with_existing(VALID_YAML_DATA, existing_vocab_file)
        g = Graph()
        g.parse(data=ttl, format="turtle")
        # connectionType was in existing and should be preserved
        ns = Namespace("https://kairos.cnext.eu/source/testapp#")
        conn_type = g.value(ns["testapp"], KAIROS_BRONZE.connectionType)
        assert str(conn_type) == "jdbc"

    def test_deprecated_table_gets_owl_deprecated(self, existing_vocab_file):
        """Removed tables should be marked owl:deprecated true."""
        ttl, _ = merge_with_existing(VALID_YAML_DATA, existing_vocab_file)
        g = Graph()
        g.parse(data=ttl, format="turtle")
        ns = Namespace("https://kairos.cnext.eu/source/testapp#")
        deprecated = g.value(ns["tblOldTable"], OWL.deprecated)
        assert str(deprecated).lower() == "true"

    def test_deprecated_column_gets_owl_deprecated(self, existing_vocab_file):
        """Removed columns should be marked owl:deprecated true."""
        ttl, _ = merge_with_existing(VALID_YAML_DATA, existing_vocab_file)
        g = Graph()
        g.parse(data=ttl, format="turtle")
        ns = Namespace("https://kairos.cnext.eu/source/testapp#")
        deprecated = g.value(ns["tblClient_OldColumn"], OWL.deprecated)
        assert str(deprecated).lower() == "true"

    def test_output_is_valid_turtle(self, existing_vocab_file):
        """Merged output should be parseable Turtle."""
        ttl, _ = merge_with_existing(VALID_YAML_DATA, existing_vocab_file)
        g = Graph()
        g.parse(data=ttl, format="turtle")
        assert len(g) > 0

    def test_updates_database_schema(self, existing_vocab_file):
        """Connection info should be updated from YAML."""
        ttl, _ = merge_with_existing(VALID_YAML_DATA, existing_vocab_file)
        g = Graph()
        g.parse(data=ttl, format="turtle")
        ns = Namespace("https://kairos.cnext.eu/source/testapp#")
        db = str(g.value(ns["testapp"], KAIROS_BRONZE.database))
        assert db == "bronze_db"


# --------------------------------------------------------------------------- #
# Orchestration Tests
# --------------------------------------------------------------------------- #


class TestRunImportSource:
    def test_fresh_generation(self, valid_yaml_file, tmp_path):
        output_dir = tmp_path / "output"
        result_path, report = run_import_source(
            valid_yaml_file, output_dir=output_dir
        )
        assert result_path is not None
        assert result_path.exists()
        assert result_path.suffix == ".ttl"
        assert report is None  # Fresh generation, no merge report

    def test_dry_run_no_write(self, valid_yaml_file, tmp_path):
        output_dir = tmp_path / "output"
        result_path, _ = run_import_source(
            valid_yaml_file, output_dir=output_dir, dry_run=True
        )
        assert result_path is None
        assert not output_dir.exists()

    def test_merge_existing(self, valid_yaml_file, tmp_path):
        output_dir = tmp_path / "testapp"
        output_dir.mkdir()
        # Create existing vocab
        existing = output_dir / "testapp.vocabulary.ttl"
        existing.write_text(
            '@prefix testapp: <https://kairos.cnext.eu/source/testapp#> .\n'
            '@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .\n'
            '@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n'
            'testapp:testapp a kairos-bronze:SourceSystem ; rdfs:label "testapp" .\n',
            encoding="utf-8",
        )
        result_path, report = run_import_source(
            valid_yaml_file, output_dir=output_dir
        )
        assert result_path is not None
        assert report is not None
        assert report.has_changes

    def test_system_name_override(self, valid_yaml_file, tmp_path):
        output_dir = tmp_path / "custom"
        result_path, _ = run_import_source(
            valid_yaml_file, system_name="custom", output_dir=output_dir
        )
        assert result_path.name == "custom.vocabulary.ttl"


# --------------------------------------------------------------------------- #
# Change Report Tests
# --------------------------------------------------------------------------- #


class TestChangeReport:
    def test_empty_report(self):
        report = ChangeReport()
        assert not report.has_changes
        assert report.summary() == "No changes"

    def test_summary_with_changes(self):
        report = ChangeReport(
            added_tables=["t1"],
            added_columns=[ColumnChange(table="t1", column="c1", change_type="added")],
        )
        assert report.has_changes
        assert "+1 tables" in report.summary()
        assert "+1 columns" in report.summary()


# Import ColumnChange for the test above
from kairos_ontology.import_source import ColumnChange  # noqa: E402
