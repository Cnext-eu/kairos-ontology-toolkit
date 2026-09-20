### Fixed
- **`propose-relationships` no longer emits one proposal per property for a single join.**
  A reference model routinely declares a generic relationship and a set of typed
  specialisations of it — a consignment's generic "has party" alongside consignor,
  consignee, carrier, freight forwarder and notify party. All of them link the same two
  classes, so every one matched the same endpoint pair and the same derived join, and each
  was emitted as an independent, equally-confident proposal. They are mutually exclusive:
  one foreign key cannot be the carrier *and* the consignee. Proposals are now grouped by
  the join they share, a property that is an `rdfs:subPropertyOf` descendant of another in
  the group is folded into it, and what remains is reported as one decision. Measured on
  one hub: nine proposals with resolved joins were three distinct joins, and accepting
  them as printed would have asserted five mutually exclusive party roles on one key.
- **A genuine either/or is no longer pasteable as one of its arms.** When the competing
  properties stand in no hierarchy — two directional properties on one non-directional
  column, say — the rendered entry carries `<CONFIRM_PROPERTY>` and lists every candidate
  above it. Naming one would make an arbitrary pick look derived, and a paste that skipped
  the surrounding note would take it.

### Added
- **`propose-relationships` checks the target class against the child domain's import
  closure.** A relationship is authored in the child's binding and resolved through the
  child domain's `owl:imports`, so a proposal naming a class that domain cannot see fails
  `compile` with `safety.relationship-endpoint` the moment it is pasted. Such proposals
  are now flagged in the summary, carry `target_resolvable: false` in `--format json`, and
  render with a comment naming what has to be imported first.
