# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Model-shape practices over a shaped Gold product (DD-240, issue #996).

On the Fracht hub 22 of 51 relationships were deactivated as ambiguous paths and listed
only in the product report. About 13 were ordinary role-playing dimensions; about 9 were
design problems -- facts pointing at facts, a dimension chain next to a direct edge -- and
both `compile --check` and `emit-gold` passed without saying so.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from kairos_ontology.core.projections.dbt.bpa_profile import (
    BpaIgnoreError,
    is_bpa_rule,
    parse_bpa_ignore,
)
from kairos_ontology.core.projections.dbt.gold_shape import _resolve_ambiguous_paths
from kairos_ontology.core.projections.dbt.gold_shape_checks import (
    active_route,
    check_model_shape,
)
from kairos_ontology.core.projections.dbt.gold_specs import (
    GoldContractError,
    GoldRelationshipSpec,
)
from kairos_ontology.core.projections.dbt.policy_specs import GoldTableRole

FACT, DIM = GoldTableRole.FACT, GoldTableRole.DIMENSION


def _tables(**roles):
    return tuple(
        SimpleNamespace(name=name, role=role, resource_uri=f"urn:{name}")
        for name, role in roles.items()
    )


def _edge(source, target, column=None, role=""):
    column = column or f"{target}_sk"
    return GoldRelationshipSpec(
        name=f"{source}_{column}",
        source_table=source,
        source_column=column,
        target_table=target,
        target_column=f"{target}_sk",
        cardinality="many-to-one",
        version_binding=None,
        role_name=role,
    )


def _shaped(*edges):
    return _resolve_ambiguous_paths(tuple(edges), frozenset())


def _codes(findings):
    return sorted(item.code for item in findings)


def _ignore(text):
    return parse_bpa_ignore(text)


class TestFactToFact:
    def test_a_fact_referencing_a_fact_is_reported(self):
        tables = _tables(fact_charge=FACT, fact_consignment=FACT, dim_job=DIM)
        relationships = _shaped(
            _edge("fact_charge", "fact_consignment"), _edge("fact_charge", "dim_job")
        )
        findings = check_model_shape(tables, relationships, ())
        assert _codes(findings) == ["gold.fact-to-fact"]
        assert "fact_charge.fact_consignment_sk -> fact_consignment" in findings[0].message

    def test_a_star_is_clean(self):
        tables = _tables(fact_a=FACT, dim_x=DIM, dim_y=DIM)
        relationships = _shaped(_edge("fact_a", "dim_x"), _edge("fact_a", "dim_y"))
        assert check_model_shape(tables, relationships, ()) == ()


class TestSnowflakeChainAndAmbiguousPath:
    """fact -> job -> branch next to fact -> branch: two routes for one filter."""

    @staticmethod
    def _model():
        tables = _tables(fact_consignment=FACT, dim_job=DIM, dim_branch=DIM)
        relationships = _shaped(
            _edge("fact_consignment", "dim_job"),
            _edge("fact_consignment", "dim_branch"),
            _edge("dim_job", "dim_branch"),
        )
        return tables, relationships

    def test_the_chain_and_the_deactivated_edge_are_both_reported(self):
        tables, relationships = self._model()
        findings = check_model_shape(tables, relationships, ())
        assert _codes(findings) == ["gold.ambiguous-path", "gold.snowflake-chain"]

    def test_the_ambiguous_path_names_the_active_route(self):
        tables, relationships = self._model()
        inactive = next(item for item in relationships if not item.is_active)
        finding = next(
            item
            for item in check_model_shape(tables, relationships, ())
            if item.code == "gold.ambiguous-path"
        )
        route = active_route(relationships, inactive.source_table, inactive.target_table)
        assert len(route) == 3
        assert " -> ".join(route) in finding.message

    def test_a_chain_the_fact_does_not_shortcut_is_an_ordinary_snowflake(self):
        tables = _tables(fact_a=FACT, dim_job=DIM, dim_branch=DIM)
        relationships = _shaped(_edge("fact_a", "dim_job"), _edge("dim_job", "dim_branch"))
        assert check_model_shape(tables, relationships, ()) == ()


class TestRolePlaying:
    def test_a_second_role_is_advisory_not_ambiguous(self):
        tables = _tables(fact_shipment=FACT, dim_location=DIM)
        relationships = _shaped(
            _edge("fact_shipment", "dim_location", "origin_sk"),
            _edge("fact_shipment", "dim_location", "destination_sk"),
        )
        findings = check_model_shape(tables, relationships, ())
        assert _codes(findings) == ["gold.role-playing-dimension"]
        assert "USERELATIONSHIP" in findings[0].message

    def test_roles_with_none_active_are_a_shape_problem(self):
        """The dimension reaches the fact by another route, so no role filters at all."""
        tables = _tables(fact_job=FACT, dim_branch=DIM, dim_staff=DIM)
        relationships = _resolve_ambiguous_paths(
            (
                _edge("fact_job", "dim_branch"),
                _edge("dim_branch", "dim_staff", "manager_sk"),
                _edge("fact_job", "dim_staff", "sales_rep_sk"),
                _edge("fact_job", "dim_staff", "operator_sk"),
            ),
            frozenset(),
        )
        findings = [
            item
            for item in check_model_shape(tables, relationships, ())
            if item.code == "gold.ambiguous-path"
        ]
        assert len(findings) == 2
        assert all("None of the 2 edges from fact_job to dim_staff" in f.message for f in findings)

    def test_the_calendar_counts_as_a_dimension(self):
        tables = _tables(fact_a=FACT)
        relationships = _shaped(
            _edge("fact_a", "dim_date", "order_date", role="order"),
            _edge("fact_a", "dim_date", "ship_date", role="ship"),
        )
        findings = check_model_shape(
            tables, relationships, (), extra_dimensions=frozenset({"dim_date"})
        )
        assert _codes(findings) == ["gold.role-playing-dimension"]


class TestExceptions:
    _TEXT = (
        "semantic-model.fact-to-fact on relationship "
        "fact_charge.fact_consignment_sk -> fact_consignment.fact_consignment_sk: "
        "charges are analysed per consignment by design"
    )

    def test_an_exception_excuses_the_finding(self):
        tables = _tables(fact_charge=FACT, fact_consignment=FACT)
        relationships = _shaped(_edge("fact_charge", "fact_consignment"))
        assert check_model_shape(tables, relationships, (_ignore(self._TEXT),)) == ()

    def test_an_exception_that_excuses_nothing_fails(self):
        tables = _tables(fact_charge=FACT, fact_consignment=DIM)
        relationships = _shaped(_edge("fact_charge", "fact_consignment"))
        with pytest.raises(GoldContractError) as raised:
            check_model_shape(tables, relationships, (_ignore(self._TEXT),))
        assert raised.value.code == "gold.bpa-ignore-unused"

    def test_a_practice_is_not_a_bpa_rule(self):
        """Only BPA rules become the TMDL annotation Tabular Editor reads."""
        assert not is_bpa_rule("semantic-model.fact-to-fact")
        assert is_bpa_rule("DAX_COLUMNS_FULLY_QUALIFIED")

    def test_a_practice_takes_only_the_objects_it_is_about(self):
        with pytest.raises(BpaIgnoreError) as raised:
            _ignore("semantic-model.fact-to-fact on table fact_charge: reason")
        assert raised.value.code == "gold.bpa-ignore-wrong-scope"

    def test_an_advice_only_practice_cannot_be_excused(self):
        with pytest.raises(BpaIgnoreError) as raised:
            _ignore("semantic-model.review-deactivated-relationships on model: reason")
        assert raised.value.code == "gold.bpa-unknown-rule"

    def test_the_reason_stays_mandatory(self):
        with pytest.raises(BpaIgnoreError) as raised:
            _ignore("semantic-model.fact-to-fact on relationship a.b -> c.d:")
        assert raised.value.code == "gold.bpa-ignore-malformed"


class TestCompileCheckProductPass:
    """`compile --check` shapes each product after its domains compile (DD-240)."""

    @staticmethod
    def _run(tmp_path, monkeypatch, *args):
        from click.testing import CliRunner

        from kairos_ontology.cli.main import cli
        from tests.test_gold_cross_domain_bridge import _cross_domain_hub

        monkeypatch.setenv("KAIROS_SKILL_CONTEXT", "1")
        monkeypatch.chdir(_cross_domain_hub(tmp_path))
        return CliRunner().invoke(cli, ["compile", *args, "--check"])

    def test_each_product_is_reported(self, tmp_path, monkeypatch):
        result = self._run(tmp_path, monkeypatch, "--all")
        assert result.exit_code == 0, result.output
        assert "Gold product billing: shape check clean" in result.output

    def test_a_product_that_cannot_shape_is_noted_not_failed(self, tmp_path, monkeypatch):
        """The bridge's other endpoint is in billing, which is not a party product member:
        emit-gold would fail, so the pass says so -- and the compile still passes."""
        result = self._run(tmp_path, monkeypatch, "--all")
        assert result.exit_code == 0, result.output
        assert "Gold product party: not shape-checked" in result.output
        assert "emit-gold fails the same way" in result.output

    def test_the_json_payload_carries_the_products(self, tmp_path, monkeypatch):
        import json

        result = self._run(tmp_path, monkeypatch, "billing", "--format", "json")
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output[result.output.index("{") :])
        assert payload["gold_products"] == [{"product": "billing", "diagnostics": []}]
