### Added
- **The time-intelligence calculation group compares against the prior period.** Next to
  `Current`, `YTD`, `QTD` and `MTD` it now carries `PM` (prior month), `PY` (prior year),
  `MoM %` and `YoY %`. The two percentage items format as `0.0%`, and the others keep the
  measure's own format. Every measure gets its comparison without per-measure authoring,
  which a hub could not do anyway: a measure naming `dim_date[full_date]` in `DATEADD`
  counted the calendar as a second home table. Additive: no existing item or ordinal
  changes. Verified on a deployed Direct Lake model through `executeQueries`.
