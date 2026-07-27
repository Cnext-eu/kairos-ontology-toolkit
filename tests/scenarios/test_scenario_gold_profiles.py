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
