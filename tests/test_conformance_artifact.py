# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unit tests for kairos_ontology.core.conformance_artifact (DD-090)."""

from __future__ import annotations

import pytest

from archetype_fixtures import build_refmodels_root
from kairos_ontology.core.archetype_loader import load_archetype, load_outcome_codes
from kairos_ontology.core.conformance_artifact import (
    ARTIFACT_RELPATH,
    ConformanceArtifactError,
    build_artifact,
    check_discovery_gate,
    compute_scorecard,
    has_unresolved_fleet_items,
    is_stale,
    open_questions,
    read_artifact,
    validate_artifact,
    write_artifact,
)


@pytest.fixture()
def refroot(tmp_path):
    return build_refmodels_root(tmp_path)


@pytest.fixture()
def archetype(refroot):
    return load_archetype(refroot, "test-carrier")


def _outcomes():
    return [
        {"uri": "https://example.org/ont/booking#Booking", "label": "Booking",
         "tier": "required", "outcome": "conforms"},
        {"uri": "https://example.org/ont/booking#CargoItem", "label": "Cargo Item",
         "tier": "required", "outcome": "conforms-with-rename", "rename_to": "CargoLine"},
        {"uri": "https://example.org/ont/party#BookingParty", "label": "Booking Party",
         "tier": "recommended", "outcome": "deviates", "deviation_reason": "bank acts as party"},
    ]


def test_compute_scorecard_groups_by_outcome_and_tier():
    sc = compute_scorecard(_outcomes())
    assert sc["total"] == 3
    assert sc["by_outcome"]["conforms"] == 1
    assert sc["by_tier"]["required"]["conforms"] == 1
    assert sc["by_tier"]["recommended"]["deviates"] == 1


def test_build_artifact_includes_modules_and_hashes(archetype):
    art = build_artifact(
        archetype=archetype, refmodels_version="1.11.0", outcomes=_outcomes(), mode="interactive"
    )
    assert art["ref_model_modules"]  # needed by design-domain pre-seed
    assert art["archetype"]["catalog_hash"] == archetype.catalog_hash
    assert art["archetype"]["concept_set_hash"] == archetype.concept_set_hash()
    assert art["scorecard"]["total"] == 3


def test_write_and_read_round_trip(tmp_path, archetype):
    art = build_artifact(
        archetype=archetype, refmodels_version="1.11.0", outcomes=_outcomes(), mode="interactive"
    )
    hub = tmp_path / "ontology-hub"
    out = write_artifact(hub, art)
    assert out == hub / ARTIFACT_RELPATH
    assert out.is_file()
    assert read_artifact(out)["archetype"]["id"] == "test-carrier"


def test_validate_accepts_valid_artifact(refroot, archetype):
    art = build_artifact(
        archetype=archetype, refmodels_version="1.11.0", outcomes=_outcomes(), mode="interactive"
    )
    assert validate_artifact(art, load_outcome_codes(refroot)) == []


def test_validate_rejects_unknown_outcome(refroot, archetype):
    outcomes = _outcomes()
    outcomes[0]["outcome"] = "totally-made-up"
    art = build_artifact(
        archetype=archetype, refmodels_version="1.11.0", outcomes=outcomes, mode="interactive"
    )
    errors = validate_artifact(art, load_outcome_codes(refroot))
    assert any("invalid outcome" in e for e in errors)


def test_validate_requires_rename_and_reason(refroot, archetype):
    outcomes = [
        {"uri": "u1", "tier": "required", "outcome": "conforms-with-rename"},
        {"uri": "u2", "tier": "required", "outcome": "deviates"},
    ]
    art = build_artifact(
        archetype=archetype, refmodels_version="1.11.0", outcomes=outcomes, mode="interactive"
    )
    errors = validate_artifact(art, load_outcome_codes(refroot))
    assert any("rename_to" in e for e in errors)
    assert any("deviation_reason" in e for e in errors)


def test_read_missing_artifact_raises(tmp_path):
    with pytest.raises(ConformanceArtifactError):
        read_artifact(tmp_path / "nope.yaml")


def test_is_stale_detects_concept_set_change(archetype):
    art = build_artifact(
        archetype=archetype, refmodels_version="1.11.0", outcomes=_outcomes(), mode="interactive"
    )
    assert is_stale(art, archetype) is False
    # Drop a concept → the recorded hash no longer matches.
    archetype.core_concepts.pop()
    assert is_stale(art, archetype) is True


# ---------------------------------------------------------------------------
# DD-148: mode, per-concept provenance fields, open_questions, check_discovery_gate
# DD-149: archetype.confirmed_by
# ---------------------------------------------------------------------------


def test_validate_rejects_invalid_mode(refroot, archetype):
    art = build_artifact(
        archetype=archetype, refmodels_version="1.11.0", outcomes=_outcomes(), mode="unattended"
    )
    errors = validate_artifact(art, load_outcome_codes(refroot))
    assert any("'mode' must be one of" in e for e in errors)


def test_validate_requires_human_confirmed_archetype(refroot, archetype):
    art = build_artifact(
        archetype=archetype,
        refmodels_version="1.11.0",
        outcomes=_outcomes(),
        mode="interactive",
        archetype_confirmed_by="ai",
    )
    errors = validate_artifact(art, load_outcome_codes(refroot))
    assert any("archetype.confirmed_by" in e for e in errors)


def test_validate_rejects_bad_confidence_and_decided_by(refroot, archetype):
    outcomes = _outcomes()
    outcomes[0]["confidence"] = 1.5
    outcomes[1]["decided_by"] = "robot"
    outcomes[2]["needs_confirmation"] = "yes"
    art = build_artifact(
        archetype=archetype, refmodels_version="1.11.0", outcomes=outcomes, mode="fleet"
    )
    errors = validate_artifact(art, load_outcome_codes(refroot))
    assert any("'confidence'" in e for e in errors)
    assert any("'decided_by'" in e for e in errors)
    assert any("'needs_confirmation'" in e for e in errors)


def test_open_questions_empty_for_interactive_mode():
    art = {"mode": "interactive", "core_concepts": [{"uri": "u1", "label": "One"}]}
    assert open_questions(art) == []
    assert has_unresolved_fleet_items(art) is False


def test_open_questions_flags_ai_decided_needs_confirmation():
    art = {
        "mode": "fleet",
        "core_concepts": [
            {"uri": "u1", "label": "One", "decided_by": "ai", "needs_confirmation": True,
             "confidence": 0.9},
        ],
    }
    questions = open_questions(art)
    assert len(questions) == 1
    assert questions[0]["reason"] == "needs_confirmation"
    assert has_unresolved_fleet_items(art) is True


def test_open_questions_flags_ai_decided_missing_confidence():
    art = {
        "mode": "fleet",
        "core_concepts": [
            {"uri": "u1", "label": "One", "decided_by": "ai"},
        ],
    }
    questions = open_questions(art)
    assert len(questions) == 1
    assert questions[0]["reason"] == "missing confidence"


def test_open_questions_ignores_user_decided_entries():
    art = {
        "mode": "fleet",
        "core_concepts": [
            {"uri": "u1", "label": "One", "decided_by": "user"},
            {"uri": "u2", "label": "Two", "decided_by": "ai", "confidence": 0.95,
             "needs_confirmation": False},
        ],
    }
    assert open_questions(art) == []


def test_check_discovery_gate_flags_when_neither_artifact_exists(tmp_path):
    errors = check_discovery_gate(tmp_path)
    assert len(errors) == 1
    assert "No business discovery evidence found" in errors[0]


def test_check_discovery_gate_passes_with_businessdiscovery_narrative_only(tmp_path):
    # DD-148: a businessdiscovery/ narrative (DD-048) satisfies the gate even without a
    # conformance artifact (DD-090) — the two are independent discovery outputs.
    narrative_dir = tmp_path / "businessdiscovery"
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "glossary.ttl").write_text("@prefix : <urn:x> .\n", encoding="utf-8")
    assert check_discovery_gate(tmp_path) == []


def test_check_discovery_gate_ignores_template_files_under_businessdiscovery(tmp_path):
    narrative_dir = tmp_path / "businessdiscovery"
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "glossary.ttl.template").write_text("", encoding="utf-8")
    errors = check_discovery_gate(tmp_path)
    assert len(errors) == 1
    assert "No business discovery evidence found" in errors[0]


def test_check_discovery_gate_passes_for_resolved_artifact(tmp_path, archetype):
    art = build_artifact(
        archetype=archetype, refmodels_version="1.11.0", outcomes=_outcomes(), mode="interactive"
    )
    write_artifact(tmp_path, art)
    assert check_discovery_gate(tmp_path) == []


def test_check_discovery_gate_flags_unresolved_fleet_items(tmp_path, archetype):
    outcomes = _outcomes()
    outcomes[0]["decided_by"] = "ai"
    outcomes[0]["needs_confirmation"] = True
    for other in outcomes[1:]:
        other["decided_by"] = "user"
    art = build_artifact(
        archetype=archetype, refmodels_version="1.11.0", outcomes=outcomes, mode="fleet"
    )
    write_artifact(tmp_path, art)
    errors = check_discovery_gate(tmp_path)
    assert len(errors) == 1
    assert "Unresolved fleet-mode discovery item" in errors[0]
