### Fixed
- **A property one hop away in the import closure is named, not denied (issue #853).** A
  binding field targeting a property declared on another class reported:

  ```
  property 'imo:flagStateCountryCode' does not resolve in the ontology
  ```

  It does resolve. The compiler indexes the whole `owl:imports` closure (DD-103), so the
  property was sitting one hop away on a class a binding could target directly (DD-144).
  The message sent authors hunting for a typo, a missing prefix or a missing import, when
  the answer is "that property belongs to another class — bind it and link the two".

  Both halves of the same mistake now say so, and name the route:

  ```
  property 'acc:partyName' does not resolve against any class in this compile, but it
  exists in the import closure: it is declared on class 'acc:TradeParty', not on the
  bound class. Bind that class in its own EntityBinding -- an imported class needs no
  local rdfs:subClassOf to be bindable (DD-144) -- and reach it from here with a
  relationships: entry, or carry the raw value with technicalFields: (DD-139).
  ```

- **`binding.property-domain-incompatible` names the class that *does* declare the
  property**, not only the one that does not. Which of the two diagnostics an author gets
  depends on whether something else in the compile happened to pull the property's class
  into scope — invisible to them and irrelevant to their mistake — so both now carry the
  same guidance.

### Notes
- **Nothing changes about which bindings compile.** Both cases failed before and fail now;
  only the messages moved. A genuinely unknown token — a typo, an undeclared prefix — still
  reports as unknown with the usable-token list, which is the honest answer there.
- Split out of #811, and it **replaces that issue's "wall 2"**. #811 reported this as a
  reachability asymmetry — range-class scalars supposedly usable only when the hub declares
  a local subclass of the range. Measured both ways, neither shape makes the property
  usable from the parent binding, and the companion-binding route works with no local
  subclass at all. The defect underneath was always the diagnostic.
- The owning class is named with the token an author would type rather than a bare IRI: a
  resolved class carries both refs, and sorting between them was picking by first
  character.
