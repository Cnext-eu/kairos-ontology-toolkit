### Added
- **Gold products can author report parameters and calculation groups (#1113, DD-262).** A
  report live-connected to a deployed model cannot add a calculated table, so what a viewer
  switches now comes from the hub. `kairos-ext:Parameter` takes a `parameterKind`: `field`
  (pick which column or measure a visual shows), `selector` (pick a label measures react to)
  or `range` (pick a number). Each is emitted as the disconnected calculated table Power BI
  Desktop writes for it, with a `<name> Value` measure for selectors and ranges.
  `kairos-ext:CalculationGroup` with `CalculationItem`s is emitted beside Time Intelligence
  with a precedence of its own. A measure reading a parameter declares
  `kairos-ext:measureParameterDependency`, and any measure can carry a dynamic format string
  with `kairos-ext:measureFormatStringExpression`. Every reference fails closed: field items
  must resolve to emitted columns or measures, names may not collide with tables, defaults
  lie within their values, and precedences are unique. Write ordered lists as a Turtle
  collection, `( "A" "B" )`. See the `kairos-design-gold` skill and the commented examples
  in `gold-ext.ttl.template`.

### Changed
- **The BPA profile moves to version 3.** `REDUCE_USAGE_OF_CALCULATED_TABLES` is now a
  render assertion rather than "by construction": a calculated table is emitted only as a
  report parameter, which reads no Direct Lake data, and each one records the exception (and
  `ENSURE_TABLES_HAVE_RELATIONSHIPS`, since it is disconnected by design) in its
  `BestPracticeAnalyzer_IgnoreRules` annotation. The dataplatform's BPA notebook embeds the
  profile, so it refreshes on the next update; the previous generation is recorded, so it
  refreshes automatically. A model with an authored calculation group sets
  `discourageImplicitMeasures` even without a calendar, as the engine requires.
