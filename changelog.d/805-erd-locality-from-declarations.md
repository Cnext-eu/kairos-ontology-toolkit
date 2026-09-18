### Fixed
- **A domain that re-declares imported classes now produces an ERD (issue #805).**
  `project --target erd` decided which classes belonged to a domain with an IRI-prefix
  string test. `kairos-design-domain` directs authors to reuse a reference-model class
  rather than mint a local one, re-declaring the imported IRI in the domain `.ttl` to
  attach labels — such a class keeps its reference-model IRI, so it was never local, and a
  domain modelled entirely that way emitted nothing at all. On one hub that was 5 of 12
  domains, and passing the right namespace explicitly did not help. Locality is now the
  union of the namespace test and what the domain file itself declares; a class the domain
  file only *references* (a reference-model superclass, say) still stays external.
- **A projection target that produces no artifacts now says so.** Both "this domain has
  nothing to draw" and "the projector found nothing" were silent, and the CLI reported
  success either way — which is why the above went unnoticed.
