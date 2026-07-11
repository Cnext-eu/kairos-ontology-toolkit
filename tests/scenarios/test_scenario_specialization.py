# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario tests for DD-044: Specialization Discovery.

Validates that design-time tools surface data properties declared on owl:subClass
descendants through the full pipeline: reference model parsing → inventory YAML →
coverage report alignment → propose-alignment prompt formatting.

Uses the acme-hub kairos-ref-party.ttl which has:
  - Party (8 direct properties: partyName, taxIdentifier, email, etc.)
  - Organisation (subClassOf Party) → registrationNumber
  - Person (subClassOf Party) → firstName, lastName
"""

from pathlib import Path

from kairos_ontology.core.analyse_sources import parse_reference_model
from kairos_ontology.core.coverage_report import (
    _align_properties,
    _build_ref_index,
    align_classes_deterministic,
    parse_domain_ontology,
)
from kairos_ontology.core.inventory import (
    INVENTORY_VERSION,
    generate_inventory,
    load_inventory,
    write_inventory,
)
from kairos_ontology.core.propose_alignment import _format_ref_inventory

REF_MODELS_DIR = Path(__file__).parent / "acme-hub" / "model" / "reference-models"


# ---------------------------------------------------------------------------
# 1. Reference model parsing — specialization ON vs OFF
# ---------------------------------------------------------------------------


class TestRefModelSpecializationParsing:
    """Modeler sees subclass properties when specializations are enabled."""

    def test_parse_ref_model_shows_specializations(self):
        """Party class surfaces Organisation/Person properties as specializations."""
        ref_path = REF_MODELS_DIR / "kairos-ref-party.ttl"
        result = parse_reference_model(ref_path, include_specializations=True)

        party = next(c for c in result["classes"] if c["name"] == "Party")
        assert "specializations" in party, "Party should have specializations key"

        spec_names = {s["class"] for s in party["specializations"]}
        assert "Organisation" in spec_names
        assert "Person" in spec_names

        # Organisation specialization should expose registrationNumber
        org_spec = next(s for s in party["specializations"]
                        if s["class"] == "Organisation")
        org_prop_names = {p["name"] for p in org_spec["properties"]}
        assert "registrationNumber" in org_prop_names
        assert org_spec["distance"] == 1

        # Person specialization should expose firstName, lastName
        person_spec = next(s for s in party["specializations"]
                           if s["class"] == "Person")
        person_prop_names = {p["name"] for p in person_spec["properties"]}
        assert "firstName" in person_prop_names
        assert "lastName" in person_prop_names
        assert person_spec["distance"] == 1

    def test_parse_ref_model_without_specializations_hides_them(self):
        """Without specializations, subclass properties are NOT on the parent."""
        ref_path = REF_MODELS_DIR / "kairos-ref-party.ttl"
        result = parse_reference_model(ref_path, include_specializations=False)

        party = next(c for c in result["classes"] if c["name"] == "Party")
        assert not party.get("specializations"), (
            "Party should not have specializations when feature is disabled"
        )

        # Party's direct properties should NOT include registrationNumber
        party_prop_names = {p["name"] for p in party["properties"]}
        assert "registrationNumber" not in party_prop_names
        assert "firstName" not in party_prop_names

        # Organisation should only have its own property
        org = next(c for c in result["classes"] if c["name"] == "Organisation")
        org_prop_names = {p["name"] for p in org["properties"]}
        assert "registrationNumber" in org_prop_names
        assert "partyName" not in org_prop_names  # partyName belongs to Party


# ---------------------------------------------------------------------------
# 2. Inventory YAML round-trip
# ---------------------------------------------------------------------------


class TestInventorySpecializations:
    """Materialized YAML inventory preserves specialization structure."""

    def test_inventory_yaml_round_trip_with_specializations(self, tmp_path):
        """Generate inventory → write YAML → load → verify specializations survive."""
        ref_path = REF_MODELS_DIR / "kairos-ref-party.ttl"
        inventory = generate_inventory(ref_path, include_specializations=True)

        assert inventory["version"] == INVENTORY_VERSION
        assert inventory["domain_name"] == "Party"

        # Write and reload
        yaml_path = tmp_path / "party-inventory.yaml"
        write_inventory(inventory, yaml_path)
        loaded = load_inventory(yaml_path)

        # Verify structure survived round-trip
        party = next(c for c in loaded["classes"] if c["name"] == "Party")
        assert "specializations" in party
        spec_names = {s["class"] for s in party["specializations"]}
        assert "Organisation" in spec_names
        assert "Person" in spec_names

        # Verify deep property structure
        org_spec = next(s for s in party["specializations"]
                        if s["class"] == "Organisation")
        org_prop_names = {p["name"] for p in org_spec["properties"]}
        assert "registrationNumber" in org_prop_names


# ---------------------------------------------------------------------------
# 3. Coverage report — specialization alignment
# ---------------------------------------------------------------------------

# Inline domain ontology: a Party-like domain with a property that name-matches
# a subclass property (registrationNumber → Organisation.registrationNumber).
_DOMAIN_WITH_SPEC_MATCH_TTL = """\
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix test: <https://test.example/spec-coverage#> .

<https://test.example/spec-coverage> a owl:Ontology ;
    rdfs:label "Spec Coverage Test" ;
    owl:versionInfo "1.0.0" .

test:Company a owl:Class ;
    rdfs:label "Company" ;
    rdfs:comment "A company entity." .

test:companyName a owl:DatatypeProperty ;
    rdfs:label "company name" ;
    rdfs:domain test:Company ;
    rdfs:range xsd:string .

test:registrationNumber a owl:DatatypeProperty ;
    rdfs:label "registration number" ;
    rdfs:domain test:Company ;
    rdfs:range xsd:string .
"""


class TestCoverageSpecialization:
    """Coverage report correctly classifies specialization matches."""

    def _get_ref_domains_with_specs(self):
        """Parse the party reference model with specializations enabled."""
        ref_path = REF_MODELS_DIR / "kairos-ref-party.ttl"
        return [parse_reference_model(ref_path, include_specializations=True)]

    def test_coverage_report_specialization_alignment(self, tmp_path):
        """registrationNumber should match as 'specialization', not 'direct'."""
        # Write temp domain ontology
        ont_path = tmp_path / "spec-domain.ttl"
        ont_path.write_text(_DOMAIN_WITH_SPEC_MATCH_TTL, encoding="utf-8")

        ont_data = parse_domain_ontology(ont_path)
        ref_domains = self._get_ref_domains_with_specs()
        ref_index = _build_ref_index(ref_domains)

        # Align
        class_alignments = align_classes_deterministic(ont_data, ref_index)

        # Company should NOT match Party by name (different name).
        # It won't have a ref_class, so specialization matching won't fire.
        # To test specialization matching, we need the class to match Party first.
        # Let's test _align_properties directly with a ref_cls that has specializations.
        party_ref = ref_index["by_name"]["party"]
        company_cls = next(c for c in ont_data["classes"] if c["name"] == "Company")

        prop_alignments = _align_properties(company_cls, party_ref, ref_index)

        # registrationNumber should be a specialization match
        reg_align = next(
            pa for pa in prop_alignments
            if pa["ontology_property"] == "registrationNumber"
        )
        assert reg_align["alignment"] == "specialization"
        assert reg_align["confidence"] == 0.5
        assert reg_align["specialization_class"] == "Organisation"
        assert "Organisation" in reg_align["refinement_suggestion"]

        # companyName should NOT match as specialization (no ref counterpart)
        name_align = next(
            pa for pa in prop_alignments
            if pa["ontology_property"] == "companyName"
        )
        assert name_align["alignment"] == "custom"

    def test_coverage_specialization_excluded_from_percentage(self, tmp_path):
        """Specialization matches must NOT inflate coverage %."""
        # Domain with 2 properties: partyName (direct match) + registrationNumber (spec match)
        domain_ttl = """\
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix test: <https://test.example/pct#> .

<https://test.example/pct> a owl:Ontology ;
    rdfs:label "Pct Test" ;
    owl:versionInfo "1.0.0" .

test:Party a owl:Class ;
    rdfs:label "Party" ;
    rdfs:comment "A party." .

test:partyName a owl:DatatypeProperty ;
    rdfs:label "party name" ;
    rdfs:domain test:Party ;
    rdfs:range xsd:string .

test:registrationNumber a owl:DatatypeProperty ;
    rdfs:label "registration number" ;
    rdfs:domain test:Party ;
    rdfs:range xsd:string .
"""
        ont_path = tmp_path / "pct-domain.ttl"
        ont_path.write_text(domain_ttl, encoding="utf-8")

        ont_data = parse_domain_ontology(ont_path)
        ref_domains = self._get_ref_domains_with_specs()
        ref_index = _build_ref_index(ref_domains)

        # Party class name-matches ref Party
        party_ref = ref_index["by_name"]["party"]
        party_cls = next(c for c in ont_data["classes"] if c["name"] == "Party")

        prop_alignments = _align_properties(party_cls, party_ref, ref_index)

        # partyName → direct name-match
        name_pa = next(p for p in prop_alignments if p["ontology_property"] == "partyName")
        assert name_pa["alignment"] == "name-match"

        # registrationNumber → specialization
        reg_pa = next(
            p for p in prop_alignments if p["ontology_property"] == "registrationNumber"
        )
        assert reg_pa["alignment"] == "specialization"

        # Coverage should count only non-custom, non-specialization
        aligned = sum(
            1 for p in prop_alignments
            if p["alignment"] not in ("custom", "specialization")
        )
        total = len(prop_alignments)
        pct = round(aligned / total * 100)

        assert total == 2
        assert aligned == 1  # only partyName
        assert pct == 50, f"Expected 50% coverage, got {pct}%"


# ---------------------------------------------------------------------------
# 4. Propose-alignment prompt — specialization hints
# ---------------------------------------------------------------------------


class TestPromptSpecializationHints:
    """LLM prompt includes specialization properties for better matching."""

    def test_propose_alignment_prompt_includes_specialization_hints(self):
        """_format_ref_inventory() should include Specialization subsections."""
        ref_path = REF_MODELS_DIR / "kairos-ref-party.ttl"
        result = parse_reference_model(ref_path, include_specializations=True)

        formatted = _format_ref_inventory(result["classes"])

        # Should contain the specializations header and subclass details
        assert "Specializations" in formatted
        assert "Organisation" in formatted
        assert "registrationNumber" in formatted
        assert "Person" in formatted
        assert "firstName" in formatted
        assert "lastName" in formatted
