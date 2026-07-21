# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""CLI contracts for structured semantic inspection (issue #224)."""

import json

from click.testing import CliRunner

from kairos_ontology.cli.main import cli


ONTOLOGY = """\
@prefix ex: <https://example.org/domain#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<https://example.org/domain> a owl:Ontology ; owl:versionInfo "1.0" .
ex:Party a owl:Class ; rdfs:label "Party" .
ex:name a owl:DatatypeProperty ; rdfs:domain ex:Party ; rdfs:label "Name" .
"""


def test_resolve_ontology_json_contract(tmp_path):
    ontology = tmp_path / "domain.ttl"
    ontology.write_text(ONTOLOGY, encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        ["resolve-ontology", str(ontology), "--json-output"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_version"] == 1
    assert payload["import_complete"] is True
    assert len(payload["closure_hash"]) == 64
    assert payload["manifest"][0]["ontology_iri"] == "https://example.org/domain"


def test_show_class_inventory_discloses_slice_coverage(tmp_path):
    ontology = tmp_path / "domain.ttl"
    ontology.write_text(ONTOLOGY, encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "show-class-inventory",
            "--ontology",
            str(ontology),
            "--max-classes",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["metadata"]["semantic_profile"] == "kairos-design"
    assert payload["metadata"]["included_class_count"] == 1
    assert payload["classes"][0]["uri"] == "https://example.org/domain#Party"


def test_explain_term_requires_full_uri_and_returns_provenance(tmp_path):
    ontology = tmp_path / "domain.ttl"
    ontology.write_text(ONTOLOGY, encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "explain-term",
            "https://example.org/domain#Party",
            "--ontology",
            str(ontology),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["term"]["uri"] == "https://example.org/domain#Party"
    assert payload["term"]["provenance"]["source_identity"] == "https://example.org/domain"


def test_show_source_schema_returns_parsed_tables(tmp_path):
    sources = tmp_path / "sources"
    system_dir = sources / "erp"
    system_dir.mkdir(parents=True)
    (system_dir / "erp.ttl").write_text(
        """\
@prefix kb: <https://kairos.cnext.eu/bronze#> .
@prefix ex: <urn:source:> .
ex:Customer a kb:SourceTable ; kb:tableName "Customer" .
ex:Customer_Id a kb:SourceColumn ;
    kb:columnName "Id" ;
    kb:dataType "integer" ;
    kb:belongsToTable ex:Customer .
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        ["show-source-schema", "--system", "erp", "--sources", str(sources)],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["system"] == "erp"
    assert payload["table_count"] == 1
    assert payload["tables"]["Customer"][0]["name"] == "Id"
