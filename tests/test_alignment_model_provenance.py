# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The three surfaces that describe which AI model ran now agree (#545).

Not a correctness bug — the toolkit did the right thing. But on a real delivery run an
operator set `KAIROS_AI_ALIGNMENT_MODEL=gpt-5.5`, saw `check-ai-config` report `ok` with no
caveat, hit a temperature rejection, then found `model_used: gpt-5.4` in the artifact and
concluded the high-end model had silently fallen back to a weaker tier.

It had not. `--high-accuracy` selects `gpt-5.4` *on purpose* for this role — alignment is
deterministic closed-vocabulary matching, so a reasoning model adds latency and cost
without benefit, which `.env.example` and `HIGH_ACCURACY_MODEL` both say. The configured
`gpt-5.5` was the value at odds with the toolkit's own advice, and a parameter rejection
can never change the model. Reconstructing that took reading `ai_provider.py`.

Two fixes: say it at pre-flight, where DD-159 wants it caught, and record *why* in the
artifact rather than only the outcome.
"""

from __future__ import annotations

import pytest

from kairos_ontology.core.ai_preflight import (
    HIGH_ACCURACY_MODEL,
    AIRolePreflight,
    _is_reasoning_model,
    tier_advisory,
)
from kairos_ontology.core.ai_provider import ROLE_ALIGNMENT


class TestReasoningTierDetection:
    @pytest.mark.parametrize("model", ["gpt-5.5", "gpt-5.6", "gpt-6.0", "GPT-5.5"])
    def test_a_reasoning_model_is_recognised(self, model):
        assert _is_reasoning_model(model)

    @pytest.mark.parametrize("model", ["gpt-5.4", "gpt-5.4-mini", "gpt-4.1", "", "llama-3"])
    def test_a_non_reasoning_model_is_not(self, model):
        assert not _is_reasoning_model(model)

    def test_a_future_version_needs_no_edit_here(self):
        """Matched on the numeric part rather than a fixed list, so the next release does
        not silently stop being recognised."""
        assert _is_reasoning_model("gpt-9.9")


class TestTierAdvisory:
    def test_the_reported_misconfiguration_is_flagged(self):
        note = tier_advisory(ROLE_ALIGNMENT, "gpt-5.5")
        assert note
        assert HIGH_ACCURACY_MODEL in note
        # It must pre-empt the wrong conclusion, not merely state a preference.
        assert "not a downgrade" in note

    def test_the_preferred_tier_is_silent(self):
        assert tier_advisory(ROLE_ALIGNMENT, HIGH_ACCURACY_MODEL) == ""

    def test_an_unknown_role_is_silent(self):
        assert tier_advisory("judgment", "gpt-5.5") == ""

    def test_no_model_is_silent(self):
        assert tier_advisory(ROLE_ALIGNMENT, "") == ""


class TestPreflightResult:
    def test_the_advisory_reaches_the_json_output(self):
        result = AIRolePreflight(
            role=ROLE_ALIGNMENT, status="ok", model="gpt-5.5", advisory="wrong tier"
        )
        assert result.to_dict()["advisory"] == "wrong tier"

    def test_it_is_absent_when_empty(self):
        result = AIRolePreflight(role=ROLE_ALIGNMENT, status="ok", model=HIGH_ACCURACY_MODEL)
        assert "advisory" not in result.to_dict()

    def test_an_advisory_does_not_make_the_role_fail(self):
        """A tier mismatch is a judgement call, not a broken configuration: the run still
        works, and failing it would be wrong."""
        result = AIRolePreflight(
            role=ROLE_ALIGNMENT, status="ok", model="gpt-5.5", advisory="wrong tier"
        )
        assert result.is_ok
        assert not result.is_blocking
        assert not result.has_warnings


def test_the_preflight_tier_matches_the_one_high_accuracy_actually_selects():
    """`ai_preflight` cannot import `propose_alignment` (it would cycle through the
    provider layer), so the constant is duplicated. Pinned here instead."""
    from kairos_ontology.core.propose_alignment import HIGH_ACCURACY_MODEL as SELECTED

    assert HIGH_ACCURACY_MODEL == SELECTED


class TestArtifactProvenance:
    def test_the_artifact_records_why_not_only_what(self):
        from kairos_ontology.core.propose_alignment import DomainAlignment, alignment_to_dict

        alignment = DomainAlignment(
            domain="party",
            domain_uris=[],
            generated_at="2026-09-19T00:00:00Z",
            model_used="gpt-5.4",
            model_source="high-accuracy-tier",
        )
        document = alignment_to_dict(alignment)
        assert document["model_used"] == "gpt-5.4"
        assert document["model_source"] == "high-accuracy-tier"

    def test_an_unrecorded_source_is_omitted_rather_than_written_empty(self):
        """Library callers that do not set it keep the previous artifact shape."""
        from kairos_ontology.core.propose_alignment import DomainAlignment, alignment_to_dict

        alignment = DomainAlignment(
            domain="party",
            domain_uris=[],
            generated_at="2026-09-19T00:00:00Z",
            model_used="gpt-5.4",
        )
        assert "model_source" not in alignment_to_dict(alignment)
