# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unit tests for kairos_ontology.core.archetype_loader (DD-090)."""

from __future__ import annotations

import pytest
import yaml

from archetype_fixtures import build_refmodels_root
from kairos_ontology.core.archetype_loader import (
    ArchetypeError,
    check_version_drift,
    list_archetypes,
    load_archetype,
    load_outcome_codes,
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
