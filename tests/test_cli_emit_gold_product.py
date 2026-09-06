# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""``emit-gold`` over a declared multi-domain product (issue #744, DD-222).

The command used to take a domain and build one compile plan. It now takes a *product* --
a domain name still works, and resolves to the implicit product of the same name -- and
builds one compile plan per participating domain.

The interesting cases are at the edges: a hub that declares nothing must be unchanged, a
member domain must not be emitted on its own, and moving a domain into a product must not
leave its old semantic model behind on disk for fabric-cicd to deploy alongside the new one.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.hub_utils import publish_root

_PRODUCT_HUB = Path(__file__).parent / "scenarios" / "v5-product-hub"

_PARTY_GOLD = """
@prefix party: <https://example.test/ontology/party#> .
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

<https://example.test/ontology/party>
  kairos-ext:goldSchema "gold_party" ;
  kairos-ext:goldProductProfile "dimensional-powerbi-v1" .

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
  kairos-ext:goldProductProfile "dimensional-powerbi-v1" .

billing:Invoice
  kairos-ext:goldTableType "fact" ;
  kairos-ext:goldTableName "fact_invoice" ;
  kairos-ext:goldSourceModel "invoice" ;
  kairos-ext:goldSourceVersion "1.0.0" ;
  kairos-ext:factGrain "one row per invoice" ;
  kairos-ext:factType "transaction" ;
  kairos-ext:dimensionVersionBinding "current" .
"""

_PRODUCTS = """
  products:
    - name: invoicing
      domains: [billing, party]
"""


def _hub(tmp_path: Path, *, declare_product: bool = True) -> Path:
    hub = tmp_path / "hub"
    shutil.copytree(_PRODUCT_HUB, hub)
    extensions = hub / "model" / "extensions"
    extensions.mkdir(parents=True, exist_ok=True)
    (extensions / "party-gold-ext.ttl").write_text(_PARTY_GOLD, encoding="utf-8")
    (extensions / "billing-gold-ext.ttl").write_text(_BILLING_GOLD, encoding="utf-8")
    if declare_product:
        config = hub / "kairos.yaml"
        config.write_text(config.read_text(encoding="utf-8") + _PRODUCTS, encoding="utf-8")
    return hub


def _emit(hub: Path, name: str, monkeypatch, *args: str):
    monkeypatch.chdir(hub)
    return CliRunner().invoke(cli, ["emit-gold", name, *args])


def _gold_dir(hub: Path) -> Path:
    return publish_root(hub) / "powerbi"


def test_a_declared_product_emits_one_model_for_both_domains(tmp_path, monkeypatch):
    hub = _hub(tmp_path)

    result = _emit(hub, "invoicing", monkeypatch, "--confirm-emit")

    assert result.exit_code == 0, result.output
    assert "billing, party" in result.output
    definition = _gold_dir(hub) / "invoicing" / "Invoicing.SemanticModel" / "definition"
    assert (definition / "tables" / "fact_invoice.tmdl").is_file()
    assert (definition / "tables" / "dim_customer.tmdl").is_file()
    relationships = (definition / "relationships.tmdl").read_text(encoding="utf-8")
    assert "toColumn: dim_customer.customer_sk" in relationships


def test_each_domain_still_gets_its_own_provenance_sidecar(tmp_path, monkeypatch):
    """A product has no build scope of its own; each domain it compiled has one."""
    hub = _hub(tmp_path)

    _emit(hub, "invoicing", monkeypatch, "--confirm-emit")

    metadata = _gold_dir(hub) / "metadata"
    assert (metadata / "billing-gold.provenance.json").is_file()
    assert (metadata / "party-gold.provenance.json").is_file()


def test_emitting_a_member_domain_points_at_the_product(tmp_path, monkeypatch):
    """Emitting `billing` alone is what produced the broken model #744 reports."""
    hub = _hub(tmp_path)

    result = _emit(hub, "billing", monkeypatch)

    assert result.exit_code != 0
    assert "emit-gold invoicing" in result.output


def test_a_hub_declaring_no_product_is_unchanged(tmp_path, monkeypatch):
    hub = _hub(tmp_path, declare_product=False)

    result = _emit(hub, "party", monkeypatch, "--confirm-emit")

    assert result.exit_code == 0, result.output
    assert (
        _gold_dir(hub) / "party" / "Party.SemanticModel" / "definition" / "model.tmdl"
    ).is_file()
    assert (_gold_dir(hub) / ".kairos-compile-manifest.gold-party.json").is_file()


def test_moving_a_domain_into_a_product_retires_its_old_model(tmp_path, monkeypatch):
    """Otherwise fabric-cicd deploys the superseded per-domain model beside the product.

    ``emit_artifacts`` only removes files its own manifest owns, so the stale tree and its
    ERD would survive every later emit and be picked up by the master-ERD disk scan.
    """
    hub = _hub(tmp_path, declare_product=False)
    _emit(hub, "billing", monkeypatch, "--confirm-emit")
    _emit(hub, "party", monkeypatch, "--confirm-emit")
    assert (_gold_dir(hub) / "billing" / "Billing.SemanticModel").is_dir()

    config = hub / "kairos.yaml"
    config.write_text(config.read_text(encoding="utf-8") + _PRODUCTS, encoding="utf-8")
    result = _emit(hub, "invoicing", monkeypatch, "--confirm-emit")

    assert result.exit_code == 0, result.output
    assert "retired the superseded per-domain emit" in result.output
    assert not (_gold_dir(hub) / "billing" / "Billing.SemanticModel").exists()
    assert not (_gold_dir(hub) / "party" / "Party.SemanticModel").exists()
    assert not (_gold_dir(hub) / ".kairos-compile-manifest.gold-billing.json").exists()
    assert (_gold_dir(hub) / "invoicing" / "Invoicing.SemanticModel").is_dir()


def test_the_dangling_relationship_is_reported_to_the_operator(tmp_path, monkeypatch):
    """`party:Country` is materialized but no domain authors a Gold table for it."""
    hub = _hub(tmp_path)

    result = _emit(hub, "invoicing", monkeypatch)

    assert result.exit_code == 0, result.output
    assert "no target table in this product" in result.output
    assert "dim_customer -> https://example.test/ontology/party#Country" in result.output


def test_repeated_product_emit_is_idempotent(tmp_path, monkeypatch):
    hub = _hub(tmp_path)

    for _ in range(2):
        result = _emit(hub, "invoicing", monkeypatch, "--confirm-emit")
        assert result.exit_code == 0, result.output


_INSIGHTS = """
schema_version: "1"
personas:
  - id: ops-manager
    description: Runs invoicing day to day
insights:
  - id: invoiced-value
    persona: ops-manager
    question: How much did we invoice this month, by customer?
    kpi: Invoiced value
    comparison: prior month
    product: invoicing
    measures: [Invoiced Value]
    dimensions: [dim_customer.customer_name]
    status: confirmed
"""


def _write_insights(hub: Path) -> None:
    path = hub / "integration" / "discovery" / "bi"
    path.mkdir(parents=True, exist_ok=True)
    (path / "insights.yaml").write_text(_INSIGHTS, encoding="utf-8")


def test_an_authored_insight_produces_a_brief(tmp_path, monkeypatch):
    hub = _hub(tmp_path)
    _write_insights(hub)

    result = _emit(hub, "invoicing", monkeypatch, "--confirm-emit")

    assert result.exit_code == 0, result.output
    brief = (_gold_dir(hub) / "invoicing" / "invoicing-insight-brief.md").read_text(
        encoding="utf-8"
    )
    assert "How much did we invoice this month, by customer?" in brief
    assert "## ops-manager — Runs invoicing day to day" in brief


def test_an_unanswerable_insight_is_reported_without_failing(tmp_path, monkeypatch):
    """The gap between what the business wants and what the model answers is a backlog."""
    hub = _hub(tmp_path)
    _write_insights(hub)

    result = _emit(hub, "invoicing", monkeypatch, "--confirm-emit")

    assert result.exit_code == 0, result.output
    assert "0/1 confirmed insight(s) answerable" in result.output
    assert "invoiced-value: missing Invoiced Value" in result.output


def test_a_hub_without_insights_gets_no_brief(tmp_path, monkeypatch):
    hub = _hub(tmp_path)

    result = _emit(hub, "invoicing", monkeypatch, "--confirm-emit")

    assert result.exit_code == 0, result.output
    assert not (_gold_dir(hub) / "invoicing" / "invoicing-insight-brief.md").exists()
    assert "confirmed insight" not in result.output


def test_a_malformed_insights_file_is_reported_not_traced(tmp_path, monkeypatch):
    """The brief is built during rendering, so a bad file surfaces there first.

    Without an explicit handler the operator got a Python traceback for a stray tab in
    their own YAML, which is exactly what the coverage report's message exists to prevent.
    """
    hub = _hub(tmp_path)
    path = hub / "integration" / "discovery" / "bi"
    path.mkdir(parents=True, exist_ok=True)
    (path / "insights.yaml").write_text("insights:\n  - id: x\n", encoding="utf-8")

    result = _emit(hub, "invoicing", monkeypatch, "--confirm-emit")

    assert result.exit_code != 0
    assert "insights.yaml is unusable" in result.output
    assert "Traceback" not in result.output
