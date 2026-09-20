### Changed
- **`anchor-tables` now requires an authored business glossary, like `propose-alignment`
  already did.** Anchoring decides what every source table *is* — its class, domain,
  grain and natural key — in one global call that everything downstream inherits, and it
  ran with no business-discovery prerequisite at all. The check `propose-alignment` has
  carried for some time is now shared by both commands, with the same
  `--without-discovery` escape and the same warning when it is used: blocking rather than
  warning, because a warning about ungrounded input is read after the expensive call has
  already been paid for.
