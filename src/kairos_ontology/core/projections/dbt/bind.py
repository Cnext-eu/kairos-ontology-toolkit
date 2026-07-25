# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The only RDF and authoring-input phase of the dbt pipeline (DD-110)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from rdflib import Graph, OWL, RDF, RDFS, URIRef

from ...ontology_loader import load_ontology
from .context import BoundSources
from .mapping_bind import bind_mapping_documents, mapping_context
from .mapping_specs import SourceMappings
from .specs import (
    BoundCoverage,
    BoundSchemaModel,
    BoundSilverModel,
    ClassBindingObservation,
    ClassFact,
    ContractFact,
    EntityCoverageSpec,
    EnumValueFact,
    JsonColumnFact,
    JsonFieldFact,
    SourceBindingsFact,
    SourceColumnFact,
    SourceCoverageSpec,
    SourceRefFact,
    SourceSystemFact,
    SourceTableFact,
)

if TYPE_CHECKING:  # pragma: no cover
    from .context import DbtInputs


class _CandidateEmission:
    """Raw eligibility gate used while extracting both bound and stub candidates."""

    def __init__(self, eligible: frozenset[str], enabled: bool) -> None:
        self._eligible = eligible
        self._enabled = enabled

    def should_emit_stub(self, class_uri: str) -> bool:
        return self._enabled and class_uri in self._eligible

    def is_release_blocking(self, class_uri: str) -> bool:
        return class_uri in self._eligible


def _classes_context(
    classes: tuple[ClassFact, ...],
) -> list[dict[str, str]]:
    return [
        {
            "uri": item.uri,
            "name": item.name,
            "label": item.label,
            "comment": item.comment,
        }
        for item in classes
    ]


def _contract_fact(contract) -> ContractFact:
    from ...dbt_contracts import APPROVED_DECISION_STATUSES

    decisions = tuple(contract.decisions)
    return ContractFact(
        name=contract.name,
        materialization=contract.materialization,
        target_class=contract.target_class,
        virtual_source_iri=contract.virtual_source_iri,
        supported_adapters=tuple(contract.supported_adapters),
        grain_key=tuple(contract.grain_key),
        replaces_source_iris=tuple(
            replacement.table_iri for replacement in contract.replaces_sources
        ),
        decision_statuses=tuple(
            sorted(decision.status for decision in decisions)
        ),
        evidence_artifacts=tuple(
            sorted(
                {
                    evidence.artifact
                    for decision in decisions
                    for evidence in decision.evidence
                }
            )
        ),
        verified_tests=tuple(
            sorted(
                {
                    test
                    for decision in decisions
                    for test in decision.verified_by
                }
            )
        ),
        approved=bool(decisions)
        and all(
            decision.status in APPROVED_DECISION_STATUSES
            and bool(decision.evidence)
            and bool(decision.verified_by)
            for decision in decisions
        ),
    )


def _freeze_systems(systems: list[dict]) -> tuple[SourceSystemFact, ...]:
    result: list[SourceSystemFact] = []
    for system in systems:
        tables: list[SourceTableFact] = []
        for table in system["tables"]:
            columns: list[SourceColumnFact] = []
            for column in table["columns"]:
                raw_json = column.get("json_info")
                json = (
                    JsonColumnFact(
                        content_type=str(raw_json.get("content_type") or ""),
                        json_path=str(raw_json.get("json_path") or ""),
                        fields=tuple(
                            JsonFieldFact(
                                name=str(field.get("name") or ""),
                                data_type=str(field.get("type") or ""),
                                path=str(field.get("path") or ""),
                                max_length=int(field.get("max_length") or 0),
                            )
                            for field in raw_json.get("fields", ())
                        ),
                    )
                    if raw_json
                    else None
                )
                columns.append(
                    SourceColumnFact(
                        uri=str(column["uri"]),
                        name=str(column["name"]),
                        data_type=str(column["data_type"]),
                        nullable=bool(column["nullable"]),
                        is_primary_key=bool(column["is_pk"]),
                        json=json,
                        enum_values=tuple(
                            EnumValueFact(
                                code=str(value.get("code") or ""),
                                label=str(value.get("label") or ""),
                            )
                            for value in (column.get("enum_values") or ())
                        ),
                        origin=str(column.get("origin") or "raw"),
                    )
                )
            tables.append(
                SourceTableFact(
                    uri=str(table["uri"]),
                    name=str(table["name"]),
                    label=str(table["label"]),
                    primary_key_columns=tuple(table.get("pk_columns") or ()),
                    incremental_column=table.get("incremental_column"),
                    columns=tuple(columns),
                    discriminator_column=table.get("discriminator_column"),
                    discriminator_values=tuple(
                        EnumValueFact(
                            code=str(value.get("code") or ""),
                            label=str(value.get("label") or ""),
                        )
                        for value in (table.get("discriminator_values") or ())
                    ),
                    relation_kind=str(table.get("relation_kind") or "physical"),
                    ref_model=str(table.get("ref_model") or ""),
                    parent_table_uri=str(table.get("parent_table_uri") or ""),
                )
            )
        result.append(
            SourceSystemFact(
                uri=str(system["system_uri"]),
                label=str(system["system_label"]),
                database=str(system["database"]),
                schema=str(system["schema"]),
                connection_type=str(system["connection_type"]),
                tables=tuple(tables),
            )
        )
    return tuple(result)


def _mapping_target_metadata(
    mappings: SourceMappings,
    graph,
) -> SourceMappings:
    from ..shared import KAIROS_EXT
    from ..uri_utils import camel_to_snake, extract_local_name
    from dataclasses import replace

    column_facts = tuple(
        replace(
            mapping,
            target_column_name=str(
                graph.value(
                    URIRef(mapping.target_property_uri),
                    KAIROS_EXT.silverColumnName,
                )
                or camel_to_snake(extract_local_name(mapping.target_property_uri))
            ),
            target_data_type=str(
                graph.value(
                    URIRef(mapping.target_property_uri),
                    KAIROS_EXT.silverDataType,
                )
                or graph.value(URIRef(mapping.target_property_uri), RDFS.range)
                or ""
            ),
            target_is_object_property=(
                URIRef(mapping.target_property_uri),
                RDF.type,
                OWL.ObjectProperty,
            )
            in graph,
            target_declared=any(
                graph.triples(
                    (
                        URIRef(mapping.target_property_uri),
                        RDF.type,
                        OWL.DatatypeProperty,
                    )
                )
            )
            or any(
                graph.triples(
                    (
                        URIRef(mapping.target_property_uri),
                        RDF.type,
                        OWL.ObjectProperty,
                    )
                )
            )
            or graph.value(
                URIRef(mapping.target_property_uri),
                RDFS.domain,
            )
            is not None
            or graph.value(
                URIRef(mapping.target_property_uri),
                RDFS.range,
            )
            is not None,
        )
        for mapping in mappings.columns
    )
    return SourceMappings(
        tables=mappings.tables,
        columns=column_facts,
        namespaces=mappings.namespaces,
    )


def _one(fact) -> str:
    """Return one unambiguous authored bind value without applying a default."""
    return fact.values[0] if fact is not None and len(fact.values) == 1 else ""


def _prepared_column_candidate(column, *, is_pk: bool = False) -> dict | None:
    name = _one(column.target_name)
    data_type = _one(column.target_type)
    if not name or not data_type:
        return None
    return {
        "uri": column.resource_uri,
        "name": name,
        "data_type": data_type,
        "nullable": not is_pk,
        "is_pk": is_pk,
        "json_info": None,
        "enum_values": None,
        "origin": "prepared",
    }


def _augment_prepared_relations(
    systems: list[dict],
    policy_facts,
) -> None:
    """Expose authored prep outputs to bind without normalizing their policy."""
    table_index = {
        table["uri"]: (system, table)
        for system in systems
        for table in system["tables"]
        if (table.get("relation_kind") or "physical") == "physical"
    }
    for policy in policy_facts.preparations:
        table_uri = _one(policy.source_table)
        indexed = table_index.get(table_uri)
        if indexed is None:
            continue
        system, table = indexed
        existing_columns = {column["uri"] for column in table["columns"]}

        prepared_outputs = [
            output
            for record_key in policy.record_keys
            for output in record_key.outputs
        ]
        for cdc in policy.cdc:
            prepared_outputs.extend(
                output
                for group in (
                    cdc.normalized_operation_fields,
                    cdc.normalized_update_timestamp_fields,
                    cdc.normalized_effective_timestamp_fields,
                    cdc.normalized_ingestion_timestamp_fields,
                    cdc.normalized_sequence_fields,
                )
                for output in group
            )
        prepared_outputs.extend(
            output
            for scalar in policy.scalar_json
            for output in scalar.extracted_columns
        )
        for output in prepared_outputs:
            candidate = _prepared_column_candidate(output)
            if candidate is not None and candidate["uri"] not in existing_columns:
                table["columns"].append(candidate)
                existing_columns.add(candidate["uri"])

        raw_by_uri = {column["uri"]: column for column in table["columns"]}
        record_key_output = next(
            (
                output
                for record_key in policy.record_keys
                for output in record_key.outputs
                if _one(output.target_name) == "_source_record_key"
            ),
            None,
        )
        for child in policy.array_json:
            relation_name = _one(child.child_relation_name)
            if not relation_name or any(
                candidate["uri"] == child.resource_uri
                for candidate in system["tables"]
            ):
                continue
            child_columns: list[dict] = []
            if record_key_output is not None:
                candidate = _prepared_column_candidate(record_key_output, is_pk=True)
                if candidate is not None:
                    child_columns.append(candidate)
            for parent_uri in (
                child.parent_key_components.values
                if child.parent_key_components is not None
                else ()
            ):
                raw = raw_by_uri.get(parent_uri)
                if raw is not None and all(
                    item["uri"] != raw["uri"] for item in child_columns
                ):
                    child_columns.append(
                        {
                            **raw,
                            "uri": f"{child.resource_uri}#parent-{raw['name']}",
                            "origin": "prepared",
                        }
                    )
            for output in child.extracted_columns:
                candidate = _prepared_column_candidate(output)
                if candidate is not None:
                    child_columns.append(candidate)
            element_index = _one(child.element_index_field)
            element_name = element_index or "_element_key"
            child_columns.append(
                {
                    "uri": f"{child.resource_uri}#{element_name}",
                    "name": element_name,
                    "data_type": "int64" if element_index else "string",
                    "nullable": False,
                    "is_pk": True,
                    "json_info": None,
                    "enum_values": None,
                    "origin": "prepared",
                }
            )
            system["tables"].append(
                {
                    "uri": child.resource_uri,
                    "name": relation_name,
                    "label": relation_name,
                    "pk_columns": ("_source_record_key", element_name),
                    "incremental_column": None,
                    "columns": child_columns,
                    "discriminator_column": None,
                    "discriminator_values": None,
                    "relation_kind": "prepared-child",
                    "ref_model": relation_name,
                    "parent_table_uri": table_uri,
                }
            )


def _source_ref(value: tuple[str, ...]) -> SourceRefFact:
    return SourceRefFact(
        source_name=value[0],
        table_name=value[1],
        table_uri=value[2],
        mapped_target_uri=value[3] if len(value) > 3 else None,
    )


def _freeze_bindings(bindings, contracts: dict[str, object]) -> SourceBindingsFact:
    contract_facts = {
        contract.name: _contract_fact(contract) for contract in contracts.values()
    }
    return SourceBindingsFact(
        active_contracts=tuple(
            sorted(
                (
                    class_uri,
                    contract_facts[contract.name],
                )
                for class_uri, contract in bindings.active_contracts.items()
            )
        ),
        virtual_table_uris=frozenset(bindings.virtual_table_uris),
        class_to_sources=tuple(
            (
                class_uri,
                tuple(_source_ref(ref) for ref in refs),
            )
            for class_uri, refs in sorted(bindings.class_to_sources.items())
        ),
        folded_source_targets=tuple(
            sorted(
                (
                    (_source_ref(ref), target)
                    for ref, target in bindings.folded_source_targets.items()
                ),
                key=lambda item: (
                    item[0].source_name,
                    item[0].table_name,
                    item[0].table_uri,
                    item[0].mapped_target_uri or "",
                    item[1],
                ),
            )
        ),
        warnings=tuple(bindings.warnings),
    )


def _freeze_coverage(domain_name: str, coverage: dict) -> BoundCoverage | None:
    if not coverage:
        return None
    entities: list[EntityCoverageSpec] = []
    for model_name, values in sorted(coverage.items()):
        source_coverage = tuple(
            SourceCoverageSpec(
                name=name,
                available_columns=int(source["available_columns"]),
                consumed_columns=int(source["consumed_columns"]),
                unused_columns=tuple(source["unused_columns"]),
            )
            for name, source in sorted(values["source_coverage"].items())
        )
        entities.append(
            EntityCoverageSpec(
                model_name=model_name,
                ontology_properties_total=int(values["ontology_properties_total"]),
                ontology_properties_required=int(values["ontology_properties_required"]),
                ontology_properties_optional=int(values["ontology_properties_optional"]),
                ontology_properties_derived=int(values["ontology_properties_derived"]),
                populated_from_source=int(values["populated_from_source"]),
                always_null=int(values["always_null"]),
                null_columns=tuple(values["null_columns"]),
                missing_required_mappings=tuple(values["missing_required_mappings"]),
                source_coverage=source_coverage,
            )
        )
    return BoundCoverage(domain_name=domain_name, entities=tuple(entities))


def _bound_silver_model(spec) -> BoundSilverModel:
    return BoundSilverModel(
        identity=spec.identity,
        kind=spec.kind,
        columns=spec.columns,
        sources=spec.sources,
        joins=spec.joins,
        requested_materialization=spec.materialization_intent,
        ontology_metadata=spec.ontology_metadata,
        where_clause=spec.where_clause,
        source_models=spec.source_models,
        surrogate_key_expression=spec.surrogate_key_expression,
        integration_key_expression=spec.integration_key_expression,
        iri_expression=spec.iri_expression,
        parent_model=spec.parent_model,
        source_identity_ref=spec.source_identity_ref,
        source_record_key_expression=spec.source_record_key_expression,
        source_record_key_generated_after_mapping=(
            spec.source_record_key_generated_after_mapping
        ),
    )


def _bound_schema_model(spec) -> BoundSchemaModel:
    return BoundSchemaModel(
        name=spec.name,
        description=spec.description,
        metadata=spec.metadata,
        columns=spec.columns,
        grain_columns=spec.grain_columns,
        source_identity_columns=spec.source_identity_columns,
        grain_where=spec.grain_where,
        table_type=spec.table_type,
        ontology_class=spec.ontology_class,
        ontology_iri=spec.ontology_iri,
        ontology_version=spec.ontology_version,
    )


def bind_sources(inputs: "DbtInputs") -> BoundSources:
    """Consume all authoring inputs and return immutable, graph-free facts."""
    from ...binding_analysis import is_discriminator_subclass
    from ..medallion_dbt_projector import (
        _extract_schema_model_facts,
        _extract_silver_model_facts,
        _parse_bronze,
        _validate_contract_boundaries,
        compute_source_bindings,
        generate_coverage_data,
    )
    from ..shared import (
        KAIROS_EXT,
        detect_ontology_uri,
        extract_foreign_key_facts,
        str_val,
    )
    from ..shared import merge_ext_graph
    from .builders import metadata_context, outcome_from_context
    from .policy_bind import bind_policy_facts

    ontology_uri = detect_ontology_uri(inputs.graph, inputs.namespace)
    ontology_metadata = replace(
        inputs.ontology_metadata,
        iri=inputs.ontology_metadata.iri or str(ontology_uri),
        version=(
            inputs.ontology_metadata.version
            or str(inputs.graph.value(ontology_uri, OWL.versionInfo) or "")
        ),
    )
    authoring_graph = Graph()
    authoring_graph += inputs.graph
    peer_ontologies = set(inputs.peer_ontologies)
    for peer_ontology in sorted(peer_ontologies):
        path = Path(peer_ontology)
        if path.is_file():
            authoring_graph += load_ontology(path).graph
    graph = merge_ext_graph(
        authoring_graph,
        Path(inputs.silver_extension) if inputs.silver_extension else None,
        fallback_paths=[Path(path) for path in inputs.ref_model_defaults],
        peer_ext_paths=[Path(path) for path in inputs.peer_extensions],
    )
    class_facts = list(inputs.classes)
    known_class_uris = {item.uri for item in class_facts}
    for resource in sorted(graph.subjects(RDF.type, OWL.Class), key=str):
        resource_uri = str(resource)
        if resource_uri in known_class_uris or not (
            graph.value(resource, KAIROS_EXT.identityStrategy)
            or graph.value(resource, KAIROS_EXT.silverTableName)
        ):
            continue
        local_name = resource_uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        class_facts.append(
            ClassFact(
                uri=resource_uri,
                name=local_name,
                label=str(graph.value(resource, RDFS.label) or local_name),
                comment=str(
                    graph.value(resource, RDFS.comment)
                    or f"{local_name} entity"
                ),
            )
        )
        known_class_uris.add(resource_uri)
    bound_classes = tuple(class_facts)
    classes = _classes_context(bound_classes)
    source_root = inputs.sources_root or inputs.bronze_root
    systems = _parse_bronze(Path(source_root) if source_root else None)
    mapping_facts = bind_mapping_documents(
        Path(inputs.mappings_root) if inputs.mappings_root else None
    )
    mappings, mapping_ns = mapping_context(mapping_facts)
    foreign_key_facts = extract_foreign_key_facts(graph)
    policy_entity_uris = {
        item.uri for item in bound_classes
    } | {
        class_uri
        for fact in foreign_key_facts
        for class_uri in (
            fact.domain_value,
            fact.range_value,
            fact.foreign_key_on,
        )
        if class_uri is not None
    }
    policy_facts = bind_policy_facts(
        graph,
        ontology_uri=str(ontology_uri),
        preparation_root=inputs.preparation_root,
        gold_extension=inputs.gold_extension,
        entity_uris=frozenset(policy_entity_uris),
        dq_entity_uris=frozenset(item.uri for item in bound_classes),
    )
    _augment_prepared_relations(systems, policy_facts)
    contracts = dict(inputs.contracts)
    virtual_contract_tables = {
        contract.virtual_source_iri for contract in contracts.values()
    }
    for system in systems:
        for table in system["tables"]:
            if table["uri"] in virtual_contract_tables:
                table["relation_kind"] = "contracted-virtual"
                table["ref_model"] = next(
                    contract.name
                    for contract in contracts.values()
                    if contract.virtual_source_iri == table["uri"]
                )
    _validate_contract_boundaries(
        contracts,
        classes,
        graph,
        systems,
        mappings,
        inputs.target_platform,
    )

    legacy_bindings = compute_source_bindings(
        classes=classes,
        graph=graph,
        systems=systems,
        mappings=mappings,
        contract_registry=contracts,
    )
    binding_observations = tuple(
        ClassBindingObservation(
            class_uri=item.uri,
            has_sources=bool(legacy_bindings.class_to_sources.get(item.uri)),
            discriminator_parent_name=(
                is_discriminator_subclass(graph, item.uri)[1]
                if not legacy_bindings.class_to_sources.get(item.uri)
                else None
            ),
            eligible=item.uri in inputs.eligible_class_uris,
        )
        for item in bound_classes
    )

    # The retained graph-dependent model extractor is confined to bind. Its output is
    # captured as immutable candidate facts; templates are not loaded or rendered.
    candidate_emission = _CandidateEmission(
        inputs.eligible_class_uris,
        inputs.emit_aspirational_stubs,
    )
    naming_convention = (
        str_val(graph, ontology_uri, KAIROS_EXT.namingConvention)
        or "camel-to-snake"
    )
    silver_specs, warnings, entity_metadata = _extract_silver_model_facts(
        classes,
        graph,
        inputs.namespace,
        systems,
        mappings,
        metadata_context(inputs.ontology_metadata),
        inputs.ontology_name,
        platform=inputs.target_platform,
        mapping_ns=mapping_ns,
        contract_registry=contracts,
        emit_aspirational_stubs=inputs.emit_aspirational_stubs,
        eligible_class_uris=set(inputs.eligible_class_uris),
        bindings=legacy_bindings,
        analysis=candidate_emission,
    )
    outcomes = tuple(outcome_from_context(item) for item in entity_metadata)
    generated_names = (
        {
            outcome.identity.class_name
            for outcome in outcomes
            if outcome.identity.outcome.value not in {"skipped", "folded"}
        }
        if systems
        else None
    )
    aspirational_names = {
        outcome.identity.class_name for outcome in outcomes if outcome.aspirational
    }
    schema_models = _extract_schema_model_facts(
        classes,
        graph,
        inputs.namespace,
        Path(inputs.shapes_root) if inputs.shapes_root else None,
        inputs.ontology_name,
        metadata_context(inputs.ontology_metadata),
        systems=systems,
        mappings=mappings,
        generated_class_names=generated_names,
        platform=inputs.target_platform,
        aspirational_class_names=aspirational_names,
        naming_conv=naming_convention,
    )

    coverage = (
        _freeze_coverage(
            inputs.ontology_name,
            generate_coverage_data(
                classes,
                graph,
                inputs.namespace,
                systems,
                mappings,
                inputs.ontology_name,
            ),
        )
        if systems
        else None
    )
    parent_relations = tuple(
        sorted(
            (item.uri, str(parent))
            for item in bound_classes
            for parent in graph.objects(URIRef(item.uri), RDFS.subClassOf)
            if isinstance(parent, URIRef)
            and not str(parent).startswith("http://www.w3.org/")
        )
    )
    macro_root = Path(inputs.template_root) / "macros"
    macro_names = tuple(
        path.name for path in sorted(macro_root.glob("*.sql"))
    ) if macro_root.is_dir() else ()
    contract_facts = tuple(
        sorted((name, _contract_fact(contract)) for name, contract in contracts.items())
    )
    virtual_table_uris = frozenset(
        contract.virtual_source_iri for contract in contracts.values()
    )
    class_uris = {item.uri for item in bound_classes}
    replacement_input_uris = frozenset(
        replacement.table_iri
        for contract in contracts.values()
        if contract.target_class in class_uris
        for replacement in contract.replaces_sources
    )

    return BoundSources(
        classes=bound_classes,
        namespace=inputs.namespace,
        ontology_name=inputs.ontology_name,
        ontology_metadata=ontology_metadata,
        target_platform=inputs.target_platform,
        template_root=inputs.template_root,
        logical_sources_only=inputs.logical_sources_only,
        emit_aspirational_stubs=inputs.emit_aspirational_stubs,
        systems=_freeze_systems(systems),
        mappings=_mapping_target_metadata(mapping_facts, graph),
        contracts=contract_facts,
        virtual_table_uris=virtual_table_uris,
        replacement_input_uris=replacement_input_uris,
        source_bindings=_freeze_bindings(legacy_bindings, contracts),
        binding_observations=binding_observations,
        foreign_key_facts=foreign_key_facts,
        ontology_uri=str(ontology_uri),
        parent_relations=parent_relations,
        silver_candidates=tuple(_bound_silver_model(spec) for spec in silver_specs),
        silver_outcomes=outcomes,
        schema_candidates=tuple(
            _bound_schema_model(spec) for spec in schema_models
        ),
        coverage=coverage,
        macro_names=macro_names,
        warnings=tuple(warnings),
        policy_facts=policy_facts,
    )
