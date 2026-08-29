# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Jinja adapters used exclusively by the dbt render phase."""

from __future__ import annotations

from collections.abc import Iterable

from jinja2 import Environment

from .builders import metadata_context, thaw_value
from .canonical_hash import (
    CanonicalHashSqlInput,
    canonical_hash_macro_call,
    temporal_match_count_column,
)
from .mapping_renderers import (
    render_mapping_expression,
    render_mapping_join_condition,
)
from .mapping_specs import MappingContractError
from .silver_contract import (
    canonical_type_label,
    silver_column_marker,
    silver_model_fingerprint,
)
from .specs import (
    ColumnSpec,
    ModelPhysicalPlan,
    SchemaModelSpec,
    SilverModelSpec,
    SilverModelKind,
    SilverModelPhysicalPlan,
    SourceBindingSpec,
)


def _column_context(
    column: ColumnSpec,
    *,
    schema: bool = False,
    adapter: str = "",
    sources: tuple[SourceBindingSpec, ...] = (),
    physical=None,
) -> dict[str, object]:
    if schema:
        metadata = dict(column.metadata)
        data_type = ""
        if column.canonical_type is not None:
            metadata["canonical_type"] = canonical_type_label(column.canonical_type)
        if column.nullable is not None:
            metadata["nullable"] = str(column.nullable).lower()
        if column.default_expression:
            metadata["default"] = column.default_expression
        if column.role:
            metadata["silver_role"] = column.role
        if column.provenance:
            metadata["provenance"] = ",".join(column.provenance)
        if physical is not None:
            metadata["physical_type"] = physical.physical_type
            metadata["ordinal"] = str(physical.ordinal)
            data_type = physical.physical_type
        return {
            "name": column.name,
            "description": column.description,
            "meta": metadata,
            "tests": [thaw_value(test) for test in column.tests],
            "data_type": data_type,
        }
    if column.mapping_resource_uri and column.mapping_expression is None:
        raise MappingContractError(
            "mapping.render-blocked",
            "mapped column has no validated expression contract",
            resource_uri=column.mapping_resource_uri,
            rule_id="DD-107-render",
        )
    expression = (
        render_mapping_expression(
            column.mapping_expression,
            adapter=adapter,
            sources=sources,
        )
        if column.mapping_expression is not None
        else column.expression
    )
    context: dict[str, object] = {
        "expression": expression,
        "name": column.name,
        "target_name": column.name,
        "role": column.role,
        "runtime_generated": column.runtime_generated,
    }
    if column.description:
        context["comment"] = column.description
    if column.data_type:
        context["data_type"] = column.data_type
    if column.generated_after_mapping:
        context["generated_after_mapping"] = True
    if not column.include_in_change_detection:
        context["include_in_change_detection"] = False
    return context


def _source_context(source: SourceBindingSpec, adapter: str) -> dict[str, object]:
    context: dict[str, object] = {"alias": source.alias}
    if source.source_name:
        context["source_name"] = source.source_name
    if source.table_name:
        context["table_name"] = source.table_name
        context["raw_table_name"] = source.table_name
    if source.table_uri:
        context["table_uri"] = source.table_uri
    if source.model_name:
        context["model"] = source.model_name
    if source.generator == "date_spine":
        context["cte"] = (
            "SELECT CAST(value AS DATE) AS date_key\n"
            f"    FROM {{{{ kairos_date_spine({source.generator_argument}) }}}}"
        )
    if source.filter_mapping_resource_uri and source.filter_expression is None:
        raise MappingContractError(
            "mapping.render-blocked",
            "mapped row filter has no validated expression contract",
            resource_uri=source.filter_mapping_resource_uri,
            rule_id="DD-107-render",
        )
    filter_expression = (
        render_mapping_expression(
            source.filter_expression,
            adapter=adapter,
            sources=(source,),
        )
        if source.filter_expression is not None
        else source.filter_condition
    )
    if filter_expression:
        context["filter"] = filter_expression
    if source.ref_model:
        context["ref_model"] = source.ref_model
    return context


def _join_context(join, adapter: str) -> dict[str, object]:
    return {
        "type": join.join_type,
        "alias": join.alias,
        "condition": render_mapping_join_condition(join, adapter=adapter),
        "ref": join.referenced_model,
        "fk_column": join.fk_column,
    }


def _runtime_context(
    spec: SilverModelSpec,
    adapter: str,
) -> dict[str, object]:
    runtime = spec.runtime
    if runtime is None:
        return {}
    authority = runtime.authority
    incremental = authority.incremental
    history = authority.history
    relationships = {
        relationship.property_uri: relationship for relationship in runtime.temporal_relationships
    }
    columns = [
        _column_context(
            column,
            adapter=adapter,
            sources=spec.sources,
        )
        for column in spec.columns
        if not column.runtime_generated
    ]
    temporal_lookups: list[dict[str, object]] = []
    for join in spec.joins:
        relationship = relationships.get(join.relationship_uri)
        if relationship is None:
            continue
        source_partition = ", ".join(
            next(
                (
                    column["expression"]
                    for column in columns
                    if column["target_name"] == merge_column
                ),
                (f"{join.source_alias}.{merge_column}" if join.source_alias else merge_column),
            )
            for merge_column in incremental.merge_identity.value
        )
        parent_key = next(
            (column["expression"] for column in columns if column["target_name"] == join.fk_column),
            f"{join.alias}.{join.fk_column}",
        )
        match_count = temporal_match_count_column(relationship.property_uri)
        temporal_lookups.append(
            {
                "property_uri": relationship.property_uri,
                "join": _join_context(join, adapter),
                "parent_key": parent_key,
                "match_count_column": match_count,
                "match_count_expression": (
                    f"COUNT({parent_key}) OVER (PARTITION BY {source_partition})"
                ),
                "mode": relationship.mode.value.value,
                "cardinality": relationship.cardinality.value.value,
                "missing_action": relationship.missing_action.value.value,
                "ambiguous_action": relationship.ambiguous_action.value.value,
                "late_parent_action": relationship.late_parent_action.value.value,
                "participates_in_change_detection": (
                    relationship.participates_in_change_detection.value
                ),
                "quarantine_missing": relationship.missing_action.value.value
                in {"quarantine", "retry"},
                "quarantine_ambiguous": relationship.ambiguous_action.value.value
                in {"quarantine", "retry"},
                "unknown_member": (relationship.missing_action.value.value == "unknown-member"),
            }
        )
    joined_relationships = {join.relationship_uri for join in spec.joins if join.relationship_uri}
    for relationship in runtime.temporal_relationships:
        if relationship.property_uri in joined_relationships:
            continue
        temporal_lookups.append(
            {
                "property_uri": relationship.property_uri,
                "join": {"fk_column": ""},
                "parent_key": "NULL",
                "match_count_column": temporal_match_count_column(relationship.property_uri),
                "match_count_expression": "0",
                "mode": relationship.mode.value.value,
                "cardinality": relationship.cardinality.value.value,
                "missing_action": relationship.missing_action.value.value,
                "ambiguous_action": relationship.ambiguous_action.value.value,
                "late_parent_action": relationship.late_parent_action.value.value,
                "participates_in_change_detection": (
                    relationship.participates_in_change_detection.value
                ),
                "quarantine_missing": relationship.missing_action.value.value
                in {"quarantine", "retry"},
                "quarantine_ambiguous": relationship.ambiguous_action.value.value
                in {"quarantine", "retry"},
                "unknown_member": False,
            }
        )
    for column in columns:
        lookup = next(
            (
                item
                for item in temporal_lookups
                if item["join"]["fk_column"] == column["target_name"]
            ),
            None,
        )
        if lookup is not None and lookup["unknown_member"]:
            column["expression"] = f"COALESCE({column['expression']}, '__KAIROS_UNKNOWN__')"

    canonical_hash = (
        canonical_hash_macro_call(
            tuple(
                CanonicalHashSqlInput(item.column_name, item.data_type)
                for item in runtime.canonical_hash_columns
            )
        )
        if runtime.canonical_hash_columns
        else ""
    )
    lookback = incremental.lookback.value
    diagnostic_columns = [
        temporal_match_count_column(item.property_uri) for item in runtime.temporal_relationships
    ]
    temporal_actions = [
        {
            "match_count_column": temporal_match_count_column(item.property_uri),
            "quarantine_missing": item.missing_action.value.value in {"quarantine", "retry"},
            "quarantine_ambiguous": item.ambiguous_action.value.value in {"quarantine", "retry"},
        }
        for item in runtime.temporal_relationships
    ]
    newer_terms = []
    for index, column in enumerate(runtime.ordering_columns):
        equal_prefix = " AND ".join(
            f"source.{prior} = target.{prior}" for prior in runtime.ordering_columns[:index]
        )
        newer = f"source.{column} > target.{column}"
        newer_terms.append(f"({equal_prefix} AND {newer})" if equal_prefix else newer)
    required_input_names = (
        incremental.cdc_operation.value,
        incremental.ordering.source_updated_at.value,
        incremental.ordering.source_effective_at.value,
        incremental.ordering.ingested_at.value,
        *incremental.ordering.tie_breakers.value,
        *incremental.merge_identity.value,
    )
    input_columns = list(
        dict.fromkeys(
            [
                column["target_name"]
                for column in columns
                if not column.get("generated_after_mapping", False)
                and column["target_name"] != "_loaded_at"
            ]
            + list(required_input_names)
            + diagnostic_columns
        )
    )
    column_by_name = {column["target_name"]: column for column in columns}
    missing_inputs = [
        name
        for name in input_columns
        if name not in column_by_name and name not in diagnostic_columns
    ]
    if missing_inputs and spec.kind is SilverModelKind.ENTITY:
        raise ValueError(
            "DD-109 runtime inputs are absent from the logical Silver model: "
            + ", ".join(missing_inputs)
        )
    return {
        "runtime": {
            "model_kind": spec.kind.value,
            "timestamp_type": "DATETIME2(6)" if adapter == "fabric" else "TIMESTAMP",
            "scd_type": history.scd_type.value.value,
            "time_basis": (
                history.time_basis.value.value
                if history.time_basis is not None
                else "current-state"
            ),
            "merge_identity": list(incremental.merge_identity.value),
            "cdc_operation": incremental.cdc_operation.value,
            "source_updated_at": incremental.ordering.source_updated_at.value,
            "source_effective_at": incremental.ordering.source_effective_at.value,
            "ingested_at": incremental.ordering.ingested_at.value,
            "ordering_columns": list(runtime.ordering_columns),
            "newer_predicate": " OR ".join(newer_terms),
            "contradictory_tie_failure": (
                "CAST('DD-109 contradictory exact replay tie' AS INTEGER)"
                if adapter == "fabric"
                else "RAISE_ERROR('DD-109 contradictory exact replay tie')"
            ),
            "tie_breakers": list(incremental.ordering.tie_breakers.value),
            "lookback_amount": lookback.amount,
            "lookback_unit": lookback.unit.value,
            "hard_delete": incremental.hard_delete.value.value,
            "soft_delete": incremental.soft_delete.value.value,
            "late_arrival": incremental.late_arrival.value.value,
            "correction": incremental.correction.value.value,
            "replay": incremental.replay.value.value,
            "backfill": incremental.backfill.value.value,
            "schema_evolution": incremental.schema_evolution.action.value.value,
            "on_schema_change": (
                "sync_all_columns"
                if incremental.schema_evolution.action.value.value == "approved-contract-update"
                else "fail"
            ),
            "business_valid_from": history.business_valid_from_column,
            "business_valid_to": history.business_valid_to_column,
            "system_from": history.system_from_column,
            "system_to": history.system_to_column,
            "current_flag": history.current_flag_column,
            "deleted_flag": history.deleted_flag_column,
            "canonical_hash": canonical_hash,
            "compare_columns": list(runtime.compare_columns),
            "columns": columns,
            "input_columns": input_columns,
            "input_select_columns": [
                column_by_name[name] for name in input_columns if name in column_by_name
            ],
            "base_columns": [
                column for column in columns if not column.get("generated_after_mapping", False)
            ],
            "generated_columns": [
                column for column in columns if column.get("generated_after_mapping", False)
            ],
            "temporal_lookups": temporal_lookups,
            "diagnostic_columns": diagnostic_columns,
            "temporal_actions": temporal_actions,
        }
    }


def render_silver_model(
    spec: SilverModelSpec,
    env: Environment,
    plan: ModelPhysicalPlan,
    adapter: str,
) -> str:
    """Render one Silver spec through the existing template contract."""
    unique_keys = plan.unique_key
    unique_key: str | list[str] = ""
    if len(unique_keys) == 1:
        unique_key = unique_keys[0]
    elif unique_keys:
        unique_key = list(unique_keys)
    context: dict[str, object] = {
        "model_name": spec.identity.model_name,
        "domain_name": spec.identity.domain_name,
        "schema_name": spec.identity.schema_name,
        "columns": [
            _column_context(
                column,
                adapter=adapter,
                sources=spec.sources,
            )
            for column in spec.columns
        ],
        "ontology_metadata": metadata_context(spec.ontology_metadata),
    }
    if spec.kind is SilverModelKind.ENTITY:
        context.update(
            {
                "unique_key": unique_key,
                "source_ctes": [_source_context(source, adapter) for source in spec.sources],
                "joins": [_join_context(join, adapter) for join in spec.joins],
                "where_clause": spec.where_clause,
            }
        )
    elif spec.kind is SilverModelKind.SOURCE_BRANCH:
        source = spec.sources[0]
        source_context = _source_context(source, adapter)
        context.update(
            {
                "source_name": source.source_name,
                "raw_table_name": source.table_name,
                "source_alias": source.alias,
                "joins": [_join_context(join, adapter) for join in spec.joins],
                "filter_condition": source_context.get("filter", ""),
                "source_record_key_expression": spec.source_record_key_expression,
                "source_record_key_generated_after_mapping": (
                    spec.source_record_key_generated_after_mapping
                ),
                "parent_model": spec.parent_model,
                "ref_model": source.ref_model,
                "source_identity_ref": spec.source_identity_ref,
            }
        )
    elif spec.kind is SilverModelKind.UNION:
        entity_identity = spec.authority.entity_identity if spec.authority is not None else None
        multi_source = spec.authority.multi_source if spec.authority is not None else None
        context.update(
            {
                "unique_key": unique_key,
                "source_models": list(spec.source_models),
                "sk_expression": spec.surrogate_key_expression,
                "integration_key_expression": spec.integration_key_expression,
                "iri_expression": spec.iri_expression,
                "identity_strategy": (
                    entity_identity.strategy.value.value if entity_identity is not None else ""
                ),
                "key_scope": (
                    entity_identity.key_scope.value.value if entity_identity is not None else ""
                ),
                "branch_relationship": (
                    multi_source.relationship.value.value if multi_source is not None else ""
                ),
                "source_precedence": (
                    list(multi_source.precedence.ordered_sources.value)
                    if multi_source is not None
                    else []
                ),
            }
        )
    elif spec.kind in {
        SilverModelKind.CONTRIBUTION_LINEAGE,
        SilverModelKind.RECONCILIATION,
    }:
        authority = spec.authority
        identity = authority.entity_identity if authority is not None else None
        multi_source = authority.multi_source if authority is not None else None
        driving_source = (
            identity.driving_source.source_ref.value
            if identity is not None and identity.driving_source.source_ref is not None
            else ""
        )
        context.update(
            {
                "parent_model": spec.parent_model,
                "parent_key_column": f"{spec.parent_model}_sk",
                "parent_key_expression": (
                    f"{spec.parent_model}_sk"
                    if spec.source_models == (spec.parent_model,)
                    else spec.surrogate_key_expression
                ),
                "source_models": [
                    {
                        "name": source.model_name,
                        "identity_ref": source.table_uri,
                        "role": (
                            "driving" if source.table_uri == driving_source else "contributor"
                        ),
                    }
                    for source in spec.sources
                ],
                "integration_key_expression": spec.integration_key_expression,
                "branch_relationship": (
                    multi_source.relationship.value.value if multi_source is not None else ""
                ),
                "normalization_policy": (
                    multi_source.normalization.statement.value if multi_source is not None else ""
                ),
                "source_precedence": (
                    list(multi_source.precedence.ordered_sources.value)
                    if multi_source is not None
                    else []
                ),
                "conflict_action": (
                    multi_source.conflict.value.value if multi_source is not None else ""
                ),
                "collision_action": (
                    multi_source.collision.value.value if multi_source is not None else ""
                ),
                "deletion_action": (
                    multi_source.deletion.value.value if multi_source is not None else ""
                ),
                "late_arrival_action": (
                    multi_source.late_arrival.value.value if multi_source is not None else ""
                ),
                "reconciliation_tests": (
                    list(multi_source.reconciliation_tests.value)
                    if multi_source is not None
                    else []
                ),
            }
        )
    if (
        spec.kind is SilverModelKind.SOURCE_BRANCH
        and spec.authority is not None
        and spec.authority.foreign_keys
    ):
        relationship_by_uri = {item.property_uri: item for item in spec.authority.foreign_keys}
        column_contexts = context["columns"]
        temporal_lookups = []
        for join in spec.joins:
            relationship = relationship_by_uri.get(join.relationship_uri)
            if relationship is None:
                continue
            parent_key = next(
                (
                    column["expression"]
                    for column in column_contexts
                    if column["target_name"] == join.fk_column
                ),
                f"{join.alias}.{join.fk_column}",
            )
            runtime_authority = spec.authority.runtime
            merge_identity = (
                runtime_authority.incremental.merge_identity.value
                if runtime_authority is not None
                else ("_source_record_key",)
            )
            source_partition = ", ".join(
                next(
                    (
                        column["expression"]
                        for column in column_contexts
                        if column["target_name"] == merge_column
                    ),
                    (f"{join.source_alias}.{merge_column}" if join.source_alias else merge_column),
                )
                for merge_column in merge_identity
            )
            diagnostic = temporal_match_count_column(relationship.property_uri)
            temporal_lookups.append(
                {
                    "join": _join_context(join, adapter),
                    "match_count_column": diagnostic,
                    "match_count_expression": (
                        f"COUNT({parent_key}) OVER (PARTITION BY {source_partition})"
                    ),
                    "unknown_member": (relationship.missing_action.value.value == "unknown-member"),
                    "quarantine_missing": relationship.missing_action.value.value
                    in {"quarantine", "retry"},
                    "quarantine_ambiguous": (
                        relationship.ambiguous_action.value.value in {"quarantine", "retry"}
                    ),
                }
            )
        joined_relationships = {
            join.relationship_uri for join in spec.joins if join.relationship_uri
        }
        for relationship in spec.authority.foreign_keys:
            if relationship.property_uri in joined_relationships:
                continue
            temporal_lookups.append(
                {
                    "join": {"fk_column": ""},
                    "match_count_column": temporal_match_count_column(relationship.property_uri),
                    "match_count_expression": "0",
                    "unknown_member": False,
                    "quarantine_missing": relationship.missing_action.value.value
                    in {"quarantine", "retry"},
                    "quarantine_ambiguous": (
                        relationship.ambiguous_action.value.value in {"quarantine", "retry"}
                    ),
                }
            )
        for column in column_contexts:
            lookup = next(
                (
                    item
                    for item in temporal_lookups
                    if item["join"]["fk_column"] == column["target_name"]
                ),
                None,
            )
            if lookup is not None and lookup["unknown_member"]:
                column["expression"] = f"COALESCE({column['expression']}, '__KAIROS_UNKNOWN__')"
        context["temporal_lookups"] = temporal_lookups
    context.update(_runtime_context(spec, adapter))
    content = env.get_template(plan.template_name).render(**context)
    header = (
        f"-- DD-110-SILVER-SPEC-SHA256: {silver_model_fingerprint(spec)}\n"
        f"-- DD-110-COLUMNS: {silver_column_marker(spec)}\n"
    )
    return header + content


def _schema_context(
    model: SchemaModelSpec,
    physical: SilverModelPhysicalPlan | None,
) -> dict[str, object]:
    physical_columns = (
        {column.name: column for column in physical.columns} if physical is not None else {}
    )
    return {
        "name": model.name,
        "description": model.description,
        "meta": dict(model.metadata),
        "columns": [
            _column_context(
                column,
                schema=True,
                physical=physical_columns.get(column.name),
            )
            for column in model.columns
        ],
        "grain_columns": list(model.grain_columns),
        "source_identity_columns": list(model.source_identity_columns),
        "grain_where": model.grain_where,
        "table_type": model.table_type,
        "ontology_class": model.ontology_class,
        "ontology_iri": model.ontology_iri,
        "ontology_version": model.ontology_version,
        "data_tests": [thaw_value(test) for test in model.data_tests],
    }


def render_schema_models(
    models: Iterable[SchemaModelSpec],
    env: Environment,
    *,
    template_name: str,
    physical_models: Iterable[SilverModelPhysicalPlan] = (),
) -> str:
    """Render immutable schema specs through the existing YAML template."""
    physical = {model.model_name: model for model in physical_models}
    return env.get_template(template_name).render(
        models=[_schema_context(model, physical.get(model.name)) for model in models]
    )
