# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Pure logical shaping for dbt source, Silver, schema, Gold, and report specs."""

from __future__ import annotations

import re
from dataclasses import replace

from .builders import (
    build_silver_registry,
    freeze_value,
    thaw_value,
)
from .gold_shape import shape_gold_product
from .canonical_hash import temporal_match_count_column
from .context import NormalizedProjectFacts, ProjectionContract, ShapedProject
from .policy_specs import (
    CanonicalTypeKind,
    CanonicalTypeSpec,
    ChangeDetectionStrategy,
    EntityIriMode,
    IdentityStrategy,
    SilverColumnRole,
)
from .specs import (
    CanonicalHashColumnSpec,
    ColumnSpec,
    CoverageSpec,
    MacroSetSpec,
    MaterializationIntent,
    SchemaDocumentSpec,
    SchemaKind,
    SchemaModelSpec,
    SilverModelKind,
    SilverModelSpec,
    SilverForeignKeySpec,
    SilverKeySpec,
    SourceBindingSpec,
    SourceCatalogSpec,
    SourceTableSpec,
    RuntimeModelSpec,
)
from ..uri_utils import camel_to_snake, dbt_source_name

_STRING = CanonicalTypeSpec(CanonicalTypeKind.STRING)
_HASH_STRING = CanonicalTypeSpec(CanonicalTypeKind.STRING, length=64)
_BOOLEAN = CanonicalTypeSpec(CanonicalTypeKind.BOOLEAN)
_INT64 = CanonicalTypeSpec(CanonicalTypeKind.INT64)
_TIMESTAMP = CanonicalTypeSpec(CanonicalTypeKind.TIMESTAMP)


def _model_piece(value: str) -> str:
    result = re.sub(r"[^a-zA-Z0-9_]", "_", camel_to_snake(value)).strip("_")
    if result and result[0].isdigit():
        result = f"s_{result}"
    return result or "source"


def _generated_key_expression(inputs: tuple[str, ...]) -> str:
    return (
        "{{ dbt_utils.generate_surrogate_key(["
        + ", ".join(repr(value) for value in inputs)
        + "]) }}"
    )


def _identity_input_names(model: SilverModelSpec) -> tuple[str, ...]:
    authority = model.authority
    identity = authority.entity_identity if authority is not None else None
    if identity is None:
        return ("_source_system", "_source_record_key")
    if identity.strategy.value is IdentityStrategy.DETERMINISTIC_INTEGRATION_KEY:
        return identity.business.keys.value
    if identity.strategy.value is IdentityStrategy.BUSINESS_KEY and authority.multi_source is None:
        return identity.business.keys.value
    return ("_source_system", "_source_record_key")


def _identity_expression_inputs(
    model: SilverModelSpec,
    columns: tuple[ColumnSpec, ...],
) -> tuple[str, ...]:
    input_names = _identity_input_names(model)
    if model.kind is SilverModelKind.UNION or (
        model.authority is not None and model.authority.runtime is not None
    ):
        return input_names
    by_name = {column.name: column.expression or column.name for column in columns}
    return tuple(by_name.get(name, name) for name in input_names)


def _timestamp_expression(
    timestamp,
    *,
    source_alias: str,
    source_identity_ref: str,
    columns: tuple[ColumnSpec, ...],
    platform: str,
) -> str:
    source = next(
        (item for item in timestamp.sources if item.source_identity_ref == source_identity_ref),
        None,
    )
    source_column = (
        source.source_column
        if source is not None and source.supplied
        else None
        if source is not None
        else timestamp.source_column
    )
    if source_column is None:
        target_type = "DATETIME2" if platform == "fabric" else "TIMESTAMP"
        return f"CAST(NULL AS {target_type})"
    existing = next(
        (column for column in columns if column.name == source_column),
        None,
    )
    if existing is not None and existing.expression:
        return existing.expression
    return f"{source_alias}.{source_column}"


def _apply_identity_contract(
    model: SilverModelSpec,
    *,
    source_identity_ref: str = "",
    platform: str,
) -> SilverModelSpec:
    authority = model.authority
    identity = authority.entity_identity if authority is not None else None
    if identity is None:
        if model.kind is SilverModelKind.SOURCE_BRANCH:
            source = model.sources[0] if model.sources else SourceBindingSpec(alias="source")
            structural = (
                ColumnSpec(
                    "_source_system",
                    expression=f"'{source.source_name}'",
                    canonical_type=_STRING,
                    nullable=False,
                    role=SilverColumnRole.SOURCE_IDENTITY.value,
                    generated_after_mapping=True,
                ),
                ColumnSpec(
                    "_source_identity_ref",
                    expression="CAST(NULL AS {{ dbt.type_string() }})",
                    canonical_type=_STRING,
                    nullable=True,
                    role=SilverColumnRole.SOURCE_IDENTITY.value,
                    generated_after_mapping=True,
                ),
                ColumnSpec(
                    "_source_record_key",
                    expression=model.source_record_key_expression,
                    canonical_type=_STRING,
                    nullable=False,
                    role=SilverColumnRole.SOURCE_IDENTITY.value,
                    generated_after_mapping=(model.source_record_key_generated_after_mapping),
                ),
            )
            names = {column.name for column in model.columns}
            return replace(
                model,
                columns=(
                    *(column for column in structural if column.name not in names),
                    *model.columns,
                ),
            )
        columns = list(
            column for column in model.columns if column.name != f"{model.identity.model_name}_iri"
        )
        if model.kind is SilverModelKind.UNION:
            names = {column.name for column in columns}
            columns.extend(
                ColumnSpec(
                    name=name,
                    expression=name,
                    canonical_type=_STRING,
                    nullable=False,
                    role=SilverColumnRole.SOURCE_IDENTITY.value,
                )
                for name in (
                    "_source_system",
                    "_source_identity_ref",
                    "_source_record_key",
                )
                if name not in names
            )
        by_name = {column.name: column.expression for column in columns}
        key_expression = _generated_key_expression(
            (
                by_name.get("_source_system", "_source_system"),
                by_name.get("_source_record_key", "_source_record_key"),
            )
        )
        columns = tuple(
            (
                replace(
                    column,
                    expression=key_expression,
                    canonical_type=_STRING,
                    nullable=False,
                    role=SilverColumnRole.SURROGATE_JOIN_KEY.value,
                    description="Physical source-scoped join key; identity policy is missing",
                    provenance=tuple(sorted({*column.provenance, "rule:DD-108-surrogate"})),
                    generated_after_mapping=True,
                )
                if column.name == f"{model.identity.model_name}_sk"
                else column
            )
            for column in columns
        )
        return replace(
            model,
            columns=columns,
            surrogate_key_expression=key_expression,
            iri_expression="",
        )

    columns = list(model.columns)
    model_name = model.identity.model_name
    sk_name = f"{model_name}_sk"
    iri_name = f"{model_name}_iri"
    if model.kind is SilverModelKind.SOURCE_BRANCH:
        names = {column.name for column in columns}
        source = model.sources[0] if model.sources else SourceBindingSpec(alias="source")
        structural = (
            ColumnSpec(
                name="_source_system",
                expression=f"'{source.source_name.replace(chr(39), chr(39) * 2)}'",
                canonical_type=_STRING,
                nullable=False,
                role=SilverColumnRole.SOURCE_IDENTITY.value,
                description="Immutable source-system lineage",
                provenance=("rule:DD-108-source-identity",),
                generated_after_mapping=True,
                include_in_change_detection=False,
            ),
            ColumnSpec(
                name="_source_identity_ref",
                expression=(
                    f"'{source_identity_ref.replace(chr(39), chr(39) * 2)}'"
                    if source_identity_ref
                    else "CAST(NULL AS {{ dbt.type_string() }})"
                ),
                canonical_type=_STRING,
                nullable=not bool(source_identity_ref),
                role=SilverColumnRole.SOURCE_IDENTITY.value,
                description="Prepared source-identity policy reference",
                provenance=("rule:DD-108-source-identity",),
                generated_after_mapping=True,
                include_in_change_detection=False,
            ),
            ColumnSpec(
                name="_source_record_key",
                expression=model.source_record_key_expression,
                canonical_type=_STRING,
                nullable=False,
                role=SilverColumnRole.SOURCE_IDENTITY.value,
                description="Source/table-scoped immutable record key",
                provenance=("rule:DD-108-source-identity",),
                generated_after_mapping=(model.source_record_key_generated_after_mapping),
                include_in_change_detection=False,
            ),
        )
        columns = [
            *structural,
            *(
                column
                for column in columns
                if column.name
                not in {
                    "_source_system",
                    "_source_identity_ref",
                    "_source_record_key",
                }
            ),
        ]
        expected = (
            item
            for item in authority.audit.columns
            if item.supplied and item.column_name != "_loaded_at"
        )
        names = {column.name for column in columns}
        alias = model.sources[0].alias if model.sources else "source"
        for timestamp in expected:
            if timestamp.column_name in names:
                continue
            columns.append(
                ColumnSpec(
                    name=timestamp.column_name,
                    expression=_timestamp_expression(
                        timestamp,
                        source_alias=alias,
                        source_identity_ref=source_identity_ref,
                        columns=tuple(columns),
                        platform=platform,
                    ),
                    canonical_type=_TIMESTAMP,
                    nullable=True,
                    role=SilverColumnRole.AUDIT.value,
                    description=f"DD-108 {timestamp.role.value} lineage timestamp",
                    provenance=("rule:DD-108-audit",),
                    include_in_change_detection=False,
                )
            )
        return replace(model, columns=tuple(columns))

    by_name = {column.name: column for column in columns}
    inputs = _identity_expression_inputs(model, tuple(columns))
    key_expression = _generated_key_expression(inputs)
    if model.kind is SilverModelKind.UNION:
        names = {column.name for column in columns}
        lineage_columns = (
            ColumnSpec(
                name="_source_system",
                expression="_source_system",
                canonical_type=_STRING,
                nullable=False,
                role=SilverColumnRole.SOURCE_IDENTITY.value,
                description="Immutable source-system lineage",
                provenance=("rule:DD-108-source-identity",),
                include_in_change_detection=False,
            ),
            ColumnSpec(
                name="_source_identity_ref",
                expression="_source_identity_ref",
                canonical_type=_STRING,
                nullable=False,
                role=SilverColumnRole.SOURCE_IDENTITY.value,
                description="Prepared source-identity policy reference",
                provenance=("rule:DD-108-source-identity",),
                include_in_change_detection=False,
            ),
            ColumnSpec(
                name="_source_record_key",
                expression="_source_record_key",
                canonical_type=_STRING,
                nullable=False,
                role=SilverColumnRole.SOURCE_IDENTITY.value,
                description="Source/table-scoped immutable record key",
                provenance=("rule:DD-108-source-identity",),
                include_in_change_detection=False,
            ),
        )
        columns.extend(column for column in lineage_columns if column.name not in names)
        names.update(column.name for column in lineage_columns)
        for timestamp in authority.audit.columns:
            if timestamp.supplied and timestamp.column_name not in names:
                columns.append(
                    ColumnSpec(
                        name=timestamp.column_name,
                        expression=(
                            "{{ kairos_current_timestamp() }}"
                            if timestamp.column_name == "_loaded_at"
                            else timestamp.column_name
                        ),
                        canonical_type=_TIMESTAMP,
                        nullable=timestamp.column_name != "_loaded_at",
                        role=SilverColumnRole.AUDIT.value,
                        description=f"DD-108 {timestamp.role.value} lineage timestamp",
                        provenance=("rule:DD-108-audit",),
                        generated_after_mapping=timestamp.column_name == "_loaded_at",
                        include_in_change_detection=False,
                    )
                )
        iri_expression = (
            ""
            if identity.iri.mode.value is EntityIriMode.OMIT
            else (
                f"CONCAT('{identity.entity_uri}/instance/', "
                f"{_generated_key_expression(tuple(_identity_input_names(model)))})"
            )
        )
        existing_names = {column.name for column in columns}
        generated_columns = [
            ColumnSpec(
                name=sk_name,
                expression=key_expression,
                canonical_type=_STRING,
                nullable=False,
                role=SilverColumnRole.SURROGATE_JOIN_KEY.value,
                description="Physical surrogate join key; not business identity",
                provenance=("rule:DD-108-surrogate",),
                generated_after_mapping=True,
            )
        ]
        if identity.integration.emitted:
            integration_name = f"{model_name}_integration_key"
            generated_columns.append(
                ColumnSpec(
                    name=integration_name,
                    expression=_generated_key_expression(tuple(identity.business.keys.value)),
                    canonical_type=_STRING,
                    nullable=False,
                    role=SilverColumnRole.INTEGRATION_IDENTITY.value,
                    description="Governed deterministic integration identity",
                    provenance=("rule:DD-108-integration-identity",),
                    generated_after_mapping=True,
                )
            )
        if iri_expression:
            generated_columns.append(
                ColumnSpec(
                    name=iri_name,
                    expression=iri_expression,
                    canonical_type=_STRING,
                    nullable=False,
                    role=SilverColumnRole.ENTITY_IRI.value,
                    description=("Entity-instance IRI; independent of the physical join key"),
                    provenance=("rule:DD-108-entity-iri",),
                    generated_after_mapping=True,
                )
            )
        columns = [
            *(column for column in generated_columns if column.name not in existing_names),
            *columns,
        ]
        return replace(
            model,
            columns=tuple(columns),
            surrogate_key_expression=key_expression,
            integration_key_expression=(
                _generated_key_expression(tuple(identity.business.keys.value))
                if identity.integration.emitted
                else ""
            ),
            iri_expression=iri_expression,
        )

    if sk_name in by_name:
        columns = [
            (
                replace(
                    column,
                    expression=key_expression,
                    canonical_type=_STRING,
                    nullable=False,
                    role=SilverColumnRole.SURROGATE_JOIN_KEY.value,
                    description="Physical surrogate join key; not business identity",
                    provenance=tuple(sorted({*column.provenance, "rule:DD-108-surrogate"})),
                    generated_after_mapping=True,
                )
                if column.name == sk_name
                else column
            )
            for column in columns
        ]
    else:
        columns.insert(
            0,
            ColumnSpec(
                name=sk_name,
                expression=key_expression,
                canonical_type=_STRING,
                nullable=False,
                role=SilverColumnRole.SURROGATE_JOIN_KEY.value,
                description="Physical surrogate join key; not business identity",
                provenance=("rule:DD-108-surrogate",),
                generated_after_mapping=True,
            ),
        )

    integration_name = f"{model_name}_integration_key"
    if identity.integration.emitted and integration_name not in {item.name for item in columns}:
        columns.insert(
            0,
            ColumnSpec(
                name=integration_name,
                expression=_generated_key_expression(tuple(identity.business.keys.value)),
                canonical_type=_STRING,
                nullable=False,
                role=SilverColumnRole.INTEGRATION_IDENTITY.value,
                description="Governed deterministic integration identity",
                provenance=("rule:DD-108-integration-identity",),
                generated_after_mapping=True,
            ),
        )

    if identity.iri.mode.value is EntityIriMode.OMIT:
        columns = [column for column in columns if column.name != iri_name]
    else:
        iri_expression = (
            f"CONCAT('{identity.entity_uri}/instance/', {_generated_key_expression(inputs)})"
        )
        if iri_name in {column.name for column in columns}:
            columns = [
                (
                    replace(
                        column,
                        expression=iri_expression,
                        canonical_type=_STRING,
                        nullable=False,
                        role=SilverColumnRole.ENTITY_IRI.value,
                        description="Entity-instance IRI; independent of the physical join key",
                        provenance=tuple(sorted({*column.provenance, "rule:DD-108-entity-iri"})),
                        generated_after_mapping=True,
                    )
                    if column.name == iri_name
                    else column
                )
                for column in columns
            ]
        else:
            columns.insert(
                1,
                ColumnSpec(
                    name=iri_name,
                    expression=iri_expression,
                    canonical_type=_STRING,
                    nullable=False,
                    role=SilverColumnRole.ENTITY_IRI.value,
                    description="Entity-instance IRI; independent of the physical join key",
                    provenance=("rule:DD-108-entity-iri",),
                    generated_after_mapping=True,
                ),
            )

    if "_source_identity_ref" not in {column.name for column in columns}:
        escaped_ref = source_identity_ref.replace("'", "''")
        columns.append(
            ColumnSpec(
                name="_source_identity_ref",
                expression=(
                    f"'{escaped_ref}'" if escaped_ref else "CAST(NULL AS {{ dbt.type_string() }})"
                ),
                canonical_type=_STRING,
                nullable=not bool(escaped_ref),
                role=SilverColumnRole.SOURCE_IDENTITY.value,
                description="Prepared source-identity policy reference",
                provenance=("rule:DD-108-source-identity",),
                include_in_change_detection=False,
            )
        )

    names = {column.name for column in columns}
    alias = model.sources[0].alias if model.sources else "source"
    for timestamp in authority.audit.columns:
        if not timestamp.supplied or timestamp.column_name in names:
            continue
        expression = (
            "{{ kairos_current_timestamp() }}"
            if timestamp.column_name == "_loaded_at"
            else _timestamp_expression(
                timestamp,
                source_alias=alias,
                source_identity_ref=source_identity_ref,
                columns=tuple(columns),
                platform=platform,
            )
        )
        columns.append(
            ColumnSpec(
                name=timestamp.column_name,
                expression=expression,
                canonical_type=_TIMESTAMP,
                nullable=False if timestamp.column_name == "_loaded_at" else True,
                role=SilverColumnRole.AUDIT.value,
                description=f"DD-108 {timestamp.role.value} lineage timestamp",
                provenance=("rule:DD-108-audit",),
                generated_after_mapping=True,
                include_in_change_detection=False,
            )
        )
        names.add(timestamp.column_name)
    return replace(
        model,
        columns=tuple(columns),
        surrogate_key_expression=key_expression,
        integration_key_expression=(
            _generated_key_expression(tuple(identity.business.keys.value))
            if identity.integration.emitted
            else ""
        ),
        iri_expression=(
            ""
            if identity.iri.mode.value is EntityIriMode.OMIT
            else (
                f"CONCAT('{identity.entity_uri}/instance/', "
                f"{_generated_key_expression(tuple(_identity_input_names(model)))})"
            )
        ),
    )


def _apply_runtime_columns(model: SilverModelSpec) -> SilverModelSpec:
    authority = model.authority
    runtime = authority.runtime if authority is not None else None
    if runtime is None or model.kind not in {
        SilverModelKind.ENTITY,
        SilverModelKind.SOURCE_BRANCH,
    }:
        return model
    alias = model.sources[0].alias if model.sources else "source"
    incremental = runtime.incremental
    technical_columns = (
        incremental.cdc_operation.value,
        incremental.ordering.source_updated_at.value,
        incremental.ordering.source_effective_at.value,
        incremental.ordering.ingested_at.value,
        *incremental.merge_identity.value,
        *incremental.ordering.tie_breakers.value,
    )
    columns = list(model.columns)
    names = {column.name for column in columns}
    for name in dict.fromkeys(technical_columns):
        if name in names:
            continue
        columns.append(
            ColumnSpec(
                name=name,
                expression=f"{alias}.{name}",
                canonical_type=(
                    _INT64
                    if name in incremental.ordering.tie_breakers.value
                    else (
                        _TIMESTAMP
                        if name
                        in {
                            incremental.ordering.source_updated_at.value,
                            incremental.ordering.source_effective_at.value,
                            incremental.ordering.ingested_at.value,
                        }
                        else _STRING
                    )
                ),
                nullable=False,
                role=SilverColumnRole.AUDIT.value,
                description="DD-109 normalized incremental runtime field",
                provenance=("rule:DD-109-runtime-input",),
                include_in_change_detection=False,
            )
        )
        names.add(name)
    return replace(model, columns=tuple(columns))


def _runtime_model(
    model: SilverModelSpec,
    project: NormalizedProjectFacts,
) -> SilverModelSpec:
    authority = model.authority
    runtime_authority = authority.runtime if authority is not None else None
    relationships = (
        {item.property_uri: item for item in authority.foreign_keys}
        if authority is not None
        else {}
    )
    joins = tuple(
        (
            replace(
                join,
                temporal_mode=relationships[join.relationship_uri].mode.value.value,
                as_of_column=(
                    relationships[join.relationship_uri].as_of_column.value
                    if relationships[join.relationship_uri].as_of_column is not None
                    else ""
                ),
            )
            if join.relationship_uri in relationships
            else join
        )
        for join in model.joins
    )
    fk_change_detection = {
        join.fk_column: relationships[join.relationship_uri].participates_in_change_detection.value
        for join in joins
        if join.relationship_uri in relationships
    }
    normalized_model = replace(
        model,
        joins=joins,
        columns=tuple(
            (
                replace(
                    column,
                    include_in_change_detection=fk_change_detection[column.name],
                )
                if column.name in fk_change_detection
                else column
            )
            for column in model.columns
        ),
    )
    if runtime_authority is None or model.kind not in {
        SilverModelKind.ENTITY,
        SilverModelKind.UNION,
    }:
        columns = normalized_model.columns
        if model.kind is SilverModelKind.SOURCE_BRANCH:
            existing_names = {column.name for column in columns}
            columns = (
                *columns,
                *(
                    ColumnSpec(
                        name=temporal_match_count_column(relationship.property_uri),
                        canonical_type=_INT64,
                        nullable=False,
                        default_expression="0",
                        role=SilverColumnRole.FOREIGN_KEY.value,
                        description=(
                            "DD-109 temporal lookup match-count diagnostic for "
                            f"{relationship.property_uri}"
                        ),
                        provenance=(
                            f"property:{relationship.property_uri}",
                            "rule:DD-109-temporal-fk",
                        ),
                        runtime_generated=True,
                        include_in_change_detection=False,
                    )
                    for relationship in relationships.values()
                    if temporal_match_count_column(relationship.property_uri) not in existing_names
                ),
            )
        return replace(
            normalized_model,
            columns=tuple(columns),
            materialization_intent=(
                MaterializationIntent("view")
                if model.kind is SilverModelKind.SOURCE_BRANCH
                else (
                    MaterializationIntent("table")
                    if model.kind in {SilverModelKind.ENTITY, SilverModelKind.UNION}
                    else model.materialization_intent
                )
            ),
            runtime=None,
        )

    identity = authority.entity_identity
    if identity is None:
        raise ValueError(
            f"DD-109 runtime model {model.identity.model_name!r} has no identity authority"
        )
    hash_columns: list[CanonicalHashColumnSpec] = []
    hash_policy = runtime_authority.canonical_hash
    if hash_policy is not None:
        for property_uri in hash_policy.inputs.value:
            matches = {
                (mapping.target_column_name, mapping.target_data_type)
                for mapping in project.mappings.columns
                if mapping.target_property_uri == property_uri
            }
            if not matches:
                relationship_columns = {
                    column.name
                    for column in model.columns
                    if f"relationship:{property_uri}" in column.provenance
                }
                matches = {
                    (column.name, column.canonical_type)
                    for column in model.columns
                    if column.name in relationship_columns and column.canonical_type is not None
                }
            if len(matches) != 1:
                raise ValueError(
                    "DD-109-hash: canonical hash input "
                    f"{property_uri!r} must resolve to exactly one typed Silver column"
                )
            column_name, data_type = next(iter(matches))
            if column_name not in {column.name for column in model.columns}:
                raise ValueError(
                    "DD-109-hash: canonical hash input "
                    f"{property_uri!r} resolves outside model {model.identity.model_name!r}"
                )
            hash_columns.append(CanonicalHashColumnSpec(property_uri, column_name, data_type))

    role_by_name = {item.column.name: item.role.value for item in authority.columns}
    compare_columns = tuple(
        column.name
        for column in normalized_model.columns
        if role_by_name.get(column.name)
        in {SilverColumnRole.BUSINESS, SilverColumnRole.FOREIGN_KEY}
        and column.include_in_change_detection
    )
    if hash_policy is not None:
        hash_input_uris = set(hash_policy.inputs.value)
        for relationship in authority.foreign_keys:
            included = relationship.property_uri in hash_input_uris
            if relationship.participates_in_change_detection.value != included:
                raise ValueError(
                    "DD-109-temporal-fk: canonical hash inputs must agree with "
                    "explicit FK change-detection participation for "
                    f"{relationship.property_uri!r}"
                )
    if (
        runtime_authority.change_detection.value is ChangeDetectionStrategy.COMPARE_COLUMNS
        and not compare_columns
    ):
        raise ValueError(
            f"DD-109-scd: {model.identity.model_name!r} has no change-detection columns"
        )
    if (
        runtime_authority.change_detection.value is ChangeDetectionStrategy.CANONICAL_HASH
        and not hash_columns
    ):
        raise ValueError(f"DD-109-hash: {model.identity.model_name!r} has no canonical hash inputs")

    columns = normalized_model.columns
    incremental = runtime_authority.incremental
    history = runtime_authority.history
    interval_start = (
        history.business_valid_from_column
        if history.time_basis is not None and history.time_basis.value.value == "business-valid"
        else history.system_from_column
    )
    unique_key = (
        incremental.merge_identity.value
        if history.scd_type.value.value == "1"
        else (*incremental.merge_identity.value, interval_start)
    )
    ordering_columns = (
        incremental.ordering.source_effective_at.value,
        incremental.ordering.source_updated_at.value,
        incremental.ordering.ingested_at.value,
        *incremental.ordering.tie_breakers.value,
    )
    runtime_names = {
        "_row_hash",
        history.deleted_flag_column,
        history.business_valid_from_column,
        history.business_valid_to_column,
        history.system_from_column,
        history.system_to_column,
        history.current_flag_column,
        *(
            temporal_match_count_column(relationship.property_uri)
            for relationship in authority.foreign_keys
        ),
    }
    base_columns = [
        column
        for column in columns
        if column.name not in runtime_names and column.name != "_loaded_at"
    ]
    output_columns = [
        ColumnSpec(
            name=temporal_match_count_column(relationship.property_uri),
            canonical_type=_INT64,
            nullable=False,
            default_expression="0",
            role=SilverColumnRole.FOREIGN_KEY.value,
            description=(
                f"DD-109 temporal lookup match-count diagnostic for {relationship.property_uri}"
            ),
            provenance=(
                f"property:{relationship.property_uri}",
                "rule:DD-109-temporal-fk",
            ),
            runtime_generated=True,
            include_in_change_detection=False,
        )
        for relationship in authority.foreign_keys
    ]
    loaded_at = next(
        (column for column in columns if column.name == "_loaded_at"),
        ColumnSpec(
            name="_loaded_at",
            expression="{{ kairos_current_timestamp() }}",
            canonical_type=_TIMESTAMP,
            nullable=False,
            role=SilverColumnRole.AUDIT.value,
            description="Timestamp when this Silver version was materialized",
            provenance=("rule:DD-108-audit",),
            generated_after_mapping=True,
            include_in_change_detection=False,
        ),
    )
    output_columns.extend(
        (
            replace(loaded_at, runtime_generated=True, nullable=False),
            ColumnSpec(
                name=history.deleted_flag_column,
                canonical_type=_BOOLEAN,
                nullable=False,
                default_expression="0",
                role=SilverColumnRole.HISTORY.value,
                description="DD-109 explicit delete/tombstone state",
                provenance=("rule:DD-109-delete",),
                runtime_generated=True,
                include_in_change_detection=False,
            ),
        )
    )
    if runtime_authority.canonical_hash is not None:
        output_columns.append(
            ColumnSpec(
                name="_row_hash",
                canonical_type=_HASH_STRING,
                nullable=False,
                role=SilverColumnRole.HISTORY.value,
                description=("DD-109 canonical SHA-256 v1 lowercase hexadecimal representation"),
                provenance=(
                    f"policy:{runtime_authority.canonical_hash.resource_uri}",
                    "rule:DD-109-hash",
                ),
                runtime_generated=True,
                include_in_change_detection=False,
            )
        )
    if history.scd_type.value.value == "2":
        output_columns.extend(
            (
                ColumnSpec(
                    name=history.business_valid_from_column,
                    canonical_type=_TIMESTAMP,
                    nullable=(
                        history.time_basis is None
                        or history.time_basis.value.value != "business-valid"
                    ),
                    role=SilverColumnRole.HISTORY.value,
                    description="Inclusive business-valid interval start",
                    provenance=("rule:DD-109-business-interval",),
                    runtime_generated=True,
                    include_in_change_detection=False,
                ),
                ColumnSpec(
                    name=history.business_valid_to_column,
                    canonical_type=_TIMESTAMP,
                    nullable=True,
                    role=SilverColumnRole.HISTORY.value,
                    description="Exclusive business-valid interval end",
                    provenance=("rule:DD-109-business-interval",),
                    runtime_generated=True,
                    include_in_change_detection=False,
                ),
                ColumnSpec(
                    name=history.system_from_column,
                    canonical_type=_TIMESTAMP,
                    nullable=False,
                    role=SilverColumnRole.HISTORY.value,
                    description="Inclusive system/load interval start",
                    provenance=("rule:DD-109-system-interval",),
                    runtime_generated=True,
                    include_in_change_detection=False,
                ),
                ColumnSpec(
                    name=history.system_to_column,
                    canonical_type=_TIMESTAMP,
                    nullable=True,
                    role=SilverColumnRole.HISTORY.value,
                    description="Exclusive system/load interval end",
                    provenance=("rule:DD-109-system-interval",),
                    runtime_generated=True,
                    include_in_change_detection=False,
                ),
                ColumnSpec(
                    name=history.current_flag_column,
                    canonical_type=_BOOLEAN,
                    nullable=False,
                    default_expression="1",
                    role=SilverColumnRole.HISTORY.value,
                    description="Deterministic current system version",
                    provenance=("rule:DD-109-current-row",),
                    runtime_generated=True,
                    include_in_change_detection=False,
                ),
            )
        )
    return replace(
        model,
        columns=tuple((*base_columns, *output_columns)),
        joins=joins,
        materialization_intent=MaterializationIntent("incremental", unique_key),
        runtime=RuntimeModelSpec(
            authority=runtime_authority,
            canonical_hash_columns=tuple(hash_columns),
            compare_columns=compare_columns,
            ordering_columns=ordering_columns,
            temporal_relationships=authority.foreign_keys,
        ),
    )


def _identity_auxiliary_models(
    silver_models: tuple[SilverModelSpec, ...],
) -> tuple[SilverModelSpec, ...]:
    result: list[SilverModelSpec] = []
    source_identity_by_model = {
        item.identity.model_name: item.source_identity_ref
        for item in silver_models
        if item.kind is SilverModelKind.SOURCE_BRANCH
    }
    for model in silver_models:
        authority = model.authority
        identity = authority.entity_identity if authority is not None else None
        if (
            identity is None
            or model.kind not in {SilverModelKind.ENTITY, SilverModelKind.UNION}
            or model.identity.artifact_path is None
        ):
            continue
        source_models = (
            model.source_models
            if model.kind is SilverModelKind.UNION
            else (model.identity.model_name,)
        )
        source_refs = identity.source.record_key_refs.value
        source_pairs = (
            tuple(
                (
                    source_model,
                    source_identity_by_model.get(source_model, ""),
                )
                for source_model in source_models
            )
            if model.kind is SilverModelKind.UNION
            else (
                (
                    model.identity.model_name,
                    source_refs[0] if len(source_refs) == 1 else "",
                ),
            )
        )
        actual_source_refs = {source_ref for _, source_ref in source_pairs if source_ref}
        if (
            model.kind is SilverModelKind.UNION
            or authority.multi_source is not None
            or authority.contribution_lineage is not None
        ) and (
            any(not source_ref for _, source_ref in source_pairs)
            or actual_source_refs != set(source_refs)
        ):
            raise ValueError(
                "identity.contributor-source-mismatch: generated source branches must "
                "cover every declared sourceIdentity exactly by reference "
                f"for {model.identity.class_uri!r} [DD-108-contribution-lineage]"
            )
        sources = tuple(
            SourceBindingSpec(
                alias=f"contributor_{index + 1}",
                model_name=source_model,
                table_uri=source_ref,
            )
            for index, (source_model, source_ref) in enumerate(source_pairs)
        )
        directory = model.identity.artifact_path.rsplit("/", 1)[0]
        if authority.contribution_lineage is not None:
            relation_name = authority.contribution_lineage.relation_name
            contribution_columns = (
                ColumnSpec(
                    name=authority.contribution_lineage.parent_key_column,
                    canonical_type=_STRING,
                    nullable=False,
                    role=SilverColumnRole.SURROGATE_JOIN_KEY.value,
                    description=f"Join key to {model.identity.model_name}",
                    provenance=("rule:DD-108-contribution-lineage",),
                ),
                ColumnSpec(
                    "_source_system",
                    canonical_type=_STRING,
                    nullable=False,
                    role=SilverColumnRole.SOURCE_IDENTITY.value,
                    provenance=("rule:DD-108-contribution-lineage",),
                ),
                ColumnSpec(
                    "_source_record_key",
                    canonical_type=_STRING,
                    nullable=False,
                    role=SilverColumnRole.SOURCE_IDENTITY.value,
                    provenance=("rule:DD-108-contribution-lineage",),
                ),
                ColumnSpec(
                    "_contribution_role",
                    canonical_type=_STRING,
                    nullable=False,
                    role=SilverColumnRole.AUDIT.value,
                    provenance=("rule:DD-108-contribution-lineage",),
                ),
                ColumnSpec(
                    "_source_identity_ref",
                    canonical_type=_STRING,
                    nullable=False,
                    role=SilverColumnRole.SOURCE_IDENTITY.value,
                    provenance=("rule:DD-108-contribution-lineage",),
                ),
            )
            result.append(
                SilverModelSpec(
                    identity=replace(
                        model.identity,
                        model_name=relation_name,
                        artifact_path=f"{directory}/{relation_name}.sql",
                    ),
                    kind=SilverModelKind.CONTRIBUTION_LINEAGE,
                    columns=contribution_columns,
                    sources=sources,
                    source_models=source_models,
                    surrogate_key_expression=model.surrogate_key_expression,
                    parent_model=model.identity.model_name,
                    ontology_metadata=model.ontology_metadata,
                    authority=authority,
                )
            )
        if authority.multi_source is not None:
            relation_name = f"{model.identity.model_name}__reconciliation"
            reconciliation_columns = [
                ColumnSpec("_branch_model", canonical_type=_STRING, nullable=False),
                ColumnSpec(
                    "_source_system",
                    canonical_type=_STRING,
                    nullable=False,
                    role=SilverColumnRole.SOURCE_IDENTITY.value,
                ),
                ColumnSpec(
                    "_source_record_key",
                    canonical_type=_STRING,
                    nullable=False,
                    role=SilverColumnRole.SOURCE_IDENTITY.value,
                ),
            ]
            if model.integration_key_expression:
                reconciliation_columns.append(
                    ColumnSpec(
                        f"{model.identity.model_name}_integration_key",
                        canonical_type=_STRING,
                        nullable=False,
                        role=SilverColumnRole.INTEGRATION_IDENTITY.value,
                    )
                )
            reconciliation_columns.extend(
                (
                    ColumnSpec(
                        "_contribution_role",
                        canonical_type=_STRING,
                        nullable=False,
                    ),
                    ColumnSpec(
                        "_source_identity_ref",
                        canonical_type=_STRING,
                        nullable=False,
                        role=SilverColumnRole.SOURCE_IDENTITY.value,
                    ),
                    ColumnSpec(
                        "_source_key_occurrences",
                        canonical_type=_INT64,
                        nullable=False,
                    ),
                    ColumnSpec(
                        (
                            "_integration_key_occurrences"
                            if model.integration_key_expression
                            else "_branch_identity_occurrences"
                        ),
                        canonical_type=_INT64,
                        nullable=False,
                    ),
                    ColumnSpec(
                        "_source_key_collision",
                        canonical_type=_BOOLEAN,
                        nullable=False,
                    ),
                    ColumnSpec(
                        (
                            "_equivalent_branch_overlap"
                            if model.integration_key_expression
                            else "_branch_identity_duplicate"
                        ),
                        canonical_type=_BOOLEAN,
                        nullable=False,
                    ),
                    ColumnSpec(
                        "_conflict_action",
                        canonical_type=_STRING,
                        nullable=False,
                    ),
                    ColumnSpec(
                        "_collision_action",
                        canonical_type=_STRING,
                        nullable=False,
                    ),
                    ColumnSpec(
                        "_branch_deletion_action",
                        canonical_type=_STRING,
                        nullable=False,
                    ),
                    ColumnSpec(
                        "_late_arrival_action",
                        canonical_type=_STRING,
                        nullable=False,
                    ),
                )
            )
            reconciliation_columns = [
                replace(
                    column,
                    provenance=("rule:DD-108-multi-source-reconciliation",),
                )
                for column in reconciliation_columns
            ]
            result.append(
                SilverModelSpec(
                    identity=replace(
                        model.identity,
                        model_name=relation_name,
                        artifact_path=f"{directory}/{relation_name}.sql",
                    ),
                    kind=SilverModelKind.RECONCILIATION,
                    columns=tuple(reconciliation_columns),
                    sources=sources,
                    source_models=source_models,
                    surrogate_key_expression=model.surrogate_key_expression,
                    integration_key_expression=model.integration_key_expression,
                    parent_model=model.identity.model_name,
                    ontology_metadata=model.ontology_metadata,
                    authority=authority,
                )
            )
    return tuple(result)


_REF_MODEL = re.compile(r"""ref\(\s*['"]([^'"]+)['"]\s*\)""")


def _referenced_model(value: str) -> str:
    match = _REF_MODEL.search(value)
    return match.group(1) if match else value.strip()


def _finalize_silver_contracts(
    models: tuple[SilverModelSpec, ...],
) -> tuple[SilverModelSpec, ...]:
    """Commit exact keys, relationships, types, nullability, and provenance."""
    type_by_name: dict[str, set[CanonicalTypeSpec]] = {}
    for item in models:
        for column in item.columns:
            if column.canonical_type is not None:
                type_by_name.setdefault(column.name, set()).add(column.canonical_type)
    result: list[SilverModelSpec] = []
    for model in models:
        authority = model.authority
        identity = authority.entity_identity if authority is not None else None
        normalized_columns: list[ColumnSpec] = []
        for column in model.columns:
            canonical_type = column.canonical_type
            candidates = type_by_name.get(column.name, set())
            if canonical_type is None and len(candidates) == 1:
                canonical_type = next(iter(candidates))
            if canonical_type is None and column.role in {
                SilverColumnRole.SOURCE_IDENTITY.value,
                SilverColumnRole.INTEGRATION_IDENTITY.value,
                SilverColumnRole.MASTERED_IDENTIFIER.value,
                SilverColumnRole.SURROGATE_JOIN_KEY.value,
                SilverColumnRole.ENTITY_IRI.value,
                SilverColumnRole.FOREIGN_KEY.value,
            }:
                canonical_type = _STRING
            nullable = column.nullable
            if nullable is None:
                nullable = column.role not in {
                    SilverColumnRole.SOURCE_IDENTITY.value,
                    SilverColumnRole.INTEGRATION_IDENTITY.value,
                    SilverColumnRole.SURROGATE_JOIN_KEY.value,
                    SilverColumnRole.ENTITY_IRI.value,
                    SilverColumnRole.AUDIT.value,
                    SilverColumnRole.HISTORY.value,
                }
            normalized_columns.append(
                replace(
                    column,
                    canonical_type=canonical_type,
                    nullable=nullable,
                    provenance=tuple(
                        sorted(
                            {
                                *column.provenance,
                                f"class:{model.identity.class_uri}",
                            }
                        )
                    ),
                )
            )
        names = {column.name for column in normalized_columns}

        relationships = (
            {item.property_uri: item for item in authority.foreign_keys}
            if authority is not None
            else {}
        )
        foreign_keys: list[SilverForeignKeySpec] = []
        for join in model.joins:
            if not join.fk_column or join.fk_column not in names:
                continue
            target = _referenced_model(join.referenced_model)
            if not target:
                continue
            relationship = relationships.get(join.relationship_uri)
            temporal_mode = (
                relationship.mode.value.value
                if relationship is not None
                else join.temporal_mode or "none"
            )
            referenced_columns = (f"{target}_sk",)
            foreign_keys.append(
                SilverForeignKeySpec(
                    property_uri=join.relationship_uri,
                    columns=(join.fk_column,),
                    referenced_model=target,
                    referenced_columns=referenced_columns,
                    label=(
                        join.relationship_uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
                        if join.relationship_uri
                        else join.fk_column
                    ),
                    temporal_mode=temporal_mode,
                    as_of_column=(
                        relationship.as_of_column.value
                        if relationship is not None and relationship.as_of_column is not None
                        else join.as_of_column
                    ),
                    interval=(
                        relationship.interval.value.value
                        if relationship is not None and relationship.interval is not None
                        else ""
                    ),
                    cardinality=(
                        relationship.cardinality.value.value if relationship is not None else ""
                    ),
                    missing_action=(
                        relationship.missing_action.value.value if relationship is not None else ""
                    ),
                    ambiguous_action=(
                        relationship.ambiguous_action.value.value
                        if relationship is not None
                        else ""
                    ),
                    late_parent_action=(
                        relationship.late_parent_action.value.value
                        if relationship is not None
                        else ""
                    ),
                    participates_in_change_detection=(
                        relationship.participates_in_change_detection.value
                        if relationship is not None
                        else False
                    ),
                    provenance=tuple(
                        value
                        for value in (
                            f"property:{join.relationship_uri}" if join.relationship_uri else "",
                            (
                                "rule:DD-109-temporal-fk"
                                if relationship is not None
                                else "rule:DD-110-emitted-fk"
                            ),
                        )
                        if value
                    ),
                )
            )

        primary_key = None
        unique_keys: list[SilverKeySpec] = []
        grain = None
        if model.kind in {SilverModelKind.ENTITY, SilverModelKind.UNION}:
            if model.runtime is not None:
                primary_columns = model.materialization_intent.unique_key
            else:
                surrogate = f"{model.identity.model_name}_sk"
                primary_columns = (surrogate,) if surrogate in names else ()
            if primary_columns:
                primary_key = SilverKeySpec(
                    tuple(primary_columns),
                    provenance=("rule:DD-110-primary-key",),
                )
            if identity is not None and identity.integration.emitted:
                grain_columns = (f"{model.identity.model_name}_integration_key",)
            elif (
                identity is not None
                and identity.business.authoritative
                and authority is not None
                and authority.multi_source is None
            ):
                grain_columns = identity.business.keys.value
            else:
                grain_columns = ("_source_system", "_source_record_key")
            grain_columns = tuple(column for column in grain_columns if column in names)
            if grain_columns:
                predicate = (
                    f"{model.runtime.authority.history.current_flag_column} = 1"
                    if model.runtime is not None
                    and model.runtime.authority.history.scd_type.value.value == "2"
                    else ""
                )
                grain = SilverKeySpec(
                    grain_columns,
                    predicate=predicate,
                    provenance=("rule:DD-108-business-grain",),
                )
                unique_keys.append(grain)
        elif model.kind is SilverModelKind.CONTRIBUTION_LINEAGE:
            grain_columns = tuple(
                column
                for column in (
                    f"{model.parent_model}_sk",
                    "_source_system",
                    "_source_record_key",
                )
                if column in names
            )
            grain = SilverKeySpec(
                grain_columns,
                provenance=("rule:DD-108-contribution-lineage",),
            )
            unique_keys.append(grain)

        result.append(
            replace(
                model,
                columns=tuple(normalized_columns),
                primary_key=primary_key,
                unique_keys=tuple(unique_keys),
                grain=grain,
                foreign_keys=tuple(
                    sorted(
                        foreign_keys,
                        key=lambda item: (
                            item.columns,
                            item.referenced_model,
                            item.property_uri,
                        ),
                    )
                ),
                comment=(f"Silver {model.kind.value} for {model.identity.class_name}"),
                provenance=tuple(
                    value
                    for value in (
                        f"class:{model.identity.class_uri}",
                        "rule:DD-110-silver-authority",
                    )
                    if value
                ),
            )
        )
    by_name = {item.identity.model_name: item for item in result}
    propagated: list[SilverModelSpec] = []
    for model in result:
        if model.kind is not SilverModelKind.UNION:
            propagated.append(model)
            continue
        names = {column.name for column in model.columns}
        foreign_keys = {
            (
                item.property_uri,
                item.columns,
                item.referenced_model,
                item.referenced_columns,
            ): item
            for item in model.foreign_keys
        }
        for source_name in model.source_models:
            source = by_name.get(source_name)
            if source is None:
                continue
            for item in source.foreign_keys:
                if all(column in names for column in item.columns):
                    foreign_keys.setdefault(
                        (
                            item.property_uri,
                            item.columns,
                            item.referenced_model,
                            item.referenced_columns,
                        ),
                        item,
                    )
        propagated.append(
            replace(
                model,
                foreign_keys=tuple(
                    sorted(
                        foreign_keys.values(),
                        key=lambda item: (
                            item.columns,
                            item.referenced_model,
                            item.property_uri,
                        ),
                    )
                ),
            )
        )
    return tuple(propagated)


def _schema_model(
    model,
    silver_models: tuple[SilverModelSpec, ...],
) -> SchemaModelSpec:
    silver = next(
        (
            item
            for item in silver_models
            if item.identity.model_name == model.name
            and item.kind in {SilverModelKind.ENTITY, SilverModelKind.UNION}
        ),
        None,
    )
    authority = silver.authority if silver is not None else None
    if authority is None or authority.entity_identity is None:
        documented = {column.name: column for column in model.columns}
        columns = tuple(
            replace(
                column,
                description=(
                    documented[column.name].description
                    if column.name in documented and documented[column.name].description
                    else column.description
                ),
                metadata=(
                    documented[column.name].metadata
                    if column.name in documented
                    else column.metadata
                ),
                tests=(
                    documented[column.name].tests if column.name in documented else column.tests
                ),
            )
            for column in (silver.columns if silver is not None else model.columns)
        )
        return SchemaModelSpec(
            name=model.name,
            description=model.description,
            metadata=model.metadata,
            columns=columns,
            grain_columns=(
                silver.grain.columns
                if silver is not None and silver.grain is not None
                else model.grain_columns
            ),
            source_identity_columns=model.source_identity_columns,
            grain_where=model.grain_where,
            table_type=model.table_type,
            ontology_class=model.ontology_class,
            ontology_iri=model.ontology_iri,
            ontology_version=model.ontology_version,
        )

    identity = authority.entity_identity
    roles_by_column = {
        column: tuple(
            item for item in authority.identity_roles if item.emitted and column in item.columns
        )
        for column in {
            column for item in authority.identity_roles if item.emitted for column in item.columns
        }
    }
    role_by_column = {column: roles[-1] for column, roles in roles_by_column.items() if roles}
    authority_by_column = {item.column.name: item for item in authority.columns}
    temporal_by_property = {item.property_uri: item for item in authority.foreign_keys}
    documented = {column.name: column for column in model.columns}
    physical_columns = (
        {column.name: column for column in silver.columns} if silver is not None else {}
    )
    temporal_by_column = {
        column: temporal_by_property[foreign_key.property_uri]
        for foreign_key in (silver.foreign_keys if silver is not None else ())
        if foreign_key.property_uri in temporal_by_property
        for column in foreign_key.columns
    }
    ordered_names = (
        [column.name for column in silver.columns] if silver is not None else list(documented)
    )
    runtime = authority.runtime

    columns: list[ColumnSpec] = []
    for name in ordered_names:
        physical = physical_columns.get(name, ColumnSpec(name=name, description=name))
        source_documentation = documented.get(name)
        current = replace(
            physical,
            description=(
                source_documentation.description
                if source_documentation is not None and source_documentation.description
                else physical.description
            ),
            metadata=(
                source_documentation.metadata
                if source_documentation is not None
                else physical.metadata
            ),
            tests=(
                source_documentation.tests if source_documentation is not None else physical.tests
            ),
        )
        role = role_by_column.get(name)
        metadata = dict(current.metadata)
        tests = list(current.tests)
        relationship = temporal_by_column.get(name)
        if relationship is not None:
            metadata.update(
                {
                    "temporal_mode": relationship.mode.value.value,
                    "temporal_cardinality": relationship.cardinality.value.value,
                    "missing_parent_action": relationship.missing_action.value.value,
                    "ambiguous_parent_action": (relationship.ambiguous_action.value.value),
                    "late_parent_action": relationship.late_parent_action.value.value,
                    "fk_change_detection": str(
                        relationship.participates_in_change_detection.value
                    ).lower(),
                }
            )
        if role is not None:
            identity_roles = roles_by_column[name]
            metadata.update(
                {
                    "identity_role": role.role.value,
                    "identity_roles": ",".join(
                        identity_role.role.value for identity_role in identity_roles
                    ),
                    "identity_scope": role.key_scope.value,
                    "establishes_business_identity": str(
                        any(
                            identity_role.establishes_business_identity
                            for identity_role in identity_roles
                        )
                    ).lower(),
                }
            )
        column_authority = authority_by_column.get(name)
        identity_role = role_by_column.get(name)
        if identity_role is not None and identity_role.role in {
            SilverColumnRole.INTEGRATION_IDENTITY,
            SilverColumnRole.SURROGATE_JOIN_KEY,
            SilverColumnRole.ENTITY_IRI,
        }:
            tests = [
                test
                for test in tests
                if not (
                    test == "unique"
                    or (isinstance(thaw_value(test), dict) and "unique" in thaw_value(test))
                )
            ]
            tests.append(
                freeze_value(
                    {
                        "unique": {
                            "config": {"where": (f"{runtime.history.current_flag_column} = 1")}
                        }
                    }
                )
                if runtime is not None and runtime.history.scd_type.value.value == "2"
                else "unique"
            )
        if (
            (column_authority is not None and not column_authority.nullable.value)
            or current.nullable is False
        ) and "not_null" not in tests:
            tests.append("not_null")
        columns.append(
            replace(
                current,
                metadata=tuple(sorted(metadata.items())),
                tests=tuple(tests),
            )
        )

    model_metadata = dict(model.metadata)
    model_metadata.update(
        {
            "identity_strategy": identity.strategy.value.value,
            "key_scope": identity.key_scope.value.value,
            "business_grain": identity.business_grain.value,
            "entity_instance_iri_policy": identity.iri.mode.value.value,
            "driving_source_mode": identity.driving_source.mode.value.value,
            "driving_source": (
                identity.driving_source.source_ref.value
                if identity.driving_source.source_ref is not None
                else ""
            ),
            "surrogate_establishes_business_identity": "false",
            "mdm_routed": str(identity.mastered.routed_to_mdm).lower(),
        }
    )
    if authority.multi_source is not None:
        model_metadata.update(
            {
                "branch_relationship": authority.multi_source.relationship.value.value,
                "normalization_policy": authority.multi_source.normalization.statement.value,
                "source_precedence": authority.multi_source.precedence.mode.value.value,
                "attribute_conflict_policy": authority.multi_source.conflict.value.value,
                "key_collision_policy": authority.multi_source.collision.value.value,
                "branch_deletion_policy": authority.multi_source.deletion.value.value,
                "branch_late_arrival_policy": (authority.multi_source.late_arrival.value.value),
                "reconciliation_tests": ",".join(authority.multi_source.reconciliation_tests.value),
            }
        )
    for timestamp in authority.audit.columns:
        model_metadata[f"{timestamp.column_name}_origin"] = timestamp.origin.value.value
        model_metadata[f"{timestamp.column_name}_supplied"] = str(timestamp.supplied).lower()

    grain_columns = silver.grain.columns if silver is not None and silver.grain is not None else ()
    if len(grain_columns) == 1:
        unique_test = (
            freeze_value(
                {"unique": {"config": {"where": f"{runtime.history.current_flag_column} = 1"}}}
            )
            if runtime is not None and runtime.history.scd_type.value.value == "2"
            else "unique"
        )
        columns = [
            (
                replace(
                    column,
                    tests=(
                        *(
                            test
                            for test in column.tests
                            if not (
                                test == "unique"
                                or (
                                    isinstance(thaw_value(test), dict)
                                    and "unique" in thaw_value(test)
                                )
                            )
                        ),
                        unique_test,
                    ),
                )
                if column.name == grain_columns[0]
                else column
            )
            for column in columns
        ]

    def _generic_test(name: str, arguments: dict[str, object]) -> dict[str, object]:
        # dbt is removing top-level generic-test arguments; nest under `arguments`
        # ahead of that removal (v5 Silver path only -- the legacy v4 projector at
        # medallion_dbt_projector.py has its own, separately-emitted generic test).
        return {name: {"arguments": arguments}}

    data_tests: list[object] = []
    if runtime is not None:
        incremental = runtime.incremental
        data_tests.extend(
            (
                _generic_test(
                    "kairos_runtime_total_order",
                    {
                        "identity_columns": list(incremental.merge_identity.value),
                        "ordering_columns": [
                            incremental.ordering.source_effective_at.value,
                            incremental.ordering.source_updated_at.value,
                            incremental.ordering.ingested_at.value,
                            *incremental.ordering.tie_breakers.value,
                        ],
                    },
                ),
                _generic_test(
                    "kairos_runtime_replay_idempotent",
                    {
                        "identity_columns": list(incremental.merge_identity.value),
                        "operation_column": incremental.cdc_operation.value,
                    },
                ),
                _generic_test(
                    "kairos_runtime_cdc_contract",
                    {
                        "operation_column": incremental.cdc_operation.value,
                        "source_updated_at": (incremental.ordering.source_updated_at.value),
                        "source_effective_at": (incremental.ordering.source_effective_at.value),
                        "ingested_at": incremental.ordering.ingested_at.value,
                    },
                ),
                _generic_test(
                    "kairos_runtime_delete_policy",
                    {
                        "operation_column": incremental.cdc_operation.value,
                        "hard_action": incremental.hard_delete.value.value,
                        "soft_action": incremental.soft_delete.value.value,
                    },
                ),
            )
        )
        if runtime.history.scd_type.value.value == "2":
            data_tests.extend(
                (
                    _generic_test(
                        "kairos_runtime_one_current",
                        {
                            "identity_columns": list(incremental.merge_identity.value),
                            "current_column": runtime.history.current_flag_column,
                        },
                    ),
                    _generic_test(
                        "kairos_runtime_half_open_intervals",
                        {
                            "identity_columns": list(incremental.merge_identity.value),
                            "business_from_column": (runtime.history.business_valid_from_column),
                            "business_to_column": runtime.history.business_valid_to_column,
                            "system_from_column": runtime.history.system_from_column,
                            "system_to_column": runtime.history.system_to_column,
                        },
                    ),
                )
            )
    for relationship in authority.foreign_keys:
        data_tests.append(
            _generic_test(
                "kairos_temporal_fk_cardinality",
                {
                    "property_uri": relationship.property_uri,
                    "match_count_column": temporal_match_count_column(relationship.property_uri),
                    "mode": relationship.mode.value.value,
                    "cardinality": relationship.cardinality.value.value,
                    "missing_action": relationship.missing_action.value.value,
                    "ambiguous_action": relationship.ambiguous_action.value.value,
                },
            )
        )

    return SchemaModelSpec(
        name=model.name,
        description=model.description,
        metadata=tuple(sorted((key, str(value)) for key, value in model_metadata.items())),
        columns=tuple(columns),
        grain_columns=grain_columns,
        source_identity_columns=("_source_system", "_source_record_key"),
        grain_where=(
            f"{runtime.history.current_flag_column} = 1"
            if runtime is not None and runtime.history.scd_type.value.value == "2"
            else ""
        ),
        table_type=model.table_type,
        ontology_class=model.ontology_class,
        ontology_iri=model.ontology_iri,
        ontology_version=model.ontology_version,
        data_tests=tuple(freeze_value(test) for test in data_tests),
        authority=authority,
    )


def _source_catalogs(project: NormalizedProjectFacts) -> tuple[SourceCatalogSpec, ...]:
    mapped = {mapping.source_table_uri for mapping in project.mappings.tables}
    mapped.update(project.replacement_input_uris)
    # #584: physical tables read via {{ source() }} inside contracted dbt model closures
    # must be declared in the same shared per-system catalogs, or the emitted project
    # fails dbt parse offline.
    mapped.update(project.contracted_input_uris)
    catalogs: list[SourceCatalogSpec] = []
    for system in project.systems:
        source_name = dbt_source_name(system.label)
        tables = tuple(
            SourceTableSpec(name=table.name, label=table.label)
            for table in system.tables
            if table.relation_kind == "physical"
            and table.uri not in project.virtual_table_uris
            and (not mapped or table.uri in mapped)
        )
        if not tables:
            continue
        catalogs.append(
            SourceCatalogSpec(
                artifact_path=f"models/silver/_{source_name}__sources.yml",
                source_name=source_name,
                system_label=system.label,
                database=system.database,
                schema=system.schema,
                tables=tables,
                logical_sources_only=project.logical_sources_only,
            )
        )
    return tuple(catalogs)


def _silver_models(
    project: NormalizedProjectFacts,
) -> tuple[SilverModelSpec, ...]:
    specs: list[SilverModelSpec] = []
    for candidate in project.silver_models:
        model = SilverModelSpec(
            identity=candidate.identity,
            kind=candidate.kind,
            columns=candidate.columns,
            sources=candidate.sources,
            joins=candidate.joins,
            materialization_intent=candidate.materialization_intent,
            ontology_metadata=candidate.ontology_metadata,
            where_clause=candidate.where_clause,
            source_models=candidate.source_models,
            surrogate_key_expression=candidate.surrogate_key_expression,
            integration_key_expression=candidate.integration_key_expression,
            iri_expression=candidate.iri_expression,
            parent_model=candidate.parent_model,
            source_identity_ref=candidate.source_identity_ref,
            source_record_key_expression=candidate.source_record_key_expression,
            source_record_key_generated_after_mapping=(
                candidate.source_record_key_generated_after_mapping
            ),
            authority=candidate.authority,
        )
        identity_model = _apply_identity_contract(
            model,
            source_identity_ref=candidate.source_identity_ref,
            platform=project.target_platform,
        )
        specs.append(_runtime_model(_apply_runtime_columns(identity_model), project))
    return tuple(specs)


def shape_project(contract: ProjectionContract) -> ShapedProject:
    """Create ordered logical specs without RDF, file access, or rendering."""
    project = contract.project
    primary_silver_models = _finalize_silver_contracts(_silver_models(project))
    silver_models = _finalize_silver_contracts(
        (
            *primary_silver_models,
            *_identity_auxiliary_models(primary_silver_models),
        )
    )
    registry = build_silver_registry(
        project.silver_outcomes,
        project.parent_relations,
        (model.authority for model in silver_models if model.authority is not None),
        ontology_version=project.ontology_metadata.version,
        materialized_models=silver_models,
    )
    gold_product = shape_gold_product(
        project.policy,
        registry,
        silver_models,
        contract.fk_classification,
        ontology_name=project.ontology_name,
        ontology_version=project.ontology_metadata.version,
        required=False,
    )

    schema_documents: list[SchemaDocumentSpec] = []
    if project.schema_models:
        schema_documents.append(
            SchemaDocumentSpec(
                artifact_path=(
                    f"models/silver/{project.ontology_name}/_{project.ontology_name}__models.yml"
                ),
                kind=SchemaKind.SILVER,
                models=tuple(
                    _schema_model(model, primary_silver_models) for model in project.schema_models
                ),
            )
        )
    return ShapedProject(
        source_catalogs=_source_catalogs(project),
        silver_models=silver_models,
        silver_outcomes=project.silver_outcomes,
        schema_documents=tuple(schema_documents),
        gold_product=gold_product,
        silver_registry=registry,
        coverage=(
            CoverageSpec(
                domain_name=project.coverage.domain_name,
                entities=project.coverage.entities,
            )
            if project.coverage is not None
            else None
        ),
        macros=MacroSetSpec(project.macro_names),
        warnings=project.warnings,
        policy=project.policy,
    )
