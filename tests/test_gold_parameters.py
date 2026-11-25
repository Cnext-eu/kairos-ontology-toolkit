# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Authorable report parameters and calculation groups (issue #1113, DD-262).

A thin report live-connected to a deployed model cannot add a field parameter, a selector
or a what-if range: each is a calculated table, so it has to come from the hub. These
tests pin the vocabulary end to end -- bind, normalize, shape, render, assert -- on the
v5 lane `emit-gold` runs, and the fail-closed checks the issue asks for.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from kairos_ontology.core.compiler.kernel import build_compile_plan
from kairos_ontology.core.projections.dbt.gold_assert import assert_gold_semantics
from kairos_ontology.core.projections.dbt.gold_connection import GoldProductConfig
from kairos_ontology.core.projections.dbt.gold_specs import GoldContractError
from kairos_ontology.core.projections.medallion_gold_projector import (
    generate_gold_from_compile_plan,
    generate_gold_from_compile_plans,
)

_V5_HUB = Path(__file__).parent / "scenarios" / "v5-hub"
_DEFINITION = "party/Party.SemanticModel/definition"

_HEADER = """
@prefix party: <https://example.test/ontology/party#> .
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

<https://example.test/ontology/party>
  kairos-ext:goldSchema "gold" ;
  kairos-ext:measure party:CustomerCount ;
{links}  kairos-ext:goldProductProfile "dimensional-powerbi-v1" .

party:Customer
  kairos-ext:goldTableType "dimension" ;
  kairos-ext:goldTableName "dim_customer" ;
  kairos-ext:goldSourceModel "customer" ;
  kairos-ext:goldSourceVersion "1.0.0" ;
  kairos-ext:dimensionExposure "current-only" ;
  kairos-ext:dimensionVersionBinding "current" .

party:CustomerCount a kairos-ext:Measure ;
  kairos-ext:measureId "customer_count" ;
  kairos-ext:measureDisplayName "Customers" ;
  kairos-ext:measureDefinition "Number of customers." ;
  kairos-ext:measureExpression "COUNTROWS(dim_customer)" ;
  kairos-ext:measureColumnDependency <https://example.test/ontology/party#customerName> ;
  kairos-ext:measureLifecycleState "provisional" ;
  kairos-ext:measureDataType "int64" ;
  kairos-ext:measureFormatString "#,0" ;
  kairos-ext:measureFolder "Party" .
"""

#: Items deliberately listed against alphabetical order: the collection's order must win.
_BREAKDOWN = """
party:Breakdown a kairos-ext:Parameter ;
  kairos-ext:parameterId "breakdown" ;
  kairos-ext:parameterKind "field" ;
  kairos-ext:parameterDisplayName "Breakdown" ;
  kairos-ext:parameterItem ( "Name=column:dim_customer.customer_name"
                             "Customers=measure:customer_count"
                             "Id=column:dim_customer.customer_id" ) .
"""

_VOLUME_UNIT = """
party:VolumeUnit a kairos-ext:Parameter ;
  kairos-ext:parameterId "volume_unit" ;
  kairos-ext:parameterKind "selector" ;
  kairos-ext:parameterDisplayName "Volume unit" ;
  kairos-ext:parameterValue ( "Weight" "Shipments" "Say \\"hi\\"" ) ;
  kairos-ext:parameterDefault "Shipments" .
"""

_TOLERANCE = """
party:Tolerance a kairos-ext:Parameter ;
  kairos-ext:parameterId "tolerance_days" ;
  kairos-ext:parameterKind "range" ;
  kairos-ext:parameterDisplayName "Tolerance (days)" ;
  kairos-ext:parameterMin 0 ; kairos-ext:parameterMax 10 ;
  kairos-ext:parameterStep 1 ; kairos-ext:parameterDefault 2 .
"""

_MEASURES = """
party:Title a kairos-ext:Measure ;
  kairos-ext:measureId "breakdown_title" ;
  kairos-ext:measureDisplayName "Breakdown Title" ;
  kairos-ext:measureDefinition "Visual title naming the picked field." ;
  kairos-ext:measureExpression "\\"Customers by \\" & SELECTEDVALUE('Breakdown'[Breakdown])" ;
  kairos-ext:measureParameterDependency "breakdown" ;
  kairos-ext:measureLifecycleState "provisional" ;
  kairos-ext:measureDataType "string" ;
  kairos-ext:measureFormatString "General" ;
  kairos-ext:measureFolder "Titles" .

party:Selected a kairos-ext:Measure ;
  kairos-ext:measureId "volume_selected" ;
  kairos-ext:measureDisplayName "Volume Selected" ;
  kairos-ext:measureDefinition "The volume in the picked unit." ;
  kairos-ext:measureExpression "SWITCH([Volume unit Value], \\"Weight\\", [Customers] * 2, [Customers])" ;
  kairos-ext:measureFormatStringExpression "IF([Volume unit Value] = \\"Weight\\", \\"#,0.00\\", \\"#,0\\")" ;
  kairos-ext:measureDependency party:CustomerCount ;
  kairos-ext:measureParameterDependency "volume_unit" ;
  kairos-ext:measureLifecycleState "provisional" ;
  kairos-ext:measureDataType "decimal" ;
  kairos-ext:measureFormatString "#,0" ;
  kairos-ext:measureFolder "Party" .
"""

_SCALE = """
party:Scale a kairos-ext:CalculationGroup ;
  kairos-ext:calculationGroupId "scale" ;
  kairos-ext:calculationGroupDisplayName "Scale" ;
  kairos-ext:calculationGroupPrecedence {precedence} ;
  kairos-ext:calculationItem party:ScaleDoubled, party:ScaleAsIs .

party:ScaleAsIs a kairos-ext:CalculationItem ;
  kairos-ext:calculationItemName "As is" ;
  kairos-ext:calculationItemOrdinal 0 ;
  kairos-ext:calculationItemExpression "SELECTEDMEASURE()" .

party:ScaleDoubled a kairos-ext:CalculationItem ;
  kairos-ext:calculationItemName "Doubled" ;
  kairos-ext:calculationItemOrdinal 1 ;
  kairos-ext:calculationItemExpression \"\"\"VAR _m = SELECTEDMEASURE()
RETURN
    _m * 2\"\"\" ;
  kairos-ext:calculationItemFormatString "\\"#,0.0\\"" .
"""

_ALL_LINKS = (
    "  kairos-ext:measure party:Title, party:Selected ;\n"
    "  kairos-ext:parameter party:Breakdown, party:VolumeUnit, party:Tolerance ;\n"
    "  kairos-ext:calculationGroup party:Scale ;\n"
)
_ALL_BODY = _BREAKDOWN + _VOLUME_UNIT + _TOLERANCE + _MEASURES + _SCALE.format(precedence=20)


def _hub(tmp_path: Path, *, links: str, body: str) -> Path:
    hub = tmp_path / "hub"
    shutil.copytree(_V5_HUB, hub)
    extensions = hub / "model" / "extensions"
    extensions.mkdir(parents=True, exist_ok=True)
    (extensions / "party-gold-ext.ttl").write_text(
        _HEADER.format(links=links) + body, encoding="utf-8"
    )
    return hub


def _plan(tmp_path: Path, *, links: str, body: str):
    return build_compile_plan(_hub(tmp_path, links=links, body=body), "party")


def _blocking_codes(tmp_path: Path, *, links: str, body: str) -> set[str]:
    """The error codes of a compile *links*/*body* block, as `compile --check` reports."""
    plan = _plan(tmp_path, links=links, body=body)
    assert plan.blocked, "expected the authored value to block the compile"
    return {
        diagnostic.code
        for diagnostic in plan.diagnostics.ordered
        if str(getattr(diagnostic, "severity", "")).lower().endswith("error")
    }


def _product_error(tmp_path: Path, *, links: str, body: str) -> GoldContractError:
    """Shape the declared one-domain product, where nothing is deferred."""
    plan = _plan(tmp_path, links=links, body=body)
    assert not plan.blocked, [item.render() for item in plan.diagnostics.items]
    with pytest.raises(GoldContractError) as excinfo:
        generate_gold_from_compile_plans(
            [plan], GoldProductConfig(name="party", domains=("party",))
        )
    return excinfo.value


@pytest.fixture(scope="module")
def artifacts(tmp_path_factory) -> dict[str, str]:
    """Every parameter kind, two parameter-reading measures and a calculation group."""
    plan = _plan(tmp_path_factory.mktemp("parameters"), links=_ALL_LINKS, body=_ALL_BODY)
    assert not plan.blocked, [item.render() for item in plan.diagnostics.items]
    return generate_gold_from_compile_plan(plan)


def _table(artifacts: dict[str, str], name: str) -> str:
    return artifacts[f"{_DEFINITION}/tables/{name}.tmdl"]


def _report(artifacts: dict[str, str]) -> dict:
    path = next(name for name in artifacts if name.endswith("-gold-product.json"))
    return json.loads(artifacts[path])


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


class TestFieldParameter:
    def test_is_a_calculated_table_named_by_its_id(self, artifacts):
        tmdl = _table(artifacts, "breakdown")
        assert "table Breakdown" in tmdl
        assert "\tpartition Breakdown = calculated" in tmdl

    def test_carries_the_parameter_metadata_power_bi_recognises(self, artifacts):
        assert '\t\textendedProperty ParameterMetadata = {"version":3,"kind":2}' in _table(
            artifacts, "breakdown"
        )

    def test_items_keep_their_authored_order_and_resolve_to_model_names(self, artifacts):
        """A measure item uses the name the model gives it, on its home table."""
        tmdl = _table(artifacts, "breakdown")
        name = tmdl.index("NAMEOF('dim_customer'[customer_name]), 0)")
        measure = tmdl.index("NAMEOF('dim_customer'[Customers]), 1)")
        identifier = tmdl.index("NAMEOF('dim_customer'[customer_id]), 2)")
        assert name < measure < identifier

    def test_helper_columns_are_hidden_and_the_picker_sorts_by_order(self, artifacts):
        tmdl = _table(artifacts, "breakdown")
        fields = tmdl.split("\tcolumn 'Breakdown Fields'", 1)[1].split("\n\n", 1)[0]
        order = tmdl.split("\tcolumn 'Breakdown Order'", 1)[1].split("\n\n", 1)[0]
        assert "isHidden" in fields and "isHidden" in order
        picker = tmdl.split("\tcolumn Breakdown\n", 1)[1].split("\n\n", 1)[0]
        assert "sortByColumn: 'Breakdown Order'" in picker
        assert "isHidden" not in picker

    def test_a_measure_reading_only_the_parameter_lives_on_its_table(self, artifacts):
        tmdl = _table(artifacts, "breakdown")
        assert "measure 'Breakdown Title' = " in tmdl
        assert "Breakdown Title" not in _table(artifacts, "dim_customer")


class TestSelectorParameter:
    def test_is_a_datatable_in_authored_order_with_dax_escaping(self, artifacts):
        tmdl = _table(artifacts, "volume_unit")
        assert "DATATABLE(" in tmdl
        weight = tmdl.index('{"Weight", 0}')
        shipments = tmdl.index('{"Shipments", 1}')
        quoted = tmdl.index('{"Say ""hi""", 2}')
        assert weight < shipments < quoted

    def test_value_measure_falls_back_to_the_default_and_is_hidden(self, artifacts):
        tmdl = _table(artifacts, "volume_unit")
        block = tmdl.split("\tmeasure 'Volume unit Value' = ", 1)[1].split("\n\n", 1)[0]
        assert block.startswith("SELECTEDVALUE('Volume unit'[Volume unit], \"Shipments\")")
        assert "isHidden" in block

    def test_a_measure_reading_it_gets_its_dynamic_format_string_last(self, artifacts):
        tmdl = _table(artifacts, "dim_customer")
        block = tmdl.split("\tmeasure 'Volume Selected' = ", 1)[1].split("\n\n", 1)[0]
        assert block.splitlines()[-1] == (
            '\t\tformatStringDefinition = IF([Volume unit Value] = "Weight", "#,0.00", "#,0")'
        )


class TestRangeParameter:
    def test_is_a_generateseries_with_its_value_measure(self, artifacts):
        tmdl = _table(artifacts, "tolerance_days")
        assert "\t\tsource = GENERATESERIES(0, 10, 1)" in tmdl
        assert (
            "\tmeasure 'Tolerance (days) Value' = "
            "SELECTEDVALUE('Tolerance (days)'[Tolerance (days)], 2)"
        ) in tmdl
        assert '\t\textendedProperty ParameterMetadata = {"version":0}' in tmdl

    def test_whole_numbers_render_an_integer_column(self, artifacts):
        tmdl = _table(artifacts, "tolerance_days")
        assert "\t\tdataType: int64" in tmdl

    def test_a_fractional_step_renders_a_double_column(self, tmp_path):
        body = _TOLERANCE.replace("kairos-ext:parameterStep 1", "kairos-ext:parameterStep 0.5")
        plan = _plan(tmp_path, links="  kairos-ext:parameter party:Tolerance ;\n", body=body)
        tmdl = generate_gold_from_compile_plan(plan)[f"{_DEFINITION}/tables/tolerance_days.tmdl"]
        assert "\t\tdataType: double" in tmdl
        assert "GENERATESERIES(0, 10, 0.5)" in tmdl
        assert "\t\tformatString: 0.00" in tmdl


class TestCalculationGroup:
    def test_is_emitted_with_its_precedence_and_items_in_ordinal_order(self, artifacts):
        tmdl = artifacts[f"{_DEFINITION}/calculationGroups/scale.tmdl"]
        assert "\t\tprecedence: 20" in tmdl
        assert tmdl.index("calculationItem 'As is'") < tmdl.index("calculationItem Doubled")

    def test_a_multi_line_item_is_fenced_and_its_format_string_is_last(self, artifacts):
        tmdl = artifacts[f"{_DEFINITION}/calculationGroups/scale.tmdl"]
        item = tmdl.split("\t\tcalculationItem Doubled = ```\n", 1)[1].split("\n\n", 1)[0]
        assert item.splitlines()[:3] == [
            "\t\t\t\tVAR _m = SELECTEDMEASURE()",
            "\t\t\t\tRETURN",
            "\t\t\t\t    _m * 2",
        ]
        assert item.splitlines()[-1] == '\t\t\tformatStringDefinition = "#,0.0"'

    def test_the_model_discourages_implicit_measures_without_a_calendar(self, artifacts):
        """#791: the engine creates no calculation group otherwise -- and this product has
        no calendar, which used to be the only thing that set the flag."""
        model = artifacts[f"{_DEFINITION}/model.tmdl"]
        assert "\tdiscourageImplicitMeasures" in model
        assert "Time Intelligence" not in model


class TestModel:
    def test_every_parameter_and_group_is_referenced(self, artifacts):
        model = artifacts[f"{_DEFINITION}/model.tmdl"]
        for ref in (
            "ref table Breakdown",
            "ref table 'Volume unit'",
            "ref table 'Tolerance (days)'",
            "ref table Scale",
        ):
            assert ref in model

    @pytest.mark.parametrize("name", ["breakdown", "volume_unit", "tolerance_days"])
    def test_each_parameter_records_its_bpa_exceptions(self, artifacts, name):
        assert (
            "\tannotation BestPracticeAnalyzer_IgnoreRules = "
            '{"RuleIDs":["ENSURE_TABLES_HAVE_RELATIONSHIPS",'
            '"REDUCE_USAGE_OF_CALCULATED_TABLES"]}'
        ) in _table(artifacts, name)

    def test_no_parameter_relates_to_anything(self, artifacts):
        relationships = artifacts[f"{_DEFINITION}/relationships.tmdl"]
        for name in ("Breakdown", "Volume unit", "Tolerance (days)", "Scale"):
            assert name not in relationships

    def test_the_report_records_parameters_and_groups(self, artifacts):
        report = _report(artifacts)
        assert [item["id"] for item in report["parameters"]] == [
            "breakdown",
            "tolerance_days",
            "volume_unit",
        ]
        assert report["parameters"][0]["items"][1] == {
            "label": "Customers",
            "measure": "dim_customer.Customers",
        }
        assert report["calculation_groups"][0]["precedence"] == 20
        selected = next(item for item in report["measures"] if item["id"] == "volume_selected")
        assert selected["parameter_dependencies"] == ["volume_unit"]

    def test_a_product_without_any_keeps_its_report(self, tmp_path):
        plan = _plan(tmp_path, links="", body="")
        report = _report(generate_gold_from_compile_plan(plan))
        assert "parameters" not in report
        assert "calculation_groups" not in report

    def test_the_output_is_deterministic(self, artifacts, tmp_path):
        again = generate_gold_from_compile_plan(_plan(tmp_path, links=_ALL_LINKS, body=_ALL_BODY))
        tmdl = {path: text for path, text in artifacts.items() if path.endswith(".tmdl")}
        assert tmdl == {path: text for path, text in again.items() if path.endswith(".tmdl")}

    @pytest.mark.slow
    def test_the_tom_serializer_accepts_the_model(self, artifacts):
        """The real engine, when the .NET SDK is present -- the shapes were read back from
        TOM's own serializer, and this keeps them honest."""
        from kairos_ontology.core.projections.dbt.tmdl_validate import validate_tmdl_artifacts

        results = validate_tmdl_artifacts(artifacts)
        if all(item.status == "unavailable" for item in results):
            pytest.skip("the .NET SDK is not available")
        assert [item.status for item in results] == ["pass"], [item.message for item in results]


# ---------------------------------------------------------------------------
# Fail-closed authoring checks
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_unordered_values_are_refused(self, tmp_path):
        body = _VOLUME_UNIT.replace(
            '( "Weight" "Shipments" "Say \\"hi\\"" )', '"Weight", "Shipments"'
        )
        codes = _blocking_codes(
            tmp_path, links="  kairos-ext:parameter party:VolumeUnit ;\n", body=body
        )
        assert "parameter.unordered-values" in codes

    def test_a_selector_default_must_be_a_value(self, tmp_path):
        body = _VOLUME_UNIT.replace('parameterDefault "Shipments"', 'parameterDefault "Volume"')
        codes = _blocking_codes(
            tmp_path, links="  kairos-ext:parameter party:VolumeUnit ;\n", body=body
        )
        assert "parameter.default-out-of-range" in codes

    def test_a_range_default_must_lie_in_the_range(self, tmp_path):
        body = _TOLERANCE.replace("parameterDefault 2", "parameterDefault 11")
        codes = _blocking_codes(
            tmp_path, links="  kairos-ext:parameter party:Tolerance ;\n", body=body
        )
        assert "parameter.default-out-of-range" in codes

    def test_a_range_step_must_be_positive(self, tmp_path):
        body = _TOLERANCE.replace("parameterStep 1", "parameterStep 0")
        codes = _blocking_codes(
            tmp_path, links="  kairos-ext:parameter party:Tolerance ;\n", body=body
        )
        assert "parameter.invalid-range" in codes

    def test_a_slot_of_another_kind_is_refused(self, tmp_path):
        body = _BREAKDOWN.replace(
            'parameterKind "field" ;',
            'parameterKind "field" ;\n  kairos-ext:parameterDefault "x" ;',
        )
        codes = _blocking_codes(
            tmp_path, links="  kairos-ext:parameter party:Breakdown ;\n", body=body
        )
        assert "parameter.slot-not-applicable" in codes

    def test_a_malformed_item_is_refused(self, tmp_path):
        body = _BREAKDOWN.replace('"Id=column:dim_customer.customer_id"', '"Id=column:customer_id"')
        codes = _blocking_codes(
            tmp_path, links="  kairos-ext:parameter party:Breakdown ;\n", body=body
        )
        assert "parameter.invalid-item" in codes

    def test_an_unlinked_parameter_is_refused(self, tmp_path):
        codes = _blocking_codes(tmp_path, links="", body=_TOLERANCE)
        assert "gold.unlinked-parameter" in codes

    def test_a_calculation_group_needs_a_positive_precedence(self, tmp_path):
        """0 is Time Intelligence's."""
        codes = _blocking_codes(
            tmp_path,
            links="  kairos-ext:calculationGroup party:Scale ;\n",
            body=_SCALE.format(precedence=0),
        )
        assert "policy.unsupported-value" in codes

    def test_item_ordinals_are_unique(self, tmp_path):
        body = _SCALE.format(precedence=5).replace(
            "calculationItemOrdinal 1", "calculationItemOrdinal 0"
        )
        codes = _blocking_codes(
            tmp_path, links="  kairos-ext:calculationGroup party:Scale ;\n", body=body
        )
        assert "calculation-group.duplicate-item-ordinal" in codes


class TestShaping:
    def test_a_measure_naming_an_undeclared_parameter_is_refused(self, tmp_path):
        """Declaring the dependency is what admits the parameter's names into the DAX."""
        selected = "party:Selected" + _MEASURES.split("party:Selected", 1)[1]
        undeclared = selected.replace('kairos-ext:measureParameterDependency "volume_unit" ;', "")
        codes = _blocking_codes(
            tmp_path,
            links=(
                "  kairos-ext:measure party:Selected ;\n  kairos-ext:parameter party:VolumeUnit ;\n"
            ),
            body=_VOLUME_UNIT + undeclared,
        )
        assert "measure.unresolved-dax-reference" in codes

    def test_a_dependency_on_an_unknown_parameter_is_refused(self, tmp_path):
        body = _MEASURES.split("party:Selected", 1)[0].replace('"breakdown"', '"no_such_parameter"')
        codes = _blocking_codes(tmp_path, links="  kairos-ext:measure party:Title ;\n", body=body)
        assert "measure.unknown-parameter-dependency" in codes

    def test_a_display_name_may_not_repeat_a_table(self, tmp_path):
        body = _TOLERANCE.replace('"Tolerance (days)"', '"dim_customer"')
        codes = _blocking_codes(
            tmp_path, links="  kairos-ext:parameter party:Tolerance ;\n", body=body
        )
        assert "gold.report-object-name-collision" in codes

    def test_an_id_may_not_repeat_a_table_file(self, tmp_path):
        body = _TOLERANCE.replace('parameterId "tolerance_days"', 'parameterId "dim_customer"')
        codes = _blocking_codes(
            tmp_path, links="  kairos-ext:parameter party:Tolerance ;\n", body=body
        )
        assert "gold.report-object-name-collision" in codes

    def test_two_groups_may_not_share_a_precedence(self, tmp_path):
        second = (
            _SCALE.format(precedence=20)
            .replace("party:Scale ", "party:Other ")
            .replace('"scale"', '"other"')
            .replace('"Scale"', '"Other"')
            .replace("party:ScaleDoubled", "party:OtherDoubled")
            .replace("party:ScaleAsIs", "party:OtherAsIs")
        )
        codes = _blocking_codes(
            tmp_path,
            links="  kairos-ext:calculationGroup party:Scale, party:Other ;\n",
            body=_SCALE.format(precedence=20) + second,
        )
        assert "gold.calculation-group-precedence-collision" in codes

    def test_an_item_reading_an_undeclared_column_is_refused(self, tmp_path):
        body = _SCALE.format(precedence=5).replace(
            '"SELECTEDMEASURE()"',
            '"CALCULATE(SELECTEDMEASURE(), dim_customer[customer_id] = \\"x\\")"',
        )
        codes = _blocking_codes(
            tmp_path, links="  kairos-ext:calculationGroup party:Scale ;\n", body=body
        )
        assert "calculation-group.unresolved-dax-reference" in codes

    def test_a_declared_column_dependency_admits_the_reference(self, tmp_path):
        body = _SCALE.format(precedence=5).replace(
            '"SELECTEDMEASURE()" .',
            '"CALCULATE(SELECTEDMEASURE(), dim_customer[customer_id] = \\"x\\")" ;\n'
            '  kairos-ext:calculationItemColumnDependency "dim_customer.customer_id" .',
        )
        plan = _plan(tmp_path, links="  kairos-ext:calculationGroup party:Scale ;\n", body=body)
        assert not plan.blocked, [item.render() for item in plan.diagnostics.items]

    def test_an_unresolved_item_is_deferred_on_a_domain_compile(self, tmp_path):
        """It may name another domain's table, exactly as a bridge endpoint may (#763)..."""
        body = _BREAKDOWN.replace("dim_customer.customer_id", "dim_elsewhere.code")
        plan = _plan(tmp_path, links="  kairos-ext:parameter party:Breakdown ;\n", body=body)
        assert not plan.blocked, [item.render() for item in plan.diagnostics.items]
        assert (
            "parameterItem",
            "Id=column:dim_elsewhere.code",
        ) in plan.shaped_project.gold_product.deferred_references

    def test_and_fails_closed_when_the_product_is_shaped(self, tmp_path):
        """...and at product level there is no wider union to wait for."""
        body = _BREAKDOWN.replace("dim_customer.customer_id", "dim_elsewhere.code")
        error = _product_error(
            tmp_path, links="  kairos-ext:parameter party:Breakdown ;\n", body=body
        )
        assert error.code == "gold.parameter-item-unresolved"


class TestRenderAssertion:
    def test_a_calculated_table_that_is_not_a_parameter_is_refused(self):
        artifacts = {
            "m/M.SemanticModel/definition/tables/rogue.tmdl": (
                "table rogue\n\tcolumn x\n\t\tdataType: int64\n\t\tsourceColumn: [Value]\n"
                "\t\tsummarizeBy: none\n\n\tpartition rogue = calculated\n"
                "\t\tsource = GENERATESERIES(1, 2, 1)\n"
            )
        }
        with pytest.raises(GoldContractError) as excinfo:
            assert_gold_semantics(artifacts)
        assert excinfo.value.code == "gold.calculated-table-not-parameter"

    def test_a_parameter_table_must_record_its_exception(self):
        artifacts = {
            "m/M.SemanticModel/definition/tables/p.tmdl": (
                'table p\n\tannotation Kairos_ParameterKind = "range"\n\n'
                "\tpartition p = calculated\n\t\tsource = GENERATESERIES(1, 2, 1)\n"
            )
        }
        with pytest.raises(GoldContractError) as excinfo:
            assert_gold_semantics(artifacts)
        assert excinfo.value.code == "gold.calculated-table-exception-missing"
