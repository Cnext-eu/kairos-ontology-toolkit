# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Focused Stage 2 coverage for immutable dbt adapter capabilities."""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest

from kairos_ontology.core.determinism import ENV_GENERATED_AT, resolve_generated_at
from kairos_ontology.core.projections.dbt.capabilities import (
    ADAPTER_CAPABILITY_REGISTRY,
    negotiate_capabilities,
)
from kairos_ontology.core.projections.dbt.policy_specs import (
    AdapterCapability,
    AdapterCapabilityRegistry,
    AdapterName,
    ApprovedDeviationSpec,
    CapabilityDisposition,
    CapabilityRequirementSpec,
    CapabilitySupport,
    EffectiveValue,
    PolicyProvenance,
    PolicySource,
)

_SOME_DATE = date(2026, 1, 1)


def _deviation(
    *,
    expiry_date: str,
    review_date: str = "2019-01-01",
    approved: bool = True,
    adapter: AdapterName | None = None,
    policy_reference: str = "DD-110-constraints",
    scope: str = "*",
) -> ApprovedDeviationSpec:
    """Build a minimal approved-deviation fixture for expiry tests."""

    def _value(value: str) -> EffectiveValue[str]:
        return EffectiveValue(
            value=value,
            provenance=PolicyProvenance(
                source=PolicySource.AUTHORED,
                rule_id="DD-114-deviation",
                resource_uri="urn:test:deviation-1",
            ),
        )

    return ApprovedDeviationSpec(
        resource_uri="urn:test:deviation-1",
        adapter=adapter,
        policy_reference=_value(policy_reference),
        scope=_value(scope),
        rationale=_value("test rationale"),
        owner_role=_value("test-owner"),
        approval_status=_value("approved" if approved else "rejected"),
        review_date=_value(review_date),
        expiry_date=_value(expiry_date),
        evidence=("test-evidence",),
    )


_CONSTRAINTS_REQUIREMENT = CapabilityRequirementSpec(
    AdapterCapability.CONSTRAINTS,
    "entity",
    "DD-110-constraints",
)

STAGE2_REQUIREMENTS = (
    CapabilityRequirementSpec(
        AdapterCapability.CANONICAL_SHA256_HASH,
        "incremental",
        "DD-109-hash",
    ),
    CapabilityRequirementSpec(
        AdapterCapability.INCREMENTAL_SCD1,
        "incremental",
        "DD-133-stage2-scd1",
    ),
    CapabilityRequirementSpec(
        AdapterCapability.INCREMENTAL_SCD2,
        "incremental",
        "DD-133-stage2-scd2",
    ),
    CapabilityRequirementSpec(
        AdapterCapability.TOTAL_ORDERING,
        "incremental",
        "DD-133-stage2-total-order",
    ),
    CapabilityRequirementSpec(
        AdapterCapability.TEMPORAL_FK_CURRENT,
        "relationship",
        "DD-133-stage2-temporal-current",
    ),
    CapabilityRequirementSpec(
        AdapterCapability.TEMPORAL_FK_AS_OF,
        "relationship",
        "DD-133-stage2-temporal-as-of",
    ),
    CapabilityRequirementSpec(
        AdapterCapability.SCHEMA_EVOLUTION_FAIL,
        "incremental",
        "DD-133-stage2-schema-evolution",
    ),
    CapabilityRequirementSpec(
        AdapterCapability.SCHEMA_EVOLUTION_APPEND_COMPATIBLE,
        "incremental",
        "DD-133-stage2-schema-evolution",
    ),
    CapabilityRequirementSpec(
        AdapterCapability.CONFORMANCE_UNION_ALL,
        "conformance",
        "DD-133-stage2-conformance",
    ),
    CapabilityRequirementSpec(
        AdapterCapability.CONFORMANCE_DEDUPLICATE,
        "conformance",
        "DD-133-stage2-conformance",
    ),
    CapabilityRequirementSpec(
        AdapterCapability.CONTRACTED_DBT_SOURCE,
        "source",
        "DD-133-stage2-contracted-source",
    ),
)


@pytest.mark.parametrize("adapter", tuple(AdapterName))
def test_stage2_physical_capabilities_are_explicitly_supported(adapter: AdapterName) -> None:
    results = negotiate_capabilities(adapter, STAGE2_REQUIREMENTS, current_date=_SOME_DATE)

    assert len(results) == len(STAGE2_REQUIREMENTS)
    assert {result.disposition for result in results} == {CapabilityDisposition.SUPPORTED}
    assert all(result.evidence for result in results)
    assert all(result.rule_id.startswith(("DD-109", "DD-133")) for result in results)


@pytest.mark.parametrize("adapter", tuple(AdapterName))
def test_stage2_profile_covers_every_declared_capability_once(adapter: AdapterName) -> None:
    profile = ADAPTER_CAPABILITY_REGISTRY.adapter(adapter)
    declared = [item.capability for item in profile.capabilities]

    assert len(declared) == len(set(declared))
    assert set(declared) == set(AdapterCapability)


def test_unsupported_stage2_combination_blocks_without_fallback() -> None:
    fabric = ADAPTER_CAPABILITY_REGISTRY.adapter(AdapterName.FABRIC)
    capabilities = tuple(
        (
            dataclasses.replace(item, support=CapabilitySupport.UNSUPPORTED)
            if item.capability is AdapterCapability.SCHEMA_EVOLUTION_APPEND_COMPATIBLE
            else item
        )
        for item in fabric.capabilities
    )
    registry = AdapterCapabilityRegistry(
        version="stage2-unsupported-test",
        adapters=(dataclasses.replace(fabric, capabilities=capabilities),),
    )
    requirement = CapabilityRequirementSpec(
        AdapterCapability.SCHEMA_EVOLUTION_APPEND_COMPATIBLE,
        "incremental",
        "DD-133-stage2-schema-evolution",
    )

    result = negotiate_capabilities(
        AdapterName.FABRIC, (requirement,), registry=registry, current_date=_SOME_DATE
    )

    assert result[0].disposition is CapabilityDisposition.BLOCKING
    assert result[0].message == "Capability is unsupported by this adapter."


def test_expired_deviation_no_longer_authorizes_the_degradation() -> None:
    """An approved deviation whose expiry_date has passed must stop matching.

    Regression test for GitHub issue #319: a matched-but-expired deviation used
    to flip the disposition to DEVIATION unconditionally, so the underlying
    capability requirement never resumed blocking once its waiver lapsed. The
    requirement must block again, exactly as if the deviation were never
    written.
    """
    deviation = _deviation(expiry_date="2020-01-01")

    result = negotiate_capabilities(
        AdapterName.FABRIC,
        (_CONSTRAINTS_REQUIREMENT,),
        (deviation,),
        current_date=date(2026, 1, 1),
    )

    assert result[0].disposition is CapabilityDisposition.BLOCKING
    assert result[0].deviation_ref is None
    assert result[0].message == "Capability requires an approved scoped deviation."


def test_unexpired_deviation_still_authorizes_the_degradation() -> None:
    """A deviation whose expiry_date is still in the future keeps matching.

    Guards against over-correcting the #319 fix: approved, non-expired
    deviations must continue to authorize their capability exactly as before.
    """
    deviation = _deviation(expiry_date="2099-01-01")

    result = negotiate_capabilities(
        AdapterName.FABRIC,
        (_CONSTRAINTS_REQUIREMENT,),
        (deviation,),
        current_date=date(2026, 1, 1),
    )

    assert result[0].disposition is CapabilityDisposition.DEVIATION
    assert result[0].deviation_ref == "urn:test:deviation-1"


def test_deviation_expiry_is_case_deterministic_via_kairos_generated_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expiry must be judged against the pinned KAIROS_GENERATED_AT clock.

    The deviation's expiry_date (2026-06-01) is in the past relative to the
    real wall clock at authoring time, but in the future relative to a
    KAIROS_GENERATED_AT pin of 2026-01-01. If the code read a wall clock
    directly (forbidden by the determinism convention in
    ``core/determinism.py``), this deviation would wrongly be treated as
    expired. Resolving "now" through resolve_generated_at() and threading it
    in as ``current_date`` must make the deviation match instead.
    """
    monkeypatch.setenv(ENV_GENERATED_AT, "2026-01-01T00:00:00Z")
    deviation = _deviation(expiry_date="2026-06-01")

    pinned_now = resolve_generated_at()
    assert pinned_now.date() == date(2026, 1, 1)

    result = negotiate_capabilities(
        AdapterName.FABRIC,
        (_CONSTRAINTS_REQUIREMENT,),
        (deviation,),
        current_date=pinned_now.date(),
    )

    assert result[0].disposition is CapabilityDisposition.DEVIATION
    assert result[0].deviation_ref == "urn:test:deviation-1"
