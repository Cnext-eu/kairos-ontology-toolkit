# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""v5 binding adapter (DD-133): ``EntityBinding`` -> ``BoundSources`` via typed facts.

This is the seam proven by ``tmp_spike/seam_spike.py``. It takes one parsed, closed
:class:`~kairos_ontology.core.compiler.bindings.EntityBinding` plus a resolved symbol context
and hand-constructs the graph-free typed facts the *existing* immutable dbt pipeline consumes
(``normalize_contract -> shape_project -> plan_materialization -> render_project``). It reads
**no** RDF and writes **no** intermediate mapping / preparation / Silver-extension TTL.

It deliberately reuses the downstream DD-107 mapping type-inference tables and helpers (the
underscore-prefixed names imported from ``mapping_normalize`` / ``policy_normalize``) so the
authored ``AuthoredExpressionFact`` metadata this adapter emits is derived from the *same*
rules the normalizer re-validates. Any divergence surfaces immediately as a
``MappingContractError`` from the pipeline, never as silent corruption.

Scope of this first slice: a **single entity** binding with fields, an explicit grain, a
source-natural / surrogate identity, and a synthesized neutral DD-106 passthrough preparation
policy. Cross-entity relationships / foreign keys, multi-source conformance, quality-test
emission, and non-full-refresh load modes are handled by later slice todos (kernel + scenario)
and by deferred stages 2+.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from ..projections.dbt import BoundSources
from ..projections.dbt.context import ActiveSourceScope, ActiveSourceTable
from ..projections.dbt.mapping_normalize import _BOOLEAN, _INT64, _canonical_type, _type_label
from ..projections.dbt.mapping_specs import (
    AuthoredCaseBranchFact,
    AuthoredExpressionFact,
    ColumnMappingFact,
    MappingCapability,
    MappingContractError,
    MappingNullPolicy,
    SourceMappings,
    TableMappingFact,
)
from ..projections.dbt.policy_normalize import _source_type
from ..projections.dbt.policy_specs import (
    AuthoredValuesFact,
    CanonicalTypeKind,
    CanonicalTypeSpec,
    EntityIdentityFact,
    GoldProductFact,
    MedallionPolicyFacts,
    PreparationPolicyFact,
    PreparedColumnFact,
    SourceRecordKeyFact,
)
from ..projections.dbt.specs import (
    BoundSchemaModel,
    BoundSilverModel,
    ClassBindingObservation,
    ClassFact,
    ColumnSpec,
    ModelIdentity,
    ModelOutcome,
    OntologyMetadataSpec,
    SilverModelKind,
    SourceBindingSpec,
    SourceBindingsFact,
    SourceColumnFact,
    SourceRefFact,
    SourceSystemFact,
    SourceTableFact,
)
from .bindings import (
    EntityBinding,
    ExprCase,
    ExprColumn,
    ExprFunction,
    ExprLiteral,
    ExprMacro,
    ExprNull,
    ExprOperator,
    Expression,
)
from .result import CompileDiagnostic, CompileError, SourceLocation, order_compile_diagnostics

# Author identity strategy (schema enum) -> internal DD-108 IdentityStrategy value.
_IDENTITY_STRATEGY = {
    "source-natural": "business-key",
    "surrogate": "surrogate-only",
}

_MACRO_NAMESPACE = "https://kairos.cnext.eu/mapping/macro#"
# Author macro name -> approved namespaced macro IRI (subset of mapping_normalize._APPROVED_MACROS).
_MACRO_IRI = {
    "concat": f"{_MACRO_NAMESPACE}concat",
    "dayOfWeek": f"{_MACRO_NAMESPACE}dayOfWeek",
    "monthName": f"{_MACRO_NAMESPACE}monthName",
    "quarter": f"{_MACRO_NAMESPACE}quarter",
}

_STRING = CanonicalTypeSpec(CanonicalTypeKind.STRING)
_INT32 = CanonicalTypeSpec(CanonicalTypeKind.INT32)


# --------------------------------------------------------------------------------------
# Resolved symbol context (populated by the caller / kernel; hand-authored in adapter tests).
# --------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ResolvedColumn:
    """One physical source column resolved from a source vocabulary."""

    name: str
    data_type: str
    nullable: bool
    is_primary_key: bool = False


@dataclass(frozen=True, slots=True)
class ResolvedRelation:
    """One physical source relation the binding's ``source.relation`` resolves to."""

    ref: str
    uri: str
    system_label: str
    table_name: str
    columns: tuple[ResolvedColumn, ...]
    database: str = "raw_db"
    schema: str = "dbo"
    connection_type: str = "jdbc"
    system_uri: str = ""

    def column_uri(self, name: str) -> str:
        """Return the stable URI used for one column of this relation."""
        return f"{self.uri}/{name}"


@dataclass(frozen=True, slots=True)
class ResolvedProperty:
    """One domain property a binding field targets, resolved from the ontology closure."""

    ref: str
    uri: str
    column_name: str
    data_type: str
    description: str = ""
    is_object_property: bool = False
    domain_uris: tuple[str, ...] = ()
    range_uri: str = ""


@dataclass(frozen=True, slots=True)
class ResolvedClass:
    """The single domain class the binding materializes."""

    ref: str
    uri: str
    name: str
    label: str = ""
    comment: str = ""


@dataclass(frozen=True, slots=True)
class ResolutionContext:
    """Everything the adapter needs to resolve one binding's symbols, graph-free."""

    domain: str
    namespace: str
    ontology_name: str
    ontology_iri: str
    ontology_version: str
    template_root: str
    target_platform: str = "fabric"
    schema_name: str = "silver"
    relations: tuple[ResolvedRelation, ...] = ()
    classes: tuple[ResolvedClass, ...] = ()
    properties: tuple[ResolvedProperty, ...] = ()

    def relation(self, ref: str) -> ResolvedRelation | None:
        """Return the resolved relation for an author ``source.relation`` token."""
        return next((item for item in self.relations if item.ref == ref), None)

    def klass(self, ref: str) -> ResolvedClass | None:
        """Return the resolved class for an author ``target.class`` token."""
        return next((item for item in self.classes if item.ref == ref), None)

    def property(self, ref: str) -> ResolvedProperty | None:
        """Return the resolved property for an author field ``property`` token."""
        return next((item for item in self.properties if item.ref == ref), None)


@dataclass(frozen=True, slots=True)
class _Symbol:
    """A resolved source column symbol: URI, canonical type, nullability."""

    uri: str
    type: CanonicalTypeSpec
    nullable: bool


@dataclass
class _ExprBuilder:
    """Recursively converts the closed binding expression grammar into typed facts.

    Each ``build`` returns the authored fact plus the *inferred* output type and nullability
    (mirroring ``mapping_normalize._expression``) so parents can derive their own metadata.
    """

    symbols: dict[str, _Symbol]
    source_path: str
    resource_base: str
    diagnostics: list[CompileDiagnostic] = field(default_factory=list)
    _counter: int = 0

    def _uid(self, kind: str) -> str:
        self._counter += 1
        return f"{self.resource_base}/expr-{self._counter}-{kind}"

    def _diag(self, expr: Expression, code: str, message: str) -> None:
        self.diagnostics.append(
            CompileDiagnostic(
                code=code,
                message=message,
                location=SourceLocation(
                    path=self.source_path, pointer=getattr(expr, "pointer", "") or "/"
                ),
            )
        )

    def _placeholder(self) -> tuple[AuthoredExpressionFact, CanonicalTypeSpec, bool]:
        # Used only after a diagnostic is recorded; compilation aborts before the pipeline.
        fact = AuthoredExpressionFact(
            resource_uri=self._uid("placeholder"),
            kind="literal",
            output_type="string",
            nullable="false",
            null_policy="never-null",
            determinism="deterministic",
            capabilities=("typed-literal",),
            literal_lexical="",
            literal_datatype="string",
        )
        return fact, _STRING, False

    def build(
        self, expr: Expression, expected_type: CanonicalTypeSpec | None = None
    ) -> tuple[AuthoredExpressionFact, CanonicalTypeSpec, bool]:
        """Build one authored expression fact plus its inferred (type, nullable)."""
        if isinstance(expr, ExprColumn):
            result = self._column(expr)
        elif isinstance(expr, ExprLiteral):
            result = self._literal(expr)
        elif isinstance(expr, ExprNull):
            output = expected_type or _STRING
            result = (
                AuthoredExpressionFact(
                    resource_uri=self._uid("null"),
                    kind="null",
                    output_type=_type_label(output),
                    nullable="true",
                    null_policy=MappingNullPolicy.EXPLICIT_NULL.value,
                    determinism="deterministic",
                    capabilities=(MappingCapability.NULL_HANDLING.value,),
                ),
                output,
                True,
            )
        elif isinstance(expr, ExprOperator):
            result = self._operator(expr)
        elif isinstance(expr, ExprFunction):
            result = self._function(expr)
        elif isinstance(expr, ExprCase):
            result = self._case(expr, expected_type)
        elif isinstance(expr, ExprMacro):
            result = self._macro(expr)
        else:
            self._diag(
                expr, "binding.unknown-expression", f"unsupported expression {type(expr).__name__}"
            )
            result = self._placeholder()
        declared = getattr(expr, "null_policy", "")
        if declared and declared != result[0].null_policy:
            self._diag(
                expr,
                "binding.null-policy-incompatible",
                f"declared nullPolicy '{declared}' conflicts with inferred "
                f"'{result[0].null_policy}'",
            )
        return result

    def _column(self, expr: ExprColumn) -> tuple[AuthoredExpressionFact, CanonicalTypeSpec, bool]:
        symbol = self.symbols.get(expr.column)
        if symbol is None:
            self._diag(
                expr,
                "binding.unknown-column",
                f"source column '{expr.column}' is not a column of the bound relation",
            )
            return self._placeholder()
        fact = AuthoredExpressionFact(
            resource_uri=self._uid("col"),
            kind="source-column",
            output_type=_type_label(symbol.type),
            nullable=_bool_lex(symbol.nullable),
            null_policy=MappingNullPolicy.PROPAGATE.value,
            determinism="deterministic",
            capabilities=(MappingCapability.SOURCE_COLUMN.value,),
            source_column_uri=symbol.uri,
        )
        return fact, symbol.type, symbol.nullable

    def _literal(self, expr: ExprLiteral) -> tuple[AuthoredExpressionFact, CanonicalTypeSpec, bool]:
        try:
            output = _canonical_type(expr.datatype, self.resource_base)
        except MappingContractError as exc:
            self._diag(expr, "binding.bad-literal-type", str(exc))
            return self._placeholder()
        fact = AuthoredExpressionFact(
            resource_uri=self._uid("lit"),
            kind="literal",
            output_type=_type_label(output),
            nullable="false",
            null_policy=MappingNullPolicy.NEVER_NULL.value,
            determinism="deterministic",
            capabilities=(MappingCapability.TYPED_LITERAL.value,),
            literal_lexical=expr.lexical,
            literal_datatype=expr.datatype,
        )
        return fact, output, False

    def _operator(
        self, expr: ExprOperator
    ) -> tuple[AuthoredExpressionFact, CanonicalTypeSpec, bool]:
        built = [self.build(arg) for arg in expr.args]
        arg_facts = tuple(fact for fact, _, _ in built)
        arg_types = [type_ for _, type_, _ in built]
        any_nullable = any(nullable for _, _, nullable in built)
        numeric = {"add", "subtract", "multiply", "divide", "modulo", "negate"}
        null_test = {"is-null", "is-not-null"}
        if expr.op in numeric:
            output = _numeric_output(arg_types)
            null_policy = MappingNullPolicy.PROPAGATE
            nullable = any_nullable
        elif expr.op in null_test:
            output, null_policy, nullable = _BOOLEAN, MappingNullPolicy.NEVER_NULL, False
        else:  # comparison / logical
            output, null_policy, nullable = _BOOLEAN, MappingNullPolicy.THREE_VALUED, any_nullable
        fact = AuthoredExpressionFact(
            resource_uri=self._uid("op"),
            kind="operator",
            output_type=_type_label(output),
            nullable=_bool_lex(nullable),
            null_policy=null_policy.value,
            determinism="deterministic",
            capabilities=(MappingCapability.SCALAR_OPERATOR.value,),
            operation=expr.op,
            arguments=arg_facts,
        )
        return fact, output, nullable

    def _function(
        self, expr: ExprFunction
    ) -> tuple[AuthoredExpressionFact, CanonicalTypeSpec, bool]:
        built = [self.build(arg) for arg in expr.args]
        arg_facts = tuple(fact for fact, _, _ in built)
        arg_types = [type_ for _, type_, _ in built]
        any_nullable = any(nullable for _, _, nullable in built)
        all_nullable = bool(built) and all(nullable for _, _, nullable in built)
        capability = MappingCapability.SCALAR_FUNCTION
        if expr.fn in {"abs", "round"}:
            output, null_policy, nullable = (
                arg_types[0] if arg_types else _INT64,
                MappingNullPolicy.PROPAGATE,
                any_nullable,
            )
        elif expr.fn == "length":
            output, null_policy, nullable = _INT64, MappingNullPolicy.PROPAGATE, any_nullable
        elif expr.fn in {"upper", "lower", "concat"}:
            output, null_policy, nullable = _STRING, MappingNullPolicy.PROPAGATE, any_nullable
        elif expr.fn == "coalesce":
            output = arg_types[0] if arg_types else _STRING
            null_policy, nullable, capability = (
                MappingNullPolicy.FIRST_NON_NULL,
                all_nullable,
                MappingCapability.NULL_HANDLING,
            )
        else:  # nullif
            output = arg_types[0] if arg_types else _STRING
            null_policy, nullable, capability = (
                MappingNullPolicy.NULL_IF_EQUAL,
                True,
                MappingCapability.NULL_HANDLING,
            )
        fact = AuthoredExpressionFact(
            resource_uri=self._uid("fn"),
            kind="function",
            output_type=_type_label(output),
            nullable=_bool_lex(nullable),
            null_policy=null_policy.value,
            determinism="deterministic",
            capabilities=(capability.value,),
            operation=expr.fn,
            arguments=arg_facts,
        )
        return fact, output, nullable

    def _case(
        self, expr: ExprCase, expected_type: CanonicalTypeSpec | None = None
    ) -> tuple[AuthoredExpressionFact, CanonicalTypeSpec, bool]:
        branch_facts: list[AuthoredCaseBranchFact] = []
        result_types: list[CanonicalTypeSpec] = []
        any_nullable = False
        for index, branch in enumerate(expr.branches):
            when_fact, _, _ = self.build(branch.when)
            then_fact, then_type, then_nullable = self.build(branch.then, expected_type)
            result_types.append(then_type)
            any_nullable = any_nullable or then_nullable
            branch_facts.append(
                AuthoredCaseBranchFact(
                    resource_uri=f"{self.resource_base}/case-branch-{index}",
                    condition=when_fact,
                    result=then_fact,
                )
            )
        if expr.else_ is None:
            self._diag(
                expr, "binding.case-requires-else", "a case expression requires an explicit else"
            )
            return self._placeholder()
        else_fact, else_type, else_nullable = self.build(expr.else_, expected_type)
        result_types.append(else_type)
        any_nullable = any_nullable or else_nullable
        output = expected_type or (result_types[0] if result_types else _STRING)
        fact = AuthoredExpressionFact(
            resource_uri=self._uid("case"),
            kind="case",
            output_type=_type_label(output),
            nullable=_bool_lex(any_nullable),
            null_policy=MappingNullPolicy.BRANCH.value,
            determinism="deterministic",
            capabilities=(MappingCapability.CASE_EXPRESSION.value,),
            branches=tuple(branch_facts),
            else_expression=else_fact,
        )
        return fact, output, any_nullable

    def _macro(self, expr: ExprMacro) -> tuple[AuthoredExpressionFact, CanonicalTypeSpec, bool]:
        iri = _MACRO_IRI.get(expr.macro)
        if iri is None:
            self._diag(expr, "binding.unknown-macro", f"macro '{expr.macro}' is not approved")
            return self._placeholder()
        built = [self.build(arg) for arg in expr.args]
        arg_facts = tuple(fact for fact, _, _ in built)
        any_nullable = any(nullable for _, _, nullable in built)
        output = _STRING if expr.macro in {"concat", "monthName"} else _INT32
        fact = AuthoredExpressionFact(
            resource_uri=self._uid("macro"),
            kind="macro",
            output_type=_type_label(output),
            nullable=_bool_lex(any_nullable),
            null_policy=MappingNullPolicy.PROPAGATE.value,
            determinism="deterministic",
            capabilities=(MappingCapability.NAMESPACED_MACRO.value,),
            macro_uri=iri,
            arguments=arg_facts,
        )
        return fact, output, any_nullable


def _bool_lex(value: bool) -> str:
    return "true" if value else "false"


def _numeric_output(types: list[CanonicalTypeSpec]) -> CanonicalTypeSpec:
    if not types:
        return _INT64
    if any(item.kind is CanonicalTypeKind.FLOAT64 for item in types):
        return CanonicalTypeSpec(CanonicalTypeKind.FLOAT64)
    decimals = [item for item in types if item.kind is CanonicalTypeKind.DECIMAL]
    if decimals:
        return CanonicalTypeSpec(
            CanonicalTypeKind.DECIMAL,
            precision=max((item.precision or 18) for item in decimals),
            scale=max((item.scale or 0) for item in decimals),
        )
    rank = {CanonicalTypeKind.INT16: 1, CanonicalTypeKind.INT32: 2, CanonicalTypeKind.INT64: 3}
    numeric = [item for item in types if item.kind in rank]
    if numeric:
        return max(numeric, key=lambda item: rank[item.kind])
    return types[0]


def _first_source_column(fact: AuthoredExpressionFact) -> str:
    if fact.kind == "source-column":
        return fact.source_column_uri
    for child in fact.arguments:
        found = _first_source_column(child)
        if found:
            return found
    for branch in fact.branches:
        for child in (branch.condition, branch.result):
            found = _first_source_column(child)
            if found:
                return found
    if fact.else_expression is not None:
        return _first_source_column(fact.else_expression)
    return ""


def _values(resource: str, predicate: str, *values: str) -> AuthoredValuesFact:
    return AuthoredValuesFact(resource, predicate, tuple(values))


def adapt_binding(binding: EntityBinding, context: ResolutionContext) -> BoundSources:
    """Adapt one parsed :class:`EntityBinding` to a complete graph-free ``BoundSources``.

    Resolves the binding's source relation, target class, and field properties against
    ``context`` and converts every field expression into an ``AuthoredExpressionFact`` whose
    metadata is derived from the same DD-107 rules the downstream normalizer re-validates. A
    neutral DD-106 passthrough preparation policy and a DD-108 identity policy are synthesized
    internally (never authored as TTL). Raises :class:`CompileError` with ordered,
    source-located diagnostics for any unresolved symbol or malformed field.
    """
    diagnostics: list[CompileDiagnostic] = []
    path = binding.source_path or "<binding>"

    if binding.source.dbt_model and not binding.source.relation:
        raise CompileError(
            [
                CompileDiagnostic(
                    code="binding.unsupported-dbt-model-source",
                    message="contracted dbtModel sources are deferred to a later slice",
                    location=SourceLocation(path=path, pointer="/source/dbtModel"),
                )
            ]
        )

    relation = context.relation(binding.source.relation)
    klass = context.klass(binding.target_class)
    if relation is None:
        diagnostics.append(
            CompileDiagnostic(
                code="binding.unknown-relation",
                message=f"source relation '{binding.source.relation}' does not resolve",
                location=SourceLocation(path=path, pointer="/source/relation"),
            )
        )
    if klass is None:
        diagnostics.append(
            CompileDiagnostic(
                code="binding.unknown-class",
                message=f"target class '{binding.target_class}' does not resolve",
                location=SourceLocation(path=path, pointer="/target/class"),
            )
        )
    if relation is None or klass is None:
        raise CompileError(order_compile_diagnostics(diagnostics))

    symbols = {
        column.name: _Symbol(
            uri=relation.column_uri(column.name),
            type=_source_type(column.data_type) or _STRING,
            nullable=column.nullable,
        )
        for column in relation.columns
        if _source_type(column.data_type) is not None
    }

    model_name = _slug(klass.name)
    resource_base = f"urn:kairos:v5:{context.domain}:{model_name}"
    meta = OntologyMetadataSpec(iri=context.ontology_iri, version=context.ontology_version)

    builder = _ExprBuilder(symbols=symbols, source_path=path, resource_base=resource_base)
    column_mappings: list[ColumnMappingFact] = []
    column_specs: list[ColumnSpec] = []
    for index, field_map in enumerate(binding.fields):
        prop = context.property(field_map.property)
        if prop is None:
            diagnostics.append(
                CompileDiagnostic(
                    code="binding.unknown-property",
                    message=f"property '{field_map.property}' does not resolve in the ontology",
                    location=SourceLocation(path=path, pointer=f"/fields/{index}/property"),
                )
            )
            continue
        if prop.domain_uris and klass.uri not in prop.domain_uris:
            diagnostics.append(
                CompileDiagnostic(
                    code="binding.property-domain-incompatible",
                    message=(
                        f"property '{field_map.property}' does not apply to "
                        f"class '{binding.target_class}'"
                    ),
                    location=SourceLocation(path=path, pointer=f"/fields/{index}/property"),
                )
            )
            continue
        map_uri = f"{resource_base}:map:{prop.column_name}"
        target_type = _canonical_type(prop.data_type, map_uri)
        expr_fact, _out_type, nullable = builder.build(field_map.expression, target_type)
        if isinstance(field_map.expression, ExprColumn):
            expression: AuthoredExpressionFact | None = None
            source_uri = expr_fact.source_column_uri
        else:
            expression = expr_fact
            source_uri = _first_source_column(expr_fact)
            if not source_uri and not symbols:
                diagnostics.append(
                    CompileDiagnostic(
                        code="binding.unknown-column",
                        message="source relation has no usable columns",
                        location=SourceLocation(path=path, pointer=f"/fields/{index}/expression"),
                    )
                )
                continue
            source_uri = source_uri or sorted(symbol.uri for symbol in symbols.values())[0]
        column_mappings.append(
            ColumnMappingFact(
                resource_uri=map_uri,
                source_column_uri=source_uri,
                target_property_uri=prop.uri,
                match_type="exact",
                expression=expression,
                target_column_name=prop.column_name,
                target_data_type=prop.data_type,
                target_is_object_property=prop.is_object_property,
            )
        )
        column_specs.append(
            ColumnSpec(
                name=prop.column_name,
                data_type=prop.data_type,
                nullable=nullable,
                mapping_resource_uri=map_uri,
                description=prop.description,
            )
        )

    diagnostics.extend(builder.diagnostics)

    for check in binding.quality:
        if check.kind not in {"not-null", "unique"}:
            continue
        dbt_test = "not_null" if check.kind == "not-null" else "unique"
        for column in check.columns:
            source_uri = relation.column_uri(column)
            matched = False
            for index, mapping in enumerate(column_mappings):
                if mapping.source_column_uri != source_uri:
                    continue
                matched = True
                tests = tuple(dict.fromkeys((*column_specs[index].tests, dbt_test)))
                column_specs[index] = replace(column_specs[index], tests=tests)
            if not matched:
                diagnostics.append(
                    CompileDiagnostic(
                        code="binding.quality-column-unmapped",
                        message=(
                            f"quality check column '{column}' is not mapped to a target field"
                        ),
                        location=SourceLocation(path=path, pointer=check.pointer),
                    )
                )

    # Validate identity/grain columns resolve to real source columns.
    for pointer, columns in (
        ("/identity/sourceKey", binding.identity.source_key),
        ("/grain/columns", binding.grain.columns),
    ):
        for column in columns:
            if column not in symbols:
                diagnostics.append(
                    CompileDiagnostic(
                        code="binding.unknown-key-column",
                        message=f"column '{column}' is not a column of the bound relation",
                        location=SourceLocation(path=path, pointer=pointer),
                    )
                )

    strategy_value = _IDENTITY_STRATEGY.get(binding.identity.strategy)
    if strategy_value is None:
        diagnostics.append(
            CompileDiagnostic(
                code="binding.unknown-identity-strategy",
                message=f"identity strategy '{binding.identity.strategy}' is not supported",
                location=SourceLocation(path=path, pointer="/identity/strategy"),
            )
        )

    if diagnostics:
        raise CompileError(order_compile_diagnostics(diagnostics))

    bound = _assemble_bound_sources(
        binding=binding,
        context=context,
        relation=relation,
        klass=klass,
        symbols=symbols,
        model_name=model_name,
        resource_base=resource_base,
        meta=meta,
        strategy_value=strategy_value,
        column_mappings=tuple(column_mappings),
        column_specs=tuple(column_specs),
    )
    return bound


def _assemble_bound_sources(
    *,
    binding: EntityBinding,
    context: ResolutionContext,
    relation: ResolvedRelation,
    klass: ResolvedClass,
    symbols: dict[str, _Symbol],
    model_name: str,
    resource_base: str,
    meta: OntologyMetadataSpec,
    strategy_value: str,
    column_mappings: tuple[ColumnMappingFact, ...],
    column_specs: tuple[ColumnSpec, ...],
) -> BoundSources:
    class_uri = klass.uri
    system_uri = relation.system_uri or f"{relation.uri}#system"
    source_columns = tuple(
        SourceColumnFact(
            relation.column_uri(column.name),
            column.name,
            column.data_type,
            column.nullable,
            column.is_primary_key,
        )
        for column in relation.columns
    )
    pk_columns = tuple(column.name for column in relation.columns if column.is_primary_key)
    system = SourceSystemFact(
        uri=system_uri,
        label=relation.system_label,
        database=relation.database,
        schema=relation.schema,
        connection_type=relation.connection_type,
        tables=(
            SourceTableFact(
                uri=relation.uri,
                name=relation.table_name,
                label=relation.table_name,
                primary_key_columns=pk_columns,
                incremental_column=None,
                columns=source_columns,
            ),
        ),
    )

    mappings = SourceMappings(
        tables=(
            TableMappingFact(
                resource_uri=f"{resource_base}:table-map",
                source_table_uri=relation.uri,
                target_class_uri=class_uri,
                mapping_type="direct",
                match_type="exact",
            ),
        ),
        columns=column_mappings,
    )

    # Neutral DD-106 passthrough preparation policy (no cleanup/cast/CDC), one source-record key.
    prep_uri = f"{resource_base}:prep"
    record_key_uri = f"{resource_base}:record-key"
    key_component_uris = tuple(symbols[name].uri for name in binding.identity.source_key)
    prep = PreparationPolicyFact(
        resource_uri=prep_uri,
        source_table=_values(prep_uri, "sourceTable", relation.uri),
        mode=_values(prep_uri, "prepMode", "passthrough"),
        schema_change_policy=_values(prep_uri, "schemaChangePolicy", "fail"),
        normalization_evidence=None,
        renames=(),
        cleanup_rules=(),
        type_conversions=(),
        sentinel_rules=(),
        cdc=(),
        record_keys=(
            SourceRecordKeyFact(
                resource_uri=record_key_uri,
                source_scope=_values(record_key_uri, "sourceScope", relation.system_label),
                table_scope=_values(record_key_uri, "tableScope", relation.table_name),
                components=_values(record_key_uri, "components", *key_component_uris),
                outputs=(
                    PreparedColumnFact(
                        resource_uri=f"{record_key_uri}/output",
                        target_name=_values(
                            f"{record_key_uri}/output", "targetName", "_source_record_key"
                        ),
                        target_type=_values(f"{record_key_uri}/output", "targetType", "string"),
                    ),
                ),
            ),
        ),
        scalar_json=(),
        array_json=(),
        technical_dedupes=(),
    )

    natural_key_columns = binding.identity.business_key or binding.identity.source_key
    surrogate = strategy_value == "surrogate-only"
    identity = EntityIdentityFact(
        resource_uri=class_uri,
        business_grain=_values(class_uri, "businessGrain", f"one {model_name} per source grain"),
        strategy=_values(class_uri, "identityStrategy", strategy_value),
        iri_policy=_values(class_uri, "entityInstanceIriPolicy", "omit"),
        key_scope=_values(class_uri, "keyScope", "source-table"),
        source_identities=_values(class_uri, "sourceIdentity", record_key_uri),
        natural_keys=(
            _values(class_uri, "naturalKey")
            if surrogate
            else _values(class_uri, "naturalKey", *natural_key_columns)
        ),
        change_detection=_values(class_uri, "changeDetectionStrategy", "compare-columns"),
        lineage_policy=_values(class_uri, "lineagePolicy", "source-lineage-only"),
        contribution_lineage=None,
        reconciliation_limitation=(
            _values(
                class_uri,
                "reconciliationLimitation",
                "surrogate-only key does not assert cross-source business identity",
            )
            if surrogate
            else None
        ),
        driving_source=None,
        multi_source_policy_refs=None,
        scd_type=None,
        scd2_time_basis=None,
        hash_policy_refs=None,
        incremental_policy_refs=None,
    )

    model_identity = ModelIdentity(
        class_name=klass.name,
        class_uri=class_uri,
        model_name=model_name,
        domain_name=context.domain,
        schema_name=context.schema_name,
        artifact_path=f"models/{context.schema_name}/{context.domain}/{model_name}.sql",
        outcome=ModelOutcome.GENERATED,
    )
    silver_model = BoundSilverModel(
        identity=model_identity,
        kind=SilverModelKind.ENTITY,
        columns=column_specs,
        sources=(
            SourceBindingSpec(
                alias="src",
                source_name=relation.system_label,
                table_name=relation.table_name,
                table_uri=relation.uri,
            ),
        ),
        ontology_metadata=meta,
    )
    schema_model = BoundSchemaModel(
        name=model_name,
        description=klass.comment or klass.label or model_name,
        metadata=(
            ("ontology_class", klass.name),
            ("ontology_iri", context.ontology_iri),
            ("ontology_version", context.ontology_version),
        ),
        columns=column_specs,
        grain_columns=binding.grain.columns,
        source_identity_columns=("_source_system", "_source_record_key"),
        table_type="entity",
        ontology_class=klass.name,
        ontology_iri=context.ontology_iri,
        ontology_version=context.ontology_version,
    )

    return BoundSources(
        classes=(ClassFact(class_uri, klass.name, klass.label or klass.name, klass.comment),),
        namespace=context.namespace,
        ontology_name=context.ontology_name,
        ontology_metadata=meta,
        target_platform=context.target_platform,
        template_root=context.template_root,
        logical_sources_only=False,
        emit_aspirational_stubs=False,
        systems=(system,),
        mappings=mappings,
        contracts=(),
        virtual_table_uris=frozenset(),
        replacement_input_uris=frozenset(),
        source_bindings=SourceBindingsFact(
            active_contracts=(),
            virtual_table_uris=frozenset(),
            class_to_sources=(
                (
                    class_uri,
                    (SourceRefFact(relation.system_label, relation.table_name, relation.uri),),
                ),
            ),
            folded_source_targets=(),
            warnings=(),
        ),
        binding_observations=(ClassBindingObservation(class_uri, True, None, False),),
        foreign_key_facts=(),
        ontology_uri=context.ontology_iri,
        parent_relations=(),
        silver_candidates=(silver_model,),
        silver_outcomes=(),
        schema_candidates=(schema_model,),
        coverage=None,
        macro_names=(),
        warnings=(),
        policy_facts=MedallionPolicyFacts(
            ontology_uri=context.ontology_iri,
            naming_convention=None,
            preparations=(prep,),
            identities=(identity,),
            multi_source=(),
            incremental=(),
            hashes=(),
            temporal_relationships=(),
            data_quality=(),
            gold=GoldProductFact(
                ontology_uri=context.ontology_iri,
                profile=None,
                schema=None,
                measure_refs=None,
                calendar_refs=None,
                security_refs=None,
                tables=(),
                measures=(),
                calendars=(),
                security_policies=(),
            ),
            adapter_support=(),
            deviations=(),
        ),
        active_source_scope=ActiveSourceScope(
            (ActiveSourceTable(relation.uri, "physical", ("v5 binding adapter",)),)
        ),
    )


def _slug(value: str) -> str:
    out = "".join(char if char.isalnum() else "_" for char in value).strip("_").lower()
    return out or "entity"
