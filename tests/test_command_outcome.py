# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the shared exit-code/blocking-decision shape (issues #405, #408)."""

from kairos_ontology.core.command_outcome import (
    REASON_COLLISION,
    REASON_EMPTY,
    REASON_EXCEPTION,
    REASON_EXCLUDED,
    CommandOutcome,
    CommandOutcomeDecline,
    CommandOutcomeTarget,
)


class TestCommandOutcomeTarget:
    def test_total_failure_requires_attempts_and_failures(self):
        assert CommandOutcomeTarget("t", attempted=1, produced=0, failed=1).total_failure is True

    def test_empty_target_is_not_a_total_failure(self):
        """A target with nothing to attempt (an empty directory) is not broken —
        there was simply nothing to build."""
        assert CommandOutcomeTarget("t", attempted=0, produced=0, failed=0).total_failure is False

    def test_all_skipped_target_is_not_a_total_failure(self):
        """Every attempted source was legitimately excluded/empty (no failures at
        all) — still not a failure."""
        assert CommandOutcomeTarget("t", attempted=3, produced=0, failed=0).total_failure is False

    def test_partial_success_is_not_a_total_failure(self):
        assert CommandOutcomeTarget("t", attempted=3, produced=1, failed=2).total_failure is False


class TestCommandOutcomeIsBlocking:
    def test_no_findings_is_not_blocking(self):
        outcome = CommandOutcome(command="c", produced=("a",))
        assert outcome.is_blocking is False
        assert outcome.has_warnings is False

    def test_collision_blocks_even_with_other_successes(self):
        """DD-054 amendment: a single name collision must abort loudly even though
        other sources in the same run succeeded — a collision is a blocking-kind
        reason regardless of how much else the run produced."""
        outcome = CommandOutcome(
            command="c",
            produced=("a",),
            failed=(CommandOutcomeDecline("b", REASON_COLLISION, "collided with a"),),
        )
        assert outcome.is_blocking is True
        # DD-153 invariant, direction 1: is_blocking (⟹ a ❌ line / exit != 0 at the
        # CLI layer) is asserted true here; direction 2 (no ❌ unless blocking) is
        # covered by the non-blocking cases below.

    def test_total_failure_of_a_target_blocks_regardless_of_reason(self):
        """A target that attempted work and produced nothing is blocking even when
        every failure is a plain REASON_EXCEPTION (not a collision) — total failure
        of a target is caught by `total_failure`, independent of reason kind."""
        outcome = CommandOutcome(
            command="c",
            failed=(CommandOutcomeDecline("a", REASON_EXCEPTION, "parse error"),),
            targets=(CommandOutcomeTarget("only-target", attempted=1, produced=0, failed=1),),
        )
        assert outcome.is_blocking is True

    def test_exception_on_unowned_source_is_advisory_not_blocking(self):
        """The regression this suite guards against: `generate-inventory` globbing a
        vendored `ontology-reference-models/` checkout must not be made
        unconvergeable by a single upstream TTL the hub author cannot fix (DD-153,
        rejecting "make every partial failure blocking"). REASON_EXCEPTION is not in
        `_BLOCKING_REASONS`, so it is advisory: visible via `has_warnings`, but it
        does not block a plain (non-strict) run on its own."""
        outcome = CommandOutcome(
            command="c",
            produced=("a",),
            failed=(CommandOutcomeDecline("b", REASON_EXCEPTION, "cannot parse"),),
            targets=(CommandOutcomeTarget("t", attempted=2, produced=1, failed=1),),
        )
        assert outcome.is_blocking is False
        assert outcome.has_warnings is True

    def test_exception_on_unowned_source_escalates_under_strict(self):
        """The same outcome as above, but with `--strict`: a non-blocking-kind
        failure still counts toward the strict escalation gate, exactly like
        `advisory_findings` does."""
        outcome = CommandOutcome(
            command="c",
            produced=("a",),
            failed=(CommandOutcomeDecline("b", REASON_EXCEPTION, "cannot parse"),),
            targets=(CommandOutcomeTarget("t", attempted=2, produced=1, failed=1),),
            strict=True,
        )
        assert outcome.is_blocking is True

    def test_skipped_alone_is_not_blocking(self):
        """A source excluded by design (e.g. a pattern-library template stub) or
        empty of content is not a failure — declaring generate-inventory blocking
        on every such source would make it unconvergeable against a vendored
        checkout the caller does not own."""
        outcome = CommandOutcome(
            command="c",
            produced=("a",),
            skipped=(
                CommandOutcomeDecline("b", REASON_EXCLUDED, "pattern template"),
                CommandOutcomeDecline("c", REASON_EMPTY, "no classes"),
            ),
            targets=(CommandOutcomeTarget("t", attempted=3, produced=1, failed=0),),
        )
        assert outcome.is_blocking is False
        assert outcome.has_warnings is True

    def test_advisory_findings_only_block_under_strict(self):
        outcome = CommandOutcome(command="c", produced=("a",), advisory_findings=True)
        assert outcome.is_blocking is False
        assert outcome.has_warnings is True

        strict_outcome = CommandOutcome(
            command="c", produced=("a",), advisory_findings=True, strict=True
        )
        assert strict_outcome.is_blocking is True


class TestCommandOutcomeToDict:
    def test_to_dict_round_trips_shape(self):
        outcome = CommandOutcome(
            command="generate-inventory",
            produced=("a-inventory.yaml",),
            failed=(CommandOutcomeDecline("b.ttl", REASON_COLLISION, "detail"),),
            skipped=(CommandOutcomeDecline("c.ttl", REASON_EMPTY, "detail"),),
            targets=(CommandOutcomeTarget("reference-models", attempted=3, produced=1, failed=1),),
        )
        payload = outcome.to_dict()
        assert payload["schema_version"] == 1
        assert payload["command"] == "generate-inventory"
        assert payload["produced"] == ["a-inventory.yaml"]
        assert payload["failed"] == [
            {"item": "b.ttl", "reason": REASON_COLLISION, "detail": "detail"}
        ]
        assert payload["skipped"] == [{"item": "c.ttl", "reason": REASON_EMPTY, "detail": "detail"}]
        assert payload["targets"] == [
            {
                "name": "reference-models",
                "attempted": 3,
                "produced": 1,
                "failed": 1,
                "total_failure": False,
            }
        ]
        assert payload["is_blocking"] is True  # failed is non-empty
        assert payload["has_warnings"] is True  # skipped is non-empty
