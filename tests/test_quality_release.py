# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Executable DQ and fail-closed release contracts (DD-114/DD-115)."""

from __future__ import annotations

import dataclasses
import hashlib

import pytest
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.projector import ProjectionRunError
from kairos_ontology.core.projections.dbt import (
    bind_sources,
    normalize_contract,
    shape_project,
)
from kairos_ontology.core.projections.dbt.materialize import (
    _quality_physical_plans,
)
from kairos_ontology.core.projections.dbt.policy_normalize import _normalize_dq
from kairos_ontology.core.projections.dbt.policy_specs import (
    AuthoredValuesFact,
    DataQualityRuleFact,
    DqAction,
    DqCategory,
    DqCheckKind,
    DqParameterSpec,
    DqResultStatus,
    DqRuntimeFieldSpec,
    DqRuntimeResultContractSpec,
)
from kairos_ontology.core.projections.dbt.quality_renderers import (
    render_dq_accepted_model,
    render_dq_quarantine,
    render_dq_result,
    render_dq_runtime_contract,
    render_dq_test,
)
from kairos_ontology.core.projections.dbt.specs import (
    ColumnSpec,
    DqModelPhysicalPlan,
    DqRulePhysicalPlan,
    ModelIdentity,
    ModelOutcome,
    SilverModelKind,
    SilverModelSpec,
)
from kairos_ontology.core.release_evaluator import (
    BaselineLoadResult,
    DqRuntimeObservation,
    ReleaseBaselineSpec,
    ReleaseDisposition,
    ReleaseEvaluationInput,
    evaluate_release,
)


def _auth(resource: str, predicate: str, *values: str) -> AuthoredValuesFact:
    return AuthoredValuesFact(resource, predicate, tuple(values))


def _dq_fact(
    kind: str,
    expression: str,
    *,
    category: str = "business",
    action: str = "block",
    tolerance: str = "0",
    suffix: str = "",
) -> DataQualityRuleFact:
    resource = f"urn:dq:{kind}{suffix}"
    return DataQualityRuleFact(
        resource_uri=resource,
        rule_id=_auth(resource, "dqRuleId", f"dq.{kind}{suffix}"),
        version=_auth(resource, "dqRuleVersion", "1"),
        category=_auth(resource, "dqCategory", category),
        scope=_auth(resource, "dqScope", "entity"),
        check_kind=_auth(resource, "dqCheckType", kind),
        check_expression=_auth(resource, "dqCheckExpression", expression),
        severity=_auth(resource, "dqSeverity", "error"),
        tolerance=_auth(resource, "dqTolerance", tolerance),
        action=_auth(resource, "dqAction", action),
        owner_role=_auth(resource, "dqOwnerRole", "Data Owner"),
        evidence=_auth(resource, "dqEvidence", "evidence:approved-rule"),
        test_refs=_auth(resource, "dqTestRef", f"kairos.dq.{kind}.v1"),
    )


_CHECKS = (
    ("contract-shape", "required=business_id", "contract", "block", "0"),
    ("freshness", "column=updated_at;unit=hours", "operational", "warn", "24"),
    ("volume", "metric=row-count", "source", "block", "1"),
    ("duplicate-rate", "columns=business_id", "source", "warn", "0.01"),
    (
        "range",
        "column=amount;minimum=0;maximum=1000",
        "business",
        "quarantine",
        "0.05",
    ),
    (
        "distribution",
        "column=status;allowed=active|inactive",
        "business",
        "quarantine",
        "0.1",
    ),
    (
        "reconciliation",
        "compare_model=expected;metric=count",
        "operational",
        "block",
        "0",
    ),
    (
        "referential-coverage",
        "column=parent_id;parent_model=parent;parent_column=parent_id",
        "contract",
        "quarantine",
        "0",
    ),
    (
        "cross-field",
        "left=start_value;operator=lte;right=end_value",
        "business",
        "quarantine",
        "0",
    ),
)


@pytest.mark.parametrize(
    ("kind", "expression", "category", "action", "tolerance"),
    _CHECKS,
)
def test_each_dq_category_check_action_and_tolerance_normalizes(
    kind,
    expression,
    category,
    action,
    tolerance,
):
    rule = _normalize_dq(
        (
            _dq_fact(
                kind,
                expression,
                category=category,
                action=action,
                tolerance=tolerance,
            ),
        )
    )[0]

    assert rule.category.value is DqCategory(category)
    assert rule.check.check_kind.value is DqCheckKind(kind)
    assert rule.action.value is DqAction(action)
    assert rule.tolerance.value.value == tolerance
    assert len(rule.rule_hash) == 64
    assert rule.check.test_refs.value == (f"kairos.dq.{kind}.v1",)


@pytest.mark.parametrize(
    ("kind", "expression", "tolerance"),
    (
        ("contract-shape", "required=business_id", "1"),
        ("duplicate-rate", "columns=business_id", "1.01"),
        ("volume", "metric=row-count", "1.5"),
        ("range", "column=amount;minimum=10;maximum=1", "0"),
    ),
)
def test_invalid_dq_tolerance_or_expression_fails_closed(
    kind,
    expression,
    tolerance,
):
    with pytest.raises(ValueError):
        _normalize_dq(
            (_dq_fact(kind, expression, tolerance=tolerance),)
        )


def test_raw_sql_and_unknown_test_references_are_rejected():
    raw_sql = _dq_fact(
        "cross-field",
        "left=amount;operator=eq;right=select * from secret",
    )
    with pytest.raises(ValueError, match="dbt identifiers"):
        _normalize_dq((raw_sql,))

    unknown = dataclasses.replace(
        _dq_fact("volume", "metric=row-count"),
        test_refs=_auth("urn:dq:volume", "dqTestRef", "package.raw_sql"),
    )
    with pytest.raises(ValueError, match="toolkit-owned"):
        _normalize_dq((unknown,))


def test_aggregate_quarantine_and_unresolvable_scope_block_materialization():
    from tests.test_dbt_phases import _client_inputs

    bound = bind_sources(_client_inputs())
    contract = normalize_contract(bound)
    shaped = shape_project(contract)
    rule = contract.policy.data_quality[0]
    aggregate_rule = dataclasses.replace(
        rule,
        check=dataclasses.replace(
            rule.check,
            check_kind=dataclasses.replace(
                rule.check.check_kind,
                value=DqCheckKind.FRESHNESS,
            ),
            parameters=(
                DqParameterSpec("column", ("_source_updated_at",)),
                DqParameterSpec("unit", ("hours",)),
            ),
            test_refs=dataclasses.replace(
                rule.check.test_refs,
                value=("kairos.dq.freshness.v1",),
            ),
        ),
    )
    shaped = dataclasses.replace(
        shaped,
        silver_models=tuple(
            dataclasses.replace(
                model,
                authority=dataclasses.replace(
                    model.authority,
                    quality_rules=(aggregate_rule,),
                ),
            )
            if model.authority is not None
            and rule in model.authority.quality_rules
            else model
            for model in shaped.silver_models
        ),
    )
    with pytest.raises(ValueError, match="no deterministic row-level"):
        _quality_physical_plans(shaped)

    fact = bound.policy_facts.data_quality[0]
    unknown_scope = dataclasses.replace(
        fact.scope,
        values=("urn:unknown:scope",),
    )
    unscoped = dataclasses.replace(
        bound,
        policy_facts=dataclasses.replace(
            bound.policy_facts,
            data_quality=(
                dataclasses.replace(fact, scope=unknown_scope),
            ),
        ),
    )
    with pytest.raises(ValueError, match="does not resolve"):
        normalize_contract(unscoped)


def _quality_plan(kind: str, expression: str, action: str = "block"):
    rule = _normalize_dq(
        (
            _dq_fact(
                kind,
                expression,
                action=action,
                tolerance="0",
            ),
        )
    )[0]
    rule_plan = DqRulePhysicalPlan(
        rule=rule,
        target_model_name="entity",
        evaluated_model_name=(
            "entity__dq_input" if action == "quarantine" else "entity"
        ),
        result_model_name=f"entity__dq__{kind.replace('-', '_')}",
        result_artifact_path=f"models/quality/entity__dq__{kind}.sql",
        test_artifact_path=f"tests/quality/test_entity__dq__{kind}.sql",
        row_level=kind
        in {
            "contract-shape",
            "range",
            "distribution",
            "referential-coverage",
            "cross-field",
        },
    )
    model_plan = DqModelPhysicalPlan(
        model_name="entity",
        original_artifact_path="models/silver/domain/entity.sql",
        evaluated_model_name=rule_plan.evaluated_model_name,
        evaluated_artifact_path="models/silver/domain/entity__dq_input.sql",
        quarantine_model_name=(
            "entity__dq_quarantine" if action == "quarantine" else ""
        ),
        quarantine_artifact_path=(
            "models/silver/domain/entity__dq_quarantine.sql"
            if action == "quarantine"
            else ""
        ),
        rules=(rule_plan,),
    )
    return rule_plan, model_plan


def _silver_model() -> SilverModelSpec:
    return SilverModelSpec(
        identity=ModelIdentity(
            class_name="Entity",
            class_uri="urn:domain:Entity",
            model_name="entity",
            domain_name="domain",
            schema_name="silver_domain",
            artifact_path="models/silver/domain/entity.sql",
            outcome=ModelOutcome.GENERATED,
        ),
        kind=SilverModelKind.ENTITY,
        columns=(
            ColumnSpec("amount"),
            ColumnSpec("_source_system"),
            ColumnSpec("_source_identity_ref"),
            ColumnSpec("_source_record_key"),
            ColumnSpec("_source_updated_at"),
            ColumnSpec("_source_effective_at"),
            ColumnSpec("_ingested_at"),
            ColumnSpec("_loaded_at"),
        ),
    )


def test_row_quarantine_preserves_lineage_and_filters_normal_relation():
    rule, quality = _quality_plan(
        "range",
        "column=amount;minimum=0;maximum=100",
        "quarantine",
    )
    quarantine = render_dq_quarantine(quality, _silver_model(), adapter="fabric")
    accepted = render_dq_accepted_model(quality, _silver_model())

    for field in (
        "source_record_key",
        "rule_id",
        "rule_version",
        "category",
        "reason",
        "observed_value",
        "evidence",
        "quarantined_at",
        "source_system",
        "source_identity_ref",
        "source_updated_at",
        "source_effective_at",
        "ingested_at",
        "loaded_at",
        "source_class_uri",
    ):
        assert field in quarantine
    assert rule.result_model_name in quarantine
    assert "not exists" in accepted
    assert "entity__dq_input" in accepted


@pytest.mark.parametrize(
    ("kind", "expression"),
    (
        ("freshness", "column=updated_at;unit=hours"),
        ("volume", "metric=row-count"),
        ("duplicate-rate", "columns=business_id"),
        ("distribution", "column=status;allowed=A|B"),
        ("reconciliation", "compare_model=expected;metric=count"),
        (
            "referential-coverage",
            "column=parent_id;parent_model=parent;parent_column=parent_id",
        ),
    ),
)
def test_aggregate_dq_checks_render_namespaced_result_contracts(kind, expression):
    rule, _ = _quality_plan(kind, expression)
    rendered = render_dq_result(
        rule,
        adapter="databricks",
        adapter_version="1.0",
    )
    test_sql = render_dq_test(rule)

    assert f"kairos_dq_{kind.replace('-', '_')}" in rendered
    assert "observed_value" in rendered
    assert "affected_count" in rendered
    assert "monitoring remain" in rendered
    assert rule.result_model_name in test_sql


def test_runtime_result_schema_has_closed_status_and_required_semantics():
    fields = tuple(
        DqRuntimeFieldSpec(name, "string", False, name)
        for name in (
            "execution_timestamp",
            "run_id",
            "snapshot_id",
            "adapter_name",
            "adapter_version",
            "model_name",
            "rule_id",
            "rule_version",
            "rule_hash",
            "category",
            "status",
            "observed_value",
            "tolerance",
            "action",
            "affected_count",
            "quarantined_count",
            "reconciliation_values",
            "evidence",
            "evidence_uri",
        )
    )
    spec = DqRuntimeResultContractSpec(
        schema_version="1.0",
        relation_name="kairos_dq_runtime_results",
        fields=fields,
        statuses=tuple(DqResultStatus),
    )
    rendered = render_dq_runtime_contract(spec)

    assert '"pass"' in rendered
    assert '"fail"' in rendered
    assert '"error"' in rendered
    assert '"not-evaluated"' in rendered
    assert "monitoring, alerting, or trend storage" in rendered


def _baseline(**changes) -> ReleaseBaselineSpec:
    values = {
        "schema_version": "1.0",
        "policy_version": "1.0",
        "approval_status": "approved",
        "owner_role": "Release Owner",
        "reviewed_at": "2026-01-01",
        "expires_at": "2099-12-31",
        "required_adapters": (),
        "required_artifacts": (),
        "artifact_hashes": (),
        "block_warnings": False,
        "require_dq_runtime_results": False,
        "source_hash": "b" * 64,
    }
    values.update(changes)
    return ReleaseBaselineSpec(**values)


def _domain(adapter: str = "fabric") -> dict:
    content_hash = hashlib.sha256(b"select 1\n").hexdigest()
    parity_hash = hashlib.sha256(b'{"status":"pass"}\n').hexdigest()
    return {
        "policy_version": "1.0",
        "toolkit_version": "5.0",
        "ontology_version": "2.0",
        "closure_version": "c" * 64,
        "adapter": {"name": adapter, "version": "1.0"},
        "policy_issues": [],
        "blocking_reasons": [],
        "binding_status": {"status": "ready", "unbound_eligible": []},
        "coverage_status": {
            "status": "ready",
            "missing_required_mappings": [],
        },
        "gold_status": {
            "profile": None,
            "security": "not-applicable",
            "measures": "not-applicable",
            "calendar": "not-applicable",
        },
        "artifact_completeness": {"status": "ready", "missing": []},
        "generated_artifacts": [
            {"path": "model.sql", "sha256": content_hash},
            {
                "path": "metadata/domain-silver-parity.json",
                "sha256": parity_hash,
            },
        ],
        "parity_status": {
            "status": "pass",
            "required": True,
            "manifest_path": "metadata/domain-silver-parity.json",
            "manifest_sha256": parity_hash,
            "artifact_hashes": {"model.sql": content_hash},
            "errors": [],
        },
        "capabilities": [
            {
                "adapter": adapter,
                "capability": "canonical-types",
                "disposition": "supported",
                "rule_id": "DD-111-types",
                "scope": "project",
                "reason": "",
                "evidence": ["registry-v1"],
                "deviation_ref": None,
            }
        ],
        "adapter_compile_evidence": [
            {
                "resource_uri": f"urn:evidence:{adapter}",
                "adapter": adapter,
                "adapter_version": "1.0",
                "scope": "*",
                "capabilities": ["canonical-types"],
                "status": "supported",
                "compile_evidence": [f"compile:{adapter}:success"],
            }
        ],
        "deviations": [],
        "dq_rules": [],
    }


def _evaluate(
    domain: dict,
    *,
    baseline: ReleaseBaselineSpec | None = None,
    runtime_results: tuple[DqRuntimeObservation, ...] = (),
):
    return evaluate_release(
        ReleaseEvaluationInput(
            strict=True,
            generated_at="2026-07-25T12:00:00+00:00",
            toolkit_version="5.0",
            baseline_result=BaselineLoadResult(baseline or _baseline()),
            domains=(("domain", domain),),
            runtime_results=runtime_results,
        )
    )


@pytest.mark.parametrize("adapter", ("fabric", "databricks"))
def test_both_adapters_need_compile_evidence_not_registry_claims(adapter):
    domain = _domain(adapter)
    assert _evaluate(domain).release_ready

    domain["adapter_compile_evidence"] = []
    result = _evaluate(domain)
    assert not result.release_ready
    assert any(
        item.code == "release.adapter-compile-evidence"
        for item in result.blockers
    )


@pytest.mark.parametrize(
    "status",
    ("partial", "unsupported", "environment-blocked"),
)
def test_partial_unsupported_or_environment_blocked_evidence_blocks(status):
    domain = _domain()
    domain["adapter_compile_evidence"][0]["status"] = status
    assert not _evaluate(domain).release_ready


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("adapter", "databricks"),
        ("adapter_version", "2.0"),
        ("scope", "gold"),
        ("compile_evidence", []),
    ),
)
def test_compile_evidence_must_match_adapter_version_scope_and_be_nonempty(
    field,
    value,
):
    domain = _domain()
    domain["adapter_compile_evidence"][0][field] = value
    assert not _evaluate(domain).release_ready


def test_valid_deviation_is_reported_but_invalid_or_expired_blocks():
    domain = _domain()
    domain["capabilities"][0].update(
        disposition="deviation",
        deviation_ref="urn:deviation",
    )
    deviation = {
        "resource_uri": "urn:deviation",
        "adapter": "fabric",
        "policy_reference": "DD-111-types",
        "scope": "project",
        "rationale": "Reviewed bounded workaround.",
        "owner_role": "Platform Owner",
        "approval_status": "approved",
        "review_date": "2026-01-01",
        "expiry_date": "2099-12-31",
        "evidence": ["review:approved"],
    }
    domain["deviations"] = [deviation]
    valid = _evaluate(domain)
    assert valid.release_ready
    assert any(
        item.disposition is ReleaseDisposition.DEVIATION
        for item in valid.findings
    )

    for change in (
        {"approval_status": "proposed"},
        {"expiry_date": "2026-01-02"},
        {"adapter": "databricks"},
        {"scope": "gold"},
    ):
        invalid_domain = _domain()
        invalid_domain["capabilities"][0].update(
            disposition="deviation",
            deviation_ref="urn:deviation",
        )
        invalid_domain["deviations"] = [{**deviation, **change}]
        assert not _evaluate(invalid_domain).release_ready


def test_artifact_omission_and_hash_drift_block():
    domain = _domain()
    missing = _evaluate(
        domain,
        baseline=_baseline(required_artifacts=("domain:missing.sql",)),
    )
    assert any(item.code == "release.required-artifact-missing" for item in missing.blockers)

    drift = _evaluate(
        domain,
        baseline=_baseline(
            artifact_hashes=(("domain:model.sql", "0" * 64),),
        ),
    )
    assert any(item.code == "release.artifact-hash-drift" for item in drift.blockers)


@pytest.mark.parametrize(
    ("status", "runtime_required", "blocking"),
    (
        ("pass", True, False),
        ("fail", True, True),
        ("error", True, True),
        ("not-evaluated", True, True),
        ("not-evaluated", False, False),
    ),
)
def test_runtime_dq_status_semantics(status, runtime_required, blocking):
    domain = _domain()
    rule_hash = "d" * 64
    result_path = "models/quality/dq_result.sql"
    test_path = "tests/quality/test_dq_result.sql"
    for path in (result_path, test_path):
        domain["generated_artifacts"].append(
            {
                "path": path,
                "sha256": hashlib.sha256(path.encode("utf-8")).hexdigest(),
            }
        )
    domain["dq_rules"] = [
        {
            "rule_id": "dq.volume",
            "rule_version": "1",
            "rule_hash": rule_hash,
            "model_name": "entity",
            "category": "operational",
            "action": "block",
            "tolerance": {"kind": "count", "value": "1", "unit": ""},
            "evidence": ["policy:dq.volume"],
            "result_artifact": result_path,
            "test_artifact": test_path,
            "quarantine_artifact": None,
        }
    ]
    observation = DqRuntimeObservation(
        execution_timestamp="2026-07-25T11:00:00+00:00",
        run_id="run-1",
        model_name="entity",
        rule_id="dq.volume",
        rule_version="1",
        rule_hash=rule_hash,
        status=status,
        observed_value="0",
        tolerance="1",
        action="block",
        evidence="run:1",
    )
    result = _evaluate(
        domain,
        baseline=_baseline(
            require_dq_runtime_results=runtime_required,
        ),
        runtime_results=(observation,),
    )

    assert bool(result.blockers) is blocking


@pytest.mark.parametrize(
    ("surface", "code"),
    (
        ("binding_status", "release.binding-blocking"),
        ("coverage_status", "release.coverage-blocking"),
    ),
)
def test_binding_and_coverage_blockers(surface, code):
    domain = _domain()
    domain[surface]["status"] = "blocking"
    assert any(item.code == code for item in _evaluate(domain).blockers)


@pytest.mark.parametrize(
    "surface",
    ("tables", "security", "measures", "calendar", "adapter", "tmdl_compile"),
)
def test_gold_security_measure_and_calendar_blockers(surface):
    domain = _domain()
    domain["gold_status"].update(
        profile="dimensional-powerbi-v1",
        security="ready",
        measures="ready",
        calendar="ready",
        tables="ready",
        adapter="ready",
        tmdl_compile="ready",
    )
    domain["gold_status"][surface] = "blocking"
    assert any(
        item.code == f"release.{surface}-blocking"
        for item in _evaluate(domain).blockers
    )


def test_absent_optional_calendar_and_security_are_not_strict_blockers():
    domain = _domain()
    domain["gold_status"].update(
        profile="dimensional-powerbi-v1",
        tables="ready",
        measures="ready",
        calendar="not-applicable",
        security="not-applicable",
        adapter="ready",
        tmdl_compile="ready",
    )
    assert _evaluate(domain).release_ready


def test_release_manifest_is_deterministic_and_never_claims_monitoring():
    first = _evaluate(_domain())
    second = _evaluate(_domain())

    assert first.manifest == second.manifest
    assert first.report == second.report
    assert first.release_ready
    assert "monitoring" in first.report["monitoring_boundary"]
    assert "downstream" in first.report["monitoring_boundary"]


def test_strict_release_blocks_silver_parity_drift():
    domain = _domain()
    domain["parity_status"]["artifact_hashes"]["model.sql"] = "0" * 64

    result = _evaluate(domain)

    assert any(
        finding.code == "release.silver-parity-drift"
        for finding in result.blockers
    )


def test_cli_strict_release_error_exits_nonzero(tmp_path, monkeypatch):
    hub = tmp_path / "ontology-hub"
    (hub / "model" / "ontologies").mkdir(parents=True)
    (hub / "model" / "ontologies" / "domain.ttl").write_text(
        "<urn:domain> a <http://www.w3.org/2002/07/owl#Ontology> .\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(hub)

    def blocked(**_kwargs):
        raise ProjectionRunError("Strict release blocked: DD-114-baseline")

    monkeypatch.setattr(
        "kairos_ontology.cli.main.run_projections",
        blocked,
    )
    result = CliRunner().invoke(cli, ["project", "--target", "dbt", "--strict"])

    assert result.exit_code != 0
    assert "Strict release blocked" in result.output


def test_quality_phase_specs_are_frozen_and_slotted():
    for record in (
        DqRulePhysicalPlan,
        DqModelPhysicalPlan,
        ReleaseBaselineSpec,
        ReleaseEvaluationInput,
    ):
        assert dataclasses.is_dataclass(record)
        assert record.__dataclass_params__.frozen
        assert "__slots__" in record.__dict__
