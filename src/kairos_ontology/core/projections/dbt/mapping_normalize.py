# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Pure semantic validation for structured scalar mapping contracts (DD-107)."""

from __future__ import annotations

from ...adapters import SUPPORTED_ADAPTER_IDS

import math
import re
from dataclasses import replace
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from .mapping_specs import (
    AuthoredExpressionFact,
    CaseBranchSpec,
    CaseExpression,
    ColumnMappingSpec,
    FunctionExpression,
    LiteralExpression,
    MAX_MAPPING_AST_DEPTH,
    MacroExpression,
    MappingCapability,
    MappingCapabilityResult,
    MappingContractError,
    MappingContractSpec,
    MappingDeterminism,
    MappingExpression,
    MappingExpressionMetadata,
    MappingExpressionProvenance,
    MappingInputSpec,
    MappingNullPolicy,
    MappingRoute,
    NullExpression,
    OperatorExpression,
    SourceColumnExpression,
    SourceMappings,
    TableMappingSpec,
    TransformationAuthoritySpec,
)
from .policy_specs import (
    CanonicalTypeKind,
    CanonicalTypeSpec,
    MedallionPolicySpec,
)
from .policy_normalize import _source_type, _target_type, _types_compatible
from .specs import ContractFact, SourceSystemFact

_BOOLEAN = CanonicalTypeSpec(CanonicalTypeKind.BOOLEAN)
_INT64 = CanonicalTypeSpec(CanonicalTypeKind.INT64)
_NUMERIC_KINDS = frozenset(
    {
        CanonicalTypeKind.INT16,
        CanonicalTypeKind.INT32,
        CanonicalTypeKind.INT64,
        CanonicalTypeKind.DECIMAL,
        CanonicalTypeKind.FLOAT64,
    }
)
_TECHNICAL_FUNCTIONS = frozenset(
    {
        "cast",
        "try-cast",
        "try_cast",
        "trim",
        "left-trim",
        "ltrim",
        "right-trim",
        "rtrim",
        "replace",
        "json-value",
        "json_value",
        "json-array",
        "json_array",
        "sentinel",
        "cdc-value",
    }
)
_NONDETERMINISTIC_FUNCTIONS = frozenset(
    {
        "current-date",
        "current_date",
        "current-timestamp",
        "current_timestamp",
        "getdate",
        "now",
        "rand",
        "random",
        "newid",
        "uuid",
    }
)
_RELATIONAL_FUNCTIONS = frozenset(
    {
        "aggregate",
        "avg",
        "count",
        "dense-rank",
        "dense_rank",
        "explode",
        "fallback-across-relations",
        "flatten",
        "join",
        "lag",
        "lead",
        "lookup",
        "max",
        "min",
        "rank",
        "row-number",
        "row_number",
        "sum",
        "union",
        "window",
    }
)
_OPERATORS = {
    "add": (2, "numeric"),
    "subtract": (2, "numeric"),
    "multiply": (2, "numeric"),
    "divide": (2, "numeric"),
    "modulo": (2, "numeric"),
    "negate": (1, "numeric"),
    "equal": (2, "comparison"),
    "not-equal": (2, "comparison"),
    "less-than": (2, "comparison"),
    "less-or-equal": (2, "comparison"),
    "greater-than": (2, "comparison"),
    "greater-or-equal": (2, "comparison"),
    "and": (2, "logical"),
    "or": (2, "logical"),
    "not": (1, "logical"),
    "is-null": (1, "null-test"),
    "is-not-null": (1, "null-test"),
}
_FUNCTION_ARITY: dict[str, tuple[int, int | None]] = {
    "abs": (1, 1),
    "round": (1, 2),
    "concat": (2, None),
    "upper": (1, 1),
    "lower": (1, 1),
    "length": (1, 1),
    "coalesce": (2, None),
    "nullif": (2, 2),
}
_MACRO_NAMESPACE = "https://kairos.cnext.eu/mapping/macro#"
_APPROVED_MACROS = {
    f"{_MACRO_NAMESPACE}concat": "kairos_concat",
    f"{_MACRO_NAMESPACE}dayOfWeek": "kairos_day_of_week",
    f"{_MACRO_NAMESPACE}monthName": "kairos_month_name",
    f"{_MACRO_NAMESPACE}quarter": "kairos_quarter",
}
_CAPABILITY_ADAPTERS = {capability: SUPPORTED_ADAPTER_IDS for capability in MappingCapability}
_TIME_LEXICAL = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](?:\.[0-9]{1,7})?")


def _error(
    code: str,
    message: str,
    *,
    resource_uri: str = "",
    rule_id: str = "DD-107",
) -> MappingContractError:
    return MappingContractError(
        code,
        message,
        resource_uri=resource_uri,
        rule_id=rule_id,
    )


def _canonical_type(value: str, resource_uri: str) -> CanonicalTypeSpec:
    raw = value.strip().lower()
    result = _target_type(raw)
    if result is None:
        aliases = {kind.value: kind for kind in CanonicalTypeKind}
        sized_string = re.fullmatch(r"string\((\d+)\)", raw)
        decimal = re.fullmatch(r"decimal\((\d+),(\d+)\)", raw)
        if sized_string:
            result = CanonicalTypeSpec(
                CanonicalTypeKind.STRING,
                length=int(sized_string.group(1)),
            )
        elif decimal:
            precision, scale = map(int, decimal.groups())
            if 1 <= precision <= 38 and 0 <= scale <= precision:
                result = CanonicalTypeSpec(
                    CanonicalTypeKind.DECIMAL,
                    precision=precision,
                    scale=scale,
                )
        elif raw in aliases:
            result = CanonicalTypeSpec(aliases[raw])
    if result is None:
        raise _error(
            "mapping.invalid-output-type",
            f"unknown canonical output type {value!r}",
            resource_uri=resource_uri,
            rule_id="DD-107-types",
        )
    return result


def _type_label(value: CanonicalTypeSpec) -> str:
    if value.kind is CanonicalTypeKind.DECIMAL:
        return f"decimal({value.precision or 18},{value.scale or 0})"
    if value.kind is CanonicalTypeKind.STRING and value.length:
        return f"string({value.length})"
    return value.kind.value


def _type_equivalent(left: CanonicalTypeSpec, right: CanonicalTypeSpec) -> bool:
    if left.kind is not right.kind:
        return False
    if left.kind is CanonicalTypeKind.DECIMAL:
        return (
            left.precision or 18,
            left.scale or 0,
        ) == (
            right.precision or 18,
            right.scale or 0,
        )
    if left.kind is CanonicalTypeKind.STRING and left.length and right.length:
        return left.length == right.length
    return True


def _target_compatible(
    output: CanonicalTypeSpec,
    target: CanonicalTypeSpec,
) -> bool:
    return output.kind is target.kind and (
        _types_compatible(output, target) or _type_equivalent(output, target)
    )


def _bool(value: str, resource_uri: str) -> bool:
    if value.lower() in {"true", "1"}:
        return True
    if value.lower() in {"false", "0"}:
        return False
    raise _error(
        "mapping.invalid-nullability",
        f"nullable must be an xsd:boolean lexical value, got {value!r}",
        resource_uri=resource_uri,
        rule_id="DD-107-null-semantics",
    )


def _declared_metadata(
    fact: AuthoredExpressionFact,
    *,
    mapping_resource_uri: str,
    output_type: CanonicalTypeSpec,
    nullable: bool,
    null_policy: MappingNullPolicy,
    capability: MappingCapability,
    inputs: tuple[MappingInputSpec, ...],
) -> MappingExpressionMetadata:
    declared_type = _canonical_type(fact.output_type, fact.resource_uri)
    if not _type_equivalent(declared_type, output_type):
        raise _error(
            "mapping.output-type-mismatch",
            (
                f"declared output type {_type_label(declared_type)!r} does not match "
                f"inferred {_type_label(output_type)!r}"
            ),
            resource_uri=fact.resource_uri,
            rule_id="DD-107-types",
        )
    declared_nullable = _bool(fact.nullable, fact.resource_uri)
    if declared_nullable is not nullable:
        raise _error(
            "mapping.nullability-mismatch",
            (f"declared nullable={declared_nullable} does not match inferred nullable={nullable}"),
            resource_uri=fact.resource_uri,
            rule_id="DD-107-null-semantics",
        )
    try:
        declared_null_policy = MappingNullPolicy(fact.null_policy)
    except ValueError as exc:
        raise _error(
            "mapping.invalid-null-policy",
            f"unknown nullPolicy {fact.null_policy!r}",
            resource_uri=fact.resource_uri,
            rule_id="DD-107-null-semantics",
        ) from exc
    if declared_null_policy is not null_policy:
        raise _error(
            "mapping.null-policy-mismatch",
            (
                f"declared nullPolicy {declared_null_policy.value!r} does not match "
                f"required {null_policy.value!r}"
            ),
            resource_uri=fact.resource_uri,
            rule_id="DD-107-null-semantics",
        )
    if fact.determinism != MappingDeterminism.DETERMINISTIC.value:
        raise _error(
            "mapping.nondeterministic-expression",
            "normal mapping expressions must declare determinism 'deterministic'",
            resource_uri=fact.resource_uri,
            rule_id="DD-107-determinism",
        )
    try:
        capabilities = tuple(
            sorted(
                (MappingCapability(item) for item in fact.capabilities),
                key=lambda item: item.value,
            )
        )
    except ValueError as exc:
        raise _error(
            "mapping.unknown-capability",
            f"unknown expression capability in {fact.capabilities!r}",
            resource_uri=fact.resource_uri,
            rule_id="DD-107-adapter-capability",
        ) from exc
    if capabilities != (capability,):
        raise _error(
            "mapping.capability-mismatch",
            (
                f"{fact.kind} expression must declare exactly "
                f"requiresCapability {capability.value!r}"
            ),
            resource_uri=fact.resource_uri,
            rule_id="DD-107-adapter-capability",
        )
    return MappingExpressionMetadata(
        output_type=output_type,
        nullable=nullable,
        null_policy=null_policy,
        determinism=MappingDeterminism.DETERMINISTIC,
        referenced_inputs=tuple(
            sorted(
                {item.source_column_uri: item for item in inputs}.values(),
                key=lambda item: item.source_column_uri,
            )
        ),
        capability_requirements=capabilities,
        supported_adapters=_CAPABILITY_ADAPTERS[capability],
        provenance=MappingExpressionProvenance(
            mapping_resource_uri=mapping_resource_uri,
            expression_resource_uri=fact.resource_uri,
            source="authored",
        ),
    )


def _inputs(expressions: tuple[MappingExpression, ...]) -> tuple[MappingInputSpec, ...]:
    return tuple(
        sorted(
            {
                item.source_column_uri: item
                for expression in expressions
                for item in expression.metadata.referenced_inputs
            }.values(),
            key=lambda item: item.source_column_uri,
        )
    )


def _require_arity(
    operation: str,
    arguments: tuple[MappingExpression, ...],
    minimum: int,
    maximum: int | None,
    resource_uri: str,
) -> None:
    count = len(arguments)
    if count < minimum or (maximum is not None and count > maximum):
        expected = str(minimum) if minimum == maximum else f"{minimum}..{maximum or 'n'}"
        raise _error(
            "mapping.invalid-arity",
            f"{operation!r} expects {expected} arguments, found {count}",
            resource_uri=resource_uri,
            rule_id="DD-107-arity",
        )


def _require_types(
    arguments: tuple[MappingExpression, ...],
    kinds: frozenset[CanonicalTypeKind] | set[CanonicalTypeKind],
    operation: str,
    resource_uri: str,
) -> None:
    invalid = [
        _type_label(item.metadata.output_type)
        for item in arguments
        if item.metadata.output_type.kind not in kinds
    ]
    if invalid:
        raise _error(
            "mapping.invalid-argument-type",
            f"{operation!r} does not accept argument types {invalid}",
            resource_uri=resource_uri,
            rule_id="DD-107-types",
        )


def _comparable(
    left: CanonicalTypeSpec,
    right: CanonicalTypeSpec,
) -> bool:
    return left.kind is right.kind or left.kind in _NUMERIC_KINDS and right.kind in _NUMERIC_KINDS


def _numeric_output(arguments: tuple[MappingExpression, ...]) -> CanonicalTypeSpec:
    values = tuple(item.metadata.output_type for item in arguments)
    if any(item.kind is CanonicalTypeKind.FLOAT64 for item in values):
        return CanonicalTypeSpec(CanonicalTypeKind.FLOAT64)
    if any(item.kind is CanonicalTypeKind.DECIMAL for item in values):
        decimals = tuple(item for item in values if item.kind is CanonicalTypeKind.DECIMAL)
        return CanonicalTypeSpec(
            CanonicalTypeKind.DECIMAL,
            precision=max((item.precision or 18) for item in decimals),
            scale=max((item.scale or 0) for item in decimals),
        )
    rank = {
        CanonicalTypeKind.INT16: 1,
        CanonicalTypeKind.INT32: 2,
        CanonicalTypeKind.INT64: 3,
    }
    return max(values, key=lambda item: rank[item.kind])


def _validate_literal(
    lexical: str,
    datatype_uri: str,
    output_type: CanonicalTypeSpec,
    resource_uri: str,
) -> None:
    literal_type = _target_type(datatype_uri)
    if literal_type is None or literal_type.kind is not output_type.kind:
        raise _error(
            "mapping.literal-type-mismatch",
            (
                f"literal datatype {datatype_uri!r} does not match declared "
                f"{_type_label(output_type)!r}"
            ),
            resource_uri=resource_uri,
            rule_id="DD-107-typed-literal",
        )
    try:
        if output_type.kind is CanonicalTypeKind.BOOLEAN:
            if lexical not in {"true", "false", "1", "0"}:
                raise ValueError
        elif output_type.kind in {
            CanonicalTypeKind.INT16,
            CanonicalTypeKind.INT32,
            CanonicalTypeKind.INT64,
        }:
            if not re.fullmatch(r"[+-]?[0-9]+", lexical):
                raise ValueError
            int(lexical)
        elif output_type.kind is CanonicalTypeKind.DECIMAL:
            Decimal(lexical)
        elif output_type.kind is CanonicalTypeKind.FLOAT64:
            if not math.isfinite(float(lexical)):
                raise ValueError
        elif output_type.kind is CanonicalTypeKind.DATE:
            date.fromisoformat(lexical)
        elif output_type.kind is CanonicalTypeKind.TIME:
            if not _TIME_LEXICAL.fullmatch(lexical):
                raise ValueError
            time.fromisoformat(lexical)
        elif output_type.kind is CanonicalTypeKind.TIMESTAMP:
            datetime.fromisoformat(lexical.replace("Z", "+00:00"))
    except (InvalidOperation, OverflowError, ValueError) as exc:
        raise _error(
            "mapping.invalid-literal-lexical",
            f"{lexical!r} is invalid for {_type_label(output_type)}",
            resource_uri=resource_uri,
            rule_id="DD-107-typed-literal",
        ) from exc


def _expression(
    fact: AuthoredExpressionFact,
    *,
    mapping_resource_uri: str,
    symbols: dict[str, MappingInputSpec],
    depth: int = 1,
) -> MappingExpression:
    if depth > MAX_MAPPING_AST_DEPTH:
        raise _error(
            "mapping.expression-too-deep",
            f"expression AST exceeds the maximum depth of {MAX_MAPPING_AST_DEPTH}",
            resource_uri=fact.resource_uri,
            rule_id="DD-107-ast-depth",
        )
    if fact.kind == "source-column":
        source = symbols.get(fact.source_column_uri)
        if source is None:
            raise _error(
                "mapping.unknown-source-column",
                f"sourceColumn {fact.source_column_uri!r} does not resolve",
                resource_uri=fact.resource_uri,
                rule_id="DD-107-source-ownership",
            )
        metadata = _declared_metadata(
            fact,
            mapping_resource_uri=mapping_resource_uri,
            output_type=source.data_type,
            nullable=source.nullable,
            null_policy=MappingNullPolicy.PROPAGATE,
            capability=MappingCapability.SOURCE_COLUMN,
            inputs=(source,),
        )
        return SourceColumnExpression(metadata, source)

    if fact.kind == "literal":
        output = _canonical_type(fact.output_type, fact.resource_uri)
        _validate_literal(
            fact.literal_lexical,
            fact.literal_datatype,
            output,
            fact.resource_uri,
        )
        metadata = _declared_metadata(
            fact,
            mapping_resource_uri=mapping_resource_uri,
            output_type=output,
            nullable=False,
            null_policy=MappingNullPolicy.NEVER_NULL,
            capability=MappingCapability.TYPED_LITERAL,
            inputs=(),
        )
        return LiteralExpression(
            metadata,
            fact.literal_lexical,
            fact.literal_datatype,
        )

    if fact.kind == "null":
        output = _canonical_type(fact.output_type, fact.resource_uri)
        metadata = _declared_metadata(
            fact,
            mapping_resource_uri=mapping_resource_uri,
            output_type=output,
            nullable=True,
            null_policy=MappingNullPolicy.EXPLICIT_NULL,
            capability=MappingCapability.NULL_HANDLING,
            inputs=(),
        )
        return NullExpression(metadata)

    if fact.kind == "operator":
        signature = _OPERATORS.get(fact.operation)
        if signature is None:
            raise _error(
                "mapping.unknown-operator",
                f"operator {fact.operation!r} is not in the DD-107 allowlist",
                resource_uri=fact.resource_uri,
                rule_id="DD-107-operator-allowlist",
            )
        arguments = tuple(
            _expression(
                item,
                mapping_resource_uri=mapping_resource_uri,
                symbols=symbols,
                depth=depth + 1,
            )
            for item in fact.arguments
        )
        arity, family = signature
        _require_arity(fact.operation, arguments, arity, arity, fact.resource_uri)
        if family == "numeric":
            _require_types(arguments, _NUMERIC_KINDS, fact.operation, fact.resource_uri)
            output = _numeric_output(arguments)
            null_policy = MappingNullPolicy.PROPAGATE
            nullable = any(item.metadata.nullable for item in arguments)
        elif family == "comparison":
            if not _comparable(
                arguments[0].metadata.output_type,
                arguments[1].metadata.output_type,
            ):
                raise _error(
                    "mapping.invalid-argument-type",
                    f"{fact.operation!r} arguments are not comparable",
                    resource_uri=fact.resource_uri,
                    rule_id="DD-107-types",
                )
            output = _BOOLEAN
            null_policy = MappingNullPolicy.THREE_VALUED
            nullable = any(item.metadata.nullable for item in arguments)
        elif family == "logical":
            _require_types(
                arguments,
                {CanonicalTypeKind.BOOLEAN},
                fact.operation,
                fact.resource_uri,
            )
            output = _BOOLEAN
            null_policy = MappingNullPolicy.THREE_VALUED
            nullable = any(item.metadata.nullable for item in arguments)
        else:
            output = _BOOLEAN
            null_policy = MappingNullPolicy.NEVER_NULL
            nullable = False
        metadata = _declared_metadata(
            fact,
            mapping_resource_uri=mapping_resource_uri,
            output_type=output,
            nullable=nullable,
            null_policy=null_policy,
            capability=MappingCapability.SCALAR_OPERATOR,
            inputs=_inputs(arguments),
        )
        return OperatorExpression(metadata, fact.operation, arguments)

    if fact.kind == "function":
        if fact.operation in _RELATIONAL_FUNCTIONS:
            raise _error(
                "mapping.relational-expression",
                (
                    f"function {fact.operation!r} is relational or grain-affecting; "
                    "use an approved contracted dbt transformation"
                ),
                resource_uri=fact.resource_uri,
                rule_id="DD-107-transformation-routing",
            )
        if fact.operation in _TECHNICAL_FUNCTIONS:
            raise _error(
                "mapping.technical-cleanup",
                (
                    f"function {fact.operation!r} is technical cleanup; route it "
                    "through a contracted dbt transformation"
                ),
                resource_uri=fact.resource_uri,
                rule_id="DD-107-transformation-routing",
            )
        if fact.operation in _NONDETERMINISTIC_FUNCTIONS:
            raise _error(
                "mapping.nondeterministic-expression",
                f"function {fact.operation!r} is nondeterministic",
                resource_uri=fact.resource_uri,
                rule_id="DD-107-determinism",
            )
        arity = _FUNCTION_ARITY.get(fact.operation)
        if arity is None:
            raise _error(
                "mapping.unknown-function",
                f"function {fact.operation!r} is not in the DD-107 allowlist",
                resource_uri=fact.resource_uri,
                rule_id="DD-107-function-allowlist",
            )
        arguments = tuple(
            _expression(
                item,
                mapping_resource_uri=mapping_resource_uri,
                symbols=symbols,
                depth=depth + 1,
            )
            for item in fact.arguments
        )
        _require_arity(fact.operation, arguments, *arity, fact.resource_uri)
        capability = MappingCapability.SCALAR_FUNCTION
        null_policy = MappingNullPolicy.PROPAGATE
        nullable = any(item.metadata.nullable for item in arguments)
        if fact.operation in {"abs", "round"}:
            _require_types(arguments[:1], _NUMERIC_KINDS, fact.operation, fact.resource_uri)
            if len(arguments) == 2:
                _require_types(
                    arguments[1:],
                    {
                        CanonicalTypeKind.INT16,
                        CanonicalTypeKind.INT32,
                        CanonicalTypeKind.INT64,
                    },
                    fact.operation,
                    fact.resource_uri,
                )
            output = arguments[0].metadata.output_type
        elif fact.operation in {"concat", "upper", "lower", "length"}:
            _require_types(
                arguments,
                {CanonicalTypeKind.STRING},
                fact.operation,
                fact.resource_uri,
            )
            output = (
                _INT64
                if fact.operation == "length"
                else _canonical_type(fact.output_type, fact.resource_uri)
            )
            if fact.operation != "length" and output.kind is not CanonicalTypeKind.STRING:
                raise _error(
                    "mapping.output-type-mismatch",
                    f"{fact.operation!r} must output string",
                    resource_uri=fact.resource_uri,
                    rule_id="DD-107-types",
                )
        elif fact.operation == "coalesce":
            first = arguments[0].metadata.output_type
            if any(not _comparable(first, item.metadata.output_type) for item in arguments[1:]):
                raise _error(
                    "mapping.invalid-argument-type",
                    "coalesce arguments must have compatible types",
                    resource_uri=fact.resource_uri,
                    rule_id="DD-107-types",
                )
            output = _canonical_type(fact.output_type, fact.resource_uri)
            if any(not _target_compatible(item.metadata.output_type, output) for item in arguments):
                raise _error(
                    "mapping.output-type-mismatch",
                    "coalesce arguments must match the declared output type",
                    resource_uri=fact.resource_uri,
                    rule_id="DD-107-types",
                )
            nullable = all(item.metadata.nullable for item in arguments)
            null_policy = MappingNullPolicy.FIRST_NON_NULL
            capability = MappingCapability.NULL_HANDLING
        else:
            if not _comparable(
                arguments[0].metadata.output_type,
                arguments[1].metadata.output_type,
            ):
                raise _error(
                    "mapping.invalid-argument-type",
                    "nullif arguments must have compatible types",
                    resource_uri=fact.resource_uri,
                    rule_id="DD-107-types",
                )
            output = arguments[0].metadata.output_type
            nullable = True
            null_policy = MappingNullPolicy.NULL_IF_EQUAL
            capability = MappingCapability.NULL_HANDLING
        metadata = _declared_metadata(
            fact,
            mapping_resource_uri=mapping_resource_uri,
            output_type=output,
            nullable=nullable,
            null_policy=null_policy,
            capability=capability,
            inputs=_inputs(arguments),
        )
        return FunctionExpression(metadata, fact.operation, arguments)

    if fact.kind == "case":
        if not fact.branches or fact.else_expression is None:
            raise _error(
                "mapping.invalid-case",
                "CASE requires at least one branch and one explicit elseExpression",
                resource_uri=fact.resource_uri,
                rule_id="DD-107-case",
            )
        branches = tuple(
            CaseBranchSpec(
                condition=_expression(
                    branch.condition,
                    mapping_resource_uri=mapping_resource_uri,
                    symbols=symbols,
                    depth=depth + 1,
                ),
                result=_expression(
                    branch.result,
                    mapping_resource_uri=mapping_resource_uri,
                    symbols=symbols,
                    depth=depth + 1,
                ),
            )
            for branch in fact.branches
        )
        else_expression = _expression(
            fact.else_expression,
            mapping_resource_uri=mapping_resource_uri,
            symbols=symbols,
            depth=depth + 1,
        )
        _require_types(
            tuple(branch.condition for branch in branches),
            {CanonicalTypeKind.BOOLEAN},
            "case condition",
            fact.resource_uri,
        )
        output = _canonical_type(fact.output_type, fact.resource_uri)
        results = tuple(branch.result for branch in branches) + (else_expression,)
        if any(not _target_compatible(item.metadata.output_type, output) for item in results):
            raise _error(
                "mapping.output-type-mismatch",
                "all CASE results must match the declared output type",
                resource_uri=fact.resource_uri,
                rule_id="DD-107-types",
            )
        metadata = _declared_metadata(
            fact,
            mapping_resource_uri=mapping_resource_uri,
            output_type=output,
            nullable=any(item.metadata.nullable for item in results),
            null_policy=MappingNullPolicy.BRANCH,
            capability=MappingCapability.CASE_EXPRESSION,
            inputs=_inputs(tuple(branch.condition for branch in branches) + results),
        )
        return CaseExpression(metadata, branches, else_expression)

    if fact.kind == "macro":
        macro_name = _APPROVED_MACROS.get(fact.macro_uri)
        if macro_name is None:
            raise _error(
                "mapping.unapproved-macro",
                (
                    f"macro IRI {fact.macro_uri!r} is not approved; approved IRIs are "
                    f"{sorted(_APPROVED_MACROS)}"
                ),
                resource_uri=fact.resource_uri,
                rule_id="DD-107-macro-allowlist",
            )
        arguments = tuple(
            _expression(
                item,
                mapping_resource_uri=mapping_resource_uri,
                symbols=symbols,
                depth=depth + 1,
            )
            for item in fact.arguments
        )
        if fact.macro_uri.endswith("concat"):
            _require_arity("macro concat", arguments, 2, None, fact.resource_uri)
            _require_types(
                arguments,
                {CanonicalTypeKind.STRING},
                "macro concat",
                fact.resource_uri,
            )
            expected_kind = CanonicalTypeKind.STRING
        else:
            _require_arity(macro_name, arguments, 1, 1, fact.resource_uri)
            _require_types(
                arguments,
                {CanonicalTypeKind.DATE, CanonicalTypeKind.TIMESTAMP},
                macro_name,
                fact.resource_uri,
            )
            expected_kind = (
                CanonicalTypeKind.STRING
                if fact.macro_uri.endswith("monthName")
                else CanonicalTypeKind.INT32
            )
        output = _canonical_type(fact.output_type, fact.resource_uri)
        if output.kind is not expected_kind:
            raise _error(
                "mapping.output-type-mismatch",
                f"macro {fact.macro_uri!r} must output {expected_kind.value}",
                resource_uri=fact.resource_uri,
                rule_id="DD-107-types",
            )
        metadata = _declared_metadata(
            fact,
            mapping_resource_uri=mapping_resource_uri,
            output_type=output,
            nullable=any(item.metadata.nullable for item in arguments),
            null_policy=MappingNullPolicy.PROPAGATE,
            capability=MappingCapability.NAMESPACED_MACRO,
            inputs=_inputs(arguments),
        )
        return MacroExpression(
            metadata,
            fact.macro_uri,
            macro_name,
            arguments,
        )

    raise _error(
        "mapping.invalid-expression-kind",
        f"unknown expression kind {fact.kind!r}",
        resource_uri=fact.resource_uri,
    )


def _effective_symbols(
    systems: tuple[SourceSystemFact, ...],
    policy: MedallionPolicySpec,
) -> tuple[
    dict[str, MappingInputSpec],
    dict[str, tuple[MappingInputSpec, ...]],
]:
    by_uri: dict[str, list[MappingInputSpec]] = {}
    for system in systems:
        for table in system.tables:
            for column in table.columns:
                source_type = _source_type(column.data_type)
                if source_type is None:
                    continue
                symbol = MappingInputSpec(
                    source_column_uri=column.uri,
                    source_table_uri=table.uri,
                    source_name=system.label,
                    authored_name=column.name,
                    physical_name=column.name,
                    data_type=source_type,
                    nullable=column.nullable,
                    origin=column.origin,
                )
                by_uri.setdefault(column.uri, []).append(symbol)
                if table.relation_kind == "contracted-virtual":
                    for alias in (
                        f"{table.uri}__{column.name}",
                        f"{table.uri}/{column.name}",
                    ):
                        if alias != column.uri:
                            by_uri.setdefault(alias, []).append(
                                replace(symbol, source_column_uri=alias)
                            )
    ambiguous = {uri: tuple(values) for uri, values in by_uri.items() if len(values) != 1}
    unique = {uri: values[0] for uri, values in by_uri.items() if len(values) == 1}
    return unique, ambiguous


def _source_symbol(
    source_column_uri: str,
    symbols: dict[str, MappingInputSpec],
    ambiguous: dict[str, tuple[MappingInputSpec, ...]],
    resource_uri: str,
) -> MappingInputSpec:
    if source_column_uri in ambiguous:
        owners = ", ".join(sorted(item.source_table_uri for item in ambiguous[source_column_uri]))
        raise _error(
            "mapping.ambiguous-source-column",
            f"sourceColumn {source_column_uri!r} has multiple owners: {owners}",
            resource_uri=resource_uri,
            rule_id="DD-107-source-ownership",
        )
    symbol = symbols.get(source_column_uri)
    if symbol is None:
        raise _error(
            "mapping.unknown-source-column",
            f"sourceColumn {source_column_uri!r} does not exist",
            resource_uri=resource_uri,
            rule_id="DD-107-source-ownership",
        )
    return symbol


def _contract_for_table(
    table_uri: str,
    target_uri: str,
    contracts: tuple[tuple[str, ContractFact], ...],
) -> ContractFact | None:
    return next(
        (
            contract
            for _, contract in contracts
            if contract.target_class == target_uri
            and (
                contract.virtual_source_iri == table_uri
                or table_uri in contract.replaces_source_iris
            )
        ),
        None,
    )


def _route(
    table_uri: str,
    target_uri: str,
    *,
    systems: tuple[SourceSystemFact, ...],
    policy: MedallionPolicySpec,
    contracts: tuple[tuple[str, ContractFact], ...],
    replacement_input_uris: frozenset[str],
    resource_uri: str,
) -> tuple[MappingRoute, str]:
    contract = _contract_for_table(table_uri, target_uri, contracts)
    if table_uri in replacement_input_uris:
        if contract is None:
            raise _error(
                "mapping.replaced-source-direct-authority",
                (
                    f"source table {table_uri!r} is governed by a replacement contract "
                    "and cannot retain direct mapping authority"
                ),
                resource_uri=resource_uri,
                rule_id="DD-107-transformation-routing",
            )
        raise _error(
            "mapping.replaced-source-direct-authority",
            (
                f"map contract {contract.name!r} virtual source "
                f"{contract.virtual_source_iri!r}, not replaced table {table_uri!r}"
            ),
            resource_uri=resource_uri,
            rule_id="DD-107-transformation-routing",
        )
    relation_kind = next(
        (
            table.relation_kind
            for system in systems
            for table in system.tables
            if table.uri == table_uri
        ),
        "",
    )
    if relation_kind == "contracted-virtual":
        if contract is None or contract.virtual_source_iri != table_uri:
            raise _error(
                "mapping.unapproved-transformation-route",
                "virtual source has no matching approved discovered dbt contract",
                resource_uri=resource_uri,
                rule_id="DD-107-transformation-routing",
            )
        readiness_gaps: list[str] = []
        if not contract.decision_statuses:
            readiness_gaps.append("no explicit transformation decisions are declared")
        elif not contract.approved:
            readiness_gaps.append(
                f"decision statuses are not all approved: {contract.decision_statuses!r}"
            )
        if not contract.evidence_artifacts:
            readiness_gaps.append("no accepted repository evidence artifacts are recorded")
        if not contract.verified_tests:
            readiness_gaps.append("no executable verified tests are recorded")
        if readiness_gaps:
            raise _error(
                "mapping.unapproved-transformation-route",
                (
                    f"contract {contract.name!r} is not production-ready: "
                    f"{'; '.join(readiness_gaps)}; add approved DD-107 decisions "
                    "with accepted evidence and executable verified tests"
                ),
                resource_uri=resource_uri,
                rule_id="DD-107-transformation-readiness",
            )
        return MappingRoute.CONTRACTED_TRANSFORMATION, contract.name
    return MappingRoute.DIRECT, ""


def _capability_results(
    tables: tuple[TableMappingSpec, ...],
    columns: tuple[ColumnMappingSpec, ...],
) -> tuple[MappingCapabilityResult, ...]:
    values: set[tuple[str, str, MappingCapability]] = set()

    def collect(resource_uri: str, expression: MappingExpression) -> None:
        for capability in expression.metadata.capability_requirements:
            for adapter in SUPPORTED_ADAPTER_IDS:
                values.add((resource_uri, adapter, capability))
        if isinstance(expression, (OperatorExpression, FunctionExpression, MacroExpression)):
            for argument in expression.arguments:
                collect(resource_uri, argument)
        elif isinstance(expression, CaseExpression):
            for branch in expression.branches:
                collect(resource_uri, branch.condition)
                collect(resource_uri, branch.result)
            collect(resource_uri, expression.else_expression)

    for mapping in tables:
        if mapping.row_filter is not None:
            collect(mapping.resource_uri, mapping.row_filter)
    for mapping in columns:
        collect(mapping.resource_uri, mapping.expression)
    return tuple(
        MappingCapabilityResult(
            mapping_resource_uri=resource_uri,
            adapter=adapter,
            capability=capability,
            supported=adapter in _CAPABILITY_ADAPTERS[capability],
            reason=(
                "mapping-expression-capability-registry-v1"
                if adapter in _CAPABILITY_ADAPTERS[capability]
                else "capability absent from mapping-expression registry"
            ),
        )
        for resource_uri, adapter, capability in sorted(
            values,
            key=lambda item: (item[0], item[1], item[2].value),
        )
    )


def normalize_mapping_contract(
    facts: SourceMappings,
    *,
    systems: tuple[SourceSystemFact, ...],
    policy: MedallionPolicySpec,
    contracts: tuple[tuple[str, ContractFact], ...],
    replacement_input_uris: frozenset[str],
) -> MappingContractSpec:
    """Validate types, ownership, nulls, determinism, routing, and capabilities."""

    symbols, ambiguous = _effective_symbols(systems, policy)
    tables: list[TableMappingSpec] = []
    columns: list[ColumnMappingSpec] = []
    table_uris = {table.uri for system in systems for table in system.tables}
    seen_table_resources: set[str] = set()
    seen_column_resources: set[str] = set()

    for fact in facts.tables:
        if fact.resource_uri in seen_table_resources:
            raise _error(
                "mapping.duplicate-resource",
                "table mapping resource is duplicated",
                resource_uri=fact.resource_uri,
            )
        seen_table_resources.add(fact.resource_uri)
        if fact.source_table_uri not in table_uris:
            raise _error(
                "mapping.unknown-source-table",
                f"sourceTable {fact.source_table_uri!r} does not exist",
                resource_uri=fact.resource_uri,
                rule_id="DD-107-source-ownership",
            )
        if fact.mapping_type not in {"direct", "split"}:
            contract = _contract_for_table(
                fact.source_table_uri,
                fact.target_class_uri,
                contracts,
            )
            hint = (
                f"; route through contract {contract.name!r} virtual source "
                f"{contract.virtual_source_iri!r}"
                if contract is not None
                else "; create and approve a contracted dbt transformation"
            )
            raise _error(
                "mapping.relational-mapping-type",
                (f"mappingType {fact.mapping_type!r} is relational or grain-affecting{hint}"),
                resource_uri=fact.resource_uri,
                rule_id="DD-107-transformation-routing",
            )
        route, contract_name = _route(
            fact.source_table_uri,
            fact.target_class_uri,
            systems=systems,
            policy=policy,
            contracts=contracts,
            replacement_input_uris=replacement_input_uris,
            resource_uri=fact.resource_uri,
        )
        row_filter = (
            _expression(
                fact.row_filter,
                mapping_resource_uri=fact.resource_uri,
                symbols=symbols,
            )
            if fact.row_filter is not None
            else None
        )
        if fact.mapping_type == "split" and row_filter is None:
            raise _error(
                "mapping.missing-split-filter",
                "split mappings require one typed boolean rowFilter",
                resource_uri=fact.resource_uri,
                rule_id="DD-107-row-filter",
            )
        if fact.mapping_type == "direct" and row_filter is not None:
            raise _error(
                "mapping.undeclared-row-loss",
                "rowFilter is allowed only on an explicit split mapping",
                resource_uri=fact.resource_uri,
                rule_id="DD-107-row-filter",
            )
        if row_filter is not None:
            if row_filter.metadata.output_type.kind is not CanonicalTypeKind.BOOLEAN:
                raise _error(
                    "mapping.filter-type-mismatch",
                    "rowFilter must output boolean",
                    resource_uri=fact.resource_uri,
                    rule_id="DD-107-row-filter",
                )
            foreign_tables = {
                item.source_table_uri
                for item in row_filter.metadata.referenced_inputs
                if item.source_table_uri != fact.source_table_uri
            }
            if foreign_tables:
                raise _error(
                    "mapping.cross-relation-expression",
                    (
                        f"rowFilter references other relations {sorted(foreign_tables)}; "
                        "use a contracted dbt transformation"
                    ),
                    resource_uri=fact.resource_uri,
                    rule_id="DD-107-transformation-routing",
                )
        tables.append(
            TableMappingSpec(
                resource_uri=fact.resource_uri,
                source_table_uri=fact.source_table_uri,
                target_class_uri=fact.target_class_uri,
                mapping_type=fact.mapping_type,
                match_type=fact.match_type,
                row_filter=row_filter,
                route=route,
                contract_name=contract_name,
            )
        )

    target_owner: dict[tuple[str, str], str] = {}
    for fact in facts.columns:
        if not fact.target_declared:
            continue
        if fact.resource_uri in seen_column_resources:
            raise _error(
                "mapping.duplicate-resource",
                "column mapping resource is duplicated",
                resource_uri=fact.resource_uri,
            )
        seen_column_resources.add(fact.resource_uri)
        source = _source_symbol(
            fact.source_column_uri,
            symbols,
            ambiguous,
            fact.resource_uri,
        )
        key = (source.source_table_uri, fact.target_property_uri)
        previous = target_owner.setdefault(key, fact.resource_uri)
        if previous != fact.resource_uri:
            raise _error(
                "mapping.ambiguous-target-property",
                (
                    f"target property {fact.target_property_uri!r} has multiple mappings "
                    f"for source table {source.source_table_uri!r}"
                ),
                resource_uri=fact.resource_uri,
                rule_id="DD-107-source-ownership",
            )
        target_type = _target_type(fact.target_data_type)
        if target_type is None and fact.target_is_object_property:
            target_type = source.data_type
        if target_type is None:
            raise _error(
                "mapping.unknown-target-type",
                (
                    f"target property {fact.target_property_uri!r} has no supported "
                    "declared range/silver type"
                ),
                resource_uri=fact.resource_uri,
                rule_id="DD-107-types",
            )
        if fact.expression is None:
            metadata = MappingExpressionMetadata(
                output_type=source.data_type,
                nullable=source.nullable,
                null_policy=MappingNullPolicy.PROPAGATE,
                determinism=MappingDeterminism.DETERMINISTIC,
                referenced_inputs=(source,),
                capability_requirements=(MappingCapability.SOURCE_COLUMN,),
                supported_adapters=SUPPORTED_ADAPTER_IDS,
                provenance=MappingExpressionProvenance(
                    mapping_resource_uri=fact.resource_uri,
                    expression_resource_uri=f"{fact.resource_uri}/direct",
                    source="derived-direct",
                ),
            )
            expression: MappingExpression = SourceColumnExpression(metadata, source)
        else:
            expression = _expression(
                fact.expression,
                mapping_resource_uri=fact.resource_uri,
                symbols=symbols,
            )
        foreign_tables = {
            item.source_table_uri
            for item in expression.metadata.referenced_inputs
            if item.source_table_uri != source.source_table_uri
        }
        if foreign_tables:
            contract = _contract_for_table(
                source.source_table_uri,
                "",
                contracts,
            )
            hint = f" through contract {contract.name!r}" if contract else ""
            raise _error(
                "mapping.cross-relation-expression",
                (
                    f"expression references other relations {sorted(foreign_tables)}; "
                    f"route relational logic{hint} through a contracted transformation"
                ),
                resource_uri=fact.resource_uri,
                rule_id="DD-107-transformation-routing",
            )
        if not _target_compatible(expression.metadata.output_type, target_type):
            expression = FunctionExpression(
                replace(expression.metadata, output_type=target_type),
                "cast",
                (expression,),
            )
        target_table = next(
            (item for item in facts.tables if item.source_table_uri == source.source_table_uri),
            None,
        )
        target_class_uri = target_table.target_class_uri if target_table else ""
        route, contract_name = _route(
            source.source_table_uri,
            target_class_uri,
            systems=systems,
            policy=policy,
            contracts=contracts,
            replacement_input_uris=replacement_input_uris,
            resource_uri=fact.resource_uri,
        )
        columns.append(
            ColumnMappingSpec(
                resource_uri=fact.resource_uri,
                source_column_uri=fact.source_column_uri,
                target_property_uri=fact.target_property_uri,
                target_column_name=fact.target_column_name,
                target_data_type=target_type,
                match_type=fact.match_type,
                expression=expression,
                route=route,
                contract_name=contract_name,
            )
        )

    table_specs = tuple(sorted(tables, key=lambda item: item.resource_uri))
    column_specs = tuple(sorted(columns, key=lambda item: item.resource_uri))
    results = _capability_results(table_specs, column_specs)
    unsupported = tuple(item for item in results if not item.supported)
    if unsupported:
        first = unsupported[0]
        raise _error(
            "mapping.unsupported-adapter-capability",
            (f"{first.capability.value!r} is unsupported on adapter {first.adapter!r}"),
            resource_uri=first.mapping_resource_uri,
            rule_id=first.rule_id,
        )
    return MappingContractSpec(
        tables=table_specs,
        columns=column_specs,
        namespaces=facts.namespaces,
        capability_results=results,
        transformation_authorities=tuple(
            TransformationAuthoritySpec(
                name=contract.name,
                target_class_uri=contract.target_class,
                virtual_source_iri=contract.virtual_source_iri,
                replaces_source_iris=contract.replaces_source_iris,
                supported_adapters=contract.supported_adapters,
                grain_key=contract.grain_key,
                decision_statuses=contract.decision_statuses,
                evidence_artifacts=contract.evidence_artifacts,
                verified_tests=contract.verified_tests,
                approved=contract.approved,
            )
            for _, contract in sorted(contracts)
        ),
    )


def normalize_mapping_expression(
    fact: AuthoredExpressionFact,
    *,
    mapping_resource_uri: str,
    inputs: tuple[MappingInputSpec, ...],
) -> MappingExpression:
    """Validate one standalone AST against an exact immutable source-symbol set."""

    symbols = {item.source_column_uri: item for item in inputs}
    if len(symbols) != len(inputs):
        raise _error(
            "mapping.ambiguous-source-column",
            "standalone expression inputs contain duplicate source-column IRIs",
            resource_uri=mapping_resource_uri,
            rule_id="DD-107-source-ownership",
        )
    return _expression(
        fact,
        mapping_resource_uri=mapping_resource_uri,
        symbols=symbols,
    )


def bind_expression_to_column(
    expression: MappingExpression,
    *,
    source_column_uri: str,
    physical_name: str,
) -> MappingExpression:
    """Return an AST with one exact source symbol rebound, never regex-rewritten."""

    if isinstance(expression, SourceColumnExpression):
        if expression.input.source_column_uri != source_column_uri:
            return expression
        rebound = replace(expression.input, physical_name=physical_name)
        return SourceColumnExpression(
            replace(
                expression.metadata,
                referenced_inputs=(rebound,),
            ),
            rebound,
        )
    if isinstance(expression, OperatorExpression):
        arguments = tuple(
            bind_expression_to_column(
                item,
                source_column_uri=source_column_uri,
                physical_name=physical_name,
            )
            for item in expression.arguments
        )
        return replace(
            expression,
            arguments=arguments,
            metadata=replace(expression.metadata, referenced_inputs=_inputs(arguments)),
        )
    if isinstance(expression, FunctionExpression):
        arguments = tuple(
            bind_expression_to_column(
                item,
                source_column_uri=source_column_uri,
                physical_name=physical_name,
            )
            for item in expression.arguments
        )
        return replace(
            expression,
            arguments=arguments,
            metadata=replace(expression.metadata, referenced_inputs=_inputs(arguments)),
        )
    if isinstance(expression, MacroExpression):
        arguments = tuple(
            bind_expression_to_column(
                item,
                source_column_uri=source_column_uri,
                physical_name=physical_name,
            )
            for item in expression.arguments
        )
        return replace(
            expression,
            arguments=arguments,
            metadata=replace(expression.metadata, referenced_inputs=_inputs(arguments)),
        )
    if isinstance(expression, CaseExpression):
        branches = tuple(
            CaseBranchSpec(
                bind_expression_to_column(
                    item.condition,
                    source_column_uri=source_column_uri,
                    physical_name=physical_name,
                ),
                bind_expression_to_column(
                    item.result,
                    source_column_uri=source_column_uri,
                    physical_name=physical_name,
                ),
            )
            for item in expression.branches
        )
        else_expression = bind_expression_to_column(
            expression.else_expression,
            source_column_uri=source_column_uri,
            physical_name=physical_name,
        )
        nested = (
            tuple(item.condition for item in branches)
            + tuple(item.result for item in branches)
            + (else_expression,)
        )
        return replace(
            expression,
            branches=branches,
            else_expression=else_expression,
            metadata=replace(expression.metadata, referenced_inputs=_inputs(nested)),
        )
    return expression
