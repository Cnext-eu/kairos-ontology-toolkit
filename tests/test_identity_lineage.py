# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""DD-108 identity, lineage, conformance, and MDM-boundary tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from kairos_ontology.core.projections.dbt.policy_normalize import (
    PolicyNormalizationError,
    normalize_medallion_policy,
)
from kairos_ontology.core.projections.dbt.policy_specs import (
    AuthoredValuesFact,
    IdentityStrategy,
    KeyScope,
    SilverColumnRole,
    TimestampOrigin,
    TimestampRole,
)
from kairos_ontology.core.projections.dbt.shape import _apply_identity_contract
from kairos_ontology.core.projections.dbt.specs import (
    ColumnSpec,
    ForeignKeyPolicy,
    SilverModelKind,
    SilverModelSpec,
    SourceBindingSpec,
)
from tests.test_dbt_policy_specs import (
    _bound_and_normalized,
    _silver_candidate,
    _source_facts,
)


EXT = "https://kairos.cnext.eu/ext#"
RECORD_KEY = "urn:test#recordKey"
ARRAY_KEY = "urn:test#ArrayJson"


def _authored(
    identity,
    predicate: str,
    *values: str,
) -> AuthoredValuesFact:
    return AuthoredValuesFact(
        identity.resource_uri,
        f"{EXT}{predicate}",
        tuple(values),
    )


def _values(fact: AuthoredValuesFact, *values: str) -> AuthoredValuesFact:
    return replace(fact, values=tuple(values))


def _normalize(facts, mappings, identity, *, candidate=None):
    return normalize_medallion_policy(
        replace(facts, identities=(identity,)),
        systems=_source_facts(),
        mappings=mappings,
        silver_candidates=(candidate or _silver_candidate(),),
        fk_policy=ForeignKeyPolicy((), (), ()),
    )


def _exact_equivalence_policy(tmp_path):
    facts, _, mappings = _bound_and_normalized(tmp_path)
    identity = facts.identities[0]
    multi = facts.multi_source[0]
    exact_multi = replace(
        multi,
        branch_relationship=_values(
            multi.branch_relationship,
            "exactly-equivalent",
        ),
        source_precedence=_values(
            multi.source_precedence,
            f"declared-order:{RECORD_KEY},{ARRAY_KEY}",
        ),
        collision=_values(multi.collision, "quarantine"),
    )
    exact_identity = replace(
        identity,
        strategy=_values(
            identity.strategy,
            IdentityStrategy.DETERMINISTIC_INTEGRATION_KEY.value,
        ),
        source_identities=_values(identity.source_identities, RECORD_KEY, ARRAY_KEY),
        driving_source=_authored(identity, "drivingSource", RECORD_KEY),
        multi_source_policy_refs=_authored(
            identity,
            "multiSourcePolicy",
            exact_multi.resource_uri,
        ),
    )
    exact_facts = replace(
        facts,
        identities=(exact_identity,),
        multi_source=(exact_multi,),
    )
    return (
        normalize_medallion_policy(
            exact_facts,
            systems=_source_facts(),
            mappings=mappings,
            silver_candidates=(_silver_candidate(),),
            fk_policy=ForeignKeyPolicy((), (), ()),
        ),
        exact_facts,
        mappings,
    )


def _logical_model(policy) -> SilverModelSpec:
    candidate = _silver_candidate()
    columns = (
        ColumnSpec("entity_sk"),
        ColumnSpec("entity_iri"),
        ColumnSpec("business_id", expression="src.business_id"),
        ColumnSpec("_source_system", expression="'test-source'"),
        ColumnSpec("_source_record_key", expression="src._source_record_key"),
        ColumnSpec("_loaded_at", expression="{{ kairos_current_timestamp() }}"),
    )
    return SilverModelSpec(
        identity=candidate.identity,
        kind=SilverModelKind.ENTITY,
        columns=columns,
        sources=(
            SourceBindingSpec(
                alias="src",
                source_name="test-source",
                table_name="test-table",
                table_uri="urn:test#table",
            ),
        ),
        authority=policy.silver_models[0],
    )


def test_all_identity_strategies_normalize_without_inventing_roles(tmp_path):
    facts, _, mappings = _bound_and_normalized(tmp_path)
    business = facts.identities[0]
    policies = {
        IdentityStrategy.BUSINESS_KEY: _normalize(
            facts,
            mappings,
            business,
        ),
        IdentityStrategy.SOURCE_SCOPED_IMMUTABLE_KEY: _normalize(
            facts,
            mappings,
            replace(
                business,
                strategy=_values(
                    business.strategy,
                    IdentityStrategy.SOURCE_SCOPED_IMMUTABLE_KEY.value,
                ),
                key_scope=_values(business.key_scope, KeyScope.SOURCE_TABLE.value),
            ),
        ),
        IdentityStrategy.EXTERNALLY_MASTERED_IDENTIFIER: _normalize(
            facts,
            mappings,
            replace(
                business,
                strategy=_values(
                    business.strategy,
                    IdentityStrategy.EXTERNALLY_MASTERED_IDENTIFIER.value,
                ),
                key_scope=_values(business.key_scope, KeyScope.ENTERPRISE.value),
            ),
        ),
    }
    surrogate = replace(
        business,
        strategy=_values(
            business.strategy,
            IdentityStrategy.SURROGATE_ONLY.value,
        ),
        key_scope=_values(business.key_scope, KeyScope.SOURCE_TABLE.value),
        natural_keys=None,
        reconciliation_limitation=_authored(
            business,
            "reconciliationLimitation",
            "No stable business identifier exists; reconcile manually by source record.",
        ),
    )
    policies[IdentityStrategy.SURROGATE_ONLY] = _normalize(
        facts,
        mappings,
        surrogate,
    )
    policies[IdentityStrategy.DETERMINISTIC_INTEGRATION_KEY] = (
        _exact_equivalence_policy(tmp_path)[0]
    )

    expected_roles = {
        SilverColumnRole.BUSINESS_NATURAL_KEY,
        SilverColumnRole.SOURCE_IDENTITY,
        SilverColumnRole.INTEGRATION_IDENTITY,
        SilverColumnRole.MASTERED_IDENTIFIER,
        SilverColumnRole.SURROGATE_JOIN_KEY,
        SilverColumnRole.ENTITY_IRI,
    }
    for strategy, policy in policies.items():
        identity = policy.identities[0]
        authority = policy.silver_models[0]
        assert identity.strategy.value is strategy
        assert {
            role.role for role in authority.identity_roles
        } == expected_roles
        authority_columns = {item.column.name for item in authority.columns}
        assert all(
            set(role.columns) <= authority_columns
            for role in authority.identity_roles
            if role.emitted
        )
        assert {
            timestamp.column_name
            for timestamp in authority.audit.columns
            if timestamp.supplied
        } <= authority_columns
        assert identity.source.may_fallback_to_business_key is False
        assert identity.surrogate.establishes_business_identity is False

    assert policies[
        IdentityStrategy.BUSINESS_KEY
    ].identities[0].business.authoritative
    assert policies[
        IdentityStrategy.DETERMINISTIC_INTEGRATION_KEY
    ].identities[0].integration.emitted
    mastered = policies[IdentityStrategy.EXTERNALLY_MASTERED_IDENTIFIER]
    assert mastered.identities[0].mastered.routed_to_mdm
    assert mastered.mdm_routing[0].survivorship_owner == "kairos-mdm-runtime"
    assert policies[
        IdentityStrategy.SURROGATE_ONLY
    ].identities[0].surrogate.reconciliation_limitation is not None


def test_strategy_controls_physical_key_and_iri_independently(tmp_path):
    facts, _, mappings = _bound_and_normalized(tmp_path)
    business = facts.identities[0]
    business_policy = _normalize(facts, mappings, business)
    source_policy = _normalize(
        facts,
        mappings,
        replace(
            business,
            strategy=_values(
                business.strategy,
                IdentityStrategy.SOURCE_SCOPED_IMMUTABLE_KEY.value,
            ),
            key_scope=_values(business.key_scope, KeyScope.SOURCE_TABLE.value),
        ),
    )
    mastered_policy = _normalize(
        facts,
        mappings,
        replace(
            business,
            strategy=_values(
                business.strategy,
                IdentityStrategy.EXTERNALLY_MASTERED_IDENTIFIER.value,
            ),
            key_scope=_values(business.key_scope, KeyScope.ENTERPRISE.value),
        ),
    )
    exact_policy, _, _ = _exact_equivalence_policy(tmp_path)

    business_model = _apply_identity_contract(
        _logical_model(business_policy),
        source_identity_ref=RECORD_KEY,
        platform="fabric",
    )
    source_model = _apply_identity_contract(
        _logical_model(source_policy),
        source_identity_ref=RECORD_KEY,
        platform="fabric",
    )
    mastered_model = _apply_identity_contract(
        _logical_model(mastered_policy),
        source_identity_ref=RECORD_KEY,
        platform="fabric",
    )
    exact_model = _apply_identity_contract(
        _logical_model(exact_policy),
        source_identity_ref=RECORD_KEY,
        platform="fabric",
    )

    assert "business_id" in business_model.surrogate_key_expression
    assert "_source_record_key" in source_model.surrogate_key_expression
    assert "_source_record_key" in mastered_model.surrogate_key_expression
    assert mastered_model.integration_key_expression == ""
    assert "business_id" in exact_model.integration_key_expression
    assert "business_id" in exact_model.surrogate_key_expression
    assert business_model.iri_expression
    assert business_model.iri_expression != business_model.surrogate_key_expression

    omitted = _normalize(
        facts,
        mappings,
        replace(
            business,
            iri_policy=_values(business.iri_policy, "omit"),
        ),
    )
    omitted_model = _apply_identity_contract(
        _logical_model(omitted),
        source_identity_ref=RECORD_KEY,
        platform="fabric",
    )
    assert omitted_model.iri_expression == ""
    assert all(column.name != "entity_iri" for column in omitted_model.columns)


@pytest.mark.parametrize(
    ("case", "error_code"),
    [
        ("business-key-without-natural-key", "identity.business-key-missing"),
        ("duplicate-natural-key", "identity.duplicate-key-component"),
        ("source-key-domain-scope", "identity.source-scoped-key-scope"),
        ("integration-without-exact-equivalence", "identity.integration-key-without"),
        ("integration-without-components", "identity.integration-key-components-missing"),
        ("mastered-with-domain-scope", "identity.mastered-key-scope"),
        ("mastered-without-identifier", "identity.mastered-identifier-missing"),
        ("surrogate-with-natural-key", "identity.surrogate-only-forbids"),
        ("surrogate-without-limitation", "identity.surrogate-limitation-missing"),
        ("surrogate-with-domain-scope", "identity.surrogate-only-key-scope"),
        ("business-with-limitation", "identity.unexpected-reconciliation"),
        ("missing-iri-policy", "identity.missing-iri-policy"),
        ("single-with-driving-source", "identity.unexpected-driving-source"),
        ("single-with-multi-policy", "identity.unexpected-multi-source-policy"),
        ("multi-without-driving-source", "identity.driving-source-missing"),
        ("multi-with-unknown-driving-source", "identity.unknown-driving-source"),
        ("unknown-source-identity", "identity.unknown-source-identity"),
        ("duplicate-source-identity", "identity.duplicate-source-identity"),
    ],
)
def test_invalid_strategy_field_combinations_fail_closed(
    tmp_path,
    case: str,
    error_code: str,
):
    facts, _, mappings = _bound_and_normalized(tmp_path)
    identity = facts.identities[0]
    if case == "business-key-without-natural-key":
        identity = replace(identity, natural_keys=None)
    elif case == "duplicate-natural-key":
        identity = replace(
            identity,
            natural_keys=_values(identity.natural_keys, "businessId,businessId"),
        )
    elif case == "source-key-domain-scope":
        identity = replace(
            identity,
            strategy=_values(
                identity.strategy,
                IdentityStrategy.SOURCE_SCOPED_IMMUTABLE_KEY.value,
            ),
        )
    elif case == "integration-without-exact-equivalence":
        identity = replace(
            identity,
            strategy=_values(
                identity.strategy,
                IdentityStrategy.DETERMINISTIC_INTEGRATION_KEY.value,
            ),
        )
    elif case == "integration-without-components":
        identity = replace(
            identity,
            strategy=_values(
                identity.strategy,
                IdentityStrategy.DETERMINISTIC_INTEGRATION_KEY.value,
            ),
            natural_keys=None,
        )
    elif case == "mastered-with-domain-scope":
        identity = replace(
            identity,
            strategy=_values(
                identity.strategy,
                IdentityStrategy.EXTERNALLY_MASTERED_IDENTIFIER.value,
            ),
        )
    elif case == "mastered-without-identifier":
        identity = replace(
            identity,
            strategy=_values(
                identity.strategy,
                IdentityStrategy.EXTERNALLY_MASTERED_IDENTIFIER.value,
            ),
            key_scope=_values(identity.key_scope, KeyScope.ENTERPRISE.value),
            natural_keys=None,
        )
    elif case == "surrogate-with-natural-key":
        identity = replace(
            identity,
            strategy=_values(
                identity.strategy,
                IdentityStrategy.SURROGATE_ONLY.value,
            ),
            key_scope=_values(identity.key_scope, KeyScope.SOURCE_TABLE.value),
            reconciliation_limitation=_authored(
                identity,
                "reconciliationLimitation",
                "Manual reconciliation only.",
            ),
        )
    elif case == "surrogate-without-limitation":
        identity = replace(
            identity,
            strategy=_values(
                identity.strategy,
                IdentityStrategy.SURROGATE_ONLY.value,
            ),
            key_scope=_values(identity.key_scope, KeyScope.SOURCE_TABLE.value),
            natural_keys=None,
        )
    elif case == "surrogate-with-domain-scope":
        identity = replace(
            identity,
            strategy=_values(
                identity.strategy,
                IdentityStrategy.SURROGATE_ONLY.value,
            ),
            natural_keys=None,
            reconciliation_limitation=_authored(
                identity,
                "reconciliationLimitation",
                "Manual reconciliation only.",
            ),
        )
    elif case == "business-with-limitation":
        identity = replace(
            identity,
            reconciliation_limitation=_authored(
                identity,
                "reconciliationLimitation",
                "Not valid for business identity.",
            ),
        )
    elif case == "missing-iri-policy":
        identity = replace(identity, iri_policy=None)
    elif case == "single-with-driving-source":
        identity = replace(
            identity,
            driving_source=_authored(identity, "drivingSource", RECORD_KEY),
        )
    elif case == "single-with-multi-policy":
        identity = replace(
            identity,
            multi_source_policy_refs=_authored(
                identity,
                "multiSourcePolicy",
                facts.multi_source[0].resource_uri,
            ),
        )
    elif case == "multi-without-driving-source":
        identity = replace(
            identity,
            strategy=_values(
                identity.strategy,
                IdentityStrategy.SOURCE_SCOPED_IMMUTABLE_KEY.value,
            ),
            key_scope=_values(identity.key_scope, KeyScope.SOURCE_TABLE.value),
            source_identities=_values(identity.source_identities, RECORD_KEY, ARRAY_KEY),
            multi_source_policy_refs=_authored(
                identity,
                "multiSourcePolicy",
                facts.multi_source[0].resource_uri,
            ),
        )
    elif case == "multi-with-unknown-driving-source":
        identity = replace(
            identity,
            strategy=_values(
                identity.strategy,
                IdentityStrategy.SOURCE_SCOPED_IMMUTABLE_KEY.value,
            ),
            key_scope=_values(identity.key_scope, KeyScope.SOURCE_TABLE.value),
            source_identities=_values(identity.source_identities, RECORD_KEY, ARRAY_KEY),
            driving_source=_authored(identity, "drivingSource", "urn:test#not-a-source"),
            multi_source_policy_refs=_authored(
                identity,
                "multiSourcePolicy",
                facts.multi_source[0].resource_uri,
            ),
        )
    elif case == "unknown-source-identity":
        identity = replace(
            identity,
            source_identities=_values(identity.source_identities, "urn:test#unknown"),
        )
    else:
        identity = replace(
            identity,
            source_identities=_values(
                identity.source_identities,
                RECORD_KEY,
                RECORD_KEY,
            ),
        )

    with pytest.raises(PolicyNormalizationError, match=error_code):
        _normalize(facts, mappings, identity)


def test_exact_equivalence_is_bidirectionally_gated(tmp_path):
    exact, exact_facts, mappings = _exact_equivalence_policy(tmp_path)
    identity = exact.identities[0]
    assert identity.integration.emitted
    assert exact.multi_source[0].exact_equivalence.approved

    authored = exact_facts.identities[0]
    wrong_strategy = replace(
        authored,
        strategy=_values(authored.strategy, IdentityStrategy.BUSINESS_KEY.value),
    )
    with pytest.raises(
        PolicyNormalizationError,
        match="identity.exact-equivalence-without-integration-strategy",
    ):
        _normalize(exact_facts, mappings, wrong_strategy)


def test_authored_natural_key_must_be_materially_supplied(tmp_path):
    facts, _, mappings = _bound_and_normalized(tmp_path)
    identity = facts.identities[0]
    candidate = _silver_candidate()
    candidate = replace(
        candidate,
        columns=tuple(
            column for column in candidate.columns if column.name != "business_id"
        ),
    )
    with pytest.raises(
        PolicyNormalizationError,
        match="identity.authored-key-not-supplied",
    ):
        _normalize(facts, mappings, identity, candidate=candidate)


def test_declared_source_identity_must_match_actual_prepared_contributor(tmp_path):
    facts, _, mappings = _bound_and_normalized(tmp_path)
    identity = replace(
        facts.identities[0],
        source_identities=_values(facts.identities[0].source_identities, ARRAY_KEY),
    )
    candidate = replace(
        _silver_candidate(),
        sources=(
            SourceBindingSpec(
                alias="src",
                source_name="test-source",
                table_name="test-table",
                table_uri="urn:test#table",
            ),
        ),
    )
    with pytest.raises(
        PolicyNormalizationError,
        match="identity.source-contributor-mismatch",
    ):
        _normalize(facts, mappings, identity, candidate=candidate)


def test_lineage_timestamp_roles_are_distinct_and_never_substituted(tmp_path):
    _, policy, _ = _bound_and_normalized(tmp_path)
    timestamps = {
        timestamp.role: timestamp for timestamp in policy.identities[0].lineage.timestamps
    }
    assert set(timestamps) == set(TimestampRole)
    assert len({timestamp.column_name for timestamp in timestamps.values()}) == 4
    assert timestamps[TimestampRole.LOADED_AT].origin.value is (
        TimestampOrigin.INJECTED_RUN_CLOCK
    )
    assert timestamps[TimestampRole.LOADED_AT].supplied
    assert timestamps[TimestampRole.SOURCE_UPDATED_AT].supplied
    assert timestamps[TimestampRole.INGESTED_AT].supplied
    assert timestamps[TimestampRole.SOURCE_EFFECTIVE_AT].supplied
    assert timestamps[TimestampRole.INGESTED_AT].origin.value is (
        TimestampOrigin.SOURCE_INGESTION
    )
    assert timestamps[TimestampRole.SOURCE_EFFECTIVE_AT].origin.value is (
        TimestampOrigin.SOURCE_BUSINESS_EFFECTIVE
    )


def test_single_source_driving_mode_and_optional_contribution_policy(tmp_path):
    facts, _, mappings = _bound_and_normalized(tmp_path)
    identity = facts.identities[0]
    policy = _normalize(facts, mappings, identity)
    driving = policy.identities[0].driving_source
    assert driving.mode.value.value == "only-source"
    assert driving.source_ref is not None
    assert driving.source_ref.value == RECORD_KEY
    assert policy.silver_models[0].contribution_lineage is None

    with_contribution = replace(
        identity,
        contribution_lineage=_authored(
            identity,
            "contributionLineagePolicy",
            "all-source-record-contributions",
        ),
    )
    contributed = _normalize(facts, mappings, with_contribution)
    relation = contributed.silver_models[0].contribution_lineage
    assert relation is not None
    assert relation.source_record_key_column == "_source_record_key"
