# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for inventory module (DD-044)."""

from pathlib import PurePosixPath, PureWindowsPath

import pytest
from rdflib import Graph

from kairos_ontology.core.inventory import (
    _canonical_filename_from_generated_from,
    generate_inventory,
    inventory_filename,
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
        # No root was passed and the source isn't under either root, so
        # provenance falls back to the bare filename (issue #404) — not the
        # machine-local absolute path.
        assert inv["generated_from"] == "party.ttl"
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

    def test_class_includes_uri(self, tmp_path):
        ref_file = tmp_path / "party.ttl"
        ref_file.write_text(SAMPLE_REF_MODEL_TTL, encoding="utf-8")

        inv = generate_inventory(ref_file)

        party_cls = next(c for c in inv["classes"] if c["name"] == "Party")
        assert party_cls["uri"] == "https://kairos.cnext.eu/ref/party#Party"
        # Every class carries its canonical IRI (no reconstruction needed).
        assert all(c.get("uri") for c in inv["classes"])
        org_cls = next(c for c in inv["classes"] if c["name"] == "Organisation")
        assert org_cls["uri"] == "https://kairos.cnext.eu/ref/party#Organisation"


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
        loaded_party = next(c for c in loaded["classes"] if c["name"] == "Party")
        assert loaded_party["uri"] == "https://kairos.cnext.eu/ref/party#Party"

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
        org_spec = next(s for s in party_cls["specializations"] if s["class"] == "Organisation")
        prop_names = {p["name"] for p in org_spec["properties"]}
        assert "registrationNumber" in prop_names


class TestContentAddressedWrites:
    """DD-154 (#419): write_inventory skips content-identical rewrites so idempotent
    reruns (init --domain, generate-inventory) produce zero diff churn — only a
    change to something other than ``generated_at`` triggers a write."""

    def _inventory(self, tmp_path):
        ref_file = tmp_path / "party.ttl"
        if not ref_file.exists():
            ref_file.write_text(SAMPLE_REF_MODEL_TTL, encoding="utf-8")
        return generate_inventory(ref_file)

    def test_first_write_returns_true(self, tmp_path):
        inv = self._inventory(tmp_path)
        out_path = tmp_path / "inv.yaml"

        assert write_inventory(inv, out_path) is True
        assert out_path.exists()

    def test_identical_rewrite_skips_and_preserves_bytes_and_mtime(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KAIROS_GENERATED_AT", "2026-08-01T00:00:00Z")
        inv = self._inventory(tmp_path)
        out_path = tmp_path / "inv.yaml"
        assert write_inventory(inv, out_path) is True
        before_bytes = out_path.read_bytes()
        before_mtime = out_path.stat().st_mtime_ns

        # A later run stamps a different generated_at — the only churn of #419.
        monkeypatch.setenv("KAIROS_GENERATED_AT", "2026-08-15T12:34:56Z")
        inv2 = self._inventory(tmp_path)
        assert inv2["generated_at"] != inv["generated_at"]

        assert write_inventory(inv2, out_path) is False
        assert out_path.read_bytes() == before_bytes
        assert out_path.stat().st_mtime_ns == before_mtime

    def test_content_change_writes_even_with_same_generated_at(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KAIROS_GENERATED_AT", "2026-08-01T00:00:00Z")
        inv = self._inventory(tmp_path)
        out_path = tmp_path / "inv.yaml"
        assert write_inventory(inv, out_path) is True

        changed = dict(inv)
        changed["domain_name"] = "PartyRenamed"
        assert changed["generated_at"] == inv["generated_at"]

        assert write_inventory(changed, out_path) is True
        assert "PartyRenamed" in out_path.read_text(encoding="utf-8")

    def test_corrupt_existing_file_is_rewritten_without_raising(self, tmp_path):
        inv = self._inventory(tmp_path)
        out_path = tmp_path / "inv.yaml"
        out_path.write_bytes(b"\xff\xfegarbage not yaml \x00\x9c")

        assert write_inventory(inv, out_path) is True
        loaded = load_inventory(out_path)
        assert loaded["domain_name"] == "Party"

    def test_crlf_and_lf_checkouts_both_compare_equal(self, tmp_path, monkeypatch):
        """A CRLF checkout (Windows core.autocrlf) and an LF checkout must both
        compare equal to the freshly-dumped envelope — the compare is
        newline-normalised, so neither causes perpetual rewrites."""
        monkeypatch.setenv("KAIROS_GENERATED_AT", "2026-08-01T00:00:00Z")
        inv = self._inventory(tmp_path)
        out_path = tmp_path / "inv.yaml"
        assert write_inventory(inv, out_path) is True

        # read_text normalises to \n regardless of what the platform wrote.
        text = out_path.read_text(encoding="utf-8")
        for newline_variant in ("\n", "\r\n"):
            checkout_bytes = text.replace("\n", newline_variant).encode("utf-8")
            out_path.write_bytes(checkout_bytes)

            assert write_inventory(inv, out_path) is False
            # Skipped: the bytes are left exactly as the checkout produced them.
            assert out_path.read_bytes() == checkout_bytes


class TestInventoryFilename:
    """DD-054: reference-model inventories are namespaced by owning model."""

    def test_ref_model_is_namespaced_by_model(self, tmp_path):
        ref_root = tmp_path / "ontology-reference-models"
        ttl = ref_root / "derived-ontologies" / "BSP" / "current" / "party" / "party.ttl"
        assert inventory_filename(ttl, ref_models_dir=ref_root) == "bsp-party-inventory.yaml"

    def test_ref_model_ignores_intermediate_segments(self, tmp_path):
        # DCSA has an extra shared-kernel segment that must not affect the name.
        ref_root = tmp_path / "ontology-reference-models"
        ttl = (
            ref_root
            / "derived-ontologies"
            / "DCSA"
            / "current"
            / "shared-kernel"
            / "party"
            / "party.ttl"
        )
        assert inventory_filename(ttl, ref_models_dir=ref_root) == "dcsa-party-inventory.yaml"

    def test_same_stem_different_models_do_not_collide(self, tmp_path):
        ref_root = tmp_path / "ontology-reference-models"
        bsp = ref_root / "derived-ontologies" / "BSP" / "current" / "party" / "party.ttl"
        imo = ref_root / "derived-ontologies" / "IMO" / "current" / "party" / "party.ttl"
        assert inventory_filename(bsp, ref_models_dir=ref_root) != inventory_filename(
            imo, ref_models_dir=ref_root
        )

    def test_hub_ontology_keeps_stem_naming(self, tmp_path):
        ttl = tmp_path / "model" / "ontologies" / "client.ttl"
        assert inventory_filename(ttl) == "client-inventory.yaml"

    def test_ref_ttl_without_marker_falls_back_to_stem(self, tmp_path):
        ref_root = tmp_path / "refs"
        ttl = ref_root / "party.ttl"
        assert inventory_filename(ttl, ref_models_dir=ref_root) == "party-inventory.yaml"


class TestIsPatternTemplateSource:
    """Issue #406: pattern-library template stubs must never be inventoried — every
    ``blueprints/patterns/<id>/template.ttl`` would otherwise collapse onto the same
    ``template-inventory.yaml`` name (``_ref_model_id`` only namespaces paths under
    ``derived-ontologies``)."""

    def test_matches_pattern_template(self, tmp_path):
        from kairos_ontology.core.inventory import is_pattern_template_source

        ref_root = tmp_path / "ontology-reference-models"
        ttl = ref_root / "blueprints" / "patterns" / "deferred-relationship" / "template.ttl"
        assert is_pattern_template_source(ttl, ref_models_dir=ref_root) is True

    def test_different_pattern_id_also_matches(self, tmp_path):
        from kairos_ontology.core.inventory import is_pattern_template_source

        ref_root = tmp_path / "ontology-reference-models"
        ttl = ref_root / "blueprints" / "patterns" / "multimodal-order-leg" / "template.ttl"
        assert is_pattern_template_source(ttl, ref_models_dir=ref_root) is True

    def test_does_not_match_real_reference_model(self, tmp_path):
        from kairos_ontology.core.inventory import is_pattern_template_source

        ref_root = tmp_path / "ontology-reference-models"
        ttl = ref_root / "derived-ontologies" / "BSP" / "current" / "party" / "party.ttl"
        assert is_pattern_template_source(ttl, ref_models_dir=ref_root) is False

    def test_does_not_match_archetype_blueprints(self, tmp_path):
        """``blueprints/archetypes/`` is a sibling of ``blueprints/patterns/`` and must
        not be caught by the same two-segment subsequence match."""
        from kairos_ontology.core.inventory import is_pattern_template_source

        ref_root = tmp_path / "ontology-reference-models"
        ttl = ref_root / "blueprints" / "archetypes" / "passthrough.yaml"
        assert is_pattern_template_source(ttl, ref_models_dir=ref_root) is False

    def test_un_normalized_root_still_matches(self, tmp_path):
        """The predicate is resolved the same way ``pattern_loader._patterns_dir`` is
        (via ``normalize_refmodels_root``'s sibling-checkout tolerance): passing the
        repository root rather than the inner ``ontology-reference-models/`` must not
        make it miss."""
        from kairos_ontology.core.inventory import is_pattern_template_source

        repo_root = tmp_path
        ttl = (
            repo_root
            / "ontology-reference-models"
            / "blueprints"
            / "patterns"
            / "deferred-relationship"
            / "template.ttl"
        )
        # Even without passing ref_models_dir at all, the two-segment subsequence
        # match still finds "blueprints/patterns" anywhere in the absolute parts.
        assert is_pattern_template_source(ttl) is True

    def test_iter_reference_inventory_sources_excludes_pattern_templates(self, tmp_path):
        from kairos_ontology.core.inventory import iter_reference_inventory_sources

        ref_root = tmp_path / "ontology-reference-models"
        real = ref_root / "derived-ontologies" / "BSP" / "current" / "party" / "party.ttl"
        real.parent.mkdir(parents=True)
        real.write_text(SAMPLE_REF_MODEL_TTL, encoding="utf-8")
        for pattern_id in ("deferred-relationship", "multimodal-order-leg"):
            template = ref_root / "blueprints" / "patterns" / pattern_id / "template.ttl"
            template.parent.mkdir(parents=True)
            template.write_text(SAMPLE_REF_MODEL_TTL, encoding="utf-8")

        sources = iter_reference_inventory_sources(ref_root)

        assert sources == [real]


class TestGeneratedFromProvenance:
    """Issue #404: ``generated_from`` must be portable, not a machine-local path."""

    def test_relative_to_root(self, tmp_path):
        root = tmp_path / "ontology-reference-models"
        ttl = root / "derived-ontologies" / "BSP" / "current" / "party" / "party.ttl"
        ttl.parent.mkdir(parents=True)
        ttl.write_text(SAMPLE_REF_MODEL_TTL, encoding="utf-8")

        inv = generate_inventory(ttl, relative_to=root)

        assert inv["generated_from"] == "derived-ontologies/BSP/current/party/party.ttl"

    def test_relative_generated_from_is_portable(self, tmp_path):
        root = tmp_path / "ontology-reference-models"
        ttl = root / "derived-ontologies" / "BSP" / "current" / "party" / "party.ttl"
        ttl.parent.mkdir(parents=True)
        ttl.write_text(SAMPLE_REF_MODEL_TTL, encoding="utf-8")

        inv = generate_inventory(ttl, relative_to=root)
        v = inv["generated_from"]

        assert not PurePosixPath(v).is_absolute()
        assert "\\" not in v
        assert ":" not in v

    def test_round_trip_filename_derivation_ontology_reference_models_root(self, tmp_path):
        # Normal case: --ref-models-dir points at ontology-reference-models/ itself,
        # so the relative provenance still contains the derived-ontologies marker.
        root = tmp_path / "ontology-reference-models"
        ttl = root / "derived-ontologies" / "BSP" / "current" / "party" / "party.ttl"
        ttl.parent.mkdir(parents=True)
        ttl.write_text(SAMPLE_REF_MODEL_TTL, encoding="utf-8")

        inv = generate_inventory(ttl, relative_to=root)
        canonical = _canonical_filename_from_generated_from(inv)
        expected = inventory_filename(ttl, ref_models_dir=root)

        assert expected == "bsp-party-inventory.yaml"
        assert canonical == expected

    def test_round_trip_filename_derivation_derived_ontologies_root(self, tmp_path):
        # Hazard case: --ref-models-dir points *at* derived-ontologies/ itself (the
        # CLI passes --ref-models-dir straight through, unnormalised). The relative
        # provenance then has no derived-ontologies marker to find, so the reader
        # must not assert a namespaced filename it cannot derive — it must agree
        # with (or defer to) the un-namespaced name generate-inventory actually
        # wrote, never raise a mismatch.
        ref_root = tmp_path / "ontology-reference-models"
        derived_root = ref_root / "derived-ontologies"
        ttl = derived_root / "BSP" / "current" / "party" / "party.ttl"
        ttl.parent.mkdir(parents=True)
        ttl.write_text(SAMPLE_REF_MODEL_TTL, encoding="utf-8")

        inv = generate_inventory(ttl, relative_to=derived_root)
        canonical = _canonical_filename_from_generated_from(inv)
        expected = inventory_filename(ttl, ref_models_dir=derived_root)

        assert expected == "party-inventory.yaml"
        assert canonical is None or canonical == expected

    def test_relative_generated_from_cross_os_parse(self, tmp_path):
        root = tmp_path / "ontology-reference-models"
        ttl = root / "derived-ontologies" / "BSP" / "current" / "party" / "party.ttl"
        ttl.parent.mkdir(parents=True)
        ttl.write_text(SAMPLE_REF_MODEL_TTL, encoding="utf-8")

        inv = generate_inventory(ttl, relative_to=root)
        v = inv["generated_from"]

        assert "derived-ontologies" in PurePosixPath(v).parts
        assert PureWindowsPath(v).stem == "party"

    def test_graph_sentinel_unchanged(self):
        inv = generate_inventory(graph=Graph(), domain_name="Party")

        assert inv["generated_from"] == "(graph)"
