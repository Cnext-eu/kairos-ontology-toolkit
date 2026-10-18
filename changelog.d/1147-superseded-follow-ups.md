### Fixed
- **A source table no domain reads any more leaves the published `_<system>__sources.yml`.**
  `compile --emit` unioned each shared source catalog with the file already on disk, so a
  table could be added but never removed: a deleted binding, a move to `dbtModel`, a renamed
  table or a `superseded` one stayed declared. The dataplatform's `validate-source-bindings`
  then kept demanding a physical binding for it, so the old loader could not be retired. Each
  domain now records what it contributes (`.kairos-compile-sources.<domain>.json` in the
  emitted project), and once every domain has a record the shared catalogs are rebuilt from
  them; a catalog nothing contributes to is removed. A target emitted before this change has
  no records, so it keeps the old union until every domain has re-emitted once, which
  `compile --all --emit` does in one run. In the dataplatform, delete the physical binding of
  a table the hub stops declaring in the same PR that bumps the package, or
  `validate-source-bindings` reports it as `unknown`.
- **A table-grain `superseded` outranks the table's column rows.** Column rows recorded
  before the table was superseded, such as a `deferred` waiting for a property or a `bound`
  through a dbt chain since removed, still counted: a deferred column stayed in
  `alignment-report`'s backlog and in `next`. The gap gate, the deferred backlog and `next`
  now read the table row for every column of a superseded table. `validate` warns about the
  leftover rows (`disposition.column-rows-under-superseded-table`), and
  `source-disposition clear --system S --table T --column-grain-only` withdraws them while
  keeping the table's own row.
