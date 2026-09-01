# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario coverage for DD-112/DD-113 Gold product profiles."""

from __future__ import annotations

import json


def _product(artifacts: dict[str, str], domain: str) -> dict:
    return json.loads(artifacts[f"metadata/{domain}-gold-product.json"])


def test_client_dimension_is_explicit_and_security_is_fail_closed(
    client_dbt_artifacts,
):
    product = _product(client_dbt_artifacts, "client")
    assert product["profile"]["name"] == "dimensional-powerbi-v1"
    assert [(item["name"], item["role"]) for item in product["tables"]] == [
        ("dim_client", "dimension")
    ]
    assert product["tables"][0]["dimension_exposure"] == "dual"
    assert product["security"]["fail_closed"]
    assert {item["kind"] for item in product["security"]["bindings"]} == {
        "RLS",
        "OLS",
    }
    assert all(item["security_boundary"] is False for item in product["perspectives"])


def test_invoice_facts_need_no_dimensions_and_keep_measure_columns(
    invoice_dbt_artifacts,
):
    product = _product(invoice_dbt_artifacts, "invoice")
    assert {item["role"] for item in product["tables"]} == {"fact"}
    assert all(item["fact_grain"] for item in product["tables"])
    assert all(not item["incremental_policy"] for item in product["tables"])
    assert all(item["lifecycle"] == "approved" for item in product["measures"])
    assert all(item["data_validated_by_projection"] is False for item in product["measures"])
    assert (
        "total_amount as total_amount"
        in invoice_dbt_artifacts["models/gold/invoice/fact_invoice.sql"]
    )


def test_invoice_calendar_is_approved_and_role_bound(invoice_dbt_artifacts):
    product = _product(invoice_dbt_artifacts, "invoice")
    assert product["calendar"]["approved"]
    assert product["calendar"]["bounds"] == ["2020-01-01", "2035-12-31"]
    assert product["calendar"]["roles"] == [
        {
            "binding": "fact_invoice.invoice_date",
            "name": "InvoiceDate",
        }
    ]
    assert "models/gold/shared/dim_date.sql" in invoice_dbt_artifacts


def test_gold_product_report_carries_passing_silver_parity(
    client_dbt_artifacts,
    invoice_dbt_artifacts,
):
    for domain, artifacts in (
        ("client", client_dbt_artifacts),
        ("invoice", invoice_dbt_artifacts),
    ):
        parity = _product(artifacts, domain)["silver_authority"]["parity"]
        assert parity["status"] == "pass"
        assert parity["required"] is True


def test_strict_gold_status_requires_external_tmdl_compile_evidence(
    client_dbt_artifacts,
    invoice_dbt_artifacts,
):
    for artifacts in (client_dbt_artifacts, invoice_dbt_artifacts):
        status = artifacts["__release_data__"]["gold_status"]
        assert status["tables"] == "ready"
        assert status["measures"] == "ready"
        assert status["tmdl_compile"] == "blocking"


def test_gold_table_named_after_its_silver_model_blocks_the_render(client_ontology, tmp_path):
    """End-to-end reproduction of issue #685 on a real hub.

    Setting `goldTableName` equal to `goldSourceModel` emits `models/silver/client/client.sql`
    and `models/gold/client/client.sql`. dbt cannot parse a project with two models of one
    name, yet this used to render, pass `compile --check`, and reach tracked publish output
    with only a `self-referential ref(...)` log warning.
    """
    import pytest

    from kairos_ontology.core.projections.dbt.render import DbtModelNameCollisionError
    from kairos_ontology.core.projections.medallion_dbt_projector import (
        generate_dbt_artifacts,
    )

    from .conftest import (
        EXTENSIONS_DIR,
        MAPPINGS_DIR,
        SHAPES_DIR,
        SOURCES_DIR,
        TEMPLATE_DIR,
    )

    graph, namespace, classes = client_ontology
    colliding_gold = tmp_path / "client-gold-ext.ttl"
    colliding_gold.write_text(
        (EXTENSIONS_DIR / "client-gold-ext.ttl")
        .read_text(encoding="utf-8")
        .replace('goldTableName "dim_client"', 'goldTableName "client"'),
        encoding="utf-8",
    )

    with pytest.raises(DbtModelNameCollisionError) as excinfo:
        generate_dbt_artifacts(
            classes=classes,
            graph=graph,
            template_dir=TEMPLATE_DIR,
            namespace=namespace,
            shapes_dir=SHAPES_DIR,
            ontology_name="client",
            ontology_metadata={
                "iri": "https://acme.example/ontology/client",
                "version": "1.0.0",
            },
            bronze_dir=SOURCES_DIR,
            sources_dir=SOURCES_DIR,
            mappings_dir=MAPPINGS_DIR,
            gold_ext_path=colliding_gold,
            silver_ext_path=EXTENSIONS_DIR / "client-silver-ext.ttl",
        )

    message = str(excinfo.value)
    assert "models/silver/client/client.sql" in message
    assert "models/gold/client/client.sql" in message
