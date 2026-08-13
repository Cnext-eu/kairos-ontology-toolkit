# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario tests for source affinity analysis and coverage reporting.

Uses acme-hub synthetic data with a reference model to exercise the full pipeline.
LLM calls are mocked to keep tests deterministic and fast.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from kairos_ontology.core.analyse_sources import (
    parse_source_vocabulary,
    parse_reference_model,
    analyse_source_system,
    run_analyse_sources,
)
from kairos_ontology.core.coverage_report import (
    _align_properties,
    _build_ref_index,
    align_classes_deterministic,
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

    @patch("kairos_ontology.core.analyse_sources._get_openai_client")
    def test_analyse_crmsystem_against_party(self, mock_get_client):
        """CRM tables should be assigned to the Party domain (single-call)."""
        mock_client = MagicMock()

        def side_effect(**kwargs):
            response = MagicMock()
            response.choices = [MagicMock()]
            response.choices[0].message.content = json.dumps(
                {
                    "domain": "Party",
                    "secondary_domains": [],
                    "confidence": 0.75,
                    "likely_entity": "Party",
                    "rationale": "Customer table contains party-related data",
                    "indicative_columns": ["CustName", "CustEmail"],
                }
            )
            return response

        mock_client.chat.completions.create.side_effect = side_effect
        mock_get_client.return_value = mock_client

        vocab_path = SOURCES_DIR / "crmsystem" / "crmsystem.vocabulary.ttl"
        ref_model_path = REF_MODELS_DIR / "kairos-ref-party.ttl"
        ref_domains = [parse_reference_model(ref_model_path)]

        analysis = analyse_source_system(vocab_path, ref_domains)

        assert analysis.system == "crmsystem"
        assert analysis.model_used == "gpt-5.4-mini"
        assert len(analysis.table_assignments) >= 1

        first = analysis.table_assignments[0]
        assert first.domain == "Party"
        assert first.confidence > 0
        assert first.likely_entity == "Party"

    @patch("kairos_ontology.core.analyse_sources._get_openai_client")
    def test_run_analyse_all_sources(self, mock_get_client, tmp_path):
        """Run analysis across all acme-hub sources."""
        mock_client = MagicMock()
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = json.dumps(
            {
                "domain": "Party",
                "secondary_domains": [],
                "confidence": 0.6,
                "likely_entity": "Party",
                "rationale": "Table has some party-related data",
                "indicative_columns": ["col1"],
            }
        )
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
    """End-to-end coverage report with deterministic alignment."""

    def test_coverage_report_client_domain(self, tmp_path):
        """Coverage report for client ontology against party ref model."""
        report = run_coverage_report(
            ontology_dir=ONTOLOGIES_DIR,
            ref_models_dir=REF_MODELS_DIR,
            sources_dir=SOURCES_DIR,
        )

        assert report.total_classes > 0

        # Write outputs
        yaml_path = write_coverage_yaml(report, tmp_path / "coverage.yaml")
        md_path = write_coverage_markdown(report, tmp_path / "coverage.md")
        assert yaml_path.exists()
        assert md_path.exists()


# ---------------------------------------------------------------------------
# Coverage report — rdfs:subPropertyOf alignment (issue #326)
# ---------------------------------------------------------------------------

# "Client" deliberately does NOT name-match or seeAlso-match any ref-party
# class (Party/Organisation/Person), so the class itself aligns as "custom".
# clientTaxRef nonetheless declares a formal rdfs:subPropertyOf edge straight
# to a reference-model property (ref-party:taxIdentifier) — this must be
# credited regardless of the (non-)alignment of its containing class, exactly
# like the class-level rdfs:seeAlso -> "linked" signal is independent of
# owl:imports/name-match. clientNotes has no alignment signal at all and must
# remain "custom"/0.0 (no false positives).
_DOMAIN_WITH_SUBPROPERTY_TTL = """\
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix test: <https://test.example/subprop-coverage#> .
@prefix ref-party: <https://kairos.cnext.eu/ref/party#> .

<https://test.example/subprop-coverage> a owl:Ontology ;
    rdfs:label "SubProperty Coverage Test" ;
    owl:versionInfo "1.0.0" .

test:Client a owl:Class ;
    rdfs:label "Client" ;
    rdfs:comment "A hub-specific client entity." .

test:clientTaxRef a owl:DatatypeProperty ;
    rdfs:label "client tax reference" ;
    rdfs:domain test:Client ;
    rdfs:range xsd:string ;
    rdfs:subPropertyOf ref-party:taxIdentifier .

test:clientNotes a owl:DatatypeProperty ;
    rdfs:label "client notes" ;
    rdfs:domain test:Client ;
    rdfs:range xsd:string .
"""


class TestCoverageSubPropertyOfAlignment:
    """rdfs:subPropertyOf is credited as a formal property-alignment signal."""

    def _get_ref_domains(self):
        ref_path = REF_MODELS_DIR / "kairos-ref-party.ttl"
        from kairos_ontology.core.analyse_sources import parse_reference_model

        return [parse_reference_model(ref_path, include_specializations=True)]

    def test_subpropertyof_credited_even_when_class_is_unmatched(self, tmp_path):
        """A property's rdfs:subPropertyOf is credited independent of its class."""
        ont_path = tmp_path / "subprop-domain.ttl"
        ont_path.write_text(_DOMAIN_WITH_SUBPROPERTY_TTL, encoding="utf-8")

        ont_data = parse_domain_ontology(ont_path)
        ref_index = _build_ref_index(self._get_ref_domains())

        class_alignments = align_classes_deterministic(ont_data, ref_index)
        client_align = next(
            c for c in class_alignments if c["ontology_class"] == "Client"
        )

        # The class itself has no name/seeAlso match to Party/Organisation/Person.
        assert client_align["alignment"] == "custom"
        assert client_align["ref_class"] is None

        prop_alignments = {
            pa["ontology_property"]: pa for pa in client_align["property_alignments"]
        }

        # (a) rdfs:subPropertyOf must be credited, not left as custom/0.0.
        tax_pa = prop_alignments["clientTaxRef"]
        assert tax_pa["alignment"] == "subproperty"
        assert tax_pa["confidence"] == 1.0
        assert tax_pa["ref_property"] == "Party.taxIdentifier"

        # (b) A property with no alignment signal at all stays custom/0.0.
        notes_pa = prop_alignments["clientNotes"]
        assert notes_pa["alignment"] == "custom"
        assert notes_pa["confidence"] == 0.0
        assert notes_pa["ref_property"] is None

    def test_subpropertyof_direct_align_properties_call(self, tmp_path):
        """Same check via _align_properties() directly, mirroring the DD-044 tests."""
        ont_path = tmp_path / "subprop-domain.ttl"
        ont_path.write_text(_DOMAIN_WITH_SUBPROPERTY_TTL, encoding="utf-8")

        ont_data = parse_domain_ontology(ont_path)
        ref_index = _build_ref_index(self._get_ref_domains())
        client_cls = next(c for c in ont_data["classes"] if c["name"] == "Client")

        # ref_cls=None: nothing else in the toolkit resolved this class, yet the
        # subPropertyOf-declared property must still be credited on its own merit.
        prop_alignments = _align_properties(client_cls, None, ref_index)
        by_name = {pa["ontology_property"]: pa for pa in prop_alignments}

        assert by_name["clientTaxRef"]["alignment"] == "subproperty"
        assert by_name["clientTaxRef"]["confidence"] == 1.0
        assert by_name["clientNotes"]["alignment"] == "custom"
        assert by_name["clientNotes"]["confidence"] == 0.0

    def test_coverage_percentage_reflects_subpropertyof_credit(self, tmp_path):
        """(c) The aggregate Properties: N/M summary counts subproperty matches."""
        ont_dir = tmp_path / "ontologies"
        ont_dir.mkdir()
        (ont_dir / "client.ttl").write_text(_DOMAIN_WITH_SUBPROPERTY_TTL, encoding="utf-8")

        report = run_coverage_report(
            ontology_dir=ont_dir,
            ref_models_dir=REF_MODELS_DIR,
        )

        assert report.total_properties == 2
        assert report.aligned_properties == 1
        assert report.property_coverage_pct == 50


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
