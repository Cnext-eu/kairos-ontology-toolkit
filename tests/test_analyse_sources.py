# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for source affinity analysis and coverage reporting."""

import json
from unittest.mock import MagicMock

import pytest
from rdflib import RDF, RDFS, OWL

from kairos_ontology.analyse_sources import (
    parse_source_vocabulary,
    parse_reference_model,
    find_specializations,
    analyse_sample_evidence,
    analyse_table_single_call,
    analyse_source_system,
    write_analysis_output,
    write_affinity_matrix,
    run_analyse_sources,
    _filter_analysis_by_domain,
    resolve_reference_models,
    load_data_domains,
    build_data_domain_targets,
    list_accelerator_packs,
    make_reporter,
    _build_single_call_prompt,
    _build_candidates,
    _summarize_classes,
    _pick_fallback,
    _resolve_module_classes,
    _resolve_uris_to_classes,
    resolve_domain_class_summaries,
    _materialize_context,
    _find_ontology_package_dirs,
    _assign_domain_key,
    _domain_display_name,
    SourceAnalysis,
    TableAssignment,
    SampleEvidence,
    FALLBACK_DOMAIN_IDS,
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

SAMPLE_REF_MODEL_WITH_SUBCLASSES_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix ref-party: <https://kairos.cnext.eu/ref/party#> .

<https://kairos.cnext.eu/ref/party> a owl:Ontology ;
    rdfs:label "Party" ;
    owl:versionInfo "1.0.0" .

ref-party:Party a owl:Class ;
    rdfs:label "Party" ;
    rdfs:comment "A business party" .

ref-party:Organisation a owl:Class ;
    rdfs:subClassOf ref-party:Party ;
    rdfs:label "Organisation" .

ref-party:Person a owl:Class ;
    rdfs:subClassOf ref-party:Party ;
    rdfs:label "Person" .

ref-party:partyName a owl:DatatypeProperty ;
    rdfs:label "Party name" ;
    rdfs:domain ref-party:Party ;
    rdfs:range xsd:string .

ref-party:registrationNumber a owl:DatatypeProperty ;
    rdfs:label "Registration number" ;
    rdfs:domain ref-party:Organisation ;
    rdfs:range xsd:string .

ref-party:firstName a owl:DatatypeProperty ;
    rdfs:label "First name" ;
    rdfs:domain ref-party:Person ;
    rdfs:range xsd:string .

ref-party:lastName a owl:DatatypeProperty ;
    rdfs:label "Last name" ;
    rdfs:domain ref-party:Person ;
    rdfs:range xsd:string .
"""

LOW_SAMPLE_COVERAGE_VOCAB_TTL = """\
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix testapp: <https://kairos.cnext.eu/source/testapp#> .

testapp:testapp a kairos-bronze:SourceSystem ;
    rdfs:label "testapp" .

testapp:Sampled a kairos-bronze:SourceTable ;
    kairos-bronze:tableName "Sampled" ;
    kairos-bronze:belongsToSystem testapp:testapp .

testapp:Sampled_Name a kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "Name" ;
    kairos-bronze:dataType "varchar(200)" ;
    kairos-bronze:sampleValues "Acme | Globex" ;
    kairos-bronze:belongsToTable testapp:Sampled .

testapp:UnsampledOne a kairos-bronze:SourceTable ;
    kairos-bronze:tableName "UnsampledOne" ;
    kairos-bronze:belongsToSystem testapp:testapp .

testapp:UnsampledOne_Code a kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "Code" ;
    kairos-bronze:dataType "varchar(50)" ;
    kairos-bronze:belongsToTable testapp:UnsampledOne .

testapp:UnsampledTwo a kairos-bronze:SourceTable ;
    kairos-bronze:tableName "UnsampledTwo" ;
    kairos-bronze:belongsToSystem testapp:testapp .

testapp:UnsampledTwo_Ref a kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "Ref" ;
    kairos-bronze:dataType "varchar(50)" ;
    kairos-bronze:belongsToTable testapp:UnsampledTwo .
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

PARTY_MODULE_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix party: <https://www.kairosflow.ai/ont/bsp/party#> .

party:TradeParty a owl:Class ;
    rdfs:label "Trade Party" ;
    rdfs:comment "A party to a trade." .

party:Consignee a owl:Class ;
    rdfs:label "Consignee" .
"""

PARTY_CATALOG_XML = """\
<?xml version="1.0"?>
<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">
  <uri name="https://www.kairosflow.ai/ont/bsp/party#" uri="party.ttl"/>
</catalog>
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
# Tests: sample evidence coverage
# ---------------------------------------------------------------------------


class TestSampleEvidence:
    """Warnings and metadata for low sample-data coverage."""

    def test_analyse_sample_evidence_warns_below_half(self):
        evidence = analyse_sample_evidence({
            "Sampled": [{"name": "Name", "samples": ["Acme"]}],
            "UnsampledOne": [{"name": "Code", "samples": []}],
            "UnsampledTwo": [{"name": "Ref", "samples": []}],
        })

        assert evidence.analysed_tables == 3
        assert evidence.sampled_tables == 1
        assert evidence.coverage_ratio == 0.3333
        assert evidence.warning is True
        assert evidence.missing_sample_tables == ["UnsampledOne", "UnsampledTwo"]

    def test_analyse_sample_evidence_allows_half_or_more(self):
        evidence = analyse_sample_evidence({
            "Sampled": [{"name": "Name", "samples": ["Acme"]}],
            "Unsampled": [{"name": "Code", "samples": []}],
        })

        assert evidence.coverage_ratio == 0.5
        assert evidence.warning is False

    def test_analyse_source_system_reports_low_sample_warning(self, tmp_path, monkeypatch):
        vocab_file = tmp_path / "testapp.vocabulary.ttl"
        vocab_file.write_text(LOW_SAMPLE_COVERAGE_VOCAB_TTL, encoding="utf-8")
        ref_file = tmp_path / "party.ttl"
        ref_file.write_text(SAMPLE_REF_MODEL_TTL, encoding="utf-8")
        ref_domains = [parse_reference_model(ref_file)]

        client = MagicMock()
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = json.dumps({
            "domain": "Party",
            "confidence": 0.8,
            "likely_entity": "Party",
            "rationale": "Party-like table",
            "indicative_columns": ["Name"],
        })
        client.chat.completions.create.return_value = response
        monkeypatch.setattr(
            "kairos_ontology.analyse_sources._get_openai_client", lambda: client
        )
        messages: list[str] = []

        analysis = analyse_source_system(
            vocab_file,
            ref_domains,
            max_workers=1,
            report=lambda message, level="info": messages.append(message),
        )

        assert analysis.sample_evidence is not None
        assert analysis.sample_evidence.warning is True
        warning = next(message for message in messages if "Sample data coverage is low" in message)
        assert "1/3 analysed table(s)" in warning
        assert "Missing samples: UnsampledOne, UnsampledTwo" in warning

    def test_write_analysis_output_includes_sample_evidence(self, tmp_path):
        import yaml as _yaml

        analysis = SourceAnalysis(
            system="testapp",
            analysed_at="2026-01-01T00:00:00Z",
            model_used="gpt-5.4-mini",
            table_assignments=[
                TableAssignment(table="Sampled", total_columns=1, domain="Party"),
            ],
            sample_evidence=SampleEvidence(
                analysed_tables=3,
                sampled_tables=1,
                coverage_ratio=0.3333,
                warning=True,
                missing_sample_tables=["UnsampledOne", "UnsampledTwo"],
            ),
        )

        out = write_analysis_output(analysis, tmp_path)
        data = _yaml.safe_load(out.read_text(encoding="utf-8"))

        assert data["sample_evidence"] == {
            "analysed_tables": 3,
            "sampled_tables": 1,
            "coverage_ratio": 0.3333,
            "threshold": 0.5,
            "status": "low",
            "warning": True,
            "missing_sample_tables": ["UnsampledOne", "UnsampledTwo"],
        }


# ---------------------------------------------------------------------------
# Tests: Data-domain-first classification
# ---------------------------------------------------------------------------


DATA_DOMAINS_YAML = """\
schema_version: "1.0"
groups:
  - id: party-commercial
    name: "Party & Commercial"
    domains:
      - id: party
        name: "Party, Role & Organisation"
        owns: "Legal entities, customers, suppliers."
        does_not_own: "Contracts, bookings, invoices."
        imports:
          - uri: "https://www.kairosflow.ai/ont/bsp/party#"
            module: "BSP / Party"
          - uri: "https://www.kairosflow.ai/ont/mmt/party#"
            module: "MMT / Party"
      - id: commercial
        name: "Customer, Contract & Commercial Agreement"
        owns: "Commercial relationships, service agreements."
        does_not_own: "Surcharge calculation, invoice posting."
        imports:
          - uri: "https://www.kairosflow.ai/ont/bsp/commercial#"
            module: "BSP / Commercial"
"""


def _write_logistics_pack(root):
    dd_dir = root / "accelerator-packs" / "logistics" / "client-hub-blueprint"
    dd_dir.mkdir(parents=True)
    (dd_dir / "data-domains.yaml").write_text(DATA_DOMAINS_YAML, encoding="utf-8")
    return dd_dir


class TestLoadDataDomainsURIs:
    """load_data_domains() captures imports URIs/modules + accelerator filter."""

    def test_captures_uris_and_modules(self, tmp_path):
        _write_logistics_pack(tmp_path)
        result = load_data_domains(tmp_path)
        assert result["party"]["uris"] == [
            "https://www.kairosflow.ai/ont/bsp/party#",
            "https://www.kairosflow.ai/ont/mmt/party#",
        ]
        assert result["party"]["modules"] == ["BSP / Party", "MMT / Party"]
        assert result["commercial"]["uris"] == [
            "https://www.kairosflow.ai/ont/bsp/commercial#"
        ]
        assert result["party"]["group"] == "party-commercial"

    def test_accelerator_filter_selects_pack(self, tmp_path):
        _write_logistics_pack(tmp_path)
        # A second pack without data-domains we want
        other = tmp_path / "accelerator-packs" / "financial-services" / "client-hub-blueprint"
        other.mkdir(parents=True)
        (other / "data-domains.yaml").write_text(
            "groups:\n  - id: fin\n    domains:\n      - id: instrument\n"
            "        name: Instrument\n",
            encoding="utf-8",
        )
        result = load_data_domains(tmp_path, accelerator="logistics")
        assert "party" in result
        assert "instrument" not in result

    def test_accelerator_filter_no_match_returns_empty(self, tmp_path):
        _write_logistics_pack(tmp_path)
        result = load_data_domains(tmp_path, accelerator="does-not-exist")
        assert result == {}

    def test_handles_missing_imports(self, tmp_path):
        dd_dir = tmp_path / "accelerator-packs" / "x" / "client-hub-blueprint"
        dd_dir.mkdir(parents=True)
        (dd_dir / "data-domains.yaml").write_text(
            "groups:\n  - id: g\n    domains:\n      - id: party\n        name: Party\n",
            encoding="utf-8",
        )
        result = load_data_domains(tmp_path)
        assert result["party"]["uris"] == []
        assert result["party"]["modules"] == []


class TestListAcceleratorPacks:
    def test_lists_packs(self, tmp_path):
        _write_logistics_pack(tmp_path)
        fin = tmp_path / "accelerator-packs" / "financial-services" / "client-hub-blueprint"
        fin.mkdir(parents=True)
        (fin / "data-domains.yaml").write_text("groups: []\n", encoding="utf-8")
        packs = list_accelerator_packs(tmp_path)
        assert packs == ["financial-services", "logistics"]

    def test_empty_when_none(self, tmp_path):
        assert list_accelerator_packs(tmp_path) == []


class TestBuildDataDomainTargets:
    def test_builds_targets_with_uris(self, tmp_path):
        _write_logistics_pack(tmp_path)
        dd = load_data_domains(tmp_path)
        targets = build_data_domain_targets(dd)

        assert len(targets) == 2
        party = next(t for t in targets if t["domain_name"] == "party")
        assert party["display_name"] == "Party, Role & Organisation"
        assert party["group"] == "party-commercial"
        assert party["uris"] == [
            "https://www.kairosflow.ai/ont/bsp/party#",
            "https://www.kairosflow.ai/ont/mmt/party#",
        ]
        # Shallow: no TTL classes resolved
        assert party["classes"] == []
        # Ownership metadata available to the prompt
        assert "Legal entities" in party["data_domain_meta"]["owns"]


class TestSingleCallPrompt:
    def _candidates(self):
        return [
            {
                "id": "commercial",
                "group": "party-commercial",
                "uris": ["https://www.kairosflow.ai/ont/bsp/commercial#"],
                "owns": "Commercial relationships, service agreements.",
                "does_not_own": "Surcharge calculation, invoice posting.",
                "class_summary": [
                    {"name": "SalesContract", "label": "Sales Contract", "comment": ""},
                ],
            },
            {
                "id": "party",
                "group": "party-commercial",
                "uris": ["https://www.kairosflow.ai/ont/bsp/party#"],
                "owns": "Legal entities and roles.",
                "does_not_own": "Contracts.",
                "class_summary": [
                    {"name": "TradeParty", "label": "Trade Party", "comment": ""},
                ],
            },
        ]

    def test_prompt_lists_all_candidates_and_concepts(self):
        columns = [{"name": "ContractNo", "data_type": "string", "samples": ["C-1"]}]
        prompt = _build_single_call_prompt("tblContracts", columns, self._candidates())

        # Both candidate ids and their key concepts appear once, in a single prompt.
        assert "### commercial" in prompt
        assert "### party" in prompt
        assert "Sales Contract" in prompt
        assert "Trade Party" in prompt
        assert "Commercial relationships" in prompt
        assert "exactly one of these ids: commercial, party" in prompt
        assert "tblContracts" in prompt
        assert "ContractNo" in prompt

    def test_prompt_omits_concepts_when_absent(self):
        cands = [{"id": "mdm", "group": "", "uris": [], "owns": "Master data.",
                  "does_not_own": "", "class_summary": []}]
        prompt = _build_single_call_prompt("tbl", [], cands)
        assert "### mdm" in prompt
        assert "KEY CONCEPTS" not in prompt


class TestBuildCandidates:
    def test_uses_class_summary_for_data_domain_path(self):
        ref_domains = [{
            "domain_name": "party",
            "group": "party-commercial",
            "uris": ["https://www.kairosflow.ai/ont/bsp/party#"],
            "classes": [],
            "class_summary": [{"name": "TradeParty", "label": "Trade Party", "comment": ""}],
            "data_domain_meta": {"owns": "Parties", "does_not_own": "Contracts"},
        }]
        cands = _build_candidates(ref_domains)
        assert cands[0]["id"] == "party"
        assert cands[0]["owns"] == "Parties"
        assert cands[0]["class_summary"][0]["label"] == "Trade Party"

    def test_summarizes_full_classes_for_reference_model_path(self):
        ref_domains = [{
            "domain_name": "Party",
            "classes": [
                {"name": f"C{i}", "label": f"L{i}", "comment": "", "properties": []}
                for i in range(30)
            ],
        }]
        cands = _build_candidates(ref_domains)
        # Capped to MAX_DOMAIN_CLASSES (18)
        assert len(cands[0]["class_summary"]) == 18

    def test_summarize_classes_caps_and_falls_back_label(self):
        out = _summarize_classes([{"name": "X", "comment": "c"}], cap=5)
        assert out[0]["label"] == "X"  # falls back to name


class TestPickFallback:
    def test_picks_first_present(self):
        assert _pick_fallback({"mdm", "party"}, FALLBACK_DOMAIN_IDS) == "mdm"

    def test_picks_reference_data_when_no_mdm(self):
        assert _pick_fallback({"reference-data", "party"}, FALLBACK_DOMAIN_IDS) == "reference-data"

    def test_unclassified_when_no_fallback_present(self):
        assert _pick_fallback({"party", "cargo"}, FALLBACK_DOMAIN_IDS) == "unclassified"


class TestMakeReporter:
    def test_quiet_suppresses_info(self, capsys):
        report = make_reporter(verbose=False, quiet=True)
        report("hello")
        report("oops", level="error")
        out = capsys.readouterr().out
        assert "hello" not in out
        assert "oops" in out

    def test_verbose_shows_verbose_lines(self, capsys):
        report = make_reporter(verbose=True, quiet=False)
        report("detail", level="verbose")
        assert "detail" in capsys.readouterr().out

    def test_default_hides_verbose_lines(self, capsys):
        report = make_reporter(verbose=False, quiet=False)
        report("detail", level="verbose")
        report("phase")
        out = capsys.readouterr().out
        assert "detail" not in out
        assert "phase" in out


class TestMaterializeContext:
    def test_writes_manifest_and_domain_docs(self, tmp_path):
        targets = [
            {
                "domain_name": "commercial",
                "display_name": "Commercial",
                "group": "party-commercial",
                "uris": ["https://www.kairosflow.ai/ont/bsp/commercial#"],
                "modules": ["BSP / Commercial"],
                "classes": [],
                "data_domain_meta": {"owns": "Contracts", "does_not_own": "Invoices"},
            },
        ]
        out = tmp_path / ".resolved"
        _materialize_context(targets, tmp_path, out, "data-domain-first")

        import yaml
        manifest = yaml.safe_load((out / "_manifest.yaml").read_text())
        assert manifest["strategy"] == "data-domain-first"
        assert manifest["domain_count"] == 1
        assert "toolkit_version" in manifest

        domain_doc = yaml.safe_load((out / "domains" / "commercial.yaml").read_text())
        assert domain_doc["domain"] == "commercial"
        assert domain_doc["uris"] == ["https://www.kairosflow.ai/ont/bsp/commercial#"]
        assert domain_doc["owns"] == "Contracts"


class TestOutputIncludesURIs:
    def test_affinity_yaml_has_uris_and_group(self, tmp_path):
        analysis = SourceAnalysis(
            system="testapp",
            analysed_at="2026-06-04T12:00:00Z",
            model_used="gpt-5-mini",
            table_assignments=[
                TableAssignment(
                    table="tblContracts",
                    total_columns=3,
                    domain="commercial",
                    domain_group="party-commercial",
                    domain_uris=["https://www.kairosflow.ai/ont/bsp/commercial#"],
                    confidence=0.85,
                    likely_entity="SalesContract",
                    secondary_domains=[{
                        "domain": "party",
                        "domain_group": "party-commercial",
                        "domain_uris": ["https://www.kairosflow.ai/ont/bsp/party#"],
                    }],
                ),
            ],
        )
        out = write_analysis_output(analysis, tmp_path)
        import yaml
        data = yaml.safe_load(out.read_text())

        assert data["schema_version"] == 2
        tbl = data["tables"][0]
        assert tbl["table"] == "tblContracts"
        assert tbl["domain"] == "commercial"
        assert tbl["domain_group"] == "party-commercial"
        assert tbl["domain_uris"] == ["https://www.kairosflow.ai/ont/bsp/commercial#"]
        assert tbl["secondary_domains"][0]["domain"] == "party"

        rollup = data["domain_summary"][0]
        assert rollup["domain"] == "commercial"
        assert rollup["table_count"] == 1
        assert rollup["tables"] == ["tblContracts"]

    def test_matrix_includes_uris_and_group(self, tmp_path):
        analyses = [
            SourceAnalysis(
                system="sys1", analysed_at="t", model_used="m",
                table_assignments=[
                    TableAssignment(
                        table="tblA", total_columns=2, domain="party",
                        domain_group="party-commercial",
                        domain_uris=["https://www.kairosflow.ai/ont/bsp/party#"],
                    ),
                    TableAssignment(
                        table="tblB", total_columns=2, domain="party",
                        domain_group="party-commercial",
                        domain_uris=["https://www.kairosflow.ai/ont/bsp/party#"],
                    ),
                ],
            ),
        ]
        out = write_affinity_matrix(analyses, tmp_path)
        import yaml
        data = yaml.safe_load(out.read_text())
        dom = data["systems"][0]["domains"][0]
        assert dom["domain"] == "party"
        assert dom["domain_group"] == "party-commercial"
        assert dom["domain_uris"] == ["https://www.kairosflow.ai/ont/bsp/party#"]
        assert dom["table_count"] == 2


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
# Tests: Specialization discovery (DD-044)
# ---------------------------------------------------------------------------


class TestFindSpecializations:
    """Tests for find_specializations() helper."""

    def test_finds_direct_subclasses(self, tmp_path):
        ref_file = tmp_path / "party.ttl"
        ref_file.write_text(SAMPLE_REF_MODEL_WITH_SUBCLASSES_TTL, encoding="utf-8")
        from rdflib import Graph, URIRef
        g = Graph()
        g.parse(ref_file, format="turtle")
        party_uri = URIRef("https://kairos.cnext.eu/ref/party#Party")

        specs = find_specializations(g, party_uri)

        spec_names = {s["class"] for s in specs}
        assert "Organisation" in spec_names
        assert "Person" in spec_names

    def test_includes_subclass_properties(self, tmp_path):
        ref_file = tmp_path / "party.ttl"
        ref_file.write_text(SAMPLE_REF_MODEL_WITH_SUBCLASSES_TTL, encoding="utf-8")
        from rdflib import Graph, URIRef
        g = Graph()
        g.parse(ref_file, format="turtle")
        party_uri = URIRef("https://kairos.cnext.eu/ref/party#Party")

        specs = find_specializations(g, party_uri)

        org_spec = next(s for s in specs if s["class"] == "Organisation")
        org_prop_names = {p["name"] for p in org_spec["properties"]}
        assert "registrationNumber" in org_prop_names

        person_spec = next(s for s in specs if s["class"] == "Person")
        person_prop_names = {p["name"] for p in person_spec["properties"]}
        assert "firstName" in person_prop_names
        assert "lastName" in person_prop_names

    def test_distance_is_correct(self, tmp_path):
        ref_file = tmp_path / "party.ttl"
        ref_file.write_text(SAMPLE_REF_MODEL_WITH_SUBCLASSES_TTL, encoding="utf-8")
        from rdflib import Graph, URIRef
        g = Graph()
        g.parse(ref_file, format="turtle")
        party_uri = URIRef("https://kairos.cnext.eu/ref/party#Party")

        specs = find_specializations(g, party_uri)

        for s in specs:
            assert s["distance"] == 1, f"{s['class']} should be distance 1"

    def test_max_depth_limits_traversal(self, tmp_path):
        """With max_depth=0, no specializations should be found."""
        ref_file = tmp_path / "party.ttl"
        ref_file.write_text(SAMPLE_REF_MODEL_WITH_SUBCLASSES_TTL, encoding="utf-8")
        from rdflib import Graph, URIRef
        g = Graph()
        g.parse(ref_file, format="turtle")
        party_uri = URIRef("https://kairos.cnext.eu/ref/party#Party")

        specs = find_specializations(g, party_uri, max_depth=0)
        assert specs == []

    def test_no_descendants_returns_empty(self, tmp_path):
        ref_file = tmp_path / "party.ttl"
        ref_file.write_text(SAMPLE_REF_MODEL_WITH_SUBCLASSES_TTL, encoding="utf-8")
        from rdflib import Graph, URIRef
        g = Graph()
        g.parse(ref_file, format="turtle")
        # Person has no subclasses
        person_uri = URIRef("https://kairos.cnext.eu/ref/party#Person")

        specs = find_specializations(g, person_uri)
        assert specs == []

    def test_cycle_protection(self):
        """A circular subClassOf should not cause infinite loop."""
        from rdflib import Graph, Namespace
        g = Graph()
        ns = Namespace("http://example.org/")
        g.add((ns.A, RDF.type, OWL.Class))
        g.add((ns.B, RDF.type, OWL.Class))
        g.add((ns.B, RDFS.subClassOf, ns.A))
        g.add((ns.A, RDFS.subClassOf, ns.B))  # circular

        specs = find_specializations(g, ns.A)
        assert len(specs) == 1
        assert specs[0]["class"] == "B"


class TestParseReferenceModelWithSpecializations:
    """Tests for parse_reference_model with include_specializations=True."""

    def test_specializations_included_when_requested(self, tmp_path):
        ref_file = tmp_path / "party.ttl"
        ref_file.write_text(SAMPLE_REF_MODEL_WITH_SUBCLASSES_TTL, encoding="utf-8")

        result = parse_reference_model(ref_file, include_specializations=True)

        party_cls = next(c for c in result["classes"] if c["name"] == "Party")
        assert "specializations" in party_cls
        spec_names = {s["class"] for s in party_cls["specializations"]}
        assert "Organisation" in spec_names
        assert "Person" in spec_names

    def test_specializations_absent_by_default(self, tmp_path):
        ref_file = tmp_path / "party.ttl"
        ref_file.write_text(SAMPLE_REF_MODEL_WITH_SUBCLASSES_TTL, encoding="utf-8")

        result = parse_reference_model(ref_file)

        party_cls = next(c for c in result["classes"] if c["name"] == "Party")
        assert "specializations" not in party_cls


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


class TestAnalyseTableSingleCall:
    def _candidates(self):
        return [
            {"id": "party", "group": "party-commercial",
             "uris": ["u-party"], "owns": "", "does_not_own": "", "class_summary": []},
            {"id": "commercial", "group": "party-commercial",
             "uris": ["u-comm"], "owns": "", "does_not_own": "", "class_summary": []},
            {"id": "mdm", "group": "master-data-management",
             "uris": [], "owns": "", "does_not_own": "", "class_summary": []},
        ]

    def _client_returning(self, payload):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(payload)
        mock_client.chat.completions.create.return_value = mock_response
        return mock_client

    def test_valid_primary_and_secondaries(self):
        client = self._client_returning({
            "domain": "party",
            "secondary_domains": ["commercial", "mdm", "party"],
            "confidence": 0.9,
            "likely_entity": "Party",
            "rationale": "party-like",
            "indicative_columns": ["Name"],
        })
        res = analyse_table_single_call(
            client, "gpt-5-mini", "tblClient", [], self._candidates()
        )
        assert res["domain"] == "party"
        assert res["confidence"] == 0.9
        assert res["likely_entity"] == "Party"
        # secondaries: deduped, primary removed, capped to 2
        assert res["secondary_domains"] == ["commercial", "mdm"]

    def test_invalid_domain_falls_back_to_mdm(self):
        client = self._client_returning({
            "domain": "nonsense", "confidence": 0.7, "likely_entity": "X",
        })
        res = analyse_table_single_call(
            client, "gpt-5-mini", "tbl", [], self._candidates()
        )
        assert res["domain"] == "mdm"
        assert res["confidence"] == 0.0
        assert res["likely_entity"] == ""

    def test_invalid_domain_unclassified_when_no_fallback(self):
        cands = [c for c in self._candidates() if c["id"] != "mdm"]
        client = self._client_returning({"domain": "nope"})
        res = analyse_table_single_call(client, "gpt-5-mini", "tbl", [], cands)
        assert res["domain"] == "unclassified"

    def test_secondaries_filtered_to_valid_ids(self):
        client = self._client_returning({
            "domain": "party",
            "secondary_domains": ["bogus", "commercial"],
            "confidence": 0.5,
        })
        res = analyse_table_single_call(client, "gpt-5-mini", "tbl", [], self._candidates())
        assert res["secondary_domains"] == ["commercial"]

    def test_handles_llm_error_gracefully(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API error")
        res = analyse_table_single_call(
            mock_client, "gpt-5-mini", "tbl", [], self._candidates()
        )
        # Empty result → fallback to first available fallback id (mdm)
        assert res["domain"] == "mdm"
        assert res["confidence"] == 0.0
        assert res["indicative_columns"] == []

    def test_normalized_id_match_for_reference_model_labels(self):
        cands = [
            {"id": "BSP Party", "group": "", "uris": ["u"], "owns": "",
             "does_not_own": "", "class_summary": []},
        ]
        client = self._client_returning({"domain": "bsp party", "confidence": 0.8})
        res = analyse_table_single_call(client, "gpt-5-mini", "tbl", [], cands)
        assert res["domain"] == "BSP Party"
        assert res["confidence"] == 0.8

    def test_non_numeric_confidence_coerces_to_zero(self):
        client = self._client_returning({"domain": "party", "confidence": "high"})
        res = analyse_table_single_call(client, "gpt-5-mini", "tbl", [], self._candidates())
        assert res["domain"] == "party"
        assert res["confidence"] == 0.0

    def test_confidence_clamped_to_unit_interval(self):
        client = self._client_returning({"domain": "party", "confidence": 1.7})
        res = analyse_table_single_call(client, "gpt-5-mini", "tbl", [], self._candidates())
        assert res["confidence"] == 1.0

    def test_non_dict_json_falls_back(self):
        client = self._client_returning(["not", "a", "dict"])
        res = analyse_table_single_call(client, "gpt-5-mini", "tbl", [], self._candidates())
        assert res["domain"] == "mdm"


# ---------------------------------------------------------------------------
# Tests: Output writing
# ---------------------------------------------------------------------------


class TestWriteAnalysisOutput:
    def test_writes_yaml(self, tmp_path):
        analysis = SourceAnalysis(
            system="testapp",
            analysed_at="2026-06-04T12:00:00Z",
            model_used="gpt-5-mini",
            table_assignments=[
                TableAssignment(
                    table="tblClient",
                    total_columns=3,
                    domain="party",
                    domain_group="party-commercial",
                    confidence=0.82,
                    rationale="Client table maps to Party domain",
                    likely_entity="Party",
                    indicative_columns=["ClientName", "ClientEmail"],
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
        assert data["schema_version"] == 2
        assert len(data["tables"]) == 1
        assert data["tables"][0]["domain"] == "party"
        assert data["tables"][0]["confidence"] == 0.82
        assert data["domain_summary"][0]["domain"] == "party"

    def test_writes_affinity_matrix(self, tmp_path):
        analyses = [
            SourceAnalysis(
                system="sys1",
                analysed_at="2026-06-04T12:00:00Z",
                model_used="gpt-5-mini",
                table_assignments=[
                    TableAssignment(table="tblA", total_columns=2, domain="party"),
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


# ---------------------------------------------------------------------------
# Tests: Semantic grounding (resolve module classes via catalog)
# ---------------------------------------------------------------------------


class TestSemanticGrounding:
    PARTY_URI = "https://www.kairosflow.ai/ont/bsp/party#"

    def _setup(self, tmp_path):
        (tmp_path / "party.ttl").write_text(PARTY_MODULE_TTL, encoding="utf-8")
        catalog = tmp_path / "catalog-v001.xml"
        catalog.write_text(PARTY_CATALOG_XML, encoding="utf-8")
        return catalog

    def test_resolve_module_classes_and_cache(self, tmp_path):
        self._setup(tmp_path)
        cache: dict = {}
        classes = _resolve_module_classes(tmp_path / "party.ttl", cache)
        names = {c["name"] for c in classes}
        assert "TradeParty" in names and "Consignee" in names
        # Cached: a second call returns the same list object (parsed once).
        assert _resolve_module_classes(tmp_path / "party.ttl", cache) is classes

    def test_resolve_uris_to_classes(self, tmp_path):
        catalog = self._setup(tmp_path)
        from kairos_ontology.catalog_utils import CatalogResolver
        resolver = CatalogResolver(catalog)
        out = _resolve_uris_to_classes([self.PARTY_URI], resolver, {}, cap=18)
        assert {c["name"] for c in out} == {"TradeParty", "Consignee"}

    def test_resolve_uris_caps_results(self, tmp_path):
        catalog = self._setup(tmp_path)
        from kairos_ontology.catalog_utils import CatalogResolver
        resolver = CatalogResolver(catalog)
        out = _resolve_uris_to_classes([self.PARTY_URI], resolver, {}, cap=1)
        assert len(out) == 1

    def test_resolve_uris_skips_unmapped(self, tmp_path):
        catalog = self._setup(tmp_path)
        from kairos_ontology.catalog_utils import CatalogResolver
        resolver = CatalogResolver(catalog)
        out = _resolve_uris_to_classes(["https://unknown.example/x#"], resolver, {}, cap=18)
        assert out == []

    def test_resolve_domain_class_summaries_attaches(self, tmp_path):
        catalog = self._setup(tmp_path)
        ref_domains = [{"domain_name": "party", "classes": [], "uris": [self.PARTY_URI]}]
        resolve_domain_class_summaries(ref_domains, catalog)
        assert "class_summary" in ref_domains[0]
        labels = {c["label"] for c in ref_domains[0]["class_summary"]}
        assert "Trade Party" in labels

    def test_grounding_skips_without_catalog(self, tmp_path):
        ref_domains = [{"domain_name": "party", "classes": [], "uris": [self.PARTY_URI]}]
        resolve_domain_class_summaries(ref_domains, None)
        assert "class_summary" not in ref_domains[0]

    def test_grounding_skips_reference_model_domains(self, tmp_path):
        catalog = self._setup(tmp_path)
        ref_domains = [{"domain_name": "X", "classes": [{"name": "A"}], "uris": []}]
        resolve_domain_class_summaries(ref_domains, catalog)
        assert "class_summary" not in ref_domains[0]


# ---------------------------------------------------------------------------
# Tests: concurrency + sidecar caching (CR-1 / CR-5)
# ---------------------------------------------------------------------------


class TestAffinityConcurrencyAndCaching:
    def _setup(self, tmp_path):
        vocab_file = tmp_path / "testapp.vocabulary.ttl"
        vocab_file.write_text(SAMPLE_VOCAB_TTL, encoding="utf-8")
        ref_file = tmp_path / "party.ttl"
        ref_file.write_text(SAMPLE_REF_MODEL_TTL, encoding="utf-8")
        ref_domains = [parse_reference_model(ref_file)]
        return vocab_file, ref_domains

    def _counting_client(self, counter):
        client = MagicMock()

        def create(**kwargs):
            counter.append(1)
            payload = {"domain": "party", "confidence": 0.9, "likely_entity": "Party"}
            resp = MagicMock()
            resp.choices = [MagicMock()]
            resp.choices[0].message.content = json.dumps(payload)
            return resp

        client.chat.completions.create.side_effect = create
        return client

    def test_sidecar_cache_skips_second_run(self, tmp_path, monkeypatch):
        from kairos_ontology._cache import SidecarCache

        vocab_file, ref_domains = self._setup(tmp_path)
        counter: list[int] = []
        client = self._counting_client(counter)
        monkeypatch.setattr(
            "kairos_ontology.analyse_sources._get_openai_client", lambda: client
        )

        cache = SidecarCache(tmp_path / ".cache" / "analyse-sources.json")
        analyse_source_system(vocab_file, ref_domains, cache=cache)
        first = len(counter)
        assert first > 0
        cache.flush()

        # Fresh cache object loading the same sidecar file → all tables hit.
        counter.clear()
        cache2 = SidecarCache(tmp_path / ".cache" / "analyse-sources.json")
        analyse_source_system(vocab_file, ref_domains, cache=cache2)
        assert counter == []

    def test_parallel_matches_serial(self, tmp_path, monkeypatch):
        vocab_file, ref_domains = self._setup(tmp_path)
        monkeypatch.setattr(
            "kairos_ontology.analyse_sources._get_openai_client",
            lambda: self._counting_client([]),
        )
        serial = analyse_source_system(vocab_file, ref_domains, max_workers=1)
        parallel = analyse_source_system(vocab_file, ref_domains, max_workers=4)
        assert [a.table for a in serial.table_assignments] == \
            [a.table for a in parallel.table_assignments]
        assert [a.domain for a in serial.table_assignments] == \
            [a.domain for a in parallel.table_assignments]

    def test_reports_each_table_as_it_completes(self, tmp_path, monkeypatch):
        vocab_file, ref_domains = self._setup(tmp_path)
        monkeypatch.setattr(
            "kairos_ontology.analyse_sources._get_openai_client",
            lambda: self._counting_client([]),
        )
        messages: list[str] = []

        analyse_source_system(
            vocab_file,
            ref_domains,
            max_workers=4,
            report=lambda message, level="info": messages.append(message),
        )

        assert any("✓" in message and "→ party" in message.lower() for message in messages)


# ---------------------------------------------------------------------------
# Tests: --domains is an OUTPUT filter, never a candidate restriction (issue #189)
# ---------------------------------------------------------------------------

TWO_TABLE_VOCAB_TTL = """\
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix testapp: <https://kairos.cnext.eu/source/testapp#> .

testapp:testapp a kairos-bronze:SourceSystem ;
    rdfs:label "testapp" .

testapp:tblClient a kairos-bronze:SourceTable ;
    kairos-bronze:tableName "tblClient" ;
    kairos-bronze:belongsToSystem testapp:testapp .

testapp:tblClient_Name a kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "Name" ;
    kairos-bronze:dataType "varchar(200)" ;
    kairos-bronze:belongsToTable testapp:tblClient .

testapp:tblContract a kairos-bronze:SourceTable ;
    kairos-bronze:tableName "tblContract" ;
    kairos-bronze:belongsToSystem testapp:testapp .

testapp:tblContract_Ref a kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "ContractRef" ;
    kairos-bronze:dataType "varchar(50)" ;
    kairos-bronze:belongsToTable testapp:tblContract .
"""


class TestFilterAnalysisByDomain:
    """Unit tests for the post-classification output filter helper."""

    def _analysis(self):
        return SourceAnalysis(
            system="s", analysed_at="t", model_used="m",
            table_assignments=[
                TableAssignment(table="a", total_columns=1, domain="party"),
                TableAssignment(table="b", total_columns=1, domain="commercial"),
            ],
        )

    def test_keeps_only_primary_domain_matches(self):
        out = _filter_analysis_by_domain(self._analysis(), ["party"])
        assert [t.table for t in out.table_assignments] == ["a"]

    def test_substring_match(self):
        out = _filter_analysis_by_domain(self._analysis(), ["comm"])
        assert [t.table for t in out.table_assignments] == ["b"]

    def test_no_match_returns_empty(self):
        out = _filter_analysis_by_domain(self._analysis(), ["booking"])
        assert out.table_assignments == []
        # Identity metadata preserved even when empty
        assert out.system == "s" and out.model_used == "m"


class TestDomainsOutputFilter:
    """--domains classifies against the full candidate set, then filters output."""

    def _setup_hub(self, tmp_path):
        ref_dir = tmp_path / "refs"
        ref_dir.mkdir()
        _write_logistics_pack(ref_dir)  # party + commercial data domains
        sys_dir = tmp_path / "sources" / "testapp"
        sys_dir.mkdir(parents=True)
        (sys_dir / "testapp.vocabulary.ttl").write_text(
            TWO_TABLE_VOCAB_TTL, encoding="utf-8"
        )
        return ref_dir, tmp_path / "sources", tmp_path / "out"

    def _routing_client(self, seen_candidate_counts):
        """Mock LLM: routes tblContract→commercial, else→party, and records how
        many candidate domains were present in each prompt."""
        client = MagicMock()

        def create(**kwargs):
            text = " ".join(
                str(m.get("content", "")) for m in kwargs.get("messages", [])
            )
            present = sum(1 for d in ("party", "commercial") if d in text)
            seen_candidate_counts.append(present)
            domain = "commercial" if "tblContract" in text else "party"
            resp = MagicMock()
            resp.choices = [MagicMock()]
            resp.choices[0].message.content = json.dumps(
                {"domain": domain, "confidence": 0.9, "likely_entity": domain}
            )
            return resp

        client.chat.completions.create.side_effect = create
        return client

    def test_classifies_against_full_set_then_filters_output(self, tmp_path, monkeypatch):
        import yaml as _yaml

        ref_dir, sources_dir, out_dir = self._setup_hub(tmp_path)
        seen: list[int] = []
        monkeypatch.setattr(
            "kairos_ontology.analyse_sources._get_openai_client",
            lambda: self._routing_client(seen),
        )

        run_analyse_sources(
            sources_dir=sources_dir,
            ref_models_dir=ref_dir,
            output_dir=out_dir,
            accelerator="logistics",
            domains_filter=["party"],
            shallow=True,
            max_workers=1,
            cost_warning=False,
        )

        # Every table was classified against BOTH candidate domains (not pruned).
        assert seen and all(count == 2 for count in seen)

        # Output keeps only the party table; the commercial one is dropped.
        affinity = _yaml.safe_load(
            (out_dir / "testapp-affinity.yaml").read_text(encoding="utf-8")
        )
        tables = {t["table"]: t["domain"] for t in affinity["tables"]}
        assert tables == {"tblClient": "party"}

    def test_zero_matching_tables_writes_empty_no_error(self, tmp_path, monkeypatch):
        import yaml as _yaml

        ref_dir, sources_dir, out_dir = self._setup_hub(tmp_path)
        monkeypatch.setattr(
            "kairos_ontology.analyse_sources._get_openai_client",
            lambda: self._routing_client([]),
        )

        # No table classifies as 'booking' → output must be empty, not an error.
        run_analyse_sources(
            sources_dir=sources_dir,
            ref_models_dir=ref_dir,
            output_dir=out_dir,
            accelerator="logistics",
            domains_filter=["booking"],
            shallow=True,
            max_workers=1,
            cost_warning=False,
        )
        affinity = _yaml.safe_load(
            (out_dir / "testapp-affinity.yaml").read_text(encoding="utf-8")
        )
        assert affinity["tables"] == []
        assert affinity["schema_version"] == 2

    def test_no_filter_keeps_all_tables(self, tmp_path, monkeypatch):
        import yaml as _yaml

        ref_dir, sources_dir, out_dir = self._setup_hub(tmp_path)
        monkeypatch.setattr(
            "kairos_ontology.analyse_sources._get_openai_client",
            lambda: self._routing_client([]),
        )

        run_analyse_sources(
            sources_dir=sources_dir,
            ref_models_dir=ref_dir,
            output_dir=out_dir,
            accelerator="logistics",
            shallow=True,
            max_workers=1,
            cost_warning=False,
        )
        affinity = _yaml.safe_load(
            (out_dir / "testapp-affinity.yaml").read_text(encoding="utf-8")
        )
        tables = {t["table"]: t["domain"] for t in affinity["tables"]}
        assert tables == {"tblClient": "party", "tblContract": "commercial"}
