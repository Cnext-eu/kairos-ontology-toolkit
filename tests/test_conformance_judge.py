# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Provider-backed archetype-conformance judgment (DD-167)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from kairos_ontology.core.conformance_judge import (
    NEEDS_CONFIRMATION_BELOW,
    VALID_OUTCOMES,
    build_batch_prompt,
    judge_concepts,
    normalize_judgment,
    parse_batch_response,
)

URI = "https://www.kairosflow.ai/ont/mmt/party#TransportParty"
CATALOG = {"uri": URI, "label": "Transport Party", "tier": "required"}


def _evidence(
    text: str = "2 source table(s) aligned to this concept: qargo.companies",
    kind: str = "alignment",
):
    stub = MagicMock()
    stub.describe.return_value = text
    stub.kind = kind
    return stub


# ---------------------------------------------------------------------------
# Guardrails on a single judgment
# ---------------------------------------------------------------------------


def test_confident_conforms_with_evidence_is_kept_as_is() -> None:
    result = normalize_judgment(
        {"outcome": "conforms", "confidence": 0.92, "rationale": "companies table carries it"},
        CATALOG,
        has_evidence=True,
    )
    assert result.outcome == "conforms"
    assert result.needs_confirmation is False
    assert result.decided_by == "ai"


def test_conforms_without_source_evidence_is_downgraded() -> None:
    """The failure mode that matters: certifying a concept the hub never models.

    A real run scored a domain "6 conforms / 0 deviates" while its ontology contained
    none of the three classes it certified.
    """
    result = normalize_judgment(
        {"outcome": "conforms", "confidence": 0.95, "rationale": "standard for carriers"},
        CATALOG,
        has_evidence=False,
    )
    assert result.outcome == "partial"
    assert result.needs_confirmation is True
    assert "no source evidence" in result.rationale


def test_non_assertive_outcomes_survive_without_evidence() -> None:
    """Only conforms/conforms-with-rename claim the data shows it."""
    for outcome in ("partial", "deviates", "not-applicable"):
        result = normalize_judgment(
            {"outcome": outcome, "confidence": 0.9, "rationale": "r", "deviation_reason": "x"},
            CATALOG,
            has_evidence=False,
        )
        assert result.outcome == outcome


def test_unknown_outcome_is_never_trusted() -> None:
    result = normalize_judgment(
        {"outcome": "mostly-conforms", "confidence": 0.99, "rationale": "r"},
        CATALOG,
        has_evidence=True,
    )
    assert result.outcome == "partial"
    assert result.needs_confirmation is True
    assert "unrecognised outcome" in result.rationale


@pytest.mark.parametrize("confidence", [None, 0.0, NEEDS_CONFIRMATION_BELOW - 0.01])
def test_low_or_missing_confidence_escalates(confidence) -> None:
    result = normalize_judgment(
        {"outcome": "partial", "confidence": confidence, "rationale": "r"},
        CATALOG,
        has_evidence=True,
    )
    assert result.needs_confirmation is True


def test_confidence_is_clamped_not_rejected() -> None:
    result = normalize_judgment(
        {"outcome": "partial", "confidence": 42, "rationale": "r"}, CATALOG, has_evidence=True
    )
    assert result.confidence == 1.0


def test_rename_without_a_target_is_flagged() -> None:
    result = normalize_judgment(
        {"outcome": "conforms-with-rename", "confidence": 0.9, "rationale": "r"},
        CATALOG,
        has_evidence=True,
    )
    assert result.needs_confirmation is True
    assert "rename target missing" in result.rationale


def test_uri_label_and_tier_come_from_the_catalog_not_the_model() -> None:
    """The model is told never to invent a URI; this makes that structural."""
    result = normalize_judgment(
        {"uri": "https://evil.example/#Invented", "outcome": "partial", "confidence": 0.9},
        CATALOG,
        has_evidence=True,
    )
    assert result.uri == URI
    assert result.label == "Transport Party"
    assert result.tier == "required"


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def test_parse_tolerates_a_fenced_code_block() -> None:
    body = json.dumps({"judgments": [{"uri": URI, "outcome": "conforms"}]})
    assert parse_batch_response(f"```json\n{body}\n```")[0]["uri"] == URI


@pytest.mark.parametrize("text", ["not json at all", "{}", '{"judgments": "nope"}'])
def test_unparseable_responses_raise_rather_than_return_nothing(text: str) -> None:
    with pytest.raises(ValueError):
        parse_batch_response(text)


def test_prompt_names_missing_evidence_explicitly() -> None:
    prompt = build_batch_prompt([{"uri": URI, "label": "L", "tier": "required", "evidence": ""}])
    assert "NONE FOUND" in prompt
    assert URI in prompt


# ---------------------------------------------------------------------------
# Batching and failure handling
# ---------------------------------------------------------------------------


def _client_returning(payload: dict) -> MagicMock:
    client = MagicMock()
    client.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content=json.dumps(payload)))
    ]
    return client


def test_every_concept_is_judged_and_batching_reduces_calls() -> None:
    catalog = [{"uri": f"{URI}{i}", "label": f"C{i}", "tier": "required"} for i in range(25)]
    client = _client_returning(
        {"judgments": [{"uri": c["uri"], "outcome": "partial", "confidence": 0.8} for c in catalog]}
    )

    report = judge_concepts(
        catalog=catalog, evidence={}, archetype_id="a", client=client, model="m", batch_size=12
    )

    assert len(report.judgments) == 25
    assert report.calls_made == 3  # 12 + 12 + 1, not 25


def test_a_failed_batch_is_recorded_not_dropped_and_not_guessed() -> None:
    """A missing concept fails validate loudly; a fabricated one passes silently."""
    catalog = [{"uri": f"{URI}{i}", "label": "C", "tier": "required"} for i in range(3)]
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("provider exploded")

    report = judge_concepts(
        catalog=catalog, evidence={}, archetype_id="a", client=client, model="m"
    )

    assert len(report.judgments) == 3
    assert all(j.needs_confirmation for j in report.judgments)
    assert all("Not judged" in j.rationale for j in report.judgments)
    assert report.notices


def test_a_concept_the_model_omits_is_recorded_as_unjudged() -> None:
    catalog = [{"uri": f"{URI}{i}", "label": "C", "tier": "required"} for i in range(2)]
    client = _client_returning(
        {"judgments": [{"uri": f"{URI}0", "outcome": "conforms", "confidence": 0.9}]}
    )

    report = judge_concepts(
        catalog=catalog, evidence={}, archetype_id="a", client=client, model="m"
    )

    omitted = [j for j in report.judgments if j.uri == f"{URI}1"]
    assert omitted and omitted[0].needs_confirmation
    assert "no judgment" in omitted[0].rationale


def test_domain_level_affinity_alone_cannot_certify_a_concept() -> None:
    """The regression this guard exists for.

    On first run the model marked TransportPartyRoleAssignment 'conforms' at 0.91
    because "16 party-related tables ... is consistent with assigning roles". Tables in
    the party domain are not evidence that a role-assignment entity exists — that
    business models roles as boolean flags.
    """
    result = normalize_judgment(
        {"outcome": "conforms", "confidence": 0.91, "rationale": "16 party tables"},
        CATALOG,
        has_evidence=True,
        concept_level_evidence=False,
    )
    assert result.outcome == "partial"
    assert result.needs_confirmation is True
    assert "domain-level affinity" in result.rationale


def test_pattern_caution_escalates_conforms_without_overriding_it() -> None:
    """A grain collision governs how a concept is modelled, not whether it exists.

    Downgrading mmt:TransportParty to 'partial' would be wrong — the business plainly
    has transport parties. Requiring a human to look is not.
    """
    result = normalize_judgment(
        {"outcome": "conforms", "confidence": 0.95, "rationale": "companies table"},
        CATALOG,
        has_evidence=True,
        concept_level_evidence=True,
        pattern_caution="qualified-role-assignment: not the durable identity",
    )
    assert result.outcome == "conforms"
    assert result.needs_confirmation is True
    assert "pattern-library caution" in result.rationale


def test_pattern_caution_does_not_disturb_a_non_assertive_outcome() -> None:
    result = normalize_judgment(
        {"outcome": "partial", "confidence": 0.9, "rationale": "r"},
        CATALOG,
        has_evidence=True,
        pattern_caution="some caution",
    )
    assert result.outcome == "partial"
    assert "pattern-library caution" not in result.rationale


def test_alignment_evidence_is_treated_as_concept_level_automatically() -> None:
    catalog = [dict(CATALOG)]
    client = _client_returning(
        {"judgments": [{"uri": URI, "outcome": "conforms", "confidence": 0.9, "rationale": "r"}]}
    )
    report = judge_concepts(
        catalog=catalog,
        evidence={URI: _evidence(kind="alignment")},
        archetype_id="a",
        client=client,
        model="m",
    )
    assert report.judgments[0].outcome == "conforms"


def test_bi_demand_and_caution_reach_the_prompt() -> None:
    catalog = [dict(CATALOG)]
    client = _client_returning(
        {"judgments": [{"uri": URI, "outcome": "partial", "confidence": 0.9}]}
    )
    judge_concepts(
        catalog=catalog,
        evidence={URI: _evidence(kind="affinity")},
        archetype_id="a",
        client=client,
        model="m",
        cautions={URI: "qualified-role-assignment: role-bearing parent"},
        bi_terms={"transportparty"},
    )
    sent = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "pattern_library_caution" in sent
    assert "downstream_bi_demand" in sent
    assert "DOMAIN-LEVEL ONLY" in sent


def test_evidence_reaches_the_prompt_and_permits_conforms() -> None:
    catalog = [dict(CATALOG)]
    client = _client_returning(
        {"judgments": [{"uri": URI, "outcome": "conforms", "confidence": 0.9, "rationale": "r"}]}
    )

    report = judge_concepts(
        catalog=catalog,
        evidence={URI: _evidence()},
        archetype_id="a",
        client=client,
        model="m",
    )

    sent = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "qargo.companies" in sent
    assert report.judgments[0].outcome == "conforms"


# ---------------------------------------------------------------------------
# Output document
# ---------------------------------------------------------------------------


def test_output_never_confirms_the_archetype() -> None:
    """DD-149 is a human gate; judging concepts must not satisfy it as a side effect."""
    client = _client_returning(
        {"judgments": [{"uri": URI, "outcome": "partial", "confidence": 0.9}]}
    )
    report = judge_concepts(
        catalog=[dict(CATALOG)], evidence={}, archetype_id="unit-load-carrier",
        client=client, model="m",
    )

    document = report.to_judgments_document()
    assert document["archetype_confirmed_by"] == "<CONFIRM_HUMAN_ARCHETYPE:unit-load-carrier>"
    assert all(entry["decided_by"] == "ai" for entry in document["core_concepts"])


def test_valid_outcomes_match_the_published_vocabulary() -> None:
    assert VALID_OUTCOMES == {
        "conforms",
        "conforms-with-rename",
        "partial",
        "deviates",
        "not-applicable",
    }
