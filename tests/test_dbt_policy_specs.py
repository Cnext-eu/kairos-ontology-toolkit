# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Gate 3c tests for immutable Medallion policy specs and adapter capabilities."""

from __future__ import annotations

import dataclasses
from enum import Enum
from pathlib import Path

import pytest
from rdflib import Graph

from kairos_ontology.core.projections.dbt import (
    ADAPTER_CAPABILITY_REGISTRY,
    AdapterCapability,
    AdapterName,
    CapabilityDisposition,
    PolicyNormalizationError,
    bind_sources,
    negotiate_capabilities,
    normalize_contract,
    plan_materialization,
    shape_project,
)
from kairos_ontology.core.projections.dbt.policy_bind import bind_policy_facts
from kairos_ontology.core.projections.dbt.policy_normalize import (
    normalize_medallion_policy,
)
from kairos_ontology.core.projections.dbt.policy_specs import (
    AuthoredValuesFact,
    CapabilityRequirementSpec,
    CanonicalHashPolicySpec,
    DataQualityRuleSpec,
    EntityIdentitySpec,
    GoldProductSpec,
    IncrementalPolicySpec,
    MedallionPolicySpec,
    MultiSourcePolicySpec,
    PolicySource,
    PreparationSpec,
    SilverModelAuthoritySpec,
    TemporalRelationshipSpec,
)
from kairos_ontology.core.projections.dbt.mapping_specs import (
    SourceMappings,
    TableMappingFact,
)
from kairos_ontology.core.projections.dbt.specs import (
    BoundSilverModel,
    ColumnSpec,
    ForeignKeyPolicy,
    ModelIdentity,
    ModelOutcome,
    SilverModelKind,
    SourceColumnFact,
    SourceSystemFact,
    SourceTableFact,
)


EXT_TTL = """
@prefix ex: <urn:test#> .
@prefix ext: <https://kairos.cnext.eu/ext#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<urn:test> a owl:Ontology ;
    ext:namingConvention "camel-to-snake" ;
    ext:goldSchema "gold_test" ;
    ext:goldProductProfile "dimensional-powerbi-v1" ;
    ext:measure ex:Revenue ;
    ext:calendarProfile ex:Calendar ;
    ext:securityPolicy ex:Security .

ex:Entity a owl:Class ;
    ext:businessGrain "one source event" ;
    ext:identityStrategy "business-key" ;
    ext:entityInstanceIriPolicy "emit" ;
    ext:keyScope "domain" ;
    ext:sourceIdentity ex:recordKey ;
    ext:naturalKey "businessId" ;
    ext:changeDetectionStrategy "canonical-hash" ;
    ext:lineagePolicy "source-record-and-load" ;
    ext:incrementalPolicy ex:Incremental ;
    ext:hashPolicy ex:Hash ;
    ext:scdType "2" ;
    ext:scd2TimeBasis "business-valid" ;
    ext:goldTableType "fact" ;
    ext:goldSourceModel "entity" ;
    ext:goldSourceVersion "1.0" ;
    ext:factGrain "one governed event" ;
    ext:factType "transaction" ;
    ext:dimensionVersionBinding "as-of-event-date" ;
    ext:perspective "Operations" ;
    ext:dataQualityRule ex:Quality .

ex:Sources a ext:MultiSourcePolicy ;
    ext:branchRelationship "overlapping" ;
    ext:normalizationPolicy "codes, units, currency, and time zones are explicit" ;
    ext:sourcePrecedence "none-without-approved-exact-equivalence" ;
    ext:attributeConflictPolicy "quarantine" ;
    ext:keyCollisionPolicy "retain-source-scoped-identities" ;
    ext:branchDeletionPolicy "retain-other-branches" ;
    ext:branchLateArrivalPolicy "reconcile-on-arrival" ;
    ext:reconciliationTest "branch-union-reconciliation" .

ex:Incremental a ext:IncrementalPolicy ;
    ext:mergeIdentity "_source_record_key" ;
    ext:cdcOperation "_cdc_operation" ;
    ext:sourceUpdateTimestamp "_source_updated_at" ;
    ext:sourceEffectiveTimestamp "_source_effective_at" ;
    ext:ingestionTimestamp "_ingested_at" ;
    ext:totalOrderTieBreaker "_source_record_key" ;
    ext:lookbackWindow "7 days" ;
    ext:hardDeletePolicy "tombstone" ;
    ext:softDeletePolicy "apply-operation" ;
    ext:lateArrivalPolicy "reconcile-with-lookback" ;
    ext:correctionPolicy "replace-by-total-order" ;
    ext:replayPolicy "idempotent-merge" ;
    ext:backfillPolicy "full-rebuild-approved" ;
    ext:schemaChangePolicy "fail" .

ex:Hash a ext:HashPolicy ;
    ext:hashContractVersion "1" ;
    ext:hashAlgorithm "SHA-256" ;
    ext:hashInput ( ex:businessId ) ;
    ext:hashNullRepresentation "typed-length-delimited-null" .

ex:parent a owl:ObjectProperty ;
    ext:silverForeignKeyTemporalMode "current" ;
    ext:silverForeignKeyChangeDetection false ;
    ext:silverForeignKeyCardinality "zero-or-one" ;
    ext:silverForeignKeyMissingPolicy "quarantine" ;
    ext:silverForeignKeyAmbiguousPolicy "fail" ;
    ext:silverForeignKeyLateParentPolicy "restate" .

ex:Quality a ext:DataQualityRule ;
    ext:dqRuleId "entity.business-id" ;
    ext:dqRuleVersion "1" ;
    ext:dqCategory "business" ;
    ext:dqScope ex:Entity ;
    ext:dqCheckType "cross-field" ;
    ext:dqCheckExpression "left=business_id;operator=ne;right=_source_record_key" ;
    ext:dqSeverity "error" ;
    ext:dqTolerance "0" ;
    ext:dqAction "quarantine" ;
    ext:dqOwnerRole "Domain Data Owner" ;
    ext:dqEvidence "approved identity policy" ;
    ext:dqTestRef "kairos.dq.cross-field.v1" .

ex:Revenue a ext:Measure ;
    ext:measureId "test.revenue" ;
    ext:measureDefinition "Governed revenue in the active filter context." ;
    ext:measureExpression "SUM([amount])" ;
    ext:measureColumnDependency ex:amount ;
    ext:measureLifecycleState "approved" ;
    ext:measureDataType "decimal" ;
    ext:measureFormatString "#,##0.00" ;
    ext:measureFolder "Finance" ;
    ext:measureOwnerRole "Finance Data Owner" ;
    ext:measureValidationTest "revenue-reconciliation" ;
    ext:measureValidationEvidence "dq-run:revenue-v1" .

ex:Calendar a ext:CalendarProfile ;
    ext:calendarStartDate "2020-01-01"^^xsd:date ;
    ext:calendarEndDate "2035-12-31"^^xsd:date ;
    ext:fiscalYearStartMonth 1 ;
    ext:weekPattern "iso-8601-monday" ;
    ext:calendarLocale "en-US" ;
    ext:holidaySource "none-approved" ;
    ext:calendarTimeZone "UTC" ;
    ext:periodClosurePolicy "approved-period-status" ;
    ext:rolePlayingDate "EventDate=Entity.event_date" ;
    ext:calendarApprovalStatus "approved" .

ex:Security a ext:SecurityPolicy ;
    ext:entitlementSource "governed-entitlements" ;
    ext:identityMapping "model-user-to-entitlement-subject" ;
    ext:rolePolicy "Reader" ;
    ext:filterDirection "entitlement-to-product" ;
    ext:securityBinding "Entity.business_id=Reader:RLS" ;
    ext:positiveSecurityTest "allowed-reader" ;
    ext:negativeSecurityTest "denied-reader" ;
    ext:securityTestEvidence "security-run:reader-v1" ;
    ext:failClosed true .

ex:FabricEvidence a ext:AdapterSupport ;
    ext:adapterName "fabric" ;
    ext:adapterVersion "1.0" ;
    ext:evidenceScope "project" ;
    ext:capability "canonical-types" ;
    ext:supportStatus "supported" ;
    ext:compileEvidence "compile:test-fabric" .

ex:ConstraintDeviation a ext:Deviation ;
    ext:adapterName "fabric" ;
    ext:policyReference "DD-110-constraints" ;
    ext:deviationScope "silver" ;
    ext:deviationRationale "Constraint is emitted as documented non-enforced metadata." ;
    ext:deviationOwnerRole "Platform Owner" ;
    ext:approvalStatus "approved" ;
    ext:reviewDate "2027-01-01"^^xsd:date ;
    ext:expiryDate "2028-01-01"^^xsd:date ;
    ext:deviationEvidence "review:constraint-deviation" .
"""


PREP_TTL = """
@prefix ex: <urn:test#> .
@prefix prep: <https://kairos.cnext.eu/preparation#> .

ex:Policy a prep:PreparationPolicy ;
    prep:sourceTable ex:table ;
    prep:prepMode "normalize" ;
    prep:schemaChangePolicy "fail" ;
    prep:normalizationEvidence "profile:test-table" ;
    prep:physicalRename ex:Rename ;
    prep:cleanupRule ex:Trim ;
    prep:typeConversion ex:Cast ;
    prep:sentinelNormalization ex:Sentinel ;
    prep:cdcMapping ex:Cdc ;
    prep:recordKeyPolicy ex:recordKey ;
    prep:scalarJsonExtraction ex:ScalarJson ;
    prep:arrayChildContract ex:ArrayJson .

ex:Rename a prep:PhysicalRename ;
    prep:sourceColumn ex:column ;
    prep:targetColumnName "business_id" .
ex:Trim a prep:CleanupRule ;
    prep:sourceColumn ex:column ;
    prep:cleanupOperation "trim" ;
    prep:lossless true .
ex:Cast a prep:TypeConversion ;
    prep:sourceColumn ex:column ;
    prep:targetType "string" ;
    prep:parsePolicy "strict-text" ;
    prep:errorPolicy "fail" .
ex:Sentinel a prep:SentinelNormalization ;
    prep:sourceColumn ex:column ;
    prep:sentinelValue "UNKNOWN" ;
    prep:sentinelAction "to-null" ;
    prep:evidence "profile:test-table" .
ex:Cdc a prep:CdcMapping ;
    prep:rawOperationColumn ex:column ;
    prep:rawUpdateTimestampColumn ex:column ;
    prep:rawEffectiveTimestampColumn ex:column ;
    prep:rawIngestionTimestampColumn ex:column ;
    prep:rawSequenceColumn ex:column ;
    prep:operationCodeMap "I=insert" ;
    prep:normalizedOperationField ex:operation ;
    prep:normalizedUpdateTimestampField ex:updatedAt ;
    prep:normalizedEffectiveTimestampField ex:effectiveAt ;
    prep:normalizedIngestionTimestampField ex:ingestedAt ;
    prep:normalizedSequenceField ex:sequence .
ex:recordKey a prep:RecordKeyPolicy ;
    prep:sourceScope "test-source" ;
    prep:tableScope "test-table" ;
    prep:recordKeyComponent ex:column ;
    prep:recordKeyOutput ex:keyOutput .
ex:ScalarJson a prep:ScalarJsonExtraction ;
    prep:sourceColumn ex:column ;
    prep:jsonPath "$.value" ;
    prep:extractedColumn ex:scalarOutput ;
    prep:rawPayloadRetention "retain-payload" ;
    prep:errorPolicy "quarantine" .
ex:ArrayJson a prep:ArrayChildContract ;
    prep:sourceColumn ex:column ;
    prep:jsonPath "$.items" ;
    prep:childRelationName "stg_test__items" ;
    prep:parentKeyComponent ex:column ;
    prep:elementIndexField "_element_index" ;
    prep:nullArrayPolicy "zero-children" ;
    prep:emptyArrayPolicy "zero-children" ;
    prep:rawPayloadRetention "retain-replayable-reference" ;
    prep:extractedColumn ex:arrayOutput .

ex:keyOutput a prep:PreparedColumn ;
    prep:targetColumnName "_source_record_key" ;
    prep:targetType "string" .
ex:updatedAt a prep:PreparedColumn ;
    prep:targetColumnName "_source_updated_at" ;
    prep:targetType "timestamp" .
ex:effectiveAt a prep:PreparedColumn ;
    prep:targetColumnName "_source_effective_at" ;
    prep:targetType "timestamp" .
ex:ingestedAt a prep:PreparedColumn ;
    prep:targetColumnName "_ingested_at" ;
    prep:targetType "timestamp" .
ex:operation a prep:PreparedColumn ;
    prep:targetColumnName "_cdc_operation" ;
    prep:targetType "string" .
ex:sequence a prep:PreparedColumn ;
    prep:targetColumnName "_cdc_sequence" ;
    prep:targetType "int64" .
ex:scalarOutput a prep:PreparedColumn ;
    prep:targetColumnName "json_value" ;
    prep:targetType "string" ;
    prep:jsonPath "$.value" .
ex:arrayOutput a prep:PreparedColumn ;
    prep:targetColumnName "item_value" ;
    prep:targetType "decimal(18,2)" ;
    prep:jsonPath "$.amount" .
"""


def _source_facts() -> tuple[SourceSystemFact, ...]:
    return (
        SourceSystemFact(
            uri="urn:test#system",
            label="Test Source",
            database="test",
            schema="raw",
            connection_type="lakehouse",
            tables=(
                SourceTableFact(
                    uri="urn:test#table",
                    name="test_table",
                    label="Test table",
                    primary_key_columns=("business_id",),
                    incremental_column="updated_at",
                    columns=(
                        SourceColumnFact(
                            uri="urn:test#column",
                            name="business_id",
                            data_type="string",
                            nullable=False,
                            is_primary_key=True,
                        ),
                    ),
                ),
            ),
        ),
    )


def _silver_candidate() -> BoundSilverModel:
    return BoundSilverModel(
        identity=ModelIdentity(
            class_name="Entity",
            class_uri="urn:test#Entity",
            model_name="entity",
            domain_name="test",
            schema_name="silver_test",
            artifact_path="models/silver/test/entity.sql",
            outcome=ModelOutcome.GENERATED,
        ),
        kind=SilverModelKind.ENTITY,
        columns=(
            ColumnSpec("entity_sk", data_type="BIGINT"),
            ColumnSpec("business_id", data_type="STRING"),
            ColumnSpec("_source_system", data_type="STRING"),
            ColumnSpec("_source_record_key", data_type="STRING"),
            ColumnSpec("_source_identity_ref", data_type="STRING"),
            ColumnSpec("_loaded_at", data_type="TIMESTAMP"),
        ),
    )


def _bound_and_normalized(tmp_path: Path):
    prep = tmp_path / "test-prep.ttl"
    prep.write_text(PREP_TTL, encoding="utf-8")
    graph = Graph().parse(data=EXT_TTL, format="turtle")
    facts = bind_policy_facts(
        graph,
        ontology_uri="urn:test",
        preparation_root=str(tmp_path),
        gold_extension=None,
        entity_uris=frozenset({"urn:test#Entity"}),
    )
    mappings = SourceMappings(
        tables=(
            TableMappingFact(
                "urn:test#mapping",
                "urn:test#table",
                "urn:test#Entity",
                "direct",
                "exactMatch",
            ),
        ),
        columns=(),
    )
    policy = normalize_medallion_policy(
        facts,
        systems=_source_facts(),
        mappings=mappings,
        silver_candidates=(_silver_candidate(),),
        fk_policy=ForeignKeyPolicy((), (), ()),
    )
    return facts, policy, mappings


def _assert_immutable(value: object) -> None:
    assert not isinstance(value, (list, dict, set, bytearray, bytes, Graph, Path))
    if dataclasses.is_dataclass(value):
        assert value.__dataclass_params__.frozen
        assert "__slots__" in type(value).__dict__
        for field in dataclasses.fields(value):
            _assert_immutable(getattr(value, field.name))
    elif isinstance(value, (tuple, frozenset)):
        for item in value:
            _assert_immutable(item)
    else:
        assert value is None or isinstance(value, (str, int, float, bool, Enum))


@pytest.mark.parametrize(
    "record_type",
    [
        PreparationSpec,
        EntityIdentitySpec,
        MultiSourcePolicySpec,
        IncrementalPolicySpec,
        CanonicalHashPolicySpec,
        TemporalRelationshipSpec,
        DataQualityRuleSpec,
        SilverModelAuthoritySpec,
        GoldProductSpec,
        MedallionPolicySpec,
    ],
)
def test_every_policy_spec_family_is_frozen_and_slotted(record_type):
    assert dataclasses.is_dataclass(record_type)
    assert record_type.__dataclass_params__.frozen
    assert "__slots__" in record_type.__dict__


def test_rdf_facts_normalize_all_policy_families(tmp_path: Path):
    facts, policy, _ = _bound_and_normalized(tmp_path)

    assert facts.preparations and facts.identities and facts.gold.measures
    assert policy.preparations[0].array_children
    assert policy.preparations[0].scalar_json
    assert policy.preparations[0].cdc is not None
    assert policy.identities[0].source.may_fallback_to_business_key is False
    assert policy.multi_source[0].exact_equivalence.approved is False
    assert policy.incremental[0].ordering.tie_breakers.value
    assert policy.hashes[0].algorithm.value == "SHA-256"
    assert policy.temporal_relationships[0].ambiguous_action.value.value == "fail"
    assert policy.data_quality[0].effect.quarantines_rows
    assert policy.silver_models[0].audit.source_record_key_column == "_source_record_key"
    runtime_columns = {
        item.column.name: item.role.value.value
        for item in policy.silver_models[0].columns
    }
    assert runtime_columns["_business_valid_from"] == "history"
    assert runtime_columns["_business_valid_to"] == "history"
    assert runtime_columns["_system_from"] == "history"
    assert runtime_columns["_system_to"] == "history"
    assert runtime_columns["is_current"] == "history"
    assert runtime_columns["_is_deleted"] == "history"
    assert runtime_columns["_row_hash"] == "history"
    assert policy.silver_models[0].deviation_refs == ("urn:test#ConstraintDeviation",)
    assert policy.gold.profile is not None
    assert policy.gold.measures[0].lifecycle.value.value == "approved"
    assert policy.gold.calendar is not None and policy.gold.calendar.approved
    assert policy.gold.security is not None and policy.gold.security.fail_closed.value
    assert policy.gold.perspectives[0].is_security_boundary is False
    assert policy.adapter_evidence[0].compile_evidence.value == (
        "compile:test-fabric",
    )
    assert policy.dq_runtime_result.schema_version == "1.0"
    _assert_immutable(facts)
    _assert_immutable(policy)


def test_default_and_override_provenance_are_retained(tmp_path: Path):
    facts, policy, mappings = _bound_and_normalized(tmp_path)
    assert policy.naming_convention.provenance.source is PolicySource.OVERRIDE
    assert policy.naming_convention.provenance.rule_id == "DD-106-naming"
    assert policy.target_adapter.provenance.source is PolicySource.DEFAULT

    defaulted = normalize_medallion_policy(
        dataclasses.replace(facts, naming_convention=None),
        systems=_source_facts(),
        mappings=mappings,
        silver_candidates=(_silver_candidate(),),
        fk_policy=ForeignKeyPolicy((), (), ()),
    )
    assert defaulted.naming_convention.provenance.source is PolicySource.DEFAULT
    assert defaulted.naming_convention.provenance.rule_id == "DD-106-naming"


def test_passthrough_with_operations_is_rejected_actionably(tmp_path: Path):
    facts, _, mappings = _bound_and_normalized(tmp_path)
    prep = facts.preparations[0]
    contradictory_mode = AuthoredValuesFact(
        prep.mode.resource_uri,
        prep.mode.predicate_uri,
        ("passthrough",),
    )
    contradictory = dataclasses.replace(
        facts,
        preparations=(
            dataclasses.replace(prep, mode=contradictory_mode),
        ),
    )
    with pytest.raises(
        PolicyNormalizationError,
        match="prep.passthrough-blocked.*DD-106-prep-passthrough",
    ) as caught:
        normalize_medallion_policy(
            contradictory,
            systems=_source_facts(),
            mappings=mappings,
            silver_candidates=(_silver_candidate(),),
            fk_policy=ForeignKeyPolicy((), (), ()),
        )
    assert caught.value.code == "prep.passthrough-blocked"
    assert caught.value.diagnostic.code == caught.value.code
    assert caught.value.diagnostic.rule_id == caught.value.rule_id
    assert caught.value.diagnostic.resource_uri == caught.value.resource_uri
    assert caught.value.diagnostic.predicate_uri == caught.value.predicate_uri


def test_unsupported_and_contradictory_values_never_fall_back(tmp_path: Path):
    facts, _, mappings = _bound_and_normalized(tmp_path)
    identity = facts.identities[0]
    invalid = dataclasses.replace(
        identity,
        strategy=AuthoredValuesFact(
            identity.strategy.resource_uri,
            identity.strategy.predicate_uri,
            ("fuzzy-match",),
        ),
    )
    with pytest.raises(
        PolicyNormalizationError,
        match="policy.unsupported-value.*identity strategy",
    ):
        normalize_medallion_policy(
            dataclasses.replace(facts, identities=(invalid,)),
            systems=_source_facts(),
            mappings=mappings,
            silver_candidates=(_silver_candidate(),),
            fk_policy=ForeignKeyPolicy((), (), ()),
        )

    conflicting = dataclasses.replace(
        identity,
        strategy=AuthoredValuesFact(
            identity.strategy.resource_uri,
            identity.strategy.predicate_uri,
            ("business-key", "surrogate-only"),
        ),
    )
    with pytest.raises(
        PolicyNormalizationError,
        match="policy.contradictory-values",
    ):
        normalize_medallion_policy(
            dataclasses.replace(facts, identities=(conflicting,)),
            systems=_source_facts(),
            mappings=mappings,
            silver_candidates=(_silver_candidate(),),
            fk_policy=ForeignKeyPolicy((), (), ()),
        )


def test_capability_registry_is_complete_and_both_adapters_negotiate(tmp_path: Path):
    _, policy, _ = _bound_and_normalized(tmp_path)
    for adapter in AdapterName:
        record = ADAPTER_CAPABILITY_REGISTRY.adapter(adapter)
        assert {item.capability for item in record.capabilities} == set(AdapterCapability)
        assert {item.semantic_type for item in record.type_mappings}

    fabric = negotiate_capabilities(
        AdapterName.FABRIC,
        policy.capability_requirements,
        policy.deviations,
    )
    assert all(result.rule_id and result.evidence for result in fabric)
    constraint = next(
        item for item in fabric if item.capability is AdapterCapability.CONSTRAINTS
    )
    assert constraint.disposition is CapabilityDisposition.DEVIATION

    databricks = negotiate_capabilities(
        AdapterName.DATABRICKS,
        policy.capability_requirements,
        policy.deviations,
    )
    assert any(
        item.disposition is CapabilityDisposition.BLOCKING for item in databricks
    )


def test_unknown_adapter_and_unapproved_deviation_fail_closed():
    requirement = CapabilityRequirementSpec(
        AdapterCapability.CONSTRAINTS,
        "silver",
        "DD-110-constraints",
    )
    with pytest.raises(ValueError, match="Unsupported adapter"):
        negotiate_capabilities("warehouse-x", (requirement,))

    for adapter in AdapterName:
        result = negotiate_capabilities(adapter, (requirement,))
        assert result[0].disposition is CapabilityDisposition.BLOCKING
        assert result[0].rule_id == "DD-110-constraints"
        assert result[0].evidence


def test_mdm_boundary_is_routing_only(tmp_path: Path):
    _, policy, _ = _bound_and_normalized(tmp_path)
    assert policy.mdm_routing == ()
    assert not hasattr(policy.multi_source[0], "survivorship")
    assert not hasattr(policy.multi_source[0], "match_threshold")


def test_authoritative_policy_is_carried_through_every_phase():
    from tests.test_dbt_phases import _client_inputs

    bound = bind_sources(_client_inputs())
    contract = normalize_contract(bound)
    shaped = shape_project(contract)
    plan = plan_materialization(contract, shaped)

    assert contract.project.policy is contract.policy
    assert contract.policy.target_adapter.provenance.source is PolicySource.OVERRIDE
    assert shaped.policy is contract.policy
    assert plan.policy is contract.policy
    assert plan.release.policy_version == contract.policy.version
    assert plan.adapter.capability_results == plan.release.capability_results
    assert all(model.authority is not None for model in shaped.silver_models)
    for value in (bound, contract, shaped, plan):
        _assert_immutable(value)
