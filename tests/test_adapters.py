# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Canonical target-platform vocabulary (DD-215)."""

from __future__ import annotations

import pytest

from kairos_ontology.core.adapters import (
    ADAPTER_CHOICES,
    DBT_ADAPTER_PACKAGES,
    DBT_PROFILE_TYPES,
    SUPPORTED_ADAPTER_IDS,
    AdapterName,
    UnsupportedAdapterError,
    dbt_profile_type,
    resolve_adapter,
)


def test_canonical_ids_name_the_engine_not_the_vendor():
    """`fabric` alone cannot distinguish Warehouse T-SQL from Lakehouse Spark SQL."""

    assert SUPPORTED_ADAPTER_IDS == ("fabric-warehouse", "databricks")


@pytest.mark.parametrize("adapter", SUPPORTED_ADAPTER_IDS)
def test_canonical_ids_resolve_to_themselves_without_deprecation(adapter: str):
    assert resolve_adapter(adapter) == (adapter, None)


def test_deprecated_fabric_spelling_still_resolves_and_says_so():
    """Hubs are client repos; an upgrade must not break one outright."""

    canonical, deprecation = resolve_adapter("fabric")
    assert canonical == "fabric-warehouse"
    assert deprecation is not None
    assert "fabric-warehouse" in deprecation


def test_enum_construction_also_resolves_the_alias():
    assert AdapterName("fabric") is AdapterName.FABRIC_WAREHOUSE


def test_fabric_lakehouse_is_rejected_with_its_own_reason():
    """It must never silently receive the T-SQL profile just because it is also Fabric."""

    with pytest.raises(UnsupportedAdapterError) as excinfo:
        resolve_adapter("fabric-lakehouse")
    assert "Spark SQL" in str(excinfo.value)
    assert "fabric-warehouse" in str(excinfo.value)


@pytest.mark.parametrize("value", ["snowflake", "postgres", "", "FABRIC", "duckdb"])
def test_unknown_adapters_never_fall_back(value: str):
    with pytest.raises(UnsupportedAdapterError):
        resolve_adapter(value)


def test_cli_choices_accept_canonical_ids_and_deprecated_spellings():
    assert set(SUPPORTED_ADAPTER_IDS) <= set(ADAPTER_CHOICES)
    assert "fabric" in ADAPTER_CHOICES


def test_dbt_vocabulary_is_mapped_not_assumed_to_be_ours():
    """dbt-fabric calls itself `fabric` whichever Fabric engine it points at."""

    assert dbt_profile_type("fabric-warehouse") == "fabric"
    assert dbt_profile_type("fabric") == "fabric"
    assert dbt_profile_type("databricks") == "databricks"


@pytest.mark.parametrize("adapter", SUPPORTED_ADAPTER_IDS)
def test_every_supported_adapter_declares_its_dbt_type_and_package(adapter: str):
    assert adapter in DBT_PROFILE_TYPES
    assert adapter in DBT_ADAPTER_PACKAGES
