# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Integrated DD-106 source-preparation projection tests."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.projections.dbt import (
    PolicyNormalizationError,
    PrepModelSpec,
    bind_sources,
    normalize_contract,
    plan_materialization,
    render_project,
    shape_project,
)
from kairos_ontology.core.projections.dbt.policy_specs import (
    AuthoredValuesFact,
    CanonicalTypeKind,
    CanonicalTypeSpec,
)
from kairos_ontology.core.projections.dbt.prep_renderers import _conversion_expression
from kairos_ontology.core.projections.dbt.shape import _source_record_key_expression
from kairos_ontology.core.projections.medallion_dbt_projector import (
    generate_dbt_artifacts,
)
from tests.scenarios.conftest import (
    EXTENSIONS_DIR,
    MAPPINGS_DIR,
    SHAPES_DIR,
    SOURCES_DIR,
    TEMPLATE_DIR,
    _load_ontology,
)
from tests.test_dbt_phases import _client_inputs


def _artifacts(
    domain: str,
    adapter: str = "fabric",
    *,
    include_gold: bool = True,
) -> dict:
    graph, namespace, classes = _load_ontology(domain)
    peers = [EXTENSIONS_DIR / "client-silver-ext.ttl"] if domain == "invoice" else []
    return generate_dbt_artifacts(
        classes=classes,
        graph=graph,
        template_dir=TEMPLATE_DIR,
        namespace=namespace,
        shapes_dir=SHAPES_DIR,
        ontology_name=domain,
        sources_dir=SOURCES_DIR,
        mappings_dir=MAPPINGS_DIR,
        gold_ext_path=(
            EXTENSIONS_DIR / f"{domain}-gold-ext.ttl"
            if include_gold
            else None
        ),
        silver_ext_path=EXTENSIONS_DIR / f"{domain}-silver-ext.ttl",
        peer_ext_paths=peers,
        target_platform=adapter,
    )


def _policy_for(bound, table_suffix: str):
    return next(
        policy
        for policy in bound.policy_facts.preparations
        if policy.source_table.values[0].endswith(table_suffix)
    )


def test_missing_duplicate_and_absent_prep_mode_are_blocking():
    bound = bind_sources(_client_inputs())
    policy = _policy_for(bound, "#Customers")

    missing_facts = dataclasses.replace(
        bound.policy_facts,
        preparations=tuple(item for item in bound.policy_facts.preparations if item is not policy),
    )
    with pytest.raises(PolicyNormalizationError, match="prep.missing-policy"):
        normalize_contract(dataclasses.replace(bound, policy_facts=missing_facts))

    duplicate_facts = dataclasses.replace(
        bound.policy_facts,
        preparations=bound.policy_facts.preparations + (policy,),
    )
    with pytest.raises(PolicyNormalizationError, match="prep.duplicate-policy"):
        normalize_contract(dataclasses.replace(bound, policy_facts=duplicate_facts))

    absent_mode = dataclasses.replace(
        policy,
        mode=AuthoredValuesFact(
            policy.mode.resource_uri,
            policy.mode.predicate_uri,
            (),
        ),
    )
    absent_facts = dataclasses.replace(
        bound.policy_facts,
        preparations=tuple(
            absent_mode if item is policy else item for item in bound.policy_facts.preparations
        ),
    )
    with pytest.raises(PolicyNormalizationError, match="prep.missing-mode"):
        normalize_contract(dataclasses.replace(bound, policy_facts=absent_facts))

    duplicate_mode = dataclasses.replace(
        policy,
        mode=AuthoredValuesFact(
            policy.mode.resource_uri,
            policy.mode.predicate_uri,
            ("normalize", "passthrough"),
        ),
    )
    duplicate_mode_facts = dataclasses.replace(
        bound.policy_facts,
        preparations=tuple(
            duplicate_mode if item is policy else item for item in bound.policy_facts.preparations
        ),
    )
    with pytest.raises(
        PolicyNormalizationError,
        match="prep.duplicate-mode",
    ):
        normalize_contract(dataclasses.replace(bound, policy_facts=duplicate_mode_facts))


@pytest.mark.parametrize(
    ("column_change", "expected"),
    [
        ({"name": "select"}, "prep.missing-safe-rename"),
        ({"data_type": "int"}, "prep.missing-required-cast"),
    ],
)
def test_passthrough_validation_fails_closed(column_change, expected):
    bound = bind_sources(_client_inputs())
    systems = []
    for system in bound.systems:
        if system.label != "CrmSystem":
            systems.append(system)
            continue
        tables = []
        for table in system.tables:
            if table.name != "Customers":
                tables.append(table)
                continue
            first, *rest = table.columns
            tables.append(
                dataclasses.replace(
                    table,
                    columns=(
                        dataclasses.replace(first, **column_change),
                        *rest,
                    ),
                )
            )
        systems.append(dataclasses.replace(system, tables=tuple(tables)))
    with pytest.raises(PolicyNormalizationError, match=expected):
        normalize_contract(dataclasses.replace(bound, systems=tuple(systems)))


def test_shape_emits_only_domain_scoped_prep_specs_and_verified_routes():
    shaped = shape_project(normalize_contract(bind_sources(_client_inputs())))
    assert shaped.prep_models
    assert not shaped.prep_children
    assert all(isinstance(item, PrepModelSpec) for item in shaped.prep_models)
    assert dataclasses.is_dataclass(PrepModelSpec)
    assert PrepModelSpec.__dataclass_params__.frozen

    by_table = {route.table_name: route for route in shaped.prep_routes}
    assert by_table["tblClient"].ref_model == "stg_admin_pulse__tbl_client"
    assert by_table["Customers"].mode == "normalize"
    assert by_table["Customers"].ref_model == "stg_crm_system__customers"
    assert any("crm_system__customers" in model.model_name for model in shaped.prep_models)


def test_fabric_prep_renders_names_casts_sentinels_keys_cdc_and_scalar_json():
    artifacts = _artifacts("invoice")
    invoice = artifacts["models/staging/billing_pro/stg_billing_pro__tbl_invoice.sql"]
    line = artifacts["models/staging/billing_pro/stg_billing_pro__tbl_invoice_line.sql"]

    assert "src.[Status] AS invoice_status" in invoice
    assert "TRIM(CASE WHEN src.[Currency] = 'N/A' THEN NULL" in invoice
    assert "src.[Currency] AS Currency__raw" in invoice
    assert "CAST(src.[LastModified] AS DATETIME2(6)) AS _source_updated_at" in invoice
    assert "JSON_VALUE(src.[MetadataJson], '$.channel')" in invoice
    assert "src.[MetadataJson] AS MetadataJson" in invoice
    assert "_prep_json_error__source_channel" in invoice
    assert "\"'billingpro'\"" in invoice
    assert "\"'tblInvoice'\"" in invoice
    assert "NOT LIKE '%[^0-9]%'" in line
    assert "__kairos_invalid_integer-lexical__" in line
    assert "THEN CAST(src.[LineID] AS VARCHAR(8000))" in line
    assert "src.[LineID] AS LineID__raw" in line


def test_array_child_preserves_parent_grain_and_raw_replay_payload():
    artifacts = _artifacts("invoice")
    child = artifacts["models/staging/billing_pro/stg_billingpro__invoice_line_details.sql"]
    assert "CROSS APPLY OPENJSON(parent.[LineDetails], '$')" in child
    assert "parent.[_source_record_key] AS _source_record_key" in child
    assert "CAST(element.[key] AS BIGINT) AS _element_index" in child
    assert "element.[value] AS _raw_payload" in child
    assert "Null and empty arrays produce zero child rows" in child
    assert sum(line.strip().startswith("FROM ") for line in child.splitlines()) == 1

    silver = artifacts["models/silver/invoice/invoice_line_tax.sql"]
    assert "ref('stg_billingpro__invoice_line_details')" in silver
    assert "._source_record_key as _source_record_key" in silver
    assert "_source_record_id" not in silver


def test_technical_dedupe_uses_complete_total_order():
    artifacts = _artifacts("client")
    relation = artifacts["models/staging/admin_pulse/stg_admin_pulse__tbl_relation.sql"]
    assert "ROW_NUMBER() OVER (" in relation
    assert "PARTITION BY [ClientID]" in relation
    assert "ORDER BY [ModifiedDate] DESC, [RelationID] DESC" in relation
    assert "WHERE _prep_row_number = 1" in relation


def test_staging_schema_contracts_and_tests_share_prep_specs():
    artifacts = _artifacts("invoice")
    schema = yaml.safe_load(artifacts["models/staging/billing_pro/_billing_pro__staging.yml"])
    models = {item["name"]: item for item in schema["models"]}
    parent = models["stg_billing_pro__tbl_invoice"]
    child = models["stg_billingpro__invoice_line_details"]
    assert parent["config"]["contract"]["enforced"] is True
    source_key = next(item for item in parent["columns"] if item["name"] == "_source_record_key")
    assert source_key["data_tests"] == ["not_null", "unique"]
    assert child["data_tests"][0]["dbt_utils.unique_combination_of_columns"][
        "combination_of_columns"
    ] == ["_source_record_key", "_element_index"]
    assert any(item["name"] == "_raw_payload" for item in child["columns"])


def test_silver_automatically_routes_all_runtime_sources_through_prep():
    invoice = _artifacts("invoice")
    normalized = invoice["models/silver/invoice/invoice__from_billing_pro__tbl_invoice.sql"]
    runtime_model = invoice["models/silver/invoice/invoice_tag.sql"]
    assert "ref('stg_billing_pro__tbl_invoice')" in normalized
    assert "source('billing_pro', 'tblInvoice')" not in normalized
    assert "ref('stg_billing_pro__tbl_invoice_tag')" in runtime_model
    assert "source('billing_pro', 'tblInvoiceTag')" not in runtime_model

    crm = _artifacts("client")["models/silver/client/client__from_crm_system.sql"]
    assert "ref('stg_crm_system__customers')" in crm
    assert "customers._source_record_key" in crm

    client = _artifacts("client")
    branch = client[
        "models/silver/client/client__from_admin_pulse__tbl_client__corporate_client.sql"
    ]
    assert "where ([tbl_client].[client_type_code] = 0)" in branch.lower()
    assert "where Type = 0" not in branch


def test_databricks_renderer_has_no_fabric_only_array_sql():
    artifacts = _artifacts("invoice", "databricks", include_gold=False)
    child = artifacts["models/staging/billing_pro/stg_billingpro__invoice_line_details.sql"]
    parent = artifacts["models/staging/billing_pro/stg_billing_pro__tbl_invoice.sql"]
    assert "POSEXPLODE" in child
    assert "OPENJSON" not in child
    assert "`LineDetails`" in child
    assert "GET_JSON_OBJECT" in parent
    assert "[MetadataJson]" not in parent


@pytest.mark.parametrize(
    ("policy", "target_type", "fabric_positive", "databricks_positive"),
    [
        (
            "strict-text",
            "VARCHAR(40)",
            "THEN CAST(src.value AS VARCHAR(40))",
            "THEN CAST(src.value AS VARCHAR(40))",
        ),
        (
            "integer-lexical",
            "BIGINT",
            "NOT LIKE '%[^0-9]%'",
            r"RLIKE '^[+-]?[0-9]+$'",
        ),
        (
            "decimal-invariant",
            "DECIMAL(18,4)",
            "NOT LIKE '%.%.%'",
            r"RLIKE '^[+-]?[0-9]+(?:\.[0-9]+)?$'",
        ),
        (
            "boolean-canonical",
            "BOOLEAN",
            "Latin1_General_100_BIN2",
            "IN ('true', 'false')",
        ),
    ],
)
def test_implemented_parse_policies_render_validation_and_fail_closed_sql(
    policy,
    target_type,
    fabric_positive,
    databricks_positive,
):
    fabric, _ = _conversion_expression(
        "src.value",
        "BIT" if policy == "boolean-canonical" else target_type,
        policy,
        "fail",
        "fabric",
    )
    databricks, _ = _conversion_expression(
        "src.value",
        target_type,
        policy,
        "fail",
        "databricks",
    )
    assert fabric_positive in fabric
    assert databricks_positive in databricks
    assert f"__kairos_invalid_{policy}__" in fabric
    assert f"Invalid {policy} lexical value" in databricks
    assert "RAISE_ERROR" in databricks


def test_null_with_evidence_uses_the_same_lexical_validation_for_value_and_flag():
    expression, invalid = _conversion_expression(
        "src.value",
        "BIGINT",
        "integer-lexical",
        "null-with-evidence",
        "databricks",
    )
    predicate = r"CAST(src.value AS STRING) RLIKE '^[+-]?[0-9]+$'"
    assert predicate in expression
    assert predicate in invalid
    assert "TRY_CAST(src.value AS BIGINT) IS NOT NULL" in expression
    assert "ELSE CAST(NULL AS BIGINT)" in expression
    assert invalid.startswith("src.value IS NOT NULL AND NOT")


@pytest.mark.parametrize(
    ("policy", "target_kind"),
    [
        ("strict-iso-8601", "timestamp"),
        ("boolean-canonical", "string"),
        ("strict-text", "int64"),
    ],
)
def test_unimplemented_parse_policy_combinations_block_materialization(
    policy,
    target_kind,
):
    contract = normalize_contract(bind_sources(_client_inputs()))
    shaped = shape_project(contract)
    model = next(item for item in shaped.prep_models if item.source_table_name == "tblClient")
    column = next(item for item in model.columns if item.conversion is not None)
    conversion = column.conversion
    changed_conversion = dataclasses.replace(
        conversion,
        target_type=dataclasses.replace(
            conversion.target_type,
            value=CanonicalTypeSpec(CanonicalTypeKind(target_kind)),
        ),
        parse_policy=dataclasses.replace(
            conversion.parse_policy,
            value=policy,
        ),
    )
    changed_model = dataclasses.replace(
        model,
        columns=tuple(
            dataclasses.replace(item, conversion=changed_conversion)
            if item is column
            else item
            for item in model.columns
        ),
    )
    shaped = dataclasses.replace(
        shaped,
        prep_models=tuple(
            changed_model if item is model else item for item in shaped.prep_models
        ),
    )
    plan = plan_materialization(contract, shaped)
    expected = f"parse:{policy}:{target_kind}"
    assert any(expected in reason for _, reason in plan.release.blocking_rules)
    with pytest.raises(ValueError, match="Preparation materialization blocked"):
        render_project(shaped, plan)


def test_source_scope_prevents_same_table_and_pk_key_collision():
    shaped = shape_project(normalize_contract(bind_sources(_client_inputs())))
    routes = {route.table_name: route for route in shaped.prep_routes}
    first_key = dataclasses.replace(
        routes["tblClient"].source_record_key,
        table_scope="same_table",
        component_columns=("same_pk",),
    )
    second_key = dataclasses.replace(
        routes["Customers"].source_record_key,
        table_scope="same_table",
        component_columns=("same_pk",),
    )
    first_route = dataclasses.replace(
        routes["tblClient"],
        ref_model="",
        source_record_key=first_key,
    )
    second_route = dataclasses.replace(
        routes["Customers"],
        ref_model="",
        source_record_key=second_key,
    )
    first = _source_record_key_expression(first_route, "src")
    second = _source_record_key_expression(second_route, "src")
    assert "\"'adminpulse'\", \"'same_table'\", 'src.same_pk'" in first
    assert "\"'crmsystem'\", \"'same_table'\", 'src.same_pk'" in second
    assert first != second


def test_prep_projection_is_deterministic(monkeypatch):
    monkeypatch.setenv("KAIROS_GENERATED_AT", "2026-01-01T00:00:00Z")
    assert _artifacts("invoice") == _artifacts("invoice")


def test_unsupported_prep_feature_is_reported_and_not_rendered():
    bound = bind_sources(_client_inputs())
    policy = _policy_for(bound, "#tblClientPII")
    cleanup = policy.cleanup_rules[0]
    unsupported_cleanup = dataclasses.replace(
        cleanup,
        operation=AuthoredValuesFact(
            cleanup.operation.resource_uri,
            cleanup.operation.predicate_uri,
            ("unicode-normalize",),
        ),
    )
    changed_policy = dataclasses.replace(
        policy,
        cleanup_rules=(unsupported_cleanup,),
    )
    changed_facts = dataclasses.replace(
        bound.policy_facts,
        preparations=tuple(
            changed_policy if item is policy else item for item in bound.policy_facts.preparations
        ),
    )
    changed_bound = dataclasses.replace(bound, policy_facts=changed_facts)
    contract = normalize_contract(changed_bound)
    shaped = shape_project(contract)
    plan = plan_materialization(contract, shaped)
    assert any("unicode-normalize" in reason for _, reason in plan.release.blocking_rules)
    with pytest.raises(ValueError, match="Preparation materialization blocked"):
        render_project(shaped, plan)


def test_release_data_contains_prep_routing_and_capability_reasons():
    release = _artifacts("invoice")["__release_data__"]
    assert release["policy_version"] == "1.0"
    assert any(
        route["table_name"] == "tblInvoice"
        and route["mode"] == "normalize"
        and route["ref_model"] == "stg_billing_pro__tbl_invoice"
        for route in release["preparation_routes"]
    )
    assert all(item["rule_id"] and item["reason"] for item in release["capabilities"])


def test_legacy_staging_generator_and_cli_are_removed():
    root = Path(__file__).parents[1]
    assert not (root / "src" / "kairos_ontology" / "core" / "generate_staging.py").exists()
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "generate-staging" not in result.output
    core = root / "src" / "kairos_ontology"
    assert all(
        "bronze_expanded" not in path.read_text(encoding="utf-8")
        and "generate_staging" not in path.read_text(encoding="utf-8")
        for path in core.rglob("*.py")
    )
