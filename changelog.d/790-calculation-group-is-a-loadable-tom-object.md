### Fixed
- **The emitted time-intelligence calculation group can actually be created (issues #790, #791).**
  A calculation group is a table, and the Analysis Services engine enforces rules on it that the
  bundled TMDL validator does not. Kairos emitted the four `calculationItem` lines and nothing
  else, so the group had zero columns; the model also never set `discourageImplicitMeasures`,
  which the engine requires before it will create any calculation group at all. Both offline
  gates reported success — `package-powerbi-release` passed and TOM/TMDL structural validation
  reported no failures — and the Fabric service then refused to create the semantic model with
  `The total number of data columns inside the calculation group table 'Time Intelligence' is 0`.
  The group now carries the `'Time Calculation'` name column and the hidden `Ordinal` column it
  sorts by, an explicit `ordinal:` on every item so they read chronologically rather than
  alphabetically, and its own partition; the model sets `discourageImplicitMeasures` and declares
  `ref table 'Time Intelligence'` whenever a calendar is approved.

### Added
- **A semantic gate on the emitted Power BI model.** `pbip_validate` never reads TMDL and
  `tmdl_validate` only proves the TMDL deserializes, which is why every defect in #619, #623 and
  #790–#794 passed both and was rejected downstream. A new `gold_assert` module runs over the
  artifacts `emit-gold` and `package-powerbi-release` are about to write and fails closed on
  engine rules the serializer cannot see — starting with calculation-group columns, sort order,
  partition and ordinals, and the model-level `discourageImplicitMeasures` coupling. This is the
  gate #623's second fix item asked for.
