# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Compile-time and render-time BPA checks (DD-238, issue #980).

`gold_assert` used to be the only semantic gate, and it runs at render time. An author
iterating with `compile --check` never saw a defect the profile treats as real, and an
authored-policy failure in a measure surfaced as `safety.type-incompatible` at the hub
root, naming neither the rule nor the file.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import tests.test_gold_projector as harness
from kairos_ontology.core.compiler.kernel import build_compile_plan
from kairos_ontology.core.projections.dbt import bpa_profile
from kairos_ontology.core.projections.dbt.bpa_profile import parse_bpa_ignore
from kairos_ontology.core.projections.dbt.gold_assert import assert_gold_semantics
from kairos_ontology.core.projections.dbt.gold_bpa_checks import check_product
from kairos_ontology.core.projections.dbt.gold_specs import GoldContractError
from kairos_ontology.core.projections.dbt.policy_specs import CanonicalTypeKind

REPO = Path(__file__).resolve().parent.parent


def _measure(expression, *, columns=(("fact_sale", "amount"),), measures=(), name=""):
    return SimpleNamespace(
        measure_id="sales.total",
        name=name or "sales.total",
        expression=expression,
        emitted=True,
        column_dependencies=columns,
        measure_dependencies=measures,
        home_table="fact_sale",
        resource_uri="urn:m",
    )


def _column(name, *, kind=CanonicalTypeKind.DECIMAL, hidden=False, comment="described"):
    return SimpleNamespace(
        name=name, canonical_type=SimpleNamespace(kind=kind), hidden=hidden, comment=comment
    )


def _table(*columns, name="fact_sale"):
    return SimpleNamespace(name=name, columns=columns, resource_uri="urn:t")


_DESCRIBED = (_table(_column("amount")),)


def _codes(advisories):
    return [item.code for item in advisories]


class TestColumnQualification:
    @pytest.mark.parametrize(
        "expression",
        [
            "SUM(fact_sale[amount])",
            "SUM('fact_sale'[amount])",
            'SUM(fact_sale[amount]) & "[amount]"',
            "SUM(fact_sale[amount]) // was SUM([amount])",
            "SUM(fact_sale[amount]) /* [amount] */",
        ],
    )
    def test_qualified_references_and_non_code_text_pass(self, expression):
        assert check_product(_DESCRIBED, (_measure(expression),), ()) == ()

    @pytest.mark.parametrize(
        "expression",
        ["SUM([amount])", "VAR x = 1 RETURN [amount]", "SUMX(fact_sale, [amount] * 2)"],
    )
    def test_an_unqualified_declared_column_blocks(self, expression):
        with pytest.raises(GoldContractError) as excinfo:
            check_product(_DESCRIBED, (_measure(expression),), ())
        assert excinfo.value.code == "gold.dax-column-unqualified"
        assert "fact_sale[amount]" in str(excinfo.value)

    def test_an_authored_exception_excuses_it(self):
        ignore = parse_bpa_ignore(
            "DAX_COLUMNS_FULLY_QUALIFIED on measure sales.total: row context in SUMX"
        )
        check_product(_DESCRIBED, (_measure("SUM([amount])"),), (ignore,))

    def test_an_exception_with_nothing_to_excuse_fails(self):
        ignore = parse_bpa_ignore("DAX_COLUMNS_FULLY_QUALIFIED on measure sales.total: stale")
        with pytest.raises(GoldContractError) as excinfo:
            check_product(_DESCRIBED, (_measure("SUM(fact_sale[amount])"),), (ignore,))
        assert excinfo.value.code == "gold.bpa-ignore-unused"


class TestMeasureQualification:
    def _measures(self, expression):
        base = SimpleNamespace(
            measure_id="sales.base",
            name="Base",
            expression="SUM(fact_sale[amount])",
            emitted=True,
            column_dependencies=(("fact_sale", "amount"),),
            measure_dependencies=(),
            home_table="fact_sale",
            resource_uri="urn:b",
        )
        return (base, _measure(expression, columns=(), measures=("sales.base",)))

    def test_an_unqualified_measure_reference_passes(self):
        assert check_product(_DESCRIBED, self._measures("[Base] * 2"), ()) == ()

    def test_a_qualified_measure_reference_blocks(self):
        with pytest.raises(GoldContractError) as excinfo:
            check_product(_DESCRIBED, self._measures("fact_sale[Base] * 2"), ())
        assert excinfo.value.code == "gold.dax-measure-qualified"


class TestWarnings:
    def test_division_warns_and_divide_does_not(self):
        advisories = check_product(
            _DESCRIBED, (_measure("SUM(fact_sale[amount]) / 2"),), ()
        )
        assert _codes(advisories) == ["gold.dax-division-operator"]
        assert check_product(
            _DESCRIBED, (_measure("DIVIDE(SUM(fact_sale[amount]), 2)"),), ()
        ) == ()

    def test_a_float_column_warns(self):
        tables = (_table(_column("ratio", kind=CanonicalTypeKind.FLOAT64)),)
        assert _codes(check_product(tables, (), ())) == ["gold.float-column"]

    def test_undescribed_visible_columns_warn_once_per_table(self):
        tables = (
            _table(
                _column("a", comment=""),
                _column("b", comment=""),
                _column("hidden_sk", comment="", hidden=True),
            ),
        )
        advisories = check_product(tables, (), ())
        assert _codes(advisories) == ["gold.description-missing"]
        assert "a, b" in advisories[0].message
        assert "hidden_sk" not in advisories[0].message

    def test_a_column_exception_silences_its_warning(self):
        tables = (_table(_column("ratio", kind=CanonicalTypeKind.FLOAT64)),)
        ignore = parse_bpa_ignore(
            "AVOID_FLOATING_POINT_DATA_TYPES on column fact_sale.ratio: an IEEE sensor value"
        )
        assert check_product(tables, (), (ignore,)) == ()


class TestEndToEnd:
    def test_the_acme_measures_are_clean(self):
        """The scaffold example and the acme scenario now show the qualified form."""
        harness._generate("invoice")

    def test_the_old_unqualified_example_now_blocks(self, tmp_path):
        text = harness._gold_text("invoice").replace(
            "SUM(fact_invoice[total_amount])", "SUM([total_amount])", 1
        )
        with pytest.raises(GoldContractError) as excinfo:
            harness._generate("invoice", gold_path=harness._write_gold(tmp_path, "invoice", text))
        assert excinfo.value.code == "gold.dax-column-unqualified"

    def test_compile_check_reports_warnings_without_blocking(self, tmp_path):
        import tests.test_gold_cross_domain_bridge as bridge

        plan = build_compile_plan(bridge._cross_domain_hub(tmp_path), "party")
        warnings = [item for item in plan.diagnostics.items if item.severity.value == "warning"]
        assert "gold.description-missing" in {item.code for item in warnings}
        assert all(item.location.path.endswith("party-gold-ext.ttl") for item in warnings)
        assert not plan.blocked

    def test_a_measure_policy_failure_keeps_its_own_code(self, tmp_path):
        """#980: this surfaced as `safety.type-incompatible` at the hub root."""
        import tests.test_gold_cross_domain_bridge as bridge

        hub = bridge._cross_domain_hub(tmp_path)
        path = hub / "model" / "extensions" / "party-gold-ext.ttl"
        path.write_text(
            path.read_text(encoding="utf-8")
            + "\n<https://example.test/ontology/party> kairos-ext:measure party:CustomerCount .\n"
            "party:CustomerCount a kairos-ext:Measure ;\n"
            '  kairos-ext:measureId "party.customer-count" ;\n'
            '  kairos-ext:measureDefinition "Number of customers." ;\n'
            '  kairos-ext:measureExpression "COUNTROWS(dim_customer)" ;\n'
            "  kairos-ext:measureColumnDependency <https://example.test/ontology/party#customerName> ;\n"
            '  kairos-ext:measureLifecycleState "provisional" .\n',
            encoding="utf-8",
        )
        plan = build_compile_plan(hub, "party")
        codes = {item.code: item for item in plan.diagnostics.items}
        assert "safety.type-incompatible" not in codes
        failure = codes["measure.incomplete-semantic-contract"]
        assert failure.location.path.endswith("party-gold-ext.ttl")
        assert failure.rule_id == "DD-113-measure-lifecycle"
        assert plan.blocked


# ---------------------------------------------------------------------------
# Render-time assertions
# ---------------------------------------------------------------------------

_TABLE = "m/M.SemanticModel/definition/tables/{name}.tmdl"
_RELATIONSHIPS = "m/M.SemanticModel/definition/relationships.tmdl"


def _column_tmdl(name, data_type="string", *extra):
    return "\n".join(
        [f"\tcolumn {name}", f"\t\tdataType: {data_type}", *extra, f"\t\tsourceColumn: {name}", ""]
    )


def _artifacts(**tables):
    return {_TABLE.format(name=name): f"table {name}\n\n" + body for name, body in tables.items()}


class TestRenderAssertions:
    def test_the_emitted_acme_model_passes(self):
        assert_gold_semantics(harness._generate("invoice"))

    def test_a_visible_summarized_number_fails(self):
        artifacts = _artifacts(fact=_column_tmdl("qty", "int64", "\t\tsummarizeBy: sum"))
        with pytest.raises(GoldContractError) as excinfo:
            assert_gold_semantics(artifacts)
        assert excinfo.value.code == "gold.column-summarized"

    def test_a_hidden_summarized_number_passes(self):
        assert_gold_semantics(
            _artifacts(fact=_column_tmdl("qty", "int64", "\t\tisHidden", "\t\tsummarizeBy: sum"))
        )

    def test_a_column_without_source_fails(self):
        artifacts = _artifacts(fact="\tcolumn qty\n\t\tdataType: string\n")
        with pytest.raises(GoldContractError) as excinfo:
            assert_gold_semantics(artifacts)
        assert excinfo.value.code == "gold.column-source-missing"

    def test_a_measure_without_format_fails(self):
        artifacts = _artifacts(fact="\tmeasure 'Total' = 1\n\t\tlineageTag: x\n")
        with pytest.raises(GoldContractError) as excinfo:
            assert_gold_semantics(artifacts)
        assert excinfo.value.code == "gold.measure-format-missing"

    def test_an_unmarked_date_table_fails(self):
        body = "\tdataCategory: Time\n\n" + _column_tmdl("date_key", "int64", "\t\tisKey", "\t\tsummarizeBy: none")
        with pytest.raises(GoldContractError) as excinfo:
            assert_gold_semantics(_artifacts(dim_date=body))
        assert excinfo.value.code == "gold.date-table-not-marked"

    def test_an_unsorted_month_name_fails(self):
        body = (
            "\tdataCategory: Time\n\n"
            + _column_tmdl("full_date", "dateTime", "\t\tisKey")
            + _column_tmdl("month_name")
        )
        with pytest.raises(GoldContractError) as excinfo:
            assert_gold_semantics(_artifacts(dim_date=body))
        assert excinfo.value.code == "gold.calendar-unsorted"

    def test_a_control_character_in_a_description_fails(self):
        artifacts = _artifacts(fact="\t/// bad\x07text\n" + _column_tmdl("name"))
        with pytest.raises(GoldContractError) as excinfo:
            assert_gold_semantics(artifacts)
        assert excinfo.value.code == "gold.description-control-character"

    @pytest.mark.parametrize(("inactive", "raises"), [(False, True), (True, False)])
    def test_an_active_join_across_types_fails(self, inactive, raises):
        artifacts = _artifacts(
            fact=_column_tmdl("dim_sk", "int64", "\t\tsummarizeBy: none"),
            dim=_column_tmdl("dim_sk", "string"),
        )
        artifacts[_RELATIONSHIPS] = (
            "relationship r1\n"
            + ("\tisActive: false\n" if inactive else "")
            + "\tfromColumn: fact.dim_sk\n\ttoColumn: dim.dim_sk\n"
        )
        if raises:
            with pytest.raises(GoldContractError) as excinfo:
                assert_gold_semantics(artifacts)
            assert excinfo.value.code == "gold.relationship-type-mismatch"
        else:
            assert_gold_semantics(artifacts)


def test_descriptions_drop_control_characters():
    from kairos_ontology.core.projections.dbt.gold_render import _tmdl_text

    assert _tmdl_text('a\x07b\tc\n"d"') == 'ab\tc ""d""'


def test_every_enforcing_code_exists_in_the_toolkit():
    """A profile row naming a code nothing raises would claim a check that never runs."""
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (REPO / "src" / "kairos_ontology" / "core").rglob("*.py")
        if path.name != "bpa_profile.py"
    )
    for item in bpa_profile.all_rules():
        for target in bpa_profile.Target:
            code = item.disposition(target).enforced_by
            if code:
                assert f'"{code}"' in source, (item.rule_id, code)
