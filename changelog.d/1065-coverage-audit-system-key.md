### Fixed
- **`audit-column-coverage` keys tables by system and table, and reads dbtModel bindings.**
  The audit keyed every binding by table name alone. Two systems with a table of the same
  name shared one bucket, so a binding on one system's `customers` hid the other's as
  bound and reported its columns as orphans of the wrong binding. A `source.dbtModel`
  binding was attached to a table named `""`, and every table its model chain reads was
  reported unbound, with all its columns as orphans. Now:
  - every finding is keyed by `(system, table)`, where the system is the
    `integration/sources/<system>/` directory, the same name a binding's `source.relation`
    carries;
  - a table a dbtModel chain reads is bound, and a column the chain's SQL names is
    referenced (DD-250);
  - when a chain reads a table with `select *`, its other columns are listed in a new
    lineage-unconfirmed section instead of as orphans.

  JSON output moves to `schema_version: 2`. Every finding carries `system`, orphans carry
  `read_by_models`, and a `lineage_unconfirmed` list is added. Text output prints
  `system.table`. A table bound only through a chain is not checked for cross-domain
  candidates, and a note says so.
