# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Pure physical planning for logical dbt specifications (DD-110)."""

from __future__ import annotations

import hashlib
import re

from .context import (
    MaterializationPlan,
    ProjectionContract,
    ShapedProject,
)
from .specs import (
    AdapterPlan,
    DocumentPhysicalPlan,
    DqModelPhysicalPlan,
    DqRulePhysicalPlan,
    ModelPhysicalPlan,
    PrepModelPhysicalPlan,
    PrepSchemaPhysicalPlan,
    ProjectConfigPlan,
    ReleasePlan,
    RuntimePhysicalPlan,
    TemporalLookupPhysicalPlan,
    SilverModelKind,
    SilverConstraintPhysicalPlan,
    SilverIndexPhysicalPlan,
    SilverModelPhysicalPlan,
    SilverPhysicalColumnPlan,
    SilverPhysicalPlan,
    SilverRelationLinkPlan,
)
from .policy_specs import (
    AdapterCapability,
    CapabilityDisposition,
    CapabilityResultSpec,
    CanonicalTypeKind,
    CanonicalTypeSpec,
    ChangeDetectionStrategy,
    DqAction,
    DqCheckKind,
    ParentAction,
    SilverColumnRole,
    TechnicalDedupeMode,
)
from .diagnostics import (
    Diagnostic,
    ExecutionMode,
    diagnostic_from_exception,
    order_diagnostics,
)


_REF_NAME = re.compile(r"""ref\(\s*['"]([^'"]+)['"]\s*\)""")
_ROW_LEVEL_DQ_CHECKS = frozenset(
    {
        DqCheckKind.CONTRACT_SHAPE,
        DqCheckKind.RANGE,
        DqCheckKind.DISTRIBUTION,
        DqCheckKind.REFERENTIAL_COVERAGE,
        DqCheckKind.CROSS_FIELD,
    }
)


class QualityMaterializationBlocked(ValueError):
    """A DQ rule cannot be rendered without violating its authored semantics."""

    def __init__(self, blocking_rules: tuple[tuple[str, str], ...]) -> None:
        self.blocking_rules = blocking_rules
        detail = "; ".join(
            f"{rule_id}: {message}" for rule_id, message in blocking_rules
        )
        super().__init__(f"Data-quality materialization blocked: {detail}")


class SilverMaterializationBlocked(ValueError):
    """The shared Silver authority cannot be mapped to an exact physical plan."""

    def __init__(self, blocking_rules: tuple[tuple[str, str], ...]) -> None:
        self.blocking_rules = blocking_rules
        detail = "; ".join(
            f"{rule_id}: {message}" for rule_id, message in blocking_rules
        )
        super().__init__(f"Silver physical materialization blocked: {detail}")


class MaterializationCollectionError(ValueError):
    """Independent physical-planning blockers collected without rendering."""

    def __init__(self, diagnostics: tuple[Diagnostic, ...], first_error: Exception) -> None:
        self.diagnostics = order_diagnostics(diagnostics)
        super().__init__(str(first_error))


def _dependency_name(value: str) -> str:
    match = _REF_NAME.search(value)
    return match.group(1) if match else value


def _dependencies(model) -> tuple[str, ...]:
    values = {
        source.model_name for source in model.sources if source.model_name
    }
    values.update(source.ref_model for source in model.sources if source.ref_model)
    values.update(
        _dependency_name(join.referenced_model)
        for join in model.joins
        if join.referenced_model
    )
    values.update(getattr(model, "source_models", ()))
    return tuple(sorted(values))


def _quality_physical_plans(
    shaped: ShapedProject,
) -> tuple[DqModelPhysicalPlan, ...]:
    known_models = frozenset(item.identity.model_name for item in shaped.silver_models)
    plans: list[DqModelPhysicalPlan] = []
    blockers: list[tuple[str, str]] = []
    for model in shaped.silver_models:
        authority = model.authority
        if (
            model.kind not in {SilverModelKind.ENTITY, SilverModelKind.UNION}
            or authority is None
            or not authority.quality_rules
            or model.identity.artifact_path is None
        ):
            continue
        column_names = frozenset(column.name for column in model.columns)
        if model.kind is SilverModelKind.UNION:
            column_names = column_names | {
                "_source_identity_ref",
                "_source_record_key",
                "_source_system",
            }
        rules: list[DqRulePhysicalPlan] = []
        quarantine = any(
            rule.action.value is DqAction.QUARANTINE
            for rule in authority.quality_rules
        )
        evaluated_model_name = (
            f"{model.identity.model_name}__dq_input"
            if quarantine
            else model.identity.model_name
        )
        original_path = model.identity.artifact_path
        directory, filename = original_path.rsplit("/", 1)
        evaluated_path = (
            f"{directory}/{filename.removesuffix('.sql')}__dq_input.sql"
            if quarantine
            else original_path
        )
        for rule in authority.quality_rules:
            kind = rule.check.check_kind.value
            parameters = {
                item.name: item.values for item in rule.check.parameters
            }
            referenced_columns = {
                value
                for key in {
                    "column",
                    "columns",
                    "compare_column",
                    "left",
                    "parent_column",
                    "required",
                    "right",
                }
                for value in parameters.get(key, ())
                if key not in {"compare_column", "parent_column"}
            }
            missing_columns = sorted(referenced_columns - column_names)
            if missing_columns:
                blockers.append(
                    (
                        rule.rule_id.value,
                        (
                            f"DQ rule {rule.rule_id.value!r} references columns absent "
                            f"from {model.identity.model_name!r}: {missing_columns!r}"
                        ),
                    )
                )
            for key in ("compare_model", "parent_model"):
                target = parameters.get(key, ())
                if target and target[0] not in known_models:
                    blockers.append(
                        (
                            rule.rule_id.value,
                            (
                                f"DQ rule {rule.rule_id.value!r} references unknown "
                                f"model {target[0]!r}"
                            ),
                        )
                    )
            row_level = kind in _ROW_LEVEL_DQ_CHECKS
            if rule.action.value is DqAction.QUARANTINE:
                if not row_level:
                    blockers.append(
                        (
                            rule.rule_id.value,
                            (
                                f"{kind.value!r} has no deterministic row-level "
                                "quarantine semantics in policy v1"
                            ),
                        )
                    )
                lineage_columns = {
                    "_source_identity_ref",
                    "_source_record_key",
                    "_source_system",
                }
                missing_lineage = sorted(lineage_columns - column_names)
                if missing_lineage:
                    blockers.append(
                        (
                            rule.rule_id.value,
                            (
                                "row quarantine requires immutable source lineage "
                                f"columns: {missing_lineage!r}"
                            ),
                        )
                    )
            slug = re.sub(
                r"[^a-z0-9_]+",
                "_",
                f"{rule.rule_id.value}_{rule.version.value}".lower(),
            ).strip("_")
            slug = f"{slug}_{rule.rule_hash[:12]}"
            result_name = f"{model.identity.model_name}__dq__{slug}"
            rules.append(
                DqRulePhysicalPlan(
                    rule=rule,
                    target_model_name=model.identity.model_name,
                    evaluated_model_name=evaluated_model_name,
                    result_model_name=result_name,
                    result_artifact_path=(
                        f"models/quality/{model.identity.domain_name}/"
                        f"{result_name}.sql"
                    ),
                    test_artifact_path=(
                        f"tests/quality/{model.identity.domain_name}/"
                        f"test_{result_name}.sql"
                    ),
                    row_level=row_level,
                )
            )
        plans.append(
            DqModelPhysicalPlan(
                model_name=model.identity.model_name,
                original_artifact_path=original_path,
                evaluated_model_name=evaluated_model_name,
                evaluated_artifact_path=evaluated_path,
                quarantine_model_name=(
                    f"{model.identity.model_name}__dq_quarantine"
                    if quarantine
                    else ""
                ),
                quarantine_artifact_path=(
                    f"{directory}/{model.identity.model_name}__dq_quarantine.sql"
                    if quarantine
                    else ""
                ),
                rules=tuple(
                    sorted(rules, key=lambda item: item.rule.rule_id.value)
                ),
            )
        )
    if blockers:
        raise QualityMaterializationBlocked(tuple(sorted(set(blockers))))
    return tuple(sorted(plans, key=lambda item: item.model_name))


def _feature_capability(feature: str) -> AdapterCapability:
    if feature.startswith("array:"):
        return AdapterCapability.JSON_ARRAY_CHILD
    if feature.startswith("json-scalar:"):
        return AdapterCapability.JSON_SCALAR
    return AdapterCapability.CANONICAL_TYPES


def _prep_feature_requirements(shaped: ShapedProject) -> tuple[tuple[str, str, str], ...]:
    result: set[tuple[str, str, str]] = set()
    for model in shaped.prep_models:
        result.add(
            (
                f"schema-evolution:{model.schema_evolution.value}",
                "DD-106-schema-evolution",
                model.model_name,
            )
        )
        for column in model.columns:
            for cleanup in column.cleanup_rules:
                result.add(
                    (
                        f"cleanup:{cleanup.operation.value.value}",
                        "DD-106-prep-cleanup",
                        model.model_name,
                    )
                )
            if column.conversion is not None:
                result.add(
                    (
                        f"cast:{column.conversion.error_action.value.value}",
                        "DD-106-prep-cast",
                        model.model_name,
                    )
                )
                result.add(
                    (
                        (
                            f"parse:{column.conversion.parse_policy.value}:"
                            f"{column.conversion.target_type.value.kind.value}"
                        ),
                        "DD-106-prep-cast",
                        model.model_name,
                    )
                )
        for scalar in model.scalar_columns:
            result.add(
                (
                    f"json-scalar:{scalar.error_action.value}",
                    "DD-106-json-scalar",
                    model.model_name,
                )
            )
            result.add(
                (
                    "raw-payload-retention"
                    if scalar.retention.value == "retain-payload"
                    else "replayable-reference-retention",
                    "DD-106-json-replay",
                    model.model_name,
                )
            )
        if model.technical_dedupe.mode.value is TechnicalDedupeMode.COMPLETE_TOTAL_ORDER:
            result.add(
                ("technical-dedupe", "DD-106-technical-dedupe", model.model_name)
            )
    for child in shaped.prep_children:
        result.add(
            (
                "array:scalar-object-elements",
                "DD-106-json-array",
                child.model_name,
            )
        )
        result.add(
            (
                f"array:{child.null_action.value}",
                "DD-106-json-array",
                child.model_name,
            )
        )
        result.add(
            (
                f"array:{child.empty_action.value}",
                "DD-106-json-array",
                child.model_name,
            )
        )
        result.add(
            (
                "array:element-index"
                if child.element_index_column
                else "array:element-key",
                "DD-106-json-array",
                child.model_name,
            )
        )
        result.add(
            (
                "raw-payload-retention"
                if child.retention.value == "retain-payload"
                else "replayable-reference-retention",
                "DD-106-json-replay",
                child.model_name,
            )
        )
    return tuple(sorted(result))


def _prep_physical_plans(
    shaped: ShapedProject,
    adapter_name,
) -> tuple[
    tuple[PrepModelPhysicalPlan, ...],
    tuple[PrepSchemaPhysicalPlan, ...],
    tuple[CapabilityResultSpec, ...],
]:
    from .capabilities import (
        physical_canonical_type,
        physical_source_type,
        supports_preparation_feature,
    )

    unsupported: dict[str, list[tuple[str, str]]] = {}
    capability_results: list[CapabilityResultSpec] = []
    for feature, rule_id, model_name in _prep_feature_requirements(shaped):
        if supports_preparation_feature(adapter_name, feature):
            continue
        message = (
            f"Adapter {adapter_name.value!r} does not support required preparation "
            f"feature {feature!r} for {model_name!r}."
        )
        unsupported.setdefault(model_name, []).append((rule_id, message))
        capability_results.append(
            CapabilityResultSpec(
                adapter=adapter_name,
                capability=_feature_capability(feature),
                disposition=CapabilityDisposition.BLOCKING,
                rule_id=rule_id,
                scope="prep",
                evidence=("adapter-capability-registry-v1: feature absent",),
                message=message,
            )
        )

    boolean_type = physical_canonical_type(
        adapter_name, CanonicalTypeSpec(CanonicalTypeKind.BOOLEAN)
    )
    string_type = physical_canonical_type(
        adapter_name, CanonicalTypeSpec(CanonicalTypeKind.STRING)
    )
    int64_type = physical_canonical_type(
        adapter_name, CanonicalTypeSpec(CanonicalTypeKind.INT64)
    )
    plans: list[PrepModelPhysicalPlan] = []
    parent_types: dict[str, dict[str, str]] = {}
    source_by_model: dict[str, str] = {}

    def canonical_type(
        model_name: str,
        column_name: str,
        value: CanonicalTypeSpec,
    ) -> str:
        try:
            return physical_canonical_type(adapter_name, value)
        except ValueError as exc:
            message = f"{model_name}.{column_name}: {exc}"
            unsupported.setdefault(model_name, []).append(
                ("DD-111-types", message)
            )
            return string_type

    for model in shaped.prep_models:
        types: list[tuple[str, str]] = []
        for column in model.columns:
            try:
                raw_type = physical_source_type(
                    adapter_name, column.source_data_type
                )
            except ValueError as exc:
                message = f"{model.model_name}: {exc}"
                unsupported.setdefault(model.model_name, []).append(
                    ("DD-111-types", message)
                )
                raw_type = string_type
            output_type = (
                canonical_type(
                    model.model_name,
                    column.output_name,
                    column.conversion.target_type.value,
                )
                if column.conversion is not None
                else raw_type
            )
            types.append((column.output_name, output_type))
            if column.raw_output_name:
                types.append((column.raw_output_name, raw_type))
            if column.error_flag_name:
                types.append((column.error_flag_name, boolean_type))
        for cdc in model.cdc_columns:
            types.append(
                (
                    cdc.output_name,
                    canonical_type(
                        model.model_name,
                        cdc.output_name,
                        cdc.data_type,
                    ),
                )
            )
        for scalar in model.scalar_columns:
            types.append(
                (
                    scalar.output_name,
                    canonical_type(
                        model.model_name,
                        scalar.output_name,
                        scalar.data_type,
                    ),
                )
            )
            if scalar.error_flag_name:
                types.append((scalar.error_flag_name, boolean_type))
        types.append(
            (
                model.source_record_key.output_name,
                canonical_type(
                    model.model_name,
                    model.source_record_key.output_name,
                    model.source_record_key.data_type,
                ),
            )
        )
        names = [name for name, _ in types]
        if len(names) != len(set(names)):
            duplicates = sorted(
                {name for name in names if names.count(name) > 1}
            )
            unsupported.setdefault(model.model_name, []).append(
                (
                    "DD-106-prep-columns",
                    (
                        f"Preparation model {model.model_name!r} has duplicate "
                        f"output columns: {', '.join(duplicates)}"
                    ),
                )
            )
        parent_types[model.model_name] = dict(types)
        source_by_model[model.model_name] = model.source_name
        plans.append(
            PrepModelPhysicalPlan(
                model_name=model.model_name,
                artifact_path=model.artifact_path,
                kind="parent",
                column_types=tuple(types),
                blocking_reasons=tuple(
                    sorted(unsupported.get(model.model_name, ()))
                ),
            )
        )

    for child in shaped.prep_children:
        parent = parent_types[child.parent_model_name]
        types = [
            ("_source_record_key", parent["_source_record_key"]),
            *(
                (name, parent[name])
                for name in child.parent_key_columns
                if name != "_source_record_key"
            ),
            (
                child.element_index_column or "_element_key",
                int64_type if child.element_index_column else string_type,
            ),
            *(
                (
                    column.name,
                    canonical_type(
                        child.model_name,
                        column.name,
                        column.data_type,
                    ),
                )
                for column in child.columns
            ),
        ]
        if child.retention.value == "retain-payload":
            types.append(("_raw_payload", string_type))
        source_by_model[child.model_name] = child.source_name
        plans.append(
            PrepModelPhysicalPlan(
                model_name=child.model_name,
                artifact_path=child.artifact_path,
                kind="array-child",
                column_types=tuple(types),
                dependencies=(child.parent_model_name,),
                blocking_reasons=tuple(
                    sorted(unsupported.get(child.model_name, ()))
                ),
            )
        )

    grouped: dict[str, list[str]] = {}
    for plan in plans:
        grouped.setdefault(source_by_model[plan.model_name], []).append(
            plan.model_name
        )
    documents = tuple(
        PrepSchemaPhysicalPlan(
            artifact_path=f"models/staging/{source}/_{source}__staging.yml",
            source_name=source,
            model_names=tuple(sorted(names)),
        )
        for source, names in sorted(grouped.items())
    )
    return tuple(plans), documents, tuple(capability_results)


def _runtime_physical_plan(
    model,
    adapter_name,
    capability_results: tuple[CapabilityResultSpec, ...],
) -> RuntimePhysicalPlan | None:
    runtime = model.runtime
    authority = model.authority
    relationships = {
        item.property_uri: item
        for item in authority.foreign_keys
    } if authority is not None else {}
    temporal_lookups: list[TemporalLookupPhysicalPlan] = []
    for join in model.joins:
        relationship = relationships.get(join.relationship_uri)
        if relationship is None:
            continue
        needs_quarantine = any(
            action.value in {ParentAction.QUARANTINE, ParentAction.RETRY}
            for action in (
                relationship.missing_action,
                relationship.ambiguous_action,
                relationship.late_parent_action,
            )
        )
        temporal_lookups.append(
            TemporalLookupPhysicalPlan(
                property_uri=relationship.property_uri,
                strategy=relationship.mode.value.value,
                cardinality_check=relationship.cardinality.value.value,
                missing_action=relationship.missing_action.value.value,
                ambiguous_action=relationship.ambiguous_action.value.value,
                late_parent_action=relationship.late_parent_action.value.value,
                quarantine_artifact_path=(
                    "models/silver/"
                    f"{model.identity.domain_name}/"
                    f"{model.identity.model_name}__fk_quarantine.sql"
                    if needs_quarantine
                    else ""
                ),
            )
        )
    joined_relationships = {
        join.relationship_uri for join in model.joins if join.relationship_uri
    }
    for relationship in relationships.values():
        if relationship.property_uri in joined_relationships:
            continue
        needs_quarantine = any(
            action.value in {ParentAction.QUARANTINE, ParentAction.RETRY}
            for action in (
                relationship.missing_action,
                relationship.ambiguous_action,
                relationship.late_parent_action,
            )
        )
        temporal_lookups.append(
            TemporalLookupPhysicalPlan(
                property_uri=relationship.property_uri,
                strategy=relationship.mode.value.value,
                cardinality_check=relationship.cardinality.value.value,
                missing_action=relationship.missing_action.value.value,
                ambiguous_action=relationship.ambiguous_action.value.value,
                late_parent_action=relationship.late_parent_action.value.value,
                quarantine_artifact_path=(
                    "models/silver/"
                    f"{model.identity.domain_name}/"
                    f"{model.identity.model_name}__fk_quarantine.sql"
                    if needs_quarantine
                    else ""
                ),
            )
        )
    if runtime is None and not temporal_lookups:
        return None

    blockers = tuple(
        sorted(
            {
                (result.rule_id, result.message)
                for result in capability_results
                if result.disposition is CapabilityDisposition.BLOCKING
                and result.capability
                in {
                    AdapterCapability.CANONICAL_SHA256_HASH,
                    AdapterCapability.MERGE_UPSERT,
                    AdapterCapability.DELETE_SEMANTICS,
                    AdapterCapability.WINDOW_FUNCTIONS,
                    AdapterCapability.TEMPORAL_LOOKUP,
                    AdapterCapability.QUARANTINE,
                }
            }
        )
    )
    if runtime is None:
        return RuntimePhysicalPlan(
            adapter=adapter_name.value,
            strategy="temporal-view",
            merge_strategy="none",
            delete_strategy="none",
            hash_strategy="none",
            replay_strategy="none",
            backfill_strategy="none",
            lookback_strategy="none",
            schema_change_strategy="none",
            temporal_lookups=tuple(temporal_lookups),
            blocking_reasons=blockers,
        )

    incremental = runtime.authority.incremental
    lookback = incremental.lookback.value
    runtime_blockers = set(blockers)
    unsupported_hash_types = sorted(
        {
            item.data_type.kind.value
            for item in runtime.canonical_hash_columns
            if item.data_type.kind
            in {CanonicalTypeKind.FLOAT64, CanonicalTypeKind.JSON}
        }
    )
    if unsupported_hash_types:
        runtime_blockers.add(
            (
                "DD-109-hash",
                "canonical hash v1 cannot guarantee Fabric/Databricks SQL parity for "
                f"types: {', '.join(unsupported_hash_types)}",
            )
        )
    schema_change = incremental.schema_evolution.action.value.value
    if schema_change == "quarantine":
        runtime_blockers.add(
            (
                "DD-109-schema-change",
                "dbt cannot quarantine an unparseable runtime schema change; "
                "use fail or an approved contract update",
            )
        )
    return RuntimePhysicalPlan(
        adapter=adapter_name.value,
        strategy=f"scd{runtime.authority.history.scd_type.value.value}",
        merge_strategy=(
            "fabric-merge"
            if adapter_name.value == "fabric"
            else "databricks-delta-merge"
        ),
        delete_strategy=(
            f"hard:{incremental.hard_delete.value.value};"
            f"soft:{incremental.soft_delete.value.value}"
        ),
        hash_strategy=(
            "canonical-sha256-v1"
            if runtime.authority.change_detection.value
            is ChangeDetectionStrategy.CANONICAL_HASH
            else "typed-null-safe-column-compare"
        ),
        replay_strategy=incremental.replay.value.value,
        backfill_strategy=incremental.backfill.value.value,
        lookback_strategy=f"bounded-{lookback.amount}-{lookback.unit.value}",
        schema_change_strategy=(
            "sync_all_columns"
            if schema_change == "approved-contract-update"
            else "fail"
        ),
        temporal_lookups=tuple(temporal_lookups),
        blocking_reasons=tuple(sorted(runtime_blockers)),
    )


def _bounded_identifier(
    adapter: str,
    kind: str,
    schema: str,
    model: str,
    columns: tuple[str, ...],
    referenced_model: str = "",
) -> str:
    """Return a collision-safe deterministic adapter-bounded identifier."""
    maximum = 128 if adapter == "fabric" else 255
    identity = "|".join((adapter, kind, schema, model, *columns, referenced_model))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    base = re.sub(
        r"[^a-z0-9_]+",
        "_",
        "_".join((kind, model, *columns, referenced_model)).lower(),
    ).strip("_")
    suffix = f"_{digest}"
    return f"{base[: maximum - len(suffix)].rstrip('_')}{suffix}"


def _silver_physical_plan(
    shaped: ShapedProject,
    model_plans: tuple[ModelPhysicalPlan, ...],
    quality_plans: tuple[DqModelPhysicalPlan, ...],
    *,
    adapter_name,
    adapter_version: str,
    capability_results: tuple[CapabilityResultSpec, ...],
) -> SilverPhysicalPlan:
    """Map the sole logical Silver authority to one exact adapter plan."""
    from .capabilities import physical_canonical_type

    plan_by_model = {item.model_name: item for item in model_plans}
    quality_by_model = {item.model_name: item for item in quality_plans}
    constraint_capability = next(
        (
            item
            for item in capability_results
            if item.capability is AdapterCapability.CONSTRAINTS
        ),
        None,
    )
    constraint_disposition = (
        constraint_capability.disposition.value
        if constraint_capability is not None
        else "not-negotiated"
    )
    constraint_deviation = (
        constraint_capability.deviation_ref or ""
        if constraint_capability is not None
        else ""
    )
    blockers: list[tuple[str, str]] = []
    physical_models: list[SilverModelPhysicalPlan] = []
    model_specs = {
        item.identity.model_name: item for item in shaped.silver_models
    }
    for model in shaped.silver_models:
        if model.identity.artifact_path is None:
            continue
        dbt_plan = plan_by_model[model.identity.model_name]
        columns: list[SilverPhysicalColumnPlan] = []
        for ordinal, column in enumerate(model.columns, start=1):
            if column.canonical_type is None:
                blockers.append(
                    (
                        "DD-110-column-type",
                        (
                            f"{model.identity.model_name}.{column.name} has no "
                            "normalized canonical type"
                        ),
                    )
                )
                continue
            if column.nullable is None:
                blockers.append(
                    (
                        "DD-110-column-nullability",
                        (
                            f"{model.identity.model_name}.{column.name} has no "
                            "normalized nullability"
                        ),
                    )
                )
                continue
            try:
                physical_type = physical_canonical_type(
                    adapter_name,
                    column.canonical_type,
                )
            except ValueError as exc:
                blockers.append(
                    (
                        "DD-111-types",
                        f"{model.identity.model_name}.{column.name}: {exc}",
                    )
                )
                continue
            columns.append(
                SilverPhysicalColumnPlan(
                    ordinal=ordinal,
                    name=column.name,
                    canonical_type=column.canonical_type,
                    physical_type=physical_type,
                    nullable=column.nullable,
                    default_expression=column.default_expression,
                    role=column.role or SilverColumnRole.BUSINESS.value,
                    comment=column.description,
                    provenance=column.provenance,
                    runtime_generated=column.runtime_generated,
                )
            )

        constraints: list[SilverConstraintPhysicalPlan] = []
        if model.primary_key is not None:
            constraints.append(
                SilverConstraintPhysicalPlan(
                    name=_bounded_identifier(
                        adapter_name.value,
                        "pk",
                        model.identity.schema_name,
                        model.identity.model_name,
                        model.primary_key.columns,
                    ),
                    kind="primary-key",
                    columns=model.primary_key.columns,
                    enforced=False,
                    capability_disposition=constraint_disposition,
                    deviation_ref=constraint_deviation,
                    predicate=model.primary_key.predicate,
                    provenance=model.primary_key.provenance,
                )
            )
        for key in model.unique_keys:
            constraints.append(
                SilverConstraintPhysicalPlan(
                    name=_bounded_identifier(
                        adapter_name.value,
                        "uq",
                        model.identity.schema_name,
                        model.identity.model_name,
                        key.columns,
                    ),
                    kind="unique",
                    columns=key.columns,
                    enforced=False,
                    capability_disposition=constraint_disposition,
                    deviation_ref=constraint_deviation,
                    predicate=key.predicate,
                    provenance=key.provenance,
                )
            )
        for foreign_key in model.foreign_keys:
            target = model_specs.get(foreign_key.referenced_model)
            constraints.append(
                SilverConstraintPhysicalPlan(
                    name=_bounded_identifier(
                        adapter_name.value,
                        "fk",
                        model.identity.schema_name,
                        model.identity.model_name,
                        foreign_key.columns,
                        foreign_key.referenced_model,
                    ),
                    kind="foreign-key",
                    columns=foreign_key.columns,
                    referenced_schema=(
                        target.identity.schema_name if target is not None else ""
                    ),
                    referenced_model=foreign_key.referenced_model,
                    referenced_columns=foreign_key.referenced_columns,
                    enforced=False,
                    capability_disposition=constraint_disposition,
                    deviation_ref=constraint_deviation,
                    temporal_mode=foreign_key.temporal_mode,
                    as_of_column=foreign_key.as_of_column,
                    property_uri=foreign_key.property_uri,
                    provenance=foreign_key.provenance,
                )
            )
        indexes = tuple(
            SilverIndexPhysicalPlan(
                name=_bounded_identifier(
                    adapter_name.value,
                    "ix",
                    model.identity.schema_name,
                    model.identity.model_name,
                    constraint.columns,
                    constraint.referenced_model,
                ),
                columns=constraint.columns,
                purpose=constraint.kind,
                applied=False,
                provenance=(
                    "rule:DD-111-layout",
                    "deployment-profile-required",
                ),
            )
            for constraint in constraints
        )

        links: list[SilverRelationLinkPlan] = []
        quality = quality_by_model.get(model.identity.model_name)
        if quality is not None:
            if quality.quarantine_artifact_path:
                links.append(
                    SilverRelationLinkPlan(
                        relation_kind="dq-quarantine",
                        relation_name=quality.quarantine_model_name,
                        artifact_path=quality.quarantine_artifact_path,
                        rule_ids=tuple(
                            item.rule.rule_id.value for item in quality.rules
                        ),
                    )
                )
            links.extend(
                SilverRelationLinkPlan(
                    relation_kind="dq-result",
                    relation_name=rule.result_model_name,
                    artifact_path=rule.result_artifact_path,
                    rule_ids=(rule.rule.rule_id.value,),
                )
                for rule in quality.rules
            )
        if dbt_plan.runtime is not None:
            temporal_paths: dict[str, set[str]] = {}
            for lookup in dbt_plan.runtime.temporal_lookups:
                if lookup.quarantine_artifact_path:
                    temporal_paths.setdefault(
                        lookup.quarantine_artifact_path,
                        set(),
                    ).add(lookup.property_uri)
            links.extend(
                SilverRelationLinkPlan(
                    relation_kind="temporal-fk-quarantine",
                    relation_name=path.rsplit("/", 1)[-1].removesuffix(".sql"),
                    artifact_path=path,
                    property_uris=tuple(sorted(properties)),
                )
                for path, properties in sorted(temporal_paths.items())
            )
        physical_models.append(
            SilverModelPhysicalPlan(
                model_name=model.identity.model_name,
                schema_name=model.identity.schema_name,
                kind=model.kind,
                materialization=dbt_plan.materialization,
                sql_artifact_path=model.identity.artifact_path,
                columns=tuple(columns),
                constraints=tuple(constraints),
                indexes=indexes,
                relation_links=tuple(links),
                comment=model.comment,
                provenance=model.provenance,
            )
        )
    if blockers:
        raise SilverMaterializationBlocked(tuple(sorted(set(blockers))))
    domain = shaped.silver_models[0].identity.domain_name if shaped.silver_models else "domain"
    return SilverPhysicalPlan(
        domain_name=domain,
        adapter=adapter_name.value,
        adapter_version=adapter_version,
        ddl_artifact_path=f"analyses/{domain}/{domain}-ddl.sql",
        constraint_artifact_path=f"metadata/{domain}-silver-constraints.json",
        erd_artifact_path=f"docs/diagrams/{domain}/{domain}-erd.mmd",
        parity_artifact_path=f"metadata/{domain}-silver-parity.json",
        models=tuple(physical_models),
        capability_results=capability_results,
    )


def _plan_materialization(
    contract: ProjectionContract,
    shaped: ShapedProject,
    mode: ExecutionMode = ExecutionMode.FAIL_FAST,
) -> MaterializationPlan:
    """Select adapter, materialization, dependencies, and release facts."""
    from .capabilities import adapter_spec, negotiate_capabilities
    from .gold_materialize import materialize_gold_product

    project = contract.project
    adapter_name = contract.policy.target_adapter.value
    capability_results = negotiate_capabilities(
        adapter_name,
        contract.policy.capability_requirements,
        contract.policy.deviations,
    )
    prep_plans, prep_documents, prep_capability_results = _prep_physical_plans(
        shaped,
        adapter_name,
    )
    mapping_capability_results = tuple(
        item
        for item in contract.mapping_contract.capability_results
        if item.adapter == adapter_name.value
    )
    mapping_blockers = {
        (
            item.rule_id,
            (
                item.reason
                or (
                    f"Mapping {item.mapping_resource_uri!r} requires unsupported "
                    f"{item.capability.value!r} on {item.adapter!r}."
                )
            ),
        )
        for item in mapping_capability_results
        if not item.supported
    }
    capability_results = tuple(
        sorted(
            capability_results + prep_capability_results,
            key=lambda item: (
                item.capability.value,
                item.rule_id,
                item.message,
            ),
        )
    )
    silver_templates = {
        "entity": "silver_model.sql.jinja2",
        "source_branch": "silver_source_model.sql.jinja2",
        "union": "silver_union_model.sql.jinja2",
        "contribution_lineage": "silver_contribution_lineage.sql.jinja2",
        "reconciliation": "silver_reconciliation.sql.jinja2",
        "stub": "silver_stub_model.sql.jinja2",
    }
    silver_plans: list[ModelPhysicalPlan] = []
    for model in shaped.silver_models:
        if model.identity.artifact_path is None:
            continue
        runtime_plan = _runtime_physical_plan(
            model,
            adapter_name,
            capability_results,
        )
        template_name = silver_templates[model.kind.value]
        if model.runtime is not None:
            template_name = (
                "silver_runtime_scd2.sql.jinja2"
                if model.runtime.authority.history.scd_type.value.value == "2"
                else "silver_runtime_scd1.sql.jinja2"
            )
        silver_plans.append(
            ModelPhysicalPlan(
            model_name=model.identity.model_name,
            artifact_path=model.identity.artifact_path or "",
            template_name=template_name,
            materialization=model.materialization_intent.kind,
            unique_key=model.materialization_intent.unique_key,
            incremental_column=model.materialization_intent.incremental_column,
            dependencies=_dependencies(model),
            runtime=runtime_plan,
        )
        )
    model_plans = tuple(silver_plans)
    collected: list[Diagnostic] = []
    first_error: Exception | None = None
    try:
        quality_plans = _quality_physical_plans(shaped)
    except QualityMaterializationBlocked as exc:
        if mode is ExecutionMode.FAIL_FAST:
            raise
        first_error = first_error or exc
        quality_plans = ()
        collected.extend(
            Diagnostic(
                code="quality.materialization-blocked",
                message=message,
                rule_id=rule_id,
                resource_uri=rule_id,
                stage="quality",
                owner_skill="kairos-design-silver",
                evidence=(f"rule:{rule_id}",),
                remediation=(
                    "Correct the data-quality rule with kairos-design-silver."
                ),
            )
            for rule_id, message in exc.blocking_rules
        )
    adapter_version = adapter_spec(adapter_name).version
    try:
        gold_physical = (
            materialize_gold_product(
                shaped.gold_product,
                adapter_version=adapter_version,
                capability_results=capability_results,
            )
            if shaped.gold_product is not None
            else None
        )
    except Exception as exc:
        if mode is ExecutionMode.FAIL_FAST:
            raise
        first_error = first_error or exc
        gold_physical = None
        collected.append(diagnostic_from_exception(exc, stage="gold"))
    try:
        silver_physical = _silver_physical_plan(
            shaped,
            model_plans,
            quality_plans,
            adapter_name=adapter_name,
            adapter_version=adapter_version,
            capability_results=capability_results,
        )
    except SilverMaterializationBlocked as exc:
        if mode is ExecutionMode.FAIL_FAST:
            raise
        first_error = first_error or exc
        silver_physical = None
        collected.append(diagnostic_from_exception(exc, stage="adapter"))
    if collected:
        raise MaterializationCollectionError(tuple(collected), first_error or ValueError())
    runtime_blockers = {
        reason
        for model_plan in model_plans
        if model_plan.runtime is not None
        for reason in model_plan.runtime.blocking_reasons
    }
    class_names = {item.uri: item.name for item in project.classes}
    unbound = tuple(
        sorted(
            class_names[uri]
            for uri, state in contract.binding_policy.states
            if state == "stub" and uri in class_names
        )
    )
    return MaterializationPlan(
        adapter=AdapterPlan(
            platform=adapter_name.value,
            version=adapter_version,
            template_root=project.template_root,
            capability_results=capability_results,
        ),
        prep_models=prep_plans,
        prep_documents=prep_documents,
        models=model_plans,
        quality_models=quality_plans,
        documents=tuple(
            DocumentPhysicalPlan(
                artifact_path=document.artifact_path,
                template_name="schema_models.yml.jinja2",
            )
            for document in shaped.schema_documents
        ),
        project=ProjectConfigPlan(
            project_name=f"{project.ontology_name}_project",
            domains=(project.ontology_name,),
            gold_domains=(project.ontology_name,) if shaped.has_gold else (),
            emit=project.has_sources,
        ),
        release=ReleasePlan(
            unbound_eligible_names=unbound,
            known_models=tuple(
                sorted(
                    set(project.contracts)
                    | {item.model_name for item in prep_plans}
                )
            ),
            policy_version=contract.policy.version,
            ontology_name=project.ontology_name,
            ontology_version=project.ontology_metadata.version,
            toolkit_version=project.ontology_metadata.toolkit_version,
            closure_version=project.ontology_metadata.closure_hash,
            capability_results=capability_results,
            blocking_reasons=tuple(
                sorted(
                    {
                        issue.message
                        for issue in contract.policy.issues
                        if issue.blocking
                    }
                    | {
                        result.message
                        for result in capability_results
                        if result.disposition is CapabilityDisposition.BLOCKING
                    }
                    | {
                        message
                        for prep_plan in prep_plans
                        for _, message in prep_plan.blocking_reasons
                    }
                    | {message for _, message in mapping_blockers}
                    | {message for _, message in runtime_blockers}
                )
            ),
            blocking_rules=tuple(
                sorted(
                    {
                        (issue.rule_id, issue.message)
                        for issue in contract.policy.issues
                        if issue.blocking
                    }
                    | {
                        (result.rule_id, result.message)
                        for result in capability_results
                        if result.disposition is CapabilityDisposition.BLOCKING
                    }
                    | {
                        reason
                        for prep_plan in prep_plans
                        for reason in prep_plan.blocking_reasons
                    }
                    | mapping_blockers
                    | runtime_blockers
                )
            ),
            projection_blocking_rules=tuple(
                sorted(
                    {
                        (issue.rule_id, issue.message)
                        for issue in contract.policy.issues
                        if issue.blocking and issue.projection_blocking
                    }
                    | {
                        (result.rule_id, result.message)
                        for result in capability_results
                        if result.disposition is CapabilityDisposition.BLOCKING
                    }
                    | {
                        reason
                        for prep_plan in prep_plans
                        for reason in prep_plan.blocking_reasons
                    }
                    | mapping_blockers
                    | runtime_blockers
                )
            ),
            prep_routes=shaped.prep_routes,
            mapping_contract=contract.mapping_contract,
            mapping_capability_results=mapping_capability_results,
            silver_authorities=tuple(
                model.authority
                for model in shaped.silver_models
                if model.kind.value in {"entity", "union"}
                and model.authority is not None
            ),
        ),
        silver=silver_physical,
        gold=gold_physical,
        policy=contract.policy,
    )


def plan_materialization(
    contract: ProjectionContract,
    shaped: ShapedProject,
) -> MaterializationPlan:
    """Preserve the two-argument fail-fast physical-planning contract."""

    return _plan_materialization(contract, shaped)


def collect_materialization(
    contract: ProjectionContract,
    shaped: ShapedProject,
) -> MaterializationPlan:
    """Collect independent physical-planning blockers without rendering."""

    return _plan_materialization(contract, shaped, ExecutionMode.COLLECT)
