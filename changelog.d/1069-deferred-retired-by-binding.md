### Fixed
- **A deferred column that a binding now maps leaves the deferred backlog.** DD-251 says a
  binding that names a deferred column retires it, but the backlog read the ledger alone. A
  column deferred, then modelled and bound, stayed "deferred" in `next`, in the
  `alignment-report` backlog, and on `draft-gap-decisions --include-deferred`, so the
  backlog could only grow. Now a column-grain `deferred` row gives way to a `source.relation`
  binding that names the column. `alignment-report` counts the column as bound and lists the
  stale ledger row in a new "Deferred rows a binding has retired" section. The sheet no
  longer re-lists it. Only `deferred` gives way: a ruled-out column a binding still names
  keeps its ledger decision. A `source.dbtModel` chain that reads the column is still
  evidence only (DD-250), so the column stays in the backlog.
