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


class TestTheDeferredEndpointIsPrinted:
    """Deferred on the plan but never shown: `compile party --check` was green with no word
    about the endpoint, and `emit-gold` on the product then failed on exactly that."""

    def test_compile_check_names_the_bridge_and_the_endpoint(self, tmp_path, monkeypatch):
        from click.testing import CliRunner

        from kairos_ontology.cli.main import cli

        monkeypatch.chdir(_cross_domain_hub(tmp_path))
        result = CliRunner().invoke(cli, ["compile", "party", "--check"])

        assert result.exit_code == 0, result.output
        assert "compile check passed" in result.output
        assert "bridge endpoint(s) are outside this domain" in result.output
        assert "bridge_customer_invoice -> https://example.test/ontology/billing#Invoice" in (
            result.output
        )

    def test_the_json_payload_carries_them_too(self, tmp_path, monkeypatch):
        from click.testing import CliRunner

        from kairos_ontology.cli.main import cli

        monkeypatch.chdir(_cross_domain_hub(tmp_path))
        result = CliRunner().invoke(cli, ["compile", "party", "--check", "--format", "json"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)  # the skill notice goes to stderr
        assert payload["unresolved_bridges"] == [
            {
                "bridge": "bridge_customer_invoice",
                "endpoint": "https://example.test/ontology/billing#Invoice",
            }
        ]


def _product_artifacts(hub: Path) -> dict[str, str]:
    product = GoldProductConfig(name="invoicing", domains=("party", "billing"))
    return generate_gold_from_compile_plans(
        [build_compile_plan(hub, domain) for domain in product.domains], product
    )


def _relationship_blocks(artifacts: dict[str, str]) -> dict[str, str]:
    """``toColumn`` -> the whole relationship block, so one edge can be asserted alone."""
    text = artifacts["invoicing/Invoicing.SemanticModel/definition/relationships.tmdl"]
    blocks = [block for block in text.split("relationship ") if block.strip()]
    return {
        line.split("toColumn: ", 1)[1].strip(): block
        for block in blocks
        for line in block.splitlines()
        if "toColumn: " in line
    }


def _with_cross_filter(hub: Path, value: str) -> Path:
    path = hub / "model" / "extensions" / "party-gold-ext.ttl"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\n<https://example.test/ontology/party> "
        + f'kairos-ext:goldRelationshipCrossFilter "{value}" .\n',
        encoding="utf-8",
    )
    return hub


class TestBridgeFilterDirection:
    """DD-238 / #977: a many-to-many bridge must let a far-side filter reach the fact."""

    def test_the_edge_to_the_fact_side_filters_both_ways(self, tmp_path):
        blocks = _relationship_blocks(_product_artifacts(_cross_domain_hub(tmp_path)))
        assert "crossFilteringBehavior: bothDirections" in blocks["fact_invoice.invoice_sk"]
        assert "crossFilteringBehavior" not in blocks["dim_customer.customer_sk"]

    def test_the_bidirectional_edge_records_that_it_was_checked(self, tmp_path):
        blocks = _relationship_blocks(_product_artifacts(_cross_domain_hub(tmp_path)))
        assert (
            "annotation BestPracticeAnalyzer_IgnoreRules = "
            '{"RuleIDs":["CHECK_IF_BI-DIRECTIONAL_AND_MANY-TO-MANY_RELATIONSHIPS_ARE_VALID"]}'
        ) in blocks["fact_invoice.invoice_sk"]

    def test_bridge_edges_render_no_cardinality(self, tmp_path):
        """Each edge is genuinely many-to-one; `bridgeCardinality` relates the endpoints."""
        artifacts = _product_artifacts(_cross_domain_hub(tmp_path))
        text = artifacts["invoicing/Invoicing.SemanticModel/definition/relationships.tmdl"]
        assert "Cardinality" not in text

    def test_the_report_names_the_edge_and_why(self, tmp_path):
        report = _report(_product_artifacts(_cross_domain_hub(tmp_path)))
        assert report["bidirectional_relationships"] == [
            {
                "from": "bridge_customer_invoice.country_name",
                "to": "fact_invoice.invoice_sk",
                "reason": "bridge-default",
            }
        ]
        assert "undecided_bridge_filters" not in report

    def test_the_author_can_turn_it_off(self, tmp_path):
        hub = _with_cross_filter(
            _cross_domain_hub(tmp_path),
            "bridge_customer_invoice.country_name -> fact_invoice.invoice_sk = single",
        )
        artifacts = _product_artifacts(hub)
        block = _relationship_blocks(artifacts)["fact_invoice.invoice_sk"]
        assert "crossFilteringBehavior" not in block
        assert "bidirectional_relationships" not in _report(artifacts)

    def test_the_author_can_turn_another_edge_on(self, tmp_path):
        hub = _with_cross_filter(
            _cross_domain_hub(tmp_path),
            "bridge_customer_invoice.code -> dim_customer.customer_sk = both",
        )
        report = _report(_product_artifacts(hub))
        assert {
            (item["to"], item["reason"]) for item in report["bidirectional_relationships"]
        } == {
            ("fact_invoice.invoice_sk", "bridge-default"),
            ("dim_customer.customer_sk", "authored"),
        }

    def test_a_stale_override_fails_closed_at_product_level(self, tmp_path):
        hub = _with_cross_filter(
            _cross_domain_hub(tmp_path),
            "bridge_customer_invoice.code -> dim_nope.customer_sk = both",
        )
        with pytest.raises(GoldContractError) as excinfo:
            _product_artifacts(hub)
        assert excinfo.value.code == "gold.unknown-relationship-cross-filter"

    def test_a_malformed_override_fails_the_domain_compile(self, tmp_path):
        """No edge is out of scope for a syntax error, so it fails in `compile --check`."""
        hub = _with_cross_filter(
            _cross_domain_hub(tmp_path),
            "bridge_customer_invoice.code -> dim_customer.customer_sk = sideways",
        )
        plan = build_compile_plan(hub, "party")
        assert "gold.unknown-relationship-cross-filter" in {
            item.code for item in plan.diagnostics.items
        }

    @pytest.mark.skipif(shutil.which("dotnet") is None, reason="dotnet SDK not installed")
    def test_the_bidirectional_model_deserializes_in_tom(self, tmp_path):
        from kairos_ontology.core.projections.dbt.tmdl_validate import validate_tmdl_artifacts

        results = validate_tmdl_artifacts(_product_artifacts(_cross_domain_hub(tmp_path)))
        assert results and all(item.status == "pass" for item in results), [
            item.message for item in results
        ]


class TestUndecidedBridge:
    """With no single fact-side endpoint the projector does not guess (DD-238)."""

    @staticmethod
    def _shape(tables, relationships, *overrides):
        from types import SimpleNamespace

        from kairos_ontology.core.projections.dbt.gold_shape import _bridge_cross_filters

        member = SimpleNamespace(
            policy=SimpleNamespace(
                gold=SimpleNamespace(relationship_cross_filters=overrides, ontology_uri="urn:t")
            )
        )
        return _bridge_cross_filters((member,), tables, relationships)

    @staticmethod
    def _fixture():
        from types import SimpleNamespace

        from kairos_ontology.core.projections.dbt.gold_specs import GoldRelationshipSpec
        from kairos_ontology.core.projections.dbt.policy_specs import (
            BridgeCardinality,
            GoldTableRole,
        )

        def table(name, role, cardinality=None):
            return SimpleNamespace(name=name, role=role, bridge_cardinality=cardinality)

        def edge(source, target):
            return GoldRelationshipSpec(
                name=f"{source}_{target}",
                source_table=source,
                source_column=f"{target}_sk",
                target_table=target,
                target_column=f"{target}_sk",
                cardinality="many-to-one",
                version_binding=None,
            )

        tables = (
            table("bridge_a_b", GoldTableRole.BRIDGE, BridgeCardinality.MANY_TO_MANY),
            table("dim_a", GoldTableRole.DIMENSION),
            table("dim_b", GoldTableRole.DIMENSION),
        )
        return tables, (edge("bridge_a_b", "dim_a"), edge("bridge_a_b", "dim_b"))

    def test_two_dimensions_leave_it_single_and_reported(self):
        tables, relationships = self._fixture()
        shaped, undecided = self._shape(tables, relationships)
        assert not any(item.bidirectional for item in shaped)
        assert undecided == ("bridge_a_b",)

    def test_an_authored_direction_decides_it(self):
        tables, relationships = self._fixture()
        shaped, undecided = self._shape(
            tables, relationships, "bridge_a_b.dim_a_sk -> dim_a.dim_a_sk = both"
        )
        assert [item.target_table for item in shaped if item.bidirectional] == ["dim_a"]
        assert undecided == ()


def test_a_model_without_bridges_keeps_its_relationship_bytes():
    """DD-226's compatibility promise, restated for DD-238: no bridge, no new lines."""
    import tests.test_gold_projector as harness

    artifacts = harness._generate("invoice")
    relationships = next(
        content for path, content in artifacts.items() if path.endswith("/relationships.tmdl")
    )
    assert "crossFilteringBehavior" not in relationships
    assert "Cardinality" not in relationships
    report = harness._report(artifacts, "invoice")
    assert "bidirectional_relationships" not in report
    assert "undecided_bridge_filters" not in report


@pytest.mark.parametrize(
    ("cardinality", "lines"),
    [
        ("many-to-one", []),
        ("one-to-one", ["\tfromCardinality: one"]),
        ("many-to-many", ["\ttoCardinality: many"]),
        ("one-to-many", ["\tfromCardinality: one", "\ttoCardinality: many"]),
    ],
)
def test_cardinality_renders_only_where_it_departs_from_many_to_one(cardinality, lines):
    from kairos_ontology.core.projections.dbt.gold_render import _cardinality_lines

    assert _cardinality_lines(cardinality) == lines
