# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the versioned, typed ``unresolved_anchor`` record (uri-anchor-contract).

Generic fixture data only — this is toolkit-internal plumbing, not a domain
accelerator concern.
"""

from __future__ import annotations

import yaml

from kairos_ontology.core.unresolved_anchors import (
    REASON_AMBIGUOUS_CONFIRMED_ALIAS,
    UNRESOLVED_ANCHOR_DOC_SCHEMA_VERSION,
    UNRESOLVED_ANCHOR_SCHEMA_VERSION,
    UnresolvedAnchor,
    load_unresolved_anchors_doc,
    merge_preserving_anchor_resolutions,
    unresolved_anchor_id,
    unresolved_anchors_path,
    write_unresolved_anchors_doc,
)

CLASS_A_URI = "https://ex.org/ont/module#ClassA"
CLASS_B_URI = "https://ex.org/ont/module#ClassB"


def _anchor(**overrides) -> UnresolvedAnchor:
    base = dict(
        id="domainx-sys1-tablea-anchor",
        domain="domainx",
        system="sys1",
        table="tablea",
        likely_entity="TableAEntity",
        candidate_uris=[CLASS_A_URI, CLASS_B_URI],
        evidence=["confirmed alias 'TableAEntity' -> " + CLASS_A_URI],
    )
    base.update(overrides)
    return UnresolvedAnchor(**base)


class TestUnresolvedAnchorId:
    def test_stable_and_slugified(self):
        aid = unresolved_anchor_id("Domain X", "Sys 1", "Table A")
        assert aid == "Domain X-sys-1-table-a-anchor"

    def test_deterministic(self):
        assert unresolved_anchor_id("d", "s", "t") == unresolved_anchor_id("d", "s", "t")


class TestUnresolvedAnchorRoundTrip:
    def test_to_dict_from_dict_round_trip(self):
        anchor = _anchor()
        data = anchor.to_dict()
        restored = UnresolvedAnchor.from_dict(data)
        assert restored is not None
        assert restored.id == anchor.id
        assert restored.domain == anchor.domain
        assert restored.system == anchor.system
        assert restored.table == anchor.table
        assert restored.likely_entity == anchor.likely_entity
        assert restored.candidate_uris == anchor.candidate_uris
        assert restored.evidence == anchor.evidence
        assert restored.status == "open"
        assert restored.schema_version == UNRESOLVED_ANCHOR_SCHEMA_VERSION

    def test_sparse_fields_omitted_when_empty(self):
        anchor = UnresolvedAnchor(
            id="x", domain="d", system="s", table="t",
        )
        data = anchor.to_dict()
        assert "likely_entity" not in data
        assert "candidate_uris" not in data
        assert "evidence" not in data
        assert "resolved_uri" not in data

    def test_resolved_record_round_trips_resolution_fields(self):
        anchor = _anchor(
            status="resolved", resolved_uri=CLASS_A_URI,
            resolved_by="a-human", resolved_at="2026-01-01T00:00:00Z",
        )
        restored = UnresolvedAnchor.from_dict(anchor.to_dict())
        assert restored.status == "resolved"
        assert restored.resolved_uri == CLASS_A_URI
        assert restored.resolved_by == "a-human"
        assert restored.resolved_at == "2026-01-01T00:00:00Z"

    def test_from_dict_rejects_missing_identity(self):
        assert UnresolvedAnchor.from_dict({"id": "x"}) is None
        diagnostics: list[str] = []
        assert UnresolvedAnchor.from_dict({}, diagnostics=diagnostics) is None
        assert diagnostics

    def test_from_dict_coerces_unknown_status(self):
        diagnostics: list[str] = []
        restored = UnresolvedAnchor.from_dict(
            {"id": "x", "domain": "d", "system": "s", "table": "t", "status": "bogus"},
            diagnostics=diagnostics,
        )
        assert restored is not None
        assert restored.status == "open"
        assert diagnostics

    def test_from_dict_tolerates_bad_schema_version(self):
        diagnostics: list[str] = []
        restored = UnresolvedAnchor.from_dict(
            {"id": "x", "domain": "d", "system": "s", "table": "t",
             "schema_version": "not-a-number"},
            diagnostics=diagnostics,
        )
        assert restored is not None
        assert restored.schema_version == UNRESOLVED_ANCHOR_SCHEMA_VERSION
        assert diagnostics

    def test_from_dict_forward_compat_newer_schema_version_loads_tolerantly(self):
        diagnostics: list[str] = []
        restored = UnresolvedAnchor.from_dict(
            {"id": "x", "domain": "d", "system": "s", "table": "t",
             "schema_version": UNRESOLVED_ANCHOR_SCHEMA_VERSION + 1},
            diagnostics=diagnostics,
        )
        assert restored is not None
        assert restored.schema_version == UNRESOLVED_ANCHOR_SCHEMA_VERSION + 1
        assert diagnostics


class TestLoadUnresolvedAnchorsDoc:
    def test_missing_file_returns_empty_no_diagnostics(self, tmp_path):
        anchors, diagnostics = load_unresolved_anchors_doc(tmp_path / "missing.yaml")
        assert anchors == []
        assert diagnostics == []

    def test_valid_document_loads(self, tmp_path):
        path = tmp_path / "domainx-unresolved-anchors.yaml"
        write_unresolved_anchors_doc(path, "domainx", [_anchor()])
        anchors, diagnostics = load_unresolved_anchors_doc(path)
        assert len(anchors) == 1
        assert anchors[0].id == "domainx-sys1-tablea-anchor"
        assert diagnostics == []

    def test_malformed_yaml_returns_diagnostic_not_raise(self, tmp_path):
        path = tmp_path / "broken.yaml"
        path.write_text("anchors: [unterminated", encoding="utf-8")
        anchors, diagnostics = load_unresolved_anchors_doc(path)
        assert anchors == []
        assert diagnostics

    def test_non_mapping_document_returns_diagnostic(self, tmp_path):
        path = tmp_path / "list.yaml"
        path.write_text("- just\n- a\n- list\n", encoding="utf-8")
        anchors, diagnostics = load_unresolved_anchors_doc(path)
        assert anchors == []
        assert diagnostics

    def test_legacy_document_missing_anchors_key_is_tolerated(self, tmp_path):
        path = tmp_path / "legacy.yaml"
        path.write_text("domain: domainx\n", encoding="utf-8")
        anchors, diagnostics = load_unresolved_anchors_doc(path)
        assert anchors == []
        assert diagnostics == []

    def test_non_mapping_anchor_entry_is_skipped_with_diagnostic(self, tmp_path):
        path = tmp_path / "partial.yaml"
        path.write_text(
            yaml.safe_dump({"anchors": ["not-a-mapping", _anchor().to_dict()]}),
            encoding="utf-8",
        )
        anchors, diagnostics = load_unresolved_anchors_doc(path)
        assert len(anchors) == 1
        assert diagnostics


class TestMergePreservingAnchorResolutions:
    def test_resolved_decision_survives_a_reproduced_ambiguity(self):
        existing = [_anchor(status="resolved", resolved_uri=CLASS_A_URI, resolved_by="human")]
        fresh = [_anchor()]  # same id, still ambiguous this run
        merged = merge_preserving_anchor_resolutions(fresh, existing)
        assert len(merged) == 1
        assert merged[0].status == "resolved"
        assert merged[0].resolved_uri == CLASS_A_URI

    def test_open_record_no_longer_reproduced_is_dropped(self):
        existing = [_anchor(id="stale-anchor", status="open")]
        merged = merge_preserving_anchor_resolutions([], existing)
        assert merged == []

    def test_resolved_record_no_longer_reproduced_is_kept_for_history(self):
        existing = [_anchor(id="stale-anchor", status="resolved", resolved_uri=CLASS_A_URI)]
        merged = merge_preserving_anchor_resolutions([], existing)
        assert len(merged) == 1
        assert merged[0].status == "resolved"

    def test_new_fresh_ambiguity_with_no_prior_record_is_kept(self):
        fresh = [_anchor()]
        merged = merge_preserving_anchor_resolutions(fresh, [])
        assert len(merged) == 1
        assert merged[0].status == "open"

    def test_merged_output_is_sorted_by_id(self):
        fresh = [_anchor(id="zzz-anchor"), _anchor(id="aaa-anchor")]
        merged = merge_preserving_anchor_resolutions(fresh, [])
        assert [a.id for a in merged] == ["aaa-anchor", "zzz-anchor"]


class TestWriteUnresolvedAnchorsDoc:
    def test_write_then_load_round_trip(self, tmp_path):
        path = unresolved_anchors_path(tmp_path, "domainx")
        assert path.name == "domainx-unresolved-anchors.yaml"
        write_unresolved_anchors_doc(path, "domainx", [_anchor()])
        assert path.is_file()
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert raw["schema_version"] == UNRESOLVED_ANCHOR_DOC_SCHEMA_VERSION
        assert raw["domain"] == "domainx"
        assert len(raw["anchors"]) == 1
        assert raw["anchors"][0]["reason"] == REASON_AMBIGUOUS_CONFIRMED_ALIAS

    def test_write_creates_parent_directories(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "domainx-unresolved-anchors.yaml"
        write_unresolved_anchors_doc(path, "domainx", [])
        assert path.is_file()

    def test_write_sorts_deterministically(self, tmp_path):
        path = tmp_path / "domainx-unresolved-anchors.yaml"
        write_unresolved_anchors_doc(
            path, "domainx", [_anchor(id="zzz-anchor"), _anchor(id="aaa-anchor")]
        )
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        ids = [a["id"] for a in raw["anchors"]]
        assert ids == ["aaa-anchor", "zzz-anchor"]
