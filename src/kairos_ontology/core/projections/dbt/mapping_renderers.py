# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Adapter-specific SQL rendering exclusively from validated DD-107 AST nodes."""

from __future__ import annotations

from ...adapters import FABRIC_WAREHOUSE

from .capabilities import has_native_boolean, physical_canonical_type
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

#: Operators whose operands are conditions rather than values.
_LOGICAL_OPERATORS = frozenset({"and", "or", "not"})

#: Operators that already render as a native SQL predicate. Everything else renders as a
#: value -- which, on an adapter with no native boolean, is a bit column rather than a
#: condition. See :class:`~.policy_specs.AdapterDialectSpec` (DD-215).
_PREDICATE_OPERATORS = _LOGICAL_OPERATORS | frozenset(
    {
        "equal",
        "not-equal",
        "less-than",
        "less-or-equal",
        "greater-than",
        "greater-or-equal",
        "is-null",
        "is-not-null",
    }
)


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
    if adapter == FABRIC_WAREHOUSE:
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

    if adapter == FABRIC_WAREHOUSE:
        payload = lexical.encode("utf-8").hex().upper()
        return f"CONVERT(VARCHAR(8000), 0x{payload})" if payload else "CAST('' AS VARCHAR(8000))"
    if adapter == "databricks":
        payload = lexical.encode("utf-8").hex().upper()
        return f"decode(unhex('{payload}'), 'UTF-8')"
    raise ValueError(f"unsupported mapping adapter {adapter!r}")


def _source_alias(
    expression: SourceColumnExpression,
    sources: tuple[SourceBindingSpec, ...],
) -> str:
    matches = tuple(
        source.alias for source in sources if source.table_uri == expression.input.source_table_uri
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
            if adapter == FABRIC_WAREHOUSE
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
        return f"CAST({_text_literal(lexical, adapter)} AS {_physical_type(expression, adapter)})"
    raise _error(
        expression,
        f"typed literals of kind {kind.value!r} have no portable renderer",
    )


def _is_predicate_shaped(expression: MappingExpression) -> bool:
    """Whether this node already renders as a native SQL predicate rather than a value."""

    return (
        isinstance(expression, OperatorExpression) and expression.operator in _PREDICATE_OPERATORS
    )


def _is_boolean(expression: MappingExpression) -> bool:
    return expression.metadata.output_type.kind is CanonicalTypeKind.BOOLEAN


def _render_predicate(
    expression: MappingExpression,
    adapter: str,
    sources: tuple[SourceBindingSpec, ...],
    *,
    depth: int = 1,
) -> str:
    """Render where SQL expects a condition (WHERE, CASE WHEN, AND/OR/NOT operand).

    On an adapter with no native boolean the canonical BOOLEAN type is a bit column, and
    T-SQL rejects ``where is_debtor`` with "An expression of non-boolean type specified in
    a context where a condition is expected". Comparing to ``1`` is also the correct null
    semantics: a role exists only where the flag is explicitly set, so NULL must not pass.
    """

    rendered = _render(expression, adapter, sources, depth=depth)
    if _is_predicate_shaped(expression) or has_native_boolean(adapter):
        return rendered
    if not _is_boolean(expression):
        raise _error(
            expression,
            "non-boolean expression rendered where a condition is expected",
        )
    return f"({rendered} = 1)"


def _render_value(
    expression: MappingExpression,
    adapter: str,
    sources: tuple[SourceBindingSpec, ...],
    *,
    depth: int = 1,
) -> str:
    """Render where SQL expects a value (select list, function argument, CASE result).

    The mirror of :func:`_render_predicate`: T-SQL has no boolean *value*, so a native
    predicate such as ``(a IS NULL)`` cannot stand in a select list either. The
    three-valued form is used when the predicate can itself be NULL, so that unknown does
    not collapse to false.
    """

    rendered = _render(expression, adapter, sources, depth=depth)
    if not _is_predicate_shaped(expression) or has_native_boolean(adapter):
        return rendered
    if expression.metadata.nullable:
        return f"CASE WHEN {rendered} THEN 1 WHEN NOT {rendered} THEN 0 ELSE NULL END"
    return f"CASE WHEN {rendered} THEN 1 ELSE 0 END"


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
        # AND/OR/NOT take conditions, every other operator takes values. The two need
        # different SQL on an adapter without a native boolean, so the operands cannot
        # all be rendered through one path.
        render_argument = (
            _render_predicate if expression.operator in _LOGICAL_OPERATORS else _render_value
        )
        arguments = tuple(
            render_argument(item, adapter, sources, depth=depth + 1)
            for item in expression.arguments
        )
        if expression.operator in _BINARY_OPERATORS:
            return f"({arguments[0]} {_BINARY_OPERATORS[expression.operator]} {arguments[1]})"
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
            _render_value(item, adapter, sources, depth=depth + 1) for item in expression.arguments
        )
        if expression.function == "cast":
            return f"CAST({arguments[0]} AS {_physical_type(expression, adapter)})"
        if expression.function == "coalesce":
            return f"COALESCE({', '.join(arguments)})"
        if expression.function == "nullif":
            return f"NULLIF({arguments[0]}, {arguments[1]})"
        if expression.function == "length":
            if adapter == FABRIC_WAREHOUSE:
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
        if expression.function == "round" and adapter == FABRIC_WAREHOUSE and len(arguments) == 1:
            return f"ROUND({arguments[0]}, 0)"
        if expression.function in {"abs", "round", "upper", "lower"}:
            return f"{expression.function.upper()}({', '.join(arguments)})"
        raise _error(expression, f"function {expression.function!r} is not renderable")
    if isinstance(expression, CaseExpression):
        branches = " ".join(
            (
                f"WHEN {_render_predicate(branch.condition, adapter, sources, depth=depth + 1)} "
                f"THEN {_render_value(branch.result, adapter, sources, depth=depth + 1)}"
            )
            for branch in expression.branches
        )
        otherwise = _render_value(
            expression.else_expression,
            adapter,
            sources,
            depth=depth + 1,
        )
        return f"CASE {branches} ELSE {otherwise} END"
    if isinstance(expression, MacroExpression):
        arguments = ", ".join(
            _render_value(item, adapter, sources, depth=depth + 1) for item in expression.arguments
        )
        return f"{{{{ {expression.macro_name}({arguments}) }}}}"
    raise _error(expression, f"unknown validated node {type(expression).__name__}")


def render_mapping_join_condition(join: JoinSpec, *, adapter: str) -> str:
    """Render a generated FK predicate from normalized source-symbol bindings."""

    source_alias = quote_mapping_identifier(join.source_alias, adapter) if join.source_alias else ""
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
        parts.append(f"{target_alias}.{quote_mapping_identifier('is_current', adapter)} = 1")
    elif join.temporal_mode == "as-of":
        if not join.as_of_column or not source_alias:
            raise MappingContractError(
                "mapping.render-blocked",
                "as-of FK join has no bound source alias/as-of column",
                resource_uri=join.fk_column or join.alias,
                rule_id="DD-107-render",
            )
        as_of = f"{source_alias}.{quote_mapping_identifier(join.as_of_column, adapter)}"
        as_of = (
            f"CAST({as_of} AS DATETIME2(6))"
            if adapter == FABRIC_WAREHOUSE
            else f"CAST({as_of} AS TIMESTAMP)"
        )
        valid_from = (
            f"{target_alias}.{quote_mapping_identifier(join.parent_valid_from_column, adapter)}"
        )
        valid_to = (
            f"{target_alias}.{quote_mapping_identifier(join.parent_valid_to_column, adapter)}"
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
    position: str = "value",
) -> str:
    """Render one validated expression with bound symbols and safe literals only.

    ``position`` declares what the surrounding SQL expects: ``"value"`` for a select-list
    or argument slot, ``"predicate"`` for a WHERE/ON slot. It is not cosmetic -- on an
    adapter with no native boolean the same AST node renders differently in each (DD-215).
    """

    if adapter not in {item.value for item in AdapterName}:
        raise _error(expression, f"unknown adapter {adapter!r}")
    if position == "predicate":
        return _render_predicate(expression, adapter, sources)
    if position != "value":
        raise _error(expression, f"unknown render position {position!r}")
    return _render_value(expression, adapter, sources)
