# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""RDF/file binding helpers for retained Gold and runtime policy facts."""

from __future__ import annotations

from pathlib import Path

from rdflib import BNode, Graph, Namespace, URIRef
from rdflib.collection import Collection
from rdflib.namespace import RDF

from .policy_specs import (
    AdapterSupportFact,
    AuthoredValuesFact,
    CalendarFact,
    DataQualityRuleFact,
    DeviationFact,
    EntityIdentityFact,
    GoldProductFact,
    GoldTablePolicyFact,
    HashPolicyFact,
    IncrementalPolicyFact,
    MeasureFact,
    MedallionPolicyFacts,
    MultiSourcePolicyFact,
    SecurityFact,
    TemporalRelationshipFact,
)


EXT = Namespace("https://kairos.cnext.eu/ext#")


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


























_IDENTITY_PREDICATES = (
    EXT.businessGrain,
    EXT.identityStrategy,
    EXT.entityInstanceIriPolicy,
    EXT.keyScope,
    EXT.sourceIdentity,
    EXT.changeDetectionStrategy,
    EXT.lineagePolicy,
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
            incremental_policy_refs=None,
            correction=None,
            late_arrival=None,
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




def bind_policy_facts(
    graph: Graph,
    *,
    ontology_uri: str,
    gold_extension: str | None,
    entity_uris: frozenset[str] | None = None,
    dq_entity_uris: frozenset[str] | None = None,
) -> MedallionPolicyFacts:
    """Read retained extension authoring and emit graph-free immutable facts."""
    policy_graph = Graph()
    policy_graph += graph
    if gold_extension:
        path = Path(gold_extension)
        if path.is_file():
            policy_graph.parse(path, format="turtle")

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
        identities=(),
        multi_source=(),
        incremental=(),
        hashes=(),
        temporal_relationships=(),
        data_quality=(),
        gold=gold,
        adapter_support=_adapter_support(policy_graph, EXT),
        deviations=_deviations(policy_graph, EXT),
    )
