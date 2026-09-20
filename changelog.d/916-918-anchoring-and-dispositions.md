### Added
- **`anchor-tables` reports tables of different grain anchored to one class.** The
  `likely_entity` field has always been persisted so a detector could "detect when tables
  with different candidate entities collapse onto one `ref_class`" — that detector was
  never written. Meanwhile the collapse happens: on one hub a unit-grain table and an
  item-grain table anchored to the same class, and a port-pair table and a multi-leg table
  to another. Nothing objected until `compile` raised `conformance.group-required`, a gate
  that asks the author to declare a **merge** — which for two different grains is exactly
  the wrong remedy and fans out silently once followed. The report says so explicitly.

  Two conditions are required and arity is the discriminator: differing *candidate
  entities* and a differing *number* of natural-key columns. Two systems spelling one key
  differently is not a grain difference, and a false "these are not the same entity"
  invites a re-anchor that is wrong.

- **`anchor-tables` reports replication lanes.** A CDC or data-factory copy exposes the
  same business table plus a watermark; both copies then anchor identically and present as
  a multi-source estate that does not exist. Measured on one hub: eight pairs, 21% of
  anchored tables and 25% of the alignment spend, each contributing a false conformance
  merge. Detection is on column sets, not names — a candidate whose columns are a superset
  of another's within the same system, adding at most three columns, all of them
  operational. The report deliberately does not recommend dropping the replica: a CDC lane
  is often the *more current* copy, so it is a choice, not a cleanup.

### Fixed
- **`generate-bindings` honours table-grain dispositions.** It loaded the ledger and used
  only the column-grain half, so a table recorded as `not-business-data`, `blueprint-gap`
  or `deferred` had a binding generated for it anyway. Since `--force` is the documented
  way to pick up a corrected anchor, every legitimate regeneration silently undid every
  table-grain decision a hub had made — nine tables on one hub, eight of them replicas
  whose bindings had produced the false merge the dispositions were recorded to resolve.
  That made the decisions look ineffective rather than ignored.

  `bound` deliberately does not skip: it asserts a binding *exists*. An explicit `--table`
  still generates, so one dispositioned table can be regenerated without clearing the
  ledger.
