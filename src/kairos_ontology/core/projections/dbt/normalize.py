# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Pure effective-policy classification for bound dbt facts (DD-110)."""

from __future__ import annotations

from dataclasses import replace

from .context import BoundSources, NormalizedProjectFacts, ProjectionContract
from .diagnostics import ExecutionMode
from .mapping_normalize import normalize_mapping_contract
from .mapping_specs import MappingContractError, MappingContractSpec
from .specs import (
    BindingPolicy,
    ForeignKeyDescriptorSpec,
    ForeignKeyDiagnosticSpec,
    ForeignKeyPolicy,
    NormalizedCoverage,
    NormalizedSchemaModel,
    NormalizedSilverModel,
)
from .policy_specs import (
    CanonicalTypeKind,
    CanonicalTypeSpec,
    PolicySource,
    SilverColumnRole,
)


def _binding_policy(bound: BoundSources) -> BindingPolicy:
    states: list[tuple[str, str]] = []
    reasons: list[tuple[str, str]] = []
    for observation in bound.binding_observations:
        if observation.has_sources:
            state = "bound"
            reason = "bound to bronze source(s)"
        elif observation.discriminator_parent_name:
            state = "folded"
            reason = f"S3 discriminator subclass of {observation.discriminator_parent_name}"
        else:
            state = "skipped"
            reason = "no source binding"
        states.append((observation.class_uri, state))
        reasons.append((observation.class_uri, reason))
    return BindingPolicy(
        states=tuple(states),
        reasons=tuple(reasons),
    )


def _foreign_key_policy(bound: BoundSources) -> ForeignKeyPolicy:
    from ..shared import normalize_foreign_key_facts

    classification = normalize_foreign_key_facts(bound.foreign_key_facts)

    parents_by_child: dict[str, set[str]] = {}
    for child_uri, parent_uri in bound.parent_relations:
        parents_by_child.setdefault(child_uri, set()).add(parent_uri)

    def inherits_from(class_uri: str, roots: set[str]) -> bool:
        frontier = [class_uri]
        visited: set[str] = set()
        while frontier:
            current = frontier.pop()
            if current in roots:
                return True
            if current in visited:
                continue
            visited.add(current)
            frontier.extend(parents_by_child.get(current, ()))
        return False

    folded_parent_by_child: dict[str, str] = {}
    for observation in bound.binding_observations:
        if not observation.discriminator_parent_name:
            continue
        for parent_uri in parents_by_child.get(observation.class_uri, ()):
            parent_name = parent_uri.rstrip("#/").rsplit("#", 1)[-1].rsplit("/", 1)[-1]
            if parent_name == observation.discriminator_parent_name:
                folded_parent_by_child[observation.class_uri] = parent_uri
                break

    return ForeignKeyPolicy(
        descriptors=tuple(
            ForeignKeyDescriptorSpec(
                property_uri=str(item.property_uri),
                domain_class=str(item.domain_class),
                range_class=str(item.range_class),
                source_class=str(item.source_class),
                target_class=str(item.target_class),
                is_functional=item.is_functional,
                max_cardinality_classes=frozenset(str(uri) for uri in item.max_cardinality_classes),
                silver_foreign_key=item.silver_foreign_key,
                silver_column_name=item.silver_column_name,
                redirected=item.redirected,
                reverse=item.reverse,
                junction_table_name=item.junction_table_name,
                nullable=item.nullable,
                conditional_on_type=item.conditional_on_type,
                silver_applicable_classes=frozenset(
                    {
                        applicable_uri
                        for class_fact in bound.classes
                        if inherits_from(
                            class_fact.uri,
                            (
                                {str(item.source_class)}
                                if (
                                    item.redirected
                                    or item.silver_foreign_key
                                    or item.silver_column_name is not None
                                    or item.is_functional
                                )
                                else {str(uri) for uri in item.max_cardinality_classes}
                            ),
                        )
                        for applicable_uri in (
                            class_fact.uri,
                            folded_parent_by_child.get(class_fact.uri),
                        )
                        if applicable_uri
                    }
                ),
            )
            for item in classification.descriptors
        ),
        diagnostics=tuple(
            ForeignKeyDiagnosticSpec(
                kind=item.kind,
                property_uri=str(item.property_uri),
                message=item.message,
            )
            for item in classification.diagnostics
        ),
        outgoing_relationship_sources=tuple(
            str(uri) for uri in classification.outgoing_relationship_sources
        ),
    )


def normalize_contract(
    bound: BoundSources,
    mode: ExecutionMode = ExecutionMode.FAIL_FAST,
) -> ProjectionContract:
    """Classify effective policy without RDF, files, or templates."""
    from .policy_normalize import _target_type, normalize_medallion_policy

    binding_policy = _binding_policy(bound)
    foreign_key_policy = _foreign_key_policy(bound)
    from .diagnostics import EvaluationResult, EvaluationStatus
    from .policy_normalize import PolicyCollectionError

    collection_error = None
    try:
        policy = normalize_medallion_policy(
            bound.policy_facts,
            systems=bound.systems,
            mappings=bound.mappings,
            silver_candidates=bound.silver_candidates,
            fk_policy=foreign_key_policy,
            target_adapter=bound.target_platform,
            target_source=PolicySource.OVERRIDE,
            mode=mode,
            contracts=bound.contracts,
        )
    except PolicyCollectionError as exc:
        if mode is ExecutionMode.FAIL_FAST or exc.partial_value is None:
            raise
        collection_error = exc
        policy = exc.partial_value
    try:
        mapping_contract = normalize_mapping_contract(
            bound.mappings,
            systems=bound.systems,
            policy=policy,
            contracts=bound.contracts,
            replacement_input_uris=bound.replacement_input_uris,
        )
        mapping_result = EvaluationResult(
            status=EvaluationStatus.PASSED,
            value=mapping_contract,
        )
    except MappingContractError as exc:
        if mode is ExecutionMode.FAIL_FAST:
            raise
        mapping_result = EvaluationResult(
            status=EvaluationStatus.FAILED,
            diagnostics=(exc.diagnostic,),
        )
        mapping_contract = MappingContractSpec((), (), bound.mappings.namespaces, ())
    if collection_error is not None or mapping_result.status is EvaluationStatus.FAILED:
        if collection_error is None:
            from .policy_normalize import PolicyNormalizationStages

            stages = PolicyNormalizationStages(
                preparation=EvaluationResult(status=EvaluationStatus.PASSED),
                identity=EvaluationResult(status=EvaluationStatus.PASSED),
                runtime=EvaluationResult(status=EvaluationStatus.PASSED),
                foreign_keys=EvaluationResult(status=EvaluationStatus.PASSED),
                mapping=mapping_result,
            )
        else:
            stages = replace(collection_error.stages, mapping=mapping_result)
        raise PolicyCollectionError(stages)
    mapping_inputs = {
        item.source_column_uri: item
        for mapping in mapping_contract.columns
        for item in mapping.expression.metadata.referenced_inputs
    }
    authorities = {item.identity.class_uri: item for item in policy.silver_models}
    mapped_types: dict[str, set[CanonicalTypeSpec]] = {}
    mapped_properties: dict[str, set[str]] = {}
    for mapping in mapping_contract.columns:
        mapped_types.setdefault(mapping.target_column_name, set()).add(mapping.target_data_type)
        mapped_properties.setdefault(mapping.target_column_name, set()).add(
            mapping.target_property_uri
        )

    def inferred_type(column, authority) -> CanonicalTypeSpec | None:
        if column.mapping_expression is not None:
            return column.mapping_expression.metadata.output_type
        declared = _target_type(column.data_type)
        if declared is not None:
            return declared
        candidates = mapped_types.get(column.name, set())
        if len(candidates) == 1:
            return next(iter(candidates))
        if len(candidates) > 1:
            raise MappingContractError(
                "mapping.ambiguous-silver-type",
                (f"Silver column {column.name!r} has conflicting canonical mapping types"),
                resource_uri=authority.identity.class_uri if authority else "",
                rule_id="DD-110-silver-authority",
            )
        timestamp_names = (
            {timestamp.column_name for timestamp in authority.audit.columns}
            if authority is not None
            else set()
        )
        runtime = authority.runtime if authority is not None else None
        if runtime is not None:
            timestamp_names.update(
                {
                    runtime.incremental.ordering.source_updated_at.value,
                    runtime.incremental.ordering.source_effective_at.value,
                    runtime.incremental.ordering.ingested_at.value,
                    runtime.history.business_valid_from_column,
                    runtime.history.business_valid_to_column,
                    runtime.history.system_from_column,
                    runtime.history.system_to_column,
                }
            )
        if column.name in timestamp_names or column.name.endswith("_at"):
            return CanonicalTypeSpec(CanonicalTypeKind.TIMESTAMP)
        if column.name in {
            "_is_deleted",
            "_is_current",
            "is_current",
        }:
            return CanonicalTypeSpec(CanonicalTypeKind.BOOLEAN)
        if column.name.startswith("_kairos_fk_match_count_"):
            return CanonicalTypeSpec(CanonicalTypeKind.INT64)
        if column.name.endswith(("_sk", "_iri", "_integration_key", "_label")):
            return CanonicalTypeSpec(CanonicalTypeKind.STRING)
        if column.name in {
            "_source_system",
            "_source_identity_ref",
            "_source_record_key",
            "_cdc_operation",
            "_row_hash",
        }:
            return CanonicalTypeSpec(CanonicalTypeKind.STRING)
        if column.name.startswith("_cdc_sequence"):
            return CanonicalTypeSpec(CanonicalTypeKind.INT64)
        if column.expression.startswith("'") or "VARCHAR" in column.expression.upper():
            return CanonicalTypeSpec(CanonicalTypeKind.STRING)
        return None

    def normalized_column(column, authority):
        mapping = None
        if column.mapping_resource_uri:
            mapping = mapping_contract.column(column.mapping_resource_uri)
            if mapping is None:
                raise MappingContractError(
                    "mapping.unresolved-model-expression",
                    "Silver column references an unknown normalized mapping contract",
                    resource_uri=column.mapping_resource_uri,
                    rule_id="DD-107-phase-contract",
                )
            column = replace(column, mapping_expression=mapping.expression)
        authority_column = (
            next(
                (item for item in authority.columns if item.column.name == column.name),
                None,
            )
            if authority is not None
            else None
        )
        canonical_type = inferred_type(column, authority)
        nullable = (
            mapping.expression.metadata.nullable
            if mapping is not None
            else (
                authority_column.nullable.value if authority_column is not None else column.nullable
            )
        )
        role = (
            authority_column.role.value.value
            if authority_column is not None
            else SilverColumnRole.BUSINESS.value
        )
        provenance = set(column.provenance)
        if mapping is not None:
            provenance.update(
                {
                    f"mapping:{mapping.resource_uri}",
                    f"property:{mapping.target_property_uri}",
                    "rule:DD-107",
                }
            )
        else:
            provenance.update(
                f"property:{value}" for value in mapped_properties.get(column.name, ())
            )
        return replace(
            column,
            canonical_type=canonical_type,
            nullable=nullable,
            role=role,
            provenance=tuple(sorted(provenance)),
        )

    def normalized_source(source):
        if not source.filter_mapping_resource_uri:
            return source
        mapping = mapping_contract.table(source.filter_mapping_resource_uri)
        if mapping is None or mapping.row_filter is None:
            raise MappingContractError(
                "mapping.unresolved-model-filter",
                "Silver source references an unknown normalized rowFilter contract",
                resource_uri=source.filter_mapping_resource_uri,
                rule_id="DD-107-phase-contract",
            )
        return replace(source, filter_expression=mapping.row_filter)

    def normalized_join(join):
        if not join.source_column_uris:
            return join
        try:
            inputs = tuple(mapping_inputs[uri] for uri in join.source_column_uris)
        except KeyError as exc:
            raise MappingContractError(
                "mapping.unresolved-join-input",
                "Silver FK join references a source symbol absent from normalized mappings",
                resource_uri=str(exc.args[0]),
                rule_id="DD-107-source-ownership",
            ) from exc
        return replace(join, source_inputs=inputs)

    table_context = {
        table.uri: (system.label, table) for system in bound.systems for table in system.tables
    }
    source_ref_by_table: dict[tuple[str, str], str] = {}
    for class_uri, authority in authorities.items():
        identity = authority.entity_identity
        if identity is None:
            continue
        table_uris = tuple(
            dict.fromkeys(
                source.table_uri
                for candidate in bound.silver_candidates
                if candidate.identity.class_uri == class_uri
                for source in candidate.sources
            )
        )
        source_ref_by_table.update(
            {
                (class_uri, table_uri): source_ref
                for table_uri, source_ref in zip(
                    table_uris,
                    identity.source.record_key_refs.value,
                    strict=False,
                )
            }
        )

    def source_identity(candidate) -> tuple[str, str]:
        if candidate.source_identity_ref or not candidate.sources:
            return candidate.source_identity_ref, candidate.source_record_key_expression
        source = candidate.sources[0]
        identity_ref = source_ref_by_table.get(
            (candidate.identity.class_uri, source.table_uri),
            "",
        )
        context = table_context.get(source.table_uri)
        if context is None:
            return identity_ref, ""
        system_label, table = context
        components = tuple(column.name for column in table.columns if column.is_primary_key)
        if not components:
            return identity_ref, ""
        arguments = (
            f"'{system_label}'",
            f"'{table.name}'",
            *(f"{source.alias}.{name}" for name in components),
        )
        expression = (
            "{{ dbt_utils.generate_surrogate_key(["
            + ", ".join(repr(argument) for argument in arguments)
            + "]) }}"
        )
        return identity_ref, expression

    return ProjectionContract(
        fk_classification=foreign_key_policy,
        binding_policy=binding_policy,
        ontology_uri=bound.ontology_uri,
        policy=policy,
        mapping_contract=mapping_contract,
        project=NormalizedProjectFacts(
            classes=bound.classes,
            ontology_name=bound.ontology_name,
            ontology_metadata=bound.ontology_metadata,
            template_root=bound.template_root,
            logical_sources_only=bound.logical_sources_only,
            has_sources=bound.has_sources,
            systems=bound.systems,
            mappings=mapping_contract,
            contracts=tuple(name for name, _ in bound.contracts),
            virtual_table_uris=bound.virtual_table_uris,
            replacement_input_uris=bound.replacement_input_uris,
            parent_relations=bound.parent_relations,
            silver_models=tuple(
                NormalizedSilverModel(
                    identity=candidate.identity,
                    kind=candidate.kind,
                    columns=tuple(
                        normalized_column(
                            column,
                            authorities.get(candidate.identity.class_uri),
                        )
                        for column in candidate.columns
                    ),
                    sources=tuple(normalized_source(source) for source in candidate.sources),
                    joins=tuple(normalized_join(join) for join in candidate.joins),
                    materialization_intent=candidate.requested_materialization,
                    ontology_metadata=candidate.ontology_metadata,
                    where_clause=candidate.where_clause,
                    source_models=candidate.source_models,
                    surrogate_key_expression=candidate.surrogate_key_expression,
                    integration_key_expression=candidate.integration_key_expression,
                    iri_expression=candidate.iri_expression,
                    parent_model=candidate.parent_model,
                    source_identity_ref=source_identity(candidate)[0],
                    source_record_key_expression=source_identity(candidate)[1],
                    source_record_key_generated_after_mapping=(
                        candidate.source_record_key_generated_after_mapping
                        or bool(source_identity(candidate)[1])
                    ),
                    authority=authorities.get(candidate.identity.class_uri),
                )
                for candidate in bound.silver_candidates
            ),
            silver_outcomes=bound.silver_outcomes,
            schema_models=tuple(
                NormalizedSchemaModel(
                    name=model.name,
                    description=model.description,
                    metadata=model.metadata,
                    columns=model.columns,
                    grain_columns=model.grain_columns,
                    source_identity_columns=model.source_identity_columns,
                    grain_where=model.grain_where,
                    table_type=model.table_type,
                    ontology_class=model.ontology_class,
                    ontology_iri=model.ontology_iri,
                    ontology_version=model.ontology_version,
                )
                for model in bound.schema_candidates
            ),
            coverage=(
                NormalizedCoverage(
                    domain_name=bound.coverage.domain_name,
                    entities=bound.coverage.entities,
                )
                if bound.coverage is not None
                else None
            ),
            macro_names=bound.macro_names,
            warnings=bound.warnings,
            policy=policy,
            active_source_scope=bound.active_source_scope,
        ),
    )
