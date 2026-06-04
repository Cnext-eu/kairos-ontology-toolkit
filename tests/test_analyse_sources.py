# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for source affinity analysis and coverage reporting."""

import json
from unittest.mock import MagicMock

import pytest

from kairos_ontology.analyse_sources import (
    parse_source_vocabulary,
    parse_reference_model,
    analyse_table_against_domain,
    analyse_source_system,
    write_analysis_output,
    write_affinity_matrix,
    SourceAnalysis,
    DomainAffinity,
    TableMatch,
    ColumnSuggestion,
)
from kairos_ontology.coverage_report import (
    parse_domain_ontology,
    CoverageReport,
    DomainCoverage,
    ClassAlignment,
    PropertyAlignment,
    write_coverage_yaml,
    write_coverage_markdown,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_VOCAB_TTL = """\
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix testapp: <https://kairos.cnext.eu/source/testapp#> .

testapp:testapp a kairos-bronze:SourceSystem ;
    rdfs:label "testapp" .

testapp:tblClient a kairos-bronze:SourceTable ;
    kairos-bronze:tableName "tblClient" ;
    kairos-bronze:belongsToSystem testapp:testapp .

testapp:tblClient_ClientName a kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "ClientName" ;
    kairos-bronze:dataType "varchar(200)" ;
    kairos-bronze:nullable true ;
    kairos-bronze:sampleValues "Acme NV | Baker BV | Charlie Inc" ;
    kairos-bronze:belongsToTable testapp:tblClient .

testapp:tblClient_VATNumber a kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "VATNumber" ;
    kairos-bronze:dataType "varchar(50)" ;
    kairos-bronze:nullable true ;
    kairos-bronze:sampleValues "BE0123456789 | NL987654321B01" ;
    kairos-bronze:belongsToTable testapp:tblClient .

testapp:tblClient_Email a kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "Email" ;
    kairos-bronze:dataType "varchar(100)" ;
    kairos-bronze:nullable true ;
    kairos-bronze:belongsToTable testapp:tblClient .
"""

SAMPLE_REF_MODEL_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix ref-party: <https://kairos.cnext.eu/ref/party#> .

<https://kairos.cnext.eu/ref/party> a owl:Ontology ;
    rdfs:label "Party" ;
    owl:versionInfo "1.0.0" .

ref-party:Party a owl:Class ;
    rdfs:label "Party" ;
    rdfs:comment "A business party (person or organisation)" .

ref-party:partyName a owl:DatatypeProperty ;
    rdfs:label "Party name" ;
    rdfs:domain ref-party:Party ;
    rdfs:range xsd:string .

ref-party:taxIdentifier a owl:DatatypeProperty ;
    rdfs:label "Tax identifier" ;
    rdfs:domain ref-party:Party ;
    rdfs:range xsd:string .

ref-party:email a owl:DatatypeProperty ;
    rdfs:label "Email address" ;
    rdfs:domain ref-party:Party ;
    rdfs:range xsd:string .
"""

SAMPLE_ONTOLOGY_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix acme: <https://acme.example.com/ontology/client#> .

<https://acme.example.com/ontology/client> a owl:Ontology ;
    rdfs:label "Client" ;
    owl:versionInfo "1.0.0" .

acme:Client a owl:Class ;
    rdfs:label "Client" ;
    rdfs:comment "A client entity" .

acme:clientName a owl:DatatypeProperty ;
    rdfs:label "Client name" ;
    rdfs:domain acme:Client ;
    rdfs:range xsd:string .

acme:vatNumber a owl:DatatypeProperty ;
    rdfs:label "VAT number" ;
    rdfs:domain acme:Client ;
    rdfs:range xsd:string .

acme:customField a owl:DatatypeProperty ;
    rdfs:label "Custom field" ;
    rdfs:domain acme:Client ;
    rdfs:range xsd:string .
"""


# ---------------------------------------------------------------------------
# Tests: Source vocabulary parsing
# ---------------------------------------------------------------------------


class TestParseSourceVocabulary:
    def test_parses_tables_and_columns(self, tmp_path):
        vocab_file = tmp_path / "testapp.vocabulary.ttl"
        vocab_file.write_text(SAMPLE_VOCAB_TTL, encoding="utf-8")

        tables = parse_source_vocabulary(vocab_file)

        assert "tblClient" in tables
        cols = tables["tblClient"]
        assert len(cols) == 3

        names = {c["name"] for c in cols}
        assert names == {"ClientName", "VATNumber", "Email"}

        # Check samples parsed
        client_name = next(c for c in cols if c["name"] == "ClientName")
        assert "Acme NV" in client_name["samples"]

    def test_empty_file_returns_empty(self, tmp_path):
        vocab_file = tmp_path / "empty.vocabulary.ttl"
        vocab_file.write_text(
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n",
            encoding="utf-8",
        )
        tables = parse_source_vocabulary(vocab_file)
        assert tables == {}


# ---------------------------------------------------------------------------
# Tests: Reference model parsing
# ---------------------------------------------------------------------------


class TestParseReferenceModel:
    def test_parses_classes_and_properties(self, tmp_path):
        ref_file = tmp_path / "party.ttl"
        ref_file.write_text(SAMPLE_REF_MODEL_TTL, encoding="utf-8")

        result = parse_reference_model(ref_file)

        assert result["domain_name"] == "Party"
        assert len(result["classes"]) == 1
        assert result["classes"][0]["name"] == "Party"
        assert len(result["classes"][0]["properties"]) == 3

        prop_names = {p["name"] for p in result["classes"][0]["properties"]}
        assert "partyName" in prop_names
        assert "taxIdentifier" in prop_names


# ---------------------------------------------------------------------------
# Tests: Domain ontology parsing
# ---------------------------------------------------------------------------


class TestParseDomainOntology:
    def test_parses_ontology(self, tmp_path):
        ont_file = tmp_path / "client.ttl"
        ont_file.write_text(SAMPLE_ONTOLOGY_TTL, encoding="utf-8")

        result = parse_domain_ontology(ont_file)

        assert result["domain_name"] == "Client"
        assert len(result["classes"]) == 1
        assert result["classes"][0]["name"] == "Client"
        assert len(result["classes"][0]["properties"]) == 3


# ---------------------------------------------------------------------------
# Tests: LLM analysis (mocked)
# ---------------------------------------------------------------------------


class TestAnalyseTableAgainstDomain:
    def test_calls_llm_and_parses_response(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "domain_relevance": 0.85,
            "matches": [
                {
                    "column": "ClientName",
                    "ref_property": "Party.partyName",
                    "confidence": 0.95,
                    "evidence": "Both represent the name of a business entity",
                },
                {
                    "column": "VATNumber",
                    "ref_property": "Party.taxIdentifier",
                    "confidence": 0.90,
                    "evidence": "VAT number is a tax identifier",
                },
            ],
            "unmatched": [
                {"column": "Email", "reason": "Generic field, multiple possible matches"},
            ],
        })
        mock_client.chat.completions.create.return_value = mock_response

        columns = [
            {"name": "ClientName", "data_type": "varchar(200)", "samples": ["Acme NV"]},
            {"name": "VATNumber", "data_type": "varchar(50)", "samples": ["BE0123456789"]},
            {"name": "Email", "data_type": "varchar(100)", "samples": []},
        ]
        domain_summary = {
            "domain_name": "Party",
            "classes": [{"name": "Party", "label": "Party", "properties": [
                {"name": "partyName", "label": "Party name", "range": "string"},
                {"name": "taxIdentifier", "label": "Tax identifier", "range": "string"},
            ]}],
        }

        result = analyse_table_against_domain(
            mock_client, "gpt-5-mini", "tblClient", columns, domain_summary
        )

        assert result["domain_relevance"] == 0.85
        assert len(result["matches"]) == 2
        assert result["matches"][0]["column"] == "ClientName"

    def test_handles_llm_error_gracefully(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API error")

        result = analyse_table_against_domain(
            mock_client, "gpt-5-mini", "tblClient", [], {"domain_name": "X", "classes": []}
        )

        assert result["domain_relevance"] == 0.0
        assert result["matches"] == []


# ---------------------------------------------------------------------------
# Tests: Output writing
# ---------------------------------------------------------------------------


class TestWriteAnalysisOutput:
    def test_writes_yaml(self, tmp_path):
        analysis = SourceAnalysis(
            system="testapp",
            analysed_at="2026-06-04T12:00:00Z",
            model_used="gpt-5-mini",
            domain_affinities=[
                DomainAffinity(
                    domain="Party",
                    ref_model_file="party.ttl",
                    confidence=0.82,
                    matched_tables=[
                        TableMatch(
                            table="tblClient",
                            total_columns=3,
                            matched_columns=2,
                            suggestions=[
                                ColumnSuggestion(
                                    column="ClientName",
                                    ref_property="Party.partyName",
                                    confidence=0.95,
                                    evidence="Name match",
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        )

        output_file = write_analysis_output(analysis, tmp_path)

        assert output_file.exists()
        assert output_file.name == "testapp-affinity.yaml"

        import yaml
        with open(output_file) as f:
            data = yaml.safe_load(f)

        assert data["system"] == "testapp"
        assert data["model_used"] == "gpt-5-mini"
        assert len(data["domain_contributions"]) == 1
        assert data["domain_contributions"][0]["domain"] == "Party"
        assert data["domain_contributions"][0]["confidence"] == 0.82

    def test_writes_affinity_matrix(self, tmp_path):
        analyses = [
            SourceAnalysis(
                system="sys1",
                analysed_at="2026-06-04T12:00:00Z",
                model_used="gpt-5-mini",
                domain_affinities=[
                    DomainAffinity(domain="Party", ref_model_file="party.ttl", confidence=0.8),
                ],
            ),
        ]

        matrix_file = write_affinity_matrix(analyses, tmp_path)

        assert matrix_file.exists()
        assert matrix_file.name == "affinity-matrix.yaml"


# ---------------------------------------------------------------------------
# Tests: Coverage report output
# ---------------------------------------------------------------------------


class TestCoverageReportOutput:
    def test_writes_coverage_yaml(self, tmp_path):
        report = CoverageReport(
            generated_at="2026-06-04T12:00:00Z",
            model_used="gpt-5-mini",
            total_classes=5,
            aligned_classes=3,
            class_coverage_pct=60.0,
            total_properties=20,
            aligned_properties=12,
            property_coverage_pct=60.0,
            domains=[
                DomainCoverage(
                    domain="Client",
                    class_coverage_pct=100.0,
                    property_coverage_pct=67.0,
                    classes=[
                        ClassAlignment(
                            name="Client",
                            label="Client",
                            ref_class="Party",
                            alignment="semantic",
                            confidence=0.9,
                            properties=[
                                PropertyAlignment(
                                    name="clientName",
                                    label="Client name",
                                    ref_property="Party.partyName",
                                    alignment="semantic",
                                    confidence=0.95,
                                    source_columns=["testapp.tblClient.ClientName"],
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        )

        yaml_path = write_coverage_yaml(report, tmp_path / "coverage-report.yaml")
        assert yaml_path.exists()

        import yaml
        with open(yaml_path) as f:
            data = yaml.safe_load(f)

        assert data["summary"]["class_coverage_pct"] == "60.0%"
        assert data["domains"][0]["name"] == "Client"

    def test_writes_coverage_markdown(self, tmp_path):
        report = CoverageReport(
            generated_at="2026-06-04T12:00:00Z",
            model_used="gpt-5-mini",
            total_classes=5,
            aligned_classes=3,
            class_coverage_pct=60.0,
            total_properties=20,
            aligned_properties=12,
            property_coverage_pct=60.0,
            domains=[],
            suggestions=["Consider aligning Client with Party reference model"],
        )

        md_path = write_coverage_markdown(report, tmp_path / "coverage-report.md")
        assert md_path.exists()

        content = md_path.read_text(encoding="utf-8")
        assert "# Ontology Coverage Report" in content
        assert "60.0%" in content
        assert "Improvement Suggestions" in content


# ---------------------------------------------------------------------------
# Tests: Missing GITHUB_TOKEN
# ---------------------------------------------------------------------------


class TestMissingToken:
    def test_analyse_raises_without_token(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)

        vocab_file = tmp_path / "test.vocabulary.ttl"
        vocab_file.write_text(SAMPLE_VOCAB_TTL, encoding="utf-8")

        ref_file = tmp_path / "party.ttl"
        ref_file.write_text(SAMPLE_REF_MODEL_TTL, encoding="utf-8")

        with pytest.raises(EnvironmentError, match="GITHUB_TOKEN"):
            analyse_source_system(vocab_file, [ref_file])
