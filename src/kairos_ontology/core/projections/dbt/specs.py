# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Deeply immutable facts, logical specs, and physical dbt plans (DD-110)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .mapping_specs import (
        MappingCapabilityResult,
        MappingContractSpec,
        MappingExpression,
        MappingInputSpec,
    )
    from .policy_specs import (
        CanonicalTypeSpec,
        CapabilityResultSpec,
        DataQualityRuleSpec,
        SilverRuntimeAuthoritySpec,
        SilverModelAuthoritySpec,
        TemporalRelationshipSpec,
    )


class ModelOutcome(str, Enum):
    """The logical outcome of attempting to build a projected model."""

    GENERATED = "generated"
    SKIPPED = "skipped"
    FOLDED = "folded"


class SilverModelKind(str, Enum):
    """Logical Silver model form, independent of a rendering template."""

    ENTITY = "entity"
    SOURCE_BRANCH = "source_branch"
    UNION = "union"
    CONTRIBUTION_LINEAGE = "contribution_lineage"
    RECONCILIATION = "reconciliation"


Scalar = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class FrozenSequence:
    """An immutable sequence nested in a template value."""

    values: tuple["FrozenValue", ...]


@dataclass(frozen=True, slots=True)
class FrozenMapping:
    """An immutable mapping nested in a template value."""

    entries: tuple[tuple[str, "FrozenValue"], ...]


FrozenValue = Scalar | FrozenSequence | FrozenMapping


@dataclass(frozen=True, slots=True)
class OntologyMetadataSpec:
    """Provenance values consumed by current SQL/YAML templates."""

    generated_at: str = ""
    iri: str = ""
    version: str = ""
    toolkit_version: str = ""
    closure_hash: str = ""
    silver_default_packages: tuple[str, ...] = ()
    silver_overrides: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ClassFact:
    """One projected ontology class copied out of the authoring graph."""

    uri: str
    name: str
    label: str
    comment: str


@dataclass(frozen=True, slots=True)
class EnumValueFact:
    """One source enumeration value."""

    code: str
    label: str


@dataclass(frozen=True, slots=True)
class JsonFieldFact:
    """One typed field in a source JSON column."""

    name: str
    data_type: str
    path: str
    max_length: int


@dataclass(frozen=True, slots=True)
class JsonColumnFact:
    """JSON-specific source-column metadata."""

    content_type: str
    json_path: str
    fields: tuple[JsonFieldFact, ...]


@dataclass(frozen=True, slots=True)
class SourceColumnFact:
    """A source-vocabulary column consumed during binding."""

    uri: str
    name: str
    data_type: str
    nullable: bool
    is_primary_key: bool
    json: JsonColumnFact | None = None
    enum_values: tuple[EnumValueFact, ...] = ()
    origin: str = "raw"


@dataclass(frozen=True, slots=True)
class SourceTableFact:
    """A source-vocabulary table consumed during binding."""

    uri: str
    name: str
    label: str
    primary_key_columns: tuple[str, ...]
    incremental_column: str | None
    columns: tuple[SourceColumnFact, ...]
    discriminator_column: str | None = None
    discriminator_values: tuple[EnumValueFact, ...] = ()
    relation_kind: str = "physical"
    ref_model: str = ""
    parent_table_uri: str = ""


@dataclass(frozen=True, slots=True)
class SourceSystemFact:
    """A bound source system; no RDF vocabulary object survives this record."""

    uri: str
    label: str
    database: str
    schema: str
    connection_type: str
    tables: tuple[SourceTableFact, ...]


@dataclass(frozen=True, slots=True)
class ContractFact:
    """The contract fields needed after bind has consumed contract files."""

    name: str
    materialization: str
    target_class: str
    virtual_source_iri: str
    supported_adapters: tuple[str, ...]
    grain_key: tuple[str, ...]
    replaces_source_iris: tuple[str, ...] = ()
    decision_statuses: tuple[str, ...] = ()
    evidence_artifacts: tuple[str, ...] = ()
    verified_tests: tuple[str, ...] = ()
    approved: bool = False
    identity_resource_uri: str = ""
    content_hash: str = ""
    identity_requirements: tuple[str, ...] = ()
    identity_verified: bool = False
    canonical_cdc_bindings: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class SourceRefFact:
    """A canonical class-to-source binding."""

    source_name: str
    table_name: str
    table_uri: str
    mapped_target_uri: str | None = None


@dataclass(frozen=True, slots=True)
class SourceBindingsFact:
    """Deeply immutable source-binding observations made during bind."""

    active_contracts: tuple[tuple[str, ContractFact], ...]
    virtual_table_uris: frozenset[str]
    class_to_sources: tuple[tuple[str, tuple[SourceRefFact, ...]], ...]
    folded_source_targets: tuple[tuple[SourceRefFact, str], ...]
    warnings: tuple[str, ...]

    def sources_for(self, class_uri: str) -> tuple[SourceRefFact, ...]:
        """Return the committed source references for one class."""
        return next(
            (sources for uri, sources in self.class_to_sources if uri == class_uri),
            (),
        )

    def contract_for(self, class_uri: str) -> ContractFact | None:
        """Return the active transformation contract for one class."""
        return next(
            (contract for uri, contract in self.active_contracts if uri == class_uri),
            None,
        )


@dataclass(frozen=True, slots=True)
class ClassBindingObservation:
    """Raw bind observations normalized into an effective binding policy later."""

    class_uri: str
    has_sources: bool
    discriminator_parent_name: str | None


@dataclass(frozen=True, slots=True)
class BindingPolicy:
    """Normalized, immutable per-class materialization classification."""

    states: tuple[tuple[str, str], ...]
    reasons: tuple[tuple[str, str], ...]

    def state(self, class_uri: str) -> str:
        return next((state for uri, state in self.states if uri == class_uri), "skipped")

    def reason(self, class_uri: str) -> str:
        return next(
            (reason for uri, reason in self.reasons if uri == class_uri),
            "no source binding",
        )

    def is_bound(self, class_uri: str) -> bool:
        return self.state(class_uri) == "bound"


@dataclass(frozen=True, slots=True)
class ForeignKeyDiagnosticSpec:
    """Graph-free FK authoring diagnostic."""

    kind: str
    property_uri: str
    message: str


@dataclass(frozen=True, slots=True)
class ForeignKeyDescriptorSpec:
    """Graph-free normalized relationship policy."""

    property_uri: str
    domain_class: str
    range_class: str
    source_class: str
    target_class: str
    is_functional: bool
    max_cardinality_classes: frozenset[str]
    silver_foreign_key: bool
    silver_column_name: str | None
    redirected: bool
    reverse: bool
    junction_table_name: str | None
    nullable: bool | None
    conditional_on_type: str
    silver_applicable_classes: frozenset[str] = frozenset()

    def qualifies_silver(self, class_uri: str | None = None) -> bool:
        """Return whether the canonical Silver FK signals apply to a class."""
        if class_uri is not None and self.silver_applicable_classes:
            return class_uri in self.silver_applicable_classes
        property_signal = (
            self.redirected
            or self.silver_foreign_key
            or self.silver_column_name is not None
            or self.is_functional
        )
        if property_signal:
            return True
        if class_uri is None:
            return bool(self.max_cardinality_classes)
        return class_uri in self.max_cardinality_classes


@dataclass(frozen=True, slots=True)
class ForeignKeyPolicy:
    """Complete graph-free effective FK classification."""

    descriptors: tuple[ForeignKeyDescriptorSpec, ...]
    diagnostics: tuple[ForeignKeyDiagnosticSpec, ...]
    outgoing_relationship_sources: tuple[str, ...]


#: The dbt package name the hub emits, and therefore the name a dataplatform must give
#: to `overrides:` when it rebinds one of the package's sources (#701). Shared so the
#: emitter and the dataplatform scaffold cannot drift apart on it.
HUB_DBT_PACKAGE_NAME = "kairos_medallion_project"


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    """Stable identity and generation outcome for one logical model."""

    class_name: str
    class_uri: str
    model_name: str
    domain_name: str
    schema_name: str
    artifact_path: str | None
    outcome: ModelOutcome
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    """A logical projected column independent of its output encoding."""

    name: str
    expression: str = ""
    data_type: str = ""
    canonical_type: "CanonicalTypeSpec | None" = None
    nullable: bool | None = None
    default_expression: str = ""
    role: str = ""
    description: str = ""
    metadata: tuple[tuple[str, str], ...] = ()
    tests: tuple[FrozenValue, ...] = ()
    provenance: tuple[str, ...] = ()
    generated_after_mapping: bool = False
    runtime_generated: bool = False
    include_in_change_detection: bool = True
    mapping_resource_uri: str = ""
    mapping_expression: "MappingExpression | None" = None


@dataclass(frozen=True, slots=True)
class SourceBindingSpec:
    """A committed input relation for a Silver or Gold model."""

    alias: str
    source_name: str = ""
    table_name: str = ""
    table_uri: str = ""
    model_name: str = ""
    filter_condition: str = ""
    filter_mapping_resource_uri: str = ""
    filter_expression: "MappingExpression | None" = None
    ref_model: str = ""
    generator: str = ""
    generator_argument: int = 0


@dataclass(frozen=True, slots=True)
class ForeignKeySpec:
    """A logical FK relationship or lookup join."""

    column: str
    referenced_table: str
    referenced_column: str
    label: str


@dataclass(frozen=True, slots=True)
class SilverKeySpec:
    """One exact logical key or grain declaration."""

    columns: tuple[str, ...]
    predicate: str = ""
    provenance: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SilverForeignKeySpec:
    """One emitted Silver relationship, including its temporal lookup contract."""

    property_uri: str
    columns: tuple[str, ...]
    referenced_model: str
    referenced_columns: tuple[str, ...]
    label: str
    temporal_mode: str
    as_of_column: str = ""
    interval: str = ""
    cardinality: str = ""
    missing_action: str = ""
    ambiguous_action: str = ""
    late_parent_action: str = ""
    participates_in_change_detection: bool = False
    provenance: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class JoinSpec:
    """A SQL-independent join decision with its committed predicate."""

    join_type: str
    alias: str
    condition: str
    referenced_model: str = ""
    fk_column: str = ""
    source_alias: str = ""
    source_column_uris: tuple[str, ...] = ()
    source_inputs: tuple["MappingInputSpec", ...] = ()
    target_columns: tuple[str, ...] = ()
    relationship_uri: str = ""
    temporal_mode: str = ""
    as_of_column: str = ""
    parent_valid_from_column: str = "_business_valid_from"
    parent_valid_to_column: str = "_business_valid_to"


@dataclass(frozen=True, slots=True)
class MaterializationIntent:
    """Logical dbt materialization intent."""

    kind: str
    unique_key: tuple[str, ...] = ()
    incremental_column: str = ""


@dataclass(frozen=True, slots=True)
class ScdSpec:
    """History/change-detection configuration for a logical model."""

    scd_type: str = ""
    hash_columns: tuple[str, ...] = ()
    valid_from_expression: str = ""
    current_row_filter: str = ""


@dataclass(frozen=True, slots=True)
class CanonicalHashColumnSpec:
    """One ordered, typed physical column in a canonical hash contract."""

    property_uri: str
    column_name: str
    data_type: "CanonicalTypeSpec"


@dataclass(frozen=True, slots=True)
class RuntimeModelSpec:
    """Logical DD-109 execution contract resolved for one Silver model."""

    authority: "SilverRuntimeAuthoritySpec"
    canonical_hash_columns: tuple[CanonicalHashColumnSpec, ...] = ()
    compare_columns: tuple[str, ...] = ()
    ordering_columns: tuple[str, ...] = ()
    temporal_relationships: tuple["TemporalRelationshipSpec", ...] = ()


@dataclass(frozen=True, slots=True)
class SilverModelSpec:
    """Sole immutable logical authority for every emitted Silver representation."""

    identity: ModelIdentity
    kind: SilverModelKind
    columns: tuple[ColumnSpec, ...]
    sources: tuple[SourceBindingSpec, ...] = ()
    joins: tuple[JoinSpec, ...] = ()
    materialization_intent: MaterializationIntent = MaterializationIntent("table")
    ontology_metadata: OntologyMetadataSpec = OntologyMetadataSpec()
    where_clause: str = ""
    source_models: tuple[str, ...] = ()
    surrogate_key_expression: str = ""
    integration_key_expression: str = ""
    iri_expression: str = ""
    parent_model: str = ""
    source_identity_ref: str = ""
    source_record_key_expression: str = ""
    source_record_key_generated_after_mapping: bool = False
    authority: "SilverModelAuthoritySpec | None" = None
    runtime: RuntimeModelSpec | None = None
    primary_key: SilverKeySpec | None = None
    unique_keys: tuple[SilverKeySpec, ...] = ()
    grain: SilverKeySpec | None = None
    foreign_keys: tuple[SilverForeignKeySpec, ...] = ()
    comment: str = ""
    provenance: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BoundSilverModel:
    """Graph-derived Silver candidate copied into a logical spec by shape."""

    identity: ModelIdentity
    kind: SilverModelKind
    columns: tuple[ColumnSpec, ...]
    sources: tuple[SourceBindingSpec, ...] = ()
    joins: tuple[JoinSpec, ...] = ()
    requested_materialization: MaterializationIntent = MaterializationIntent("table")
    ontology_metadata: OntologyMetadataSpec = OntologyMetadataSpec()
    where_clause: str = ""
    source_models: tuple[str, ...] = ()
    surrogate_key_expression: str = ""
    integration_key_expression: str = ""
    iri_expression: str = ""
    parent_model: str = ""
    source_identity_ref: str = ""
    source_record_key_expression: str = ""
    source_record_key_generated_after_mapping: bool = False


@dataclass(frozen=True, slots=True)
class NormalizedSilverModel:
    """Silver candidate after normalize has committed effective policy."""

    identity: ModelIdentity
    kind: SilverModelKind
    columns: tuple[ColumnSpec, ...]
    sources: tuple[SourceBindingSpec, ...] = ()
    joins: tuple[JoinSpec, ...] = ()
    materialization_intent: MaterializationIntent = MaterializationIntent("table")
    ontology_metadata: OntologyMetadataSpec = OntologyMetadataSpec()
    where_clause: str = ""
    source_models: tuple[str, ...] = ()
    surrogate_key_expression: str = ""
    integration_key_expression: str = ""
    iri_expression: str = ""
    parent_model: str = ""
    source_identity_ref: str = ""
    source_record_key_expression: str = ""
    source_record_key_generated_after_mapping: bool = False
    authority: "SilverModelAuthoritySpec | None" = None


@dataclass(frozen=True, slots=True)
class SilverModelOutcome:
    """Registry/report facts produced by Silver logical construction."""

    identity: ModelIdentity
    scd_type: str | None
    source_count: int
    column_names: tuple[str, ...]
    fk_join_count: int
    info_notes: tuple[str, ...] = ()
    model_name_reported: bool = False
    info_notes_reported: bool = False


@dataclass(frozen=True, slots=True)
class SchemaModelSpec:
    """Logical dbt schema model, including tests and grain assertions."""

    name: str
    description: str
    metadata: tuple[tuple[str, str], ...]
    columns: tuple[ColumnSpec, ...]
    grain_columns: tuple[str, ...] = ()
    source_identity_columns: tuple[str, ...] = ()
    grain_where: str = ""
    table_type: str = ""
    ontology_class: str = ""
    ontology_iri: str = ""
    ontology_version: str = ""
    data_tests: tuple[FrozenValue, ...] = ()
    authority: "SilverModelAuthoritySpec | None" = None


@dataclass(frozen=True, slots=True)
class BoundSchemaModel:
    """Graph-derived schema candidate emitted by bind."""

    name: str
    description: str
    metadata: tuple[tuple[str, str], ...]
    columns: tuple[ColumnSpec, ...]
    grain_columns: tuple[str, ...] = ()
    source_identity_columns: tuple[str, ...] = ()
    grain_where: str = ""
    table_type: str = ""
    ontology_class: str = ""
    ontology_iri: str = ""
    ontology_version: str = ""


@dataclass(frozen=True, slots=True)
class NormalizedSchemaModel:
    """Schema candidate after normalize has committed policy."""

    name: str
    description: str
    metadata: tuple[tuple[str, str], ...]
    columns: tuple[ColumnSpec, ...]
    grain_columns: tuple[str, ...] = ()
    source_identity_columns: tuple[str, ...] = ()
    grain_where: str = ""
    table_type: str = ""
    ontology_class: str = ""
    ontology_iri: str = ""
    ontology_version: str = ""
    authority: "SilverModelAuthoritySpec | None" = None


class SchemaKind(str, Enum):
    """Logical schema-document kind, independent of output encoding."""

    SILVER = "silver"
    GOLD = "gold"


@dataclass(frozen=True, slots=True)
class SchemaDocumentSpec:
    """An ordered logical YAML document; it contains no rendered YAML."""

    artifact_path: str
    kind: SchemaKind
    models: tuple[SchemaModelSpec, ...]


@dataclass(frozen=True, slots=True)
class SourceTableSpec:
    """A table declaration in a logical dbt source catalog."""

    name: str
    label: str


@dataclass(frozen=True, slots=True)
class SourceCatalogSpec:
    """A logical dbt source catalog."""

    artifact_path: str
    source_name: str
    system_label: str
    database: str
    schema: str
    tables: tuple[SourceTableSpec, ...]
    logical_sources_only: bool


@dataclass(frozen=True, slots=True)
class SilverRegistry:
    """Immutable, deterministically ordered Silver model registry."""

    names: tuple[tuple[str, str], ...]
    columns: tuple[tuple[str, frozenset[str]], ...]
    versions: tuple[tuple[str, str], ...] = ()
    ambiguous_parents: tuple[tuple[str, tuple[str, ...]], ...] = ()
    authorities: tuple[tuple[str, "SilverModelAuthoritySpec"], ...] = ()


@dataclass(frozen=True, slots=True)
class SourceCoverageSpec:
    """Coverage of one mapped physical source table."""

    name: str
    available_columns: int
    consumed_columns: int
    unused_columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EntityCoverageSpec:
    """Logical coverage facts for one projected entity."""

    model_name: str
    ontology_properties_total: int
    ontology_properties_required: int
    ontology_properties_optional: int
    ontology_properties_derived: int
    populated_from_source: int
    always_null: int
    null_columns: tuple[str, ...]
    missing_required_mappings: tuple[str, ...]
    source_coverage: tuple[SourceCoverageSpec, ...]


@dataclass(frozen=True, slots=True)
class CoverageSpec:
    """Coverage facts for one ontology domain."""

    domain_name: str
    entities: tuple[EntityCoverageSpec, ...]


@dataclass(frozen=True, slots=True)
class BoundCoverage:
    """Graph-derived coverage facts emitted by bind."""

    domain_name: str
    entities: tuple[EntityCoverageSpec, ...]


@dataclass(frozen=True, slots=True)
class NormalizedCoverage:
    """Coverage facts forwarded through normalized policy."""

    domain_name: str
    entities: tuple[EntityCoverageSpec, ...]


@dataclass(frozen=True, slots=True)
class MacroSetSpec:
    """Names of packaged macros that render copies into the dbt project."""

    names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ModelPhysicalPlan:
    """Adapter-specific physical choices for one SQL model."""

    model_name: str
    artifact_path: str
    template_name: str
    materialization: str
    unique_key: tuple[str, ...] = ()
    incremental_column: str = ""
    dependencies: tuple[str, ...] = ()
    runtime: "RuntimePhysicalPlan | None" = None


@dataclass(frozen=True, slots=True)
class SilverPhysicalColumnPlan:
    """Adapter-mapped physical form of one authoritative Silver column."""

    ordinal: int
    name: str
    canonical_type: "CanonicalTypeSpec"
    physical_type: str
    nullable: bool
    default_expression: str
    role: str
    comment: str
    provenance: tuple[str, ...] = ()
    runtime_generated: bool = False


@dataclass(frozen=True, slots=True)
class SilverConstraintPhysicalPlan:
    """Constraint metadata; enforcement is always stated explicitly."""

    name: str
    kind: str
    columns: tuple[str, ...]
    referenced_schema: str = ""
    referenced_model: str = ""
    referenced_columns: tuple[str, ...] = ()
    enforced: bool = False
    capability_disposition: str = ""
    deviation_ref: str = ""
    temporal_mode: str = ""
    as_of_column: str = ""
    property_uri: str = ""
    predicate: str = ""
    provenance: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SilverIndexPhysicalPlan:
    """Deployment-owned index recommendation, never an ontology enforcement claim."""

    name: str
    columns: tuple[str, ...]
    purpose: str
    applied: bool = False
    provenance: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SilverRelationLinkPlan:
    """An explicit DQ, quarantine, or temporal-result relation link."""

    relation_kind: str
    relation_name: str
    artifact_path: str
    rule_ids: tuple[str, ...] = ()
    property_uris: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SilverModelPhysicalPlan:
    """Complete adapter-specific physical plan for one Silver model."""

    model_name: str
    schema_name: str
    kind: SilverModelKind
    materialization: str
    sql_artifact_path: str
    columns: tuple[SilverPhysicalColumnPlan, ...]
    constraints: tuple[SilverConstraintPhysicalPlan, ...]
    indexes: tuple[SilverIndexPhysicalPlan, ...]
    relation_links: tuple[SilverRelationLinkPlan, ...]
    comment: str = ""
    provenance: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SilverPhysicalPlan:
    """One adapter-selected Silver DDL/metadata/ERD/parity bundle."""

    domain_name: str
    adapter: str
    adapter_version: str
    ddl_artifact_path: str
    constraint_artifact_path: str
    erd_artifact_path: str
    parity_artifact_path: str
    models: tuple[SilverModelPhysicalPlan, ...]
    capability_results: tuple["CapabilityResultSpec", ...] = ()


@dataclass(frozen=True, slots=True)
class DqRulePhysicalPlan:
    """One executable, adapter-selected DQ result and dbt-test plan."""

    rule: "DataQualityRuleSpec"
    target_model_name: str
    evaluated_model_name: str
    result_model_name: str
    result_artifact_path: str
    test_artifact_path: str
    row_level: bool


@dataclass(frozen=True, slots=True)
class DqModelPhysicalPlan:
    """Quality routing for one Silver model, including explicit quarantine outputs."""

    model_name: str
    original_artifact_path: str
    evaluated_model_name: str
    evaluated_artifact_path: str
    quarantine_model_name: str
    quarantine_artifact_path: str
    rules: tuple[DqRulePhysicalPlan, ...]

    @property
    def quarantines_rows(self) -> bool:
        return bool(self.quarantine_artifact_path)


@dataclass(frozen=True, slots=True)
class TemporalLookupPhysicalPlan:
    """Adapter-selected execution behavior for one FK lookup."""

    property_uri: str
    strategy: str
    cardinality_check: str
    missing_action: str
    ambiguous_action: str
    late_parent_action: str
    quarantine_artifact_path: str = ""


@dataclass(frozen=True, slots=True)
class RuntimePhysicalPlan:
    """Adapter-capability-aware physical plan for one DD-109 model."""

    adapter: str
    strategy: str
    merge_strategy: str
    delete_strategy: str
    hash_strategy: str
    replay_strategy: str
    backfill_strategy: str
    lookback_strategy: str
    schema_change_strategy: str
    temporal_lookups: tuple[TemporalLookupPhysicalPlan, ...] = ()
    blocking_reasons: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class DocumentPhysicalPlan:
    """Adapter-specific renderer choice for one logical schema document."""

    artifact_path: str
    template_name: str


@dataclass(frozen=True, slots=True)
class AdapterPlan:
    """The selected adapter and template bundle."""

    platform: str
    version: str
    template_root: str
    capability_results: tuple["CapabilityResultSpec", ...] = ()


@dataclass(frozen=True, slots=True)
class ProjectConfigPlan:
    """Logical inputs for project-level dbt configuration artifacts."""

    project_name: str
    domains: tuple[str, ...]
    gold_domains: tuple[str, ...]
    emit: bool


@dataclass(frozen=True, slots=True)
class ReleasePlan:
    """Release-gate and external-model facts."""

    known_models: tuple[str, ...]
    policy_version: str = ""
    ontology_name: str = ""
    ontology_version: str = ""
    toolkit_version: str = ""
    closure_version: str = ""
    capability_results: tuple["CapabilityResultSpec", ...] = ()
    blocking_reasons: tuple[str, ...] = ()
    blocking_rules: tuple[tuple[str, str], ...] = ()
    projection_blocking_rules: tuple[tuple[str, str], ...] = ()
    mapping_contract: "MappingContractSpec | None" = None
    mapping_capability_results: tuple["MappingCapabilityResult", ...] = ()
    silver_authorities: tuple["SilverModelAuthoritySpec", ...] = ()
    active_sources: tuple[tuple[str, str, tuple[str, ...]], ...] = ()
