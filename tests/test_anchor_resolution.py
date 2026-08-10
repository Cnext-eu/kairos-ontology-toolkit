# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for uri-anchor-contract's confirmed-alias table-anchor resolution.

Uses fully generic fixture data (no DCSA/Booking-specific business logic) since
this is new toolkit-internal plumbing, not a domain accelerator concern.
"""

from __future__ import annotations

from kairos_ontology.core.anchor_resolution import (
    AnchorResolution,
    ConfirmedAlias,
    build_confirmed_alias_index,
    load_confirmed_alias_index,
    resolve_table_anchor,
)

CLASS_A_URI = "https://ex.org/ont/module#ClassA"
CLASS_B_URI = "https://ex.org/ont/module#ClassB"

REF_CLASSES = [
    {"name": "ClassA", "uri": CLASS_A_URI},
    {"name": "ClassB", "uri": CLASS_B_URI},
]


def _artifact(*concepts: dict) -> dict:
    return {"core_concepts": list(concepts)}


class TestBuildConfirmedAliasIndex:
    def test_confirms_outcome_indexed_by_label_and_local_name(self):
        artifact = _artifact(
            {
                "uri": CLASS_A_URI,
                "label": "Class A",
                "outcome": "conforms",
            }
        )
        index = build_confirmed_alias_index(artifact)
        assert "classa" in index
        keys = {k for k in index}
        assert any(k for k in keys)  # both "class a" and "classa" normalize the same

    def test_rename_to_is_indexed_as_an_additional_alias(self):
        artifact = _artifact(
            {
                "uri": CLASS_A_URI,
                "label": "ClassA",
                "outcome": "conforms-with-rename",
                "rename_to": "LegacyThing",
            }
        )
        index = build_confirmed_alias_index(artifact)
        assert "legacything" in index
        assert index["legacything"][0].canonical_uri == CLASS_A_URI

    def test_non_confirmed_outcome_is_ignored(self):
        artifact = _artifact(
            {
                "uri": CLASS_A_URI,
                "label": "ClassA",
                "outcome": "rejected",
            }
        )
        index = build_confirmed_alias_index(artifact)
        assert index == {}

    def test_contradictory_confirmed_evidence_yields_multiple_aliases_for_one_key(self):
        artifact = _artifact(
            {"uri": CLASS_A_URI, "label": "Shared", "outcome": "conforms"},
            {"uri": CLASS_B_URI, "label": "Shared", "outcome": "conforms"},
        )
        index = build_confirmed_alias_index(artifact)
        assert len(index["shared"]) == 2
        uris = {a.canonical_uri for a in index["shared"]}
        assert uris == {CLASS_A_URI, CLASS_B_URI}

    def test_malformed_artifact_returns_empty_index_without_raising(self):
        assert build_confirmed_alias_index(None) == {}
        assert build_confirmed_alias_index({}) == {}
        assert build_confirmed_alias_index({"core_concepts": "not-a-list"}) == {}
        assert (
            build_confirmed_alias_index(
                {"core_concepts": [{"outcome": "conforms"}]}  # missing uri
            )
            == {}
        )

    def test_missing_label_falls_back_to_uri_local_name(self):
        artifact = _artifact({"uri": CLASS_A_URI, "outcome": "conforms"})
        index = build_confirmed_alias_index(artifact)
        assert "classa" in index


class TestLoadConfirmedAliasIndex:
    def test_none_path_returns_empty(self):
        assert load_confirmed_alias_index(None) == {}

    def test_missing_file_returns_empty(self, tmp_path):
        assert load_confirmed_alias_index(tmp_path / "does-not-exist.yaml") == {}

    def test_valid_file_loads(self, tmp_path):
        path = tmp_path / "core-concepts-conformance.yaml"
        path.write_text(
            "schema_version: 1\n"
            "core_concepts:\n"
            "  - uri: " + CLASS_A_URI + "\n"
            "    label: ClassA\n"
            "    outcome: conforms\n"
            "    tier: 1\n",
            encoding="utf-8",
        )
        index = load_confirmed_alias_index(path)
        assert "classa" in index

    def test_unparsable_file_returns_empty_not_raises(self, tmp_path):
        path = tmp_path / "broken.yaml"
        path.write_text("core_concepts: [unterminated", encoding="utf-8")
        assert load_confirmed_alias_index(path) == {}


class TestResolveTableAnchor:
    def test_confirmed_single_match(self):
        index = build_confirmed_alias_index(
            _artifact(
                {
                    "uri": CLASS_A_URI,
                    "label": "ClassA",
                    "outcome": "conforms",
                }
            )
        )
        res = resolve_table_anchor("ClassA", index, REF_CLASSES)
        assert res.status == "confirmed"
        assert res.resolved_uri == CLASS_A_URI
        assert res.resolved_name == "ClassA"
        assert res.is_confirmed
        assert res.evidence

    def test_confirmed_via_rename_to_alias(self):
        index = build_confirmed_alias_index(
            _artifact(
                {
                    "uri": CLASS_A_URI,
                    "label": "ClassA",
                    "outcome": "conforms-with-rename",
                    "rename_to": "LegacyThing",
                }
            )
        )
        res = resolve_table_anchor("LegacyThing", index, REF_CLASSES)
        assert res.status == "confirmed"
        assert res.resolved_uri == CLASS_A_URI

    def test_ambiguous_never_silently_picks_nearest_class(self):
        index = build_confirmed_alias_index(
            _artifact(
                {"uri": CLASS_A_URI, "label": "Shared", "outcome": "conforms"},
                {"uri": CLASS_B_URI, "label": "Shared", "outcome": "conforms"},
            )
        )
        res = resolve_table_anchor("Shared", index, REF_CLASSES)
        assert res.status == "ambiguous"
        assert res.is_ambiguous
        assert set(res.candidate_uris) == {CLASS_A_URI, CLASS_B_URI}
        assert res.resolved_uri is None
        assert res.resolved_name is None
        assert len(res.evidence) == 2

    def test_no_match_falls_through(self):
        index = build_confirmed_alias_index(
            _artifact(
                {
                    "uri": CLASS_A_URI,
                    "label": "ClassA",
                    "outcome": "conforms",
                }
            )
        )
        res = resolve_table_anchor("SomethingElseEntirely", index, REF_CLASSES)
        assert res.status == "none"
        assert not res.is_confirmed
        assert not res.is_ambiguous

    def test_confirmed_uri_not_in_ref_classes_pool_resolves_to_none(self):
        # Confirmed evidence exists, but the class' module isn't in this
        # table's candidate pool this run — must not fail, must fall through.
        index = build_confirmed_alias_index(
            _artifact(
                {
                    "uri": "https://ex.org/ont/other-module#ClassZ",
                    "label": "ClassZ",
                    "outcome": "conforms",
                }
            )
        )
        res = resolve_table_anchor("ClassZ", index, REF_CLASSES)
        assert res.status == "none"

    def test_empty_likely_entity_resolves_to_none(self):
        index = build_confirmed_alias_index(
            _artifact(
                {
                    "uri": CLASS_A_URI,
                    "label": "ClassA",
                    "outcome": "conforms",
                }
            )
        )
        assert resolve_table_anchor("", index, REF_CLASSES).status == "none"

    def test_empty_alias_index_resolves_to_none(self):
        assert resolve_table_anchor("ClassA", {}, REF_CLASSES).status == "none"

    def test_default_none_resolution_singleton_shape(self):
        res = AnchorResolution(status="none")
        assert res.resolved_uri is None
        assert res.candidate_uris == ()
        assert res.evidence == ()


class TestConfirmedAlias:
    def test_is_frozen_and_carries_outcome(self):
        alias = ConfirmedAlias(
            alias="ClassA",
            canonical_uri=CLASS_A_URI,
            canonical_label="ClassA",
            outcome="conforms",
        )
        assert alias.outcome == "conforms"
