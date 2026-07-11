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
    compute_scorecard,
    is_stale,
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
    art = build_artifact(archetype=archetype, refmodels_version="1.11.0", outcomes=_outcomes())
    assert art["ref_model_modules"]  # needed by design-domain pre-seed
    assert art["archetype"]["catalog_hash"] == archetype.catalog_hash
    assert art["archetype"]["concept_set_hash"] == archetype.concept_set_hash()
    assert art["scorecard"]["total"] == 3


def test_write_and_read_round_trip(tmp_path, archetype):
    art = build_artifact(archetype=archetype, refmodels_version="1.11.0", outcomes=_outcomes())
    hub = tmp_path / "ontology-hub"
    out = write_artifact(hub, art)
    assert out == hub / ARTIFACT_RELPATH
    assert out.is_file()
    assert read_artifact(out)["archetype"]["id"] == "test-carrier"


def test_validate_accepts_valid_artifact(refroot, archetype):
    art = build_artifact(archetype=archetype, refmodels_version="1.11.0", outcomes=_outcomes())
    assert validate_artifact(art, load_outcome_codes(refroot)) == []


def test_validate_rejects_unknown_outcome(refroot, archetype):
    outcomes = _outcomes()
    outcomes[0]["outcome"] = "totally-made-up"
    art = build_artifact(archetype=archetype, refmodels_version="1.11.0", outcomes=outcomes)
    errors = validate_artifact(art, load_outcome_codes(refroot))
    assert any("invalid outcome" in e for e in errors)


def test_validate_requires_rename_and_reason(refroot, archetype):
    outcomes = [
        {"uri": "u1", "tier": "required", "outcome": "conforms-with-rename"},
        {"uri": "u2", "tier": "required", "outcome": "deviates"},
    ]
    art = build_artifact(archetype=archetype, refmodels_version="1.11.0", outcomes=outcomes)
    errors = validate_artifact(art, load_outcome_codes(refroot))
    assert any("rename_to" in e for e in errors)
    assert any("deviation_reason" in e for e in errors)


def test_read_missing_artifact_raises(tmp_path):
    with pytest.raises(ConformanceArtifactError):
        read_artifact(tmp_path / "nope.yaml")


def test_is_stale_detects_concept_set_change(archetype):
    art = build_artifact(archetype=archetype, refmodels_version="1.11.0", outcomes=_outcomes())
    assert is_stale(art, archetype) is False
    # Drop a concept → the recorded hash no longer matches.
    archetype.core_concepts.pop()
    assert is_stale(art, archetype) is True
