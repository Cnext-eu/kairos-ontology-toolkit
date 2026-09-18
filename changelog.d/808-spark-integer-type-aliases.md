### Fixed
- **Spark's `long`, `short` and `byte` are now recognised source types (issue #808).** The
  compiler's type-alias table was T-SQL-flavoured and had no entry for Spark's integer
  names, but `import-source` writes the source catalog's `data_type` through verbatim — so
  on a Databricks-backed hub every 64-bit integer arrives as `long`. A column whose type
  missed the table was dropped from the bound relation's symbol table before any binding
  expression touched it, and referencing it anywhere — `fields:`, `grain.columns`,
  `identity.sourceKey`, `quality:` — failed with `safety.column-unresolved: not a column of
  the bound relation`. On one real hub that was 123 columns, essentially every weight,
  dimension, tonnage and monetary amount, producing a Silver contract with almost no
  measures in it. There was no binding-side workaround: `cast` is deliberately outside the
  closed scalar-expression grammar, so the only escape was a hand-written passthrough dbt
  model per affected table.
- **`scaffold-binding` no longer proposes `VARCHAR(255)` for an integer column.** The
  Fabric and Databricks warehouse type maps had the same gap and fell through to their
  string default, so the wrong type was baked into authored bindings before the compiler
  ever saw them.
- **An unrecognised source type now says so.** The diagnostic names the offending type and
  points at `kairos-ontology suggest-type` instead of claiming the column does not exist —
  the old message sent four separate authors hunting a schema problem that did not exist.
  `suggest-type`'s own "Supported:" list is now rendered from the compiler's table rather
  than hand-maintained beside it, which is how it came to omit these names in the first
  place.
