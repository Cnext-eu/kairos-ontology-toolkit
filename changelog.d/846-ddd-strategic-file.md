### Added
- **One hub-wide strategic DDD file, `model/extensions/ddd-contexts-ext.ttl` (DD-229, #846).**
  Bounded contexts and the context map are declared once for the whole hub and referenced by
  IRI from the per-domain `{domain}-ddd-ext.ttl` overlays, which now carry tactical design only.
  `validate --ddd` validates the strategic file on its own, merges it into every overlay's
  validation graph, and adds a hub-wide consistency audit that per-domain SHACL could not do:
  `ddd.context-redeclared` (warning), `ddd.context-label-conflict`, `ddd.class-in-two-contexts`
  and `ddd.tactical-in-strategic-file` (errors). A hub that still declares its contexts inside
  each overlay validates as before and is told what to move.
- **`kairos-ddd` vocabulary 1.1.0.** `kairos-ddd:subdomainType` classifies a context as
  `CoreDomain`, `SupportingSubdomain` or `GenericSubdomain`; `kairos-ddd:invariant` records an
  aggregate's business rules as repeatable prose beside its class. Overlays may also carry
  `skos:scopeNote`, `skos:example` and `skos:altLabel` on class and property IRIs — the
  context-specific language, which never redefines the canonical `rdfs:label`/`rdfs:comment`.
- **Four new overlay shapes.** A `boundedContext` value must be a declared context (a typo used
  to render as a new unlabelled box); an element belongs to at most one context;
  `subdomainType` is closed; a context relationship joins two different contexts.

### Fixed
- **`validate --ddd` no longer parses an overlay into the ontology loader's cached graph.**
  `build_merged_graph` merged the overlay into the graph object `load_ontology` memoizes per
  path, so every overlay validated earlier in the process became part of the next one's
  merged graph — and of the domain graph the rest of `validate` then read. Symptoms were
  order-dependent: an `AggregateMember` without a root passed because an earlier overlay's
  `aggregateRoot` triple was still there. The domain graph is now copied before merging.

### Changed
- **`project --target ddd` per-domain reports show the contexts a domain participates in**, with
  their subdomain type, the edges touching them, and a new `## Invariants` section, instead of
  whatever the one overlay happened to declare. The hub-wide map follows in DD-230.
