# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Adapter-specific SQL rendering exclusively from validated DD-107 AST nodes."""

from __future__ import annotations

from .capabilities import physical_canonical_type
from .mapping_specs import (
    CaseExpression,
    FunctionExpression,
    LiteralExpression,
    MacroExpression,
    MAX_MAPPING_AST_DEPTH,
    MappingContractError,
    MappingExpression,
    NullExpression,
    OperatorExpression,
    SourceColumnExpression,
)
from .policy_specs import AdapterName, CanonicalTypeKind
from .specs import JoinSpec, SourceBindingSpec


_BINARY_OPERATORS = {
    "add": "+",
    "subtract": "-",
    "multiply": "*",
    "divide": "/",
    "modulo": "%",
    "equal": "=",
    "not-equal": "<>",
    "less-than": "<",
    "less-or-equal": "<=",
    "greater-than": ">",
    "greater-or-equal": ">=",
    "and": "AND",
    "or": "OR",
}


def _error(expression: MappingExpression, message: str) -> MappingContractError:
    return MappingContractError(
        "mapping.render-blocked",
        message,
        resource_uri=expression.metadata.provenance.expression_resource_uri,
        rule_id="DD-107-render",
    )


def quote_mapping_identifier(value: str, adapter: str) -> str:
    if "\x00" in value or not value:
        raise ValueError("SQL identifiers must be non-empty and contain no NUL")
    if adapter == "fabric":
        return f"[{value.replace(']', ']]')}]"
    if adapter == "databricks":
        return f"`{value.replace('`', '``')}`"
    raise ValueError(f"unsupported mapping adapter {adapter!r}")


def _physical_type(expression: MappingExpression, adapter: str) -> str:
    return physical_canonical_type(
        AdapterName(adapter),
        expression.metadata.output_type,
    )


def _text_literal(lexical: str, adapter: str) -> str:
    """Encode authored text as data so parser escape rules cannot reinterpret it."""

    if adapter == "fabric":
        payload = lexical.encode("utf-8").hex().upper()
        return (
            f"CONVERT(VARCHAR(8000), 0x{payload})"
            if payload
            else "CAST('' AS VARCHAR(8000))"
        )
    if adapter == "databricks":
        payload = lexical.encode("utf-8").hex().upper()
        return f"decode(unhex('{payload}'), 'UTF-8')"
    raise ValueError(f"unsupported mapping adapter {adapter!r}")


def _source_alias(
    expression: SourceColumnExpression,
    sources: tuple[SourceBindingSpec, ...],
) -> str:
    matches = tuple(
        source.alias
        for source in sources
        if source.table_uri == expression.input.source_table_uri
    )
    if len(matches) != 1:
        raise _error(
            expression,
            (
                f"source input {expression.input.source_column_uri!r} does not bind "
                "to exactly one model source"
            ),
        )
    return matches[0]


def _literal(expression: LiteralExpression, adapter: str) -> str:
    kind = expression.metadata.output_type.kind
    lexical = expression.lexical
    if kind is CanonicalTypeKind.STRING:
        return _text_literal(lexical, adapter)
    if kind is CanonicalTypeKind.BOOLEAN:
        truthy = lexical in {"true", "1"}
        return (
            f"CAST({1 if truthy else 0} AS BIT)"
            if adapter == "fabric"
            else "TRUE"
            if truthy
            else "FALSE"
        )
    if kind in {
        CanonicalTypeKind.INT16,
        CanonicalTypeKind.INT32,
        CanonicalTypeKind.INT64,
        CanonicalTypeKind.DECIMAL,
        CanonicalTypeKind.FLOAT64,
    }:
        return lexical
    if kind in {
        CanonicalTypeKind.DATE,
        CanonicalTypeKind.TIME,
        CanonicalTypeKind.TIMESTAMP,
    }:
        return (
            f"CAST({_text_literal(lexical, adapter)} "
            f"AS {_physical_type(expression, adapter)})"
        )
    raise _error(
        expression,
        f"typed literals of kind {kind.value!r} have no portable renderer",
    )


def _render(
    expression: MappingExpression,
    adapter: str,
    sources: tuple[SourceBindingSpec, ...],
    *,
    depth: int = 1,
) -> str:
    if depth > MAX_MAPPING_AST_DEPTH:
        raise _error(
            expression,
            f"expression AST exceeds the maximum depth of {MAX_MAPPING_AST_DEPTH}",
        )
    if adapter not in expression.metadata.supported_adapters:
        raise _error(
            expression,
            f"expression is unsupported on adapter {adapter!r}",
        )
    if isinstance(expression, SourceColumnExpression):
        alias = _source_alias(expression, sources)
        return (
            f"{quote_mapping_identifier(alias, adapter)}."
            f"{quote_mapping_identifier(expression.input.physical_name, adapter)}"
        )
    if isinstance(expression, LiteralExpression):
        return _literal(expression, adapter)
    if isinstance(expression, NullExpression):
        return f"CAST(NULL AS {_physical_type(expression, adapter)})"
    if isinstance(expression, OperatorExpression):
        arguments = tuple(
            _render(item, adapter, sources, depth=depth + 1)
            for item in expression.arguments
        )
        if expression.operator in _BINARY_OPERATORS:
            return (
                f"({arguments[0]} {_BINARY_OPERATORS[expression.operator]} "
                f"{arguments[1]})"
            )
        if expression.operator == "negate":
            return f"(-{arguments[0]})"
        if expression.operator == "not":
            return f"(NOT {arguments[0]})"
        if expression.operator == "is-null":
            return f"({arguments[0]} IS NULL)"
        if expression.operator == "is-not-null":
            return f"({arguments[0]} IS NOT NULL)"
        raise _error(expression, f"operator {expression.operator!r} is not renderable")
    if isinstance(expression, FunctionExpression):
        arguments = tuple(
            _render(item, adapter, sources, depth=depth + 1)
            for item in expression.arguments
        )
        if expression.function == "coalesce":
            return f"COALESCE({', '.join(arguments)})"
        if expression.function == "nullif":
            return f"NULLIF({arguments[0]}, {arguments[1]})"
        if expression.function == "length":
            if adapter == "fabric":
                return (
                    f"CAST(LEN({arguments[0]}) + "
                    f"(DATALENGTH({arguments[0]}) - "
                    f"DATALENGTH(RTRIM({arguments[0]}))) AS BIGINT)"
                )
            return f"LENGTH({arguments[0]})"
        if expression.function == "concat":
            body = f"CONCAT({', '.join(arguments)})"
            nullable = tuple(
                argument
                for argument, spec in zip(arguments, expression.arguments, strict=True)
                if spec.metadata.nullable
            )
            if nullable:
                predicate = " OR ".join(f"{argument} IS NULL" for argument in nullable)
                body = (
                    f"CASE WHEN {predicate} THEN "
                    f"CAST(NULL AS {_physical_type(expression, adapter)}) "
                    f"ELSE {body} END"
                )
            return body
        if expression.function == "round" and adapter == "fabric" and len(arguments) == 1:
            return f"ROUND({arguments[0]}, 0)"
        if expression.function in {"abs", "round", "upper", "lower"}:
            return f"{expression.function.upper()}({', '.join(arguments)})"
        raise _error(expression, f"function {expression.function!r} is not renderable")
    if isinstance(expression, CaseExpression):
        branches = " ".join(
            (
                f"WHEN {_render(branch.condition, adapter, sources, depth=depth + 1)} "
                f"THEN {_render(branch.result, adapter, sources, depth=depth + 1)}"
            )
            for branch in expression.branches
        )
        otherwise = _render(
            expression.else_expression,
            adapter,
            sources,
            depth=depth + 1,
        )
        return f"CASE {branches} ELSE {otherwise} END"
    if isinstance(expression, MacroExpression):
        arguments = ", ".join(
            _render(item, adapter, sources, depth=depth + 1)
            for item in expression.arguments
        )
        return f"{{{{ {expression.macro_name}({arguments}) }}}}"
    raise _error(expression, f"unknown validated node {type(expression).__name__}")


def render_mapping_join_condition(join: JoinSpec, *, adapter: str) -> str:
    """Render a generated FK predicate from normalized source-symbol bindings."""

    source_alias = (
        quote_mapping_identifier(join.source_alias, adapter)
        if join.source_alias
        else ""
    )
    target_alias = quote_mapping_identifier(join.alias, adapter)
    if join.source_inputs:
        if (
            len(join.source_inputs) != len(join.target_columns)
            or not join.source_alias
            or not join.alias
        ):
            raise MappingContractError(
                "mapping.render-blocked",
                "normalized FK join bindings are incomplete",
                resource_uri=join.fk_column or join.alias,
                rule_id="DD-107-render",
            )
        parts = [
            (
                f"{source_alias}."
                f"{quote_mapping_identifier(source.physical_name, adapter)} = "
                f"{target_alias}.{quote_mapping_identifier(target, adapter)}"
            )
            for source, target in zip(
                join.source_inputs,
                join.target_columns,
                strict=True,
            )
        ]
    else:
        parts = [join.condition]
    if join.temporal_mode == "current":
        parts.append(
            f"{target_alias}.{quote_mapping_identifier('is_current', adapter)} = 1"
        )
    elif join.temporal_mode == "as-of":
        if not join.as_of_column or not source_alias:
            raise MappingContractError(
                "mapping.render-blocked",
                "as-of FK join has no bound source alias/as-of column",
                resource_uri=join.fk_column or join.alias,
                rule_id="DD-107-render",
            )
        as_of = (
            f"{source_alias}."
            f"{quote_mapping_identifier(join.as_of_column, adapter)}"
        )
        as_of = (
            f"CAST({as_of} AS DATETIME2(6))"
            if adapter == "fabric"
            else f"CAST({as_of} AS TIMESTAMP)"
        )
        valid_from = (
            f"{target_alias}."
            f"{quote_mapping_identifier('_business_valid_from', adapter)}"
        )
        valid_to = (
            f"{target_alias}."
            f"{quote_mapping_identifier('_business_valid_to', adapter)}"
        )
        parts.extend(
            (
                f"{as_of} >= {valid_from}",
                f"({valid_to} IS NULL OR {as_of} < {valid_to})",
            )
        )
    return " AND ".join(parts)


def render_mapping_expression(
    expression: MappingExpression,
    *,
    adapter: str,
    sources: tuple[SourceBindingSpec, ...],
) -> str:
    """Render one validated expression with bound symbols and safe literals only."""

    if adapter not in {"fabric", "databricks"}:
        raise _error(expression, f"unknown adapter {adapter!r}")
    return _render(expression, adapter, sources)
