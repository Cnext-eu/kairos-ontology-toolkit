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


#: Issue #1113 on the ACME invoice product: a field parameter switching between the two
#: governed measures, and a date-basis calculation group beside the calendar's Time
#: Intelligence group -- the report design the issue's evidence builds by hand.
_INVOICE_REPORT_OBJECTS = """
<https://acme.example/ontology/invoice>
    kairos-ext:parameter acme-inv:FinanceMeasure ;
    kairos-ext:calculationGroup acme-inv:DateBasis .

acme-inv:FinanceMeasure a kairos-ext:Parameter ;
    kairos-ext:parameterId "finance_measure" ;
    kairos-ext:parameterKind "field" ;
    kairos-ext:parameterDisplayName "Finance measure" ;
    kairos-ext:parameterItem ( "Invoice total=measure:invoice.total-amount"
                               "Line total=measure:invoice.total-line-amount" ) .

acme-inv:DateBasis a kairos-ext:CalculationGroup ;
    kairos-ext:calculationGroupId "date_basis" ;
    kairos-ext:calculationGroupDisplayName "Date Basis" ;
    kairos-ext:calculationGroupPrecedence 20 ;
    kairos-ext:calculationItem acme-inv:DateBasisCalendar, acme-inv:DateBasisInvoice .

acme-inv:DateBasisCalendar a kairos-ext:CalculationItem ;
    kairos-ext:calculationItemName "Calendar" ;
    kairos-ext:calculationItemOrdinal 0 ;
    kairos-ext:calculationItemExpression "SELECTEDMEASURE()" .

acme-inv:DateBasisInvoice a kairos-ext:CalculationItem ;
    kairos-ext:calculationItemName "Invoice date" ;
    kairos-ext:calculationItemOrdinal 1 ;
    kairos-ext:calculationItemExpression \"\"\"VAR _from = MIN(dim_date[full_date])
VAR _to = MAX(dim_date[full_date]) + 1
RETURN
    CALCULATE(SELECTEDMEASURE(), REMOVEFILTERS(dim_date),
        fact_invoice[invoice_date] >= _from, fact_invoice[invoice_date] < _to)\"\"\" ;
    kairos-ext:calculationItemColumnDependency "dim_date.full_date", "fact_invoice.invoice_date" .
"""


def test_invoice_report_parameters_and_date_basis_beside_time_intelligence(
    invoice_ontology, tmp_path
):
    """#1113: authored report objects on a calendar product, through the Gold harness."""
    from kairos_ontology.core.projections.medallion_gold_projector import (
        generate_gold_artifacts,
    )

    from .conftest import EXTENSIONS_DIR, MAPPINGS_DIR, SHAPES_DIR, SOURCES_DIR, TEMPLATE_DIR

    graph, namespace, classes = invoice_ontology
    gold_ext = tmp_path / "invoice-gold-ext.ttl"
    gold_ext.write_text(
        (EXTENSIONS_DIR / "invoice-gold-ext.ttl").read_text(encoding="utf-8")
        + _INVOICE_REPORT_OBJECTS,
        encoding="utf-8",
    )
    artifacts = generate_gold_artifacts(
        classes=classes,
        graph=graph,
        template_dir=TEMPLATE_DIR,
        namespace=namespace,
        shapes_dir=SHAPES_DIR,
        ontology_name="invoice",
        ontology_metadata={"iri": "https://acme.example/ontology/invoice", "version": "1.0.0"},
        sources_dir=SOURCES_DIR,
        mappings_dir=MAPPINGS_DIR,
        gold_ext_path=gold_ext,
        silver_ext_path=EXTENSIONS_DIR / "invoice-silver-ext.ttl",
        peer_ext_paths=[EXTENSIONS_DIR / "client-silver-ext.ttl"],
    )
    definition = "invoice/Invoice.SemanticModel/definition"
    parameter = artifacts[f"{definition}/tables/finance_measure.tmdl"]
    assert "NAMEOF('fact_invoice'[Total Invoice Amount]), 0)" in parameter
    assert "NAMEOF('fact_invoice_line'[Total Line Amount]), 1)" in parameter

    groups = {
        path.rsplit("/", 1)[1]: text
        for path, text in artifacts.items()
        if "/calculationGroups/" in path
    }
    assert set(groups) == {"time-intelligence.tmdl", "date_basis.tmdl"}
    assert "\t\tprecedence: 20" in groups["date_basis.tmdl"]
    assert "precedence:" not in groups["time-intelligence.tmdl"]

    model = artifacts[f"{definition}/model.tmdl"]
    assert "ref table 'Finance measure'" in model
    assert "ref table 'Date Basis'" in model
    assert "ref table 'Time Intelligence'" in model

    report = next(path for path in artifacts if path.endswith("-gold-product.json"))
    product = json.loads(artifacts[report])
    assert product["calculation_groups"][0]["items"][1]["column_dependencies"] == [
        "dim_date.full_date",
        "fact_invoice.invoice_date",
    ]
