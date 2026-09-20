### Changed
- **`relationship.unrealized-technical-field` no longer points at a command that may have
  nothing to offer.** The remedy read "Run `kairos-ontology propose-relationships` to
  derive the entry, or keep the carrier deliberately if the parent is not bound yet",
  which is true only when an object property links the two bound classes and a join key
  matches. Measured on two hubs, that is often not the case: of nine warnings on one, five
  named bindings that appear as a child in no proposal at all, and the single genuine hit
  rendered a `<CONFIRM_PROPERTY>` choice rather than a pasteable entry. The causes the
  command cannot resolve are structural — no object property exists between the two bound
  classes, the carrier is polymorphic and can never be one relationship, or the property
  is declared container-to-contained so the key sits on the parent — and none is fixed by
  running it again. The message now says what the command does derive, what it only
  reports, and that keeping the carrier is the right answer in those cases.
