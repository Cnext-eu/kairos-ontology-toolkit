# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unit tests for kairos_ontology.core.archetype_loader (DD-090)."""

from __future__ import annotations

import json

import pytest
import yaml

from archetype_fixtures import build_refmodels_root
from kairos_ontology.core.archetype_loader import (
    VALID_TIERS,
    ArchetypeError,
    check_version_drift,
    list_archetypes,
    load_archetype,
    load_outcome_codes,
    load_valid_tiers,
    locate_discovery_doc,
    normalize_refmodels_root,
    resolve_refmodels_root,
)


@pytest.fixture()
def refroot(tmp_path):
    return build_refmodels_root(tmp_path)


class TestRootResolution:
    def test_normalize_accepts_inner_root(self, refroot):
        assert normalize_refmodels_root(refroot) == refroot

    def test_normalize_accepts_repo_root(self, refroot):
        repo_root = refroot.parent  # the outer dir containing ontology-reference-models/
        assert normalize_refmodels_root(repo_root) == refroot

    def test_normalize_rejects_unrelated_dir(self, tmp_path):
        with pytest.raises(ArchetypeError):
            normalize_refmodels_root(tmp_path)

    def test_resolve_via_env_var(self, refroot, monkeypatch):
        monkeypatch.setenv("KAIROS_REFMODELS_ROOT", str(refroot.parent))
        assert resolve_refmodels_root() == refroot

    def test_resolve_explicit_wins_over_env(self, refroot, monkeypatch, tmp_path):
        monkeypatch.setenv("KAIROS_REFMODELS_ROOT", str(tmp_path))  # bogus
        assert resolve_refmodels_root(explicit=refroot) == refroot

    def test_resolve_fails_without_any_source(self, tmp_path, monkeypatch):
        monkeypatch.delenv("KAIROS_REFMODELS_ROOT", raising=False)
        with pytest.raises(ArchetypeError):
            resolve_refmodels_root(cwd=tmp_path, hub_root=None)


class TestListAndOutcomeCodes:
    def test_list_archetypes_excludes_noise(self, refroot):
        assert list_archetypes(refroot) == ["test-carrier"]

    def test_outcome_codes_loaded_from_contract(self, refroot):
        codes = load_outcome_codes(refroot)
        assert codes == [
            "conforms", "conforms-with-rename", "partial", "deviates", "not-applicable",
        ]

    def test_outcome_codes_missing_raises(self, refroot):
        (refroot / "blueprints" / "archetypes" / "_schema" / "outcome-codes.yaml").unlink()
        with pytest.raises(ArchetypeError):
            load_outcome_codes(refroot)


class TestValidTiers:
    """The tier enum is owned by reference-models (#276 Q4) — resolve, don't hardcode."""

    _SCHEMA_RELPATH = ("blueprints", "archetypes", "_schema", "archetype.schema.json")

    def _schema_path(self, refroot):
        return refroot.joinpath(*self._SCHEMA_RELPATH)

    def test_resolves_published_enum(self, refroot):
        assert load_valid_tiers(refroot) == ("required", "recommended", "optional")

    def test_picks_up_a_newly_published_tier_without_a_toolkit_release(self, refroot):
        path = self._schema_path(refroot)
        schema = json.loads(path.read_text(encoding="utf-8"))
        schema["$defs"]["tier"]["enum"].append("not_applicable")
        path.write_text(json.dumps(schema), encoding="utf-8")
        assert load_valid_tiers(refroot) == (
            "required", "recommended", "optional", "not_applicable",
        )

    def test_falls_back_when_schema_absent(self, refroot):
        self._schema_path(refroot).unlink()
        assert load_valid_tiers(refroot) == VALID_TIERS

    def test_falls_back_on_malformed_schema(self, refroot):
        self._schema_path(refroot).write_text("{not json", encoding="utf-8")
        assert load_valid_tiers(refroot) == VALID_TIERS

    def test_falls_back_when_enum_is_missing_or_wrong_shape(self, refroot):
        path = self._schema_path(refroot)
        schema = json.loads(path.read_text(encoding="utf-8"))
        schema["$defs"]["tier"] = {"type": "string"}  # no enum
        path.write_text(json.dumps(schema), encoding="utf-8")
        assert load_valid_tiers(refroot) == VALID_TIERS

    def test_accepts_an_outer_repo_root(self, refroot):
        """The schema loader normalizes its root like every other entry point does."""
        assert load_valid_tiers(refroot.parent) == ("required", "recommended", "optional")


class TestLoadArchetype:
    def test_loads_modules_and_concepts(self, refroot):
        a = load_archetype(refroot, "test-carrier")
        assert a.id == "test-carrier"
        assert len(a.ref_model_modules) == 2
        assert len(a.core_concepts) == 4
        assert a.catalog_hash and a.concept_set_hash()

    def test_concept_set_hash_is_order_independent(self, refroot):
        a = load_archetype(refroot, "test-carrier")
        h1 = a.concept_set_hash()
        a.core_concepts.reverse()
        assert a.concept_set_hash() == h1

    def test_missing_archetype_raises(self, refroot):
        with pytest.raises(ArchetypeError, match="not found"):
            load_archetype(refroot, "does-not-exist")

    def test_schema_version_mismatch_hard_fails(self, refroot):
        path = refroot / "blueprints" / "archetypes" / "test-carrier.yaml"
        data = yaml.safe_load(path.read_text())
        data["schema_version"] = 2
        path.write_text(yaml.safe_dump(data))
        with pytest.raises(ArchetypeError, match="schema_version"):
            load_archetype(refroot, "test-carrier")

    def test_additional_property_rejected(self, refroot):
        path = refroot / "blueprints" / "archetypes" / "test-carrier.yaml"
        data = yaml.safe_load(path.read_text())
        data["unexpected_key"] = "boom"
        path.write_text(yaml.safe_dump(data))
        with pytest.raises(ArchetypeError, match="schema validation"):
            load_archetype(refroot, "test-carrier")

    def test_missing_required_field_rejected(self, refroot):
        path = refroot / "blueprints" / "archetypes" / "test-carrier.yaml"
        data = yaml.safe_load(path.read_text())
        del data["label"]
        path.write_text(yaml.safe_dump(data))
        with pytest.raises(ArchetypeError, match="schema validation"):
            load_archetype(refroot, "test-carrier")

    def test_bad_uri_rejected(self, refroot):
        path = refroot / "blueprints" / "archetypes" / "test-carrier.yaml"
        data = yaml.safe_load(path.read_text())
        data["core_concepts"][0]["uri"] = "not-a-url"
        path.write_text(yaml.safe_dump(data))
        with pytest.raises(ArchetypeError, match="schema validation"):
            load_archetype(refroot, "test-carrier")

    def test_id_filename_mismatch_rejected(self, refroot):
        path = refroot / "blueprints" / "archetypes" / "test-carrier.yaml"
        data = yaml.safe_load(path.read_text())
        data["id"] = "other-id"
        path.write_text(yaml.safe_dump(data))
        with pytest.raises(ArchetypeError, match="does not match filename"):
            load_archetype(refroot, "test-carrier")


class TestDiscoveryDocPairing:
    def test_locates_paired_doc(self, refroot):
        doc = locate_discovery_doc(refroot, "test-carrier")
        assert doc is not None and doc.name == "test-carrier.md"

    def test_missing_doc_returns_none(self, refroot):
        assert locate_discovery_doc(refroot, "no-such-archetype") is None

    def test_multi_pack_match_raises(self, tmp_path):
        root = build_refmodels_root(tmp_path, add_duplicate_discovery=True)
        with pytest.raises(ArchetypeError, match="ambiguous"):
            locate_discovery_doc(root, "test-carrier")


class TestVersionDrift:
    def test_no_warning_when_in_range(self, refroot):
        a = load_archetype(refroot, "test-carrier")
        assert check_version_drift(a, refroot) == []

    def test_warns_when_out_of_range(self, tmp_path):
        root = build_refmodels_root(tmp_path, repo_version="2.5.0")
        a = load_archetype(root, "test-carrier")
        warnings = check_version_drift(a, root)
        assert any("repo_tag_range" in w for w in warnings)

    def test_ontology_versions_in_range_no_warning(self, refroot):
        # Fixture pins booking >=1.0.0,<2 with VERSION 1.2.0.
        a = load_archetype(refroot, "test-carrier")
        assert check_version_drift(a, refroot) == []

    def test_warns_when_ontology_version_out_of_range(self, tmp_path):
        root = build_refmodels_root(tmp_path, booking_version="2.0.0")
        a = load_archetype(root, "test-carrier")
        warnings = check_version_drift(a, root)
        assert any("ontology_versions" in w and "booking" in w for w in warnings)

    def test_ontology_versions_missing_module_no_crash(self, tmp_path):
        # Build a root without the derived-ontologies tree by using a custom archetype
        # whose ontology_versions key has no matching folder.
        root = build_refmodels_root(tmp_path)
        a = load_archetype(root, "test-carrier")
        a.compatible_with["ontology_versions"] = {"UnknownModule": ">=1.0.0,<2"}
        # No crash, no false positive.
        assert check_version_drift(a, root) == []

    def test_ontology_versions_omitted_backward_compatible(self, tmp_path):
        root = build_refmodels_root(tmp_path, repo_version="2.5.0")
        a = load_archetype(root, "test-carrier")
        del a.compatible_with["ontology_versions"]
        warnings = check_version_drift(a, root)
        # Only the repo_tag_range warning fires; behaviour unchanged from pre-fix.
        assert any("repo_tag_range" in w for w in warnings)
        assert not any("ontology_versions" in w for w in warnings)


class TestModuleVersionAcrossTiers:
    """A pin can name a module in any ontology tier, not just ``derived-ontologies/`` (#276 Q3).

    Before this, a blueprint-tier pin resolved to ``None`` and was skipped silently — so the one
    module on a 0.x cadence, already declared ``required`` by ``freight-forwarder``, had no drift
    coverage whatsoever.
    """

    def test_blueprint_tier_pin_is_checked(self, tmp_path):
        root = build_refmodels_root(tmp_path, blueprint_version="0.1.0")
        a = load_archetype(root, "test-carrier")
        a.compatible_with["ontology_versions"] = {"Blueprint": ">=1.0.0,<2"}
        warnings = check_version_drift(a, root)
        assert any("Blueprint" in w and "0.1.0" in w for w in warnings)

    def test_blueprint_tier_pin_in_range_is_quiet(self, tmp_path):
        root = build_refmodels_root(tmp_path, blueprint_version="0.1.0")
        a = load_archetype(root, "test-carrier")
        a.compatible_with["ontology_versions"] = {"blueprints": ">=0.1.0,<1"}
        assert check_version_drift(a, root) == []

    def test_authoritative_tier_pin_is_checked(self, tmp_path):
        root = build_refmodels_root(tmp_path, authoritative_version="1.0.0")
        a = load_archetype(root, "test-carrier")
        a.compatible_with["ontology_versions"] = {"FIBO": ">=2.0.0,<3"}
        warnings = check_version_drift(a, root)
        assert any("FIBO" in w and "1.0.0" in w for w in warnings)

    def test_blueprint_pin_without_a_blueprint_tier_stays_silent(self, tmp_path):
        # No blueprints/ontology/VERSION in this checkout — still "no signal", never a crash.
        root = build_refmodels_root(tmp_path)
        a = load_archetype(root, "test-carrier")
        a.compatible_with["ontology_versions"] = {"Blueprint": ">=9.0.0,<10"}
        assert check_version_drift(a, root) == []
