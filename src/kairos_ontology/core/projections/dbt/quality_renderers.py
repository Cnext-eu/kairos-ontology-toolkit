# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Render executable DD-115 DQ contracts from immutable physical plans."""

from __future__ import annotations

from ...adapters import FABRIC_WAREHOUSE

import json

from .policy_specs import (
    DqAction,
    DqCheckKind,
    DqRuntimeResultContractSpec,
)
from .specs import DqModelPhysicalPlan, DqRulePhysicalPlan, SilverModelSpec


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _parameters(plan: DqRulePhysicalPlan) -> dict[str, tuple[str, ...]]:
    return {item.name: item.values for item in plan.rule.check.parameters}


def _macro_call(plan: DqRulePhysicalPlan) -> str:
    kind = plan.rule.check.check_kind.value
    params = _parameters(plan)
    arguments = [
        f"model=ref({_literal(plan.evaluated_model_name)})",
        f"tolerance={plan.rule.tolerance.value.value}",
    ]
    if kind is DqCheckKind.CONTRACT_SHAPE:
        arguments.append(f"required_columns={list(params['required'])!r}")
    elif kind is DqCheckKind.FRESHNESS:
        arguments.extend(
            (
                f"column={_literal(params['column'][0])}",
                f"unit={_literal(params['unit'][0])}",
            )
        )
    elif kind is DqCheckKind.DUPLICATE_RATE:
        arguments.append(f"columns={list(params['columns'])!r}")
    elif kind is DqCheckKind.RANGE:
        arguments.extend(
            (
                f"column={_literal(params['column'][0])}",
                f"minimum={params.get('minimum', ('none',))[0]}",
                f"maximum={params.get('maximum', ('none',))[0]}",
            )
        )
    elif kind is DqCheckKind.DISTRIBUTION:
        arguments.extend(
            (
                f"column={_literal(params['column'][0])}",
                f"allowed_values={list(params['allowed'])!r}",
            )
        )
    elif kind is DqCheckKind.RECONCILIATION:
        arguments.extend(
            (
                f"compare_model=ref({_literal(params['compare_model'][0])})",
                f"metric={_literal(params['metric'][0])}",
            )
        )
        if "column" in params:
            arguments.append(f"column={_literal(params['column'][0])}")
            arguments.append(f"compare_column={_literal(params['compare_column'][0])}")
    elif kind is DqCheckKind.REFERENTIAL_COVERAGE:
        arguments.extend(
            (
                f"column={_literal(params['column'][0])}",
                f"parent_model=ref({_literal(params['parent_model'][0])})",
                f"parent_column={_literal(params['parent_column'][0])}",
            )
        )
    elif kind is DqCheckKind.CROSS_FIELD:
        arguments.extend(
            (
                f"left={_literal(params['left'][0])}",
                f"operator={_literal(params['operator'][0])}",
                f"right={_literal(params['right'][0])}",
            )
        )
    rendered = ",\n    ".join(arguments)
    macro = kind.value.replace("-", "_")
    return f"{{{{ kairos_dq_{macro}(\n    {rendered}\n) }}}}"


def render_dq_result(
    plan: DqRulePhysicalPlan,
    *,
    adapter: str,
    adapter_version: str,
) -> str:
    """Render one persistent downstream result relation; no result is fabricated."""
    rule = plan.rule
    evidence = "|".join(rule.evidence.value)
    text_type = "VARCHAR(8000)" if adapter == FABRIC_WAREHOUSE else "STRING"
    return (
        f"-- DD-115 executable result contract for {rule.rule_id.value}.\n"
        "-- The toolkit emits this contract; execution and monitoring remain downstream.\n"
        "{{ config(materialized='table', schema='quality') }}\n\n"
        "with evaluated as (\n"
        f"{_macro_call(plan)}\n"
        ")\n"
        "select\n"
        "    {{ kairos_current_timestamp() }} as execution_timestamp,\n"
        "    '{{ invocation_id }}' as run_id,\n"
        f"    cast(null as {text_type}) as snapshot_id,\n"
        f"    {_literal(adapter)} as adapter_name,\n"
        f"    {_literal(adapter_version)} as adapter_version,\n"
        f"    {_literal(plan.target_model_name)} as model_name,\n"
        f"    {_literal(rule.rule_id.value)} as rule_id,\n"
        f"    {_literal(rule.version.value)} as rule_version,\n"
        f"    {_literal(rule.rule_hash)} as rule_hash,\n"
        f"    {_literal(rule.category.value.value)} as category,\n"
        "    evaluated.status,\n"
        "    evaluated.observed_value,\n"
        f"    {_literal(rule.tolerance.value.value)} as tolerance,\n"
        f"    {_literal(rule.action.value.value)} as action,\n"
        "    evaluated.affected_count,\n"
        "    case when evaluated.status = 'fail'\n"
        f"              and {_literal(rule.action.value.value)} = 'quarantine'\n"
        "         then evaluated.affected_count else 0 end as quarantined_count,\n"
        "    evaluated.reconciliation_values,\n"
        f"    {_literal(evidence)} as evidence,\n"
        f"    cast(null as {text_type}) as evidence_uri\n"
        "from evaluated\n"
    )


def render_dq_test(plan: DqRulePhysicalPlan) -> str:
    """Render a singular dbt test over the persistent DQ result relation."""
    severity = "error" if plan.rule.action.value is DqAction.BLOCK else "warn"
    return (
        f"-- DD-115 test for {plan.rule.rule_id.value}; "
        "monitoring and alert delivery are downstream.\n"
        f"{{{{ config(severity={_literal(severity)}, "
        f"tags=['kairos-dq', {_literal(plan.rule.category.value.value)}]) }}}}\n\n"
        "select *\n"
        f"from {{{{ ref({_literal(plan.result_model_name)}) }}}}\n"
        "where status in ('fail', 'error', 'not-evaluated')\n"
    )


def _quoted(alias: str, column: str) -> str:
    return f"{alias}.{{{{ adapter.quote({_literal(column)}) }}}}"


def _row_predicate(plan: DqRulePhysicalPlan, alias: str = "source") -> str:
    kind = plan.rule.check.check_kind.value
    params = _parameters(plan)
    if kind is DqCheckKind.CONTRACT_SHAPE:
        return " or ".join(f"{_quoted(alias, column)} is null" for column in params["required"])
    if kind is DqCheckKind.RANGE:
        column = _quoted(alias, params["column"][0])
        conditions = []
        if "minimum" in params:
            conditions.append(f"{column} < {params['minimum'][0]}")
        if "maximum" in params:
            conditions.append(f"{column} > {params['maximum'][0]}")
        return " or ".join(conditions)
    if kind is DqCheckKind.DISTRIBUTION:
        column = _quoted(alias, params["column"][0])
        allowed = ", ".join(_literal(item) for item in params["allowed"])
        return f"{column} is null or {column} not in ({allowed})"
    if kind is DqCheckKind.REFERENTIAL_COVERAGE:
        column = _quoted(alias, params["column"][0])
        parent = params["parent_model"][0]
        parent_column = _quoted("parent", params["parent_column"][0])
        return (
            f"{column} is null or not exists (\n"
            "            select 1\n"
            f"            from {{{{ ref({_literal(parent)}) }}}} parent\n"
            f"            where {parent_column} = {column}\n"
            "        )"
        )
    if kind is DqCheckKind.CROSS_FIELD:
        left = _quoted(alias, params["left"][0])
        right = _quoted(alias, params["right"][0])
        operator = params["operator"][0]
        if operator == "eq":
            return f"not (({left} = {right}) or ({left} is null and {right} is null))"
        if operator == "ne":
            return f"(({left} = {right}) or ({left} is null and {right} is null))"
        sql_operator = {"lt": "<", "lte": "<=", "gt": ">", "gte": ">="}[operator]
        return f"{left} is null or {right} is null or not ({left} {sql_operator} {right})"
    raise ValueError(f"DQ rule {plan.rule.rule_id.value!r} has no row-level predicate")


def _observed_value(
    plan: DqRulePhysicalPlan,
    *,
    adapter: str,
) -> tuple[str, str]:
    params = _parameters(plan)
    text_type = "VARCHAR(8000)" if adapter == FABRIC_WAREHOUSE else "STRING"
    fields = (
        params.get("left", ()) + params.get("right", ())
        if plan.rule.check.check_kind.value is DqCheckKind.CROSS_FIELD
        else (params.get("required") or params.get("columns") or params.get("column") or ())
    )
    if not fields:
        return f"cast(null as {text_type})", ""
    first = fields[0]
    return f"cast({_quoted('source', first)} as {text_type})", ",".join(fields)


def render_dq_accepted_model(
    quality: DqModelPhysicalPlan,
    model: SilverModelSpec,
) -> str:
    """Render the normal relation from rows that did not enter quarantine."""
    quarantine_rules = tuple(
        rule for rule in quality.rules if rule.rule.action.value is DqAction.QUARANTINE
    )
    guards = []
    for rule in quarantine_rules:
        predicate = _row_predicate(rule)
        guards.append(
            "not exists (\n"
            "        select 1\n"
            f"        from {{{{ ref({_literal(rule.result_model_name)}) }}}} result\n"
            "        where result.status = 'fail'\n"
            f"          and ({predicate})\n"
            "    )"
        )
    where = "\n  and ".join(guards) if guards else "1 = 1"
    return (
        f"-- DD-115 passing rows for {quality.model_name}; rejected rows remain explicit.\n"
        "{{ config(\n"
        "    materialized='view',\n"
        f"    schema={_literal(model.identity.schema_name)}\n"
        ") }}\n\n"
        "select source.*\n"
        f"from {{{{ ref({_literal(quality.evaluated_model_name)}) }}}} source\n"
        f"where {where}\n"
    )


def _column_or_null(
    columns: frozenset[str],
    name: str,
    *,
    adapter: str,
) -> str:
    if name in columns:
        return _quoted("source", name)
    timestamp_type = "DATETIME2(6)" if adapter == FABRIC_WAREHOUSE else "TIMESTAMP"
    return f"cast(null as {timestamp_type})"


def render_dq_quarantine(
    quality: DqModelPhysicalPlan,
    model: SilverModelSpec,
    *,
    adapter: str,
) -> str:
    """Render an explicit immutable-lineage reject relation for row-level failures."""
    columns = frozenset(column.name for column in model.columns)
    selections = []
    for plan in quality.rules:
        rule = plan.rule
        if rule.action.value is not DqAction.QUARANTINE:
            continue
        observed, observed_fields = _observed_value(plan, adapter=adapter)
        evidence = "|".join(rule.evidence.value)
        reason = (
            f"{rule.check.check_kind.value.value} exceeded tolerance {rule.tolerance.value.value}"
        )
        predicate = _row_predicate(plan)
        selections.append(
            "select\n"
            "    source.{{ adapter.quote('_source_record_key') }} "
            "as source_record_key,\n"
            f"    {_literal(rule.rule_id.value)} as rule_id,\n"
            f"    {_literal(rule.version.value)} as rule_version,\n"
            f"    {_literal(rule.rule_hash)} as rule_hash,\n"
            f"    {_literal(rule.category.value.value)} as category,\n"
            f"    {_literal(reason)} as reason,\n"
            f"    {observed} as observed_value,\n"
            f"    {_literal(observed_fields)} as observed_fields,\n"
            f"    {_literal(rule.tolerance.value.value)} as tolerance,\n"
            f"    {_literal(rule.severity.value.value)} as severity,\n"
            f"    {_literal(rule.action.value.value)} as action,\n"
            f"    {_literal(rule.owner_role.value)} as owner_role,\n"
            f"    {_literal(evidence)} as evidence,\n"
            "    {{ kairos_current_timestamp() }} as quarantined_at,\n"
            "    source.{{ adapter.quote('_source_system') }} as source_system,\n"
            "    source.{{ adapter.quote('_source_identity_ref') }} "
            "as source_identity_ref,\n"
            f"    {_column_or_null(columns, '_source_updated_at', adapter=adapter)} "
            "as source_updated_at,\n"
            f"    {_column_or_null(columns, '_source_effective_at', adapter=adapter)} "
            "as source_effective_at,\n"
            f"    {_column_or_null(columns, '_ingested_at', adapter=adapter)} "
            "as ingested_at,\n"
            f"    {_column_or_null(columns, '_loaded_at', adapter=adapter)} "
            "as loaded_at,\n"
            f"    {_literal(quality.evaluated_model_name)} as source_model,\n"
            f"    {_literal(model.identity.class_uri)} as source_class_uri\n"
            f"from {{{{ ref({_literal(quality.evaluated_model_name)}) }}}} source\n"
            f"cross join {{{{ ref({_literal(plan.result_model_name)}) }}}} result\n"
            "where result.status = 'fail'\n"
            f"  and ({predicate})"
        )
    return (
        f"-- DD-115 explicit quarantine relation for {quality.model_name}.\n"
        "-- Rows retain immutable source lineage and are excluded from the normal model.\n"
        "{{ config(materialized='table', schema='quality') }}\n\n"
        + "\nunion all\n".join(selections)
        + "\n"
    )


def render_dq_runtime_contract(spec: DqRuntimeResultContractSpec) -> str:
    """Render the portable schema for immutable downstream runtime observations."""
    properties = {
        field.name: {
            "description": field.description,
            "type": (
                [
                    "integer" if field.data_type == "integer" else "string",
                    "null",
                ]
                if field.nullable
                else ("integer" if field.data_type == "integer" else "string")
            ),
            "x-kairos-data-type": field.data_type,
        }
        for field in spec.fields
    }
    for field in spec.fields:
        if field.data_type == "timestamp":
            properties[field.name]["format"] = "date-time"
    properties["status"]["enum"] = [status.value for status in spec.statuses]
    payload = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://kairos.cnext.eu/contracts/dq-runtime-result/v1",
        "additionalProperties": False,
        "description": (
            "Immutable downstream DQ observations. Kairos generates executable "
            "contracts but does not operate monitoring, alerting, or trend storage."
        ),
        "properties": properties,
        "required": [field.name for field in spec.fields if not field.nullable],
        "title": spec.relation_name,
        "type": "object",
        "version": spec.schema_version,
        "x-kairos-immutable-imported-evidence": spec.immutable_imported_evidence,
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"
