# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""RDF/file binding helpers for the DD-106--DD-115 authored policy surface."""

from __future__ import annotations

from pathlib import Path

from rdflib import BNode, Graph, Namespace, URIRef
from rdflib.collection import Collection
from rdflib.namespace import RDF

from .policy_specs import (
    AdapterSupportFact,
    ArrayJsonFact,
    AuthoredValuesFact,
    CalendarFact,
    CdcMappingFact,
    CleanupRuleFact,
    DataQualityRuleFact,
    DeviationFact,
    DedupeOrderFact,
    EntityIdentityFact,
    GoldProductFact,
    GoldTablePolicyFact,
    HashPolicyFact,
    IncrementalPolicyFact,
    MeasureFact,
    MedallionPolicyFacts,
    MultiSourcePolicyFact,
    PhysicalRenameFact,
    PreparationPolicyFact,
    PreparedColumnFact,
    ScalarJsonFact,
    SecurityFact,
    SentinelRuleFact,
    SourceRecordKeyFact,
    TemporalRelationshipFact,
    TechnicalDedupeFact,
    TypeConversionFact,
)


EXT = Namespace("https://kairos.cnext.eu/ext#")
PREP = Namespace("https://kairos.cnext.eu/preparation#")


def _values(
    graph: Graph,
    subject: URIRef,
    predicate: URIRef,
    *,
    required_slot: bool = False,
) -> AuthoredValuesFact | None:
    values = tuple(sorted({str(value) for value in graph.objects(subject, predicate)}))
    if not values and not required_slot:
        return None
    return AuthoredValuesFact(
        resource_uri=str(subject),
        predicate_uri=str(predicate),
        values=values,
    )


def _required(graph: Graph, subject: URIRef, predicate: URIRef) -> AuthoredValuesFact:
    value = _values(graph, subject, predicate, required_slot=True)
    assert value is not None
    return value


def _ordered_required(
    graph: Graph,
    subject: URIRef,
    predicate: URIRef,
) -> AuthoredValuesFact:
    objects = tuple(graph.objects(subject, predicate))
    values: tuple[str, ...]
    ordered = False
    if objects and all(isinstance(value, BNode) for value in objects):
        collections = tuple(
            tuple(str(value) for value in Collection(graph, node))
            for node in objects
        )
        values = collections[0]
        ordered = all(value == values for value in collections)
    else:
        values = tuple(sorted({str(value) for value in objects}))
        ordered = False
    return AuthoredValuesFact(
        resource_uri=str(subject),
        predicate_uri=str(predicate),
        values=values,
        ordered=ordered,
    )


def _subjects_of_type(graph: Graph, class_uri: URIRef) -> tuple[URIRef, ...]:
    return tuple(
        URIRef(value)
        for value in sorted(
            {
                str(subject)
                for subject in graph.subjects(RDF.type, class_uri)
                if isinstance(subject, URIRef)
            }
        )
    )


def _linked(graph: Graph, subject: URIRef, predicate: URIRef) -> tuple[URIRef, ...]:
    return tuple(
        URIRef(value)
        for value in sorted(
            {
                str(resource)
                for resource in graph.objects(subject, predicate)
                if isinstance(resource, URIRef)
            }
        )
    )


def _prepared_column(graph: Graph, resource: URIRef) -> PreparedColumnFact:
    return PreparedColumnFact(
        resource_uri=str(resource),
        target_name=_required(graph, resource, PREP.targetColumnName),
        target_type=_required(graph, resource, PREP.targetType),
        json_path=_values(graph, resource, PREP.jsonPath),
    )


def _renames(graph: Graph, policy: URIRef) -> tuple[PhysicalRenameFact, ...]:
    return tuple(
        PhysicalRenameFact(
            resource_uri=str(resource),
            source_column=_required(graph, resource, PREP.sourceColumn),
            target_name=_required(graph, resource, PREP.targetColumnName),
        )
        for resource in _linked(graph, policy, PREP.physicalRename)
    )


def _cleanup_rules(graph: Graph, policy: URIRef) -> tuple[CleanupRuleFact, ...]:
    return tuple(
        CleanupRuleFact(
            resource_uri=str(resource),
            source_column=_required(graph, resource, PREP.sourceColumn),
            operation=_required(graph, resource, PREP.cleanupOperation),
            lossless=_required(graph, resource, PREP.lossless),
        )
        for resource in _linked(graph, policy, PREP.cleanupRule)
    )


def _type_conversions(graph: Graph, policy: URIRef) -> tuple[TypeConversionFact, ...]:
    return tuple(
        TypeConversionFact(
            resource_uri=str(resource),
            source_column=_required(graph, resource, PREP.sourceColumn),
            target_type=_required(graph, resource, PREP.targetType),
            parse_policy=_required(graph, resource, PREP.parsePolicy),
            error_policy=_required(graph, resource, PREP.errorPolicy),
        )
        for resource in _linked(graph, policy, PREP.typeConversion)
    )


def _sentinel_rules(graph: Graph, policy: URIRef) -> tuple[SentinelRuleFact, ...]:
    return tuple(
        SentinelRuleFact(
            resource_uri=str(resource),
            source_column=_required(graph, resource, PREP.sourceColumn),
            sentinel_value=_required(graph, resource, PREP.sentinelValue),
            action=_required(graph, resource, PREP.sentinelAction),
            normalized_value=_values(graph, resource, PREP.normalizedValue),
            evidence=_required(graph, resource, PREP.evidence),
        )
        for resource in _linked(graph, policy, PREP.sentinelNormalization)
    )


def _prepared_links(
    graph: Graph,
    resource: URIRef,
    predicate: URIRef,
) -> tuple[PreparedColumnFact, ...]:
    return tuple(_prepared_column(graph, item) for item in _linked(graph, resource, predicate))


def _cdc_mappings(graph: Graph, policy: URIRef) -> tuple[CdcMappingFact, ...]:
    return tuple(
        CdcMappingFact(
            resource_uri=str(resource),
            raw_operation_columns=_values(graph, resource, PREP.rawOperationColumn),
            raw_update_timestamp_columns=_values(
                graph, resource, PREP.rawUpdateTimestampColumn
            ),
            raw_effective_timestamp_columns=_values(
                graph, resource, PREP.rawEffectiveTimestampColumn
            ),
            raw_ingestion_timestamp_columns=_values(
                graph, resource, PREP.rawIngestionTimestampColumn
            ),
            raw_sequence_columns=_values(graph, resource, PREP.rawSequenceColumn),
            operation_code_map=_values(graph, resource, PREP.operationCodeMap),
            normalized_operation_fields=_prepared_links(
                graph, resource, PREP.normalizedOperationField
            ),
            normalized_update_timestamp_fields=_prepared_links(
                graph, resource, PREP.normalizedUpdateTimestampField
            ),
            normalized_effective_timestamp_fields=_prepared_links(
                graph, resource, PREP.normalizedEffectiveTimestampField
            ),
            normalized_ingestion_timestamp_fields=_prepared_links(
                graph, resource, PREP.normalizedIngestionTimestampField
            ),
            normalized_sequence_fields=_prepared_links(
                graph, resource, PREP.normalizedSequenceField
            ),
        )
        for resource in _linked(graph, policy, PREP.cdcMapping)
    )


def _record_keys(graph: Graph, policy: URIRef) -> tuple[SourceRecordKeyFact, ...]:
    return tuple(
        SourceRecordKeyFact(
            resource_uri=str(resource),
            source_scope=_required(graph, resource, PREP.sourceScope),
            table_scope=_required(graph, resource, PREP.tableScope),
            components=_required(graph, resource, PREP.recordKeyComponent),
            outputs=_prepared_links(graph, resource, PREP.recordKeyOutput),
        )
        for resource in _linked(graph, policy, PREP.recordKeyPolicy)
    )


def _scalar_json(graph: Graph, policy: URIRef) -> tuple[ScalarJsonFact, ...]:
    return tuple(
        ScalarJsonFact(
            resource_uri=str(resource),
            source_column=_required(graph, resource, PREP.sourceColumn),
            json_path=_required(graph, resource, PREP.jsonPath),
            extracted_columns=_prepared_links(graph, resource, PREP.extractedColumn),
            retention=_required(graph, resource, PREP.rawPayloadRetention),
            error_policy=_required(graph, resource, PREP.errorPolicy),
        )
        for resource in _linked(graph, policy, PREP.scalarJsonExtraction)
    )


def _array_json(graph: Graph, policy: URIRef) -> tuple[ArrayJsonFact, ...]:
    return tuple(
        ArrayJsonFact(
            resource_uri=str(resource),
            source_column=_required(graph, resource, PREP.sourceColumn),
            json_path=_required(graph, resource, PREP.jsonPath),
            child_relation_name=_required(graph, resource, PREP.childRelationName),
            parent_key_components=_required(graph, resource, PREP.parentKeyComponent),
            element_key_path=_values(graph, resource, PREP.elementKeyPath),
            element_index_field=_values(graph, resource, PREP.elementIndexField),
            null_policy=_required(graph, resource, PREP.nullArrayPolicy),
            empty_policy=_required(graph, resource, PREP.emptyArrayPolicy),
            retention=_required(graph, resource, PREP.rawPayloadRetention),
            extracted_columns=_prepared_links(graph, resource, PREP.extractedColumn),
        )
        for resource in _linked(graph, policy, PREP.arrayChildContract)
    )


def _technical_dedupes(
    graph: Graph,
    policy: URIRef,
) -> tuple[TechnicalDedupeFact, ...]:
    return tuple(
        TechnicalDedupeFact(
            resource_uri=str(resource),
            keys=_required(graph, resource, PREP.dedupeKeyColumn),
            order_terms=tuple(
                DedupeOrderFact(
                    resource_uri=str(term),
                    source_column=_required(graph, term, PREP.sourceColumn),
                    position=_required(graph, term, PREP.orderPosition),
                    direction=_required(graph, term, PREP.sortDirection),
                )
                for term in _linked(graph, resource, PREP.dedupeOrderTerm)
            ),
        )
        for resource in _linked(graph, policy, PREP.technicalDedupe)
    )


def _preparations(graph: Graph) -> tuple[PreparationPolicyFact, ...]:
    return tuple(
        PreparationPolicyFact(
            resource_uri=str(policy),
            source_table=_required(graph, policy, PREP.sourceTable),
            mode=_required(graph, policy, PREP.prepMode),
            schema_change_policy=_required(graph, policy, PREP.schemaChangePolicy),
            normalization_evidence=_values(graph, policy, PREP.normalizationEvidence),
            renames=_renames(graph, policy),
            cleanup_rules=_cleanup_rules(graph, policy),
            type_conversions=_type_conversions(graph, policy),
            sentinel_rules=_sentinel_rules(graph, policy),
            cdc=_cdc_mappings(graph, policy),
            record_keys=_record_keys(graph, policy),
            scalar_json=_scalar_json(graph, policy),
            array_json=_array_json(graph, policy),
            technical_dedupes=_technical_dedupes(graph, policy),
        )
        for policy in _subjects_of_type(graph, PREP.PreparationPolicy)
    )


_IDENTITY_PREDICATES = (
    EXT.businessGrain,
    EXT.identityStrategy,
    EXT.entityInstanceIriPolicy,
    EXT.keyScope,
    EXT.sourceIdentity,
    EXT.changeDetectionStrategy,
    EXT.lineagePolicy,
)


def _identity_subjects(graph: Graph) -> tuple[URIRef, ...]:
    return tuple(
        URIRef(value)
        for value in sorted(
            {
                str(subject)
                for predicate in _IDENTITY_PREDICATES
                for subject in graph.subjects(predicate, None)
                if isinstance(subject, URIRef)
            }
        )
    )


def _identities(
    graph: Graph,
    entity_uris: frozenset[str] | None = None,
) -> tuple[EntityIdentityFact, ...]:
    return tuple(
        EntityIdentityFact(
            resource_uri=str(resource),
            business_grain=_values(graph, resource, EXT.businessGrain),
            strategy=_values(graph, resource, EXT.identityStrategy),
            iri_policy=_values(graph, resource, EXT.entityInstanceIriPolicy),
            key_scope=_values(graph, resource, EXT.keyScope),
            source_identities=_values(graph, resource, EXT.sourceIdentity),
            natural_keys=_values(graph, resource, EXT.naturalKey),
            change_detection=_values(graph, resource, EXT.changeDetectionStrategy),
            lineage_policy=_values(graph, resource, EXT.lineagePolicy),
            contribution_lineage=_values(
                graph, resource, EXT.contributionLineagePolicy
            ),
            reconciliation_limitation=_values(
                graph, resource, EXT.reconciliationLimitation
            ),
            driving_source=_values(graph, resource, EXT.drivingSource),
            multi_source_policy_refs=_values(
                graph, resource, EXT.multiSourcePolicy
            ),
            scd_type=_values(graph, resource, EXT.scdType),
            scd2_time_basis=_values(graph, resource, EXT.scd2TimeBasis),
            hash_policy_refs=_values(graph, resource, EXT.hashPolicy),
            incremental_policy_refs=_values(graph, resource, EXT.incrementalPolicy),
        )
        for resource in _identity_subjects(graph)
        if entity_uris is None or str(resource) in entity_uris
    )


def _multi_source(graph: Graph) -> tuple[MultiSourcePolicyFact, ...]:
    return tuple(
        MultiSourcePolicyFact(
            resource_uri=str(resource),
            branch_relationship=_required(graph, resource, EXT.branchRelationship),
            normalization=_required(graph, resource, EXT.normalizationPolicy),
            source_precedence=_required(graph, resource, EXT.sourcePrecedence),
            conflict=_required(graph, resource, EXT.attributeConflictPolicy),
            collision=_required(graph, resource, EXT.keyCollisionPolicy),
            deletion=_required(graph, resource, EXT.branchDeletionPolicy),
            late_arrival=_required(graph, resource, EXT.branchLateArrivalPolicy),
            reconciliation_tests=_required(graph, resource, EXT.reconciliationTest),
        )
        for resource in _subjects_of_type(graph, EXT.MultiSourcePolicy)
    )


def _incremental(graph: Graph) -> tuple[IncrementalPolicyFact, ...]:
    return tuple(
        IncrementalPolicyFact(
            resource_uri=str(resource),
            merge_identity=_required(graph, resource, EXT.mergeIdentity),
            cdc_operation=_required(graph, resource, EXT.cdcOperation),
            source_updated_at=_required(graph, resource, EXT.sourceUpdateTimestamp),
            source_effective_at=_required(
                graph, resource, EXT.sourceEffectiveTimestamp
            ),
            ingested_at=_required(graph, resource, EXT.ingestionTimestamp),
            total_order=_required(graph, resource, EXT.totalOrderTieBreaker),
            lookback=_required(graph, resource, EXT.lookbackWindow),
            hard_delete=_required(graph, resource, EXT.hardDeletePolicy),
            soft_delete=_required(graph, resource, EXT.softDeletePolicy),
            late_arrival=_required(graph, resource, EXT.lateArrivalPolicy),
            correction=_required(graph, resource, EXT.correctionPolicy),
            replay=_required(graph, resource, EXT.replayPolicy),
            backfill=_required(graph, resource, EXT.backfillPolicy),
            schema_change=_required(graph, resource, EXT.schemaChangePolicy),
        )
        for resource in _subjects_of_type(graph, EXT.IncrementalPolicy)
    )


def _hashes(graph: Graph) -> tuple[HashPolicyFact, ...]:
    return tuple(
        HashPolicyFact(
            resource_uri=str(resource),
            version=_required(graph, resource, EXT.hashContractVersion),
            algorithm=_required(graph, resource, EXT.hashAlgorithm),
            inputs=_ordered_required(graph, resource, EXT.hashInput),
            null_representation=_required(
                graph, resource, EXT.hashNullRepresentation
            ),
        )
        for resource in _subjects_of_type(graph, EXT.HashPolicy)
    )


def _temporal_relationships(graph: Graph) -> tuple[TemporalRelationshipFact, ...]:
    resources = tuple(
        URIRef(value)
        for value in sorted(
            {
                str(subject)
                for subject in graph.subjects(EXT.silverForeignKeyTemporalMode, None)
                if isinstance(subject, URIRef)
            }
        )
    )
    return tuple(
        TemporalRelationshipFact(
            property_uri=str(resource),
            mode=_required(graph, resource, EXT.silverForeignKeyTemporalMode),
            as_of_column=_values(
                graph, resource, EXT.silverForeignKeyAsOfColumn
            ),
            interval=_values(graph, resource, EXT.silverForeignKeyInterval),
            time_zone=_values(graph, resource, EXT.silverForeignKeyTimeZone),
            precision=_values(graph, resource, EXT.silverForeignKeyPrecision),
            cardinality=_required(
                graph, resource, EXT.silverForeignKeyCardinality
            ),
            missing_action=_required(
                graph, resource, EXT.silverForeignKeyMissingPolicy
            ),
            ambiguous_action=_required(
                graph, resource, EXT.silverForeignKeyAmbiguousPolicy
            ),
            late_parent_action=_required(
                graph, resource, EXT.silverForeignKeyLateParentPolicy
            ),
            change_detection=_values(
                graph, resource, EXT.silverForeignKeyChangeDetection
            ),
        )
        for resource in resources
    )


def _data_quality(
    graph: Graph,
    entity_uris: frozenset[str] | None,
) -> tuple[DataQualityRuleFact, ...]:
    resources = _subjects_of_type(graph, EXT.DataQualityRule)
    if entity_uris is not None:
        resources = tuple(
            resource
            for resource in resources
            if any(
                str(owner) in entity_uris
                for owner in graph.subjects(EXT.dataQualityRule, resource)
            )
            or str(graph.value(resource, EXT.dqScope) or "") in entity_uris
        )
    return tuple(
        DataQualityRuleFact(
            resource_uri=str(resource),
            rule_id=_required(graph, resource, EXT.dqRuleId),
            version=_required(graph, resource, EXT.dqRuleVersion),
            category=_required(graph, resource, EXT.dqCategory),
            scope=_required(graph, resource, EXT.dqScope),
            check_kind=_required(graph, resource, EXT.dqCheckType),
            check_expression=_required(graph, resource, EXT.dqCheckExpression),
            severity=_required(graph, resource, EXT.dqSeverity),
            tolerance=_required(graph, resource, EXT.dqTolerance),
            action=_required(graph, resource, EXT.dqAction),
            owner_role=_required(graph, resource, EXT.dqOwnerRole),
            evidence=_required(graph, resource, EXT.dqEvidence),
            test_refs=_required(graph, resource, EXT.dqTestRef),
        )
        for resource in resources
    )


def _gold_tables(graph: Graph) -> tuple[GoldTablePolicyFact, ...]:
    resources = tuple(
        URIRef(value)
        for value in sorted(
            {
                str(subject)
                for subject in graph.subjects(EXT.goldTableType, None)
                if isinstance(subject, URIRef)
            }
        )
    )
    return tuple(
        GoldTablePolicyFact(
            resource_uri=str(resource),
            role=_required(graph, resource, EXT.goldTableType),
            table_name=_values(graph, resource, EXT.goldTableName),
            source_model=_values(graph, resource, EXT.goldSourceModel),
            source_version=_values(graph, resource, EXT.goldSourceVersion),
            fact_grain=_values(graph, resource, EXT.factGrain),
            fact_type=_values(graph, resource, EXT.factType),
            dimension_exposure=_values(graph, resource, EXT.dimensionExposure),
            version_binding=_values(
                graph, resource, EXT.dimensionVersionBinding
            ),
            incremental_policy_refs=_values(
                graph, resource, EXT.incrementalPolicy
            ),
            correction=_values(graph, resource, EXT.correctionPolicy),
            late_arrival=_values(graph, resource, EXT.lateArrivalPolicy),
            bridge_grain=_values(graph, resource, EXT.bridgeGrain),
            bridge_endpoints=_values(graph, resource, EXT.bridgeEndpoint),
            bridge_endpoint_bindings=_values(
                graph, resource, EXT.bridgeEndpointBinding
            ),
            bridge_cardinality=_values(graph, resource, EXT.bridgeCardinality),
            bridge_weight_column=_values(graph, resource, EXT.bridgeWeightColumn),
            bridge_allocation=_values(graph, resource, EXT.bridgeAllocationSemantics),
            perspectives=_values(graph, resource, EXT.perspective),
        )
        for resource in resources
    )


def _measures(graph: Graph) -> tuple[MeasureFact, ...]:
    return tuple(
        MeasureFact(
            resource_uri=str(resource),
            measure_id=_required(graph, resource, EXT.measureId),
            definition=_required(graph, resource, EXT.measureDefinition),
            expression=_values(graph, resource, EXT.measureExpression),
            column_dependencies=_values(
                graph, resource, EXT.measureColumnDependency
            ),
            measure_dependencies=_values(graph, resource, EXT.measureDependency),
            lifecycle=_required(graph, resource, EXT.measureLifecycleState),
            data_type=_values(graph, resource, EXT.measureDataType),
            format_string=_values(graph, resource, EXT.measureFormatString),
            folder=_values(graph, resource, EXT.measureFolder),
            owner_role=_values(graph, resource, EXT.measureOwnerRole),
            tests=_values(graph, resource, EXT.measureValidationTest),
            evidence=_values(graph, resource, EXT.measureValidationEvidence),
        )
        for resource in _subjects_of_type(graph, EXT.Measure)
    )


def _calendars(graph: Graph) -> tuple[CalendarFact, ...]:
    return tuple(
        CalendarFact(
            resource_uri=str(resource),
            start_date=_required(graph, resource, EXT.calendarStartDate),
            end_date=_required(graph, resource, EXT.calendarEndDate),
            fiscal_year_start_month=_required(
                graph, resource, EXT.fiscalYearStartMonth
            ),
            week_pattern=_required(graph, resource, EXT.weekPattern),
            locale=_required(graph, resource, EXT.calendarLocale),
            holiday_source=_required(graph, resource, EXT.holidaySource),
            time_zone=_required(graph, resource, EXT.calendarTimeZone),
            period_closure=_required(graph, resource, EXT.periodClosurePolicy),
            role_playing_dates=_required(graph, resource, EXT.rolePlayingDate),
            approval_status=_required(graph, resource, EXT.calendarApprovalStatus),
        )
        for resource in _subjects_of_type(graph, EXT.CalendarProfile)
    )


def _security(graph: Graph) -> tuple[SecurityFact, ...]:
    return tuple(
        SecurityFact(
            resource_uri=str(resource),
            entitlement_source=_required(graph, resource, EXT.entitlementSource),
            identity_mapping=_required(graph, resource, EXT.identityMapping),
            role_policies=_required(graph, resource, EXT.rolePolicy),
            filter_direction=_required(graph, resource, EXT.filterDirection),
            bindings=_required(graph, resource, EXT.securityBinding),
            positive_tests=_required(graph, resource, EXT.positiveSecurityTest),
            negative_tests=_required(graph, resource, EXT.negativeSecurityTest),
            test_evidence=_required(graph, resource, EXT.securityTestEvidence),
            fail_closed=_required(graph, resource, EXT.failClosed),
        )
        for resource in _subjects_of_type(graph, EXT.SecurityPolicy)
    )


def _adapter_support(
    graph: Graph,
    namespace: Namespace,
) -> tuple[AdapterSupportFact, ...]:
    return tuple(
        AdapterSupportFact(
            resource_uri=str(resource),
            adapter_name=_required(graph, resource, namespace.adapterName),
            adapter_version=_required(graph, resource, namespace.adapterVersion),
            scope=_required(graph, resource, namespace.evidenceScope),
            capabilities=_required(graph, resource, namespace.capability),
            status=_required(graph, resource, namespace.supportStatus),
            compile_evidence=_values(
                graph, resource, namespace.compileEvidence
            ),
        )
        for resource in _subjects_of_type(graph, namespace.AdapterSupport)
    )


def _deviations(
    graph: Graph,
    namespace: Namespace,
) -> tuple[DeviationFact, ...]:
    class_uri = namespace.Deviation if namespace == EXT else namespace.AdapterDeviation
    owner_predicate = (
        namespace.deviationOwnerRole if namespace == EXT else namespace.ownerRole
    )
    return tuple(
        DeviationFact(
            resource_uri=str(resource),
            adapter_name=_values(graph, resource, namespace.adapterName),
            policy_reference=_required(
                graph, resource, namespace.policyReference
            ),
            scope=_required(graph, resource, namespace.deviationScope),
            rationale=_required(
                graph, resource, namespace.deviationRationale
            ),
            owner_role=_required(graph, resource, owner_predicate),
            approval_status=_required(
                graph, resource, namespace.approvalStatus
            ),
            review_date=_required(graph, resource, namespace.reviewDate),
            expiry_date=_required(graph, resource, namespace.expiryDate),
            evidence=_required(graph, resource, namespace.deviationEvidence),
        )
        for resource in _subjects_of_type(graph, class_uri)
    )


def _load_prep(preparation_root: str | None) -> Graph:
    graph = Graph()
    if not preparation_root:
        return graph
    root = Path(preparation_root)
    if not root.is_dir():
        return graph
    for path in sorted(root.rglob("*.ttl")):
        graph.parse(path, format="turtle")
    return graph


def bind_policy_facts(
    graph: Graph,
    *,
    ontology_uri: str,
    preparation_root: str | None,
    gold_extension: str | None,
    entity_uris: frozenset[str] | None = None,
    dq_entity_uris: frozenset[str] | None = None,
) -> MedallionPolicyFacts:
    """Read v2 extension/prep authoring and emit graph-free immutable facts."""
    policy_graph = Graph()
    policy_graph += graph
    if gold_extension:
        path = Path(gold_extension)
        if path.is_file():
            policy_graph.parse(path, format="turtle")

    prep_graph = _load_prep(preparation_root)
    ontology = URIRef(ontology_uri)
    gold = GoldProductFact(
        ontology_uri=ontology_uri,
        profile=_values(policy_graph, ontology, EXT.goldProductProfile),
        schema=_values(policy_graph, ontology, EXT.goldSchema),
        measure_refs=_values(policy_graph, ontology, EXT.measure),
        calendar_refs=_values(policy_graph, ontology, EXT.calendarProfile),
        security_refs=_values(policy_graph, ontology, EXT.securityPolicy),
        tables=_gold_tables(policy_graph),
        measures=_measures(policy_graph),
        calendars=_calendars(policy_graph),
        security_policies=_security(policy_graph),
    )
    return MedallionPolicyFacts(
        ontology_uri=ontology_uri,
        naming_convention=_values(
            policy_graph, ontology, EXT.namingConvention
        ),
        preparations=_preparations(prep_graph),
        identities=_identities(policy_graph, entity_uris),
        multi_source=_multi_source(policy_graph),
        incremental=_incremental(policy_graph),
        hashes=_hashes(policy_graph),
        temporal_relationships=_temporal_relationships(policy_graph),
        data_quality=_data_quality(
            policy_graph,
            dq_entity_uris if dq_entity_uris is not None else entity_uris,
        ),
        gold=gold,
        adapter_support=(
            _adapter_support(policy_graph, EXT)
            + _adapter_support(prep_graph, PREP)
        ),
        deviations=_deviations(policy_graph, EXT) + _deviations(prep_graph, PREP),
    )
