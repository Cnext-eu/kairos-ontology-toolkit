# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""A bridge may span two domains, so a single-domain compile must not reject it (#763).

`gold_shape` documents its bridge-endpoint check as running "over the union, not per
domain: a bridge may span two domains' tables". But `compile <domain> --check` reaches that
same code through `_shape_dimensional`, which wraps one domain in a 1-tuple — so the union
was a union of one and the check could never pass for a cross-domain bridge.

The result was that the one construct giving Power BI a slicer across two facts — the
reason `bridge` exists at all — could not be authored on a multi-domain product. Both the
per-domain `compile --check` and `emit-gold` (which compiles each member first) failed, and
the error pointed at a binding that was correct.

The check is now deferred on the single-domain path and reported as `unresolved_bridges`.
At product level the union is real, so an endpoint genuinely outside it still fails closed.
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

# `party:Country` is bound but deliberately has no Gold table in the sibling fixture, so it
# is free to act as the bridge here without disturbing those tests. Its own emitted
# columns (`code`, `country_name`) stand in for the endpoint key columns: a binding
# column must be a real Silver column of the bridge model, and what is under test is the
# endpoint *resolution*, not the join's business meaning.
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

party:Country
  kairos-ext:goldTableType "bridge" ;
  kairos-ext:goldTableName "bridge_customer_invoice" ;
  kairos-ext:goldSourceModel "country" ;
  kairos-ext:goldSourceVersion "1.0.0" ;
  kairos-ext:bridgeGrain "one row per customer and invoice" ;
  kairos-ext:bridgeEndpoint <https://example.test/ontology/party#Customer> ;
  kairos-ext:bridgeEndpoint {other_endpoint} ;
  kairos-ext:bridgeEndpointBinding "Customer=code" ;
  kairos-ext:bridgeEndpointBinding "{other_binding}" ;
  kairos-ext:bridgeCardinality "many-to-many" ;
  kairos-ext:bridgeAllocationSemantics "equal-weight" .
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

_CROSS_DOMAIN = "<https://example.test/ontology/billing#Invoice>"
_UNKNOWN = "<https://example.test/ontology/billing#NoSuchClass>"


def _hub(tmp_path: Path, *, other_endpoint: str, other_binding: str) -> Path:
    hub = tmp_path / "hub"
    shutil.copytree(_PRODUCT_HUB, hub)
    extensions = hub / "model" / "extensions"
    extensions.mkdir(parents=True, exist_ok=True)
    (extensions / "party-gold-ext.ttl").write_text(
        _PARTY_GOLD.format(other_endpoint=other_endpoint, other_binding=other_binding),
        encoding="utf-8",
    )
    (extensions / "billing-gold-ext.ttl").write_text(_BILLING_GOLD, encoding="utf-8")
    return hub


def _cross_domain_hub(tmp_path: Path) -> Path:
    return _hub(tmp_path, other_endpoint=_CROSS_DOMAIN, other_binding="Invoice=country_name")


def _report(artifacts: dict[str, str]) -> dict:
    path = next(name for name in artifacts if name.endswith("-gold-product.json"))
    return json.loads(artifacts[path])


class TestSingleDomainCompile:
    """`compile party --check` sees only `party`, so the billing endpoint is out of scope."""

    def test_the_domain_compiles_rather_than_blocking(self, tmp_path):
        plan = build_compile_plan(_cross_domain_hub(tmp_path), "party")
        assert not plan.blocked, [item.render() for item in plan.diagnostics.items]

    def test_the_deferred_endpoint_is_reported_not_silent(self, tmp_path):
        """Deferring must not mean forgetting: the plan records what it could not resolve."""
        plan = build_compile_plan(_cross_domain_hub(tmp_path), "party")
        assert plan.shaped_project.gold_product.unresolved_bridges == (
            ("bridge_customer_invoice", "https://example.test/ontology/billing#Invoice"),
        )

    def test_the_bridge_itself_is_still_shaped(self, tmp_path):
        """Only the edge it cannot resolve is missing; the table is emitted as authored."""
        plan = build_compile_plan(_cross_domain_hub(tmp_path), "party")
        product = plan.shaped_project.gold_product
        assert "bridge_customer_invoice" in {table.name for table in product.tables}
        # ...and no relationship points at a table this shaping does not have.
        targets = {item.target_table for item in product.relationships}
        assert "fact_invoice" not in targets

    def test_a_single_domain_product_is_still_strict(self, tmp_path):
        """`compile --check` defers; declaring a one-domain *product* does not.

        At product level the union is complete by definition, so an endpoint outside it is
        an authoring error rather than something to wait for.
        """
        hub = _cross_domain_hub(tmp_path)
        with pytest.raises(GoldContractError) as excinfo:
            generate_gold_from_compile_plans(
                [build_compile_plan(hub, "party")],
                GoldProductConfig(name="party", domains=("party",)),
            )
        assert excinfo.value.code == "gold.bridge-endpoint-not-materialized"


class TestProductLevelShaping:
    """With both domains present the union is real and the bridge resolves."""

    def test_both_bridge_relationships_are_emitted(self, tmp_path):
        hub = _cross_domain_hub(tmp_path)
        product = GoldProductConfig(name="invoicing", domains=("party", "billing"))
        artifacts = generate_gold_from_compile_plans(
            [build_compile_plan(hub, domain) for domain in product.domains], product
        )

        assert not _report(artifacts).get("unresolved_bridges")
        relationships = artifacts[
            "invoicing/Invoicing.SemanticModel/definition/relationships.tmdl"
        ]
        assert "bridge_customer_invoice.code" in relationships
        assert "bridge_customer_invoice.country_name" in relationships

    def test_an_endpoint_outside_the_union_still_fails_closed(self, tmp_path):
        """Deferring must not become 'never check'. A genuinely unknown endpoint is an
        authoring error, and at product level there is no wider union to wait for."""
        hub = _hub(
            tmp_path,
            other_endpoint=_UNKNOWN,
            other_binding="NoSuchClass=country_name",
        )
        product = GoldProductConfig(name="invoicing", domains=("party", "billing"))
        with pytest.raises(GoldContractError) as excinfo:
            generate_gold_from_compile_plans(
                [build_compile_plan(hub, domain) for domain in product.domains], product
            )
        assert excinfo.value.code in {
            "gold.bridge-endpoint-not-materialized",
            "gold.invalid-bridge-endpoint-binding",
        }
