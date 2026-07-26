# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Parity tests for the dbt diagnostic foundation."""

from __future__ import annotations

import dataclasses

import pytest

from kairos_ontology.core.projections.dbt import (
    Diagnostic,
    DiagnosticCollector,
    DiagnosticFailure,
    EvaluationResult,
    EvaluationStatus,
    ExecutionMode,
    MappingContractError,
    PolicyIssue,
    PolicyCollectionError,
    PolicyNormalizationError,
    Prerequisite,
    order_diagnostics,
    bind_sources,
    normalize_contract,
)
from tests.test_dbt_phases import _client_inputs


def _diagnostic(**overrides: object) -> Diagnostic:
    values = {
        "code": "prep.missing-policy",
        "message": "Preparation policy is required",
        "rule_id": "DD-106-preparation",
        "resource_uri": "https://example.test/source/B",
        "predicate_uri": "https://example.test/predicate/mode",
    }
    values.update(overrides)
    return Diagnostic(**values)


def test_collector_defaults_to_fail_fast_and_preserves_first_diagnostic() -> None:
    collector = DiagnosticCollector()
    diagnostic = _diagnostic()

    assert collector.mode is ExecutionMode.FAIL_FAST
    with pytest.raises(DiagnosticFailure) as caught:
        collector.add(diagnostic)

    assert caught.value.diagnostic is diagnostic
    assert collector.diagnostics == ()


def test_policy_error_exposes_backward_compatible_diagnostic_metadata() -> None:
    error = PolicyNormalizationError(
        "prep.missing-policy",
        "Preparation policy is required",
        rule_id="DD-106-preparation",
        resource_uri="https://example.test/source/A",
        predicate_uri="https://example.test/predicate/mode",
    )

    assert str(error) == (
        "prep.missing-policy: Preparation policy is required at "
        "https://example.test/source/A "
        "(https://example.test/predicate/mode) [DD-106-preparation]"
    )
    assert (
        error.diagnostic.code,
        error.diagnostic.rule_id,
        error.diagnostic.resource_uri,
        error.diagnostic.predicate_uri,
    ) == (error.code, error.rule_id, error.resource_uri, error.predicate_uri)
    assert error.diagnostic.schema_version == "1.0"


def test_policy_issue_exposes_backward_compatible_diagnostic_metadata() -> None:
    issue = PolicyIssue(
        code="identity.missing-policy",
        message="Identity policy is required",
        rule_id="DD-108-identity",
        resource_uri="https://example.test/Entity",
        blocking=False,
    )

    assert issue.diagnostic.code == issue.code
    assert issue.diagnostic.rule_id == issue.rule_id
    assert issue.diagnostic.resource_uri == issue.resource_uri
    assert issue.diagnostic.blocking is issue.blocking
    assert issue.diagnostic.severity.value == "warning"


def test_diagnostic_order_is_stage_resource_predicate_code_then_id() -> None:
    diagnostics = (
        _diagnostic(id="z", resource_uri="https://example.test/source/B"),
        _diagnostic(id="b", resource_uri="https://example.test/source/A"),
        _diagnostic(id="a", resource_uri="https://example.test/source/A"),
        _diagnostic(id="0", stage="binding"),
    )
    collector = DiagnosticCollector(ExecutionMode.COLLECT)
    for diagnostic in diagnostics:
        collector.add(diagnostic)

    assert [item.id for item in order_diagnostics(diagnostics)] == ["0", "a", "b", "z"]
    assert [item.id for item in collector.diagnostics] == ["0", "a", "b", "z"]


def test_not_evaluated_result_retains_failed_prerequisite() -> None:
    prerequisite = Prerequisite(
        id="preparation",
        status=EvaluationStatus.FAILED,
        diagnostic_ids=("prep-1",),
    )

    result = EvaluationResult[object].not_evaluated((prerequisite,))

    assert result.status is EvaluationStatus.NOT_EVALUATED
    assert result.value is None
    assert not result.prerequisites[0].available


def _independent_prep_and_identity_failures():
    bound = bind_sources(_client_inputs())
    facts = bound.policy_facts
    preparations = tuple(
        item
        for item in facts.preparations
        if not item.resource_uri.endswith("tblClientPIIPolicy")
    )
    identities = tuple(
        dataclasses.replace(item, strategy=None)
        if item.resource_uri.endswith("#Identifier")
        else item
        for item in facts.identities
    )
    return dataclasses.replace(
        bound,
        policy_facts=dataclasses.replace(
            facts,
            preparations=preparations,
            identities=identities,
        ),
    )


def test_collect_reports_missing_prep_and_independent_identity() -> None:
    bound = _independent_prep_and_identity_failures()

    with pytest.raises(PolicyCollectionError) as caught:
        normalize_contract(bound, ExecutionMode.COLLECT)

    diagnostics = caught.value.diagnostics
    assert [item.code for item in diagnostics if item.blocking] == [
        "prep.missing-policy",
        "identity.missing-strategy",
    ]
    assert caught.value.stages.preparation.value
    assert caught.value.stages.identity.value


def test_missing_prep_suppresses_dependent_identity_runtime_and_fk_cascades() -> None:
    error = pytest.raises(
        PolicyCollectionError,
        normalize_contract,
        _independent_prep_and_identity_failures(),
        ExecutionMode.COLLECT,
    ).value
    diagnostics = {item.code: item for item in error.diagnostics}
    prep_id = diagnostics["prep.missing-policy"].id

    assert diagnostics["identity.not-evaluated"].depends_on == (prep_id,)
    assert diagnostics["runtime.not-evaluated"].depends_on == (prep_id,)
    assert diagnostics["foreign_keys.not-evaluated"].depends_on
    assert error.stages.runtime.status is EvaluationStatus.NOT_EVALUATED
    assert error.stages.foreign_keys.status is EvaluationStatus.NOT_EVALUATED
    assert "identity.unknown-source-identity" not in diagnostics


def test_fail_fast_and_collect_preserve_first_diagnostic_and_order() -> None:
    bound = _independent_prep_and_identity_failures()
    with pytest.raises(PolicyNormalizationError) as fail_fast:
        normalize_contract(bound)
    with pytest.raises(PolicyCollectionError) as first:
        normalize_contract(bound, ExecutionMode.COLLECT)
    with pytest.raises(PolicyCollectionError) as second:
        normalize_contract(bound, ExecutionMode.COLLECT)

    assert str(first.value) == str(fail_fast.value)
    assert [item.id for item in first.value.diagnostics] == [
        item.id for item in second.value.diagnostics
    ]


def test_collect_mode_has_no_valid_projection_contract_change() -> None:
    bound = bind_sources(_client_inputs())

    assert normalize_contract(bound, ExecutionMode.COLLECT) == normalize_contract(bound)


def _four_independent_roots():
    bound = bind_sources(_client_inputs())
    facts = bound.policy_facts
    return dataclasses.replace(
        bound,
        policy_facts=dataclasses.replace(
            facts,
            preparations=tuple(
                item
                for item in facts.preparations
                if not item.resource_uri.endswith("tblClientPIIPolicy")
            ),
            incremental=(
                dataclasses.replace(facts.incremental[0], merge_identity=None),
                *facts.incremental[1:],
            ),
            temporal_relationships=(
                dataclasses.replace(facts.temporal_relationships[0], mode=None),
                *facts.temporal_relationships[1:],
            ),
        ),
        mappings=dataclasses.replace(
            bound.mappings,
            columns=(
                dataclasses.replace(
                    bound.mappings.columns[0],
                    target_data_type="not-a-canonical-type",
                ),
                *bound.mappings.columns[1:],
            ),
        ),
    )


def test_collect_reports_four_real_roots_and_suppresses_identity_cascades() -> None:
    error = pytest.raises(
        PolicyCollectionError,
        normalize_contract,
        _four_independent_roots(),
        ExecutionMode.COLLECT,
    ).value

    blockers = [item for item in error.diagnostics if item.blocking]
    assert [(item.stage, item.code) for item in blockers] == [
        ("preparation", "prep.missing-policy"),
        ("mapping", "mapping.unknown-target-type"),
        ("runtime", "policy.missing-value"),
        ("temporal_fk", "policy.missing-value"),
    ]
    assert "identity.unknown-incremental-policy" not in {
        item.code for item in error.diagnostics
    }
    identity_skip = next(
        item for item in error.diagnostics if item.code == "identity.not-evaluated"
    )
    assert len(identity_skip.depends_on) == 2


def test_every_four_root_blocker_is_reachable_by_fail_fast_after_repairs() -> None:
    valid = bind_sources(_client_inputs())
    facts = valid.policy_facts
    cases = (
        (
            dataclasses.replace(
                valid,
                policy_facts=dataclasses.replace(
                    facts,
                    preparations=tuple(
                        item
                        for item in facts.preparations
                        if not item.resource_uri.endswith("tblClientPIIPolicy")
                    ),
                ),
            ),
            PolicyNormalizationError,
            "prep.missing-policy",
        ),
        (
            dataclasses.replace(
                valid,
                mappings=dataclasses.replace(
                    valid.mappings,
                    columns=(
                        dataclasses.replace(
                            valid.mappings.columns[0],
                            target_data_type="not-a-canonical-type",
                        ),
                        *valid.mappings.columns[1:],
                    ),
                ),
            ),
            MappingContractError,
            "mapping.unknown-target-type",
        ),
        (
            dataclasses.replace(
                valid,
                policy_facts=dataclasses.replace(
                    facts,
                    incremental=(
                        dataclasses.replace(facts.incremental[0], merge_identity=None),
                        *facts.incremental[1:],
                    ),
                ),
            ),
            PolicyNormalizationError,
            "policy.missing-value",
        ),
        (
            dataclasses.replace(
                valid,
                policy_facts=dataclasses.replace(
                    facts,
                    temporal_relationships=(
                        dataclasses.replace(facts.temporal_relationships[0], mode=None),
                        *facts.temporal_relationships[1:],
                    ),
                ),
            ),
            PolicyNormalizationError,
            "policy.missing-value",
        ),
    )

    for bound, exception_type, code in cases:
        error = pytest.raises(exception_type, normalize_contract, bound).value
        assert error.code == code
