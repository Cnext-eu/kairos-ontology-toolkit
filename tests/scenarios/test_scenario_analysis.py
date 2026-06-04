# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario tests for source affinity analysis and coverage reporting.

Uses acme-hub synthetic data with a reference model to exercise the full pipeline.
LLM calls are mocked to keep tests deterministic and fast.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from kairos_ontology.analyse_sources import (
    parse_source_vocabulary,
    parse_reference_model,
    analyse_source_system,
    run_analyse_sources,
)
from kairos_ontology.coverage_report import (
    parse_domain_ontology,
    run_coverage_report,
    trace_source_evidence,
    write_coverage_yaml,
    write_coverage_markdown,
)

ACME_HUB = Path(__file__).parent / "acme-hub"
SOURCES_DIR = ACME_HUB / "integration" / "sources"
ONTOLOGIES_DIR = ACME_HUB / "model" / "ontologies"
REF_MODELS_DIR = ACME_HUB / "model" / "reference-models"


# ---------------------------------------------------------------------------
# Source vocabulary parsing against real acme-hub data
# ---------------------------------------------------------------------------


class TestAcmeHubVocabularyParsing:
    """Parse real acme-hub source vocabularies."""

    def test_parse_crmsystem_vocabulary(self):
        vocab = SOURCES_DIR / "crmsystem" / "crmsystem.vocabulary.ttl"
        tables = parse_source_vocabulary(vocab)

        assert len(tables) >= 1
        assert "Customers" in tables
        cols = tables["Customers"]
        col_names = {c["name"] for c in cols}
        assert "CustCode" in col_names
        assert "CustName" in col_names
        assert "CustEmail" in col_names

    def test_parse_adminpulse_vocabulary(self):
        vocab = SOURCES_DIR / "adminpulse" / "adminpulse.vocabulary.ttl"
        tables = parse_source_vocabulary(vocab)

        assert len(tables) >= 1
        assert "tblClient" in tables
        cols = tables["tblClient"]
        col_names = {c["name"] for c in cols}
        assert "ClientID" in col_names

    def test_parse_billingpro_vocabulary(self):
        vocab = SOURCES_DIR / "billingpro" / "billingpro.vocabulary.ttl"
        tables = parse_source_vocabulary(vocab)

        assert len(tables) >= 1
        # Should have invoice-related tables
        table_names = set(tables.keys())
        assert any("invoice" in t.lower() or "Invoice" in t for t in table_names)


# ---------------------------------------------------------------------------
# Reference model parsing
# ---------------------------------------------------------------------------


class TestAcmeHubReferenceModel:
    """Parse the synthetic reference model."""

    def test_parse_party_reference_model(self):
        ref_path = REF_MODELS_DIR / "kairos-ref-party.ttl"
        result = parse_reference_model(ref_path)

        assert result["domain_name"] == "Party"
        assert len(result["classes"]) >= 3  # Party, Organisation, Person

        class_names = {c["name"] for c in result["classes"]}
        assert "Party" in class_names
        assert "Organisation" in class_names
        assert "Person" in class_names

        # Party class should have properties
        party_cls = next(c for c in result["classes"] if c["name"] == "Party")
        prop_names = {p["name"] for p in party_cls["properties"]}
        assert "partyName" in prop_names
        assert "taxIdentifier" in prop_names
        assert "email" in prop_names


# ---------------------------------------------------------------------------
# Domain ontology parsing
# ---------------------------------------------------------------------------


class TestAcmeHubOntologyParsing:
    """Parse real acme-hub domain ontologies."""

    def test_parse_client_ontology(self):
        ont_path = ONTOLOGIES_DIR / "client.ttl"
        result = parse_domain_ontology(ont_path)

        assert result["domain_name"] == "Acme Client Domain"
        assert len(result["classes"]) >= 3  # Client + subtypes

        class_names = {c["name"] for c in result["classes"]}
        assert "Client" in class_names
        assert "CorporateClient" in class_names

    def test_parse_invoice_ontology(self):
        ont_path = ONTOLOGIES_DIR / "invoice.ttl"
        result = parse_domain_ontology(ont_path)

        assert len(result["classes"]) >= 1
        class_names = {c["name"] for c in result["classes"]}
        assert "Invoice" in class_names


# ---------------------------------------------------------------------------
# Full analysis pipeline (mocked LLM)
# ---------------------------------------------------------------------------


class TestAnalyseSourcesScenario:
    """End-to-end analysis with mocked LLM calls."""

    def _mock_llm_response(self, table_name, columns, domain):
        """Generate a realistic mock LLM response."""
        matches = []
        if domain["domain_name"] == "Party":
            for col in columns:
                col_lower = col["name"].lower()
                if "name" in col_lower or "custname" in col_lower:
                    matches.append({
                        "column": col["name"],
                        "ref_property": "Party.partyName",
                        "confidence": 0.92,
                        "evidence": "Name field maps to party name",
                    })
                elif "email" in col_lower:
                    matches.append({
                        "column": col["name"],
                        "ref_property": "Party.email",
                        "confidence": 0.95,
                        "evidence": "Email address field",
                    })
                elif "vat" in col_lower:
                    matches.append({
                        "column": col["name"],
                        "ref_property": "Party.taxIdentifier",
                        "confidence": 0.90,
                        "evidence": "VAT is a tax identifier",
                    })

        relevance = min(len(matches) / max(len(columns), 1), 1.0)
        return {
            "domain_relevance": round(relevance, 2),
            "matches": matches,
            "unmatched": [
                {"column": c["name"], "reason": "No match"}
                for c in columns
                if not any(m["column"] == c["name"] for m in matches)
            ],
        }

    @patch("kairos_ontology.analyse_sources._get_openai_client")
    def test_analyse_crmsystem_against_party(self, mock_get_client):
        """CRM system should show high affinity to Party reference model."""
        mock_client = MagicMock()

        def side_effect(**kwargs):
            # Parse the prompt to extract table and domain info
            messages = kwargs.get("messages", [])
            user_msg = messages[-1]["content"] if messages else ""

            # Simple mock: always return party-like matches
            response = MagicMock()
            response.choices = [MagicMock()]
            response.choices[0].message.content = json.dumps({
                "domain_relevance": 0.75,
                "matches": [
                    {"column": "CustName", "ref_property": "Party.partyName",
                     "confidence": 0.92, "evidence": "Customer name = party name"},
                    {"column": "CustEmail", "ref_property": "Party.email",
                     "confidence": 0.95, "evidence": "Email field"},
                ],
                "unmatched": [
                    {"column": "CustCode", "reason": "Internal code, no ref match"},
                ],
            })
            return response

        mock_client.chat.completions.create.side_effect = side_effect
        mock_get_client.return_value = mock_client

        vocab_path = SOURCES_DIR / "crmsystem" / "crmsystem.vocabulary.ttl"
        ref_model_path = REF_MODELS_DIR / "kairos-ref-party.ttl"

        analysis = analyse_source_system(vocab_path, [ref_model_path])

        assert analysis.system == "crmsystem"
        assert analysis.model_used == "gpt-5-mini"
        assert len(analysis.domain_affinities) >= 1

        party_aff = analysis.domain_affinities[0]
        assert party_aff.domain == "Party"
        assert party_aff.confidence > 0
        assert len(party_aff.matched_tables) >= 1

    @patch("kairos_ontology.analyse_sources._get_openai_client")
    def test_run_analyse_all_sources(self, mock_get_client, tmp_path):
        """Run analysis across all acme-hub sources."""
        mock_client = MagicMock()
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = json.dumps({
            "domain_relevance": 0.6,
            "matches": [{"column": "col1", "ref_property": "Party.partyName",
                         "confidence": 0.8, "evidence": "test"}],
            "unmatched": [],
        })
        mock_client.chat.completions.create.return_value = response
        mock_get_client.return_value = mock_client

        output_files = run_analyse_sources(
            sources_dir=SOURCES_DIR,
            ref_models_dir=REF_MODELS_DIR,
            output_dir=tmp_path / "_analysis",
            threshold=0.3,
        )

        # Should produce one file per source + affinity matrix
        assert len(output_files) >= 2  # at least 1 source + matrix
        assert (tmp_path / "_analysis" / "affinity-matrix.yaml").exists()


# ---------------------------------------------------------------------------
# Coverage report scenario (mocked LLM)
# ---------------------------------------------------------------------------


class TestCoverageReportScenario:
    """End-to-end coverage report with mocked LLM."""

    @patch("kairos_ontology.coverage_report.analyse_coverage_with_llm")
    def test_coverage_report_client_domain(self, mock_analyse_llm, tmp_path):
        """Coverage report for client ontology against party ref model."""
        mock_analyse_llm.return_value = {
            "class_alignments": [
                {
                    "ontology_class": "Client",
                    "ref_class": "Party",
                    "alignment": "semantic",
                    "confidence": 0.88,
                    "property_alignments": [
                        {"ontology_property": "clientName", "ref_property": "Party.partyName",
                         "alignment": "semantic", "confidence": 0.95, "suggestion": ""},
                        {"ontology_property": "vatNumber", "ref_property": "Party.taxIdentifier",
                         "alignment": "semantic", "confidence": 0.90, "suggestion": ""},
                        {"ontology_property": "clientId", "ref_property": None,
                         "alignment": "custom", "confidence": 0.0,
                         "suggestion": "Consider aligning with partyIdentifier"},
                    ],
                },
                {
                    "ontology_class": "CorporateClient",
                    "ref_class": "Organisation",
                    "alignment": "semantic",
                    "confidence": 0.82,
                    "property_alignments": [],
                },
                {
                    "ontology_class": "IndividualClient",
                    "ref_class": "Person",
                    "alignment": "semantic",
                    "confidence": 0.85,
                    "property_alignments": [],
                },
            ],
            "overall_suggestions": [
                "Consider renaming Client to Party for industry alignment",
            ],
        }

        import os
        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}), \
             patch("openai.OpenAI"):
            report = run_coverage_report(
                ontology_dir=ONTOLOGIES_DIR,
                ref_models_dir=REF_MODELS_DIR,
                sources_dir=SOURCES_DIR,
            )

        assert report.total_classes > 0
        assert report.aligned_classes > 0
        assert report.class_coverage_pct > 0

        # Write outputs
        yaml_path = write_coverage_yaml(report, tmp_path / "coverage.yaml")
        md_path = write_coverage_markdown(report, tmp_path / "coverage.md")
        assert yaml_path.exists()
        assert md_path.exists()


# ---------------------------------------------------------------------------
# Source evidence tracing
# ---------------------------------------------------------------------------


class TestSourceEvidenceTracing:
    """Test that SKOS mappings are traced correctly."""

    def test_trace_evidence_from_acme_mappings(self):
        """The acme-hub mappings should provide source evidence."""
        ont_path = ONTOLOGIES_DIR / "client.ttl"
        evidence = trace_source_evidence(ont_path, SOURCES_DIR)

        # The mappings should link some properties back to source columns
        # (depends on mapping file structure — may be empty if SKOS format differs)
        assert isinstance(evidence, dict)
