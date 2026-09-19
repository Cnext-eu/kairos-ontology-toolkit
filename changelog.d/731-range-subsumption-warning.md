### Added
- **`validate` warns when an object property's effective ranges are not a subsumption
  chain (issue #731).** Ranges are superproperty-widened: for `hasCustomer
  rdfs:subPropertyOf hasParty`, with `hasParty rdfs:range Party` and `hasCustomer
  rdfs:range Customer`, the effective ranges are `{Customer, Party}`.

  RDFS requires the object to be in **every** declared range — the intersection — which
  only makes sense if the ranges are related by `rdfs:subClassOf`. Reference models
  routinely declare a subproperty's range without asserting that chain, leaving a property
  whose effective range is `Customer ∩ Party` with nothing proving the intersection is
  inhabited by anything.

  The new `range_not_subsumption_chain` warning names the unrelated pair, says which
  property contributed the inherited range, and states the two remedies: assert the missing
  `rdfs:subClassOf`, or narrow the range.

### Notes
- Deliberately a validator warning rather than a compiler error. #729's
  relationship-endpoint check accepts a target that is, or descends from, *any* declared
  range — because intersection semantics would turn today-green hubs red on exactly this
  ontology-quality issue. The compiler's non-suppressible safety kernel is the wrong place
  to adjudicate reference-model quality; the validator is the right one.
