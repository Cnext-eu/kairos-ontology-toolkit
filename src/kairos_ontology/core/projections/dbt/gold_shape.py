# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Pure Gold profile shaping against the materialized Silver registry."""

from __future__ import annotations

import re
from collections.abc import Callable

from ..uri_utils import camel_to_snake
from .gold_specs import (
    DimensionalGoldSpec,
    GoldCalendarRoleSpec,
    GoldCalendarSpec,
    GoldColumnSpec,
    GoldContractError,
    GoldMeasureSpec,
    GoldProductLogicalSpec,
    GoldRelationshipSpec,
    GoldSecurityBindingSpec,
    GoldSecurityKind,
    GoldSecuritySpec,
    GoldTableSpec,
)
from .policy_specs import (
    CanonicalTypeKind,
    DimensionExposure,
    DimensionVersionBinding,
    GoldProfileName,
    GoldTableRole,
    MeasureLifecycle,
    MedallionPolicySpec,
    ScdType,
)
from .specs import ForeignKeyPolicy, SilverModelSpec, SilverRegistry

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECURITY_BINDING = re.compile(
    r"^(?P<table>[A-Za-z_][A-Za-z0-9_]*)\."
    r"(?P<column>[A-Za-z_][A-Za-z0-9_]*)="
    r"(?P<role>[A-Za-z_][A-Za-z0-9_]*):(?P<kind>RLS|OLS)$"
)
_CALENDAR_ROLE = re.compile(
    r"^(?P<role>[A-Za-z_][A-Za-z0-9_]*)="
    r"(?P<table>[A-Za-z_][A-Za-z0-9_]*)\."
    r"(?P<column>[A-Za-z_][A-Za-z0-9_]*)$"
)
_DAX_REFERENCE = re.compile(r"\[([^\]]+)\]")


def _fail(
    code: str,
    message: str,
    *,
    rule_id: str,
    resource_uri: str = "",
) -> None:
    raise GoldContractError(
        code,
        message,
        rule_id=rule_id,
        resource_uri=resource_uri,
    )


def _local_name(uri: str) -> str:
    return re.split(r"[/#]", uri.rstrip("/#"))[-1]


def _primary_key(model: SilverModelSpec) -> str:
    priorities = (
        "surrogate-join-key",
        "integration-identity",
        "business-natural-key",
        "source-identity",
    )
    for role in priorities:
        for column in model.columns:
            if column.role == role:
                return column.name
    for column in model.columns:
        if column.nullable is False:
            return column.name
    return model.columns[0].name if model.columns else ""


def _columns(model: SilverModelSpec, resource_uri: str) -> tuple[GoldColumnSpec, ...]:
    result: list[GoldColumnSpec] = []
    for column in model.columns:
        if column.canonical_type is None or column.nullable is None:
            _fail(
                "gold.silver-column-contract-incomplete",
                (
                    f"{model.identity.model_name}.{column.name} lacks canonical type "
                    "or nullability in the actual Silver registry"
                ),
                rule_id="DD-112-silver-binding",
                resource_uri=resource_uri,
            )
        result.append(
            GoldColumnSpec(
                source_name=column.name,
                name=column.name,
                canonical_type=column.canonical_type,
                nullable=column.nullable,
                role=column.role,
                comment=column.description,
                provenance=column.provenance,
            )
        )
    if not result:
        _fail(
            "gold.empty-silver-model",
            f"Silver model {model.identity.model_name!r} has no materialized columns",
            rule_id="DD-112-silver-binding",
            resource_uri=resource_uri,
        )
    return tuple(result)


def _column_by_property(
    tables: tuple[GoldTableSpec, ...],
    dependency: str,
) -> tuple[str, str] | None:
    exact = [
        (table.name, column.name)
        for table in tables
        for column in table.columns
        if f"property:{dependency}" in column.provenance
    ]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        _fail(
            "measure.ambiguous-column-dependency",
            f"column dependency {dependency!r} resolves to multiple emitted columns",
            rule_id="DD-113-measure-dependencies",
            resource_uri=dependency,
        )
    if "." in dependency and not dependency.startswith(("http://", "https://", "urn:")):
        table_name, column_name = dependency.rsplit(".", 1)
        if any(
            table.name == table_name and any(column.name == column_name for column in table.columns)
            for table in tables
        ):
            return table_name, column_name
    local = camel_to_snake(_local_name(dependency))
    local_matches = [
        (table.name, column.name)
        for table in tables
        for column in table.columns
        if column.name == local
    ]
    return local_matches[0] if len(local_matches) == 1 else None


def _shape_measures(
    policy: MedallionPolicySpec,
    tables: tuple[GoldTableSpec, ...],
) -> tuple[GoldMeasureSpec, ...]:
    by_resource = {item.resource_uri: item for item in policy.gold.measures}
    shaped: dict[str, GoldMeasureSpec] = {}
    visiting: set[str] = set()

    def shape(resource_uri: str) -> GoldMeasureSpec:
        if resource_uri in shaped:
            return shaped[resource_uri]
        if resource_uri in visiting:
            _fail(
                "measure.dependency-cycle",
                f"measure dependency cycle contains {resource_uri!r}",
                rule_id="DD-113-measure-dependencies",
                resource_uri=resource_uri,
            )
        source = by_resource.get(resource_uri)
        if source is None:
            _fail(
                "measure.unknown-dependency",
                f"measure dependency {resource_uri!r} is not part of this Gold product",
                rule_id="DD-113-measure-dependencies",
                resource_uri=resource_uri,
            )
        visiting.add(resource_uri)
        measure_dependencies = tuple(shape(item) for item in source.dependencies.measures.value)
        column_dependencies: list[tuple[str, str]] = []
        for dependency in source.dependencies.columns.value:
            resolved = _column_by_property(tables, dependency)
            if resolved is None:
                _fail(
                    "measure.missing-column-dependency",
                    (
                        f"measure {source.measure_id.value!r} references unavailable "
                        f"Silver/Gold column {dependency!r}"
                    ),
                    rule_id="DD-113-measure-dependencies",
                    resource_uri=source.resource_uri,
                )
            column_dependencies.append(resolved)
        home_tables = {table_name for table_name, _ in column_dependencies} | {
            item.home_table for item in measure_dependencies if item.home_table
        }
        if len(home_tables) > 1:
            _fail(
                "measure.ambiguous-home-table",
                (
                    f"measure {source.measure_id.value!r} dependencies span multiple "
                    f"home tables: {tuple(sorted(home_tables))!r}"
                ),
                rule_id="DD-113-measure-dependencies",
                resource_uri=source.resource_uri,
            )
        home_table = next(iter(home_tables), "")
        expression = source.expression.value if source.expression is not None else ""
        if source.lifecycle.value is not MeasureLifecycle.INTENT:
            allowed = {column for _, column in column_dependencies}
            allowed.update(item.measure_id for item in measure_dependencies)
            allowed.update(_local_name(item.measure_id) for item in measure_dependencies)
            missing_dax = tuple(
                sorted(
                    {
                        reference
                        for reference in _DAX_REFERENCE.findall(expression)
                        if reference not in allowed
                    }
                )
            )
            if missing_dax:
                _fail(
                    "measure.unresolved-dax-reference",
                    (
                        f"measure {source.measure_id.value!r} has undeclared DAX "
                        f"references: {missing_dax!r}"
                    ),
                    rule_id="DD-113-measure-dependencies",
                    resource_uri=source.resource_uri,
                )
            if not home_table:
                _fail(
                    "measure.home-table-missing",
                    (
                        f"measure {source.measure_id.value!r} has no resolvable "
                        "emitted home table"
                    ),
                    rule_id="DD-113-measure-dependencies",
                    resource_uri=source.resource_uri,
                )
        result = GoldMeasureSpec(
            resource_uri=source.resource_uri,
            measure_id=source.measure_id.value,
            definition=source.definition.value,
            expression=expression,
            lifecycle=source.lifecycle.value,
            home_table=home_table,
            column_dependencies=tuple(column_dependencies),
            measure_dependencies=tuple(item.measure_id for item in measure_dependencies),
            data_type=source.data_type.value if source.data_type is not None else "",
            format_string=(source.format_string.value if source.format_string is not None else ""),
            folder=source.folder.value if source.folder is not None else "",
            owner_role=(source.owner_role.value if source.owner_role is not None else ""),
            tests=source.validation_tests.value,
            evidence=source.validation_evidence.value,
            emitted=source.lifecycle.value is not MeasureLifecycle.INTENT,
        )
        visiting.remove(resource_uri)
        shaped[resource_uri] = result
        return result

    for resource_uri in sorted(by_resource):
        shape(resource_uri)
    return tuple(sorted(shaped.values(), key=lambda item: item.measure_id))


def _table_aliases(tables: tuple[GoldTableSpec, ...]) -> dict[str, GoldTableSpec]:
    aliases: dict[str, GoldTableSpec] = {}
    for table in tables:
        for alias in {
            table.name,
            table.source_model,
            _local_name(table.resource_uri),
        }:
            existing = aliases.get(alias.casefold())
            if existing is not None and existing != table:
                continue
            aliases[alias.casefold()] = table
    return aliases


def _shape_calendar(
    policy: MedallionPolicySpec,
    tables: tuple[GoldTableSpec, ...],
) -> GoldCalendarSpec | None:
    source = policy.gold.calendar
    if source is None:
        return None
    aliases = _table_aliases(tables)
    roles: list[GoldCalendarRoleSpec] = []
    names: set[str] = set()
    for value in source.role_playing_dates.value:
        match = _CALENDAR_ROLE.fullmatch(value)
        if match is None:
            _fail(
                "calendar.invalid-role-binding",
                (f"rolePlayingDate {value!r} must use " "RoleName=GoldOrSilverTable.date_column"),
                rule_id="DD-113-calendar",
                resource_uri=source.resource_uri,
            )
        role_name = match.group("role")
        if role_name.casefold() in names:
            _fail(
                "calendar.duplicate-role",
                f"calendar role {role_name!r} is duplicated",
                rule_id="DD-113-calendar",
                resource_uri=source.resource_uri,
            )
        names.add(role_name.casefold())
        table = aliases.get(match.group("table").casefold())
        column_name = match.group("column")
        column = (
            next(
                (item for item in table.columns if item.name == column_name),
                None,
            )
            if table is not None
            else None
        )
        if column is None:
            _fail(
                "calendar.missing-role-column",
                f"calendar role {value!r} does not bind an emitted Gold column",
                rule_id="DD-113-calendar",
                resource_uri=source.resource_uri,
            )
        if column.canonical_type.kind not in {
            CanonicalTypeKind.DATE,
            CanonicalTypeKind.TIMESTAMP,
        }:
            _fail(
                "calendar.non-date-role-column",
                f"calendar role {value!r} must bind a date or timestamp column",
                rule_id="DD-113-calendar",
                resource_uri=source.resource_uri,
            )
        roles.append(GoldCalendarRoleSpec(role_name, table.name, column_name))
    return GoldCalendarSpec(
        resource_uri=source.resource_uri,
        start_date=source.start_date.value,
        end_date=source.end_date.value,
        fiscal_year_start_month=source.fiscal_year_start_month.value,
        week_pattern=source.week_pattern.value,
        locale=source.locale.value,
        holiday_source=source.holiday_source.value,
        time_zone=source.time_zone.value,
        period_closure=source.period_closure.value,
        roles=tuple(sorted(roles, key=lambda item: item.role_name.casefold())),
        approved=source.approved,
    )


def _shape_security(
    policy: MedallionPolicySpec,
    tables: tuple[GoldTableSpec, ...],
) -> GoldSecuritySpec | None:
    source = policy.gold.security
    if source is None:
        return None
    aliases = _table_aliases(tables)
    roles = frozenset(source.role_policies.value)
    bindings: list[GoldSecurityBindingSpec] = []
    for value in source.bindings.value:
        match = _SECURITY_BINDING.fullmatch(value)
        if match is None:
            _fail(
                "security.invalid-binding",
                (f"securityBinding {value!r} must use " "Table.column=Role:RLS|OLS"),
                rule_id="DD-113-security",
                resource_uri=source.resource_uri,
            )
        role = match.group("role")
        if role not in roles:
            _fail(
                "security.unknown-role",
                f"security binding references undeclared role {role!r}",
                rule_id="DD-113-security",
                resource_uri=source.resource_uri,
            )
        table = aliases.get(match.group("table").casefold())
        column_name = match.group("column")
        if table is None or not any(column.name == column_name for column in table.columns):
            _fail(
                "security.missing-column-binding",
                f"security binding {value!r} does not bind an emitted Gold column",
                rule_id="DD-113-security",
                resource_uri=source.resource_uri,
            )
        bindings.append(
            GoldSecurityBindingSpec(
                table_name=table.name,
                column_name=column_name,
                role_name=role,
                kind=GoldSecurityKind(match.group("kind")),
            )
        )
    return GoldSecuritySpec(
        resource_uri=source.resource_uri,
        entitlement_source=source.entitlement_source.value,
        identity_mapping=source.identity_mapping.value,
        roles=tuple(sorted(roles)),
        filter_direction=source.filter_direction.value,
        bindings=tuple(
            sorted(
                bindings,
                key=lambda item: (
                    item.role_name,
                    item.kind.value,
                    item.table_name,
                    item.column_name,
                ),
            )
        ),
        positive_tests=source.positive_tests.value,
        negative_tests=source.negative_tests.value,
        test_evidence=source.test_evidence.value,
        fail_closed=source.fail_closed.value,
    )


def _relationship_column(table: GoldTableSpec, property_uri: str, explicit: str) -> str:
    candidates = [
        column.name for column in table.columns if f"property:{property_uri}" in column.provenance
    ]
    if explicit and any(column.name == explicit for column in table.columns):
        candidates.append(explicit)
    candidates = list(dict.fromkeys(candidates))
    return candidates[0] if len(candidates) == 1 else ""


def _shape_relationships(
    tables: tuple[GoldTableSpec, ...],
    foreign_keys: ForeignKeyPolicy,
) -> tuple[GoldRelationshipSpec, ...]:
    by_resource = {table.resource_uri: table for table in tables}
    relationships: list[GoldRelationshipSpec] = []
    for descriptor in foreign_keys.descriptors:
        source = by_resource.get(descriptor.source_class)
        target = by_resource.get(descriptor.target_class)
        if source is None or target is None:
            continue
        column_name = _relationship_column(
            source,
            descriptor.property_uri,
            descriptor.silver_column_name or "",
        )
        if not column_name:
            continue
        if (
            source.version_binding is not None
            and source.version_binding is not DimensionVersionBinding.CURRENT
            and target.role is GoldTableRole.DIMENSION
            and target.dimension_exposure is DimensionExposure.CURRENT_ONLY
        ):
            _fail(
                "gold.incompatible-dimension-version",
                (
                    f"{source.name} uses {source.version_binding.value} but "
                    f"{target.name} exposes current rows only"
                ),
                rule_id="DD-112-dimension-version",
                resource_uri=descriptor.property_uri,
            )
        if not target.primary_key:
            _fail(
                "gold.relationship-target-key-missing",
                f"relationship target {target.name!r} has no materialized key",
                rule_id="DD-112-silver-binding",
                resource_uri=descriptor.property_uri,
            )
        relationships.append(
            GoldRelationshipSpec(
                name=camel_to_snake(_local_name(descriptor.property_uri)),
                source_table=source.name,
                source_column=column_name,
                target_table=target.name,
                target_column=target.primary_key,
                cardinality="many-to-one",
                version_binding=source.version_binding,
            )
        )
    for bridge in tables:
        if bridge.role is not GoldTableRole.BRIDGE:
            continue
        for endpoint_uri, column_name in bridge.bridge_endpoint_bindings:
            target = by_resource[endpoint_uri]
            relationships.append(
                GoldRelationshipSpec(
                    name=f"{bridge.name}_{target.name}",
                    source_table=bridge.name,
                    source_column=column_name,
                    target_table=target.name,
                    target_column=target.primary_key,
                    cardinality=(
                        bridge.bridge_cardinality.value
                        if bridge.bridge_cardinality is not None
                        else ""
                    ),
                    version_binding=None,
                )
            )
    return tuple(
        sorted(
            relationships,
            key=lambda item: (
                item.source_table,
                item.source_column,
                item.target_table,
            ),
        )
    )


def _shape_dimensional(
    policy: MedallionPolicySpec,
    registry: SilverRegistry,
    silver_models: tuple[SilverModelSpec, ...],
    foreign_keys: ForeignKeyPolicy,
    ontology_name: str,
    ontology_version: str,
) -> DimensionalGoldSpec:
    profile_value = policy.gold.profile
    if profile_value is None or policy.gold.schema is None:
        _fail(
            "gold.profile-missing",
            "Gold projection requires an explicit registered product profile and schema",
            rule_id="DD-112-profile",
        )
    profile = policy.gold_registry.get(profile_value.value)
    names = dict(registry.names)
    registry_columns = dict(registry.columns)
    versions = dict(registry.versions)
    models = {model.identity.model_name: model for model in silver_models}
    incremental = {item.resource_uri: item for item in policy.incremental}
    perspective_by_table = {
        resource_uri: tuple(
            perspective.name
            for perspective in policy.gold.perspectives
            if resource_uri in perspective.table_uris
        )
        for resource_uri in names
    }
    tables: list[GoldTableSpec] = []
    used_names: set[str] = set()
    for authored in policy.gold.tables:
        if not _IDENTIFIER.fullmatch(authored.table_name.value):
            _fail(
                "gold.invalid-table-name",
                f"invalid Gold table identifier {authored.table_name.value!r}",
                rule_id="DD-112-table-role",
                resource_uri=authored.resource_uri,
            )
        if authored.table_name.value.casefold() in used_names:
            _fail(
                "gold.duplicate-table-name",
                f"duplicate Gold table name {authored.table_name.value!r}",
                rule_id="DD-112-table-role",
                resource_uri=authored.resource_uri,
            )
        used_names.add(authored.table_name.value.casefold())
        actual_name = names.get(authored.resource_uri)
        if actual_name is None:
            _fail(
                "gold.unmaterialized-silver-source",
                (
                    f"Gold table {authored.table_name.value!r} has no actual "
                    "materialized Silver registry entry"
                ),
                rule_id="DD-112-silver-binding",
                resource_uri=authored.resource_uri,
            )
        if authored.source_model.value != actual_name:
            _fail(
                "gold.source-model-drift",
                (
                    f"authored source model {authored.source_model.value!r} does not "
                    f"match Silver registry model {actual_name!r}"
                ),
                rule_id="DD-112-silver-binding",
                resource_uri=authored.resource_uri,
            )
        actual_version = versions.get(actual_name, ontology_version)
        if not actual_version or authored.source_version.value != actual_version:
            _fail(
                "gold.source-version-drift",
                (
                    f"authored source version {authored.source_version.value!r} does "
                    f"not match Silver registry version {actual_version!r}"
                ),
                rule_id="DD-112-silver-binding",
                resource_uri=authored.resource_uri,
            )
        model = models.get(actual_name)
        if model is None:
            _fail(
                "gold.silver-model-plan-missing",
                f"Silver registry model {actual_name!r} has no logical materialization",
                rule_id="DD-112-silver-binding",
                resource_uri=authored.resource_uri,
            )
        actual_columns = frozenset(column.name for column in model.columns)
        if actual_columns != registry_columns.get(actual_name, frozenset()):
            _fail(
                "gold.silver-registry-drift",
                f"Silver registry columns drifted for model {actual_name!r}",
                rule_id="DD-110-parity",
                resource_uri=authored.resource_uri,
            )
        authority = model.authority
        history = authority.history if authority is not None else None
        scd_type = history.scd_type.value.value if history is not None else ""
        if (
            authored.dimension_exposure
            and authored.dimension_exposure.value
            in {DimensionExposure.HISTORY_ONLY, DimensionExposure.DUAL}
            and history is not None
            and history.scd_type.value is not ScdType.TYPE_2
        ):
            _fail(
                "gold.dimension-history-unavailable",
                (
                    f"dimension {authored.table_name.value!r} requests history "
                    "exposure but its Silver authority is not SCD2"
                ),
                rule_id="DD-112-dimension",
                resource_uri=authored.resource_uri,
            )
        unique_key: tuple[str, ...] = ()
        updated_at = ""
        if authored.role.value is GoldTableRole.FACT:
            runtime = incremental.get(authored.incremental_policy_ref or "")
            if runtime is not None:
                unique_key = runtime.merge_identity.value
                updated_at = runtime.ordering.source_updated_at.value
                missing_runtime_columns = tuple(
                    value for value in (*unique_key, updated_at) if value not in actual_columns
                )
                if missing_runtime_columns:
                    _fail(
                        "gold.fact-runtime-column-missing",
                        (
                            f"fact {authored.table_name.value!r} runtime policy references "
                            f"unmaterialized Silver columns {missing_runtime_columns!r}"
                        ),
                        rule_id="DD-112-fact",
                        resource_uri=authored.resource_uri,
                    )
        weight = authored.bridge_weight_column.value if authored.bridge_weight_column else ""
        if weight and weight not in actual_columns:
            _fail(
                "gold.bridge-weight-column-missing",
                f"bridge weight column {weight!r} is not materialized by Silver",
                rule_id="DD-112-bridge",
                resource_uri=authored.resource_uri,
            )
        endpoint_bindings: list[tuple[str, str]] = []
        if authored.bridge_endpoint_bindings is not None:
            endpoints = authored.bridge_endpoints.value if authored.bridge_endpoints else ()
            for value in authored.bridge_endpoint_bindings.value:
                if "=" not in value:
                    _fail(
                        "gold.invalid-bridge-endpoint-binding",
                        (
                            f"bridge endpoint binding {value!r} must use "
                            "EndpointResource=column_name"
                        ),
                        rule_id="DD-112-bridge",
                        resource_uri=authored.resource_uri,
                    )
                endpoint_name, column_name = value.rsplit("=", 1)
                matching = tuple(
                    endpoint
                    for endpoint in endpoints
                    if endpoint == endpoint_name or _local_name(endpoint) == endpoint_name
                )
                if len(matching) != 1 or column_name not in actual_columns:
                    _fail(
                        "gold.invalid-bridge-endpoint-binding",
                        (
                            f"bridge endpoint binding {value!r} does not resolve "
                            "one endpoint and one emitted Silver column"
                        ),
                        rule_id="DD-112-bridge",
                        resource_uri=authored.resource_uri,
                    )
                endpoint_bindings.append((matching[0], column_name))
            if {item[0] for item in endpoint_bindings} != set(endpoints):
                _fail(
                    "gold.incomplete-bridge-endpoint-bindings",
                    "each bridge endpoint requires exactly one column binding",
                    rule_id="DD-112-bridge",
                    resource_uri=authored.resource_uri,
                )
        tables.append(
            GoldTableSpec(
                resource_uri=authored.resource_uri,
                name=authored.table_name.value,
                schema_name=policy.gold.schema.value,
                role=authored.role.value,
                source_model=actual_name,
                source_version=actual_version,
                columns=_columns(model, authored.resource_uri),
                primary_key=_primary_key(model),
                fact_grain=(authored.fact_grain.value if authored.fact_grain is not None else ""),
                fact_type=(authored.fact_type.value if authored.fact_type is not None else None),
                version_binding=(
                    authored.version_binding.value if authored.version_binding is not None else None
                ),
                correction=(authored.correction.value if authored.correction is not None else None),
                late_arrival=(
                    authored.late_arrival.value if authored.late_arrival is not None else None
                ),
                incremental_policy_ref=authored.incremental_policy_ref or "",
                incremental_unique_key=unique_key,
                incremental_updated_at=updated_at,
                dimension_exposure=(
                    authored.dimension_exposure.value
                    if authored.dimension_exposure is not None
                    else None
                ),
                silver_scd_type=scd_type,
                bridge_grain=(
                    authored.bridge_grain.value if authored.bridge_grain is not None else ""
                ),
                bridge_endpoints=(
                    authored.bridge_endpoints.value
                    if authored.bridge_endpoints is not None
                    else None
                ),
                bridge_endpoint_bindings=tuple(endpoint_bindings),
                bridge_cardinality=(
                    authored.bridge_cardinality.value
                    if authored.bridge_cardinality is not None
                    else None
                ),
                bridge_weight_column=weight,
                bridge_allocation=(
                    authored.bridge_allocation.value
                    if authored.bridge_allocation is not None
                    else ""
                ),
                perspectives=tuple(sorted(perspective_by_table.get(authored.resource_uri, ()))),
            )
        )
    ordered = tuple(sorted(tables, key=lambda item: (item.role.value, item.name)))
    included = {table.resource_uri for table in ordered}
    for table in ordered:
        if table.role is GoldTableRole.BRIDGE and (
            table.bridge_endpoints is None or not set(table.bridge_endpoints).issubset(included)
        ):
            _fail(
                "gold.bridge-endpoint-not-materialized",
                f"bridge {table.name!r} endpoints must both be explicit Gold tables",
                rule_id="DD-112-bridge",
                resource_uri=table.resource_uri,
            )
    return DimensionalGoldSpec(
        profile=profile.name,
        profile_version=profile.version,
        ontology_name=ontology_name,
        ontology_version=ontology_version,
        schema_name=policy.gold.schema.value,
        adapter=policy.target_adapter.value.value,
        tables=ordered,
        relationships=_shape_relationships(ordered, foreign_keys),
        measures=_shape_measures(policy, ordered),
        calendar=_shape_calendar(policy, ordered),
        security=_shape_security(policy, ordered),
        perspectives=tuple(
            (
                item.name,
                tuple(
                    sorted(table.name for table in ordered if table.resource_uri in item.table_uris)
                ),
            )
            for item in policy.gold.perspectives
        ),
        silver_registry_names=registry.names,
        silver_registry_columns=registry.columns,
    )


GoldProfileBuilder = Callable[
    [
        MedallionPolicySpec,
        SilverRegistry,
        tuple[SilverModelSpec, ...],
        ForeignKeyPolicy,
        str,
        str,
    ],
    GoldProductLogicalSpec,
]

_PROFILE_BUILDERS: dict[GoldProfileName, GoldProfileBuilder] = {
    GoldProfileName.DIMENSIONAL_POWERBI_V1: _shape_dimensional,
}


def shape_gold_product(
    policy: MedallionPolicySpec,
    registry: SilverRegistry,
    silver_models: tuple[SilverModelSpec, ...],
    foreign_keys: ForeignKeyPolicy,
    *,
    ontology_name: str,
    ontology_version: str,
    required: bool = False,
) -> GoldProductLogicalSpec | None:
    """Dispatch one exact registered profile; no generic dimensional fallback exists."""
    profile = policy.gold.profile
    if profile is None:
        if required:
            _fail(
                "gold.profile-missing",
                "Gold projection requires goldProductProfile",
                rule_id="DD-112-profile",
            )
        return None
    registered = policy.gold_registry.get(profile.value)
    builder = _PROFILE_BUILDERS.get(registered.name)
    if builder is None:
        _fail(
            "gold.profile-not-implemented",
            f"registered Gold profile {registered.name.value!r} has no implementation",
            rule_id="DD-112-profile",
        )
    return builder(
        policy,
        registry,
        silver_models,
        foreign_keys,
        ontology_name,
        ontology_version,
    )
