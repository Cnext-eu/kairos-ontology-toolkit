# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The one declaration of what ``dim_date`` contains (#747).

The calendar is synthesized at render time rather than shaped from a Silver model, so it
is not a ``GoldTableSpec`` and nothing that walks ``spec.tables`` can see it. Its column
list was consequently restated in seven places, and they disagreed: the dbt model and the
DDL built eleven columns while the TMDL, the dbt ``schema.yml``, the ERD, the
measure-dependency allowlist and the insight-coverage allowlist each knew about two.

The visible symptom was insight coverage reporting every date-sliced insight as
unanswerable — 6 of 9 on one hub, because essentially every legacy report compares a
period against a prior period — while naming a column that demonstrably existed in the
warehouse. But coverage was telling the truth about Power BI: with only ``date_key`` and
``full_date`` in the TMDL, ``dim_date.month_number`` really was absent from the semantic
model. The defect was the emitter under-declaring the table, not only the checker
under-resolving it.

The dbt model SQL and the TMDL table read this tuple, and the SQL builder is checked
against these names by test so the two cannot drift apart again. The DDL
(``gold_render._ddl``) still lists its columns by hand: keep it in step when adding one.
"""

from __future__ import annotations

from dataclasses import dataclass


#: The ``weekPattern`` values the generated calendar implements (#833). Both name ISO 8601
#: weeks: Monday is the first day, and week 1 is the week holding the year's first
#: Thursday. ``iso-8601-monday`` states the week-start day explicitly and means the same.
#: A convention outside this set is rejected when the profile is normalized, because
#: echoing it onto every row beside an ISO ``week_number`` would declare one convention
#: and implement another.
ISO_WEEK_PATTERNS: frozenset[str] = frozenset({"iso-8601", "iso-8601-monday"})


@dataclass(frozen=True, slots=True)
class CalendarColumn:
    """One column of the generated calendar dimension."""

    name: str
    #: Canonical kind, resolved per adapter at each emission site rather than stored as a
    #: dialect string: the DDL needs ``VARCHAR(128)``/``STRING`` and the TMDL needs
    #: ``String``, and hard-coding either here would just move the duplication.
    kind: str
    description: str
    #: False for the governance columns, which carry the profile's declared policy on
    #: every row rather than a property of the date.
    is_date_attribute: bool = True
    #: The warehouse primary key: the DDL, the ERD and the dbt tests key on it.
    is_key: bool = False
    nullable: bool = False
    #: The semantic model's key (DD-238). Power BI and the BPA rules recognise a date
    #: table by a DateTime ``isKey`` column in a ``dataCategory: Time`` table, and every
    #: role relationship already joins ``full_date``, so this -- not the Int64
    #: ``date_key`` -- is what the TMDL marks.
    marks_date_table: bool = False
    #: The column a text column sorts by in the semantic model, so ``month_name`` reads
    #: January..December rather than alphabetically.
    sort_by: str = ""


#: Ordered exactly as the generated ``select`` emits them, which is also the order the DDL
#: declares and the order a reader of the TMDL sees.
CALENDAR_COLUMNS: tuple[CalendarColumn, ...] = (
    CalendarColumn("date_key", "int64", "YYYYMMDD date key.", is_key=True),
    CalendarColumn("full_date", "date", "Calendar date.", marks_date_table=True),
    CalendarColumn("year_number", "int32", "Calendar year."),
    CalendarColumn("quarter_number", "int32", "Calendar quarter, 1-4."),
    CalendarColumn("month_number", "int32", "Calendar month, 1-12."),
    CalendarColumn(
        "month_name",
        "string",
        "Full month name, in the calendar locale.",
        sort_by="month_number",
    ),
    CalendarColumn("day_of_month", "int32", "Day of the month, 1-31."),
    CalendarColumn("week_number", "int32", "ISO 8601 week of the year, 1-53."),
    CalendarColumn(
        "week_start_date",
        "date",
        "Monday that starts the ISO week; sorts and groups weeks across a year boundary.",
    ),
    CalendarColumn(
        "fiscal_year_start_month",
        "int32",
        "Declared fiscal year start month, from the calendar profile.",
        is_date_attribute=False,
    ),
    CalendarColumn(
        "week_pattern",
        "string",
        "Declared week-numbering convention, from the calendar profile.",
        is_date_attribute=False,
    ),
    CalendarColumn(
        "calendar_locale",
        "string",
        "Declared locale, from the calendar profile.",
        is_date_attribute=False,
    ),
    CalendarColumn(
        "calendar_time_zone",
        "string",
        "Declared time zone, from the calendar profile.",
        is_date_attribute=False,
    ),
    CalendarColumn(
        "period_closure_policy",
        "string",
        "Declared period-closure policy, from the calendar profile.",
        is_date_attribute=False,
    ),
    CalendarColumn(
        "is_holiday",
        "boolean",
        "Whether the date is a holiday; null when no holiday source is configured.",
        nullable=True,
    ),
)

#: The bare column name of every calendar column, for the checks that resolve an authored
#: ``dim_date.<column>`` reference against what the product carries; callers prefix the
#: table themselves.
CALENDAR_COLUMN_NAMES: frozenset[str] = frozenset(item.name for item in CALENDAR_COLUMNS)

#: The one column the semantic model keys ``dim_date`` on, and so the one every calendar
#: role relationship must join (DD-238).
CALENDAR_DATE_TABLE_KEY: str = next(item.name for item in CALENDAR_COLUMNS if item.marks_date_table)
