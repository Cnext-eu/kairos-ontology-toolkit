### Fixed
- **An imported class the hub only relates is no longer shown as a hub concept.** Binding a
  shipped list takes an axiom such as `unece:TransportModeCodeList rdfs:subClassOf
  :TransportModeCode`, which names the imported class as a subject in the hub file. The
  concept guide, the ubiquitous language and the domain ERD counted every such subject as
  declared by the hub. The guide listed the class as `hub-local` under a minted
  `<domain>:` name, and the ERD drew it as a local class with every inherited attribute.
  A subject now counts only when the file states something about it other than
  `rdfs:subClassOf`, `owl:equivalentClass` or `owl:disjointWith`, such as a type or a label.
  A reference class the file re-declares with a label still counts (#805), and the concept
  guide now shows it under its own prefix (for example `iso4217:CurrencyCode`), not the
  domain's.

  Regenerate the DDD and ERD projections after upgrading. A hub class whose local name
  collided with such an imported class loses the domain suffix the collision forced on its
  ubiquitous-language IRI: `terms:CurrencyCode_reference_data` becomes `terms:CurrencyCode`.
- **`validate` no longer reports an import as unused when the hub uses it through its
  terms.** The check compared each term's namespace with the `owl:imports` IRI, but a
  module's IRI need not be its terms' namespace:
  `https://www.kairosflow.ai/ont/uncefact/code-lists` declares
  `https://vocabulary.uncefact.org/TransportModeCodeList`. An import now also counts as
  used when the file names a term that the module's document declares, read from the
  resolved import closure.
