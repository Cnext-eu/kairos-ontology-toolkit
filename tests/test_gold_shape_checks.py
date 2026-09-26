# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Model-shape practices over a shaped Gold product (DD-240, issue #996).

On the Fracht hub 22 of 51 relationships were deactivated as ambiguous paths and listed
only in the product report. About 13 were ordinary role-playing dimensions; about 9 were
design problems -- facts pointing at facts, a dimension chain next to a direct edge -- and
both `compile --check` and `emit-gold` passed without saying so. The Kimball rules extend
the same pass: a star over a snowflake, a date on every fact, snapshots summed the way a
snapshot can be, one conformed dimension per concept, one process per product.
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
    bus_matrix,
    check_model_shape,
    second_route,
)
from kairos_ontology.core.projections.dbt.gold_specs import (
    GoldContractError,
    GoldMeasureSpec,
    GoldRelationshipSpec,
)
from kairos_ontology.core.projections.dbt.policy_specs import (
    BridgeCardinality,
    FactType,
    GoldTableRole,
    MeasureLifecycle,
)

FACT, DIM, BRIDGE = GoldTableRole.FACT, GoldTableRole.DIMENSION, GoldTableRole.BRIDGE


def _table(name, role, **extra):
    fields = {
        "name": name,
        "role": role,
        "resource_uri": f"urn:{name}",
        "source_model": name,
        "fact_type": None,
        "bridge_weight_column": "",
        "bridge_cardinality": None,
        "bridge_allocation": "",
    }
    fields.update(extra)
    return SimpleNamespace(**fields)


def _tables(**roles):
    return tuple(_table(name, role) for name, role in roles.items())


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


def _measure(measure_id, home, expression, columns=()):
    return GoldMeasureSpec(
        resource_uri=f"urn:{measure_id}",
        measure_id=measure_id,
        definition="d",
        expression=expression,
        lifecycle=MeasureLifecycle.APPROVED,
        home_table=home,
        column_dependencies=tuple(columns),
        measure_dependencies=(),
        data_type="decimal",
        format_string="0",
        folder="",
        owner_role="",
        tests=(),
        evidence=(),
        emitted=True,
    )


def _codes(findings):
    return sorted(item.code for item in findings)


def _only(findings, code):
    return [item for item in findings if item.code == code]


def _subjects(findings, code):
    """The first word of each finding's message: the table the finding is about."""
    return [item.message.split(" ")[0] for item in _only(findings, code)]


def _ignore(text):
    return parse_bpa_ignore(text)


class TestFactToFact:
    def test_a_fact_referencing_a_fact_is_reported(self):
        tables = _tables(fact_charge=FACT, fact_consignment=FACT, dim_job=DIM)
        relationships = _shaped(
            _edge("fact_charge", "fact_consignment"), _edge("fact_charge", "dim_job")
        )
        findings = _only(check_model_shape(tables, relationships, ()), "gold.fact-to-fact")
        assert len(findings) == 1
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
        (finding,) = _only(check_model_shape(tables, relationships, ()), "gold.ambiguous-path")
        # In filter direction, from the table that would reach another twice (#1012).
        existing, added = second_route(relationships, inactive)
        assert existing[0] == added[0] and existing[-1] == added[-1]
        assert existing != added
        assert " -> ".join(existing) in finding.message
        assert " -> ".join(added) in finding.message
        assert all(
            active_route(relationships, a, b, directed=True) == [a, b]
            for a, b in zip(existing, existing[1:])
        )

    def test_an_edge_a_measure_activates_is_intended(self):
        """DD-240 amends DD-226: only a deactivated edge nothing activates is reported."""
        tables, relationships = self._model()
        inactive = next(item for item in relationships if not item.is_active)
        expression = (
            "CALCULATE(COUNTROWS(fact_consignment), USERELATIONSHIP("
            f"'{inactive.source_table}'[{inactive.source_column}], "
            f"{inactive.target_table}[{inactive.target_column}]))"
        )
        measure = _measure("m", "fact_consignment", expression)
        findings = check_model_shape(tables, relationships, (), measures=(measure,))
        assert _only(findings, "gold.ambiguous-path") == []

    def test_a_plain_snowflake_is_an_advisory_star_schema_finding(self):
        """Kimball preference: every outrigger is reported, and can be excused."""
        tables = _tables(fact_a=FACT, dim_job=DIM, dim_branch=DIM)
        relationships = _shaped(_edge("fact_a", "dim_job"), _edge("dim_job", "dim_branch"))
        assert _codes(check_model_shape(tables, relationships, ())) == ["gold.star-schema"]
        excuse = _ignore(
            "semantic-model.star-schema on relationship "
            "dim_job.dim_branch_sk -> dim_branch.dim_branch_sk: shared outrigger"
        )
        assert check_model_shape(tables, relationships, (excuse,)) == ()


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
        relationships = _shaped(
            _edge("fact_job", "dim_branch"),
            _edge("dim_branch", "dim_staff", "manager_sk"),
            _edge("fact_job", "dim_staff", "sales_rep_sk"),
            _edge("fact_job", "dim_staff", "operator_sk"),
        )
        findings = _only(check_model_shape(tables, relationships, ()), "gold.ambiguous-path")
        assert len(findings) == 2
        assert all("None of the 2 edges from fact_job to dim_staff" in f.message for f in findings)

    def test_the_calendar_counts_as_a_dimension(self):
        tables = _tables(fact_a=FACT)
        relationships = _shaped(
            _edge("fact_a", "dim_date", "order_date", role="order"),
            _edge("fact_a", "dim_date", "ship_date", role="ship"),
        )
        findings = check_model_shape(tables, relationships, (), calendar_table="dim_date")
        assert _codes(findings) == ["gold.role-playing-dimension"]


class TestKimball:
    def test_a_fact_without_a_date_role(self):
        tables = _tables(fact_a=FACT, fact_b=FACT, dim_x=DIM)
        relationships = _shaped(
            _edge("fact_a", "dim_date", "order_date", role="order"),
            _edge("fact_a", "dim_x"),
            _edge("fact_b", "dim_x"),
        )
        findings = check_model_shape(tables, relationships, (), calendar_table="dim_date")
        assert _subjects(findings, "gold.fact-without-date") == ["fact_b"]

    def test_an_accumulating_snapshot_needs_a_date_per_milestone(self):
        tables = (_table("fact_orders", FACT, fact_type=FactType.ACCUMULATING_SNAPSHOT),)
        relationships = _shaped(_edge("fact_orders", "dim_date", "ordered_on", role="ordered"))
        findings = check_model_shape(tables, relationships, (), calendar_table="dim_date")
        assert _codes(findings) == ["gold.snapshot-shape"]

    def test_a_periodic_snapshot_needs_a_calendar(self):
        tables = (
            _table("fact_stock", FACT, fact_type=FactType.PERIODIC_SNAPSHOT),
            _table("dim_item", DIM),
        )
        findings = check_model_shape(tables, _shaped(_edge("fact_stock", "dim_item")), ())
        assert _codes(findings) == ["gold.snapshot-shape"]

    def test_a_balance_summed_over_snapshot_dates(self):
        tables = (
            _table("fact_stock", FACT, fact_type=FactType.PERIODIC_SNAPSHOT),
            _table("dim_item", DIM),
        )
        relationships = _shaped(
            _edge("fact_stock", "dim_item"),
            _edge("fact_stock", "dim_date", "snapshot_date", role="snapshot"),
        )
        summed = _measure("stock", "fact_stock", "SUM(fact_stock[qty])", [("fact_stock", "qty")])
        closing = _measure(
            "stock_close",
            "fact_stock",
            "CALCULATE(SUM(fact_stock[qty]), LASTNONBLANK(dim_date[date], 1))",
            [("fact_stock", "qty")],
        )
        findings = check_model_shape(
            tables, relationships, (), measures=(summed, closing), calendar_table="dim_date"
        )
        (finding,) = _only(findings, "gold.semi-additive-sum")
        assert "'stock'" in finding.message

    def test_a_measure_on_a_dimension(self):
        tables = _tables(fact_a=FACT, dim_x=DIM)
        relationships = _shaped(_edge("fact_a", "dim_x"))
        measures = (
            _measure("credit", "dim_x", "SUM(dim_x[credit_limit])"),
            _measure("customers", "dim_x", "COUNTROWS(dim_x)"),
        )
        findings = check_model_shape(tables, relationships, (), measures=measures)
        (finding,) = _only(findings, "gold.measure-on-dimension")
        assert "'credit'" in finding.message

    def test_bridges(self):
        def bridge(name, weight):
            return _table(
                name,
                BRIDGE,
                bridge_weight_column=weight,
                bridge_cardinality=BridgeCardinality.MANY_TO_MANY,
                bridge_allocation="equal-weight",
            )

        tables = (
            *_tables(fact_a=FACT, dim_x=DIM, dim_y=DIM),
            bridge("bridge_x", ""),
            bridge("bridge_y", "weight"),
        )
        relationships = _shaped(
            _edge("fact_a", "dim_x"),
            _edge("bridge_x", "dim_x"),
            _edge("bridge_y", "dim_y"),
            _edge("bridge_y", "fact_a", "fact_a_sk"),
        )
        findings = check_model_shape(tables, relationships, ())
        assert _subjects(findings, "gold.bridge-unweighted") == ["bridge_x"]
        assert _subjects(findings, "gold.bridge-weight-unused") == ["bridge_y"]
        weighted = _measure(
            "allocated", "fact_a", "SUMX(bridge_y, bridge_y[weight])", [("bridge_y", "weight")]
        )
        findings = check_model_shape(tables, relationships, (), measures=(weighted,))
        assert _only(findings, "gold.bridge-weight-unused") == []

    def test_a_duplicate_and_an_unconnected_dimension(self):
        tables = (
            _table("fact_a", FACT),
            _table("dim_customer", DIM, source_model="customer"),
            _table("dim_client", DIM, source_model="customer"),
            _table("dim_orphan", DIM),
        )
        relationships = _shaped(_edge("fact_a", "dim_customer"), _edge("fact_a", "dim_client"))
        findings = check_model_shape(tables, relationships, ())
        assert _subjects(findings, "gold.duplicate-dimension") == ["dim_client"]
        assert _subjects(findings, "gold.unconnected-table") == ["dim_orphan"]

    def test_a_fact_with_no_relationships(self):
        findings = check_model_shape((_table("fact_alone", FACT),), (), ())
        assert _subjects(findings, "gold.unconnected-table") == ["fact_alone"]

    def test_two_processes_in_one_product(self):
        tables = _tables(fact_sales=FACT, fact_hr=FACT, dim_product=DIM, dim_employee=DIM)
        relationships = _shaped(
            _edge("fact_sales", "dim_product"),
            _edge("fact_hr", "dim_employee"),
            _edge("fact_sales", "dim_date", "sold_on", role="sold"),
            _edge("fact_hr", "dim_date", "hired_on", role="hired"),
        )
        findings = check_model_shape(tables, relationships, (), calendar_table="dim_date")
        assert _codes(findings) == ["gold.product-spans-processes"]
        excuse = _ignore("semantic-model.product-is-one-process on model: one board for both")
        assert check_model_shape(tables, relationships, (excuse,), calendar_table="dim_date") == ()

    def test_a_name_that_contradicts_the_role(self):
        tables = _tables(fact_a=FACT, fact_status=DIM)
        findings = check_model_shape(tables, _shaped(_edge("fact_a", "fact_status")), ())
        assert _subjects(findings, "gold.table-name-role") == ["fact_status"]

    def test_the_bus_matrix(self):
        tables = _tables(fact_a=FACT, fact_b=FACT, dim_x=DIM, dim_y=DIM)
        relationships = _shaped(
            _edge("fact_a", "dim_x"),
            _edge("fact_b", "dim_x"),
            _edge("fact_b", "dim_y", "one_sk"),
            _edge("fact_b", "dim_y", "two_sk"),
        )
        text = bus_matrix(tables, relationships)
        assert "| `fact_b` | ✓ | ✓×2 |" in text
        assert "Conformed across facts: `dim_x`" in text


class TestExceptions:
    _TEXT = (
        "semantic-model.fact-to-fact on relationship "
        "fact_charge.fact_consignment_sk -> fact_consignment.fact_consignment_sk: "
        "charges are analysed per consignment by design"
    )

    def test_an_exception_excuses_the_finding(self):
        tables = _tables(fact_charge=FACT, fact_consignment=FACT)
        relationships = _shaped(_edge("fact_charge", "fact_consignment"))
        findings = check_model_shape(tables, relationships, (_ignore(self._TEXT),))
        assert _only(findings, "gold.fact-to-fact") == []

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

    def test_each_product_is_reported_and_never_fails_the_compile(self, tmp_path, monkeypatch):
        """billing holds one fact and nothing else, so it has a finding: a warning only."""
        result = self._run(tmp_path, monkeypatch, "--all")
        assert result.exit_code == 0, result.output
        assert "gold.unconnected-table: fact_invoice has no relationships" in result.output
        assert "Gold product billing: shape check found 1 finding(s)" in result.output

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
        (product,) = payload["gold_products"]
        assert product["product"] == "billing"
        assert [item["code"] for item in product["diagnostics"]] == ["gold.unconnected-table"]
