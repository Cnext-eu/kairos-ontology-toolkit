# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Immutable authored facts and effective scalar mapping contracts (DD-107)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .policy_specs import CanonicalTypeSpec


MAX_MAPPING_AST_DEPTH = 64


class MappingContractError(ValueError):
    """An actionable DD-107 mapping-contract failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        resource_uri: str = "",
        predicate_uri: str = "",
        rule_id: str = "DD-107",
    ) -> None:
        self.code = code
        self.resource_uri = resource_uri
        self.predicate_uri = predicate_uri
        self.rule_id = rule_id
        location = resource_uri or "<mapping>"
        predicate = f" ({predicate_uri})" if predicate_uri else ""
        super().__init__(f"{code}: {message} at {location}{predicate} [{rule_id}]")


class MappingExpressionKind(str, Enum):
    """The closed v2 scalar-expression node kinds."""

    SOURCE_COLUMN = "source-column"
    LITERAL = "literal"
    NULL = "null"
    OPERATOR = "operator"
    FUNCTION = "function"
    CASE = "case"
    MACRO = "macro"


class MappingNullPolicy(str, Enum):
    """Declared SQL-null behavior for one scalar node."""

    PROPAGATE = "propagate"
    NEVER_NULL = "never-null"
    THREE_VALUED = "three-valued"
    FIRST_NON_NULL = "first-non-null"
    NULL_IF_EQUAL = "null-if-equal"
    BRANCH = "branch"
    EXPLICIT_NULL = "explicit-null"


class MappingDeterminism(str, Enum):
    """Only deterministic expressions can enter a normal mapping."""

    DETERMINISTIC = "deterministic"


class MappingCapability(str, Enum):
    """Portable expression features negotiated for Fabric and Databricks."""

    SOURCE_COLUMN = "source-column"
    TYPED_LITERAL = "typed-literal"
    SCALAR_OPERATOR = "scalar-operator"
    SCALAR_FUNCTION = "scalar-function"
    NULL_HANDLING = "null-handling"
    CASE_EXPRESSION = "case-expression"
    NAMESPACED_MACRO = "namespaced-macro"


class MappingRoute(str, Enum):
    """How a mapping reaches Silver."""

    DIRECT = "direct"
    PREPARED = "prepared"
    CONTRACTED_TRANSFORMATION = "contracted-transformation"


@dataclass(frozen=True, slots=True)
class AuthoredCaseBranchFact:
    """One ordered authored CASE branch."""

    resource_uri: str
    condition: "AuthoredExpressionFact"
    result: "AuthoredExpressionFact"


@dataclass(frozen=True, slots=True)
class AuthoredExpressionFact:
    """Graph-free structural copy of one authored expression node."""

    resource_uri: str
    kind: str
    output_type: str
    nullable: str
    null_policy: str
    determinism: str
    capabilities: tuple[str, ...]
    source_column_uri: str = ""
    literal_lexical: str = ""
    literal_datatype: str = ""
    operation: str = ""
    macro_uri: str = ""
    arguments: tuple["AuthoredExpressionFact", ...] = ()
    branches: tuple[AuthoredCaseBranchFact, ...] = ()
    else_expression: "AuthoredExpressionFact | None" = None


@dataclass(frozen=True, slots=True)
class TableMappingFact:
    """One v2 source-table to domain-class mapping."""

    resource_uri: str
    source_table_uri: str
    target_class_uri: str
    mapping_type: str
    match_type: str
    row_filter: AuthoredExpressionFact | None = None


@dataclass(frozen=True, slots=True)
class ColumnMappingFact:
    """One v2 source-column to domain-property mapping."""

    resource_uri: str
    source_column_uri: str
    target_property_uri: str
    match_type: str
    expression: AuthoredExpressionFact | None = None
    target_column_name: str = ""
    target_data_type: str = ""
    target_is_object_property: bool = False
    target_declared: bool = True


@dataclass(frozen=True, slots=True)
class SourceMappings:
    """Ordered v2 mapping authoring facts."""

    tables: tuple[TableMappingFact, ...]
    columns: tuple[ColumnMappingFact, ...]
    namespaces: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class MappingInputSpec:
    """One source symbol resolved to exactly one governed relation and physical name."""

    source_column_uri: str
    source_table_uri: str
    source_name: str
    authored_name: str
    physical_name: str
    data_type: CanonicalTypeSpec
    nullable: bool
    origin: str


@dataclass(frozen=True, slots=True)
class MappingExpressionProvenance:
    """Authoring and policy provenance retained on every expression node."""

    mapping_resource_uri: str
    expression_resource_uri: str
    source: str
    rule_id: str = "DD-107"


@dataclass(frozen=True, slots=True)
class MappingExpressionMetadata:
    """The complete effective contract shared by every expression node."""

    output_type: CanonicalTypeSpec
    nullable: bool
    null_policy: MappingNullPolicy
    determinism: MappingDeterminism
    referenced_inputs: tuple[MappingInputSpec, ...]
    capability_requirements: tuple[MappingCapability, ...]
    supported_adapters: tuple[str, ...]
    provenance: MappingExpressionProvenance


@dataclass(frozen=True, slots=True)
class SourceColumnExpression:
    """A bound source-column symbol, never an authored SQL identifier."""

    metadata: MappingExpressionMetadata
    input: MappingInputSpec


@dataclass(frozen=True, slots=True)
class LiteralExpression:
    """A validated typed literal retained in lexical form for safe rendering."""

    metadata: MappingExpressionMetadata
    lexical: str
    datatype_uri: str


@dataclass(frozen=True, slots=True)
class NullExpression:
    """An explicitly typed SQL NULL."""

    metadata: MappingExpressionMetadata


@dataclass(frozen=True, slots=True)
class OperatorExpression:
    """A closed-set deterministic scalar operator."""

    metadata: MappingExpressionMetadata
    operator: str
    arguments: tuple["MappingExpression", ...]


@dataclass(frozen=True, slots=True)
class FunctionExpression:
    """A closed-set deterministic scalar function."""

    metadata: MappingExpressionMetadata
    function: str
    arguments: tuple["MappingExpression", ...]


@dataclass(frozen=True, slots=True)
class CaseBranchSpec:
    """One ordered, typed CASE branch."""

    condition: "MappingExpression"
    result: "MappingExpression"


@dataclass(frozen=True, slots=True)
class CaseExpression:
    """A searched CASE with an explicit ELSE expression."""

    metadata: MappingExpressionMetadata
    branches: tuple[CaseBranchSpec, ...]
    else_expression: "MappingExpression"


@dataclass(frozen=True, slots=True)
class MacroExpression:
    """An invocation of an exact approved namespaced macro IRI."""

    metadata: MappingExpressionMetadata
    macro_uri: str
    macro_name: str
    arguments: tuple["MappingExpression", ...]


MappingExpression = (
    SourceColumnExpression
    | LiteralExpression
    | NullExpression
    | OperatorExpression
    | FunctionExpression
    | CaseExpression
    | MacroExpression
)


@dataclass(frozen=True, slots=True)
class TableMappingSpec:
    """Validated table mapping and optional typed discriminator predicate."""

    resource_uri: str
    source_table_uri: str
    target_class_uri: str
    mapping_type: str
    match_type: str
    row_filter: MappingExpression | None
    route: MappingRoute
    contract_name: str = ""


@dataclass(frozen=True, slots=True)
class ColumnMappingSpec:
    """Validated scalar mapping expression and lineage."""

    resource_uri: str
    source_column_uri: str
    target_property_uri: str
    target_column_name: str
    target_data_type: CanonicalTypeSpec
    match_type: str
    expression: MappingExpression
    route: MappingRoute
    contract_name: str = ""


@dataclass(frozen=True, slots=True)
class MappingCapabilityResult:
    """One adapter/capability result included in release evidence."""

    mapping_resource_uri: str
    adapter: str
    capability: MappingCapability
    supported: bool
    rule_id: str = "DD-107-adapter-capability"
    reason: str = ""


@dataclass(frozen=True, slots=True)
class TransformationAuthoritySpec:
    """Approved contracted-transformation authority retained in mapping release data."""

    name: str
    target_class_uri: str
    virtual_source_iri: str
    replaces_source_iris: tuple[str, ...]
    supported_adapters: tuple[str, ...]
    grain_key: tuple[str, ...]
    decision_statuses: tuple[str, ...]
    evidence_artifacts: tuple[str, ...]
    verified_tests: tuple[str, ...]
    approved: bool


@dataclass(frozen=True, slots=True)
class MappingContractSpec:
    """Complete normalized v2 mapping authority."""

    tables: tuple[TableMappingSpec, ...]
    columns: tuple[ColumnMappingSpec, ...]
    namespaces: tuple[tuple[str, str], ...]
    capability_results: tuple[MappingCapabilityResult, ...]
    version: str = "2.0"
    transformation_authorities: tuple[TransformationAuthoritySpec, ...] = ()

    def column(self, resource_uri: str) -> ColumnMappingSpec | None:
        """Return one exact column mapping by stable resource IRI."""

        return next(
            (item for item in self.columns if item.resource_uri == resource_uri),
            None,
        )

    def table(self, resource_uri: str) -> TableMappingSpec | None:
        """Return one exact table mapping by stable resource IRI."""

        return next(
            (item for item in self.tables if item.resource_uri == resource_uri),
            None,
        )
