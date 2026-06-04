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
    resolve_reference_models,
    load_data_domains,
    _find_ontology_package_dirs,
    _assign_domain_key,
    _domain_display_name,
    SourceAnalysis,
    DomainAffinity,
    TableMatch,
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

MINIMAL_ONTOLOGY_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.org/{domain}#> .

<http://example.org/{domain}> a owl:Ontology ;
    rdfs:label "{label}" .

ex:{cls} a owl:Class ;
    rdfs:label "{cls}" ;
    rdfs:comment "A {cls} entity" .
"""

PLAIN_CLASS_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.org/sub#> .

ex:SubClass a owl:Class ;
    rdfs:label "SubClass" ;
    rdfs:comment "A sub-module class" .
"""


# ---------------------------------------------------------------------------
# Tests: Domain grouping (resolve_reference_models)
# ---------------------------------------------------------------------------


class TestDomainGrouping:
    """Tests for ontology-aware domain grouping in resolve_reference_models."""

    def _write_ontology(self, path, domain="test", label="Test", cls="TestClass"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            MINIMAL_ONTOLOGY_TTL.format(domain=domain, label=label, cls=cls),
            encoding="utf-8",
        )

    def _write_plain(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(PLAIN_CLASS_TTL, encoding="utf-8")

    def test_flat_layout_each_file_own_domain(self, tmp_path):
        """Root-level files → each file is its own domain."""
        self._write_ontology(tmp_path / "party.ttl", "party", "Party", "Party")
        self._write_ontology(tmp_path / "invoice.ttl", "invoice", "Invoice", "Invoice")

        domains = resolve_reference_models(tmp_path)
        names = {d["domain_name"] for d in domains}
        assert "Party" in names
        assert "Invoice" in names
        assert len(domains) == 2

    def test_nested_with_ontology_declarations_groups_by_package_dir(self, tmp_path):
        """Nested dirs with owl:Ontology → group by package directory."""
        self._write_ontology(
            tmp_path / "derived" / "BSP" / "root.ttl", "bsp", "BSP Model", "Vessel"
        )
        self._write_plain(tmp_path / "derived" / "BSP" / "sub.ttl")
        self._write_ontology(
            tmp_path / "derived" / "DCSA" / "root.ttl", "dcsa", "DCSA Model", "Booking"
        )

        domains = resolve_reference_models(tmp_path)
        names = {d["domain_name"] for d in domains}
        # Should produce BSP and DCSA, not "derived"
        assert "BSP" in names or "BSP Model" in names
        assert "DCSA" in names or "DCSA Model" in names
        assert len(domains) == 2

    def test_nested_without_ontology_uses_parent_dir(self, tmp_path):
        """Nested dirs without owl:Ontology → group by parent directory."""
        self._write_plain(tmp_path / "group" / "alpha" / "a.ttl")
        self._write_plain(tmp_path / "group" / "beta" / "b.ttl")

        domains = resolve_reference_models(tmp_path)
        # Should group by parent dir, producing two domains
        assert len(domains) == 2

    def test_exclude_patterns_filters_files(self, tmp_path):
        """--exclude patterns remove files from discovery."""
        self._write_ontology(
            tmp_path / "active" / "party.ttl", "party", "Party", "Party"
        )
        self._write_ontology(
            tmp_path / "archive" / "old.ttl", "old", "Archived", "OldClass"
        )

        domains_all = resolve_reference_models(tmp_path)
        domains_filtered = resolve_reference_models(
            tmp_path, exclude_patterns=["archive/**"]
        )

        assert len(domains_all) == 2
        assert len(domains_filtered) == 1
        assert domains_filtered[0]["domain_name"] == "Party"

    def test_display_name_extracts_leaf(self):
        assert _domain_display_name("derived-ontologies/BSP") == "BSP"
        assert _domain_display_name("party") == "party"
        assert _domain_display_name("a/b/c") == "c"

    def test_find_ontology_package_dirs(self, tmp_path):
        self._write_ontology(tmp_path / "BSP" / "root.ttl", "bsp", "BSP", "V")
        self._write_plain(tmp_path / "BSP" / "sub.ttl")
        self._write_plain(tmp_path / "other" / "plain.ttl")

        all_ttls = sorted(tmp_path.glob("**/*.ttl"))
        pkg_dirs = _find_ontology_package_dirs(all_ttls, tmp_path)

        assert "BSP" in pkg_dirs
        assert "other" not in pkg_dirs

    def test_assign_domain_key_root_file(self, tmp_path):
        ttl = tmp_path / "party.ttl"
        ttl.touch()
        assert _assign_domain_key(ttl, tmp_path, set()) == "party"

    def test_assign_domain_key_package_dir(self, tmp_path):
        ttl = tmp_path / "derived" / "BSP" / "sub.ttl"
        ttl.parent.mkdir(parents=True)
        ttl.touch()
        pkg_dirs = {"derived/BSP"}
        assert _assign_domain_key(ttl, tmp_path, pkg_dirs) == "derived/BSP"

    def test_assign_domain_key_ancestor_package(self, tmp_path):
        ttl = tmp_path / "derived" / "BSP" / "deep" / "sub.ttl"
        ttl.parent.mkdir(parents=True)
        ttl.touch()
        pkg_dirs = {"derived/BSP"}
        assert _assign_domain_key(ttl, tmp_path, pkg_dirs) == "derived/BSP"


class TestLoadDataDomains:
    """Tests for load_data_domains() accelerator pack discovery."""

    def test_loads_data_domains_from_accelerator(self, tmp_path):
        dd_dir = (
            tmp_path / "accelerator-packs" / "logistics"
            / "client-hub-blueprint"
        )
        dd_dir.mkdir(parents=True)
        (dd_dir / "data-domains.yaml").write_text(
            "groups:\n"
            "  - id: core\n"
            "    domains:\n"
            "      - id: party\n"
            "        name: Party & Relations\n"
            "        owns: Business partners, contacts, addresses\n"
            "        does_not_own: Financial transactions\n"
            "      - id: commercial\n"
            "        name: Commercial\n"
            "        owns: Contracts, quotes, pricing\n"
            "        does_not_own: Operational execution\n",
            encoding="utf-8",
        )

        result = load_data_domains(tmp_path)
        assert "party" in result
        assert result["party"]["owns"] == "Business partners, contacts, addresses"
        assert result["party"]["does_not_own"] == "Financial transactions"
        assert result["party"]["group"] == "core"
        assert "commercial" in result

    def test_returns_empty_when_no_file(self, tmp_path):
        result = load_data_domains(tmp_path)
        assert result == {}

    def test_handles_malformed_yaml(self, tmp_path):
        dd_dir = (
            tmp_path / "accelerator-packs" / "test"
            / "client-hub-blueprint"
        )
        dd_dir.mkdir(parents=True)
        (dd_dir / "data-domains.yaml").write_text(
            "not: valid: yaml: {{broken",
            encoding="utf-8",
        )

        result = load_data_domains(tmp_path)
        assert result == {}
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
            "rationale": "Client table contains party-related data",
            "likely_entity": "Party",
            "indicative_columns": ["ClientName", "VATNumber"],
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
        assert result["likely_entity"] == "Party"
        assert "ClientName" in result["indicative_columns"]

    def test_handles_llm_error_gracefully(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API error")

        result = analyse_table_against_domain(
            mock_client, "gpt-5-mini", "tblClient", [], {"domain_name": "X", "classes": []}
        )

        assert result["domain_relevance"] == 0.0
        assert result["indicative_columns"] == []


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
                            domain_relevance=0.82,
                            rationale="Client table maps to Party domain",
                            likely_entity="Party",
                            indicative_columns=["ClientName", "ClientEmail"],
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

        ref_domains = [parse_reference_model(ref_file)]
        with pytest.raises(EnvironmentError, match="GITHUB_TOKEN"):
            analyse_source_system(vocab_file, ref_domains)
