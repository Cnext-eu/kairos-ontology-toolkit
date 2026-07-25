# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Graph-free renderers for the dimensional Power BI Gold profile."""

from __future__ import annotations

import hashlib
import json

import yaml

from .gold_specs import (
    DimensionalGoldSpec,
    GoldCalendarSpec,
    GoldMeasureSpec,
    GoldPhysicalPlan,
    GoldPhysicalTablePlan,
    GoldSecurityKind,
    GoldTableSpec,
)
def _json(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _guid(seed: str) -> str:
    value = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return (
        f"{value[:8]}-{value[8:12]}-{value[12:16]}-"
        f"{value[16:20]}-{value[20:32]}"
    )


def _quoted(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _tmdl_text(value: str) -> str:
    return value.replace('"', '""').replace("\r", " ").replace("\n", " ")


def _dbt_table_sql(table: GoldTableSpec, physical: GoldPhysicalTablePlan) -> str:
    config = [
        f"materialized={_quoted(physical.materialization)}",
        f"schema={_quoted(table.schema_name)}",
    ]
    if physical.unique_key:
        keys = ", ".join(_quoted(item) for item in physical.unique_key)
        config.append(f"unique_key=[{keys}]")
        config.append("incremental_strategy='merge'")
    lines = [
        "{{ config(",
        "    " + ",\n    ".join(config),
        ") }}",
        "",
        f"-- Gold profile: dimensional-powerbi-v1/{table.source_version}",
        f"-- Explicit role: {table.role.value}",
        f"-- Actual Silver source: {table.source_model}",
    ]
    if table.fact_grain:
        lines.append(f"-- Fact grain: {table.fact_grain}")
        lines.append(f"-- Fact type: {table.fact_type.value if table.fact_type else ''}")
    if table.bridge_grain:
        lines.append(f"-- Bridge grain: {table.bridge_grain}")
        lines.append(f"-- Allocation: {table.bridge_allocation}")
    lines.extend(
        [
            "",
            "with silver_source as (",
            f"    select * from {{{{ ref('{table.source_model}') }}}}",
            ")",
            "",
            "select",
        ]
    )
    for index, column in enumerate(table.columns):
        suffix = "," if index < len(table.columns) - 1 else ""
        lines.append(f"    {column.source_name} as {column.name}{suffix}")
    lines.append("from silver_source")
    conditions: list[str] = []
    if physical.current_filter:
        conditions.append(physical.current_filter)
    if physical.materialization == "incremental" and physical.updated_at:
        operator = "where" if not conditions else "and"
        conditions.append(
            "{% if is_incremental() %}\n"
            f"{operator} {physical.updated_at} >= (\n"
            f"    select coalesce(max({physical.updated_at}), "
            "cast('1900-01-01' as timestamp)) from {{ this }}\n"
            ")\n"
            "{% endif %}"
        )
    if conditions:
        first = conditions[0]
        if first.startswith("{%"):
            lines.append(first)
        else:
            lines.append(f"where {first}")
            lines.extend(conditions[1:])
    return "\n".join(lines) + "\n"


def _dbt_current_sql(table: GoldTableSpec, physical: GoldPhysicalTablePlan) -> str:
    return (
        "{{ config(materialized='view', schema='"
        + table.schema_name
        + "') }}\n\n"
        + f"select * from {{{{ ref('{table.name}') }}}}\n"
        + "where is_current = 1\n"
    )


def _dbt_calendar_sql(calendar: GoldCalendarSpec) -> str:
    start = _quoted(calendar.start_date)
    end = _quoted(calendar.end_date)
    return "\n".join(
        [
            "{{ config(materialized='table', schema='gold_shared') }}",
            "",
            "-- Approved governed calendar; no date bounds are inferred.",
            "with date_spine as (",
            "    {{ dbt_utils.date_spine(",
            "        datepart='day',",
            f"        start_date=\"cast({start} as date)\",",
            f"        end_date=\"dateadd(day, 1, cast({end} as date))\"",
            "    ) }}",
            ")",
            "select",
            "    cast(replace(cast(date_day as varchar), '-', '') as bigint) as date_key,",
            "    cast(date_day as date) as full_date,",
            "    extract(year from date_day) as year_number,",
            "    extract(month from date_day) as month_number,",
            "    extract(day from date_day) as day_of_month,",
            f"    {calendar.fiscal_year_start_month} as fiscal_year_start_month,",
            f"    {_quoted(calendar.week_pattern)} as week_pattern,",
            f"    {_quoted(calendar.locale)} as calendar_locale,",
            f"    {_quoted(calendar.time_zone)} as calendar_time_zone,",
            f"    {_quoted(calendar.period_closure)} as period_closure_policy,",
            (
                "    false as is_holiday"
                if calendar.holiday_source.startswith("none-")
                else "    cast(null as boolean) as is_holiday"
            ),
            "from date_spine",
            "",
        ]
    )


def _schema_yaml(
    spec: DimensionalGoldSpec,
    physical: GoldPhysicalPlan,
) -> str:
    physical_by_name = {item.name: item for item in physical.tables}
    models: list[dict] = []
    for table in spec.tables:
        plan = physical_by_name[table.name]
        columns = []
        for column in plan.columns:
            tests: list[str] = []
            if not column.nullable:
                tests.append("not_null")
            if column.name == plan.primary_key:
                tests.append("unique")
            columns.append(
                {
                    "name": column.name,
                    "description": column.comment or column.name,
                    "data_type": column.physical_type,
                    "tests": tests,
                }
            )
        models.append(
            {
                "name": table.name,
                "description": (
                    f"{table.role.value} product table sourced from "
                    f"{table.source_model}@{table.source_version}"
                ),
                "meta": {
                    "gold_profile": spec.profile.value,
                    "gold_profile_version": spec.profile_version,
                    "table_role": table.role.value,
                    "source_model": table.source_model,
                    "source_version": table.source_version,
                },
                "columns": columns,
            }
        )
    return yaml.safe_dump(
        {"version": 2, "models": models},
        sort_keys=False,
        allow_unicode=True,
    )


def render_gold_dbt_artifacts(
    spec: DimensionalGoldSpec,
    physical: GoldPhysicalPlan,
) -> dict[str, str]:
    """Render governed dimensional dbt models from typed Gold plans."""
    physical_by_name = {item.name: item for item in physical.tables}
    artifacts: dict[str, str] = {}
    for table in spec.tables:
        plan = physical_by_name[table.name]
        path = f"models/gold/{spec.ontology_name}/{table.name}.sql"
        artifacts[path] = _dbt_table_sql(table, plan)
        if plan.dual_current_name:
            artifacts[
                f"models/gold/{spec.ontology_name}/{plan.dual_current_name}.sql"
            ] = _dbt_current_sql(table, plan)
    if spec.calendar is not None and spec.calendar.approved:
        artifacts["models/gold/shared/dim_date.sql"] = _dbt_calendar_sql(spec.calendar)
        artifacts["models/gold/shared/_shared__gold_models.yml"] = yaml.safe_dump(
            {
                "version": 2,
                "models": [
                    {
                        "name": "dim_date",
                        "description": "Approved governed calendar dimension.",
                        "meta": {
                            "calendar_profile": spec.calendar.resource_uri,
                            "calendar_approved": True,
                            "calendar_start": spec.calendar.start_date,
                            "calendar_end": spec.calendar.end_date,
                        },
                        "columns": [
                            {
                                "name": "date_key",
                                "description": "YYYYMMDD date key.",
                                "tests": ["not_null", "unique"],
                            },
                            {
                                "name": "full_date",
                                "description": "Calendar date.",
                                "tests": ["not_null", "unique"],
                            },
                        ],
                    }
                ],
            },
            sort_keys=False,
            allow_unicode=True,
        )
    artifacts[physical.dbt_schema_artifact_path] = _schema_yaml(spec, physical)
    return dict(sorted(artifacts.items()))


def _ddl(
    spec: DimensionalGoldSpec,
    physical: GoldPhysicalPlan,
) -> str:
    table_by_name = {item.name: item for item in spec.tables}
    lines = [
        f"-- Gold data product: {spec.profile.value}/{spec.profile_version}",
        f"-- Adapter: {physical.adapter}/{physical.adapter_version}",
        "-- Roles, grains, and source bindings are authored; none are inferred.",
        f"CREATE SCHEMA IF NOT EXISTS {spec.schema_name};",
        "",
    ]
    for table in physical.tables:
        logical = table_by_name[table.name]
        lines.extend(
            [
                f"-- {logical.role.value.upper()}: {logical.name}",
                f"-- Silver: {logical.source_model}@{logical.source_version}",
            ]
        )
        if logical.fact_grain:
            lines.append(f"-- Grain: {logical.fact_grain}")
            lines.append(f"-- Fact type: {logical.fact_type.value}")
        if logical.bridge_grain:
            lines.append(f"-- Grain: {logical.bridge_grain}")
            lines.append(f"-- Allocation: {logical.bridge_allocation}")
        lines.append(f"CREATE TABLE {table.schema_name}.{table.name} (")
        for index, column in enumerate(table.columns):
            suffix = "," if index < len(table.columns) - 1 else ""
            nullable = "NULL" if column.nullable else "NOT NULL"
            lines.append(
                f"    {column.name} {column.physical_type} {nullable}{suffix}"
            )
        close = ") USING DELTA;" if physical.adapter == "databricks" else ");"
        lines.extend([close, ""])
        if table.dual_current_name:
            lines.extend(
                [
                    (
                        f"CREATE VIEW {table.schema_name}.{table.dual_current_name} "
                        f"AS SELECT * FROM {table.schema_name}.{table.name}"
                    ),
                    "WHERE is_current = 1;",
                    "",
                ]
            )
    if spec.calendar is not None and spec.calendar.approved:
        text_type = "STRING" if physical.adapter == "databricks" else "VARCHAR(128)"
        boolean_type = "BOOLEAN" if physical.adapter == "databricks" else "BIT"
        calendar_close = (
            ") USING DELTA;"
            if physical.adapter == "databricks"
            else ");"
        )
        lines.extend(
            [
                "-- Approved calendar profile; population is generated by dbt.",
                "CREATE TABLE gold_shared.dim_date (",
                "    date_key BIGINT NOT NULL,",
                "    full_date DATE NOT NULL,",
                "    year_number INT NOT NULL,",
                "    month_number INT NOT NULL,",
                "    day_of_month INT NOT NULL,",
                "    fiscal_year_start_month INT NOT NULL,",
                f"    week_pattern {text_type} NOT NULL,",
                f"    calendar_locale {text_type} NOT NULL,",
                f"    calendar_time_zone {text_type} NOT NULL,",
                f"    period_closure_policy {text_type} NOT NULL,",
                f"    is_holiday {boolean_type} NULL",
                calendar_close,
                "",
            ]
        )
    return "\n".join(lines)


def _erd(spec: DimensionalGoldSpec, physical: GoldPhysicalPlan) -> str:
    physical_by_name = {item.name: item for item in physical.tables}
    lines = [
        "erDiagram",
        (
            f"    %% Gold product {spec.profile.value}/{spec.profile_version}; "
            f"adapter={physical.adapter}"
        ),
    ]
    for table in spec.tables:
        plan = physical_by_name[table.name]
        lines.append(f"    {table.name.upper()} {{")
        for column in plan.columns:
            marker = " PK" if column.name == plan.primary_key else ""
            lines.append(f"        {column.physical_type} {column.name}{marker}")
        lines.append("    }")
    if spec.calendar is not None and spec.calendar.approved:
        lines.extend(
            [
                "    DIM_DATE {",
                "        BIGINT date_key PK",
                "        DATE full_date",
                "    }",
            ]
        )
    for relationship in spec.relationships:
        lines.append(
            f"    {relationship.target_table.upper()} ||--o{{ "
            f"{relationship.source_table.upper()} : "
            f'"{relationship.name}"'
        )
    if spec.calendar is not None and spec.calendar.approved:
        for role in spec.calendar.roles:
            lines.append(
                f'    DIM_DATE ||--o{{ {role.table_name.upper()} : "{role.role_name}"'
            )
    return "\n".join(lines) + "\n"


def _platform(display_name: str) -> str:
    return _json(
        {
            "$schema": (
                "https://developer.microsoft.com/json-schemas/fabric/"
                "gitIntegration/platformProperties/2.0.0/schema.json"
            ),
            "config": {
                "logicalId": "00000000-0000-0000-0000-000000000000",
                "version": "2.0",
            },
            "metadata": {"displayName": display_name, "type": "SemanticModel"},
        }
    )


def _model_tmdl(spec: DimensionalGoldSpec, physical: GoldPhysicalPlan) -> str:
    locale = (
        spec.calendar.locale
        if spec.calendar is not None and spec.calendar.approved
        else "en-US"
    )
    time_enabled = int(spec.calendar is not None and spec.calendar.approved)
    return "\n".join(
        [
            "model Model",
            f"\tculture: {locale}",
            "\tdataAccessOptions",
            "\t\tlegacyRedirects",
            "\t\treturnErrorValuesAsNull",
            "",
            f'\tannotation Kairos_GoldProfile = "{spec.profile.value}"',
            f'\tannotation Kairos_GoldProfileVersion = "{spec.profile_version}"',
            f'\tannotation Kairos_Adapter = "{physical.adapter}"',
            f"\tannotation __PBI_TimeIntelligenceEnabled = {time_enabled}",
            "",
        ]
    )


def _partition(
    table_name: str,
    schema_name: str,
    physical: GoldPhysicalPlan,
) -> list[str]:
    if physical.semantic_mode == "directLake":
        return [
            f"\tpartition {table_name} = entity",
            "\t\tmode: directLake",
            "\t\tsource",
            f'\t\t\tentityName: "{schema_name}.{table_name}"',
            f'\t\t\tschemaName: "{schema_name}"',
            "",
        ]
    return [
        f"\tpartition {table_name} = m",
        "\t\tmode: directQuery",
        "\t\tsource =",
        "\t\t\tlet",
        (
            "\t\t\t\tSource = Databricks.Catalogs("
            '"{{DATABRICKS_SERVER_HOSTNAME}}", "{{DATABRICKS_HTTP_PATH}}")'
        ),
        f'\t\t\tin Source{{[Name="{schema_name}.{table_name}"]}}[Data]',
        "",
    ]


def _table_tmdl(
    table: GoldTableSpec,
    physical: GoldPhysicalTablePlan,
    product: GoldPhysicalPlan,
    measures: tuple[GoldMeasureSpec, ...],
) -> str:
    lines = [
        f"table {table.name}",
        f"\tlineageTag: {_guid(table.name)}",
        f'\tannotation Kairos_TableRole = "{table.role.value}"',
        f'\tannotation Kairos_SilverBinding = "{table.source_model}@{table.source_version}"',
        "",
    ]
    for column in physical.columns:
        lines.extend(
            [
                f"\tcolumn {column.name}",
                f"\t\tdataType: {column.tmdl_type}",
                f"\t\tlineageTag: {_guid(f'{table.name}.{column.name}')}",
                f"\t\tsourceColumn: {column.name}",
                "\t\tsummarizeBy: none",
                "",
            ]
        )
    for measure in measures:
        lines.extend(
            [
                f"\tmeasure '{measure.measure_id}' = {measure.expression}",
                f"\t\tformatString: {measure.format_string}",
                f"\t\tdisplayFolder: {measure.folder}",
                f"\t\tlineageTag: {_guid(f'{table.name}.{measure.measure_id}')}",
                f'\t\tdescription: "{_tmdl_text(measure.definition)}"',
                f'\t\tannotation Kairos_Lifecycle = "{measure.lifecycle.value}"',
                "\t\tannotation Kairos_DataValidatedByProjection = false",
                "",
            ]
        )
    lines.extend(_partition(table.name, table.schema_name, product))
    return "\n".join(lines)


def _date_tmdl(calendar: GoldCalendarSpec, product: GoldPhysicalPlan) -> str:
    lines = [
        "table dim_date",
        f"\tlineageTag: {_guid('dim_date')}",
        "\tdataCategory: Time",
        f'\tannotation Kairos_CalendarApproval = "{"approved" if calendar.approved else "draft"}"',
        f'\tannotation Kairos_CalendarBounds = "{calendar.start_date}/{calendar.end_date}"',
        "",
        "\tcolumn date_key",
        "\t\tdataType: Int64",
        "\t\tisKey",
        "\t\tsourceColumn: date_key",
        "",
        "\tcolumn full_date",
        "\t\tdataType: DateTime",
        "\t\tsourceColumn: full_date",
        "",
    ]
    lines.extend(_partition("dim_date", "gold_shared", product))
    return "\n".join(lines)


def _relationships_tmdl(spec: DimensionalGoldSpec) -> str:
    lines: list[str] = []
    for relationship in spec.relationships:
        lines.extend(
            [
                f"relationship {_guid(relationship.name + relationship.source_table)}",
                (
                    f"\tfromColumn: {relationship.source_table}."
                    f"{relationship.source_column}"
                ),
                (
                    f"\ttoColumn: {relationship.target_table}."
                    f"{relationship.target_column}"
                ),
                "",
            ]
        )
    if spec.calendar is not None and spec.calendar.approved:
        for role in spec.calendar.roles:
            lines.extend(
                [
                    f"relationship {_guid('calendar.' + role.role_name)}",
                    f"\tfromColumn: {role.table_name}.{role.column_name}",
                    "\ttoColumn: dim_date.full_date",
                    "",
                ]
            )
    return "\n".join(lines)


def _security_tmdl(spec: DimensionalGoldSpec) -> str:
    security = spec.security
    if security is None:
        return ""
    lines: list[str] = []
    for role in security.roles:
        lines.extend(
            [
                f"role '{role}'",
                "\tmodelPermission: read",
                f'\tannotation Kairos_EntitlementSource = "{security.entitlement_source}"',
                f'\tannotation Kairos_IdentityMapping = "{security.identity_mapping}"',
                f'\tannotation Kairos_FilterDirection = "{security.filter_direction}"',
                "",
            ]
        )
        for binding in security.bindings:
            if binding.role_name != role:
                continue
            if binding.kind is GoldSecurityKind.RLS:
                lines.extend(
                    [
                        f"\ttablePermission {binding.table_name}",
                        "\t\tfilterExpression: FALSE()",
                        "",
                    ]
                )
            else:
                lines.extend(
                    [
                        (
                            f"\tcolumnPermission {binding.table_name}."
                            f"{binding.column_name}"
                        ),
                        "\t\tmetadataPermission: none",
                        "",
                    ]
                )
    return "\n".join(lines)


def _perspectives_tmdl(spec: DimensionalGoldSpec) -> str:
    lines: list[str] = []
    for name, tables in spec.perspectives:
        lines.extend(
            [
                f"perspective '{name}'",
                "\tannotation Kairos_SecurityBoundary = false",
                "",
            ]
        )
        for table in tables:
            lines.extend([f"\tperspectiveTable {table}", ""])
    return "\n".join(lines)


def _time_intelligence_tmdl(calendar: GoldCalendarSpec) -> str:
    return "\n".join(
        [
            "table 'Time Intelligence'",
            f"\tlineageTag: {_guid('time-intelligence')}",
            '\tannotation Kairos_CalendarProfile = "approved"',
            "",
            "\tcalculationGroup",
            "\t\tcalculationItem Current = SELECTEDMEASURE()",
            (
                "\t\tcalculationItem YTD = CALCULATE("
                "SELECTEDMEASURE(), DATESYTD('dim_date'[full_date]))"
            ),
            (
                "\t\tcalculationItem QTD = CALCULATE("
                "SELECTEDMEASURE(), DATESQTD('dim_date'[full_date]))"
            ),
            (
                "\t\tcalculationItem MTD = CALCULATE("
                "SELECTEDMEASURE(), DATESMTD('dim_date'[full_date]))"
            ),
            "",
        ]
    )


def _dax(spec: DimensionalGoldSpec) -> str:
    emitted = tuple(item for item in spec.measures if item.emitted)
    if not emitted:
        return ""
    lines = [
        f"// Gold measures: {spec.profile.value}/{spec.profile_version}",
        "// Lifecycle is authored governance; syntax rendering is not data validation.",
        "",
    ]
    for measure in emitted:
        lines.extend(
            [
                f"// Lifecycle: {measure.lifecycle.value}",
                f"// Home table: {measure.home_table}",
                f"[{measure.measure_id}] = {measure.expression}",
                f"// Format: {measure.format_string}",
                "",
            ]
        )
    return "\n".join(lines)


def gold_product_report(
    spec: DimensionalGoldSpec,
    physical: GoldPhysicalPlan,
    *,
    silver_parity: dict | None = None,
) -> dict:
    return {
        "schema_version": "1.0",
        "profile": {
            "name": spec.profile.value,
            "version": spec.profile_version,
        },
        "adapter": {
            "name": physical.adapter,
            "version": physical.adapter_version,
            "semantic_mode": physical.semantic_mode,
            "approved_deviations": list(physical.approved_deviations),
        },
        "silver_authority": {
            "registry_names": dict(spec.silver_registry_names),
            "registry_columns": {
                name: sorted(columns)
                for name, columns in spec.silver_registry_columns
            },
            "parity": silver_parity or {"status": "not-evaluated"},
        },
        "tables": [
            {
                "name": table.name,
                "role": table.role.value,
                "source_model": table.source_model,
                "source_version": table.source_version,
                "fact_grain": table.fact_grain or None,
                "fact_type": table.fact_type.value if table.fact_type else None,
                "incremental_policy": table.incremental_policy_ref or None,
                "correction_policy": (
                    table.correction.value if table.correction is not None else None
                ),
                "late_arrival_policy": (
                    table.late_arrival.value
                    if table.late_arrival is not None
                    else None
                ),
                "dimension_exposure": (
                    table.dimension_exposure.value
                    if table.dimension_exposure is not None
                    else None
                ),
                "version_binding": (
                    table.version_binding.value
                    if table.version_binding is not None
                    else None
                ),
                "bridge_grain": table.bridge_grain or None,
                "bridge_endpoints": list(table.bridge_endpoints or ()),
                "bridge_endpoint_bindings": [
                    {"endpoint": endpoint, "column": column}
                    for endpoint, column in table.bridge_endpoint_bindings
                ],
                "bridge_cardinality": (
                    table.bridge_cardinality.value
                    if table.bridge_cardinality is not None
                    else None
                ),
                "bridge_weight_column": table.bridge_weight_column or None,
                "bridge_allocation": table.bridge_allocation or None,
                "columns": [column.name for column in table.columns],
            }
            for table in spec.tables
        ],
        "measures": [
            {
                "id": measure.measure_id,
                "lifecycle": measure.lifecycle.value,
                "emitted": measure.emitted,
                "home_table": measure.home_table or None,
                "column_dependencies": [
                    f"{table}.{column}"
                    for table, column in measure.column_dependencies
                ],
                "measure_dependencies": list(measure.measure_dependencies),
                "data_type": measure.data_type or None,
                "format_string": measure.format_string or None,
                "folder": measure.folder or None,
                "owner_role": measure.owner_role or None,
                "tests": list(measure.tests),
                "evidence": list(measure.evidence),
                "data_validated_by_projection": False,
            }
            for measure in spec.measures
        ],
        "calendar": (
            {
                "approved": spec.calendar.approved,
                "bounds": [spec.calendar.start_date, spec.calendar.end_date],
                "fiscal_year_start_month": spec.calendar.fiscal_year_start_month,
                "week_pattern": spec.calendar.week_pattern,
                "locale": spec.calendar.locale,
                "holiday_source": spec.calendar.holiday_source,
                "time_zone": spec.calendar.time_zone,
                "period_closure": spec.calendar.period_closure,
                "roles": [
                    {
                        "name": role.role_name,
                        "binding": f"{role.table_name}.{role.column_name}",
                    }
                    for role in spec.calendar.roles
                ],
            }
            if spec.calendar is not None
            else None
        ),
        "security": (
            {
                "fail_closed": spec.security.fail_closed,
                "entitlement_source": spec.security.entitlement_source,
                "identity_mapping": spec.security.identity_mapping,
                "roles": list(spec.security.roles),
                "filter_direction": spec.security.filter_direction,
                "bindings": [
                    {
                        "table": binding.table_name,
                        "column": binding.column_name,
                        "role": binding.role_name,
                        "kind": binding.kind.value,
                    }
                    for binding in spec.security.bindings
                ],
                "positive_tests": list(spec.security.positive_tests),
                "negative_tests": list(spec.security.negative_tests),
                "test_evidence": list(spec.security.test_evidence),
                "runtime_enforcement_claimed": False,
            }
            if spec.security is not None
            else None
        ),
        "perspectives": [
            {
                "name": name,
                "tables": list(tables),
                "security_boundary": False,
            }
            for name, tables in spec.perspectives
        ],
        "compile_status": "not-evaluated",
        "deployment_status": "not-evaluated",
    }


def render_powerbi_artifacts(
    spec: DimensionalGoldSpec,
    physical: GoldPhysicalPlan,
    *,
    silver_parity: dict | None = None,
) -> dict[str, str]:
    """Render DDL, dbt, TMDL, DAX, ERD, and report artifacts."""
    domain = spec.ontology_name
    model_name = "".join(
        item.capitalize()
        for item in domain.replace("-", "_").split("_")
    )
    prefix = f"{domain}/{model_name}.SemanticModel"
    definition = f"{prefix}/definition"
    physical_by_name = {item.name: item for item in physical.tables}
    artifacts: dict[str, str] = {
        physical.ddl_artifact_path: _ddl(spec, physical),
        physical.erd_artifact_path: _erd(spec, physical),
        physical.report_artifact_path: _json(
            gold_product_report(
                spec,
                physical,
                silver_parity=silver_parity,
            )
        ),
        f"{prefix}/.platform": _platform(model_name),
        f"{prefix}/definition.pbism": _json({"version": "4.2"}),
        f"{definition}/database.tmdl": "database\n\tcompatibilityLevel: 1604\n",
        f"{definition}/model.tmdl": _model_tmdl(spec, physical),
        (
            f"{definition}/relationships/relationships.tmdl"
        ): _relationships_tmdl(spec),
    }
    for table in spec.tables:
        measures = tuple(
            item
            for item in spec.measures
            if item.emitted and item.home_table == table.name
        )
        artifacts[f"{definition}/tables/{table.name}.tmdl"] = _table_tmdl(
            table,
            physical_by_name[table.name],
            physical,
            measures,
        )
    if spec.calendar is not None and spec.calendar.approved:
        artifacts[f"{definition}/tables/dim_date.tmdl"] = _date_tmdl(
            spec.calendar,
            physical,
        )
        artifacts[
            f"{definition}/calculationGroups/time-intelligence.tmdl"
        ] = _time_intelligence_tmdl(spec.calendar)
    roles = _security_tmdl(spec)
    if roles:
        artifacts[f"{definition}/roles/security.tmdl"] = roles
    perspectives = _perspectives_tmdl(spec)
    if perspectives:
        artifacts[f"{definition}/perspectives/perspectives.tmdl"] = perspectives
    dax = _dax(spec)
    if dax:
        artifacts[f"{domain}/measures/{domain}-measures.dax"] = dax
    for path, content in render_gold_dbt_artifacts(spec, physical).items():
        artifacts[f"{domain}/dbt/{path}"] = content
    return dict(sorted(artifacts.items()))
