# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Focused Stage 2 coverage for immutable dbt adapter capabilities."""

from __future__ import annotations

import dataclasses

import pytest

from kairos_ontology.core.projections.dbt.capabilities import (
    ADAPTER_CAPABILITY_REGISTRY,
    negotiate_capabilities,
)
from kairos_ontology.core.projections.dbt.policy_specs import (
    AdapterCapability,
    AdapterCapabilityRegistry,
    AdapterName,
    CapabilityDisposition,
    CapabilityRequirementSpec,
    CapabilitySupport,
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
    results = negotiate_capabilities(adapter, STAGE2_REQUIREMENTS)

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

    result = negotiate_capabilities(AdapterName.FABRIC, (requirement,), registry=registry)

    assert result[0].disposition is CapabilityDisposition.BLOCKING
    assert result[0].message == "Capability is unsupported by this adapter."
