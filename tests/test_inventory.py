# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for inventory module (DD-044)."""


import pytest

from kairos_ontology.inventory import (
    generate_inventory,
    write_inventory,
    load_inventory,
    INVENTORY_VERSION,
)

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
    rdfs:comment "A business party" .

ref-party:Organisation a owl:Class ;
    rdfs:subClassOf ref-party:Party ;
    rdfs:label "Organisation" .

ref-party:partyName a owl:DatatypeProperty ;
    rdfs:label "Party name" ;
    rdfs:domain ref-party:Party ;
    rdfs:range xsd:string .

ref-party:registrationNumber a owl:DatatypeProperty ;
    rdfs:label "Registration number" ;
    rdfs:domain ref-party:Organisation ;
    rdfs:range xsd:string .
"""


class TestGenerateInventory:

    def test_generates_with_version_and_domain(self, tmp_path):
        ref_file = tmp_path / "party.ttl"
        ref_file.write_text(SAMPLE_REF_MODEL_TTL, encoding="utf-8")

        inv = generate_inventory(ref_file)

        assert inv["version"] == INVENTORY_VERSION
        assert inv["domain_name"] == "Party"
        assert "generated_at" in inv
        assert str(ref_file) in inv["generated_from"]
        assert inv["source_sha256"]  # provenance hash present (DD-047)

    def test_includes_specializations_by_default(self, tmp_path):
        ref_file = tmp_path / "party.ttl"
        ref_file.write_text(SAMPLE_REF_MODEL_TTL, encoding="utf-8")

        inv = generate_inventory(ref_file)

        party_cls = next(c for c in inv["classes"] if c["name"] == "Party")
        assert "specializations" in party_cls
        spec_names = {s["class"] for s in party_cls["specializations"]}
        assert "Organisation" in spec_names

    def test_specializations_disabled(self, tmp_path):
        ref_file = tmp_path / "party.ttl"
        ref_file.write_text(SAMPLE_REF_MODEL_TTL, encoding="utf-8")

        inv = generate_inventory(ref_file, include_specializations=False)

        party_cls = next(c for c in inv["classes"] if c["name"] == "Party")
        assert "specializations" not in party_cls


class TestWriteAndLoadInventory:

    def test_yaml_round_trip(self, tmp_path):
        ref_file = tmp_path / "party.ttl"
        ref_file.write_text(SAMPLE_REF_MODEL_TTL, encoding="utf-8")

        inv = generate_inventory(ref_file)
        out_path = tmp_path / "inventory" / "ref-party-inventory.yaml"
        write_inventory(inv, out_path)

        assert out_path.exists()

        loaded = load_inventory(out_path)
        assert loaded["version"] == INVENTORY_VERSION
        assert loaded["domain_name"] == "Party"
        assert len(loaded["classes"]) == len(inv["classes"])

    def test_creates_parent_dirs(self, tmp_path):
        ref_file = tmp_path / "party.ttl"
        ref_file.write_text(SAMPLE_REF_MODEL_TTL, encoding="utf-8")

        inv = generate_inventory(ref_file)
        deep_path = tmp_path / "a" / "b" / "c" / "inv.yaml"
        write_inventory(inv, deep_path)

        assert deep_path.exists()

    def test_load_nonexistent_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_inventory(tmp_path / "nonexistent.yaml")

    def test_load_invalid_yaml_raises(self, tmp_path):
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("- just\n- a\n- list\n", encoding="utf-8")

        with pytest.raises(ValueError, match="does not contain a YAML mapping"):
            load_inventory(bad_file)

    def test_specialization_properties_in_yaml(self, tmp_path):
        ref_file = tmp_path / "party.ttl"
        ref_file.write_text(SAMPLE_REF_MODEL_TTL, encoding="utf-8")

        inv = generate_inventory(ref_file)
        out_path = tmp_path / "inv.yaml"
        write_inventory(inv, out_path)

        loaded = load_inventory(out_path)
        party_cls = next(c for c in loaded["classes"] if c["name"] == "Party")
        org_spec = next(
            s for s in party_cls["specializations"] if s["class"] == "Organisation"
        )
        prop_names = {p["name"] for p in org_spec["properties"]}
        assert "registrationNumber" in prop_names
