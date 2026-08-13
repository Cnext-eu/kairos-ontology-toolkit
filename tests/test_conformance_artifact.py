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
        {
            "uri": "https://example.org/ont/booking#Booking",
            "label": "Booking",
            "tier": "required",
            "outcome": "conforms",
        },
        {
            "uri": "https://example.org/ont/booking#CargoItem",
            "label": "Cargo Item",
            "tier": "required",
            "outcome": "conforms-with-rename",
            "rename_to": "CargoLine",
        },
        {
            "uri": "https://example.org/ont/party#BookingParty",
            "label": "Booking Party",
            "tier": "recommended",
            "outcome": "deviates",
            "deviation_reason": "bank acts as party",
        },
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


def test_validate_rejects_absolute_posix_discovery_doc(refroot, archetype):
    art = build_artifact(
        archetype=archetype,
        refmodels_version="1.11.0",
        outcomes=_outcomes(),
        mode="interactive",
        discovery_doc="/home/dev/hub/ontology-reference-models/accelerator-packs/"
        "logistics/discovery/test-carrier.md",
    )
    errors = validate_artifact(art, load_outcome_codes(refroot))
    assert any("discovery_doc" in e for e in errors)


def test_validate_rejects_windows_absolute_discovery_doc(refroot, archetype):
    art = build_artifact(
        archetype=archetype,
        refmodels_version="1.11.0",
        outcomes=_outcomes(),
        mode="interactive",
        discovery_doc=r"C:\refmodels\accelerator-packs\logistics\discovery\test-carrier.md",
    )
    errors = validate_artifact(art, load_outcome_codes(refroot))
    assert any("discovery_doc" in e for e in errors)


def test_validate_accepts_relative_discovery_doc(refroot, archetype):
    art = build_artifact(
        archetype=archetype,
        refmodels_version="1.11.0",
        outcomes=_outcomes(),
        mode="interactive",
        discovery_doc="accelerator-packs/logistics/discovery/test-carrier.md",
    )
    errors = validate_artifact(art, load_outcome_codes(refroot))
    assert not any("discovery_doc" in e for e in errors)


def test_validate_accepts_null_discovery_doc(refroot, archetype):
    art = build_artifact(
        archetype=archetype,
        refmodels_version="1.11.0",
        outcomes=_outcomes(),
        mode="interactive",
        discovery_doc=None,
    )
    errors = validate_artifact(art, load_outcome_codes(refroot))
    assert not any("discovery_doc" in e for e in errors)


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
            {
                "uri": "u1",
                "label": "One",
                "decided_by": "ai",
                "needs_confirmation": True,
                "confidence": 0.9,
            },
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
            {
                "uri": "u2",
                "label": "Two",
                "decided_by": "ai",
                "confidence": 0.95,
                "needs_confirmation": False,
            },
        ],
    }
    assert open_questions(art) == []


# ---------------------------------------------------------------------------
# Issue #307: the DD-148 gate must be keyed on per-concept evidence, never on the
# self-declared, unverifiable 'mode' field. A concept with decided_by: ai and an
# unresolved judgment must be caught regardless of whether the artifact claims
# mode: interactive or mode: fleet.
# ---------------------------------------------------------------------------


def test_open_questions_flags_ai_decided_needs_confirmation_in_interactive_mode():
    """Regression for #307: 'mode: interactive' must not disable the gate.

    Before the fix, ``open_questions`` short-circuited to ``[]`` whenever
    ``mode != "fleet"``, so an artifact could declare ``mode: interactive`` while every
    concept was actually ``decided_by: ai`` with ``needs_confirmation: true`` and pass
    silently. That self-declared 'mode' field lives inside the very artifact being
    checked and is unverifiable, so it must never be the gate condition.
    """
    art = {
        "mode": "interactive",
        "core_concepts": [
            {
                "uri": "u1",
                "label": "One",
                "decided_by": "ai",
                "needs_confirmation": True,
                "confidence": 0.9,
            },
        ],
    }
    questions = open_questions(art)
    assert len(questions) == 1
    assert questions[0]["reason"] == "needs_confirmation"
    assert has_unresolved_fleet_items(art) is True


def test_open_questions_flags_ai_decided_needs_confirmation_in_fleet_mode_no_regression():
    """Same shape as the interactive case above, still flagged under 'mode: fleet'."""
    art = {
        "mode": "fleet",
        "core_concepts": [
            {
                "uri": "u1",
                "label": "One",
                "decided_by": "ai",
                "needs_confirmation": True,
                "confidence": 0.9,
            },
        ],
    }
    questions = open_questions(art)
    assert len(questions) == 1
    assert questions[0]["reason"] == "needs_confirmation"


@pytest.mark.parametrize("mode", ["interactive", "fleet"])
def test_open_questions_empty_when_ai_decisions_are_properly_confirmed(mode):
    """A properly confirmed AI decision produces no open questions, in either mode."""
    art = {
        "mode": mode,
        "core_concepts": [
            {
                "uri": "u1",
                "label": "One",
                "decided_by": "ai",
                "needs_confirmation": False,
                "confidence": 0.95,
            },
            {
                "uri": "u2",
                "label": "Two",
                "decided_by": "ai",
                "needs_confirmation": False,
                "confidence": 0.5,
            },
        ],
    }
    assert open_questions(art) == []
    assert has_unresolved_fleet_items(art) is False


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


def test_check_discovery_gate_ignores_scaffold_dash_template_ttl(tmp_path):
    # Issue #288: init's actual scaffold uses `glossary-template.ttl` (a `-template.ttl`
    # suffix), not the legacy `*.template` convention exercised above. A hub whose only
    # businessdiscovery/ file is this scaffold template has zero authored evidence and must
    # still fail the hard gate, not silently pass compile/validate.
    narrative_dir = tmp_path / "businessdiscovery"
    narrative_dir.mkdir(parents=True)
    (narrative_dir / "glossary-template.ttl").write_text("", encoding="utf-8")
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
    assert "Unresolved discovery item" in errors[0]


def test_check_discovery_gate_flags_unresolved_items_in_interactive_mode_too(tmp_path, archetype):
    """Regression for #307: the hard gate must not trust 'mode: interactive' either.

    Byte-for-byte the same per-concept judgment shape as
    ``test_check_discovery_gate_flags_unresolved_fleet_items`` above — only ``mode`` differs
    — and it must still fail. Before the fix, writing ``mode: interactive`` disabled this
    entire hard gate even though every concept was AI-decided and unconfirmed.
    """
    outcomes = _outcomes()
    outcomes[0]["decided_by"] = "ai"
    outcomes[0]["needs_confirmation"] = True
    for other in outcomes[1:]:
        other["decided_by"] = "user"
    art = build_artifact(
        archetype=archetype, refmodels_version="1.11.0", outcomes=outcomes, mode="interactive"
    )
    write_artifact(tmp_path, art)
    errors = check_discovery_gate(tmp_path)
    assert len(errors) == 1
    assert "Unresolved discovery item" in errors[0]


# --- Tier-enum ownership (#276 Q4/Q5) -------------------------------------------------

#: A tier reference-models has proposed but not yet published. The point of these tests is that
#: the toolkit must not need a release to handle it.
_FUTURE_TIER = "not_applicable"


def _outcomes_with_future_tier():
    outcomes = _outcomes()
    outcomes.append(
        {
            "uri": "https://example.org/ont/booking#OutOfScopeThing",
            "label": "Out Of Scope Thing",
            "tier": _FUTURE_TIER,
            "outcome": "not-applicable",
        }
    )
    return outcomes


def test_scorecard_never_drops_a_concept_carrying_an_unseeded_tier():
    """``total`` must equal the sum of ``by_tier`` even for a tier we predate.

    Regression: ``compute_scorecard`` used to seed buckets from ``VALID_TIERS`` and skip any
    outcome whose tier was not in it, so the concept was counted in ``total`` but silently
    omitted from every bucket — a scorecard that under-reports with no warning.
    """
    sc = compute_scorecard(_outcomes_with_future_tier())
    assert sc["total"] == 4
    counted = sum(sum(counts.values()) for counts in sc["by_tier"].values())
    assert counted == sc["total"]
    assert sc["by_tier"][_FUTURE_TIER]["not-applicable"] == 1


def test_scorecard_keeps_canonical_tiers_even_when_empty():
    """Historical shape is preserved: the three canonical buckets always appear."""
    sc = compute_scorecard(
        [
            {
                "uri": "https://example.org/ont/x#A",
                "label": "A",
                "tier": "required",
                "outcome": "conforms",
            }
        ]
    )
    assert set(sc["by_tier"]) == {"required", "recommended", "optional"}


def test_validate_accepts_a_tier_published_by_reference_models(refroot, archetype):
    """A tier resolved from the checkout is accepted without a toolkit release."""
    art = build_artifact(
        archetype=archetype,
        refmodels_version="1.11.0",
        outcomes=_outcomes_with_future_tier(),
        mode="interactive",
        valid_tiers=("required", "recommended", "optional", _FUTURE_TIER),
    )
    errors = validate_artifact(
        art,
        load_outcome_codes(refroot),
        ("required", "recommended", "optional", _FUTURE_TIER),
    )
    assert errors == []


def test_validate_rejects_an_unpublished_tier_on_the_offline_fallback(refroot, archetype):
    """Without a resolvable enum the fallback still refuses an unknown tier."""
    art = build_artifact(
        archetype=archetype,
        refmodels_version="1.11.0",
        outcomes=_outcomes_with_future_tier(),
        mode="interactive",
    )
    errors = validate_artifact(art, load_outcome_codes(refroot))
    assert any(_FUTURE_TIER in e and "invalid or missing tier" in e for e in errors)


def test_scorecard_equality_survives_a_tier_seed_mismatch(refroot, archetype):
    """Validation must not depend on which checkout happened to be resolvable.

    Regression: an artifact built where the tier enum resolved to four tiers, then validated
    where it fell back to three (no ``KAIROS_REFMODELS_ROOT``), differed only in an *empty*
    bucket — but strict equality reported "'scorecard' contradicts 'core_concepts'; regenerate
    it", sending the user to fix something that was not wrong.
    """
    art = build_artifact(
        archetype=archetype,
        refmodels_version="1.11.0",
        outcomes=_outcomes(),  # no concept actually uses the extra tier
        mode="interactive",
        valid_tiers=("required", "recommended", "optional", _FUTURE_TIER),
    )
    assert art["scorecard"]["by_tier"][_FUTURE_TIER] == {}
    # Validated against the narrower fallback enum — must still be valid.
    assert validate_artifact(art, load_outcome_codes(refroot)) == []


def test_scorecard_equality_still_catches_a_genuinely_wrong_scorecard(refroot, archetype):
    """Normalising empty buckets must not blunt the real consistency check."""
    art = build_artifact(
        archetype=archetype, refmodels_version="1.11.0", outcomes=_outcomes(), mode="interactive"
    )
    art["scorecard"]["by_tier"]["required"]["conforms"] = 99
    errors = validate_artifact(art, load_outcome_codes(refroot))
    assert any("contradicts 'core_concepts'" in e for e in errors)


# ---------------------------------------------------------------------------
# Issue #308: `validate` must actually compare the artifact against its archetype
# (hole 1: identity/coverage, hole 2: staleness) and tighten conditional-field and
# business_area validation (holes 4 and 5). Hole 3 (topology_confirmations/
# cardinality_answers shape) is explicitly out of scope — see validate_artifact's
# docstring.
# ---------------------------------------------------------------------------


def _full_outcomes():
    """``_outcomes()`` plus the archetype's fourth concept (``GhostConcept``), for full
    coverage of the ``test-carrier`` fixture archetype's catalog."""
    outcomes = _outcomes()
    outcomes.append(
        {
            "uri": "https://example.org/ont/booking#GhostConcept",
            "label": "Ghost",
            "tier": "optional",
            "outcome": "not-applicable",
        }
    )
    return outcomes


def test_validate_without_archetype_skips_identity_coverage_and_staleness_checks(
    refroot, archetype
):
    """Backward compatibility: *archetype* is opt-in.

    ``_outcomes()`` only covers 3 of the archetype's 4 concepts, yet this must still
    validate clean when no archetype is supplied — callers that cannot resolve a
    reference-models checkout must not be forced to pass one just to get shape/enum
    validation.
    """
    art = build_artifact(
        archetype=archetype, refmodels_version="1.11.0", outcomes=_outcomes(), mode="interactive"
    )
    assert validate_artifact(art, load_outcome_codes(refroot)) == []


def test_validate_hole1_rejects_incomplete_concept_coverage(refroot, archetype):
    """Regression for #308 hole 1: an artifact missing an archetype concept must fail.

    Before the fix, ``validate`` never loaded the archetype at all, so an artifact
    covering only a subset of its declared archetype's concepts validated clean.
    """
    art = build_artifact(
        archetype=archetype, refmodels_version="1.11.0", outcomes=_outcomes(), mode="interactive"
    )
    errors = validate_artifact(art, load_outcome_codes(refroot), archetype=archetype)
    assert any("missing archetype concept" in e and "GhostConcept" in e for e in errors)


def test_validate_hole1_accepts_full_concept_coverage(refroot, archetype):
    art = build_artifact(
        archetype=archetype,
        refmodels_version="1.11.0",
        outcomes=_full_outcomes(),
        mode="interactive",
    )
    assert validate_artifact(art, load_outcome_codes(refroot), archetype=archetype) == []


def test_validate_hole1_rejects_concept_not_in_the_archetypes_catalog(refroot, archetype):
    """A concept URI that isn't in the resolved archetype's catalog at all.

    Simulates 'archetype.id points at a different archetype than the one actually used'
    (#308): the recorded concepts don't genuinely belong to the archetype being validated
    against, which a mere well-formedness check (valid HTTP URI, non-empty label) would
    never catch.
    """
    outcomes = _full_outcomes()
    outcomes.append(
        {
            "uri": "https://example.org/ont/other#NotInCatalog",
            "label": "Not In Catalog",
            "tier": "required",
            "outcome": "conforms",
        }
    )
    art = build_artifact(
        archetype=archetype, refmodels_version="1.11.0", outcomes=outcomes, mode="interactive"
    )
    errors = validate_artifact(art, load_outcome_codes(refroot), archetype=archetype)
    assert any("is not a core concept of archetype" in e for e in errors)


def test_validate_hole1_rejects_tier_drift_from_the_catalog(refroot, archetype):
    outcomes = _full_outcomes()
    outcomes[0]["tier"] = "optional"  # Booking is 'required' in the test-carrier catalog
    art = build_artifact(
        archetype=archetype, refmodels_version="1.11.0", outcomes=outcomes, mode="interactive"
    )
    errors = validate_artifact(art, load_outcome_codes(refroot), archetype=archetype)
    assert any("does not match the catalog tier" in e for e in errors)


def test_validate_hole2_rejects_stale_concept_set_hash(refroot, archetype):
    """Regression for #308 hole 2: validate must call the existing is_stale(), not skip it."""
    art = build_artifact(
        archetype=archetype,
        refmodels_version="1.11.0",
        outcomes=_full_outcomes(),
        mode="interactive",
    )
    assert validate_artifact(art, load_outcome_codes(refroot), archetype=archetype) == []

    art["archetype"]["concept_set_hash"] = "deadbeef"
    assert is_stale(art, archetype) is True  # confirms this reuses the existing is_stale()
    errors = validate_artifact(art, load_outcome_codes(refroot), archetype=archetype)
    assert any("stale" in e.lower() for e in errors)


@pytest.mark.parametrize("outcome_code", ["partial", "conforms", "not-applicable"])
def test_validate_hole4_rejects_rename_to_on_a_non_rename_outcome(refroot, archetype, outcome_code):
    """Regression for #308 hole 4: the converse of the rename_to requirement was unchecked.

    `design-domain` reads `rename_to` to pre-seed local names, so a stray rename on a
    non-rename outcome would silently change downstream modelling if left unvalidated.
    """
    outcomes = [
        {
            "uri": "https://example.org/ont/booking#Booking",
            "label": "Booking",
            "tier": "required",
            "outcome": outcome_code,
            "rename_to": "ShouldNotBeHere",
        },
    ]
    art = build_artifact(
        archetype=archetype, refmodels_version="1.11.0", outcomes=outcomes, mode="interactive"
    )
    errors = validate_artifact(art, load_outcome_codes(refroot))
    assert any("'rename_to' is only valid on 'conforms-with-rename'" in e for e in errors)


@pytest.mark.parametrize("outcome_code", ["partial", "conforms", "not-applicable"])
def test_validate_hole4_rejects_deviation_reason_on_a_non_deviates_outcome(
    refroot, archetype, outcome_code
):
    outcomes = [
        {
            "uri": "https://example.org/ont/booking#Booking",
            "label": "Booking",
            "tier": "required",
            "outcome": outcome_code,
            "deviation_reason": "should not be here",
        },
    ]
    art = build_artifact(
        archetype=archetype, refmodels_version="1.11.0", outcomes=outcomes, mode="interactive"
    )
    errors = validate_artifact(art, load_outcome_codes(refroot))
    assert any("'deviation_reason' is only valid on 'deviates'" in e for e in errors)


def test_validate_hole5_rejects_non_string_business_area(refroot, archetype):
    """Regression for #308 hole 5: business_area had no type validation at all."""
    outcomes = _outcomes()
    outcomes[0]["business_area"] = {"not": "a string"}
    art = build_artifact(
        archetype=archetype, refmodels_version="1.11.0", outcomes=outcomes, mode="interactive"
    )
    errors = validate_artifact(art, load_outcome_codes(refroot))
    assert any("'business_area' must be a" in e for e in errors)


def test_validate_hole5_accepts_string_business_area(refroot, archetype):
    outcomes = _outcomes()
    outcomes[0]["business_area"] = "Commercial"
    art = build_artifact(
        archetype=archetype, refmodels_version="1.11.0", outcomes=outcomes, mode="interactive"
    )
    assert validate_artifact(art, load_outcome_codes(refroot)) == []
