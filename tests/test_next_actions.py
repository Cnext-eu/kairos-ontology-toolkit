# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unit tests for the pure next-action proposer (DD-137)."""

from __future__ import annotations

import json
from dataclasses import asdict

from kairos_ontology.core.next_actions import (
    ACTION_SKILLS,
    ActionStatus,
    CompileStatus,
    DiagnosticView,
    DomainSnapshot,
    HubInputSnapshot,
    InputStatus,
    propose_next_actions,
)


def _hub(**overrides) -> HubInputSnapshot:
    base = dict(
        hub_root="/hub",
        discovery=InputStatus.PRESENT,
        sources=InputStatus.PRESENT,
        dbt_transforms=InputStatus.PRESENT,
        shapes=InputStatus.PRESENT,
        domains=(),
        compile_ran=True,
    )
    base.update(overrides)
    return HubInputSnapshot(**base)


def _domain(name: str, **overrides) -> DomainSnapshot:
    base = dict(
        domain=name,
        ontology=InputStatus.PRESENT,
        has_bindings=True,
        binding_count=1,
        compile_status=CompileStatus.PASSED,
    )
    base.update(overrides)
    return DomainSnapshot(**base)


def _kinds(proposal) -> list[str]:
    return [action.kind for action in proposal.actions]


def test_fresh_hub_requires_human_decisions_for_discovery_and_source():
    proposal = propose_next_actions(
        _hub(discovery=InputStatus.MISSING, sources=InputStatus.MISSING, domains=())
    )
    kinds = _kinds(proposal)
    assert "design-discovery" in kinds
    assert "design-source" in kinds
    assert "design-domain" in kinds
    for action in proposal.actions:
        assert action.status is ActionStatus.HUMAN_DECISION_REQUIRED


def test_ontology_without_binding_recommends_authoring():
    proposal = propose_next_actions(
        _hub(domains=(_domain("party", has_bindings=False, binding_count=0,
                              compile_status=CompileStatus.NOT_RUN),))
    )
    assert _kinds(proposal) == ["author-binding"]
    assert proposal.actions[0].status is ActionStatus.RECOMMENDED
    assert proposal.actions[0].skill == "kairos-design-mapping"


def test_binding_without_ontology_requires_domain_decision():
    proposal = propose_next_actions(
        _hub(domains=(_domain("party", ontology=InputStatus.MISSING,
                              compile_status=CompileStatus.NOT_RUN),))
    )
    assert _kinds(proposal) == ["design-domain"]
    assert proposal.actions[0].status is ActionStatus.HUMAN_DECISION_REQUIRED


def test_failed_compile_yields_blocking_fix_actions_per_error():
    diags = (
        DiagnosticView("safety.column-unresolved", "col missing", "error", "b.yaml:3:1", "DD-133"),
        DiagnosticView("style.info", "informational", "info", "b.yaml:4:1", "DD-133"),
    )
    proposal = propose_next_actions(
        _hub(domains=(_domain("party", compile_status=CompileStatus.FAILED, diagnostics=diags),))
    )
    assert _kinds(proposal) == ["fix-diagnostic"]
    action = proposal.actions[0]
    assert action.blocking is True
    assert action.status is ActionStatus.BLOCKING
    assert action.target == "safety.column-unresolved"


def test_passed_compile_recommends_emit():
    proposal = propose_next_actions(_hub(domains=(_domain("party"),)))
    assert _kinds(proposal) == ["compile-emit"]
    assert proposal.actions[0].status is ActionStatus.RECOMMENDED


def test_not_run_compile_is_indeterminate_never_ready():
    proposal = propose_next_actions(
        _hub(compile_ran=False,
             domains=(_domain("party", compile_status=CompileStatus.NOT_RUN),))
    )
    assert _kinds(proposal) == ["run-check"]
    assert proposal.actions[0].status is ActionStatus.INDETERMINATE
    assert "compile-emit" not in _kinds(proposal)


def test_optional_policies_only_when_authored():
    without = propose_next_actions(_hub(domains=(_domain("party"),)))
    assert "review-gold" not in _kinds(without)
    assert "review-mdm" not in _kinds(without)

    with_policy = propose_next_actions(
        _hub(domains=(_domain("party", gold_policy=InputStatus.PRESENT,
                              mdm_policy=InputStatus.PRESENT),))
    )
    kinds = _kinds(with_policy)
    assert "review-gold" in kinds and "review-mdm" in kinds
    for action in with_policy.actions:
        if action.kind in {"review-gold", "review-mdm"}:
            assert action.status is ActionStatus.OPTIONAL


def test_no_actions_when_everything_present_and_compiles():
    proposal = propose_next_actions(
        _hub(domains=(_domain("party"), _domain("orders")))
    )
    # Both domains pass -> only emit actions, none blocking.
    assert set(_kinds(proposal)) == {"compile-emit"}
    assert not any(a.blocking for a in proposal.actions)


def test_ordering_is_deterministic_and_idempotent():
    snapshot = _hub(
        discovery=InputStatus.MISSING,
        domains=(
            _domain("zeta", compile_status=CompileStatus.FAILED,
                    diagnostics=(DiagnosticView("c", "m", "error", "l", "DD-133"),)),
            _domain("alpha"),
        ),
    )
    first = propose_next_actions(snapshot)
    second = propose_next_actions(snapshot)
    assert [(a.kind, a.domain) for a in first.actions] == [
        (a.kind, a.domain) for a in second.actions
    ]
    priorities = [a.priority for a in first.actions]
    assert priorities == sorted(priorities)


def test_every_action_kind_maps_to_a_skill():
    snapshot = _hub(
        discovery=InputStatus.MISSING,
        sources=InputStatus.MISSING,
        domains=(
            _domain("a", has_bindings=False, binding_count=0,
                    compile_status=CompileStatus.NOT_RUN),
            _domain("b", ontology=InputStatus.MISSING, compile_status=CompileStatus.NOT_RUN),
            _domain("c", compile_status=CompileStatus.FAILED,
                    diagnostics=(DiagnosticView("x", "m", "error", "l", "DD-133"),)),
            _domain("d", gold_policy=InputStatus.PRESENT, mdm_policy=InputStatus.PRESENT),
        ),
    )
    proposal = propose_next_actions(snapshot)
    for action in proposal.actions:
        assert action.skill == ACTION_SKILLS[action.kind]


def test_proposal_is_json_serializable_and_stable():
    proposal = propose_next_actions(_hub(domains=(_domain("party"),)))
    payload = {
        "schema_version": proposal.schema_version,
        "actions": [
            {**asdict(a), "status": a.status.value} for a in proposal.actions
        ],
    }
    first = json.dumps(payload, sort_keys=True)
    second = json.dumps(payload, sort_keys=True)
    assert first == second
    assert '"schema_version": 1' in first
