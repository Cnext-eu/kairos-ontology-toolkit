# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""DD-112/DD-113 profile-driven Gold product tests."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from kairos_ontology.core.projections.dbt import (
    DimensionalGoldSpec,
    GoldContractError,
    GoldPhysicalPlan,
)
from kairos_ontology.core.projections.dbt import gold_materialize
from kairos_ontology.core.projections.dbt.policy_normalize import (
    PolicyNormalizationError,
)
from kairos_ontology.core.projections.medallion_gold_projector import (
    generate_gold_artifacts,
)
from tests.scenarios.conftest import (
    EXTENSIONS_DIR,
    MAPPINGS_DIR,
    SHAPES_DIR,
    SOURCES_DIR,
    TEMPLATE_DIR,
    _load_ontology,
)


def _metadata(domain: str) -> dict[str, str]:
    return {
        "iri": f"https://acme.example/ontology/{domain}",
        "version": "1.0.0",
        "toolkit_version": "test",
    }


def _write_gold(tmp_path: Path, domain: str, content: str) -> Path:
    path = tmp_path / f"{domain}-gold-ext.ttl"
    path.write_text(content, encoding="utf-8")
    return path


def _gold_text(domain: str) -> str:
    return (EXTENSIONS_DIR / f"{domain}-gold-ext.ttl").read_text(encoding="utf-8")


def _generate(
    domain: str,
    *,
    gold_path: Path | None = None,
    platform: str = "fabric",
) -> dict[str, str]:
    graph, namespace, classes = _load_ontology(domain)
    peers = [EXTENSIONS_DIR / "client-silver-ext.ttl"] if domain == "invoice" else []
    return generate_gold_artifacts(
        classes=classes,
        graph=graph,
        template_dir=TEMPLATE_DIR,
        namespace=namespace,
        shapes_dir=SHAPES_DIR,
        ontology_name=domain,
        ontology_metadata=_metadata(domain),
        sources_dir=SOURCES_DIR,
        mappings_dir=MAPPINGS_DIR,
        gold_ext_path=(
            gold_path if gold_path is not None else EXTENSIONS_DIR / f"{domain}-gold-ext.ttl"
        ),
        silver_ext_path=EXTENSIONS_DIR / f"{domain}-silver-ext.ttl",
        peer_ext_paths=peers,
        target_platform=platform,
    )


@pytest.fixture(scope="module")
def client_gold() -> dict[str, str]:
    return _generate("client")


@pytest.fixture(scope="module")
def invoice_gold() -> dict[str, str]:
    return _generate("invoice")


def _report(artifacts: dict[str, str], domain: str) -> dict:
    return json.loads(artifacts[f"{domain}/{domain}-gold-product.json"])


def test_profile_registry_is_authoritative_and_absent_profile_blocks():
    graph, namespace, classes = _load_ontology("client")
    with pytest.raises(GoldContractError, match="gold.profile-missing"):
        generate_gold_artifacts(
            classes=classes,
            graph=graph,
            template_dir=TEMPLATE_DIR,
            namespace=namespace,
            ontology_name="client",
            ontology_metadata=_metadata("client"),
            sources_dir=SOURCES_DIR,
            mappings_dir=MAPPINGS_DIR,
            silver_ext_path=EXTENSIONS_DIR / "client-silver-ext.ttl",
        )


def test_unknown_profile_fails_closed(tmp_path: Path):
    text = _gold_text("client").replace(
        "dimensional-powerbi-v1",
        "wide-feature-product-v1",
    )
    with pytest.raises(PolicyNormalizationError, match="unsupported Gold product profile"):
        _generate("client", gold_path=_write_gold(tmp_path, "client", text))


def test_profile_specs_and_plans_are_frozen_slotted_dataclasses():
    for record in (DimensionalGoldSpec, GoldPhysicalPlan):
        assert dataclasses.is_dataclass(record)
        assert record.__dataclass_params__.frozen
        assert "__slots__" in record.__dict__


def test_profile_materializer_registry_accepts_future_logical_spec_types(monkeypatch):
    logical = SimpleNamespace(
        profile=gold_materialize.GoldProfileName.DIMENSIONAL_POWERBI_V1,
        profile_version="future-v1",
        ontology_name="future",
        ontology_version="1.0.0",
        adapter="fabric",
    )
    physical = SimpleNamespace(
        profile=logical.profile,
        profile_version=logical.profile_version,
        adapter=logical.adapter,
        adapter_version="1",
    )

    def materializer(spec, *, adapter_version, capability_results):
        assert spec is logical
        assert adapter_version == "1"
        assert capability_results == ()
        return physical

    monkeypatch.setitem(
        gold_materialize._PROFILE_MATERIALIZERS,
        logical.profile,
        materializer,
    )

    assert (
        gold_materialize.materialize_gold_product(
            logical,
            adapter_version="1",
            capability_results=(),
        )
        is physical
    )


def test_explicit_zero_dimension_facts_are_not_inferred(invoice_gold):
    report = _report(invoice_gold, "invoice")
    assert {table["role"] for table in report["tables"]} == {"fact"}
    assert {table["name"] for table in report["tables"]} == {
        "fact_invoice",
        "fact_invoice_line",
    }
    assert all(table["fact_grain"] for table in report["tables"])
    assert all(table["fact_type"] == "transaction" for table in report["tables"])
    assert all(not table["incremental_policy"] for table in report["tables"])
    assert all(not table["correction_policy"] for table in report["tables"])
    assert all(not table["late_arrival_policy"] for table in report["tables"])


@pytest.mark.parametrize(
    "fact_type",
    ("transaction", "periodic-snapshot", "accumulating-snapshot"),
)
def test_all_fact_types_preserve_explicit_grain(
    tmp_path: Path,
    fact_type: str,
):
    text = _gold_text("invoice").replace(
        'factType "transaction"',
        f'factType "{fact_type}"',
        1,
    )
    report = _report(
        _generate(
            "invoice",
            gold_path=_write_gold(tmp_path, "invoice", text),
        ),
        "invoice",
    )
    fact = next(item for item in report["tables"] if item["name"] == "fact_invoice")
    assert fact["fact_type"] == fact_type
    assert fact["fact_grain"] == "one invoice or credit-note source record"


def test_dimension_exposure_and_source_version_are_explicit(client_gold):
    report = _report(client_gold, "client")
    table = report["tables"][0]
    assert table["role"] == "dimension"
    assert table["dimension_exposure"] == "dual"
    assert table["version_binding"] == "current"
    assert table["source_model"] == "client"
    assert table["source_version"] == "1.0.0"
    assert report["silver_authority"]["parity"]["status"] == "pass"


@pytest.mark.parametrize(
    ("exposure", "current_view", "current_filter"),
    (
        ("current-only", False, False),
        ("history-only", False, False),
        ("dual", True, False),
    ),
)
def test_dimension_exposure_modes_are_physical(
    tmp_path: Path,
    exposure: str,
    current_view: bool,
    current_filter: bool,
):
    text = _gold_text("client").replace(
        'dimensionExposure "dual"',
        f'dimensionExposure "{exposure}"',
    )
    artifacts = _generate(
        "client",
        gold_path=_write_gold(tmp_path, "client", text),
    )
    sql = artifacts["client/dbt/models/gold/client/dim_client.sql"]
    assert ("where is_current = 1" in sql) is current_filter
    assert ("client/dbt/models/gold/client/dim_client_current.sql" in artifacts) is current_view


def test_source_model_and_version_drift_block(tmp_path: Path):
    original = _gold_text("client")
    for old, new, code in (
        ('goldSourceModel "client"', 'goldSourceModel "missing"', "source-model-drift"),
        ('goldSourceVersion "1.0.0"', 'goldSourceVersion "9.0"', "source-version-drift"),
    ):
        path = _write_gold(tmp_path, "client", original.replace(old, new))
        with pytest.raises(GoldContractError, match=code):
            _generate("client", gold_path=path)


def test_missing_silver_measure_column_blocks(tmp_path: Path):
    text = _gold_text("invoice").replace(
        "measureColumnDependency acme-inv:totalAmount",
        "measureColumnDependency acme-inv:notMaterialized",
        1,
    )
    with pytest.raises(GoldContractError, match="missing-column-dependency"):
        _generate("invoice", gold_path=_write_gold(tmp_path, "invoice", text))


def test_approved_measure_keeps_base_column_and_emits_dax(invoice_gold):
    fact_sql = invoice_gold["invoice/dbt/models/gold/invoice/fact_invoice.sql"]
    ddl = invoice_gold["invoice/invoice-gold-ddl.sql"]
    dax = invoice_gold["invoice/measures/invoice-measures.dax"]
    assert "total_amount as total_amount" in fact_sql
    assert "total_amount" in ddl
    assert "[invoice.total-amount] = SUM([total_amount])" in dax
    assert "not data validation" in dax
    measure = next(
        item
        for item in _report(invoice_gold, "invoice")["measures"]
        if item["id"] == "invoice.total-amount"
    )
    assert measure["data_type"] == "decimal"
    assert measure["format_string"] == "#,##0.00"
    assert measure["folder"] == "Finance"


@pytest.mark.parametrize(
    ("lifecycle", "emitted", "release_state"),
    (
        ("intent", False, "blocking"),
        ("provisional", True, "blocking"),
        ("validated", True, "blocking"),
        ("approved", True, "ready"),
    ),
)
def test_measure_lifecycle_controls_emission_and_release(
    tmp_path: Path,
    lifecycle: str,
    emitted: bool,
    release_state: str,
):
    text = _gold_text("invoice").replace(
        'measureLifecycleState "approved"',
        f'measureLifecycleState "{lifecycle}"',
        1,
    )
    if lifecycle == "intent":
        text = text.replace(
            '    kairos-ext:measureExpression "SUM([total_amount])" ;\n',
            "",
            1,
        )
    artifacts = _generate(
        "invoice",
        gold_path=_write_gold(tmp_path, "invoice", text),
    )
    report = _report(artifacts, "invoice")
    measure = next(item for item in report["measures"] if item["id"] == "invoice.total-amount")
    assert measure["emitted"] is emitted
    dax = artifacts.get("invoice/measures/invoice-measures.dax", "")
    assert ("[invoice.total-amount]" in dax) is emitted
    assert artifacts["__release_data__"]["gold_status"]["measures"] == release_state
    assert measure["data_validated_by_projection"] is False


def test_measure_cycle_and_missing_measure_dependency_block(tmp_path: Path):
    cycle = (
        _gold_text("invoice")
        + """
acme-inv:TotalInvoiceAmount
    kairos-ext:measureDependency acme-inv:TotalLineAmount .
acme-inv:TotalLineAmount
    kairos-ext:measureDependency acme-inv:TotalInvoiceAmount .
"""
    )
    with pytest.raises(PolicyNormalizationError, match="dependency cycle"):
        _generate("invoice", gold_path=_write_gold(tmp_path, "invoice", cycle))

    missing = (
        _gold_text("invoice")
        + """
acme-inv:TotalInvoiceAmount
    kairos-ext:measureDependency acme-inv:MissingMeasure .
"""
    )
    with pytest.raises(PolicyNormalizationError, match="do not resolve"):
        _generate("invoice", gold_path=_write_gold(tmp_path, "invoice", missing))


def test_approved_measure_requires_owner_tests_and_evidence(tmp_path: Path):
    original = _gold_text("invoice")
    cases = (
        (
            original.replace(
                '    kairos-ext:measureOwnerRole "Finance Data Owner" ;\n',
                "",
                1,
            ),
            "owner",
        ),
        (
            original.replace(
                '    kairos-ext:measureValidationTest "invoice-total-reconciliation" ;\n',
                "",
                1,
            ),
            "tests and validation evidence",
        ),
        (
            original.replace(
                '    kairos-ext:measureValidationTest "invoice-total-reconciliation" ;\n',
                '    kairos-ext:measureValidationTest "invoice-total-reconciliation" .\n',
                1,
            ).replace(
                '    kairos-ext:measureValidationEvidence "dq-run:invoice-total-v1" .\n',
                "",
                1,
            ),
            "tests and validation evidence",
        ),
    )
    for text, message in cases:
        with pytest.raises((PolicyNormalizationError, ValueError), match=message):
            _generate(
                "invoice",
                gold_path=_write_gold(
                    tmp_path,
                    "invoice",
                    text,
                ),
            )


def test_calendar_is_only_generated_when_explicit_and_approved(
    client_gold,
    invoice_gold,
):
    assert not any("dim_date" in path for path in client_gold)
    assert "invoice/dbt/models/gold/shared/dim_date.sql" in invoice_gold
    assert (
        "invoice/Invoice.SemanticModel/definition/calculationGroups/time-intelligence.tmdl"
    ) in invoice_gold
    calendar = _report(invoice_gold, "invoice")["calendar"]
    assert calendar["bounds"] == ["2020-01-01", "2035-12-31"]
    assert calendar["week_pattern"] == "iso-8601-monday"
    assert calendar["locale"] == "en-BE"
    assert calendar["holiday_source"] == "none-approved"
    assert calendar["time_zone"] == "Europe/Brussels"
    assert calendar["period_closure"] == "finance-approved-period-status"
    assert calendar["roles"][0]["binding"] == "fact_invoice.invoice_date"


def test_draft_calendar_blocks_time_intelligence(tmp_path: Path):
    text = _gold_text("invoice").replace(
        'calendarApprovalStatus "approved"',
        'calendarApprovalStatus "draft"',
    )
    artifacts = _generate(
        "invoice",
        gold_path=_write_gold(tmp_path, "invoice", text),
    )
    assert not any("dim_date" in path for path in artifacts)
    assert artifacts["__release_data__"]["gold_status"]["calendar"] == "blocking"


def test_calendar_bounds_and_role_bindings_are_validated(tmp_path: Path):
    invalid_range = _gold_text("invoice").replace("2020-01-01", "2040-01-01")
    with pytest.raises(PolicyNormalizationError, match="start date"):
        _generate(
            "invoice",
            gold_path=_write_gold(tmp_path, "invoice", invalid_range),
        )
    invalid_role = _gold_text("invoice").replace(
        "Invoice.invoice_date",
        "Invoice.not_materialized",
    )
    with pytest.raises(GoldContractError, match="missing-role-column"):
        _generate(
            "invoice",
            gold_path=_write_gold(tmp_path, "invoice", invalid_role),
        )


def test_complete_security_is_fail_closed_and_perspectives_are_navigation_only(
    client_gold,
):
    report = _report(client_gold, "client")
    assert report["security"]["fail_closed"] is True
    assert report["security"]["positive_tests"]
    assert report["security"]["negative_tests"]
    assert report["security"]["test_evidence"]
    roles = client_gold["client/Client.SemanticModel/definition/roles/security.tmdl"]
    assert "filterExpression: FALSE()" in roles
    assert "columnPermission dim_client.email" in roles
    assert "metadataPermission: none" in roles
    assert all(perspective["security_boundary"] is False for perspective in report["perspectives"])


@pytest.mark.parametrize(
    "line",
    (
        '    kairos-ext:negativeSecurityTest "unauthorized-client-reader" ;\n',
        '    kairos-ext:securityTestEvidence "security-run:client-access-v1" ;\n',
    ),
)
def test_incomplete_security_blocks_projection(tmp_path: Path, line: str):
    text = _gold_text("client").replace(line, "", 1)
    with pytest.raises(ValueError):
        _generate("client", gold_path=_write_gold(tmp_path, "client", text))


def test_databricks_requires_declared_downstream_powerbi_deviations(tmp_path: Path):
    with pytest.raises(GoldContractError, match="adapter-capability-blocking"):
        _generate("client", platform="databricks")

    text = (
        _gold_text("client")
        + """
acme:DatabricksTmdlDeviation a kairos-ext:Deviation ;
    kairos-ext:adapterName "databricks" ;
    kairos-ext:policyReference "DD-113-tmdl" ;
    kairos-ext:deviationScope "gold" ;
    kairos-ext:deviationRationale "Power BI is downstream of Databricks SQL." ;
    kairos-ext:deviationOwnerRole "Platform Owner" ;
    kairos-ext:approvalStatus "approved" ;
    kairos-ext:reviewDate "2026-07-25" ;
    kairos-ext:expiryDate "2099-12-31" ;
    kairos-ext:deviationEvidence "review:databricks-tmdl" .

acme:DatabricksSecurityDeviation a kairos-ext:Deviation ;
    kairos-ext:adapterName "databricks" ;
    kairos-ext:policyReference "DD-113-security" ;
    kairos-ext:deviationScope "gold" ;
    kairos-ext:deviationRationale "Security enforcement is in downstream Power BI." ;
    kairos-ext:deviationOwnerRole "Security Owner" ;
    kairos-ext:approvalStatus "approved" ;
    kairos-ext:reviewDate "2026-07-25" ;
    kairos-ext:expiryDate "2099-12-31" ;
    kairos-ext:deviationEvidence "review:databricks-security" .
"""
    )
    artifacts = _generate(
        "client",
        gold_path=_write_gold(tmp_path, "client", text),
        platform="databricks",
    )
    report = _report(artifacts, "client")
    assert report["adapter"]["semantic_mode"] == "directQuery"
    assert len(report["adapter"]["approved_deviations"]) == 2
    ddl = artifacts["client/client-gold-ddl.sql"]
    assert "USING DELTA" in ddl


def test_ddl_tmdl_dax_erd_and_report_are_deterministic(invoice_gold):
    second = _generate("invoice")
    comparable = {
        path: content for path, content in invoice_gold.items() if path != "__release_data__"
    }
    assert comparable == {
        path: content for path, content in second.items() if path != "__release_data__"
    }
    assert "CREATE TABLE" in invoice_gold["invoice/invoice-gold-ddl.sql"]
    assert "erDiagram" in invoice_gold["invoice/invoice-gold-erd.mmd"]
    schema = yaml.safe_load(
        invoice_gold["invoice/dbt/models/gold/invoice/_invoice__gold_models.yml"]
    )
    assert {item["name"] for item in schema["models"]} == {
        "fact_invoice",
        "fact_invoice_line",
    }


def test_pbip_wrapper_is_complete_and_schema_stamped(invoice_gold):
    """The projector owns the full PBIP wrapper, not a bare marker file.

    ``package_fabric_semantic_model.py`` used to write a richer
    ``definition.pbism`` than the projector, so the two writers disagreed on
    the same file. The projector is now authoritative.
    """
    prefix = "invoice/Invoice.SemanticModel"

    platform = json.loads(invoice_gold[f"{prefix}/.platform"])
    assert platform["metadata"] == {"displayName": "Invoice", "type": "SemanticModel"}
    assert platform["config"]["version"] == "2.0"
    assert "gitIntegration/platformProperties" in platform["$schema"]

    pbism = json.loads(invoice_gold[f"{prefix}/definition.pbism"])
    assert pbism["version"] == "4.2"
    assert pbism["settings"] == {}
    assert "semanticModel/definitionProperties" in pbism["$schema"]

    assert invoice_gold[f"{prefix}/definition/database.tmdl"] == (
        "database\n\tcompatibilityLevel: 1604\n"
    )


def test_pbip_project_and_report_wrapper_resolve_to_the_local_model(invoice_gold):
    """Desktop opens a report, so the project points at .Report which binds the model.

    Asserts the two relative references actually line up with emitted folders —
    a wrapper whose paths dangle is worse than no wrapper.
    """
    pbip = json.loads(invoice_gold["invoice/Invoice.pbip"])
    assert pbip["version"] == "1.0"
    assert pbip["artifacts"] == [{"report": {"path": "Invoice.Report"}}]

    # The referenced .Report folder exists.
    report_dir = f"invoice/{pbip['artifacts'][0]['report']['path']}"
    assert f"{report_dir}/definition.pbir" in invoice_gold
    assert json.loads(invoice_gold[f"{report_dir}/.platform"])["metadata"]["type"] == "Report"

    # …and its dataset reference resolves back to the emitted SemanticModel.
    pbir = json.loads(invoice_gold[f"{report_dir}/definition.pbir"])
    target = pbir["datasetReference"]["byPath"]["path"]
    assert target == "../Invoice.SemanticModel"
    resolved = f"invoice/{target.removeprefix('../')}"
    assert f"{resolved}/definition.pbism" in invoice_gold
    assert f"{resolved}/definition/model.tmdl" in invoice_gold


def test_blank_report_has_exactly_one_page_and_is_deterministic(invoice_gold):
    """Kairos generates the model, not visuals — the report is an empty bound canvas."""
    report_dir = "invoice/Invoice.Report"
    pages = json.loads(invoice_gold[f"{report_dir}/definition/pages/pages.json"])
    assert len(pages["pageOrder"]) == 1
    page_name = pages["pageOrder"][0]
    assert pages["activePageName"] == page_name

    # The page folder named in pages.json is the one actually emitted.
    page = json.loads(invoice_gold[f"{report_dir}/definition/pages/{page_name}/page.json"])
    assert page["name"] == page_name

    page_files = [p for p in invoice_gold if p.startswith(f"{report_dir}/definition/pages/")]
    assert len(page_files) == 2  # pages.json + the single page.json

    assert json.loads(invoice_gold[f"{report_dir}/definition/version.json"])["version"] == "4.0"
