# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Every surface that names a `dim_date` column agrees with one declaration (#747).

The calendar is synthesized at render time rather than shaped from a Silver model, so it
is not a `GoldTableSpec` and nothing walking `spec.tables` can see it. Its column list was
restated in seven places and they disagreed: the dbt model and the DDL built eleven
columns; the TMDL, the dbt `schema.yml`, the ERD, the measure-dependency allowlist and the
insight-coverage allowlist each knew about two.

The reported symptom was insight coverage calling every date-sliced insight unanswerable --
6 of 9 on one hub, because essentially every legacy report compares a period against a
prior period -- while naming a column the warehouse demonstrably had. But coverage was
*right* about Power BI: with two columns in the TMDL, `dim_date.month_number` really was
absent from the semantic model. The emitter was under-declaring the table, so widening the
checker alone would have made the insight brief lie in the other direction.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from kairos_ontology.core.insights import Insight, check_coverage
from kairos_ontology.core.projections.dbt.calendar_columns import (
    CALENDAR_COLUMN_NAMES,
    CALENDAR_COLUMNS,
)
from kairos_ontology.core.projections.dbt.gold_shape import (
    CALENDAR_TABLE,
    _CALENDAR_COLUMNS,
)


def _calendar(*, approved: bool = True):
    from kairos_ontology.core.projections.dbt.gold_specs import GoldCalendarSpec

    return GoldCalendarSpec(
        resource_uri="https://example.test/ontology/party#Calendar",
        start_date="2020-01-01",
        end_date="2030-12-31",
        fiscal_year_start_month=1,
        week_pattern="iso-8601-monday",
        locale="en-BE",
        holiday_source="none-approved",
        time_zone="Europe/Brussels",
        period_closure="none",
        roles=(),
        approved=approved,
    )


class TestDeclaration:
    def test_the_column_the_reported_hub_asked_for_is_declared(self):
        """`month_number` is the one the reported insights named and could not resolve."""
        assert "month_number" in CALENDAR_COLUMN_NAMES

    def test_the_governance_columns_are_marked_as_such(self):
        """`week_pattern` and friends carry the profile's declared policy on every row
        rather than a property of the date, which a consumer may want to tell apart."""
        attributes = {item.name for item in CALENDAR_COLUMNS if item.is_date_attribute}
        assert "month_number" in attributes
        assert "week_pattern" not in attributes

    def test_exactly_one_column_is_the_key(self):
        assert [item.name for item in CALENDAR_COLUMNS if item.is_key] == ["date_key"]

    def test_names_are_unique(self):
        names = [item.name for item in CALENDAR_COLUMNS]
        assert len(names) == len(set(names))


class TestEmittedSurfaces:
    """Each of these restated the column list and drifted from the dbt model and DDL."""

    def test_the_tmdl_declares_every_column(self):
        from kairos_ontology.core.projections.dbt.gold_render import _date_tmdl

        # directLake needs no connection object, which keeps this a unit test of the
        # column block rather than of partition rendering.
        physical = SimpleNamespace(
            semantic_mode="directLake", adapter="databricks", catalog="", schema_name=""
        )
        tmdl = _date_tmdl(_calendar(), physical, None)

        for column in CALENDAR_COLUMNS:
            assert f"column {column.name}" in tmdl, column.name
            assert f"sourceColumn: {column.name}" in tmdl, column.name
        assert "isKey" in tmdl

    @pytest.mark.parametrize("adapter", ["databricks", "fabric-warehouse"])
    def test_the_dbt_model_selects_every_column(self, adapter):
        """The SQL is hand-built per adapter, so this keeps the generated *data* in step
        with everything else derived from the declaration."""
        from kairos_ontology.core.projections.dbt.gold_render import _dbt_calendar_sql

        sql = _dbt_calendar_sql(_calendar(), adapter)
        for column in CALENDAR_COLUMNS:
            assert f" as {column.name}" in sql, (adapter, column.name)


class TestMeasureDependencies:
    def test_the_allowlist_is_the_declaration(self):
        """It was `{date_key, full_date}`, so a measure depending on
        `dim_date.month_number` -- a column the dbt model and DDL both built -- did not
        resolve."""
        assert _CALENDAR_COLUMNS == CALENDAR_COLUMN_NAMES
        assert "month_number" in _CALENDAR_COLUMNS


class TestInsightCoverage:
    """The reported symptom, exercised through the real coverage check."""

    @staticmethod
    def _spec(*, approved: bool = True):
        # check_coverage reads only measures, tables and calendar.
        return SimpleNamespace(measures=(), tables=(), calendar=_calendar(approved=approved))

    @staticmethod
    def _insight(*dimensions: str) -> Insight:
        return Insight(
            id="monthly_customers",
            persona="analyst",
            question="How many customers per month?",
            kpi="Customer count",
            product="party",
            measures=(),
            dimensions=dimensions,
            status="confirmed",
        )

    def test_a_date_sliced_insight_is_covered(self):
        coverage = check_coverage((self._insight(f"{CALENDAR_TABLE}.month_number"),), self._spec())
        assert coverage[0].missing_dimensions == ()
        assert coverage[0].covered

    def test_every_declared_calendar_column_resolves(self):
        insight = self._insight(
            *(f"{CALENDAR_TABLE}.{name}" for name in sorted(CALENDAR_COLUMN_NAMES))
        )
        assert check_coverage((insight,), self._spec())[0].missing_dimensions == ()

    def test_a_column_the_calendar_does_not_have_is_still_reported(self):
        """Widening must not become accepting anything. `week` is the column the shipped
        docs used to reference and the calendar has never emitted."""
        coverage = check_coverage((self._insight(f"{CALENDAR_TABLE}.week"),), self._spec())
        assert coverage[0].missing_dimensions == (f"{CALENDAR_TABLE}.week",)

    def test_a_draft_calendar_grants_nothing(self):
        """The allowlist is gated on approval, and widening it must not change that."""
        coverage = check_coverage(
            (self._insight(f"{CALENDAR_TABLE}.month_number"),), self._spec(approved=False)
        )
        assert coverage[0].missing_dimensions == (f"{CALENDAR_TABLE}.month_number",)
