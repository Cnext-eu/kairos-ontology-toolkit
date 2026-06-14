# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the import-source module (YAML parsing, TTL generation, merge)."""

import pytest
from rdflib import Graph, Namespace
from rdflib.namespace import RDF, RDFS, OWL

from kairos_ontology.import_source import (
    validate_source_schema,
    parse_source_schema,
    generate_vocabulary_ttl,
    generate_vocabulary_per_table,
    merge_with_existing,
    run_import_source,
    ChangeReport,
    KAIROS_BRONZE,
    _sanitize_uri_part,
    _column_uri,
    _table_uri,
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

    def test_provenance_header_stamped(self):
        # DD-072: generated vocabulary carries a toolkit provenance comment.
        ttl = generate_vocabulary_ttl(VALID_YAML_DATA)
        assert ttl.startswith("#")
        assert "kairos-ontology-toolkit" in ttl
        assert "Generator : import-source" in ttl
        # Header must not break parsing.
        Graph().parse(data=ttl, format="turtle")

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
from kairos_ontology.import_source import parse_source_schema_dir  # noqa: E402


class TestParseSourceSchemaDir:
    """Tests for directory-based schema parsing with .samples.yaml merge."""

    def test_merges_samples_from_samples_yaml(self, tmp_path):
        """parse_source_schema_dir merges per-column samples from .samples.yaml."""
        import yaml

        system_dir = tmp_path / "testapp"
        system_dir.mkdir()

        # Write manifest
        manifest = {"version": "1.1", "system": "testapp", "platform": "fabric",
                    "tables": ["tblClient"]}
        (system_dir / "_manifest.yaml").write_text(
            yaml.dump(manifest, default_flow_style=False), encoding="utf-8")

        # Write table YAML (no inline samples)
        table_data = {
            "name": "tblClient",
            "schema": "bronze",
            "row_count": 10,
            "columns": [
                {"name": "id", "data_type": "int", "ordinal_position": 1, "nullable": False},
                {"name": "name", "data_type": "varchar(100)", "ordinal_position": 2, "nullable": True},
            ],
        }
        (system_dir / "tblClient.yaml").write_text(
            yaml.dump(table_data, default_flow_style=False), encoding="utf-8")

        # Write .samples.yaml with row data
        samples_data = {
            "extracted_at": "2026-06-01T10:00:00Z",
            "table": "tblClient",
            "schema": "bronze",
            "rows": [
                {"id": "1", "name": "Acme NV"},
                {"id": "2", "name": "Baker BV"},
                {"id": "3", "name": "Acme NV"},  # duplicate
            ],
        }
        (system_dir / "tblClient.samples.yaml").write_text(
            yaml.dump(samples_data, default_flow_style=False), encoding="utf-8")

        result = parse_source_schema_dir(system_dir)

        assert len(result["tables"]) == 1
        cols = result["tables"][0]["columns"]
        # id column should have unique samples
        assert cols[0]["samples"] == ["1", "2", "3"]
        # name column should have unique samples (deduped)
        assert cols[1]["samples"] == ["Acme NV", "Baker BV"]

    def test_no_samples_when_no_samples_yaml(self, tmp_path):
        """No samples merged when .samples.yaml doesn't exist."""
        import yaml

        system_dir = tmp_path / "testapp"
        system_dir.mkdir()

        manifest = {"version": "1.1", "system": "testapp", "platform": "fabric",
                    "tables": ["tblClient"]}
        (system_dir / "_manifest.yaml").write_text(
            yaml.dump(manifest, default_flow_style=False), encoding="utf-8")

        table_data = {
            "name": "tblClient", "schema": "bronze", "row_count": 5,
            "columns": [{"name": "id", "data_type": "int", "ordinal_position": 1, "nullable": False}],
        }
        (system_dir / "tblClient.yaml").write_text(
            yaml.dump(table_data, default_flow_style=False), encoding="utf-8")

        result = parse_source_schema_dir(system_dir)
        assert "samples" not in result["tables"][0]["columns"][0]

    def test_preserves_existing_inline_samples(self, tmp_path):
        """If table YAML already has inline samples (old format), they are preserved."""
        import yaml

        system_dir = tmp_path / "testapp"
        system_dir.mkdir()

        manifest = {"version": "1.1", "system": "testapp", "platform": "fabric",
                    "tables": ["tblClient"]}
        (system_dir / "_manifest.yaml").write_text(
            yaml.dump(manifest, default_flow_style=False), encoding="utf-8")

        # Table with inline samples (backward compat)
        table_data = {
            "name": "tblClient", "schema": "bronze", "row_count": 5,
            "columns": [{"name": "id", "data_type": "int", "ordinal_position": 1,
                         "nullable": False, "samples": ["OLD1", "OLD2"]}],
        }
        (system_dir / "tblClient.yaml").write_text(
            yaml.dump(table_data, default_flow_style=False), encoding="utf-8")

        # .samples.yaml exists but inline should take precedence
        samples_data = {"table": "tblClient", "schema": "bronze",
                        "rows": [{"id": "NEW1"}, {"id": "NEW2"}]}
        (system_dir / "tblClient.samples.yaml").write_text(
            yaml.dump(samples_data, default_flow_style=False), encoding="utf-8")

        result = parse_source_schema_dir(system_dir)
        # Should keep the old inline samples
        assert result["tables"][0]["columns"][0]["samples"] == ["OLD1", "OLD2"]


class TestImportSourceHubRootDetection:
    """Tests that run_import_source detects ontology-hub/ subfolder."""

    def test_output_dir_resolves_to_ontology_hub(self, valid_yaml_file, tmp_path, monkeypatch):
        """When CWD has ontology-hub/model/ontologies/, output goes inside ontology-hub/."""
        hub = tmp_path / "ontology-hub"
        (hub / "model" / "ontologies").mkdir(parents=True)

        monkeypatch.chdir(tmp_path)
        result_path, _ = run_import_source(valid_yaml_file)
        assert result_path is not None
        # Should write inside ontology-hub/integration/sources/
        assert "ontology-hub" in str(result_path)
        assert result_path.parent.name == "testapp"
        assert "integration" in str(result_path)

    def test_freshly_scaffolded_hub_resolves(self, valid_yaml_file, tmp_path, monkeypatch):
        """When ontology-hub/ has model/ but not model/ontologies/, still resolves."""
        hub = tmp_path / "ontology-hub"
        (hub / "model").mkdir(parents=True)
        (hub / "integration").mkdir(parents=True)

        monkeypatch.chdir(tmp_path)
        result_path, _ = run_import_source(valid_yaml_file)
        assert result_path is not None
        assert "ontology-hub" in str(result_path)
        assert "integration" in str(result_path)


# --------------------------------------------------------------------------- #
# Split-Tables Tests
# --------------------------------------------------------------------------- #


class TestGenerateVocabularyPerTable:
    def test_generates_one_ttl_per_table(self):
        """Should return one TTL string per table."""
        result = generate_vocabulary_per_table(VALID_YAML_DATA)
        assert len(result) == 2
        assert "tblClient" in result
        assert "tblInvoice" in result

    def test_each_ttl_is_valid_turtle(self):
        """Each per-table TTL should be parseable."""
        result = generate_vocabulary_per_table(VALID_YAML_DATA)
        for tbl_name, ttl_str in result.items():
            g = Graph()
            g.parse(data=ttl_str, format="turtle")
            assert len(g) > 0

    def test_per_table_contains_only_own_columns(self):
        """tblClient TTL should not contain tblInvoice columns."""
        result = generate_vocabulary_per_table(VALID_YAML_DATA)
        g = Graph()
        g.parse(data=result["tblClient"], format="turtle")
        ns = Namespace("https://kairos.cnext.eu/source/testapp#")
        # tblClient columns should be present
        assert (ns["tblClient_ClientId"], None, None) in g
        # tblInvoice columns should NOT be present
        assert (ns["tblInvoice_InvoiceId"], None, None) not in g

    def test_per_table_has_ontology_declaration(self):
        """Each per-table TTL should have an owl:Ontology declaration."""
        result = generate_vocabulary_per_table(VALID_YAML_DATA)
        g = Graph()
        g.parse(data=result["tblClient"], format="turtle")
        ontologies = list(g.subjects(RDF.type, OWL.Ontology))
        assert len(ontologies) == 1

    def test_per_table_has_system_reference(self):
        """Each per-table TTL should reference the source system."""
        result = generate_vocabulary_per_table(VALID_YAML_DATA)
        g = Graph()
        g.parse(data=result["tblClient"], format="turtle")
        ns = Namespace("https://kairos.cnext.eu/source/testapp#")
        assert (ns["testapp"], RDF.type, KAIROS_BRONZE.SourceSystem) in g


class TestRunImportSourceSplitTables:
    def test_split_tables_creates_vocabulary_dir(self, valid_yaml_file, tmp_path):
        """--split-tables should create vocabulary/ subfolder with per-table TTLs."""
        output_dir = tmp_path / "output"
        result_path, report = run_import_source(
            valid_yaml_file, output_dir=output_dir, split_tables=True
        )
        assert result_path is not None
        assert result_path.name == "vocabulary"
        assert result_path.is_dir()
        ttl_files = list(result_path.glob("*.vocabulary.ttl"))
        assert len(ttl_files) == 2
        names = sorted(f.stem.replace(".vocabulary", "") for f in ttl_files)
        assert names == ["tblClient", "tblInvoice"]

    def test_split_tables_dry_run(self, valid_yaml_file, tmp_path):
        """--split-tables --dry-run should not create files."""
        output_dir = tmp_path / "output"
        result_path, _ = run_import_source(
            valid_yaml_file, output_dir=output_dir, split_tables=True, dry_run=True
        )
        assert result_path is None
        assert not (output_dir / "vocabulary").exists()


# --------------------------------------------------------------------------- #
# Fix 4: No auto-generated rdfs:comment with "Examples:" text
# --------------------------------------------------------------------------- #


class TestNoExamplesComment:
    """Fix 4: rdfs:comment should not contain auto-generated 'Examples:' text."""

    def test_vocabulary_ttl_has_no_examples_comment(self):
        """generate_vocabulary_ttl should not produce rdfs:comment with Examples."""
        data = {
            "version": "1.0",
            "system": "test",
            "platform": "fabric",
            "extracted_at": "2026-01-01T00:00:00Z",
            "connection": {},
            "tables": [
                {
                    "name": "orders",
                    "columns": [
                        {
                            "name": "status",
                            "data_type": "varchar(max)",
                            "nullable": False,
                            "samples": ["active", "closed", "pending"],
                        },
                    ],
                },
            ],
        }
        ttl = generate_vocabulary_ttl(data)
        g = Graph()
        g.parse(data=ttl, format="turtle")

        # Check no rdfs:comment contains "Examples:"
        for _, _, comment in g.triples((None, RDFS.comment, None)):
            assert "Examples:" not in str(comment), (
                f"Found auto-generated 'Examples:' in rdfs:comment: {comment}"
            )

    def test_per_table_ttl_has_no_examples_comment(self):
        """generate_vocabulary_per_table should not produce rdfs:comment with Examples."""
        data = {
            "version": "1.1",
            "system": "test",
            "platform": "fabric",
            "extracted_at": "2026-01-01T00:00:00Z",
            "connection": {},
            "tables": [
                {
                    "name": "items",
                    "columns": [
                        {
                            "name": "sku",
                            "data_type": "varchar(max)",
                            "nullable": False,
                            "samples": ["ABC-001", "XYZ-999"],
                        },
                    ],
                },
            ],
        }
        per_table = generate_vocabulary_per_table(data)
        for tbl_name, ttl in per_table.items():
            g = Graph()
            g.parse(data=ttl, format="turtle")
            for _, _, comment in g.triples((None, RDFS.comment, None)):
                assert "Examples:" not in str(comment), (
                    f"Found auto-generated 'Examples:' in {tbl_name}: {comment}"
                )

    def test_sample_values_still_present(self):
        """sampleValues annotation should still be emitted."""
        data = {
            "version": "1.0",
            "system": "test",
            "platform": "fabric",
            "extracted_at": "2026-01-01T00:00:00Z",
            "connection": {},
            "tables": [
                {
                    "name": "t",
                    "columns": [
                        {
                            "name": "c",
                            "data_type": "varchar(max)",
                            "nullable": False,
                            "samples": ["a", "b"],
                        },
                    ],
                },
            ],
        }
        ttl = generate_vocabulary_ttl(data)
        g = Graph()
        g.parse(data=ttl, format="turtle")
        sample_triples = list(g.triples((None, KAIROS_BRONZE.sampleValues, None)))
        assert len(sample_triples) > 0


# --------------------------------------------------------------------------- #
# Fix 5: URI sanitization for column names with embedded quotes
# --------------------------------------------------------------------------- #


class TestSanitizeUriPart:
    """Fix 5: _sanitize_uri_part strips URI-unsafe characters."""

    def test_strips_double_quotes(self):
        assert _sanitize_uri_part('"ID"') == "ID"

    def test_strips_spaces(self):
        assert _sanitize_uri_part("My Column") == "MyColumn"

    def test_strips_angle_brackets(self):
        assert _sanitize_uri_part("<value>") == "value"

    def test_normal_name_unchanged(self):
        assert _sanitize_uri_part("ClientId") == "ClientId"

    def test_mixed_unsafe_chars(self):
        assert _sanitize_uri_part('"Col Name"') == "ColName"


class TestColumnUriSanitization:
    """Fix 5: _column_uri and _table_uri handle quoted names."""

    def test_column_uri_strips_quotes(self):
        ns = Namespace("https://example.com/source#")
        uri = _column_uri(ns, "tbl", '"ID"')
        assert '"' not in str(uri)
        assert str(uri).endswith("tbl_ID")

    def test_table_uri_strips_quotes(self):
        ns = Namespace("https://example.com/source#")
        uri = _table_uri(ns, '"MyTable"')
        assert '"' not in str(uri)
        assert str(uri).endswith("MyTable")

    def test_oracle_style_column_produces_valid_ttl(self):
        """A graph with Oracle-style quoted column names should serialize cleanly."""
        ns = Namespace("https://kairos.cnext.eu/source/oracle-test#")
        g = Graph()
        col_uri = _column_uri(ns, "SOL__SREPORTSPATTERN", '"ID"')
        g.add((col_uri, RDF.type, KAIROS_BRONZE.SourceColumn))
        # This should NOT raise during serialization
        ttl = g.serialize(format="turtle")
        assert "SOL__SREPORTSPATTERN_ID" in ttl
