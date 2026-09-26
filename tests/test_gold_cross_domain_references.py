# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Gold references to another domain's table are deferred per domain (#1003, #1012).

A product has one calendar, authored in one domain, and its role-playing dates may bind a
fact of any domain of the product. A ``goldPrimaryRelationship`` may name an edge that
only exists once two domains are shaped together. Both were checked on every
single-domain compile, against a union of one, so neither could be authored. They now
follow the #763 bridge-endpoint contract: recorded as ``deferred_references`` on the
single-domain compile, and checked fail-closed when the product is shaped.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from kairos_ontology.core.compiler.kernel import build_compile_plan
from kairos_ontology.core.projections.dbt.gold_connection import GoldProductConfig
from kairos_ontology.core.projections.dbt.gold_specs import GoldContractError
from kairos_ontology.core.projections.medallion_gold_projector import (
    generate_gold_from_compile_plans,
)

_PRODUCT_HUB = Path(__file__).parent / "scenarios" / "v5-product-hub"

_PARTY_GOLD = """
@prefix party: <https://example.test/ontology/party#> .
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<https://example.test/ontology/party>
  kairos-ext:goldSchema "gold_party" ;
  kairos-ext:goldProductProfile "dimensional-powerbi-v1" ;
  kairos-ext:calendarProfile party:Calendar .

party:Calendar a kairos-ext:CalendarProfile ;
  kairos-ext:calendarStartDate "2020-01-01"^^xsd:date ;
  kairos-ext:calendarEndDate "2035-12-31"^^xsd:date ;
  kairos-ext:fiscalYearStartMonth 1 ;
  kairos-ext:weekPattern "iso-8601-monday" ;
  kairos-ext:calendarLocale "en-BE" ;
  kairos-ext:holidaySource "none-approved" ;
  kairos-ext:calendarTimeZone "Europe/Brussels" ;
  kairos-ext:periodClosurePolicy "finance-approved-period-status" ;
  kairos-ext:rolePlayingDate "SignUpDate=dim_customer.signed_up_on" ;
  kairos-ext:rolePlayingDate "{invoice_role}" ;
  kairos-ext:calendarApprovalStatus "approved" .

party:Customer
  kairos-ext:goldTableType "dimension" ;
  kairos-ext:goldTableName "dim_customer" ;
  kairos-ext:goldSourceModel "customer" ;
  kairos-ext:goldSourceVersion "1.0.0" ;
  kairos-ext:dimensionExposure "current-only" ;
  kairos-ext:dimensionVersionBinding "current" .
"""

_BILLING_GOLD = """
@prefix billing: <https://example.test/ontology/billing#> .
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

<https://example.test/ontology/billing>
  kairos-ext:goldSchema "gold_billing" ;
  kairos-ext:goldProductProfile "dimensional-powerbi-v1" {primary} .

billing:Invoice
  kairos-ext:goldTableType "fact" ;
  kairos-ext:goldTableName "fact_invoice" ;
  kairos-ext:goldSourceModel "invoice" ;
  kairos-ext:goldSourceVersion "1.0.0" ;
  kairos-ext:factGrain "one row per invoice" ;
  kairos-ext:factType "transaction" ;
  kairos-ext:dimensionVersionBinding "current" .
"""

_INVOICE_ROLE = "InvoiceDate=fact_invoice.invoice_date"
_CROSS_PRIMARY = "fact_invoice.invoice_date -> dim_date.full_date"
_PRODUCT = GoldProductConfig(name="invoicing", domains=("party", "billing"))


def _hub(tmp_path: Path, *, invoice_role: str = _INVOICE_ROLE, primary: str = "") -> Path:
    hub = tmp_path / "hub"
    shutil.copytree(_PRODUCT_HUB, hub)
    extensions = hub / "model" / "extensions"
    extensions.mkdir(parents=True, exist_ok=True)
    (extensions / "party-gold-ext.ttl").write_text(
        _PARTY_GOLD.format(invoice_role=invoice_role), encoding="utf-8"
    )
    (extensions / "billing-gold-ext.ttl").write_text(
        _BILLING_GOLD.format(
            primary=f';\n  kairos-ext:goldPrimaryRelationship "{primary}"' if primary else ""
        ),
        encoding="utf-8",
    )
    return hub


def _product(hub: Path) -> dict[str, str]:
    return generate_gold_from_compile_plans(
        [build_compile_plan(hub, domain) for domain in _PRODUCT.domains], _PRODUCT
    )


def _report(artifacts: dict[str, str]) -> dict:
    path = next(name for name in artifacts if name.endswith("-gold-product.json"))
    return json.loads(artifacts[path])


class TestCalendarRoleOnAnotherDomainsFact:
    """#1003: the calendar is in `party`, the fact it plays a role for is in `billing`."""

    def test_the_calendar_domain_compiles(self, tmp_path):
        plan = build_compile_plan(_hub(tmp_path), "party")
        assert not plan.blocked, [item.render() for item in plan.diagnostics.items]

    def test_the_role_is_deferred_and_reported(self, tmp_path):
        product = build_compile_plan(_hub(tmp_path), "party").shaped_project.gold_product
        assert product.deferred_references == (("rolePlayingDate", _INVOICE_ROLE),)
        # The role on its own domain's table is shaped as before.
        assert [role.role_name for role in product.calendar.roles] == ["SignUpDate"]

    def test_the_product_binds_both_roles(self, tmp_path):
        artifacts = _product(_hub(tmp_path))
        assert not _report(artifacts).get("deferred_references")
        relationships = artifacts["invoicing/Invoicing.SemanticModel/definition/relationships.tmdl"]
        assert "fromColumn: fact_invoice.invoice_date" in relationships
        assert "fromColumn: dim_customer.signed_up_on" in relationships

    def test_a_role_on_a_table_no_domain_has_fails_at_product_level(self, tmp_path):
        hub = _hub(tmp_path, invoice_role="InvoiceDate=fact_nowhere.invoice_date")
        with pytest.raises(GoldContractError) as excinfo:
            _product(hub)
        assert excinfo.value.code == "calendar.missing-role-column"

    def test_a_missing_column_on_a_table_in_scope_still_fails_per_domain(self, tmp_path):
        hub = _hub(tmp_path, invoice_role="InvoiceDate=dim_customer.no_such_date")
        plan = build_compile_plan(hub, "party")
        assert "calendar.missing-role-column" in {item.code for item in plan.diagnostics.items}

    def test_every_bad_role_is_named_not_just_the_first(self, tmp_path):
        hub = _hub(tmp_path, invoice_role="Other=dim_customer.also_nope")
        path = hub / "model" / "extensions" / "party-gold-ext.ttl"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                '"SignUpDate=dim_customer.signed_up_on"', '"SignUpDate=dim_customer.nope"'
            ),
            encoding="utf-8",
        )
        plan = build_compile_plan(hub, "party")
        (message,) = [
            item.message
            for item in plan.diagnostics.items
            if item.code == "calendar.missing-role-column"
        ]
        assert "2 calendar roles" in message
        assert "SignUpDate=dim_customer.nope" in message
        assert "Other=dim_customer.also_nope" in message


class TestPrimaryRelationshipToAnotherDomainsTable:
    """#1012: `billing` names an edge whose other end, `dim_date`, lives in `party`."""

    def test_the_declaring_domain_compiles_and_reports_it(self, tmp_path):
        plan = build_compile_plan(_hub(tmp_path, primary=_CROSS_PRIMARY), "billing")
        assert not plan.blocked, [item.render() for item in plan.diagnostics.items]
        assert plan.shaped_project.gold_product.deferred_references == (
            ("goldPrimaryRelationship", _CROSS_PRIMARY),
        )

    def test_the_product_accepts_it(self, tmp_path):
        artifacts = _product(_hub(tmp_path, primary=_CROSS_PRIMARY))
        assert not _report(artifacts).get("deferred_references")

    def test_a_stale_value_fails_at_product_level(self, tmp_path):
        hub = _hub(tmp_path, primary="fact_invoice.nope -> dim_date.full_date")
        assert not build_compile_plan(hub, "billing").blocked
        with pytest.raises(GoldContractError) as excinfo:
            _product(hub)
        assert excinfo.value.code == "gold.unknown-primary-relationship"


class TestTheDeferredReferenceIsPrinted:
    def test_compile_check_names_it(self, tmp_path, monkeypatch):
        from click.testing import CliRunner

        from kairos_ontology.cli.main import cli

        monkeypatch.chdir(_hub(tmp_path))
        result = CliRunner().invoke(cli, ["compile", "party", "--check"])
        assert result.exit_code == 0, result.output
        assert "name another domain's table" in result.output
        assert f"rolePlayingDate {_INVOICE_ROLE}" in result.output

    def test_the_json_payload_carries_it(self, tmp_path, monkeypatch):
        from click.testing import CliRunner

        from kairos_ontology.cli.main import cli

        monkeypatch.chdir(_hub(tmp_path))
        result = CliRunner().invoke(cli, ["compile", "party", "--check", "--format", "json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["deferred_references"] == [
            {"term": "rolePlayingDate", "value": _INVOICE_ROLE}
        ]
