# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Pure builders for immutable dbt logical specifications."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING

from ..uri_utils import camel_to_snake
from .specs import (
    ColumnSpec,
    FrozenMapping,
    FrozenSequence,
    FrozenValue,
    JoinSpec,
    MaterializationIntent,
    ModelIdentity,
    ModelOutcome,
    OntologyMetadataSpec,
    SchemaModelSpec,
    SilverModelOutcome,
    SilverModelSpec,
    SilverRegistry,
    SilverModelKind,
    SourceBindingSpec,
)

if TYPE_CHECKING:
    from .policy_specs import SilverModelAuthoritySpec


def freeze_value(value: object) -> FrozenValue:
    """Deep-freeze template-shaped values without weakening their type to ``Any``."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return FrozenMapping(tuple((str(key), freeze_value(item)) for key, item in value.items()))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return FrozenSequence(tuple(freeze_value(item) for item in value))
    raise TypeError(f"Unsupported logical template value: {type(value).__name__}")


def thaw_value(value: FrozenValue) -> object:
    """Adapt an immutable value back to the current Jinja template context."""
    if isinstance(value, FrozenMapping):
        return {key: thaw_value(item) for key, item in value.entries}
    if isinstance(value, FrozenSequence):
        return [thaw_value(item) for item in value.values]
    return value


def build_metadata(metadata: Mapping[str, object] | None) -> OntologyMetadataSpec:
    """Build the typed subset of provenance metadata consumed by dbt templates."""
    values = metadata or {}

    def text(key: str) -> str:
        value = values.get(key)
        return str(value) if value is not None else ""

    def texts(key: str) -> tuple[str, ...]:
        value = values.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return tuple(str(item) for item in value)
        return ()

    return OntologyMetadataSpec(
        generated_at=text("generated_at"),
        iri=text("iri"),
        version=text("version"),
        toolkit_version=text("toolkit_version"),
        closure_hash=text("closure_hash"),
        silver_default_packages=texts("silver_default_packages"),
        silver_overrides=texts("silver_overrides"),
    )


def metadata_context(metadata: OntologyMetadataSpec) -> dict[str, object]:
    """Return the legacy Jinja metadata shape."""
    return {
        "generated_at": metadata.generated_at,
        "iri": metadata.iri,
        "version": metadata.version,
        "toolkit_version": metadata.toolkit_version,
        "closure_hash": metadata.closure_hash,
        "silver_default_packages": list(metadata.silver_default_packages),
        "silver_overrides": list(metadata.silver_overrides),
    }


def column_from_context(column: Mapping[str, object]) -> ColumnSpec:
    """Build one immutable logical column from a retained helper context."""
    metadata = column.get("meta")
    metadata_items = (
        tuple((str(key), str(value)) for key, value in metadata.items())
        if isinstance(metadata, Mapping)
        else ()
    )
    tests = column.get("tests")
    test_items = (
        tuple(freeze_value(item) for item in tests)
        if isinstance(tests, Sequence) and not isinstance(tests, (str, bytes, bytearray))
        else ()
    )
    return ColumnSpec(
        name=str(column.get("target_name") or column.get("name") or ""),
        expression=str(column.get("expression") or ""),
        data_type=str(column.get("data_type") or ""),
        description=str(column.get("description") or column.get("comment") or ""),
        metadata=metadata_items,
        tests=test_items,
        generated_after_mapping=bool(column.get("generated_after_mapping", False)),
        include_in_change_detection=bool(column.get("include_in_change_detection", True)),
        mapping_resource_uri=str(column.get("mapping_resource_uri") or ""),
    )


def source_from_context(source: Mapping[str, object]) -> SourceBindingSpec:
    """Build one immutable source binding from a retained helper context."""
    return SourceBindingSpec(
        alias=str(source.get("alias") or ""),
        source_name=str(source.get("source_name") or ""),
        table_name=str(source.get("table_name") or source.get("raw_table_name") or ""),
        table_uri=str(source.get("table_uri") or ""),
        model_name=str(source.get("model") or ""),
        filter_condition=str(source.get("filter") or ""),
        filter_mapping_resource_uri=str(source.get("filter_mapping_resource_uri") or ""),
        ref_model=str(source.get("ref_model") or ""),
    )


def join_from_context(join: Mapping[str, object]) -> JoinSpec:
    """Build one immutable join from a retained helper context."""
    return JoinSpec(
        join_type=str(join.get("type") or "left"),
        alias=str(join.get("alias") or ""),
        condition=str(join.get("condition") or ""),
        referenced_model=str(join.get("ref") or ""),
        fk_column=str(join.get("fk_column") or ""),
        source_alias=str(join.get("source_alias") or ""),
        source_column_uris=tuple(join.get("source_column_uris") or ()),
        target_columns=tuple(join.get("target_columns") or ()),
        relationship_uri=str(join.get("relationship_uri") or ""),
        temporal_mode=str(join.get("temporal_mode") or ""),
        as_of_column=str(join.get("as_of_column") or ""),
    )


def build_silver_model(
    *,
    identity: ModelIdentity,
    kind: SilverModelKind,
    columns: Iterable[Mapping[str, object]],
    sources: Iterable[Mapping[str, object]] = (),
    joins: Iterable[Mapping[str, object]] = (),
    materialization: str = "table",
    unique_key: str | Sequence[str] = (),
    where_clause: str = "",
    source_models: Iterable[str] = (),
    surrogate_key_expression: str = "",
    integration_key_expression: str = "",
    iri_expression: str = "",
    parent_model: str = "",
    source_identity_ref: str = "",
    source_record_key_expression: str = "",
    source_record_key_generated_after_mapping: bool = False,
    ontology_metadata: Mapping[str, object] | None = None,
) -> SilverModelSpec:
    """Construct the authoritative immutable Silver logical model."""
    unique_keys = (
        (unique_key,)
        if isinstance(unique_key, str) and unique_key
        else tuple(str(item) for item in unique_key)
    )
    return SilverModelSpec(
        identity=identity,
        kind=kind,
        columns=tuple(column_from_context(column) for column in columns),
        sources=tuple(source_from_context(source) for source in sources),
        joins=tuple(join_from_context(join) for join in joins),
        materialization_intent=MaterializationIntent(materialization, unique_keys),
        ontology_metadata=build_metadata(ontology_metadata),
        where_clause=where_clause,
        source_models=tuple(source_models),
        surrogate_key_expression=surrogate_key_expression,
        integration_key_expression=integration_key_expression,
        iri_expression=iri_expression,
        parent_model=parent_model,
        source_identity_ref=source_identity_ref,
        source_record_key_expression=source_record_key_expression,
        source_record_key_generated_after_mapping=source_record_key_generated_after_mapping,
    )


def outcome_from_context(context: Mapping[str, object]) -> SilverModelOutcome:
    """Build typed registry/report facts from the legacy private facade shape."""
    skipped = bool(context.get("skipped", False))
    reason_value = context.get("skip_reason")
    reason = str(reason_value) if reason_value is not None else None
    outcome = (
        ModelOutcome.FOLDED
        if skipped and reason and "discriminator subclass" in reason
        else ModelOutcome.SKIPPED
        if skipped
        else ModelOutcome.GENERATED
    )
    class_name = str(context.get("class_name") or "")
    model_name = str(context.get("model_name") or "")
    if not model_name and not skipped:
        model_file = str(context.get("model_file") or "")
        model_name = model_file.replace("\\", "/").rsplit("/", 1)[-1].removesuffix(".sql")
    if not model_name and not skipped:
        model_name = camel_to_snake(class_name)
    columns = context.get("column_names")
    column_names = (
        tuple(str(item) for item in columns)
        if isinstance(columns, Sequence) and not isinstance(columns, (str, bytes, bytearray))
        else ()
    )
    notes = context.get("info_notes")
    info_notes = (
        tuple(str(item) for item in notes)
        if isinstance(notes, Sequence) and not isinstance(notes, (str, bytes, bytearray))
        else ()
    )
    source_count = context.get("source_count")
    fk_join_count = context.get("fk_join_count")
    scd_value = context.get("scd_type")
    return SilverModelOutcome(
        identity=ModelIdentity(
            class_name=class_name,
            class_uri=str(context.get("class_uri") or ""),
            model_name=model_name,
            domain_name="",
            schema_name="",
            artifact_path=(
                str(context.get("model_file")) if context.get("model_file") is not None else None
            ),
            outcome=outcome,
            reason=reason,
        ),
        scd_type=str(scd_value) if scd_value is not None else None,
        source_count=int(source_count) if isinstance(source_count, int) else 0,
        column_names=column_names,
        fk_join_count=int(fk_join_count) if isinstance(fk_join_count, int) else 0,
        info_notes=info_notes,
        model_name_reported="model_name" in context,
        info_notes_reported="info_notes" in context,
    )


def outcome_context(outcome: SilverModelOutcome) -> dict[str, object]:
    """Adapt a typed outcome to the existing report/materialization facade."""
    context: dict[str, object] = {
        "class_name": outcome.identity.class_name,
        "class_uri": outcome.identity.class_uri,
        "model_file": outcome.identity.artifact_path,
        "scd_type": outcome.scd_type,
        "source_count": outcome.source_count,
        "column_count": len(outcome.column_names),
        "column_names": list(outcome.column_names),
        "fk_join_count": outcome.fk_join_count,
        "skipped": outcome.identity.outcome in {ModelOutcome.SKIPPED, ModelOutcome.FOLDED},
        "skip_reason": outcome.identity.reason,
    }
    if outcome.model_name_reported:
        context["model_name"] = outcome.identity.model_name
    if outcome.info_notes_reported:
        context["info_notes"] = list(outcome.info_notes)
    return context


def build_silver_registry(
    outcomes: Iterable[SilverModelOutcome],
    parent_relations: Iterable[tuple[str, str]],
    authorities: Iterable["SilverModelAuthoritySpec"] = (),
    *,
    ontology_version: str = "",
    materialized_models: Iterable[SilverModelSpec] = (),
) -> SilverRegistry:
    """Build deterministic immutable name/column registries from actual outcomes."""
    names: dict[str, str] = {}
    columns: dict[str, frozenset[str]] = {}
    for outcome in outcomes:
        identity = outcome.identity
        if identity.outcome in {ModelOutcome.SKIPPED, ModelOutcome.FOLDED}:
            continue
        if not identity.class_uri or not identity.model_name:
            continue
        names[identity.class_uri] = identity.model_name
        columns[identity.model_name] = frozenset(outcome.column_names)
    for model in materialized_models:
        identity = model.identity
        if (
            identity.outcome in {ModelOutcome.SKIPPED, ModelOutcome.FOLDED}
            or not identity.class_uri
            or not identity.model_name
            or (identity.class_uri in names and names[identity.class_uri] != identity.model_name)
        ):
            continue
        names[identity.class_uri] = identity.model_name
        columns[identity.model_name] = frozenset(column.name for column in model.columns)

    parent_children: dict[str, set[str]] = defaultdict(set)
    for child_uri, parent_uri in sorted(parent_relations):
        if child_uri in names and parent_uri not in names:
            parent_children[parent_uri].add(names[child_uri])

    ambiguous: list[tuple[str, tuple[str, ...]]] = []
    for parent_uri in sorted(parent_children):
        children = tuple(sorted(parent_children[parent_uri]))
        if len(children) == 1:
            names[parent_uri] = children[0]
        else:
            ambiguous.append((parent_uri, children))

    return SilverRegistry(
        names=tuple(sorted(names.items())),
        columns=tuple(sorted(columns.items())),
        versions=tuple((model_name, ontology_version) for model_name in sorted(columns)),
        ambiguous_parents=tuple(ambiguous),
        authorities=tuple(
            sorted(
                (
                    authority.identity.model_name,
                    authority,
                )
                for authority in authorities
                if authority.identity.model_name
            )
        ),
    )


def schema_model_from_context(context: Mapping[str, object]) -> SchemaModelSpec:
    """Build one immutable schema model from accumulated logical facts."""
    columns = context.get("columns")
    column_specs = (
        tuple(column_from_context(column) for column in columns if isinstance(column, Mapping))
        if isinstance(columns, Sequence) and not isinstance(columns, (str, bytes, bytearray))
        else ()
    )
    metadata = context.get("meta")
    metadata_items = (
        tuple((str(key), str(value)) for key, value in metadata.items())
        if isinstance(metadata, Mapping)
        else ()
    )

    def strings(key: str) -> tuple[str, ...]:
        value = context.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return tuple(str(item) for item in value)
        return ()

    return SchemaModelSpec(
        name=str(context.get("name") or ""),
        description=str(context.get("description") or ""),
        metadata=metadata_items,
        columns=column_specs,
        grain_columns=strings("grain_columns"),
        source_identity_columns=strings("source_identity_columns"),
        grain_where=str(context.get("grain_where") or ""),
        table_type=str(context.get("table_type") or ""),
        ontology_class=str(context.get("ontology_class") or ""),
        ontology_iri=str(context.get("ontology_iri") or ""),
        ontology_version=str(context.get("ontology_version") or ""),
    )
