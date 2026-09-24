### Fixed
- **A table a binding reads no longer blocks `compile` as an undecided unanchored table
  (#973).** Since #948, the DD-180 gate counted only table-grain ledger rows as decisions.
  It never looked at bindings, so a table that is bound but has no reference-class
  anchor could not be cleared by any command:
  - `source-disposition set --disposition bound` is refused, because the binding is
    what states it.
  - `deferred` makes `validate` fail with `disposition.bound-and-ruled-out`.
  - `not-business-data` un-decides the bound join columns.

  The gate now uses `load_bound_relations`, the same check as the DD-164 audit, so
  `compile` and `validate` agree on which tables are bound. Hand-written table-grain
  `bound` rows added as a workaround are no longer needed and can be removed.
- **`source.dbtModel` bindings count the tables their whole `ref()` chain reads (#973).**
  Before, only the selected model's own SQL was scanned. Under the three-layer rule
  (#949), the `int_merged__` model a binding selects reads no `source()` itself; the
  `stg_` stages two `ref()` levels down do. Scanning one model therefore found none of
  the tables, and all of them were reported as unbound. The chain is now followed. A
  `ref()` that matches no model, or more than one, ends that branch without an error;
  `compile` still reports it.
