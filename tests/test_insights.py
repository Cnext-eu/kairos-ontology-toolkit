# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Personas, questions and KPI coverage (issue #744).

A Gold product could be described completely -- tables, grains, relationships, measures --
without recording what anyone wanted to know. Report design then started from the data
that happened to be modelled instead of from the decision someone needs to make.

Insights are authored, not derived. What the toolkit contributes is the check (does the
product carry what a confirmed insight names?) and the brief that hands the answer to
whoever builds the report.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import yaml

from kairos_ontology.core.insights import (
    InsightsError,
    check_coverage,
    load_insights,
    parse_insights,
    render_insight_brief,
)

_DOCUMENT = {
    "schema_version": "1",
    "personas": [
        {"id": "ops-manager", "description": "Runs the terminal day to day"},
        {"id": "cfo", "description": "Owns the number"},
    ],
    "insights": [
        {
            "id": "on-time-departures",
            "persona": "ops-manager",
            "question": "How many departures left on time this week, by terminal?",
            "kpi": "On-time departure rate",
            "comparison": "prior week",
            "product": "invoicing",
            "measures": ["On Time Rate"],
            "dimensions": ["dim_customer.customer_name"],
            "status": "confirmed",
        },
        {
            "id": "margin-by-country",
            "persona": "cfo",
            "kpi": "Margin",
            "product": "invoicing",
            "measures": ["Margin"],
            "dimensions": ["dim_customer.nope"],
            "status": "draft",
        },
    ],
}


def _spec(*, measures=(("On Time Rate", True),), calendar=False):
    """A stand-in for the shaped Gold spec: coverage reads only these four attributes."""
    return SimpleNamespace(
        measures=[SimpleNamespace(measure_id=name, emitted=emitted) for name, emitted in measures],
        tables=[
            SimpleNamespace(
                name="dim_customer",
                columns=[
                    SimpleNamespace(name="customer_name"),
                    SimpleNamespace(name="customer_id"),
                ],
            )
        ],
        calendar=SimpleNamespace(approved=True) if calendar else None,
    )


class TestParsing:
    def test_a_document_parses(self):
        parsed = parse_insights(_DOCUMENT)
        assert [item.id for item in parsed.insights] == [
            "on-time-departures",
            "margin-by-country",
        ]
        assert parsed.persona_label("cfo") == "Owns the number"

    def test_an_absent_file_is_not_an_error(self, tmp_path):
        """Every existing hub authors none, and that must stay a valid state."""
        assert load_insights(tmp_path).insights == ()
        assert load_insights(None).insights == ()

    def test_insights_are_selected_by_product(self):
        parsed = parse_insights(_DOCUMENT)
        assert len(parsed.for_product("invoicing")) == 2
        assert parsed.for_product("other") == ()

    def test_status_defaults_to_draft(self):
        parsed = parse_insights({"insights": [{"id": "x", "product": "p"}]})
        assert parsed.insights[0].status == "draft"
        assert not parsed.insights[0].confirmed

    @pytest.mark.parametrize(
        "document",
        [
            {"insights": [{"id": "x"}]},
            {"insights": [{"id": "x", "product": "p", "status": "agreed"}]},
            {"insights": [{"id": "x", "product": "p"}, {"id": "x", "product": "p"}]},
            {"insights": [{"id": "x", "product": "p", "measures": "Revenue"}]},
            {
                "personas": [{"id": "a"}],
                "insights": [{"id": "x", "product": "p", "persona": "ghost"}],
            },
        ],
        ids=["no-product", "bad-status", "duplicate-id", "measures-not-a-list", "unknown-persona"],
    )
    def test_a_malformed_document_fails_closed(self, document):
        with pytest.raises(InsightsError):
            parse_insights(document)

    def test_an_unreadable_file_fails_closed(self, tmp_path):
        path = tmp_path / "integration" / "discovery" / "bi"
        path.mkdir(parents=True)
        (path / "insights.yaml").write_text("::: not yaml :::", encoding="utf-8")
        with pytest.raises(InsightsError):
            load_insights(tmp_path)


class TestCoverage:
    def test_a_satisfied_insight_is_covered(self):
        parsed = parse_insights(_DOCUMENT)
        (result,) = check_coverage(parsed.for_product("invoicing")[:1], _spec())
        assert result.covered

    def test_a_missing_column_is_reported(self):
        parsed = parse_insights(_DOCUMENT)
        (result,) = check_coverage(parsed.for_product("invoicing")[1:], _spec())
        assert not result.covered
        assert result.missing_measures == ("Margin",)
        assert result.missing_dimensions == ("dim_customer.nope",)

    def test_an_intent_measure_does_not_count(self):
        """DD-113 `intent` measures are authored but never rendered into the model."""
        parsed = parse_insights(_DOCUMENT)
        (result,) = check_coverage(
            parsed.for_product("invoicing")[:1], _spec(measures=(("On Time Rate", False),))
        )
        assert result.missing_measures == ("On Time Rate",)

    def test_the_calendar_supplies_its_own_columns(self):
        """`dim_date` is generated rather than shaped, so it is not in `spec.tables`."""
        document = {
            "insights": [
                {
                    "id": "x",
                    "product": "invoicing",
                    "dimensions": ["dim_date.full_date"],
                    "status": "confirmed",
                }
            ]
        }
        parsed = parse_insights(document)
        (without,) = check_coverage(parsed.insights, _spec())
        (with_calendar,) = check_coverage(parsed.insights, _spec(calendar=True))
        assert without.missing_dimensions == ("dim_date.full_date",)
        assert with_calendar.covered


class TestBrief:
    def test_it_groups_by_persona_and_states_coverage(self):
        parsed = parse_insights(_DOCUMENT)
        coverage = check_coverage(parsed.for_product("invoicing"), _spec())

        brief = render_insight_brief("invoicing", parsed, coverage)

        assert "## cfo — Owns the number" in brief
        assert "## ops-manager — Runs the terminal day to day" in brief
        assert "How many departures left on time this week, by terminal?" in brief
        assert "**Compared against.** prior week" in brief
        assert "✅ covered" in brief
        assert "⚠ not answerable yet" in brief
        assert "Missing columns: `dim_customer.nope`" in brief

    def test_it_is_honest_when_nothing_is_authored(self):
        brief = render_insight_brief("invoicing", parse_insights({}), ())
        assert "No insights are authored for this product yet." in brief


def test_the_documented_shape_round_trips(tmp_path):
    """The YAML in the skill and template must actually parse."""
    path = tmp_path / "integration" / "discovery" / "bi"
    path.mkdir(parents=True)
    (path / "insights.yaml").write_text(yaml.dump(_DOCUMENT), encoding="utf-8")
    assert len(load_insights(tmp_path).insights) == 2
