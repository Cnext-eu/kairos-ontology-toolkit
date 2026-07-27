# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""v5 EntityBinding YAML schema model, loader, and closed expression grammar (DD-133).

This module owns the *document* contract for a v5 ``EntityBinding``:

* a duplicate-key-rejecting YAML loader that preserves source locations;
* JSON-Schema validation of the document shape (``schema/entity-binding.schema.json``);
* frozen dataclasses mirroring the closed schema; and
* structural validation of the closed scalar-expression grammar.

It does **not** resolve symbols against ontologies/sources and it does **not** emit RDF or
dbt artifacts — that is the adapter's job (``bindings`` -> typed facts) in a later phase.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from typing import Any

import yaml
from jsonschema import Draft7Validator

from .result import CompileDiagnostic, CompileError, SourceLocation

MAX_EXPRESSION_DEPTH = 64

# Closed allow-lists owned by the compiler (DD-133 §4). These MUST be a subset of the names
# the downstream DD-107 mapping normalizer accepts (``mapping_normalize._OPERATORS`` /
# ``_FUNCTION_ARITY`` / ``_APPROVED_MACROS``); anything outside these is rejected here so the
# author sees a source-located error instead of a deep normalizer failure. Complex logic must
# move to a contracted dbt model referenced via ``source.dbtModel``. Technical-cleanup
# functions (cast/trim/replace/json-*) are intentionally excluded — they belong in kairos-prep.
ALLOWED_OPERATORS: frozenset[str] = frozenset(
    {
        "add",
        "subtract",
        "multiply",
        "divide",
        "modulo",
        "negate",
        "equal",
        "not-equal",
        "less-than",
        "less-or-equal",
        "greater-than",
        "greater-or-equal",
        "and",
        "or",
        "not",
        "is-null",
        "is-not-null",
    }
)
ALLOWED_FUNCTIONS: frozenset[str] = frozenset(
    {"abs", "round", "concat", "upper", "lower", "length", "coalesce", "nullif"}
)
ALLOWED_MACROS: frozenset[str] = frozenset({"concat", "dayOfWeek", "monthName", "quarter"})
ALLOWED_NULL_POLICIES: frozenset[str] = frozenset(
    {
        "propagate",
        "never-null",
        "three-valued",
        "first-non-null",
        "null-if-equal",
        "branch",
        "explicit-null",
    }
)

_SCHEMA_RESOURCE = "entity-binding.schema.json"


# --------------------------------------------------------------------------------------
# Closed scalar-expression grammar (maps 1:1 to the existing mapping AST).
# --------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ExprColumn:
    """A bare source-column reference."""

    column: str
    null_policy: str = ""
    pointer: str = ""


@dataclass(frozen=True, slots=True)
class ExprLiteral:
    """A typed literal."""

    lexical: str
    datatype: str
    null_policy: str = ""
    pointer: str = ""


@dataclass(frozen=True, slots=True)
class ExprNull:
    """An explicit SQL NULL."""

    null_policy: str = "explicit-null"
    pointer: str = ""


@dataclass(frozen=True, slots=True)
class ExprOperator:
    """A scalar operator over sub-expressions."""

    op: str
    args: tuple["Expression", ...]
    null_policy: str = ""
    pointer: str = ""


@dataclass(frozen=True, slots=True)
class ExprFunction:
    """A scalar function over sub-expressions."""

    fn: str
    args: tuple["Expression", ...]
    null_policy: str = ""
    pointer: str = ""


@dataclass(frozen=True, slots=True)
class ExprCaseBranch:
    """One ordered CASE WHEN/THEN branch."""

    when: "Expression"
    then: "Expression"


@dataclass(frozen=True, slots=True)
class ExprCase:
    """A CASE expression with ordered branches and an else."""

    branches: tuple[ExprCaseBranch, ...]
    else_: "Expression | None"
    null_policy: str = ""
    pointer: str = ""


@dataclass(frozen=True, slots=True)
class ExprMacro:
    """A namespaced macro invocation."""

    macro: str
    args: tuple["Expression", ...]
    null_policy: str = ""
    pointer: str = ""


Expression = (
    ExprColumn | ExprLiteral | ExprNull | ExprOperator | ExprFunction | ExprCase | ExprMacro
)


# --------------------------------------------------------------------------------------
# Document dataclasses (mirror the closed JSON Schema).
# --------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class SourceRef:
    """The single source relation or contracted dbt model."""

    relation: str = ""
    dbt_model: str = ""


@dataclass(frozen=True, slots=True)
class GrainSpec:
    """The explicit materialized grain."""

    columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IdentitySpec:
    """The identity strategy and key scopes."""

    strategy: str
    source_key: tuple[str, ...]
    business_key: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FieldMapping:
    """One property mapped to a closed scalar expression."""

    property: str
    expression: Expression
    pointer: str = ""


@dataclass(frozen=True, slots=True)
class RelationshipJoin:
    """One local->foreign join column pair."""

    local: str
    foreign: str


@dataclass(frozen=True, slots=True)
class RelationshipSpec:
    """One relationship to a materializable or external reference entity."""

    property: str
    target: str
    on: tuple[RelationshipJoin, ...]
    cardinality: str
    mode: str
    missing_parent: str
    ambiguous_parent: str
    pointer: str = ""


@dataclass(frozen=True, slots=True)
class QualityCheck:
    """One focused data-quality check (evidence, not authority)."""

    kind: str
    columns: tuple[str, ...] = ()
    pointer: str = ""


@dataclass(frozen=True, slots=True)
class EntityBinding:
    """A fully parsed, closed v5 EntityBinding document."""

    api_version: str
    name: str
    domain: str
    source: SourceRef
    target_class: str
    grain: GrainSpec
    identity: IdentitySpec
    load_mode: str
    fields: tuple[FieldMapping, ...]
    relationships: tuple[RelationshipSpec, ...] = ()
    quality: tuple[QualityCheck, ...] = ()
    source_path: str = ""


# --------------------------------------------------------------------------------------
# Loader with duplicate-key rejection and source-location resolution.
# --------------------------------------------------------------------------------------
class _MarkResolver:
    """Resolves a JSON-pointer path to a ``(line, column)`` using a composed YAML tree."""

    def __init__(self, root: Any, path: str) -> None:
        self._root = root
        self._path = path

    def at(self, pointer: str) -> SourceLocation:
        node = self._root
        for part in [p for p in pointer.split("/") if p != ""]:
            node = self._descend(node, part)
            if node is None:
                return SourceLocation(path=self._path, pointer=pointer or "/")
        mark = getattr(node, "start_mark", None)
        if mark is None:
            return SourceLocation(path=self._path, pointer=pointer or "/")
        return SourceLocation(
            path=self._path, line=mark.line + 1, column=mark.column + 1, pointer=pointer or "/"
        )

    @staticmethod
    def _descend(node: Any, part: str) -> Any:
        if isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                if getattr(key_node, "value", None) == part:
                    return value_node
            return None
        if isinstance(node, yaml.SequenceNode):
            try:
                return node.value[int(part)]
            except (ValueError, IndexError):
                return None
        return None


def _collect_duplicate_key_diagnostics(
    node: Any, path: str, diagnostics: list[CompileDiagnostic]
) -> None:
    if isinstance(node, yaml.MappingNode):
        seen: dict[str, Any] = {}
        for key_node, value_node in node.value:
            key = getattr(key_node, "value", None)
            if isinstance(key, str):
                if key in seen:
                    mark = key_node.start_mark
                    diagnostics.append(
                        CompileDiagnostic(
                            code="binding.duplicate-key",
                            message=f"duplicate key '{key}'",
                            location=SourceLocation(
                                path=path, line=mark.line + 1, column=mark.column + 1
                            ),
                        )
                    )
                seen[key] = value_node
            _collect_duplicate_key_diagnostics(value_node, path, diagnostics)
    elif isinstance(node, yaml.SequenceNode):
        for item in node.value:
            _collect_duplicate_key_diagnostics(item, path, diagnostics)


def _load_schema() -> dict:
    text = (
        resources.files(__package__)
        .joinpath("schema")
        .joinpath(_SCHEMA_RESOURCE)
        .read_text(encoding="utf-8")
    )
    return json.loads(text)


def _schema_diagnostics(data: Any, resolver: _MarkResolver) -> list[CompileDiagnostic]:
    validator = Draft7Validator(_load_schema())
    diagnostics: list[CompileDiagnostic] = []
    for error in validator.iter_errors(data):
        pointer = "/" + "/".join(str(part) for part in error.absolute_path)
        diagnostics.append(
            CompileDiagnostic(
                code="binding.schema",
                message=error.message,
                location=resolver.at(pointer),
            )
        )
    return diagnostics


def load_entity_binding(text: str, *, path: str = "<binding>") -> EntityBinding:
    """Parse and structurally validate one EntityBinding document.

    Raises :class:`CompileError` with ordered, source-located diagnostics on any duplicate
    key, unknown field, schema violation, or malformed expression.
    """
    try:
        root = yaml.compose(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        location = SourceLocation(
            path=path,
            line=(mark.line + 1) if mark else 0,
            column=(mark.column + 1) if mark else 0,
        )
        raise CompileError(
            [CompileDiagnostic(code="binding.yaml", message=str(exc), location=location)]
        ) from exc

    resolver = _MarkResolver(root, path)
    diagnostics: list[CompileDiagnostic] = []
    _collect_duplicate_key_diagnostics(root, path, diagnostics)

    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        diagnostics.append(
            CompileDiagnostic(
                code="binding.not-a-mapping",
                message="an EntityBinding document must be a YAML mapping",
                location=resolver.at("/"),
            )
        )
        raise CompileError(diagnostics)

    diagnostics.extend(_schema_diagnostics(data, resolver))
    if diagnostics:
        raise CompileError(diagnostics)

    binding = _build_binding(data, resolver, path)
    return binding


def _build_binding(data: dict, resolver: _MarkResolver, path: str) -> EntityBinding:
    diagnostics: list[CompileDiagnostic] = []
    source = data["source"]
    source_ref = SourceRef(
        relation=str(source.get("relation", "")),
        dbt_model=str(source.get("dbtModel", "")),
    )
    identity_raw = data["identity"]
    identity = IdentitySpec(
        strategy=str(identity_raw["strategy"]),
        source_key=tuple(str(c) for c in identity_raw["sourceKey"]),
        business_key=tuple(str(c) for c in identity_raw.get("businessKey", ())),
    )
    grain = GrainSpec(columns=tuple(str(c) for c in data["grain"]["columns"]))

    fields: list[FieldMapping] = []
    for index, raw in enumerate(data["fields"]):
        pointer = f"/fields/{index}/expression"
        expression = _parse_expression(raw["expression"], pointer, resolver, diagnostics, depth=0)
        fields.append(
            FieldMapping(
                property=str(raw["property"]),
                expression=expression,
                pointer=f"/fields/{index}",
            )
        )

    relationships: list[RelationshipSpec] = []
    for index, raw in enumerate(data.get("relationships", ())):
        relationships.append(
            RelationshipSpec(
                property=str(raw["property"]),
                target=str(raw["target"]),
                on=tuple(
                    RelationshipJoin(local=str(j["local"]), foreign=str(j["foreign"]))
                    for j in raw["join"]
                ),
                cardinality=str(raw["cardinality"]),
                mode=str(raw["mode"]),
                missing_parent=str(raw["missingParent"]),
                ambiguous_parent=str(raw["ambiguousParent"]),
                pointer=f"/relationships/{index}",
            )
        )

    quality: list[QualityCheck] = []
    for index, raw in enumerate(data.get("quality", ())):
        quality.append(
            QualityCheck(
                kind=str(raw["kind"]),
                columns=tuple(str(c) for c in raw.get("columns", ())),
                pointer=f"/quality/{index}",
            )
        )

    if diagnostics:
        raise CompileError(diagnostics)

    return EntityBinding(
        api_version=str(data["apiVersion"]),
        name=str(data["metadata"]["name"]),
        domain=str(data["metadata"]["domain"]),
        source=source_ref,
        target_class=str(data["target"]["class"]),
        grain=grain,
        identity=identity,
        load_mode=str(data["load"]["mode"]),
        fields=tuple(fields),
        relationships=tuple(relationships),
        quality=tuple(quality),
        source_path=path,
    )


def _reject(
    diagnostics: list[CompileDiagnostic],
    resolver: _MarkResolver,
    pointer: str,
    code: str,
    message: str,
) -> ExprNull:
    diagnostics.append(CompileDiagnostic(code=code, message=message, location=resolver.at(pointer)))
    return ExprNull(pointer=pointer)


def _parse_expression(
    node: Any,
    pointer: str,
    resolver: _MarkResolver,
    diagnostics: list[CompileDiagnostic],
    depth: int,
) -> Expression:
    if depth > MAX_EXPRESSION_DEPTH:
        return _reject(
            diagnostics,
            resolver,
            pointer,
            "expression.too-deep",
            f"expression nesting exceeds MAX_EXPRESSION_DEPTH ({MAX_EXPRESSION_DEPTH})",
        )
    if node is None:
        return ExprNull(pointer=pointer)
    if isinstance(node, str):
        return ExprColumn(column=node, pointer=pointer)
    if not isinstance(node, dict):
        return _reject(
            diagnostics,
            resolver,
            pointer,
            "expression.invalid",
            f"expression must be a source-column string, null, or a mapping (got {type(node).__name__})",
        )

    null_policy = str(node.get("nullPolicy", ""))
    if null_policy and null_policy not in ALLOWED_NULL_POLICIES:
        _reject(
            diagnostics,
            resolver,
            pointer,
            "expression.null-policy",
            f"unknown nullPolicy '{null_policy}'",
        )

    tags = [t for t in ("column", "literal", "op", "fn", "case", "macro") if t in node]
    if len(tags) != 1:
        return _reject(
            diagnostics,
            resolver,
            pointer,
            "expression.ambiguous",
            "expression node must have exactly one of: column, literal, op, fn, case, macro",
        )
    tag = tags[0]

    if tag == "column":
        return ExprColumn(column=str(node["column"]), null_policy=null_policy, pointer=pointer)

    if tag == "literal":
        if "datatype" not in node:
            return _reject(
                diagnostics,
                resolver,
                pointer,
                "expression.literal-datatype",
                "literal expression requires a 'datatype'",
            )
        return ExprLiteral(
            lexical=str(node["literal"]),
            datatype=str(node["datatype"]),
            null_policy=null_policy,
            pointer=pointer,
        )

    if tag == "op":
        op = str(node["op"])
        if op not in ALLOWED_OPERATORS:
            _reject(
                diagnostics,
                resolver,
                pointer,
                "expression.operator-not-allowed",
                f"operator '{op}' is not in the allow-list {sorted(ALLOWED_OPERATORS)}",
            )
        args = _parse_args(node.get("args"), pointer, resolver, diagnostics, depth)
        return ExprOperator(op=op, args=args, null_policy=null_policy, pointer=pointer)

    if tag == "fn":
        fn = str(node["fn"])
        if fn not in ALLOWED_FUNCTIONS:
            _reject(
                diagnostics,
                resolver,
                pointer,
                "expression.function-not-allowed",
                f"function '{fn}' is not in the allow-list {sorted(ALLOWED_FUNCTIONS)}",
            )
        args = _parse_args(node.get("args"), pointer, resolver, diagnostics, depth)
        return ExprFunction(fn=fn, args=args, null_policy=null_policy, pointer=pointer)

    if tag == "macro":
        macro = str(node["macro"])
        if macro not in ALLOWED_MACROS:
            _reject(
                diagnostics,
                resolver,
                pointer,
                "expression.macro-not-allowed",
                f"macro '{macro}' is not in the allow-list {sorted(ALLOWED_MACROS)}",
            )
        return ExprMacro(
            macro=macro,
            args=_parse_args(node.get("args"), pointer, resolver, diagnostics, depth),
            null_policy=null_policy,
            pointer=pointer,
        )

    # tag == "case"
    raw_branches = node["case"]
    branches: list[ExprCaseBranch] = []
    if not isinstance(raw_branches, list) or not raw_branches:
        _reject(
            diagnostics,
            resolver,
            pointer,
            "expression.case-empty",
            "case expression requires a non-empty list of when/then branches",
        )
    else:
        for bi, branch in enumerate(raw_branches):
            if not isinstance(branch, dict) or "when" not in branch or "then" not in branch:
                _reject(
                    diagnostics,
                    resolver,
                    f"{pointer}/case/{bi}",
                    "expression.case-branch",
                    "each case branch requires 'when' and 'then'",
                )
                continue
            branches.append(
                ExprCaseBranch(
                    when=_parse_expression(
                        branch["when"],
                        f"{pointer}/case/{bi}/when",
                        resolver,
                        diagnostics,
                        depth + 1,
                    ),
                    then=_parse_expression(
                        branch["then"],
                        f"{pointer}/case/{bi}/then",
                        resolver,
                        diagnostics,
                        depth + 1,
                    ),
                )
            )
    else_expr = (
        _parse_expression(node["else"], f"{pointer}/else", resolver, diagnostics, depth + 1)
        if "else" in node
        else None
    )
    return ExprCase(
        branches=tuple(branches), else_=else_expr, null_policy=null_policy, pointer=pointer
    )


def _parse_args(
    raw: Any,
    pointer: str,
    resolver: _MarkResolver,
    diagnostics: list[CompileDiagnostic],
    depth: int,
) -> tuple[Expression, ...]:
    if raw is None:
        _reject(diagnostics, resolver, pointer, "expression.args-missing", "expected 'args' list")
        return ()
    if not isinstance(raw, list) or not raw:
        _reject(
            diagnostics,
            resolver,
            pointer,
            "expression.args-empty",
            "'args' must be a non-empty list",
        )
        return ()
    return tuple(
        _parse_expression(item, f"{pointer}/args/{i}", resolver, diagnostics, depth + 1)
        for i, item in enumerate(raw)
    )
