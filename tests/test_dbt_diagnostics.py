# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Parity tests for the dbt diagnostic foundation."""

from __future__ import annotations

import pytest

from kairos_ontology.core.projections.dbt import (
    Diagnostic,
    DiagnosticCollector,
    DiagnosticFailure,
    EvaluationResult,
    EvaluationStatus,
    ExecutionMode,
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


def test_collect_mode_has_no_valid_projection_contract_change() -> None:
    bound = bind_sources(_client_inputs())

    assert normalize_contract(bound, ExecutionMode.COLLECT) == normalize_contract(bound)
