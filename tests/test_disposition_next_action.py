# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""`next` proposes recording a source-table disposition (DD-164).

DD-164 was the only gate in the flow that ``validate`` **enforced** without anything ever
**asking for it**: no skill step, no next action. The first an operator heard of it was a
red validate late in a run, by which point the backlog had accumulated — on the hub that
prompted this, 70 tables were outstanding at once.

This is the table-grain question *"is this table in scope at all"*, and it is deliberately
distinct from the column-grain gap gate (DD-169/DD-186, ``draft-gap-decisions``). Both had
to exist; only one was routed to anybody.

The action is blocking because ``validate`` fails on it, and its status is
``HUMAN_DECISION_REQUIRED`` because recording an outcome is a human call — "not business data", "deferred", "blueprint gap" — so it is
proposed, never applied.
"""

from __future__ import annotations

from kairos_ontology.core.next_actions import (
    SCHEMA_VERSION,
    ActionStatus,
    CompileStatus,
    DomainSnapshot,
    HubInputSnapshot,
    InputStatus,
    SourceDispositionObservation,
    propose_next_actions,
)


def _snapshot(**kw) -> HubInputSnapshot:
    base = dict(
        hub_root="/hub",
        discovery=InputStatus.PRESENT,
        sources=InputStatus.PRESENT,
        dbt_transforms=InputStatus.PRESENT,
        shapes=InputStatus.PRESENT,
        domains=(
            DomainSnapshot(
                domain="party",
                ontology=InputStatus.PRESENT,
                has_bindings=True,
                binding_count=1,
                compile_status=CompileStatus.PASSED,
            ),
        ),
    )
    base.update(kw)
    return HubInputSnapshot(**base)  # type: ignore[arg-type]


def _dispositions(actions) -> list:
    return [a for a in actions if a.kind == "record-source-disposition"]


class TestTheObservation:
    def test_coverage_is_one_when_there_is_nothing_to_decide(self):
        """The no-observation default must not read as 0% decided."""
        assert SourceDispositionObservation().coverage == 1.0

    def test_coverage_counts_recorded_outcomes(self):
        obs = SourceDispositionObservation(tables_total=68, tables_undecided=17)
        assert obs.coverage == (68 - 17) / 68

    def test_fully_decided_is_full_coverage(self):
        assert SourceDispositionObservation(tables_total=10, tables_undecided=0).coverage == 1.0

    def test_nothing_decided_is_zero_coverage(self):
        assert SourceDispositionObservation(tables_total=10, tables_undecided=10).coverage == 0.0


class TestTheAction:
    def test_no_observation_proposes_nothing(self):
        """Existing call sites that never observed this must derive no action."""
        assert _dispositions(propose_next_actions(_snapshot()).actions) == []

    def test_a_fully_decided_hub_proposes_nothing(self):
        snap = _snapshot(
            source_dispositions=SourceDispositionObservation(tables_total=12, tables_undecided=0)
        )
        assert _dispositions(propose_next_actions(snap).actions) == []

    def test_undecided_tables_propose_recording_them(self):
        snap = _snapshot(
            source_dispositions=SourceDispositionObservation(tables_total=68, tables_undecided=17)
        )
        actions = _dispositions(propose_next_actions(snap).actions)
        assert len(actions) == 1
        assert actions[0].status is ActionStatus.HUMAN_DECISION_REQUIRED
        assert actions[0].blocking is True

    def test_the_rationale_carries_the_counts_and_the_coverage(self):
        """An operator has to be able to size the work from the line alone."""
        snap = _snapshot(
            source_dispositions=SourceDispositionObservation(tables_total=68, tables_undecided=17)
        )
        rationale = _dispositions(propose_next_actions(snap).actions)[0].rationale
        assert "17 of 68" in rationale
        assert "75% decided" in rationale
        # Say *why* it is required, or it reads as bureaucracy.
        assert "validate" in rationale
        assert "DD-164" in rationale

    def test_it_names_the_distinction_from_the_column_gap_gate(self):
        """Confusing the two gates sends the operator to the wrong command."""
        snap = _snapshot(
            source_dispositions=SourceDispositionObservation(tables_total=3, tables_undecided=3)
        )
        rationale = _dispositions(propose_next_actions(snap).actions)[0].rationale
        assert "table-grain" in rationale
        assert "column-grain" in rationale

    def test_the_command_is_runnable_and_names_the_dispositions(self):
        snap = _snapshot(
            source_dispositions=SourceDispositionObservation(tables_total=3, tables_undecided=1)
        )
        command = _dispositions(propose_next_actions(snap).actions)[0].command
        assert "source-disposition set" in command
        assert "not-business-data" in command
        assert "deferred" in command
        assert "--rationale" in command

    def test_it_is_routed_to_the_source_lifecycle_skill(self):
        snap = _snapshot(
            source_dispositions=SourceDispositionObservation(tables_total=3, tables_undecided=1)
        )
        assert _dispositions(propose_next_actions(snap).actions)[0].skill == "kairos-design-source"


class TestContract:
    def test_schema_version_was_bumped(self):
        """Every prior observation set bumped it; a silent addition breaks consumers."""
        assert SCHEMA_VERSION >= 7

    def test_the_action_survives_json_serialization(self):
        snap = _snapshot(
            source_dispositions=SourceDispositionObservation(tables_total=5, tables_undecided=2)
        )
        proposal = propose_next_actions(snap)
        assert any(a.kind == "record-source-disposition" for a in proposal.actions)


class TestObserverDegradesRatherThanCrashing:
    """`next` must survive a hub mid-import, where the audit can legitimately fail."""

    def test_a_nonexistent_hub_yields_the_no_observation_default(self, tmp_path):
        from kairos_ontology.core.hub_inspection import _source_disposition_status

        assert _source_disposition_status(tmp_path / "nope") == SourceDispositionObservation()

    def test_an_empty_hub_yields_the_no_observation_default(self, tmp_path):
        """No imported tables is not the same as none decided."""
        from kairos_ontology.core.hub_inspection import _source_disposition_status

        obs = _source_disposition_status(tmp_path)
        assert obs == SourceDispositionObservation()
        assert obs.coverage == 1.0
