### Fixed
- **A date-sliced insight is no longer reported as unanswerable (issue #747).** Insight
  coverage resolved `dim_date` against a two-element allowlist (`date_key`, `full_date`),
  so any insight slicing by month or year came back "not answerable yet" naming a column
  the warehouse demonstrably had. On one hub that was 6 of 9 insights — essentially every
  legacy report compares a period against a prior period — and the false negatives drowned
  the two real findings. The brief is the hand-off artifact to the BI engineer, so it was
  telling them the model could not answer questions it could.

- **…and `dim_date` now actually carries those columns in Power BI.** This is the half the
  issue did not reach: the TMDL declared only `date_key` and `full_date`, so
  `dim_date.month_number` was genuinely *absent from the semantic model* even though the
  dbt model and the DDL both built it. Coverage was telling the truth; the emitter was
  under-declaring the table. Widening the checker alone would have made the brief lie in
  the other direction.

  The column list was restated in seven places and they had drifted. It is now declared
  once, in `core.projections.dbt.calendar_columns`, and the dbt model, the DDL, the TMDL,
  the dbt `schema.yml`, the ERD, the measure-dependency allowlist and the insight-coverage
  allowlist all read it.

### Added
- **`dim_date` gains `quarter_number` and `month_name`.** Both are pure functions of the
  date and the macros to compute them already existed; month name was sliced on 32 times
  across 4 reports in the surveyed client estate. Every emitted surface picks them up
  automatically from the declaration.

### Known issues
- `week_number` is still not emitted, even though the calendar records a `week_pattern`.
  That column depends on a week-numbering convention nothing currently implements, so
  emitting it would repeat the mistake `week_pattern` already makes — declaring a
  convention the dimension does not honour. Tracked separately.
