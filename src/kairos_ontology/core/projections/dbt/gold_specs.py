# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Immutable Gold product specifications and physical plans (DD-112/DD-113)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .policy_specs import (
    BridgeCardinality,
    CanonicalTypeSpec,
    CorrectionAction,
    DimensionExposure,
    DimensionVersionBinding,
    FactType,
    GoldProfileName,
    GoldTableRole,
    LateArrivalAction,
    MeasureLifecycle,
)


class GoldContractError(ValueError):
    """An authored Gold product cannot be bound to actual Silver materialization."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        rule_id: str,
        resource_uri: str = "",
    ) -> None:
        self.code = code
        self.rule_id = rule_id
        self.resource_uri = resource_uri
        self.blocking_rules = ((rule_id, message),)
        super().__init__(f"{code}: {message}")


class GoldSecurityKind(str, Enum):
    RLS = "RLS"
    OLS = "OLS"


class GoldProductLogicalSpec(Protocol):
    """Common contract implemented by each profile-specific logical product."""

    profile: GoldProfileName
    profile_version: str
    ontology_name: str
    ontology_version: str
    adapter: str


class GoldProductPhysicalSpec(Protocol):
    """Common contract implemented by each profile-specific physical plan."""

    profile: GoldProfileName
    profile_version: str
    adapter: str
    adapter_version: str


@dataclass(frozen=True, slots=True)
class GoldColumnSpec:
    source_name: str
    name: str
    canonical_type: CanonicalTypeSpec
    nullable: bool
    role: str
    comment: str
    provenance: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GoldTableSpec:
    resource_uri: str
    name: str
    schema_name: str
    role: GoldTableRole
    source_model: str
    source_version: str
    columns: tuple[GoldColumnSpec, ...]
    primary_key: str
    fact_grain: str = ""
    fact_type: FactType | None = None
    version_binding: DimensionVersionBinding | None = None
    correction: CorrectionAction | None = None
    late_arrival: LateArrivalAction | None = None
    incremental_policy_ref: str = ""
    incremental_unique_key: tuple[str, ...] = ()
    incremental_updated_at: str = ""
    dimension_exposure: DimensionExposure | None = None
    silver_scd_type: str = ""
    bridge_grain: str = ""
    bridge_endpoints: tuple[str, str] | None = None
    bridge_endpoint_bindings: tuple[tuple[str, str], ...] = ()
    bridge_cardinality: BridgeCardinality | None = None
    bridge_weight_column: str = ""
    bridge_allocation: str = ""
    perspectives: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GoldRelationshipSpec:
    name: str
    source_table: str
    source_column: str
    target_table: str
    target_column: str
    cardinality: str
    version_binding: DimensionVersionBinding | None
    role_name: str = ""


@dataclass(frozen=True, slots=True)
class GoldMeasureSpec:
    resource_uri: str
    measure_id: str
    definition: str
    expression: str
    lifecycle: MeasureLifecycle
    home_table: str
    column_dependencies: tuple[tuple[str, str], ...]
    measure_dependencies: tuple[str, ...]
    data_type: str
    format_string: str
    folder: str
    owner_role: str
    tests: tuple[str, ...]
    evidence: tuple[str, ...]
    emitted: bool
    data_validated: bool = False


@dataclass(frozen=True, slots=True)
class GoldCalendarRoleSpec:
    role_name: str
    table_name: str
    column_name: str


@dataclass(frozen=True, slots=True)
class GoldCalendarSpec:
    resource_uri: str
    start_date: str
    end_date: str
    fiscal_year_start_month: int
    week_pattern: str
    locale: str
    holiday_source: str
    time_zone: str
    period_closure: str
    roles: tuple[GoldCalendarRoleSpec, ...]
    approved: bool


@dataclass(frozen=True, slots=True)
class GoldSecurityBindingSpec:
    table_name: str
    column_name: str
    role_name: str
    kind: GoldSecurityKind


@dataclass(frozen=True, slots=True)
class GoldSecuritySpec:
    resource_uri: str
    entitlement_source: str
    identity_mapping: str
    roles: tuple[str, ...]
    filter_direction: str
    bindings: tuple[GoldSecurityBindingSpec, ...]
    positive_tests: tuple[str, ...]
    negative_tests: tuple[str, ...]
    test_evidence: tuple[str, ...]
    fail_closed: bool


@dataclass(frozen=True, slots=True)
class DimensionalGoldSpec:
    profile: GoldProfileName
    profile_version: str
    ontology_name: str
    ontology_version: str
    schema_name: str
    adapter: str
    tables: tuple[GoldTableSpec, ...]
    relationships: tuple[GoldRelationshipSpec, ...]
    measures: tuple[GoldMeasureSpec, ...]
    calendar: GoldCalendarSpec | None
    security: GoldSecuritySpec | None
    perspectives: tuple[tuple[str, tuple[str, ...]], ...]
    silver_registry_names: tuple[tuple[str, str], ...]
    silver_registry_columns: tuple[tuple[str, frozenset[str]], ...]


@dataclass(frozen=True, slots=True)
class GoldPhysicalColumnPlan:
    ordinal: int
    name: str
    physical_type: str
    tmdl_type: str
    nullable: bool
    role: str
    comment: str


@dataclass(frozen=True, slots=True)
class GoldPhysicalTablePlan:
    name: str
    schema_name: str
    role: GoldTableRole
    columns: tuple[GoldPhysicalColumnPlan, ...]
    primary_key: str
    materialization: str
    unique_key: tuple[str, ...]
    updated_at: str
    current_filter: str
    dual_current_name: str


@dataclass(frozen=True, slots=True)
class GoldPhysicalPlan:
    profile: GoldProfileName
    profile_version: str
    adapter: str
    adapter_version: str
    semantic_mode: str
    tables: tuple[GoldPhysicalTablePlan, ...]
    approved_deviations: tuple[str, ...]
    ddl_artifact_path: str
    dbt_schema_artifact_path: str
    erd_artifact_path: str
    report_artifact_path: str
    exposures_artifact_path: str
