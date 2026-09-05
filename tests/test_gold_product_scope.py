# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Gold product scope spans ontology domains (issue #744, DD-222).

A Gold product was hard-wired to exactly one ontology domain. Product identity came from
a single `CompilePlan`'s `ontology_name`, every emitted path was derived from it, and
`_shape_relationships` dropped any foreign key whose target class lived in another
domain -- silently, with no diagnostic, leaving a dead surrogate-key column on the fact.

Ontology domains are a modelling boundary. Analytical products follow business processes:
facts from one domain, conformed dimensions from several others. This module pins the
product as the unit of delivery while the domain stays the unit of compilation.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from kairos_ontology.core.compiler.kernel import build_compile_plan
from kairos_ontology.core.projections.dbt.gold_connection import (
    GoldProductConfig,
    parse_gold_products,
    resolve_gold_product,
)
from kairos_ontology.core.projections.dbt.gold_shape import _sole
from kairos_ontology.core.projections.dbt.gold_specs import GoldContractError
from kairos_ontology.core.projections.medallion_gold_projector import (
    generate_gold_from_compile_plans,
)

_PRODUCT_HUB = Path(__file__).parent / "scenarios" / "v5-product-hub"

_PARTY_GOLD = """
@prefix party: <https://example.test/ontology/party#> .
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

<https://example.test/ontology/party>
  kairos-ext:goldSchema "gold_party" ;
{extra}  kairos-ext:goldProductProfile "dimensional-powerbi-v1" .

party:Customer
  kairos-ext:goldTableType "dimension" ;
  kairos-ext:goldTableName "{customer_table}" ;
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
{extra}  kairos-ext:goldProductProfile "dimensional-powerbi-v1" .

billing:Invoice
  kairos-ext:goldTableType "fact" ;
  kairos-ext:goldTableName "{invoice_table}" ;
  kairos-ext:goldSourceModel "invoice" ;
  kairos-ext:goldSourceVersion "1.0.0" ;
  kairos-ext:factGrain "one row per invoice" ;
  kairos-ext:factType "transaction" ;
  kairos-ext:dimensionVersionBinding "current" .
"""


def _hub(
    tmp_path: Path,
    *,
    party: bool = True,
    billing: bool = True,
    party_extra: str = "",
    billing_extra: str = "",
    customer_table: str = "dim_customer",
    invoice_table: str = "fact_invoice",
    products_yaml: str = "",
) -> Path:
    hub = tmp_path / "hub"
    shutil.copytree(_PRODUCT_HUB, hub)
    extensions = hub / "model" / "extensions"
    extensions.mkdir(parents=True, exist_ok=True)
    if party:
        (extensions / "party-gold-ext.ttl").write_text(
            _PARTY_GOLD.format(extra=party_extra, customer_table=customer_table),
            encoding="utf-8",
        )
    if billing:
        (extensions / "billing-gold-ext.ttl").write_text(
            _BILLING_GOLD.format(extra=billing_extra, invoice_table=invoice_table),
            encoding="utf-8",
        )
    if products_yaml:
        config = hub / "kairos.yaml"
        config.write_text(config.read_text(encoding="utf-8") + products_yaml, encoding="utf-8")
    return hub


def _emit(hub: Path, product: GoldProductConfig) -> dict[str, str]:
    plans = [build_compile_plan(hub, domain) for domain in product.domains]
    return generate_gold_from_compile_plans(plans, product)


def _report(artifacts: dict[str, str]) -> dict:
    path = next(name for name in artifacts if name.endswith("-gold-product.json"))
    return json.loads(artifacts[path])


_INVOICING = GoldProductConfig(name="invoicing", domains=("billing", "party"))


@pytest.fixture(scope="module")
def artifacts(tmp_path_factory) -> dict[str, str]:
    """The two-domain product, emitted once: a compile plan per test is slow."""
    return _emit(_hub(tmp_path_factory.mktemp("product")), _INVOICING)


class TestCrossDomainRelationships:
    """The core defect: a fact joined to a dimension its own domain does not own."""

    def test_the_cross_domain_join_is_emitted(self, artifacts):
        relationships = artifacts["invoicing/Invoicing.SemanticModel/definition/relationships.tmdl"]
        assert "fromColumn: fact_invoice.customer_sk" in relationships
        assert "toColumn: dim_customer.customer_sk" in relationships

    def test_both_domains_contribute_tables(self, artifacts):
        tables = {
            name.rsplit("/", 1)[-1].removesuffix(".tmdl")
            for name in artifacts
            if "/definition/tables/" in name
        }
        assert tables == {"dim_customer", "fact_invoice"}

    def test_the_product_records_its_domains(self, artifacts):
        assert _report(artifacts)["domains"] == ["billing", "party"]

    def test_each_domain_keeps_its_own_schema(self, artifacts):
        """Physical tables stay owned by the domain that binds them."""
        ddl = artifacts["invoicing/invoicing-gold-ddl.sql"]
        assert "CREATE SCHEMA IF NOT EXISTS gold_billing;" in ddl
        assert "CREATE SCHEMA IF NOT EXISTS gold_party;" in ddl

    def test_provenance_is_recorded_per_domain(self, artifacts):
        """A product has no compile of its own, so it has no single provenance hash."""
        parity = _report(artifacts)["silver_authority"]["parity"]
        assert set(parity["provenance_hash"]) == {"billing", "party"}


class TestUnresolvedRelationships:
    """A dangling foreign key is reported, not silently dropped (reverses #207/#661)."""

    def test_a_target_outside_the_product_is_reported(self, tmp_path):
        # `party:Country` is bound and materialized, but no domain authors a Gold table
        # for it, so `dim_customer.country_sk` has nothing to join to.
        artifacts = _emit(_hub(tmp_path), _INVOICING)
        unresolved = _report(artifacts)["unresolved_relationships"]
        assert [item["source_table"] for item in unresolved] == ["dim_customer"]
        assert unresolved[0]["target_class"].endswith("#Country")

    def test_a_resolved_product_reports_nothing(self, tmp_path):
        party_with_country = (
            _PARTY_GOLD
            + """
party:Country
  kairos-ext:goldTableType "dimension" ;
  kairos-ext:goldTableName "dim_country" ;
  kairos-ext:goldSourceModel "country" ;
  kairos-ext:goldSourceVersion "1.0.0" ;
  kairos-ext:dimensionExposure "current-only" ;
  kairos-ext:dimensionVersionBinding "current" .
"""
        )
        hub = _hub(tmp_path)
        (hub / "model" / "extensions" / "party-gold-ext.ttl").write_text(
            party_with_country.format(extra="", customer_table="dim_customer"),
            encoding="utf-8",
        )
        artifacts = _emit(hub, _INVOICING)
        assert "unresolved_relationships" not in _report(artifacts)
        relationships = artifacts["invoicing/Invoicing.SemanticModel/definition/relationships.tmdl"]
        assert "toColumn: dim_country.country_sk" in relationships


class TestSingleDomainIsUnchanged:
    """A hub that declares no product must emit exactly what it emitted before."""

    def test_paths_are_still_named_after_the_domain(self, tmp_path):
        solo = GoldProductConfig(name="billing", domains=("billing",), declared=False)
        artifacts = _emit(_hub(tmp_path, party=False), solo)
        assert "billing/Billing.SemanticModel/definition/model.tmdl" in artifacts
        assert "billing/billing-gold-product.json" in artifacts

    def test_no_product_keys_are_added_to_the_report(self, tmp_path):
        """Adding a key to every existing hub's report would be pure churn."""
        solo = GoldProductConfig(name="party", domains=("party",), declared=False)
        report = _report(_emit(_hub(tmp_path, billing=False), solo))
        assert "domains" not in report
        assert isinstance(report["silver_authority"]["parity"]["provenance_hash"], str)


class TestProductCollisions:
    def test_two_domains_cannot_emit_the_same_table_name(self, tmp_path):
        hub = _hub(tmp_path, invoice_table="dim_customer")
        with pytest.raises(GoldContractError) as excinfo:
            _emit(hub, _INVOICING)
        assert excinfo.value.code == "gold.product-table-name-collision"

    def test_two_domains_cannot_emit_the_same_measure_id(self, tmp_path):
        measure = """  kairos-ext:measure <https://example.test/measure/{domain}> ;
"""
        body = """
<https://example.test/measure/{domain}> a kairos-ext:Measure ;
  kairos-ext:measureId "Row Count" ;
  kairos-ext:measureDefinition "Rows in {table}." ;
  kairos-ext:measureExpression "COUNTROWS('{table}')" ;
  kairos-ext:measureColumnDependency "{table}.{column}" ;
  kairos-ext:measureLifecycleState "provisional" ;
  kairos-ext:measureDataType "int64" ;
  kairos-ext:measureFormatString "#,0" ;
  kairos-ext:measureFolder "Volume" .
"""
        hub = _hub(
            tmp_path,
            party_extra=measure.format(domain="party"),
            billing_extra=measure.format(domain="billing"),
        )
        for domain, table, column in (
            ("party", "dim_customer", "customer_id"),
            ("billing", "fact_invoice", "invoice_id"),
        ):
            path = hub / "model" / "extensions" / f"{domain}-gold-ext.ttl"
            path.write_text(
                path.read_text(encoding="utf-8")
                + body.format(domain=domain, table=table, column=column),
                encoding="utf-8",
            )
        with pytest.raises(GoldContractError) as excinfo:
            _emit(hub, _INVOICING)
        assert excinfo.value.code == "gold.product-measure-id-collision"


class TestSoleDeclaration:
    """One participating domain declares the calendar; the product inherits it (#744).

    Exercised directly rather than through a hub: a `CalendarProfile` is only valid with
    `rolePlayingDate` bindings onto an emitted fact column, so a second domain declaring
    one blocks its *own* compile long before product assembly runs. The rule under test
    is the assembly rule, and this is where it lives.
    """

    @staticmethod
    def _member(name: str, declares: bool):
        return SimpleNamespace(
            ontology_name=name,
            policy=SimpleNamespace(gold=SimpleNamespace(calendar="calendar" if declares else None)),
        )

    def test_no_declaration_yields_nothing(self):
        members = (self._member("a", False), self._member("b", False))
        assert _sole(members, lambda m: m.policy.gold.calendar, code="x", what="calendar") is None

    def test_one_declaration_is_inherited_by_the_product(self):
        members = (self._member("a", False), self._member("b", True))
        chosen = _sole(members, lambda m: m.policy.gold.calendar, code="x", what="calendar")
        assert chosen.ontology_name == "b"

    def test_two_declarations_fail_rather_than_pick_one(self):
        members = (self._member("a", True), self._member("b", True))
        with pytest.raises(GoldContractError) as excinfo:
            _sole(
                members,
                lambda m: m.policy.gold.calendar,
                code="gold.product-calendar-conflict",
                what="calendar profile",
            )
        assert excinfo.value.code == "gold.product-calendar-conflict"
        assert "a, b" in str(excinfo.value)


class TestProductConfig:
    def test_a_hub_without_the_block_declares_nothing(self):
        assert parse_gold_products({"gold": {}}) == ()
        assert parse_gold_products({}) == ()

    def test_a_product_parses(self):
        (product,) = parse_gold_products(
            {"gold": {"products": [{"name": "invoicing", "domains": ["billing", "party"]}]}}
        )
        assert product.name == "invoicing"
        assert product.domains == ("billing", "party")
        assert product.model_name == "Invoicing"

    def test_the_display_name_names_the_fabric_item_not_the_path(self):
        (product,) = parse_gold_products(
            {
                "gold": {
                    "products": [
                        {
                            "name": "bookings-overview",
                            "domains": ["billing"],
                            "display_name": "Bookings Overview",
                        }
                    ]
                }
            }
        )
        assert product.display_name == "Bookings Overview"
        # Paths stay path-safe regardless of what the workspace calls the item.
        assert product.model_name == "BookingsOverview"

    def test_a_hyphenated_name_becomes_pascal_case(self):
        (product,) = parse_gold_products(
            {"gold": {"products": [{"name": "bookings-overview", "domains": ["billing"]}]}}
        )
        assert product.model_name == "BookingsOverview"

    @pytest.mark.parametrize(
        "products",
        [
            [{"name": "Invoicing", "domains": ["billing"]}],
            [{"name": "invoicing", "domains": []}],
            [{"name": "invoicing"}],
            [{"name": "invoicing", "domains": ["billing"], "extra": 1}],
            [
                {"name": "a", "domains": ["billing"]},
                {"name": "b", "domains": ["billing"]},
            ],
        ],
        ids=["upper-case", "no-domains", "missing-domains", "unknown-key", "shared-domain"],
    )
    def test_malformed_products_fail_closed(self, products):
        with pytest.raises(GoldContractError) as excinfo:
            parse_gold_products({"gold": {"products": products}})
        assert excinfo.value.code == "gold.products-invalid"


class TestProductResolution:
    _YAML = """
  products:
    - name: invoicing
      domains: [billing, party]
"""

    def test_a_declared_product_resolves(self, tmp_path):
        hub = _hub(tmp_path, products_yaml=self._YAML)
        product = resolve_gold_product(hub, "invoicing", hub_domains=("billing", "party"))
        assert product.domains == ("billing", "party")
        assert product.declared

    def test_a_claimed_domain_points_at_its_product(self, tmp_path):
        """Emitting a member domain alone would produce the broken model #744 reports."""
        hub = _hub(tmp_path, products_yaml=self._YAML)
        with pytest.raises(GoldContractError) as excinfo:
            resolve_gold_product(hub, "billing", hub_domains=("billing", "party"))
        assert excinfo.value.code == "gold.domain-belongs-to-product"
        assert "emit-gold invoicing" in str(excinfo.value)

    def test_an_unclaimed_domain_is_its_own_product(self, tmp_path):
        hub = _hub(tmp_path)
        product = resolve_gold_product(hub, "party", hub_domains=("billing", "party"))
        assert product == GoldProductConfig(name="party", domains=("party",), declared=False)

    def test_an_unknown_name_fails(self, tmp_path):
        hub = _hub(tmp_path)
        with pytest.raises(GoldContractError) as excinfo:
            resolve_gold_product(hub, "nope", hub_domains=("billing", "party"))
        assert excinfo.value.code == "gold.unknown-product"
