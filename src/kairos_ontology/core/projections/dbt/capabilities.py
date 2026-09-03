# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Versioned Fabric and Databricks capability negotiation (DD-111, DD-133)."""

from __future__ import annotations

import re
from datetime import date

from .policy_specs import (
    AdapterCapability,
    AdapterDialectSpec,
    AdapterCapabilityRegistry,
    AdapterCapabilitySpec,
    AdapterName,
    AdapterSpec,
    ApprovedDeviationSpec,
    CanonicalTypeKind,
    CanonicalTypeMappingSpec,
    CanonicalTypeSpec,
    CapabilityDisposition,
    CapabilityRequirementSpec,
    CapabilityResultSpec,
    CapabilitySupport,
)

_FABRIC_RESERVED = frozenset(
    {
        "alter",
        "backup",
        "check",
        "close",
        "column",
        "commit",
        "constraint",
        "create",
        "cursor",
        "database",
        "date",
        "default",
        "delete",
        "drop",
        "execute",
        "fetch",
        "foreign",
        "from",
        "function",
        "grant",
        "group",
        "identity",
        "index",
        "insert",
        "key",
        "level",
        "open",
        "option",
        "order",
        "plan",
        "primary",
        "procedure",
        "references",
        "revoke",
        "role",
        "rollback",
        "rule",
        "schema",
        "select",
        "status",
        "system",
        "table",
        "time",
        "transaction",
        "trigger",
        "type",
        "update",
        "user",
        "value",
        "view",
    }
)

_DATABRICKS_RESERVED = frozenset(
    {
        "all",
        "alter",
        "and",
        "as",
        "between",
        "by",
        "case",
        "cast",
        # Spark SQL ANSI reserved keywords that overlap legacy T-SQL quoting needs.
        "check",
        "column",
        "constraint",
        "create",
        "cross",
        "delete",
        "distinct",
        "drop",
        "else",
        "end",
        "exists",
        "false",
        "fetch",
        "foreign",
        "from",
        "full",
        "grant",
        "group",
        "having",
        "in",
        "inner",
        "insert",
        "into",
        "is",
        "join",
        "left",
        "like",
        "limit",
        "not",
        "null",
        "on",
        "or",
        "order",
        "outer",
        "primary",
        "references",
        "right",
        "select",
        "table",
        "then",
        "true",
        "union",
        "update",
        "user",
        "using",
        "when",
        "where",
        "with",
    }
)

_COMMON_PREPARATION_FEATURES = frozenset(
    {
        "array:element-index",
        "array:element-key",
        "array:zero-children",
        "cast:fail",
        "cast:null-with-evidence",
        "cleanup:left-trim",
        "cleanup:line-ending-normalize",
        "cleanup:right-trim",
        "cleanup:trim",
        "json-scalar:fail",
        "json-scalar:null-with-evidence",
        "parse:boolean-canonical:boolean",
        "parse:decimal-invariant:decimal",
        "parse:decimal-invariant:float64",
        "parse:integer-lexical:int16",
        "parse:integer-lexical:int32",
        "parse:integer-lexical:int64",
        "parse:integer-lexical:string",
        "parse:strict-text:string",
        "raw-payload-retention",
        "replayable-reference-retention",
        "schema-evolution:fail",
        "schema-evolution:approved-contract-update",
        "array:scalar-object-elements",
        "technical-dedupe",
    }
)


def _type(
    semantic: CanonicalTypeKind,
    physical: str,
    *,
    lossy: bool = False,
    evidence: str,
) -> CanonicalTypeMappingSpec:
    return CanonicalTypeMappingSpec(
        semantic_type=semantic,
        physical_type=physical,
        lossy=lossy,
        evidence=(evidence,),
    )


def _capability(
    capability: AdapterCapability,
    support: CapabilitySupport,
    rule_id: str,
    evidence: str,
    *,
    allowed_deviation: bool = False,
) -> AdapterCapabilitySpec:
    return AdapterCapabilitySpec(
        capability=capability,
        support=support,
        rule_id=rule_id,
        evidence=(evidence,),
        allowed_deviation=allowed_deviation,
    )


_COMMON_CAPABILITIES = (
    _capability(
        AdapterCapability.CANONICAL_TYPES,
        CapabilitySupport.SUPPORTED,
        "DD-111-types",
        "registry-v1: explicit semantic-to-physical type map",
    ),
    _capability(
        AdapterCapability.CANONICAL_SHA256_HASH,
        CapabilitySupport.SUPPORTED,
        "DD-109-hash",
        "registry-v1: SHA-256 over typed length-delimited canonical input",
    ),
    _capability(
        AdapterCapability.JSON_SCALAR,
        CapabilitySupport.SUPPORTED,
        "DD-106-json-scalar",
        "registry-v1: bounded scalar JSON extraction",
    ),
    _capability(
        AdapterCapability.JSON_ARRAY_CHILD,
        CapabilitySupport.SUPPORTED,
        "DD-106-json-array",
        "registry-v1: keyed array-child expansion",
    ),
    _capability(
        AdapterCapability.MERGE_UPSERT,
        CapabilitySupport.SUPPORTED,
        "DD-109-merge",
        "registry-v1: deterministic merge/upsert",
    ),
    _capability(
        AdapterCapability.DELETE_SEMANTICS,
        CapabilitySupport.SUPPORTED,
        "DD-109-delete",
        "registry-v1: explicit hard/soft delete handling",
    ),
    _capability(
        AdapterCapability.WINDOW_FUNCTIONS,
        CapabilitySupport.SUPPORTED,
        "DD-109-total-order",
        "registry-v1: deterministic partitioned ranking and interval windows",
    ),
    _capability(
        AdapterCapability.TEMPORAL_LOOKUP,
        CapabilitySupport.SUPPORTED,
        "DD-109-temporal-fk",
        "registry-v1: cardinality-preserving current and closed-open as-of lookup",
    ),
    _capability(
        AdapterCapability.PHYSICAL_LAYOUT,
        CapabilitySupport.SUPPORTED,
        "DD-111-layout",
        "registry-v1: deployment-profile-owned physical layout",
    ),
    _capability(
        AdapterCapability.QUARANTINE,
        CapabilitySupport.SUPPORTED,
        "DD-115-quarantine",
        "registry-v1: reject/quarantine relation contract",
    ),
    _capability(
        AdapterCapability.DBT_TESTS,
        CapabilitySupport.SUPPORTED,
        "DD-115-tests",
        "registry-v1: toolkit-owned namespaced dbt tests",
    ),
)


def _stage2_capabilities(
    adapter: AdapterName,
    evidence: str,
) -> tuple[AdapterCapabilitySpec, ...]:
    merge = {
        AdapterName.FABRIC_WAREHOUSE: "Fabric Warehouse MERGE",
        AdapterName.DATABRICKS: "Delta MERGE",
    }.get(adapter)
    if merge is None:
        raise ValueError(f"No Stage 2 physical capability profile for {adapter!r}")
    return (
        _capability(
            AdapterCapability.INCREMENTAL_SCD1,
            CapabilitySupport.SUPPORTED,
            "DD-133-stage2-scd1",
            f"{evidence}: deterministic SCD1 through {merge} and existing dbt runtime plans",
        ),
        _capability(
            AdapterCapability.INCREMENTAL_SCD2,
            CapabilitySupport.SUPPORTED,
            "DD-133-stage2-scd2",
            f"{evidence}: closed-open SCD2 through {merge} and existing dbt runtime plans",
        ),
        _capability(
            AdapterCapability.TOTAL_ORDERING,
            CapabilitySupport.SUPPORTED,
            "DD-133-stage2-total-order",
            f"{evidence}: explicit ordered window keys with no implicit tie breaker",
        ),
        _capability(
            AdapterCapability.TEMPORAL_FK_CURRENT,
            CapabilitySupport.SUPPORTED,
            "DD-133-stage2-temporal-current",
            f"{evidence}: cardinality-checked current-parent lookup",
        ),
        _capability(
            AdapterCapability.TEMPORAL_FK_AS_OF,
            CapabilitySupport.SUPPORTED,
            "DD-133-stage2-temporal-as-of",
            f"{evidence}: cardinality-checked closed-open event-time lookup",
        ),
        _capability(
            AdapterCapability.SCHEMA_EVOLUTION_FAIL,
            CapabilitySupport.SUPPORTED,
            "DD-133-stage2-schema-evolution",
            f"{evidence}: dbt fail-on-schema-change contract",
        ),
        _capability(
            AdapterCapability.SCHEMA_EVOLUTION_APPEND_COMPATIBLE,
            CapabilitySupport.SUPPORTED,
            "DD-133-stage2-schema-evolution",
            f"{evidence}: dbt append-new-columns after compatibility validation",
        ),
        _capability(
            AdapterCapability.CONFORMANCE_UNION_ALL,
            CapabilitySupport.SUPPORTED,
            "DD-133-stage2-conformance",
            f"{evidence}: deterministic contracted-source UNION ALL",
        ),
        _capability(
            AdapterCapability.CONFORMANCE_DEDUPLICATE,
            CapabilitySupport.SUPPORTED,
            "DD-133-stage2-conformance",
            f"{evidence}: explicit precedence and total-order window deduplication",
        ),
        _capability(
            AdapterCapability.CONTRACTED_DBT_SOURCE,
            CapabilitySupport.SUPPORTED,
            "DD-133-stage2-contracted-source",
            f"{evidence}: ordinary dbt model plus authoritative YAML output contract",
        ),
    )


def _fabric() -> AdapterSpec:
    evidence = "fabric-warehouse-capability-profile-v1"
    return AdapterSpec(
        name=AdapterName.FABRIC_WAREHOUSE,
        version="1.0",
        type_mappings=(
            _type(
                CanonicalTypeKind.STRING,
                "VARCHAR(8000)",
                lossy=True,
                evidence=f"{evidence}: unbounded strings require an authored bound",
            ),
            _type(CanonicalTypeKind.BOOLEAN, "BIT", evidence=evidence),
            _type(CanonicalTypeKind.INT16, "SMALLINT", evidence=evidence),
            _type(CanonicalTypeKind.INT32, "INT", evidence=evidence),
            _type(CanonicalTypeKind.INT64, "BIGINT", evidence=evidence),
            _type(CanonicalTypeKind.DECIMAL, "DECIMAL(p,s)", evidence=evidence),
            _type(CanonicalTypeKind.FLOAT64, "FLOAT", evidence=evidence),
            _type(CanonicalTypeKind.DATE, "DATE", evidence=evidence),
            _type(CanonicalTypeKind.TIME, "TIME", evidence=evidence),
            _type(
                CanonicalTypeKind.TIMESTAMP,
                "DATETIME2(6)",
                lossy=True,
                evidence=f"{evidence}: normalized to microsecond precision without zone",
            ),
            _type(
                CanonicalTypeKind.BINARY,
                "VARBINARY(8000)",
                lossy=True,
                evidence=f"{evidence}: unbounded binary requires an authored bound",
            ),
            _type(
                CanonicalTypeKind.JSON,
                "VARCHAR(8000)",
                lossy=True,
                evidence=f"{evidence}: JSON retained as text",
            ),
        ),
        capabilities=_COMMON_CAPABILITIES
        + _stage2_capabilities(AdapterName.FABRIC_WAREHOUSE, evidence)
        + (
            _capability(
                AdapterCapability.CONSTRAINTS,
                CapabilitySupport.DEVIATION_REQUIRED,
                "DD-110-constraints",
                f"{evidence}: warehouse PK/FK constraints may be non-enforced",
                allowed_deviation=True,
            ),
            _capability(
                AdapterCapability.SECURITY_RLS_OLS,
                CapabilitySupport.SUPPORTED,
                "DD-113-security",
                f"{evidence}: fail-closed TMDL RLS/OLS contract",
            ),
            _capability(
                AdapterCapability.TMDL,
                CapabilitySupport.SUPPORTED,
                "DD-113-tmdl",
                f"{evidence}: Power BI DirectLake TMDL",
            ),
        ),
        reserved_identifiers=_FABRIC_RESERVED,
        preparation_features=_COMMON_PREPARATION_FEATURES,
        dialect=AdapterDialectSpec(
            native_boolean=False,
            evidence=(
                f"{evidence}: BOOLEAN maps to BIT and T-SQL rejects a bare bit column "
                "wherever a condition is expected",
            ),
        ),
    )


def _databricks() -> AdapterSpec:
    evidence = "azure-databricks-capability-profile-v1"
    return AdapterSpec(
        name=AdapterName.DATABRICKS,
        version="1.0",
        type_mappings=(
            _type(CanonicalTypeKind.STRING, "STRING", evidence=evidence),
            _type(CanonicalTypeKind.BOOLEAN, "BOOLEAN", evidence=evidence),
            _type(CanonicalTypeKind.INT16, "SMALLINT", evidence=evidence),
            _type(CanonicalTypeKind.INT32, "INT", evidence=evidence),
            _type(CanonicalTypeKind.INT64, "BIGINT", evidence=evidence),
            _type(CanonicalTypeKind.DECIMAL, "DECIMAL(p,s)", evidence=evidence),
            _type(CanonicalTypeKind.FLOAT64, "DOUBLE", evidence=evidence),
            _type(CanonicalTypeKind.DATE, "DATE", evidence=evidence),
            _type(
                CanonicalTypeKind.TIME,
                "STRING",
                lossy=True,
                evidence=f"{evidence}: time-only values use canonical text",
            ),
            _type(
                CanonicalTypeKind.TIMESTAMP,
                "TIMESTAMP",
                lossy=True,
                evidence=f"{evidence}: time-zone normalization must be explicit",
            ),
            _type(CanonicalTypeKind.BINARY, "BINARY", evidence=evidence),
            _type(CanonicalTypeKind.JSON, "VARIANT", evidence=evidence),
        ),
        capabilities=_COMMON_CAPABILITIES
        + _stage2_capabilities(AdapterName.DATABRICKS, evidence)
        + (
            _capability(
                AdapterCapability.CONSTRAINTS,
                CapabilitySupport.DEVIATION_REQUIRED,
                "DD-110-constraints",
                f"{evidence}: Delta constraint enforcement differs by constraint kind",
                allowed_deviation=True,
            ),
            _capability(
                AdapterCapability.SECURITY_RLS_OLS,
                CapabilitySupport.DEVIATION_REQUIRED,
                "DD-113-security",
                f"{evidence}: Power BI entitlement enforcement is downstream",
                allowed_deviation=True,
            ),
            _capability(
                AdapterCapability.TMDL,
                CapabilitySupport.DEVIATION_REQUIRED,
                "DD-113-tmdl",
                f"{evidence}: TMDL targets the downstream Power BI semantic model",
                allowed_deviation=True,
            ),
        ),
        reserved_identifiers=_DATABRICKS_RESERVED,
        preparation_features=_COMMON_PREPARATION_FEATURES,
        dialect=AdapterDialectSpec(
            native_boolean=True,
            evidence=(f"{evidence}: Spark SQL has a first-class BOOLEAN type",),
        ),
    )


ADAPTER_CAPABILITY_REGISTRY = AdapterCapabilityRegistry(
    version="1.0",
    adapters=(_fabric(), _databricks()),
)


def adapter_spec(
    adapter: str | AdapterName,
    registry: AdapterCapabilityRegistry = ADAPTER_CAPABILITY_REGISTRY,
) -> AdapterSpec:
    """Return one exact adapter profile; unknown names never fall back."""
    try:
        name = adapter if isinstance(adapter, AdapterName) else AdapterName(adapter)
    except ValueError as exc:
        supported = ", ".join(item.value for item in AdapterName)
        raise ValueError(
            f"Unsupported adapter {adapter!r}; expected one of: {supported} (DD-111)"
        ) from exc
    return registry.adapter(name)


def is_reserved_identifier(
    adapter: str | AdapterName,
    identifier: str,
    registry: AdapterCapabilityRegistry = ADAPTER_CAPABILITY_REGISTRY,
) -> bool:
    """Return whether an unquoted identifier is reserved by the exact adapter."""
    return identifier.lower() in adapter_spec(adapter, registry).reserved_identifiers


def has_native_boolean(
    adapter: str | AdapterName,
    registry: AdapterCapabilityRegistry = ADAPTER_CAPABILITY_REGISTRY,
) -> bool:
    """Return whether the exact adapter has a first-class boolean type (DD-215).

    ``False`` means a canonically-BOOLEAN expression is a bit/integer value on this
    adapter, so it must be coerced when it lands in a condition -- and a native SQL
    predicate must be coerced when it lands in a value position.
    """
    return adapter_spec(adapter, registry).dialect.native_boolean


def physical_canonical_type(
    adapter: str | AdapterName,
    value: CanonicalTypeSpec,
    registry: AdapterCapabilityRegistry = ADAPTER_CAPABILITY_REGISTRY,
) -> str:
    """Resolve one canonical type through the selected adapter profile."""
    profile = adapter_spec(adapter, registry)
    mapping = next(
        (item for item in profile.type_mappings if item.semantic_type is value.kind),
        None,
    )
    if mapping is None:
        raise ValueError(f"Adapter {profile.name.value!r} has no mapping for {value.kind.value!r}")
    if value.kind is CanonicalTypeKind.DECIMAL:
        precision = value.precision or 18
        scale = value.scale if value.scale is not None else 4
        if precision > 38 or scale > precision:
            raise ValueError(
                f"Adapter {profile.name.value!r} cannot represent decimal({precision},{scale})"
            )
        return f"DECIMAL({precision},{scale})"
    if value.kind is CanonicalTypeKind.STRING and value.length:
        if profile.name is AdapterName.FABRIC_WAREHOUSE and value.length > 8000:
            raise ValueError(
                "Fabric preparation strings require an authored length of 8000 "
                f"or less, not {value.length}"
            )
        return f"VARCHAR({value.length})" if profile.name is AdapterName.FABRIC_WAREHOUSE else "STRING"
    return mapping.physical_type


_DECLARED_TYPE = re.compile(
    r"^\s*([a-zA-Z0-9_]+)\s*(?:\(\s*([0-9]+|max)\s*(?:,\s*([0-9]+)\s*)?\))?\s*$",
    re.I,
)


def _matching_deviation(
    adapter: AdapterName,
    requirement: CapabilityRequirementSpec,
    deviations: tuple[ApprovedDeviationSpec, ...],
    current_date: date,
) -> ApprovedDeviationSpec | None:
    """Return the first approved, unexpired deviation covering *requirement*.

    ``current_date`` is the resolved projection "now" (see
    :func:`kairos_ontology.core.determinism.resolve_generated_at`), threaded in
    explicitly by the caller so this module never reads a wall clock directly.
    A deviation whose ``expiry_date`` has passed relative to ``current_date`` is
    treated as if it had never been authored -- it is skipped so the search can
    continue to any other deviation record that might still cover the same
    rule/scope, rather than failing the match outright.
    """
    for deviation in deviations:
        if not deviation.approved:
            continue
        if deviation.adapter is not None and deviation.adapter is not adapter:
            continue
        if deviation.policy_reference.value != requirement.rule_id:
            continue
        if deviation.scope.value not in {requirement.scope, "*"}:
            continue
        if date.fromisoformat(deviation.expiry_date.value) < current_date:
            continue
        return deviation
    return None


def negotiate_capabilities(
    adapter: str | AdapterName,
    requirements: tuple[CapabilityRequirementSpec, ...],
    deviations: tuple[ApprovedDeviationSpec, ...] = (),
    registry: AdapterCapabilityRegistry = ADAPTER_CAPABILITY_REGISTRY,
    *,
    current_date: date,
) -> tuple[CapabilityResultSpec, ...]:
    """Negotiate exact requirements without adapter fallback or silent degradation.

    ``current_date`` must be the resolved projection "now" from
    :func:`kairos_ontology.core.determinism.resolve_generated_at`, supplied by the
    caller -- this module deliberately never reads a wall clock itself so that
    expired-deviation handling stays deterministic and reproducible.
    """
    try:
        adapter_name = adapter if isinstance(adapter, AdapterName) else AdapterName(adapter)
    except ValueError as exc:
        supported = ", ".join(item.value for item in AdapterName)
        raise ValueError(
            f"Unsupported adapter {adapter!r}; expected one of: {supported} (DD-111)"
        ) from exc

    adapter_spec = registry.adapter(adapter_name)
    available = {item.capability: item for item in adapter_spec.capabilities}
    results: list[CapabilityResultSpec] = []
    for requirement in sorted(
        requirements,
        key=lambda item: (item.capability.value, item.scope, item.rule_id),
    ):
        capability = available.get(requirement.capability)
        if capability is None:
            results.append(
                CapabilityResultSpec(
                    adapter=adapter_name,
                    capability=requirement.capability,
                    disposition=CapabilityDisposition.BLOCKING,
                    rule_id=requirement.rule_id,
                    scope=requirement.scope,
                    evidence=(f"registry-{registry.version}: capability absent",),
                    message="Required capability is not registered for this adapter.",
                )
            )
            continue

        if capability.support is CapabilitySupport.SUPPORTED:
            results.append(
                CapabilityResultSpec(
                    adapter=adapter_name,
                    capability=requirement.capability,
                    disposition=CapabilityDisposition.SUPPORTED,
                    rule_id=requirement.rule_id,
                    scope=requirement.scope,
                    evidence=capability.evidence,
                    message="Capability is explicitly supported by the adapter profile.",
                )
            )
            continue

        deviation = _matching_deviation(adapter_name, requirement, deviations, current_date)
        if deviation is not None and capability.allowed_deviation:
            results.append(
                CapabilityResultSpec(
                    adapter=adapter_name,
                    capability=requirement.capability,
                    disposition=CapabilityDisposition.DEVIATION,
                    rule_id=requirement.rule_id,
                    scope=requirement.scope,
                    evidence=capability.evidence + deviation.evidence,
                    deviation_ref=deviation.resource_uri,
                    message="Required behavior is covered by an approved scoped deviation.",
                )
            )
            continue

        results.append(
            CapabilityResultSpec(
                adapter=adapter_name,
                capability=requirement.capability,
                disposition=CapabilityDisposition.BLOCKING,
                rule_id=requirement.rule_id,
                scope=requirement.scope,
                evidence=capability.evidence,
                message=(
                    "Capability requires an approved scoped deviation."
                    if capability.support is CapabilitySupport.DEVIATION_REQUIRED
                    else "Capability is unsupported by this adapter."
                ),
            )
        )
    return tuple(results)
