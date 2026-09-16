### Fixed
- **The semantic model no longer declares columns the Gold table does not have (issue #793).**
  The DD-109 `_kairos_fk_*_match_count` diagnostics reached the TMDL and the Gold DDL but never
  the dbt models that build the Gold tables, so the semantic model described a table shape that
  never existed and a Direct Lake refresh failed with `Delta protocol violation: the column
  _kairos_fk_<hash>_match_count is not found in delta table`. The cause is two `GoldTableSpec`
  objects shaped at different ages from one compile plan: `shape_project` shapes the Gold product
  before the compiler injects the diagnostics, and only `emit-gold` re-shapes afterwards, so
  `compile --emit` rendered the dbt models from the older spec. The diagnostics are now excluded
  from the Gold projection in the one function every Gold writer derives from, so the dbt model,
  the DDL, the TMDL, the ERD and the schema YAML agree by construction. They remain exactly where
  they belong, in Silver, and the Gold product report still records them under
  `silver_authority`. See DD-225, which supersedes DD-221 on this one column only — the rule that
  hiding is decided on provenance rather than role is unchanged.
- **A Gold table's primary key must be a column the product actually emits.** `_primary_key` read
  the raw Silver model while the emitted column set is filtered, and nothing reconciled them, so
  authoring `goldExcludeColumn` against a table's key left the key naming a column that is not
  there. Every consequence was silent: the relationship shaper pointed `toColumn` at a missing
  column, and `isKey`, the dbt `unique` test and the ERD `PK` marker simply stopped appearing —
  Power BI accepted the dangling endpoint at validation and rejected the model on load. This now
  fails closed as `gold.primary-key-not-emitted`.

### Removed
- **A dead type-inference branch for `_kairos_fk_match_count_*` columns.** No producer ever
  emitted that spelling — the real name is `_kairos_fk_<hash>_match_count` — so the branch was
  unreachable.
