# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Immutable Medallion policy facts and effective specifications (DD-106--DD-115)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar

from .diagnostics import Diagnostic, DiagnosticSeverity, EvaluationStatus
from .specs import ColumnSpec, ModelIdentity


T = TypeVar("T")


class PolicySource(str, Enum):
    """How an effective policy value entered the projection contract."""

    AUTHORED = "authored"
    INHERITED = "inherited"
    DEFAULT = "default"
    OVERRIDE = "override"
    DEVIATION = "deviation"


@dataclass(frozen=True, slots=True)
class PolicyProvenance:
    """Normative and authoring evidence for one effective value."""

    source: PolicySource
    rule_id: str
    resource_uri: str = ""
    predicate_uri: str = ""
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EffectiveValue(Generic[T]):
    """A value that cannot be separated from its policy provenance."""

    value: T
    provenance: PolicyProvenance


@dataclass(frozen=True, slots=True)
class AuthoredValuesFact:
    """All RDF objects authored for one subject/predicate pair."""

    resource_uri: str
    predicate_uri: str
    values: tuple[str, ...]
    ordered: bool = False


@dataclass(frozen=True, slots=True)
class PolicyIssue:
    """A deterministic policy diagnostic carried to the release gate."""

    code: str
    message: str
    rule_id: str
    resource_uri: str
    blocking: bool = True

    @property
    def diagnostic(self) -> Diagnostic:
        """Expose this legacy issue through the versioned diagnostic contract."""

        return Diagnostic(
            code=self.code,
            message=self.message,
            rule_id=self.rule_id,
            resource_uri=self.resource_uri,
            severity=(
                DiagnosticSeverity.ERROR if self.blocking else DiagnosticSeverity.WARNING
            ),
            blocking=self.blocking,
            evaluation_status=EvaluationStatus.FAILED,
        )


class NamingConvention(str, Enum):
    CAMEL_TO_SNAKE = "camel-to-snake"


class PrepMode(str, Enum):
    PASSTHROUGH = "passthrough"
    NORMALIZE = "normalize"


class CleanupOperation(str, Enum):
    TRIM = "trim"
    LEFT_TRIM = "left-trim"
    RIGHT_TRIM = "right-trim"
    UNICODE_NORMALIZE = "unicode-normalize"
    LINE_ENDING_NORMALIZE = "line-ending-normalize"


class ErrorAction(str, Enum):
    FAIL = "fail"
    QUARANTINE = "quarantine"
    NULL_WITH_EVIDENCE = "null-with-evidence"


class SentinelAction(str, Enum):
    TO_NULL = "to-null"
    TO_NORMALIZED_VALUE = "to-normalized-value"


class SchemaEvolutionAction(str, Enum):
    FAIL = "fail"
    QUARANTINE = "quarantine"
    APPROVED_CONTRACT_UPDATE = "approved-contract-update"


class RawPayloadRetention(str, Enum):
    RETAIN_PAYLOAD = "retain-payload"
    RETAIN_REPLAYABLE_REFERENCE = "retain-replayable-reference"


class ArrayValueAction(str, Enum):
    ZERO_CHILDREN = "zero-children"
    QUARANTINE = "quarantine"
    FAIL = "fail"


class CanonicalTypeKind(str, Enum):
    STRING = "string"
    BOOLEAN = "boolean"
    INT16 = "int16"
    INT32 = "int32"
    INT64 = "int64"
    DECIMAL = "decimal"
    FLOAT64 = "float64"
    DATE = "date"
    TIME = "time"
    TIMESTAMP = "timestamp"
    BINARY = "binary"
    JSON = "json"


@dataclass(frozen=True, slots=True)
class CanonicalTypeSpec:
    """Adapter-neutral type, including bounded type parameters."""

    kind: CanonicalTypeKind
    precision: int | None = None
    scale: int | None = None
    length: int | None = None


@dataclass(frozen=True, slots=True)
class PreparedColumnFact:
    resource_uri: str
    target_name: AuthoredValuesFact
    target_type: AuthoredValuesFact
    json_path: AuthoredValuesFact | None = None


@dataclass(frozen=True, slots=True)
class PhysicalRenameFact:
    resource_uri: str
    source_column: AuthoredValuesFact
    target_name: AuthoredValuesFact


@dataclass(frozen=True, slots=True)
class CleanupRuleFact:
    resource_uri: str
    source_column: AuthoredValuesFact
    operation: AuthoredValuesFact
    lossless: AuthoredValuesFact


@dataclass(frozen=True, slots=True)
class TypeConversionFact:
    resource_uri: str
    source_column: AuthoredValuesFact
    target_type: AuthoredValuesFact
    parse_policy: AuthoredValuesFact
    error_policy: AuthoredValuesFact


@dataclass(frozen=True, slots=True)
class SentinelRuleFact:
    resource_uri: str
    source_column: AuthoredValuesFact
    sentinel_value: AuthoredValuesFact
    action: AuthoredValuesFact
    normalized_value: AuthoredValuesFact | None
    evidence: AuthoredValuesFact


@dataclass(frozen=True, slots=True)
class CdcMappingFact:
    resource_uri: str
    raw_operation_columns: AuthoredValuesFact | None
    raw_update_timestamp_columns: AuthoredValuesFact | None
    raw_effective_timestamp_columns: AuthoredValuesFact | None
    raw_ingestion_timestamp_columns: AuthoredValuesFact | None
    raw_sequence_columns: AuthoredValuesFact | None
    operation_code_map: AuthoredValuesFact | None
    normalized_operation_fields: tuple[PreparedColumnFact, ...]
    normalized_update_timestamp_fields: tuple[PreparedColumnFact, ...]
    normalized_effective_timestamp_fields: tuple[PreparedColumnFact, ...]
    normalized_ingestion_timestamp_fields: tuple[PreparedColumnFact, ...]
    normalized_sequence_fields: tuple[PreparedColumnFact, ...]


@dataclass(frozen=True, slots=True)
class SourceRecordKeyFact:
    resource_uri: str
    source_scope: AuthoredValuesFact
    table_scope: AuthoredValuesFact
    components: AuthoredValuesFact
    outputs: tuple[PreparedColumnFact, ...]


@dataclass(frozen=True, slots=True)
class ScalarJsonFact:
    resource_uri: str
    source_column: AuthoredValuesFact
    json_path: AuthoredValuesFact
    extracted_columns: tuple[PreparedColumnFact, ...]
    retention: AuthoredValuesFact
    error_policy: AuthoredValuesFact


@dataclass(frozen=True, slots=True)
class ArrayJsonFact:
    resource_uri: str
    source_column: AuthoredValuesFact
    json_path: AuthoredValuesFact
    child_relation_name: AuthoredValuesFact
    parent_key_components: AuthoredValuesFact
    element_key_path: AuthoredValuesFact | None
    element_index_field: AuthoredValuesFact | None
    null_policy: AuthoredValuesFact
    empty_policy: AuthoredValuesFact
    retention: AuthoredValuesFact
    extracted_columns: tuple[PreparedColumnFact, ...]


@dataclass(frozen=True, slots=True)
class DedupeOrderFact:
    """One explicitly ordered prep deduplication tie-breaker."""

    resource_uri: str
    source_column: AuthoredValuesFact
    position: AuthoredValuesFact
    direction: AuthoredValuesFact


@dataclass(frozen=True, slots=True)
class TechnicalDedupeFact:
    """Prep-owned partition and complete total-order authoring facts."""

    resource_uri: str
    keys: AuthoredValuesFact
    order_terms: tuple[DedupeOrderFact, ...]


@dataclass(frozen=True, slots=True)
class PreparationPolicyFact:
    resource_uri: str
    source_table: AuthoredValuesFact
    mode: AuthoredValuesFact
    schema_change_policy: AuthoredValuesFact
    normalization_evidence: AuthoredValuesFact | None
    renames: tuple[PhysicalRenameFact, ...]
    cleanup_rules: tuple[CleanupRuleFact, ...]
    type_conversions: tuple[TypeConversionFact, ...]
    sentinel_rules: tuple[SentinelRuleFact, ...]
    cdc: tuple[CdcMappingFact, ...]
    record_keys: tuple[SourceRecordKeyFact, ...]
    scalar_json: tuple[ScalarJsonFact, ...]
    array_json: tuple[ArrayJsonFact, ...]
    technical_dedupes: tuple[TechnicalDedupeFact, ...]


@dataclass(frozen=True, slots=True)
class SourceTableIdentitySpec:
    source_system_uri: str
    source_table_uri: str
    source_name: str
    table_name: str


@dataclass(frozen=True, slots=True)
class PreparedColumnSpec:
    resource_uri: str
    name: EffectiveValue[str]
    data_type: EffectiveValue[CanonicalTypeSpec]
    json_path: EffectiveValue[str] | None = None


@dataclass(frozen=True, slots=True)
class PhysicalRenameSpec:
    source_column_uri: str
    target_name: EffectiveValue[str]


@dataclass(frozen=True, slots=True)
class CleanupRuleSpec:
    source_column_uri: str
    operation: EffectiveValue[CleanupOperation]
    lossless: EffectiveValue[bool]


@dataclass(frozen=True, slots=True)
class TypeConversionSpec:
    source_column_uri: str
    target_type: EffectiveValue[CanonicalTypeSpec]
    parse_policy: EffectiveValue[str]
    error_action: EffectiveValue[ErrorAction]


@dataclass(frozen=True, slots=True)
class SentinelRuleSpec:
    source_column_uri: str
    sentinel_value: EffectiveValue[str]
    action: EffectiveValue[SentinelAction]
    normalized_value: EffectiveValue[str] | None
    evidence: EffectiveValue[tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class CdcFieldSpec:
    raw_columns: EffectiveValue[tuple[str, ...]]
    normalized_fields: tuple[PreparedColumnSpec, ...]


@dataclass(frozen=True, slots=True)
class SourceCdcSpec:
    operation: CdcFieldSpec | None
    source_updated_at: CdcFieldSpec | None
    source_effective_at: CdcFieldSpec | None
    ingested_at: CdcFieldSpec | None
    sequence: CdcFieldSpec | None
    operation_code_map: EffectiveValue[tuple[tuple[str, str], ...]] | None


@dataclass(frozen=True, slots=True)
class SourceRecordKeySpec:
    resource_uri: str
    source_scope: EffectiveValue[str]
    table_scope: EffectiveValue[str]
    components: EffectiveValue[tuple[str, ...]]
    output: PreparedColumnSpec
    establishes_business_equivalence: bool = False


@dataclass(frozen=True, slots=True)
class ScalarJsonSpec:
    resource_uri: str
    source_column_uri: str
    json_path: EffectiveValue[str]
    output: PreparedColumnSpec
    retention: EffectiveValue[RawPayloadRetention]
    error_action: EffectiveValue[ErrorAction]
    preserves_parent_grain: bool = True


@dataclass(frozen=True, slots=True)
class ArrayChildSpec:
    resource_uri: str
    source_column_uri: str
    json_path: EffectiveValue[str]
    child_relation_name: EffectiveValue[str]
    parent_key_components: EffectiveValue[tuple[str, ...]]
    element_key_path: EffectiveValue[str] | None
    element_index_field: EffectiveValue[str] | None
    null_action: EffectiveValue[ArrayValueAction]
    empty_action: EffectiveValue[ArrayValueAction]
    retention: EffectiveValue[RawPayloadRetention]
    columns: tuple[PreparedColumnSpec, ...]
    preserves_parent_grain: bool = True


class TechnicalDedupeMode(str, Enum):
    NONE = "none"
    COMPLETE_TOTAL_ORDER = "complete-total-order"
    CONTRACTED_TRANSFORMATION = "contracted-transformation"


@dataclass(frozen=True, slots=True)
class TechnicalDedupeSpec:
    mode: EffectiveValue[TechnicalDedupeMode]
    keys: EffectiveValue[tuple[str, ...]]
    total_order: EffectiveValue[tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class SchemaEvolutionSpec:
    action: EffectiveValue[SchemaEvolutionAction]


@dataclass(frozen=True, slots=True)
class PreparationSpec:
    resource_uri: str
    table: SourceTableIdentitySpec
    mode: EffectiveValue[PrepMode]
    schema_evolution: SchemaEvolutionSpec
    renames: tuple[PhysicalRenameSpec, ...]
    cleanup_rules: tuple[CleanupRuleSpec, ...]
    type_conversions: tuple[TypeConversionSpec, ...]
    sentinel_rules: tuple[SentinelRuleSpec, ...]
    cdc: SourceCdcSpec | None
    source_record_key: SourceRecordKeySpec
    scalar_json: tuple[ScalarJsonSpec, ...]
    array_children: tuple[ArrayChildSpec, ...]
    technical_dedupe: TechnicalDedupeSpec
    normalization_evidence: EffectiveValue[tuple[str, ...]]


class IdentityStrategy(str, Enum):
    BUSINESS_KEY = "business-key"
    SOURCE_SCOPED_IMMUTABLE_KEY = "source-scoped-immutable-key"
    DETERMINISTIC_INTEGRATION_KEY = "deterministic-integration-key"
    EXTERNALLY_MASTERED_IDENTIFIER = "externally-mastered-identifier"
    SURROGATE_ONLY = "surrogate-only"


class KeyScope(str, Enum):
    SOURCE_TABLE = "source-table"
    SOURCE_TABLE_ARRAY_ELEMENT = "source-table-array-element"
    DOMAIN = "domain"
    ENTERPRISE = "enterprise"


class EntityIriMode(str, Enum):
    EMIT = "emit"
    OMIT = "omit"


class ChangeDetectionStrategy(str, Enum):
    COMPARE_COLUMNS = "compare-columns"
    CANONICAL_HASH = "canonical-hash"


class DrivingSourceMode(str, Enum):
    ONLY_SOURCE = "only-source"
    DECLARED = "declared"
    NONE = "none"


class TimestampRole(str, Enum):
    LOADED_AT = "loaded-at"
    INGESTED_AT = "ingested-at"
    SOURCE_UPDATED_AT = "source-updated-at"
    SOURCE_EFFECTIVE_AT = "source-effective-at"


class TimestampOrigin(str, Enum):
    INJECTED_RUN_CLOCK = "injected-run-clock"
    SOURCE_INGESTION = "source-ingestion"
    SOURCE_UPDATE = "source-update"
    SOURCE_BUSINESS_EFFECTIVE = "source-business-effective"
    NOT_SUPPLIED = "not-supplied"


@dataclass(frozen=True, slots=True)
class TimestampSourceSpec:
    """Per-contributor timestamp provenance, including an authored absence."""

    source_identity_ref: str
    source_column: str | None
    origin: TimestampOrigin
    supplied: bool


@dataclass(frozen=True, slots=True)
class TimestampSemanticSpec:
    role: TimestampRole
    column_name: str
    origin: EffectiveValue[TimestampOrigin]
    source_column: str | None = None
    supplied: bool = False
    sources: tuple[TimestampSourceSpec, ...] = ()


@dataclass(frozen=True, slots=True)
class BusinessIdentityPolicy:
    keys: EffectiveValue[tuple[str, ...]]
    authoritative: bool


@dataclass(frozen=True, slots=True)
class SourceIdentityPolicy:
    record_key_refs: EffectiveValue[tuple[str, ...]]
    may_fallback_to_business_key: bool = False


@dataclass(frozen=True, slots=True)
class IntegrationIdentityPolicy:
    emitted: bool
    exact_equivalence_required: bool = True


@dataclass(frozen=True, slots=True)
class MasteredIdentityPolicy:
    external_identifier_refs: EffectiveValue[tuple[str, ...]]
    routed_to_mdm: bool


@dataclass(frozen=True, slots=True)
class SurrogateIdentityPolicy:
    emitted_as_join_key: bool
    establishes_business_identity: bool
    reconciliation_limitation: EffectiveValue[str] | None


@dataclass(frozen=True, slots=True)
class IriPolicy:
    mode: EffectiveValue[EntityIriMode]
    distinct_from_source_and_surrogate: bool = True


@dataclass(frozen=True, slots=True)
class DrivingSourceSpec:
    mode: EffectiveValue[DrivingSourceMode]
    source_ref: EffectiveValue[str] | None


@dataclass(frozen=True, slots=True)
class ContributionLineageSpec:
    policy: EffectiveValue[str]
    emits_all_source_records: bool


@dataclass(frozen=True, slots=True)
class ContributionLineageRelationSpec:
    """Canonical relation emitted for every governed source contribution."""

    relation_name: str
    parent_key_column: str
    source_system_column: str = "_source_system"
    source_record_key_column: str = "_source_record_key"
    source_role_column: str = "_contribution_role"
    source_identity_ref_column: str = "_source_identity_ref"


@dataclass(frozen=True, slots=True)
class LineageSpec:
    policy: EffectiveValue[str]
    contribution: ContributionLineageSpec | None
    timestamps: tuple[TimestampSemanticSpec, ...]


@dataclass(frozen=True, slots=True)
class EntityIdentityFact:
    resource_uri: str
    business_grain: AuthoredValuesFact | None
    strategy: AuthoredValuesFact | None
    iri_policy: AuthoredValuesFact | None
    key_scope: AuthoredValuesFact | None
    source_identities: AuthoredValuesFact | None
    natural_keys: AuthoredValuesFact | None
    change_detection: AuthoredValuesFact | None
    lineage_policy: AuthoredValuesFact | None
    contribution_lineage: AuthoredValuesFact | None
    reconciliation_limitation: AuthoredValuesFact | None
    driving_source: AuthoredValuesFact | None
    multi_source_policy_refs: AuthoredValuesFact | None
    scd_type: AuthoredValuesFact | None
    scd2_time_basis: AuthoredValuesFact | None
    hash_policy_refs: AuthoredValuesFact | None
    incremental_policy_refs: AuthoredValuesFact | None


@dataclass(frozen=True, slots=True)
class EntityIdentitySpec:
    entity_uri: str
    business_grain: EffectiveValue[str]
    strategy: EffectiveValue[IdentityStrategy]
    key_scope: EffectiveValue[KeyScope]
    source: SourceIdentityPolicy
    business: BusinessIdentityPolicy
    integration: IntegrationIdentityPolicy
    mastered: MasteredIdentityPolicy
    surrogate: SurrogateIdentityPolicy
    iri: IriPolicy
    driving_source: DrivingSourceSpec
    change_detection: EffectiveValue[ChangeDetectionStrategy]
    lineage: LineageSpec
    multi_source_policy_ref: str | None
    hash_policy_ref: str | None
    incremental_policy_ref: str | None


class BranchRelationship(str, Enum):
    DISJOINT = "disjoint"
    OVERLAPPING = "overlapping"
    EXACTLY_EQUIVALENT = "exactly-equivalent"


class SourcePrecedenceMode(str, Enum):
    NOT_APPLICABLE_DISJOINT = "not-applicable-disjoint"
    NONE_WITHOUT_EXACT_EQUIVALENCE = "none-without-approved-exact-equivalence"
    DECLARED_ORDER = "declared-order"


class ConflictAction(str, Enum):
    BLOCK = "block"
    QUARANTINE = "quarantine"
    RETAIN_BRANCH_VALUES = "retain-branch-values"


class CollisionAction(str, Enum):
    BLOCK = "block"
    QUARANTINE = "quarantine"
    RETAIN_SOURCE_SCOPED_IDENTITIES = "retain-source-scoped-identities"


class BranchDeleteAction(str, Enum):
    RETAIN_OTHER_BRANCHES = "retain-other-branches"
    DELETE_WHEN_ALL_BRANCHES_DELETED = "delete-when-all-branches-deleted"
    BLOCK = "block"


class BranchLateArrivalAction(str, Enum):
    RECONCILE_ON_ARRIVAL = "reconcile-on-arrival"
    QUARANTINE = "quarantine"
    BLOCK = "block"


@dataclass(frozen=True, slots=True)
class MultiSourcePolicyFact:
    resource_uri: str
    branch_relationship: AuthoredValuesFact
    normalization: AuthoredValuesFact
    source_precedence: AuthoredValuesFact
    conflict: AuthoredValuesFact
    collision: AuthoredValuesFact
    deletion: AuthoredValuesFact
    late_arrival: AuthoredValuesFact
    reconciliation_tests: AuthoredValuesFact


@dataclass(frozen=True, slots=True)
class ExactEquivalenceSpec:
    approved: bool
    rule_refs: EffectiveValue[tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class SourcePrecedenceSpec:
    mode: EffectiveValue[SourcePrecedenceMode]
    ordered_sources: EffectiveValue[tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class NormalizationSpec:
    statement: EffectiveValue[str]


@dataclass(frozen=True, slots=True)
class MultiSourcePolicySpec:
    resource_uri: str
    relationship: EffectiveValue[BranchRelationship]
    exact_equivalence: ExactEquivalenceSpec
    precedence: SourcePrecedenceSpec
    normalization: NormalizationSpec
    conflict: EffectiveValue[ConflictAction]
    collision: EffectiveValue[CollisionAction]
    deletion: EffectiveValue[BranchDeleteAction]
    late_arrival: EffectiveValue[BranchLateArrivalAction]
    reconciliation_tests: EffectiveValue[tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class MdmRoutingSpec:
    entity_uri: str
    probabilistic_matching_owner: str
    survivorship_owner: str
    persistent_enterprise_identity_owner: str
    merge_split_owner: str
    policy: PolicyProvenance


class DeleteAction(str, Enum):
    TOMBSTONE = "tombstone"
    IGNORE = "ignore"
    QUARANTINE = "quarantine"
    BLOCK = "block"
    APPLY_OPERATION = "apply-operation"


class CdcOperation(str, Enum):
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"
    SOFT_DELETE = "soft-delete"
    SNAPSHOT = "snapshot"


class LateArrivalAction(str, Enum):
    RECONCILE_WITH_LOOKBACK = "reconcile-with-lookback"
    QUARANTINE = "quarantine"
    BLOCK = "block"


class CorrectionAction(str, Enum):
    REPLACE_BY_TOTAL_ORDER = "replace-by-total-order"
    REVISE_VALID_TIME = "revise-valid-time"
    APPEND_CORRECTION = "append-correction"
    QUARANTINE = "quarantine"
    BLOCK = "block"


class ReplayAction(str, Enum):
    IDEMPOTENT_MERGE = "idempotent-merge"
    FULL_REBUILD = "full-rebuild"
    BLOCK = "block"


class BackfillAction(str, Enum):
    FULL_REBUILD_APPROVED = "full-rebuild-approved"
    RANGE_REPLAY_APPROVED = "range-replay-approved"
    BLOCK = "block"


class LookbackUnit(str, Enum):
    HOURS = "hours"
    DAYS = "days"


@dataclass(frozen=True, slots=True)
class LookbackWindowSpec:
    amount: int
    unit: LookbackUnit


class ScdType(str, Enum):
    TYPE_1 = "1"
    TYPE_2 = "2"


class Scd2TimeBasis(str, Enum):
    BUSINESS_VALID = "business-valid"
    LOAD_HISTORY = "load-history"


class TemporalMode(str, Enum):
    CURRENT = "current"
    AS_OF = "as-of"
    NONE = "none"


class IntervalBoundary(str, Enum):
    CLOSED_OPEN = "closed-open"


class LookupCardinality(str, Enum):
    ZERO_OR_ONE = "zero-or-one"
    EXACTLY_ONE = "exactly-one"


class ParentAction(str, Enum):
    FAIL = "fail"
    QUARANTINE = "quarantine"
    RETRY = "retry"
    UNKNOWN_MEMBER = "unknown-member"
    RESTATE = "restate"


@dataclass(frozen=True, slots=True)
class IncrementalPolicyFact:
    resource_uri: str
    merge_identity: AuthoredValuesFact
    cdc_operation: AuthoredValuesFact
    source_updated_at: AuthoredValuesFact
    source_effective_at: AuthoredValuesFact
    ingested_at: AuthoredValuesFact
    total_order: AuthoredValuesFact
    lookback: AuthoredValuesFact
    hard_delete: AuthoredValuesFact
    soft_delete: AuthoredValuesFact
    late_arrival: AuthoredValuesFact
    correction: AuthoredValuesFact
    replay: AuthoredValuesFact
    backfill: AuthoredValuesFact
    schema_change: AuthoredValuesFact


@dataclass(frozen=True, slots=True)
class HashPolicyFact:
    resource_uri: str
    version: AuthoredValuesFact
    algorithm: AuthoredValuesFact
    inputs: AuthoredValuesFact
    null_representation: AuthoredValuesFact


@dataclass(frozen=True, slots=True)
class TemporalRelationshipFact:
    property_uri: str
    mode: AuthoredValuesFact
    as_of_column: AuthoredValuesFact | None
    interval: AuthoredValuesFact | None
    time_zone: AuthoredValuesFact | None
    precision: AuthoredValuesFact | None
    cardinality: AuthoredValuesFact
    missing_action: AuthoredValuesFact
    ambiguous_action: AuthoredValuesFact
    late_parent_action: AuthoredValuesFact
    change_detection: AuthoredValuesFact | None


@dataclass(frozen=True, slots=True)
class CdcOrderingSpec:
    source_updated_at: EffectiveValue[str]
    source_effective_at: EffectiveValue[str]
    ingested_at: EffectiveValue[str]
    tie_breakers: EffectiveValue[tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class IncrementalPolicySpec:
    resource_uri: str
    merge_identity: EffectiveValue[tuple[str, ...]]
    cdc_operation: EffectiveValue[str]
    supported_operations: EffectiveValue[tuple[CdcOperation, ...]]
    ordering: CdcOrderingSpec
    lookback: EffectiveValue[LookbackWindowSpec]
    hard_delete: EffectiveValue[DeleteAction]
    soft_delete: EffectiveValue[DeleteAction]
    late_arrival: EffectiveValue[LateArrivalAction]
    correction: EffectiveValue[CorrectionAction]
    replay: EffectiveValue[ReplayAction]
    backfill: EffectiveValue[BackfillAction]
    schema_evolution: SchemaEvolutionSpec


@dataclass(frozen=True, slots=True)
class CanonicalHashPolicySpec:
    resource_uri: str
    contract_version: EffectiveValue[str]
    algorithm: EffectiveValue[str]
    inputs: EffectiveValue[tuple[str, ...]]
    encoding: EffectiveValue[str]
    null_representation: EffectiveValue[str]
    length_delimited: bool = True
    typed: bool = True


@dataclass(frozen=True, slots=True)
class HistorySpec:
    scd_type: EffectiveValue[ScdType]
    time_basis: EffectiveValue[Scd2TimeBasis] | None
    business_valid_from_column: str
    business_valid_to_column: str
    system_from_column: str
    system_to_column: str
    current_flag_column: str
    deleted_flag_column: str
    correction: EffectiveValue[CorrectionAction] | None


@dataclass(frozen=True, slots=True)
class SilverRuntimeAuthoritySpec:
    """The sole normalized DD-109 authority for one incremental Silver model."""

    incremental: IncrementalPolicySpec
    history: HistorySpec
    change_detection: EffectiveValue[ChangeDetectionStrategy]
    canonical_hash: CanonicalHashPolicySpec | None


@dataclass(frozen=True, slots=True)
class TemporalRelationshipSpec:
    property_uri: str
    mode: EffectiveValue[TemporalMode]
    as_of_column: EffectiveValue[str] | None
    interval: EffectiveValue[IntervalBoundary] | None
    time_zone: EffectiveValue[str] | None
    precision: EffectiveValue[str] | None
    cardinality: EffectiveValue[LookupCardinality]
    missing_action: EffectiveValue[ParentAction]
    ambiguous_action: EffectiveValue[ParentAction]
    late_parent_action: EffectiveValue[ParentAction]
    participates_in_change_detection: EffectiveValue[bool]


class DqCategory(str, Enum):
    CONTRACT = "contract"
    SOURCE = "source"
    BUSINESS = "business"
    OPERATIONAL = "operational"


class DqCheckKind(str, Enum):
    CONTRACT_SHAPE = "contract-shape"
    FRESHNESS = "freshness"
    VOLUME = "volume"
    DUPLICATE_RATE = "duplicate-rate"
    RANGE = "range"
    DISTRIBUTION = "distribution"
    RECONCILIATION = "reconciliation"
    REFERENTIAL_COVERAGE = "referential-coverage"
    CROSS_FIELD = "cross-field"


class DqSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class DqAction(str, Enum):
    WARN = "warn"
    QUARANTINE = "quarantine"
    BLOCK = "block"


class DqResultStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"
    NOT_EVALUATED = "not-evaluated"


class DqToleranceKind(str, Enum):
    """Typed interpretation of a DQ acceptance threshold."""

    COUNT = "count"
    RATIO = "ratio"
    DURATION = "duration"
    ABSOLUTE_DIFFERENCE = "absolute-difference"


@dataclass(frozen=True, slots=True)
class DataQualityRuleFact:
    resource_uri: str
    rule_id: AuthoredValuesFact
    version: AuthoredValuesFact
    category: AuthoredValuesFact
    scope: AuthoredValuesFact
    check_kind: AuthoredValuesFact
    check_expression: AuthoredValuesFact
    severity: AuthoredValuesFact
    tolerance: AuthoredValuesFact
    action: AuthoredValuesFact
    owner_role: AuthoredValuesFact
    evidence: AuthoredValuesFact
    test_refs: AuthoredValuesFact


@dataclass(frozen=True, slots=True)
class DqParameterSpec:
    """One validated, non-SQL parameter in a toolkit-owned DQ expression."""

    name: str
    values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DqExpressionSpec:
    check_kind: EffectiveValue[DqCheckKind]
    parameters: tuple[DqParameterSpec, ...]
    test_refs: EffectiveValue[tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class DqToleranceSpec:
    """Canonical threshold value whose meaning is fixed by the check kind."""

    kind: DqToleranceKind
    value: str
    unit: str = ""


@dataclass(frozen=True, slots=True)
class QuarantineEffectSpec:
    quarantines_rows: bool
    releases_source_rows: bool
    release_requires_passing_recheck: bool


@dataclass(frozen=True, slots=True)
class DataQualityRuleSpec:
    resource_uri: str
    rule_id: EffectiveValue[str]
    version: EffectiveValue[str]
    category: EffectiveValue[DqCategory]
    scope: EffectiveValue[str]
    check: DqExpressionSpec
    severity: EffectiveValue[DqSeverity]
    tolerance: EffectiveValue[DqToleranceSpec]
    owner_role: EffectiveValue[str]
    action: EffectiveValue[DqAction]
    evidence: EffectiveValue[tuple[str, ...]]
    effect: QuarantineEffectSpec
    rule_hash: str


@dataclass(frozen=True, slots=True)
class DqRuntimeFieldSpec:
    """One portable field in the imported immutable runtime-result relation."""

    name: str
    data_type: str
    nullable: bool
    description: str


@dataclass(frozen=True, slots=True)
class DqRuntimeResultContractSpec:
    schema_version: str
    relation_name: str
    fields: tuple[DqRuntimeFieldSpec, ...]
    statuses: tuple[DqResultStatus, ...]
    immutable_imported_evidence: bool = True


class SilverColumnRole(str, Enum):
    BUSINESS = "business"
    BUSINESS_NATURAL_KEY = "business-natural-key"
    SOURCE_IDENTITY = "source-identity"
    INTEGRATION_IDENTITY = "integration-identity"
    MASTERED_IDENTIFIER = "mastered-identifier"
    SURROGATE_JOIN_KEY = "surrogate-join-key"
    ENTITY_IRI = "entity-iri"
    AUDIT = "audit"
    HISTORY = "history"
    FOREIGN_KEY = "foreign-key"


@dataclass(frozen=True, slots=True)
class SilverColumnAuthoritySpec:
    column: ColumnSpec
    role: EffectiveValue[SilverColumnRole]
    nullable: EffectiveValue[bool]


@dataclass(frozen=True, slots=True)
class AuditPolicySpec:
    columns: tuple[TimestampSemanticSpec, ...]
    source_system_column: str
    source_record_key_column: str


@dataclass(frozen=True, slots=True)
class IdentityRoleSpec:
    """One explicit identity role in the generated Silver contract."""

    role: SilverColumnRole
    columns: tuple[str, ...]
    emitted: bool
    establishes_business_identity: bool
    key_scope: KeyScope
    provenance: PolicyProvenance


@dataclass(frozen=True, slots=True)
class SilverModelAuthoritySpec:
    identity: ModelIdentity
    columns: tuple[SilverColumnAuthoritySpec, ...]
    entity_identity: EntityIdentitySpec | None
    audit: AuditPolicySpec
    history: HistorySpec | None
    runtime: SilverRuntimeAuthoritySpec | None
    foreign_keys: tuple[TemporalRelationshipSpec, ...]
    quality_rules: tuple[DataQualityRuleSpec, ...]
    required_capabilities: tuple["AdapterCapability", ...]
    deviation_refs: tuple[str, ...]
    identity_roles: tuple[IdentityRoleSpec, ...] = ()
    multi_source: MultiSourcePolicySpec | None = None
    contribution_lineage: ContributionLineageRelationSpec | None = None


class GoldProfileName(str, Enum):
    DIMENSIONAL_POWERBI_V1 = "dimensional-powerbi-v1"


class GoldTableRole(str, Enum):
    FACT = "fact"
    DIMENSION = "dimension"
    BRIDGE = "bridge"


class FactType(str, Enum):
    TRANSACTION = "transaction"
    PERIODIC_SNAPSHOT = "periodic-snapshot"
    ACCUMULATING_SNAPSHOT = "accumulating-snapshot"


class DimensionExposure(str, Enum):
    CURRENT_ONLY = "current-only"
    HISTORY_ONLY = "history-only"
    DUAL = "dual"


class DimensionVersionBinding(str, Enum):
    CURRENT = "current"
    AS_OF_EVENT_DATE = "as-of-event-date"
    AS_OF_INVOICE_DATE = "as-of-invoice-date"
    AS_OF_EFFECTIVE_DATE = "as-of-effective-date"


class BridgeCardinality(str, Enum):
    ONE_TO_MANY = "one-to-many"
    MANY_TO_MANY = "many-to-many"


class MeasureLifecycle(str, Enum):
    INTENT = "intent"
    PROVISIONAL = "provisional"
    VALIDATED = "validated"
    APPROVED = "approved"


@dataclass(frozen=True, slots=True)
class GoldTablePolicyFact:
    resource_uri: str
    role: AuthoredValuesFact
    table_name: AuthoredValuesFact | None
    source_model: AuthoredValuesFact | None
    source_version: AuthoredValuesFact | None
    fact_grain: AuthoredValuesFact | None
    fact_type: AuthoredValuesFact | None
    dimension_exposure: AuthoredValuesFact | None
    version_binding: AuthoredValuesFact | None
    incremental_policy_refs: AuthoredValuesFact | None
    correction: AuthoredValuesFact | None
    late_arrival: AuthoredValuesFact | None
    bridge_grain: AuthoredValuesFact | None
    bridge_endpoints: AuthoredValuesFact | None
    bridge_endpoint_bindings: AuthoredValuesFact | None
    bridge_cardinality: AuthoredValuesFact | None
    bridge_weight_column: AuthoredValuesFact | None
    bridge_allocation: AuthoredValuesFact | None
    perspectives: AuthoredValuesFact | None


@dataclass(frozen=True, slots=True)
class MeasureFact:
    resource_uri: str
    measure_id: AuthoredValuesFact
    definition: AuthoredValuesFact
    expression: AuthoredValuesFact | None
    column_dependencies: AuthoredValuesFact | None
    measure_dependencies: AuthoredValuesFact | None
    lifecycle: AuthoredValuesFact
    data_type: AuthoredValuesFact | None
    format_string: AuthoredValuesFact | None
    folder: AuthoredValuesFact | None
    owner_role: AuthoredValuesFact | None
    tests: AuthoredValuesFact | None
    evidence: AuthoredValuesFact | None


@dataclass(frozen=True, slots=True)
class CalendarFact:
    resource_uri: str
    start_date: AuthoredValuesFact
    end_date: AuthoredValuesFact
    fiscal_year_start_month: AuthoredValuesFact
    week_pattern: AuthoredValuesFact
    locale: AuthoredValuesFact
    holiday_source: AuthoredValuesFact
    time_zone: AuthoredValuesFact
    period_closure: AuthoredValuesFact
    role_playing_dates: AuthoredValuesFact
    approval_status: AuthoredValuesFact


@dataclass(frozen=True, slots=True)
class SecurityFact:
    resource_uri: str
    entitlement_source: AuthoredValuesFact
    identity_mapping: AuthoredValuesFact
    role_policies: AuthoredValuesFact
    filter_direction: AuthoredValuesFact
    bindings: AuthoredValuesFact
    positive_tests: AuthoredValuesFact
    negative_tests: AuthoredValuesFact
    test_evidence: AuthoredValuesFact
    fail_closed: AuthoredValuesFact


@dataclass(frozen=True, slots=True)
class GoldProductFact:
    ontology_uri: str
    profile: AuthoredValuesFact | None
    schema: AuthoredValuesFact | None
    measure_refs: AuthoredValuesFact | None
    calendar_refs: AuthoredValuesFact | None
    security_refs: AuthoredValuesFact | None
    tables: tuple[GoldTablePolicyFact, ...]
    measures: tuple[MeasureFact, ...]
    calendars: tuple[CalendarFact, ...]
    security_policies: tuple[SecurityFact, ...]


@dataclass(frozen=True, slots=True)
class GoldTablePolicySpec:
    resource_uri: str
    role: EffectiveValue[GoldTableRole]
    table_name: EffectiveValue[str]
    source_model: EffectiveValue[str]
    source_version: EffectiveValue[str]
    fact_grain: EffectiveValue[str] | None
    fact_type: EffectiveValue[FactType] | None
    dimension_exposure: EffectiveValue[DimensionExposure] | None
    version_binding: EffectiveValue[DimensionVersionBinding] | None
    incremental_policy_ref: str | None
    correction: EffectiveValue[CorrectionAction] | None
    late_arrival: EffectiveValue[LateArrivalAction] | None
    bridge_grain: EffectiveValue[str] | None
    bridge_endpoints: EffectiveValue[tuple[str, str]] | None
    bridge_endpoint_bindings: EffectiveValue[tuple[str, str]] | None
    bridge_cardinality: EffectiveValue[BridgeCardinality] | None
    bridge_weight_column: EffectiveValue[str] | None
    bridge_allocation: EffectiveValue[str] | None


@dataclass(frozen=True, slots=True)
class MeasureDependencySpec:
    columns: EffectiveValue[tuple[str, ...]]
    measures: EffectiveValue[tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class MeasureSpec:
    resource_uri: str
    measure_id: EffectiveValue[str]
    definition: EffectiveValue[str]
    expression: EffectiveValue[str] | None
    dependencies: MeasureDependencySpec
    lifecycle: EffectiveValue[MeasureLifecycle]
    data_type: EffectiveValue[str] | None
    format_string: EffectiveValue[str] | None
    folder: EffectiveValue[str] | None
    owner_role: EffectiveValue[str] | None
    validation_tests: EffectiveValue[tuple[str, ...]]
    validation_evidence: EffectiveValue[tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class CalendarProfileSpec:
    resource_uri: str
    start_date: EffectiveValue[str]
    end_date: EffectiveValue[str]
    fiscal_year_start_month: EffectiveValue[int]
    week_pattern: EffectiveValue[str]
    locale: EffectiveValue[str]
    holiday_source: EffectiveValue[str]
    time_zone: EffectiveValue[str]
    period_closure: EffectiveValue[str]
    role_playing_dates: EffectiveValue[tuple[str, ...]]
    approval_status: EffectiveValue[str]

    @property
    def approved(self) -> bool:
        return self.approval_status.value == "approved"


@dataclass(frozen=True, slots=True)
class SecurityPolicySpec:
    resource_uri: str
    entitlement_source: EffectiveValue[str]
    identity_mapping: EffectiveValue[str]
    role_policies: EffectiveValue[tuple[str, ...]]
    filter_direction: EffectiveValue[str]
    bindings: EffectiveValue[tuple[str, ...]]
    positive_tests: EffectiveValue[tuple[str, ...]]
    negative_tests: EffectiveValue[tuple[str, ...]]
    test_evidence: EffectiveValue[tuple[str, ...]]
    fail_closed: EffectiveValue[bool]


@dataclass(frozen=True, slots=True)
class PerspectiveSpec:
    name: str
    table_uris: tuple[str, ...]
    is_security_boundary: bool = False


@dataclass(frozen=True, slots=True)
class GoldProductProfileSpec:
    name: GoldProfileName
    version: str
    required_capabilities: tuple["AdapterCapability", ...]


@dataclass(frozen=True, slots=True)
class GoldProductProfileRegistry:
    profiles: tuple[GoldProductProfileSpec, ...]

    def get(self, name: GoldProfileName) -> GoldProductProfileSpec:
        """Return the one exact registered profile or fail closed."""
        for profile in self.profiles:
            if profile.name is name:
                return profile
        raise ValueError(f"Unknown Gold product profile: {name.value}")


@dataclass(frozen=True, slots=True)
class GoldProductSpec:
    profile: EffectiveValue[GoldProfileName] | None
    schema: EffectiveValue[str] | None
    tables: tuple[GoldTablePolicySpec, ...]
    measures: tuple[MeasureSpec, ...]
    calendar: CalendarProfileSpec | None
    security: SecurityPolicySpec | None
    perspectives: tuple[PerspectiveSpec, ...]


class AdapterName(str, Enum):
    FABRIC = "fabric"
    DATABRICKS = "databricks"


class AdapterCapability(str, Enum):
    CANONICAL_TYPES = "canonical-types"
    CANONICAL_SHA256_HASH = "canonical-sha256-hash"
    JSON_SCALAR = "json-scalar"
    JSON_ARRAY_CHILD = "json-array-child"
    MERGE_UPSERT = "merge-upsert"
    DELETE_SEMANTICS = "delete-semantics"
    WINDOW_FUNCTIONS = "window-functions"
    TEMPORAL_LOOKUP = "temporal-lookup"
    CONSTRAINTS = "constraints"
    PHYSICAL_LAYOUT = "physical-layout"
    QUARANTINE = "quarantine"
    DBT_TESTS = "dbt-tests"
    SECURITY_RLS_OLS = "security-rls-ols"
    TMDL = "tmdl"


class CapabilitySupport(str, Enum):
    SUPPORTED = "supported"
    DEVIATION_REQUIRED = "deviation-required"
    UNSUPPORTED = "unsupported"


class CapabilityDisposition(str, Enum):
    SUPPORTED = "supported"
    DEVIATION = "deviation"
    BLOCKING = "blocking"


class AdapterEvidenceStatus(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    PARTIAL = "partial"
    ENVIRONMENT_BLOCKED = "environment-blocked"


@dataclass(frozen=True, slots=True)
class CanonicalTypeMappingSpec:
    semantic_type: CanonicalTypeKind
    physical_type: str
    lossy: bool
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AdapterCapabilitySpec:
    capability: AdapterCapability
    support: CapabilitySupport
    rule_id: str
    evidence: tuple[str, ...]
    allowed_deviation: bool = False


@dataclass(frozen=True, slots=True)
class AdapterSpec:
    name: AdapterName
    version: str
    type_mappings: tuple[CanonicalTypeMappingSpec, ...]
    capabilities: tuple[AdapterCapabilitySpec, ...]
    reserved_identifiers: frozenset[str] = frozenset()
    preparation_features: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class AdapterSupportFact:
    resource_uri: str
    adapter_name: AuthoredValuesFact
    adapter_version: AuthoredValuesFact
    scope: AuthoredValuesFact
    capabilities: AuthoredValuesFact
    status: AuthoredValuesFact
    compile_evidence: AuthoredValuesFact | None


@dataclass(frozen=True, slots=True)
class AdapterEvidenceSpec:
    resource_uri: str
    adapter: EffectiveValue[AdapterName]
    adapter_version: EffectiveValue[str]
    scope: EffectiveValue[str]
    capabilities: EffectiveValue[tuple[AdapterCapability, ...]]
    status: EffectiveValue[AdapterEvidenceStatus]
    compile_evidence: EffectiveValue[tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class DeviationFact:
    resource_uri: str
    adapter_name: AuthoredValuesFact | None
    policy_reference: AuthoredValuesFact
    scope: AuthoredValuesFact
    rationale: AuthoredValuesFact
    owner_role: AuthoredValuesFact
    approval_status: AuthoredValuesFact
    review_date: AuthoredValuesFact
    expiry_date: AuthoredValuesFact
    evidence: AuthoredValuesFact


@dataclass(frozen=True, slots=True)
class ApprovedDeviationSpec:
    resource_uri: str
    adapter: AdapterName | None
    policy_reference: EffectiveValue[str]
    scope: EffectiveValue[str]
    rationale: EffectiveValue[str]
    owner_role: EffectiveValue[str]
    approval_status: EffectiveValue[str]
    review_date: EffectiveValue[str]
    expiry_date: EffectiveValue[str]
    evidence: tuple[str, ...]

    @property
    def approved(self) -> bool:
        """Return whether this record can ever authorize a deviation."""
        return self.approval_status.value == "approved"


@dataclass(frozen=True, slots=True)
class CapabilityRequirementSpec:
    capability: AdapterCapability
    scope: str
    rule_id: str


@dataclass(frozen=True, slots=True)
class CapabilityResultSpec:
    adapter: AdapterName
    capability: AdapterCapability
    disposition: CapabilityDisposition
    rule_id: str
    scope: str
    evidence: tuple[str, ...]
    deviation_ref: str | None = None
    message: str = ""


@dataclass(frozen=True, slots=True)
class AdapterCapabilityRegistry:
    version: str
    adapters: tuple[AdapterSpec, ...]

    def adapter(self, name: AdapterName) -> AdapterSpec:
        """Return an exact adapter record; no fallback adapter exists."""
        for adapter in self.adapters:
            if adapter.name is name:
                return adapter
        raise ValueError(f"Unknown adapter: {name.value}")


@dataclass(frozen=True, slots=True)
class MedallionPolicyFacts:
    ontology_uri: str
    naming_convention: AuthoredValuesFact | None
    preparations: tuple[PreparationPolicyFact, ...]
    identities: tuple[EntityIdentityFact, ...]
    multi_source: tuple[MultiSourcePolicyFact, ...]
    incremental: tuple[IncrementalPolicyFact, ...]
    hashes: tuple[HashPolicyFact, ...]
    temporal_relationships: tuple[TemporalRelationshipFact, ...]
    data_quality: tuple[DataQualityRuleFact, ...]
    gold: GoldProductFact
    adapter_support: tuple[AdapterSupportFact, ...]
    deviations: tuple[DeviationFact, ...]


@dataclass(frozen=True, slots=True)
class MedallionPolicySpec:
    version: str
    target_adapter: EffectiveValue[AdapterName]
    naming_convention: EffectiveValue[NamingConvention]
    preparations: tuple[PreparationSpec, ...]
    identities: tuple[EntityIdentitySpec, ...]
    multi_source: tuple[MultiSourcePolicySpec, ...]
    incremental: tuple[IncrementalPolicySpec, ...]
    hashes: tuple[CanonicalHashPolicySpec, ...]
    temporal_relationships: tuple[TemporalRelationshipSpec, ...]
    data_quality: tuple[DataQualityRuleSpec, ...]
    dq_runtime_result: DqRuntimeResultContractSpec
    silver_models: tuple[SilverModelAuthoritySpec, ...]
    gold_registry: GoldProductProfileRegistry
    gold: GoldProductSpec
    mdm_routing: tuple[MdmRoutingSpec, ...]
    adapter_evidence: tuple[AdapterEvidenceSpec, ...]
    deviations: tuple[ApprovedDeviationSpec, ...]
    capability_requirements: tuple[CapabilityRequirementSpec, ...]
    issues: tuple[PolicyIssue, ...]
