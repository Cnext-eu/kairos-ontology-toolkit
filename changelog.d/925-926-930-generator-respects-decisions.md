### Fixed
- **A table you disposition out no longer keeps shipping to Silver.** `generate-bindings`
  already skipped a table the ledger ruled out, but the binding written for it before the
  ruling stayed on disk — and `compile` reads the directory, so the table still compiled
  and still emitted a Silver model, with no warning anywhere. Measured on one hub: a
  generic application-settings table, recorded `not-business-data`, emitting a Silver
  model. `generate-bindings` now retracts that binding and says so; a dry run reports the
  retraction without performing it. `validate` gained
  `disposition.bound-and-ruled-out`, which catches the same contradiction whatever wrote
  the file — previously a bound table returned before the ledger was ever read, so the
  conflict counted as "bound" and passed silently.
- **`scaffold-extensions` no longer renders properties for tables that are out of scope.**
  It walked every anchored table in the domain with no disposition filter. On one hub, two
  ruled-out tables contributed three properties whose `rdfs:domain` pointed at a namespace
  the domain does not import, so `validate` failed an import rule on the strength of
  tables the operator had already removed — and deleting the properties by hand did not
  stick, because the next render produced them again.
- **`generate-bindings --force` no longer destroys an authored `relationships:` block.**
  `propose-relationships` writes nothing, so accepting a proposal means hand-editing a
  generated file — and `--force` is the documented way to pick up a corrected anchor. The
  two collided: regenerating any table in a domain silently discarded every relationship
  authored anywhere in it, and nothing failed afterwards, because a missing relationship
  only downgrades an error to the `relationship.unrealized-technical-field` warning. The
  block is now carried across, counted in the per-row output, and re-validated against the
  regenerated document.

### Changed
- **`generate-bindings` prints why each table was skipped.** Every skip already carried a
  written reason and the summary printed only the count, so a table vanishing between
  `anchor-tables` and `compile` could not be explained without reading the report object
  in a Python shell.
- **A table dropped because anchoring and alignment disagree now says so.** When every
  column the aligner matched sits on a class the anchor is not, the skip reason names the
  anchor, names the class alignment chose, and gives the two available decisions. It
  previously reported "no scalar fields mapped for this table (relationship wiring is
  deferred to propose-relationships)" — which sent one operator after
  `propose-relationships` for a sixty-column party and goods table that had nothing to do
  with relationships.
