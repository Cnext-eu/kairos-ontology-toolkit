# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Adapter-aware physical planning for governed Gold products."""

from __future__ import annotations

from .capabilities import physical_canonical_type
from .gold_specs import (
    DimensionalGoldSpec,
    GoldContractError,
    GoldPhysicalColumnPlan,
    GoldPhysicalPlan,
    GoldPhysicalTablePlan,
    GoldProductLogicalSpec,
    GoldProductPhysicalSpec,
)
from .policy_specs import (
    CanonicalTypeKind,
    CapabilityDisposition,
    CapabilityResultSpec,
    GoldProfileName,
)

_TMDL_TYPES = {
    CanonicalTypeKind.STRING: "String",
    CanonicalTypeKind.BOOLEAN: "Boolean",
    CanonicalTypeKind.INT16: "Int64",
    CanonicalTypeKind.INT32: "Int64",
    CanonicalTypeKind.INT64: "Int64",
    CanonicalTypeKind.DECIMAL: "Decimal",
    CanonicalTypeKind.FLOAT64: "Double",
    CanonicalTypeKind.DATE: "DateTime",
    CanonicalTypeKind.TIME: "String",
    CanonicalTypeKind.TIMESTAMP: "DateTime",
    CanonicalTypeKind.BINARY: "Binary",
    CanonicalTypeKind.JSON: "String",
}


def _materialize_dimensional_powerbi(
    spec: DimensionalGoldSpec,
    *,
    adapter_version: str,
    capability_results: tuple[CapabilityResultSpec, ...],
) -> GoldPhysicalPlan:
    """Map one logical Gold product to an exact supported/deviated adapter plan."""
    blockers = tuple(
        result
        for result in capability_results
        if result.scope == "gold" and result.disposition is CapabilityDisposition.BLOCKING
    )
    if blockers:
        detail = "; ".join(
            result.message or f"{result.capability.value} is unsupported for Gold"
            for result in blockers
        )
        raise GoldContractError(
            "gold.adapter-capability-blocking",
            detail,
            rule_id=blockers[0].rule_id,
        )
    tables: list[GoldPhysicalTablePlan] = []
    for table in spec.tables:
        columns = tuple(
            GoldPhysicalColumnPlan(
                ordinal=ordinal,
                name=column.name,
                physical_type=physical_canonical_type(
                    spec.adapter,
                    column.canonical_type,
                ),
                tmdl_type=_TMDL_TYPES[column.canonical_type.kind],
                nullable=column.nullable,
                role=column.role,
                comment=column.comment,
            )
            for ordinal, column in enumerate(table.columns, start=1)
        )
        current_filter = ""
        dual_name = ""
        if table.dimension_exposure is not None:
            if table.dimension_exposure.value == "current-only" and table.silver_scd_type == "2":
                current_filter = "is_current = 1"
            if table.dimension_exposure.value == "dual":
                dual_name = f"{table.name}_current"
        tables.append(
            GoldPhysicalTablePlan(
                name=table.name,
                schema_name=table.schema_name,
                role=table.role,
                columns=columns,
                primary_key=table.primary_key,
                materialization=("incremental" if table.incremental_policy_ref else "table"),
                unique_key=table.incremental_unique_key,
                updated_at=table.incremental_updated_at,
                current_filter=current_filter,
                dual_current_name=dual_name,
            )
        )
    deviations = tuple(
        sorted(
            {
                result.deviation_ref
                for result in capability_results
                if result.disposition is CapabilityDisposition.DEVIATION
                and result.deviation_ref
                and result.scope in {"*", "gold", "project"}
            }
        )
    )
    domain = spec.ontology_name
    return GoldPhysicalPlan(
        profile=spec.profile,
        profile_version=spec.profile_version,
        adapter=spec.adapter,
        adapter_version=adapter_version,
        semantic_mode="directLake" if spec.adapter == "fabric" else "directQuery",
        tables=tuple(tables),
        approved_deviations=deviations,
        ddl_artifact_path=f"{domain}/{domain}-gold-ddl.sql",
        dbt_schema_artifact_path=(f"models/gold/{domain}/_{domain}__gold_models.yml"),
        erd_artifact_path=f"{domain}/{domain}-gold-erd.mmd",
        report_artifact_path=f"{domain}/{domain}-gold-product.json",
    )


_PROFILE_MATERIALIZERS = {
    GoldProfileName.DIMENSIONAL_POWERBI_V1: _materialize_dimensional_powerbi,
}


def materialize_gold_product(
    spec: GoldProductLogicalSpec,
    *,
    adapter_version: str,
    capability_results: tuple[CapabilityResultSpec, ...],
) -> GoldProductPhysicalSpec:
    """Dispatch physical planning by exact profile without a generic Gold fallback."""
    materializer = _PROFILE_MATERIALIZERS.get(spec.profile)
    if materializer is not None:
        return materializer(
            spec,
            adapter_version=adapter_version,
            capability_results=capability_results,
        )
    raise GoldContractError(
        "gold.profile-materializer-missing",
        f"Gold profile {spec.profile.value!r} has no physical materializer",
        rule_id="DD-112-profile",
    )
