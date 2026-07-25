# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Adapter-specific rendering for immutable source-preparation specifications."""

from __future__ import annotations

import re
from collections.abc import Iterable

import yaml

from .policy_specs import TechnicalDedupeMode
from .specs import (
    PrepArrayChildModelSpec,
    PrepModelPhysicalPlan,
    PrepModelSpec,
    PrepSchemaPhysicalPlan,
)


def _quote(adapter: str, name: str) -> str:
    if adapter == "fabric":
        return f"[{name.replace(']', ']]')}]"
    if adapter == "databricks":
        return f"`{name.replace('`', '``')}`"
    raise ValueError(f"Unsupported preparation adapter {adapter!r}")


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _type(plan: PrepModelPhysicalPlan, name: str) -> str:
    return dict(plan.column_types)[name]


def _cleanup(expression: str, operation: str, adapter: str) -> str:
    if operation == "trim":
        return f"TRIM({expression})"
    if operation == "left-trim":
        return f"LTRIM({expression})"
    if operation == "right-trim":
        return f"RTRIM({expression})"
    if operation == "line-ending-normalize":
        if adapter == "fabric":
            return (
                f"REPLACE(REPLACE({expression}, CHAR(13) + CHAR(10), CHAR(10)), CHAR(13), CHAR(10))"
            )
        return rf"REGEXP_REPLACE({expression}, '\\r\\n?', '\\n')"
    raise ValueError(f"Unsupported cleanup operation {operation!r}")


def _text_expression(expression: str, adapter: str) -> str:
    target = "VARCHAR(8000)" if adapter == "fabric" else "STRING"
    return f"CAST({expression} AS {target})"


def _lexical_predicate(expression: str, policy: str, adapter: str) -> str:
    text = _text_expression(expression, adapter)
    if policy == "strict-text":
        return f"{expression} IS NOT NULL"
    if policy == "boolean-canonical":
        if adapter == "fabric":
            return (
                f"{text} COLLATE Latin1_General_100_BIN2 "
                "IN ('true' COLLATE Latin1_General_100_BIN2, "
                "'false' COLLATE Latin1_General_100_BIN2)"
            )
        return f"{text} IN ('true', 'false')"
    if policy not in {"integer-lexical", "decimal-invariant"}:
        raise ValueError(f"Unsupported parse policy {policy!r}")
    if adapter == "databricks":
        pattern = (
            r"^[+-]?[0-9]+$"
            if policy == "integer-lexical"
            else r"^[+-]?[0-9]+(?:\.[0-9]+)?$"
        )
        return f"{text} RLIKE {_literal(pattern)}"

    unsigned = (
        f"CASE WHEN LEFT({text}, 1) IN ('+', '-') "
        f"THEN SUBSTRING({text}, 2, 8000) ELSE {text} END"
    )
    if policy == "integer-lexical":
        return f"{unsigned} <> '' AND {unsigned} NOT LIKE '%[^0-9]%'"
    if policy == "decimal-invariant":
        return (
            f"{unsigned} <> '' AND {unsigned} NOT LIKE '%[^0-9.]%' "
            f"AND {unsigned} NOT LIKE '%.%.%' "
            f"AND {unsigned} NOT LIKE '.%' AND {unsigned} NOT LIKE '%.'"
        )
    raise AssertionError("unreachable parse policy")


def _parsed_expression(expression: str, target_type: str, policy: str, adapter: str) -> str:
    text = _text_expression(expression, adapter)
    if policy == "boolean-canonical":
        true_value, false_value = (
            ("CAST(1 AS BIT)", "CAST(0 AS BIT)")
            if adapter == "fabric"
            else ("CAST(TRUE AS BOOLEAN)", "CAST(FALSE AS BOOLEAN)")
        )
        return f"CASE WHEN {text} = 'true' THEN {true_value} ELSE {false_value} END"
    return f"CAST({expression} AS {target_type})"


def _conversion_expression(
    expression: str,
    target_type: str,
    policy: str,
    error_action: str,
    adapter: str,
) -> tuple[str, str]:
    lexical = _lexical_predicate(expression, policy, adapter)
    parsed = _parsed_expression(expression, target_type, policy, adapter)
    castable = (
        lexical
        if policy in {"strict-text", "boolean-canonical"}
        else f"({lexical}) AND TRY_CAST({expression} AS {target_type}) IS NOT NULL"
    )
    if error_action == "fail":
        invalid = (
            f"CAST(CAST({_literal(f'__kairos_invalid_{policy}__')} AS BIGINT) "
            f"AS {target_type})"
            if adapter == "fabric"
            else f"CAST(RAISE_ERROR({_literal(f'Invalid {policy} lexical value')}) "
            f"AS {target_type})"
        )
    elif error_action == "null-with-evidence":
        invalid = f"CAST(NULL AS {target_type})"
    else:  # pragma: no cover - capability negotiation blocks quarantine rendering
        raise ValueError(f"Unsupported parse error action {error_action!r}")
    converted = (
        f"CASE WHEN {expression} IS NULL THEN CAST(NULL AS {target_type}) "
        f"WHEN {castable} THEN {parsed} ELSE {invalid} END"
    )
    invalid_predicate = f"{expression} IS NOT NULL AND NOT ({castable})"
    return converted, invalid_predicate


def _column_expressions(
    spec: PrepModelSpec,
    plan: PrepModelPhysicalPlan,
    adapter: str,
) -> tuple[list[tuple[str, str]], dict[str, str]]:
    selected: list[tuple[str, str]] = []
    source_by_output: dict[str, str] = {}
    for column in spec.columns:
        raw = f"{spec.source_alias}.{_quote(adapter, column.source_name)}"
        expression = raw
        for sentinel in column.sentinel_rules:
            replacement = (
                "NULL"
                if sentinel.action.value.value == "to-null"
                else _literal(sentinel.normalized_value.value)
            )
            expression = (
                f"CASE WHEN {expression} = {_literal(sentinel.sentinel_value.value)} "
                f"THEN {replacement} ELSE {expression} END"
            )
        for cleanup in column.cleanup_rules:
            expression = _cleanup(
                expression,
                cleanup.operation.value.value,
                adapter,
            )
        pre_cast = expression
        invalid_predicate = ""
        if column.conversion is not None:
            target_type = _type(plan, column.output_name)
            expression, invalid_predicate = _conversion_expression(
                pre_cast,
                target_type,
                column.conversion.parse_policy.value,
                column.conversion.error_action.value.value,
                adapter,
            )
        selected.append((expression, column.output_name))
        source_by_output[column.output_name] = raw
        if column.raw_output_name:
            selected.append((raw, column.raw_output_name))
        if column.error_flag_name:
            selected.append(
                (
                    f"CASE WHEN {invalid_predicate} THEN 1 ELSE 0 END",
                    column.error_flag_name,
                )
            )
    return selected, source_by_output


def _cdc_expression(
    field,
    source_by_output: dict[str, str],
    target_type: str,
) -> str:
    raw = [source_by_output[name] for name in field.source_columns]
    value = raw[0] if len(raw) == 1 else f"COALESCE({', '.join(raw)})"
    if field.role == "operation" and field.operation_code_map:
        explicit = [
            (source, target)
            for source, target in field.operation_code_map
            if source != "*"
        ]
        fallback = next(
            (
                target
                for source, target in field.operation_code_map
                if source == "*"
            ),
            None,
        )
        branches = " ".join(
            f"WHEN {value} = {_literal(source)} THEN {_literal(target)}"
            for source, target in explicit
        )
        if fallback is not None and not explicit:
            value = _literal(fallback)
        elif fallback is not None:
            value = f"CASE {branches} ELSE {_literal(fallback)} END"
        else:
            value = f"CASE {branches} ELSE NULL END"
    return f"CAST({value} AS {target_type})"


def _scalar_expression(
    field,
    source_by_output: dict[str, str],
    target_type: str,
    adapter: str,
) -> tuple[str, str]:
    raw = source_by_output[field.source_column]
    extracted = (
        f"JSON_VALUE({raw}, {_literal(field.json_path)})"
        if adapter == "fabric"
        else f"GET_JSON_OBJECT({raw}, {_literal(field.json_path)})"
    )
    cast_name = "CAST" if field.error_action.value == "fail" else "TRY_CAST"
    return f"{cast_name}({extracted} AS {target_type})", extracted


def _select_lines(values: Iterable[tuple[str, str]], *, indent: str = "        ") -> str:
    items = list(values)
    return ",\n".join(f"{indent}{expression} AS {name}" for expression, name in items)


def render_prep_model(
    spec: PrepModelSpec,
    plan: PrepModelPhysicalPlan,
    adapter: str,
) -> str:
    """Render one normalized physical source table."""
    values, source_by_output = _column_expressions(spec, plan, adapter)
    for cdc in spec.cdc_columns:
        values.append(
            (
                _cdc_expression(
                    cdc,
                    source_by_output,
                    _type(plan, cdc.output_name),
                ),
                cdc.output_name,
            )
        )
    for scalar in spec.scalar_columns:
        expression, extracted = _scalar_expression(
            scalar,
            source_by_output,
            _type(plan, scalar.output_name),
            adapter,
        )
        values.append((expression, scalar.output_name))
        if scalar.error_flag_name:
            values.append(
                (
                    "CASE WHEN "
                    f"{source_by_output[scalar.source_column]} IS NOT NULL AND "
                    f"{extracted} IS NULL THEN 1 ELSE 0 END",
                    scalar.error_flag_name,
                )
            )

    key_arguments = [
        repr(f"'{spec.source_record_key.source_scope}'"),
        repr(f"'{spec.source_record_key.table_scope}'"),
        *(
            repr(f"normalized.{_quote(adapter, component)}")
            for component in spec.source_record_key.component_columns
        ),
    ]
    key_expression = "{{ dbt_utils.generate_surrogate_key([" + ", ".join(key_arguments) + "]) }}"
    final_names = [name for name, _ in plan.column_types]
    prepared_values = [
        (
            f"normalized.{_quote(adapter, name)}",
            name,
        )
        for name in final_names
        if name != spec.source_record_key.output_name
    ]
    prepared_values.append((key_expression, spec.source_record_key.output_name))
    source_ref = (
        f"{{{{ source({_literal(spec.source_name)}, {_literal(spec.source_table_name)}) }}}}"
    )
    cast_policy_comments = [
        (
            f"-- Cast policy {column.source_name} -> {column.output_name}: "
            f"parser={column.conversion.parse_policy.value}; "
            f"errors={column.conversion.error_action.value.value}"
        )
        for column in spec.columns
        if column.conversion is not None
    ]
    sql = [
        f"-- Source preparation model: {spec.model_name}",
        "-- Generated from the mandatory DD-106 preparation policy.",
        *cast_policy_comments,
        "{{ config(materialized='view', schema='staging') }}",
        "",
        "WITH normalized AS (",
        "    SELECT",
        _select_lines(values),
        f"    FROM {source_ref} AS {spec.source_alias}",
        "),",
        "prepared AS (",
        "    SELECT",
        _select_lines(prepared_values),
        "    FROM normalized",
        ")",
    ]

    if spec.technical_dedupe.mode.value is TechnicalDedupeMode.COMPLETE_TOTAL_ORDER:
        raw_to_output = {column.source_name: column.output_name for column in spec.columns}
        keys = [raw_to_output.get(name, name) for name in spec.technical_dedupe.keys.value]
        order = []
        for term in spec.technical_dedupe.total_order.value:
            match = re.fullmatch(
                r"([A-Za-z_][A-Za-z0-9_]*)(?:\s+(ASC|DESC))?",
                term,
                re.I,
            )
            assert match is not None
            name, direction = match.groups()
            order.append(
                f"{_quote(adapter, raw_to_output.get(name, name))} {(direction or 'ASC').upper()}"
            )
        sql[-1] += ","
        sql.extend(
            [
                "ranked AS (",
                "    SELECT",
                "        prepared.*,",
                "        ROW_NUMBER() OVER (",
                "            PARTITION BY " + ", ".join(_quote(adapter, name) for name in keys),
                "            ORDER BY " + ", ".join(order),
                "        ) AS _prep_row_number",
                "    FROM prepared",
                ")",
                "SELECT",
                ",\n".join(f"    {_quote(adapter, name)}" for name in final_names),
                "FROM ranked",
                "WHERE _prep_row_number = 1",
            ]
        )
    else:
        sql.extend(
            [
                "SELECT",
                ",\n".join(f"    {_quote(adapter, name)}" for name in final_names),
                "FROM prepared",
            ]
        )
    return "\n".join(sql) + "\n"


def render_prep_array_child(
    spec: PrepArrayChildModelSpec,
    plan: PrepModelPhysicalPlan,
    adapter: str,
) -> str:
    """Render an explicit JSON array child without changing parent grain."""
    parent = "parent"
    json_column = f"{parent}.{_quote(adapter, spec.source_json_column)}"
    values: list[tuple[str, str]] = [
        (
            f"{parent}.{_quote(adapter, '_source_record_key')}",
            "_source_record_key",
        )
    ]
    values.extend(
        (
            f"{parent}.{_quote(adapter, name)}",
            name,
        )
        for name in spec.parent_key_columns
        if name != "_source_record_key"
    )
    if adapter == "fabric":
        element_value = f"element.{_quote(adapter, 'value')}"
        index_value = f"element.{_quote(adapter, 'key')}"
        expansion = (
            f"    CROSS APPLY OPENJSON({json_column}, {_literal(spec.json_path)}) AS element"
        )
    elif adapter == "databricks":
        element_value = "TO_JSON(_array_element)"
        index_value = "_array_index"
        expansion = (
            "    LATERAL VIEW POSEXPLODE(FROM_JSON("
            f"GET_JSON_OBJECT({json_column}, {_literal(spec.json_path)}), "
            "'ARRAY<MAP<STRING,STRING>>')) exploded "
            "AS _array_index, _array_element"
        )
    else:  # pragma: no cover - guarded by adapter negotiation
        raise ValueError(f"Unsupported preparation adapter {adapter!r}")

    def extract(path: str) -> str:
        if adapter == "fabric":
            return f"JSON_VALUE({element_value}, {_literal(path)})"
        return f"GET_JSON_OBJECT({element_value}, {_literal(path)})"

    if spec.element_index_column:
        values.append(
            (
                f"CAST({index_value} AS {_type(plan, spec.element_index_column)})",
                spec.element_index_column,
            )
        )
    else:
        values.append((extract(spec.element_key_path), "_element_key"))
    values.extend(
        (
            f"CAST({extract(column.json_path)} AS {_type(plan, column.name)})",
            column.name,
        )
        for column in spec.columns
    )
    if spec.retention.value == "retain-payload":
        values.append((element_value, "_raw_payload"))

    parent_ref = "{{ ref(" + _literal(spec.parent_model_name) + ") }}"
    return "\n".join(
        [
            f"-- Source preparation array child: {spec.model_name}",
            "-- Null and empty arrays produce zero child rows; parent grain is unchanged.",
            "{{ config(materialized='view', schema='staging') }}",
            "",
            "SELECT",
            _select_lines(values, indent="    "),
            f"FROM {parent_ref} AS {parent}",
            expansion,
            "",
        ]
    )


def _column_document(name: str, data_type: str, tests: list[object]) -> dict:
    result: dict[str, object] = {
        "name": name,
        "data_type": data_type,
        "description": f"Prepared column {name}.",
    }
    if tests:
        result["data_tests"] = tests
    return result


def render_prep_schema(
    models: tuple[PrepModelSpec, ...],
    children: tuple[PrepArrayChildModelSpec, ...],
    plans: tuple[PrepModelPhysicalPlan, ...],
    document: PrepSchemaPhysicalPlan,
) -> str:
    """Render contracts and tests from the same prep model specifications."""
    model_by_name = {item.model_name: item for item in models}
    child_by_name = {item.model_name: item for item in children}
    plan_by_name = {item.model_name: item for item in plans}
    rendered_models: list[dict] = []
    for name in document.model_names:
        plan = plan_by_name[name]
        columns = []
        if name in model_by_name:
            spec = model_by_name[name]
            not_null = {column.output_name for column in spec.columns if not column.nullable}
            not_null.add(spec.source_record_key.output_name)
            error_flags = {
                column.error_flag_name for column in spec.columns if column.error_flag_name
            } | {scalar.error_flag_name for scalar in spec.scalar_columns if scalar.error_flag_name}
            for column_name, data_type in plan.column_types:
                tests: list[object] = []
                if column_name in not_null:
                    tests.append("not_null")
                if column_name == spec.source_record_key.output_name:
                    tests.append("unique")
                if column_name in error_flags:
                    tests.append({"accepted_values": {"values": [0, 1]}})
                columns.append(_column_document(column_name, data_type, tests))
            model_tests: list[object] = []
            if spec.technical_dedupe.mode.value is TechnicalDedupeMode.COMPLETE_TOTAL_ORDER:
                raw_to_output = {column.source_name: column.output_name for column in spec.columns}
                model_tests.append(
                    {
                        "dbt_utils.unique_combination_of_columns": {
                            "combination_of_columns": [
                                raw_to_output.get(item, item)
                                for item in spec.technical_dedupe.keys.value
                            ]
                        }
                    }
                )
        else:
            child = child_by_name[name]
            key_name = child.element_index_column or "_element_key"
            key_columns = ["_source_record_key", key_name]
            for column_name, data_type in plan.column_types:
                tests = ["not_null"] if column_name in key_columns else []
                columns.append(_column_document(column_name, data_type, tests))
            model_tests = [
                {"dbt_utils.unique_combination_of_columns": {"combination_of_columns": key_columns}}
            ]
        model_document = {
            "name": name,
            "description": "Governed DD-106 source preparation model.",
            "config": {"contract": {"enforced": True}},
            "columns": columns,
        }
        if model_tests:
            model_document["data_tests"] = model_tests
        rendered_models.append(model_document)
    return yaml.safe_dump(
        {"version": 2, "models": rendered_models},
        sort_keys=False,
        allow_unicode=True,
        width=1000,
    )
