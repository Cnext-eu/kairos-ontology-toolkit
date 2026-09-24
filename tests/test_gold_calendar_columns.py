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

    def test_each_description_precedes_its_column_declaration(self):
        """A TMDL `///` description belongs *before* the object, at the object's indent,
        which is how `_table_tmdl` renders every other table. Emitted after
        `sourceColumn:` inside the column body it is not a description but an unparseable
        line: the TOM serializer rejected every calendar-bearing model ("Unexpected line
        type: Empty!") and Fabric could not load it. Substring checks passed regardless."""
        from kairos_ontology.core.projections.dbt.gold_render import _date_tmdl

        physical = SimpleNamespace(
            semantic_mode="directLake", adapter="databricks", catalog="", schema_name=""
        )
        lines = _date_tmdl(_calendar(), physical, None).splitlines()

        described = [index for index, line in enumerate(lines) if line.startswith("\t/// ")]
        assert len(described) == len(CALENDAR_COLUMNS)
        for index in described:
            assert lines[index + 1].startswith("\tcolumn "), lines[index : index + 2]
        assert not any(line.startswith("\t\t///") for line in lines)

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


class TestWeekNumber:
    """#833: `week_pattern` was echoed onto every row and nothing acted on it."""

    @staticmethod
    def _fact(week: str):
        from kairos_ontology.core.projections.dbt.policy_specs import (
            AuthoredValuesFact,
            CalendarFact,
        )

        uri = "https://example.test/ontology/party#Calendar"

        def value(*items: str) -> AuthoredValuesFact:
            return AuthoredValuesFact(uri, "urn:predicate", items)

        return CalendarFact(
            resource_uri=uri,
            start_date=value("2020-01-01"),
            end_date=value("2030-12-31"),
            fiscal_year_start_month=value("1"),
            week_pattern=value(week),
            locale=value("en-BE"),
            holiday_source=value("none-approved"),
            time_zone=value("Europe/Brussels"),
            period_closure=value("none"),
            role_playing_dates=value("orderDate"),
            approval_status=value("approved"),
        )

    @pytest.mark.parametrize("week", ["iso-8601", "iso-8601-monday"])
    def test_the_iso_patterns_are_accepted(self, week):
        from kairos_ontology.core.projections.dbt.policy_normalize import _normalize_calendar

        assert _normalize_calendar(self._fact(week)).week_pattern.value == week

    @pytest.mark.parametrize("week", ["us-sunday", "iso-8601-sunday", "ISO"])
    def test_a_pattern_the_calendar_does_not_implement_is_rejected(self, week):
        from kairos_ontology.core.projections.dbt.policy_normalize import (
            PolicyNormalizationError,
            _normalize_calendar,
        )

        with pytest.raises(PolicyNormalizationError) as excinfo:
            _normalize_calendar(self._fact(week))
        assert excinfo.value.code == "calendar.unsupported-week-pattern"

    def test_the_shacl_shape_enumerates_the_same_patterns(self):
        """Authoring-time validation and normalization must accept the same set."""
        from importlib import resources

        from kairos_ontology.core.projections.dbt.calendar_columns import ISO_WEEK_PATTERNS

        shapes = (
            resources.files("kairos_ontology.scaffold")
            .joinpath("kairos-ext-shapes.shacl.ttl")
            .read_text(encoding="utf-8")
        )
        enumerated = " ".join(f'"{item}"' for item in sorted(ISO_WEEK_PATTERNS))
        assert f"sh:in ( {enumerated} )" in shapes

    @pytest.mark.parametrize(
        ("adapter", "week_function"),
        [("databricks", "weekofyear(date_day)"), ("fabric-warehouse", "datepart(iso_week,")],
    )
    def test_the_week_number_is_iso_on_each_adapter(self, adapter, week_function):
        """T-SQL's plain `week` part counts from Jan 1 and is not ISO; Spark's
        weekofyear is."""
        from kairos_ontology.core.projections.dbt.gold_render import _dbt_calendar_sql

        sql = _dbt_calendar_sql(_calendar(), adapter)
        assert f"{week_function}" in sql
        assert "datepart(week," not in sql

    def test_the_week_start_does_not_depend_on_datefirst(self):
        from kairos_ontology.core.projections.dbt.gold_render import _dbt_calendar_sql

        sql = _dbt_calendar_sql(_calendar(), "fabric-warehouse")
        assert "weekday" not in sql
        assert "cast('19000101' as date)" in sql

    def test_an_insight_slicing_by_week_resolves(self):
        spec = SimpleNamespace(measures=(), tables=(), calendar=_calendar())
        insight = TestInsightCoverage._insight(
            f"{CALENDAR_TABLE}.week_number", f"{CALENDAR_TABLE}.week_start_date"
        )
        assert check_coverage((insight,), spec)[0].missing_dimensions == ()


def _column_blocks(tmdl: str) -> dict[str, list[str]]:
    """Column name -> its property lines, from a rendered `dim_date` table."""
    blocks: dict[str, list[str]] = {}
    current = None
    for line in tmdl.splitlines():
        if line.startswith("\tcolumn "):
            current = line.removeprefix("\tcolumn ").strip()
            blocks[current] = []
        elif line.startswith("\t\t") and current is not None:
            blocks[current].append(line.strip())
        elif line.strip():
            # Any other object at table level (a description, the partition) ends it.
            current = None
    return blocks


def _rendered_date_table() -> str:
    from kairos_ontology.core.projections.dbt.gold_render import _date_tmdl

    physical = SimpleNamespace(
        semantic_mode="directLake", adapter="databricks", catalog="", schema_name=""
    )
    return _date_tmdl(_calendar(), physical, None)


class TestBestPracticeByDesign:
    """DD-238 / #979: dim_date renders the way `_table_tmdl` renders every other table."""

    def test_every_calendar_column_is_never_summarized(self):
        blocks = _column_blocks(_rendered_date_table())
        assert set(blocks) == CALENDAR_COLUMN_NAMES
        for name, properties in blocks.items():
            assert "summarizeBy: none" in properties, name

    def test_every_calendar_column_has_a_stable_distinct_lineage_tag(self):
        from kairos_ontology.core.projections.dbt.gold_render import _guid

        blocks = _column_blocks(_rendered_date_table())
        tags = {
            name: next(item for item in properties if item.startswith("lineageTag: "))
            for name, properties in blocks.items()
        }
        assert len(set(tags.values())) == len(tags)
        assert tags["month_number"] == f"lineageTag: {_guid('dim_date.month_number')}"
        assert _rendered_date_table() == _rendered_date_table()

    def test_month_name_sorts_by_month_number(self):
        blocks = _column_blocks(_rendered_date_table())
        assert "sortByColumn: month_number" in blocks["month_name"]
        sorted_columns = [name for name, props in blocks.items() if any("sortByColumn" in p for p in props)]
        assert sorted_columns == ["month_name"]

    def test_the_key_is_the_datetime_column_the_relationships_join(self):
        from kairos_ontology.core.projections.dbt.gold_shape import CALENDAR_COLUMN

        blocks = _column_blocks(_rendered_date_table())
        keyed = [name for name, properties in blocks.items() if "isKey" in properties]
        assert keyed == ["full_date"] == [CALENDAR_COLUMN]
        assert "dataType: DateTime" in blocks["full_date"]
        assert "dataCategory: Time" in _rendered_date_table()

    def test_every_role_relationship_targets_the_key(self):
        from kairos_ontology.core.projections.dbt.gold_shape import _calendar_relationships
        from kairos_ontology.core.projections.dbt.gold_specs import GoldCalendarRoleSpec
        from dataclasses import replace

        calendar = replace(
            _calendar(),
            roles=(
                GoldCalendarRoleSpec("Ordered", "fact_order", "ordered_date"),
                GoldCalendarRoleSpec("Shipped", "fact_order", "shipped_date"),
            ),
        )
        keyed = next(item.name for item in CALENDAR_COLUMNS if item.marks_date_table)
        assert {item.target_column for item in _calendar_relationships(calendar)} == {keyed}

    def test_the_warehouse_key_is_unchanged(self):
        """Only the semantic model moves: the DDL, ERD and dbt tests still key on date_key."""
        assert [item.name for item in CALENDAR_COLUMNS if item.is_key] == ["date_key"]

    @pytest.mark.skipif(
        __import__("shutil").which("dotnet") is None, reason="dotnet SDK not installed"
    )
    def test_a_calendar_bearing_model_deserializes_in_tom(self):
        import tests.test_gold_projector as harness
        from kairos_ontology.core.projections.dbt.tmdl_validate import validate_tmdl_artifacts

        artifacts = harness._generate("invoice")
        assert any(path.endswith("/tables/dim_date.tmdl") for path in artifacts)
        results = validate_tmdl_artifacts(artifacts)
        assert results and all(item.status == "pass" for item in results), [
            item.message for item in results
        ]
