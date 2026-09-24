### Added
- **`compile --check` now reports BPA findings in Gold measures and columns (DD-238).**
  Two block, because they are exact for the references a measure declares:
  `gold.dax-column-unqualified` (a column referenced as `[amount]` instead of
  `fact_sale[amount]`) and `gold.dax-measure-qualified` (a measure referenced with a table
  prefix). Three warn: `gold.description-missing` (visible columns without an ontology
  `rdfs:comment`, one warning per table), `gold.float-column` and
  `gold.dax-division-operator`. String literals and comments are never read as references.
  A `kairos-ext:bpaIgnoreRule` with its reason excuses one object; an exception excusing
  nothing fails with `gold.bpa-ignore-unused`.
- **`emit-gold` and `package-powerbi-release` assert the profile's guarantees on the
  rendered model**: a marked date table with a DateTime key, a sorted `month_name`, visible
  numbers never summarized, every column sourced, every measure with an expression and a
  format string, no control characters in descriptions, and no active relationship between
  columns of different types.

### Changed (BREAKING for hubs whose measures reference columns unqualified)
- A measure written `SUM([total_amount])` -- the form the scaffold template used to teach --
  now fails `compile --check`. Qualify the reference (`SUM(fact_invoice[total_amount])`), or
  record a `bpaIgnoreRule` with the reason the rule does not hold.

### Fixed
- **An authored-policy failure in Gold keeps its own code.** A provisional measure missing
  `measureDataType`, for example, surfaced as `safety.type-incompatible: projection
  normalization failed` at the hub root. It now reports
  `measure.incomplete-semantic-contract` with its rule, located at the domain's Gold
  extension.
- Descriptions drop control characters before they reach the TMDL.
- **Perspectives are no longer empty.** A perspective was emitted as bare `perspectiveTable`
  lines with no members, which Tabular Editor's Best Practice Analyzer, run against the acme
  model, reported as a perspective with no objects. Each perspective now lists every column and
  emitted measure of the tables it declares, as Desktop writes them.
