### Fixed (BREAKING for hubs that used table-grain `deferred`)
- **A table-grain disposition now answers for the table's columns only when it says
  something about them.** Recording any disposition against a whole table used to retire
  every one of its gap columns from the DD-169 pre-binding gate, whatever the disposition
  said. That reasoning holds for `not-business-data` (the table is not business data, so
  neither are its columns) and `blueprint-gap` (a claim about the reference model is a
  claim about what the columns needed). It does not hold for the other three, and those
  were the damaging omissions: `deferred` means "in scope, not modelled yet" — precisely
  the state the gate exists to keep raising — while `bound` and `registered-extension`
  assert the table *is* being modelled, which is when the gate matters most. On one real
  hub, 40 table-grain `deferred` records retired 1,643 columns and the gate never fired.
- **`bound` is no longer recordable as a table-grain disposition.** The DD-164 audit
  reads it from `integration/bindings/` before it consults the ledger, so authoring the
  EntityBinding is what states it; a ledger row claiming it satisfied the audit with no
  binding anywhere. Still recordable for a single column.
- `next` no longer suggests "bound to a domain" as a ledger value — it says to author the
  binding, which satisfies DD-164 on its own.

  **Upgrading:** a hub that cleared the gate with table-grain `deferred`, `bound` or
  `registered-extension` will see those columns re-enter the DD-169 gate and `compile`
  will block until each is decided. That is the omission the gate existed to catch.
  `kairos-ontology draft-gap-decisions --suggest` drafts them in bulk.
