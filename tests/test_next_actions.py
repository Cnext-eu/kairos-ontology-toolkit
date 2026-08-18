# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unit tests for the pure next-action proposer (DD-137)."""

from __future__ import annotations

import json
from dataclasses import asdict

from kairos_ontology.core.next_actions import (
    ACTION_SKILLS,
    ActionStatus,
    BiConceptMappingObservation,
    CompileStatus,
    DiagnosticView,
    DiscoveryConformanceStatus,
    DomainSnapshot,
    HubInputSnapshot,
    InputStatus,
    SourceSampleObservation,
    SourceSampleStatus,
    discovery_gate_satisfied,
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


def test_fresh_hub_blocks_on_discovery_but_leaves_source_and_domain_advisory():
    # DD-148: missing discovery is a hard block (mirrored as BLOCKING here; the real
    # enforcement is in `kairos-ontology compile`/`validate`). Design-domain inherits the
    # block transitively since discovery hasn't run; source stays advisory as before.
    proposal = propose_next_actions(
        _hub(discovery=InputStatus.MISSING, sources=InputStatus.MISSING, domains=())
    )
    by_kind = {action.kind: action for action in proposal.actions}
    assert set(by_kind) == {"design-discovery", "design-source", "design-domain"}
    assert by_kind["design-discovery"].status is ActionStatus.BLOCKING
    assert by_kind["design-discovery"].blocking is True
    assert by_kind["design-domain"].status is ActionStatus.BLOCKING
    assert by_kind["design-domain"].blocking is True
    assert by_kind["design-source"].status is ActionStatus.HUMAN_DECISION_REQUIRED
    assert by_kind["design-source"].blocking is False


def test_conformance_artifact_alone_satisfies_discovery_without_glossary_ttl():
    # DD-148: businessdiscovery/ (DD-048) and the conformance artifact (DD-090) are
    # independent — a valid conformance artifact downgrades the missing-glossary-ttl
    # signal from BLOCKING to advisory, matching what check_discovery_gate() enforces.
    proposal = propose_next_actions(
        _hub(
            discovery=InputStatus.MISSING,
            discovery_conformance=DiscoveryConformanceStatus.VALID,
            domains=(),
        )
    )
    by_kind = {action.kind: action for action in proposal.actions}
    assert by_kind["design-discovery"].status is ActionStatus.HUMAN_DECISION_REQUIRED
    assert by_kind["design-discovery"].blocking is False
    assert by_kind["design-domain"].status is ActionStatus.HUMAN_DECISION_REQUIRED
    assert by_kind["design-domain"].blocking is False


def test_present_discovery_with_domains_stays_advisory():
    # Discovery ran and is valid; a hub with existing domains sees no discovery-related
    # blocking action at all.
    proposal = propose_next_actions(
        _hub(
            domains=(
                _domain(
                    "party",
                    has_bindings=False,
                    binding_count=0,
                    compile_status=CompileStatus.NOT_RUN,
                ),
            )
        )
    )
    assert "design-discovery" not in _kinds(proposal)
    assert "resolve-discovery-open-questions" not in _kinds(proposal)


def test_unresolved_fleet_discovery_blocks_independently_of_domain_state():
    # DD-148: a fleet-mode discovery artifact with unresolved AI-decided judgments blocks
    # regardless of whether domains already exist.
    proposal = propose_next_actions(
        _hub(
            discovery_conformance=DiscoveryConformanceStatus.UNRESOLVED_FLEET,
            domains=(_domain("party"),),
        )
    )
    by_kind = {action.kind: action for action in proposal.actions}
    assert "resolve-discovery-open-questions" in by_kind
    action = by_kind["resolve-discovery-open-questions"]
    assert action.status is ActionStatus.BLOCKING
    assert action.blocking is True
    assert action.skill == "kairos-design-discovery"
    assert action.priority == 25


def test_unresolved_fleet_discovery_also_blocks_design_domain_when_no_domains_yet():
    proposal = propose_next_actions(
        _hub(discovery_conformance=DiscoveryConformanceStatus.UNRESOLVED_FLEET, domains=())
    )
    by_kind = {action.kind: action for action in proposal.actions}
    assert by_kind["design-domain"].status is ActionStatus.BLOCKING
    assert by_kind["design-domain"].blocking is True


def test_ontology_without_binding_recommends_authoring():
    proposal = propose_next_actions(
        _hub(
            domains=(
                _domain(
                    "party",
                    has_bindings=False,
                    binding_count=0,
                    compile_status=CompileStatus.NOT_RUN,
                ),
            )
        )
    )
    assert _kinds(proposal) == ["author-binding"]
    assert proposal.actions[0].status is ActionStatus.RECOMMENDED
    assert proposal.actions[0].skill == "kairos-design-mapping"


def test_binding_without_ontology_requires_domain_decision():
    proposal = propose_next_actions(
        _hub(
            domains=(
                _domain(
                    "party", ontology=InputStatus.MISSING, compile_status=CompileStatus.NOT_RUN
                ),
            )
        )
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


def test_emitted_project_surfaces_optional_validate_dbt_gate():
    proposal = propose_next_actions(
        _hub(
            domains=(_domain("party"),),
            emitted_dbt_project=InputStatus.PRESENT,
            adapter="fabric",
        )
    )
    kinds = _kinds(proposal)
    assert "validate-dbt" in kinds
    gate = next(a for a in proposal.actions if a.kind == "validate-dbt")
    assert gate.status is ActionStatus.OPTIONAL
    assert gate.blocking is False
    assert gate.skill == "kairos-execute-validate"
    assert gate.command == "kairos-ontology validate-dbt --platform fabric"


def test_validate_dbt_gate_absent_without_emitted_project():
    proposal = propose_next_actions(_hub(domains=(_domain("party"),)))
    assert "validate-dbt" not in _kinds(proposal)


def test_validate_dbt_gate_absent_when_no_domain_passes():
    proposal = propose_next_actions(
        _hub(
            domains=(_domain("party", compile_status=CompileStatus.NOT_RUN),),
            compile_ran=False,
            emitted_dbt_project=InputStatus.PRESENT,
            adapter="databricks",
        )
    )
    assert "validate-dbt" not in _kinds(proposal)


def test_validate_dbt_gate_uses_placeholder_platform_when_adapter_unknown():
    proposal = propose_next_actions(
        _hub(domains=(_domain("party"),), emitted_dbt_project=InputStatus.PRESENT)
    )
    gate = next(a for a in proposal.actions if a.kind == "validate-dbt")
    assert gate.command == "kairos-ontology validate-dbt --platform <fabric|databricks>"


def test_unreadable_emitted_project_requires_human_decision():
    proposal = propose_next_actions(
        _hub(domains=(_domain("party"),), emitted_dbt_project=InputStatus.UNREADABLE)
    )
    gate = next(a for a in proposal.actions if a.kind == "validate-dbt")
    assert gate.status is ActionStatus.HUMAN_DECISION_REQUIRED


def test_not_run_compile_is_indeterminate_never_ready():
    proposal = propose_next_actions(
        _hub(compile_ran=False, domains=(_domain("party", compile_status=CompileStatus.NOT_RUN),))
    )
    assert _kinds(proposal) == ["run-check"]
    assert proposal.actions[0].status is ActionStatus.INDETERMINATE
    assert "compile-emit" not in _kinds(proposal)


def test_optional_policies_only_when_authored():
    without = propose_next_actions(_hub(domains=(_domain("party"),)))
    assert "review-gold" not in _kinds(without)
    assert "review-mdm" not in _kinds(without)

    with_policy = propose_next_actions(
        _hub(
            domains=(
                _domain("party", gold_policy=InputStatus.PRESENT, mdm_policy=InputStatus.PRESENT),
            )
        )
    )
    kinds = _kinds(with_policy)
    assert "review-gold" in kinds and "review-mdm" in kinds
    for action in with_policy.actions:
        if action.kind in {"review-gold", "review-mdm"}:
            assert action.status is ActionStatus.OPTIONAL


def test_no_actions_when_everything_present_and_compiles():
    proposal = propose_next_actions(_hub(domains=(_domain("party"), _domain("orders"))))
    # Both domains pass -> only emit actions, none blocking.
    assert set(_kinds(proposal)) == {"compile-emit"}
    assert not any(a.blocking for a in proposal.actions)


def test_ordering_is_deterministic_and_idempotent():
    snapshot = _hub(
        discovery=InputStatus.MISSING,
        domains=(
            _domain(
                "zeta",
                compile_status=CompileStatus.FAILED,
                diagnostics=(DiagnosticView("c", "m", "error", "l", "DD-133"),),
            ),
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
            _domain("a", has_bindings=False, binding_count=0, compile_status=CompileStatus.NOT_RUN),
            _domain("b", ontology=InputStatus.MISSING, compile_status=CompileStatus.NOT_RUN),
            _domain(
                "c",
                compile_status=CompileStatus.FAILED,
                diagnostics=(DiagnosticView("x", "m", "error", "l", "DD-133"),),
            ),
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
        "actions": [{**asdict(a), "status": a.status.value} for a in proposal.actions],
    }
    first = json.dumps(payload, sort_keys=True)
    second = json.dumps(payload, sort_keys=True)
    assert first == second
    assert '"schema_version": 7' in first


# ---------------------------------------------------------------------------
# Issue #298 — source-sample-coverage observation
# ---------------------------------------------------------------------------


def test_source_samples_none_yields_human_decision_required_action():
    proposal = propose_next_actions(
        _hub(
            source_samples=SourceSampleObservation(
                status=SourceSampleStatus.NONE, tables_with_samples=0, tables_total=3
            )
        )
    )
    by_kind = {action.kind: action for action in proposal.actions}
    action = by_kind["design-source"]
    assert action.status is ActionStatus.HUMAN_DECISION_REQUIRED
    assert action.blocking is False
    assert "3" in action.rationale
    assert action.skill == "kairos-design-source"


def test_source_samples_partial_yields_optional_action_naming_missing_count():
    proposal = propose_next_actions(
        _hub(
            source_samples=SourceSampleObservation(
                status=SourceSampleStatus.PARTIAL, tables_with_samples=2, tables_total=3
            )
        )
    )
    by_kind = {action.kind: action for action in proposal.actions}
    action = by_kind["design-source"]
    assert action.status is ActionStatus.OPTIONAL
    assert "1 of 3" in action.rationale


def test_source_samples_full_adds_no_action():
    proposal = propose_next_actions(
        _hub(
            source_samples=SourceSampleObservation(
                status=SourceSampleStatus.FULL, tables_with_samples=3, tables_total=3
            )
        )
    )
    assert "design-source" not in _kinds(proposal)


def test_source_samples_not_applicable_adds_no_action():
    proposal = propose_next_actions(_hub())
    assert "design-source" not in _kinds(proposal)


# ---------------------------------------------------------------------------
# Issue #310 — discovery_gate_satisfied single source of truth
# ---------------------------------------------------------------------------


def test_discovery_gate_satisfied_true_when_glossary_ttl_present():
    snapshot = _hub(discovery=InputStatus.PRESENT)
    assert discovery_gate_satisfied(snapshot) is True


def test_discovery_gate_satisfied_true_when_only_conformance_artifact_present():
    snapshot = _hub(
        discovery=InputStatus.MISSING,
        discovery_conformance=DiscoveryConformanceStatus.VALID,
    )
    assert discovery_gate_satisfied(snapshot) is True


def test_discovery_gate_satisfied_false_when_neither_signal_present():
    snapshot = _hub(
        discovery=InputStatus.MISSING,
        discovery_conformance=DiscoveryConformanceStatus.NOT_RUN,
    )
    assert discovery_gate_satisfied(snapshot) is False


# ---------------------------------------------------------------------------
# Issue #321 — DD-047 inventory-freshness gate
# ---------------------------------------------------------------------------








def test_present_inventory_adds_no_action():
    proposal = propose_next_actions(_hub(inventory_status=InputStatus.PRESENT))
    assert "generate-inventory" not in _kinds(proposal)


# ---------------------------------------------------------------------------
# Issue #421 / DD-157 — BI concept-mapping worksheet triage observation
# ---------------------------------------------------------------------------


def test_triage_concept_mapping_maps_to_design_source_skill():
    # DD-157: worksheet triage belongs to the import-tmdl lifecycle owner
    # (kairos-design-source), NOT kairos-design-domain, whose charter forbids
    # filling the worksheet during a design slice.
    assert ACTION_SKILLS["triage-concept-mapping"] == "kairos-design-source"


def test_unfilled_concept_mapping_yields_human_decision_required_action():
    proposal = propose_next_actions(
        _hub(
            bi_concept_mappings=BiConceptMappingObservation(
                tables_total=24, tables_unfilled=24
            )
        )
    )
    by_kind = {action.kind: action for action in proposal.actions}
    action = by_kind["triage-concept-mapping"]
    assert action.status is ActionStatus.HUMAN_DECISION_REQUIRED
    assert action.blocking is False  # advisory only (DD-137/DD-147)
    assert action.skill == "kairos-design-source"
    assert "24 of 24" in action.rationale
    # The rationale must name the worksheet path and both deterministic consumers.
    assert "integration/discovery/bi/" in action.rationale
    assert "design-landscape" in action.rationale
    assert "draft-model-report" in action.rationale


def test_fully_triaged_concept_mapping_adds_no_action():
    proposal = propose_next_actions(
        _hub(bi_concept_mappings=BiConceptMappingObservation(tables_total=5, tables_unfilled=0))
    )
    assert "triage-concept-mapping" not in _kinds(proposal)


def test_default_no_observation_adds_no_action():
    # F5.2: existing constructor sites that never observed worksheets must not
    # start emitting a spurious action.
    proposal = propose_next_actions(_hub())
    assert "triage-concept-mapping" not in _kinds(proposal)
