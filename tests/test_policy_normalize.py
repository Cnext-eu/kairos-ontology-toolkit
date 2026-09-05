# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for :func:`_validate_identity_columns` in policy_normalize.py.

#486: the ``identity.authored-key-not-supplied`` error must explain that output
column names are derived from source column names via snake_case conversion,
and include the expected snake_case name for each missing column that is not
already snake_case.
"""

from __future__ import annotations

import pytest

from kairos_ontology.core.projections.dbt.policy_normalize import (
    PolicyNormalizationError,
    _column_role,
    _identity_column_nullable,
    _validate_identity_columns,
)
from kairos_ontology.core.projections.dbt.policy_specs import (
    BusinessIdentityPolicy,
    ChangeDetectionStrategy,
    DrivingSourceMode,
    DrivingSourceSpec,
    EntityIriMode,
    EntityIdentitySpec,
    IdentityStrategy,
    IntegrationIdentityPolicy,
    IriPolicy,
    KeyScope,
    LineageSpec,
    MasteredIdentityPolicy,
    SilverColumnRole,
    SourceIdentityPolicy,
    SurrogateIdentityPolicy,
    EffectiveValue,
    PolicyProvenance,
    PolicySource,
)
from kairos_ontology.core.projections.dbt.specs import (
    BoundSilverModel,
    ColumnSpec,
    ModelIdentity,
    ModelOutcome,
    SilverModelKind,
)

_PROV = PolicyProvenance(source=PolicySource.AUTHORED, rule_id="DD-108-business-identity")
_IRI = "https://example.test/party#Customer"


def _identity(keys: tuple[str, ...]) -> EntityIdentitySpec:
    return EntityIdentitySpec(
        entity_uri=_IRI,
        business_grain=EffectiveValue("party", _PROV),
        strategy=EffectiveValue(IdentityStrategy.BUSINESS_KEY, _PROV),
        key_scope=EffectiveValue(KeyScope.SOURCE_TABLE, _PROV),
        source=SourceIdentityPolicy(
            record_key_refs=EffectiveValue(("customer_id",), _PROV),
        ),
        business=BusinessIdentityPolicy(
            keys=EffectiveValue(keys, _PROV),
            authoritative=True,
        ),
        integration=IntegrationIdentityPolicy(emitted=False),
        mastered=MasteredIdentityPolicy(
            external_identifier_refs=EffectiveValue((), _PROV),
            routed_to_mdm=False,
        ),
        surrogate=SurrogateIdentityPolicy(
            emitted_as_join_key=True,
            establishes_business_identity=False,
            reconciliation_limitation=None,
        ),
        iri=IriPolicy(
            mode=EffectiveValue(EntityIriMode.OMIT, _PROV),
        ),
        driving_source=DrivingSourceSpec(
            mode=EffectiveValue(DrivingSourceMode.ONLY_SOURCE, _PROV),
            source_ref=EffectiveValue("crm.customers", _PROV),
        ),
        change_detection=EffectiveValue(ChangeDetectionStrategy.COMPARE_COLUMNS, _PROV),
        lineage=LineageSpec(
            policy=EffectiveValue("default", _PROV),
            contribution=None,
            timestamps=(),
        ),
        multi_source_policy_ref=None,
        hash_policy_ref=None,
        incremental_policy_ref=None,
    )


def _candidate(columns: tuple[ColumnSpec, ...]) -> BoundSilverModel:
    return BoundSilverModel(
        identity=ModelIdentity(
            class_name="Customer",
            class_uri=_IRI,
            model_name="customer",
            domain_name="party",
            schema_name="party",
            artifact_path=None,
            outcome=ModelOutcome.GENERATED,
        ),
        kind=SilverModelKind.ENTITY,
        columns=columns,
    )


def test_missing_camel_case_key_shows_expected_snake_case():
    """Output column names are derived from source column names via snake_case
    conversion. When the authored key is camelCase (e.g. ``OrderNo``), the error
    must include the expected snake_case output name."""
    identity = _identity(("OrderNo",))
    candidate = _candidate(
        (ColumnSpec(name="customer_id", expression="customer_id"),)
    )
    with pytest.raises(PolicyNormalizationError) as excinfo:
        _validate_identity_columns(candidate, identity)

    assert excinfo.value.code == "identity.authored-key-not-supplied"
    msg = str(excinfo.value)
    assert "snake_case conversion" in msg
    assert "OrderNo (expected snake_case output name: order_no)" in msg


def test_missing_snake_case_key_shown_as_is():
    """When the missing column is already snake_case (e.g. ``order_no``), the
    error must show it as-is without a parenthetical snake_case hint."""
    identity = _identity(("order_no",))
    candidate = _candidate(
        (ColumnSpec(name="customer_id", expression="customer_id"),)
    )
    with pytest.raises(PolicyNormalizationError) as excinfo:
        _validate_identity_columns(candidate, identity)

    msg = str(excinfo.value)
    assert "snake_case conversion" in msg
    assert "order_no" in msg
    assert "(expected snake_case output name:" not in msg


def test_multiple_missing_keys_show_mixed_detail():
    """When some keys are camelCase and some are snake_case, the error must
    annotate each missing column appropriately."""
    identity = _identity(("OrderNo", "order_seq"))
    candidate = _candidate(
        (ColumnSpec(name="customer_id", expression="customer_id"),)
    )
    with pytest.raises(PolicyNormalizationError) as excinfo:
        _validate_identity_columns(candidate, identity)

    msg = str(excinfo.value)
    assert "OrderNo (expected snake_case output name: order_no)" in msg
    # order_seq is already snake_case -- shown as-is, no parenthetical hint
    msg_order_seq = msg[msg.index("order_seq"):msg.index("order_seq") + len("order_seq")]
    assert msg_order_seq == "order_seq"


# --- #609: _column_role / _identity_column_nullable ---------------------------------


def test_column_role_classifies_wired_fk_by_role_tag_not_just_fk_names():
    """A column kernel.py already tagged ``role="foreign-key"`` must classify as
    FOREIGN_KEY even when its name isn't in ``fk_names`` (fk_names only ever holds the
    *local join column* name, never the emitted ``_sk`` alias -- #609)."""
    column = ColumnSpec(name="country_sk", role="foreign-key")
    assert _column_role(column, frozenset()) is SilverColumnRole.FOREIGN_KEY


def test_column_role_still_matches_fk_names_fallback():
    """The pre-existing name-based match (used by a separate RDF/ontology pipeline)
    must keep working for a column with no role tag."""
    column = ColumnSpec(name="customer_id", role="")
    assert _column_role(column, frozenset({"customer_id"})) is SilverColumnRole.FOREIGN_KEY


def test_column_role_unrelated_sk_column_stays_surrogate_join_key():
    """A genuine surrogate PK (``{model}_sk``, no FK role tag, no fk_names match) must
    not be reclassified -- only relationship FK columns are affected by #609."""
    column = ColumnSpec(name="customer_sk", role="")
    assert _column_role(column, frozenset()) is SilverColumnRole.SURROGATE_JOIN_KEY


@pytest.mark.parametrize(
    ("column_nullable", "expected"),
    [(True, True), (False, False), (None, True)],
)
def test_identity_column_nullable_foreign_key_follows_column_nullable(
    column_nullable, expected
):
    """#609: FK nullability must follow the already-computed ``ColumnSpec.nullable``
    (kernel.py's ``relationship.missing_parent != "error"``), not a hard-coded value.
    ``None`` (no wired value available) preserves the historical default of nullable."""
    assert (
        _identity_column_nullable(SilverColumnRole.FOREIGN_KEY, None, column_nullable)
        is expected
    )


@pytest.mark.parametrize(
    "role",
    [
        SilverColumnRole.SOURCE_IDENTITY,
        SilverColumnRole.INTEGRATION_IDENTITY,
        SilverColumnRole.MASTERED_IDENTIFIER,
        SilverColumnRole.SURROGATE_JOIN_KEY,
        SilverColumnRole.ENTITY_IRI,
    ],
)
def test_identity_column_nullable_non_fk_roles_ignore_column_nullable(role):
    """The new ``column_nullable`` parameter must be inert for every role other than
    FOREIGN_KEY -- these roles stay hard-coded non-nullable regardless of it."""
    assert _identity_column_nullable(role, None, column_nullable=True) is False
    assert _identity_column_nullable(role, None, column_nullable=None) is False
