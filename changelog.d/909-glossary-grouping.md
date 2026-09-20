### Fixed
- **`build-glossary` no longer destroys business terms that share a canonical class.**
  Concepts were grouped by `linked_iri` where one was present (DD-063), which made the
  IRI the concept's *identity* rather than a reference. A glossary exists precisely
  because many business words map onto few canonical classes, so on a real hub sixteen
  party roles — cargo broker, freight forwarder, ship owner, ship manager, charterer and
  others, each with its own authored definition — all legitimately carried the same
  `TradeParty` IRI, collapsed into one concept labelled with whichever was processed
  last, and the other fifteen were discarded without even becoming `skos:altLabel`. The
  glossary went from **164 concepts to 82 by adding the links the
  `kairos-design-discovery` skill instructs**, so the safe action and the documented
  action were opposites.

  Grouping is now always by normalized `prefLabel`, and `linked_iri` is carried as the
  cross-reference it is — several concepts pointing at one class is what `rdfs:seeAlso`
  means. Synonyms remain `altLabel`'s job, and the same term recorded in two documents
  still merges. DD-063 is amended accordingly.

  **On your next `build-glossary` run** a hub will see more concepts wherever terms had
  been silently merged, and local names derived from the label rather than the IRI
  fragment. A hand-authored glossary was never affected — only the generator collapsed
  terms.
