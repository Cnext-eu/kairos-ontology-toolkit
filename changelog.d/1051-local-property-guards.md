### Added
- **`kairos-ontology find-term <name> --domain <d>` and the MCP tool `find_term`
  (DD-248).** The closure lookup by *name*: which properties in the domain's
  `owl:imports` closure does this name or label resemble, and on which classes. The
  same matcher the aligner and the gap sheet use. The kairos-design-domain skill now
  requires it before any property is proposed: reuse the closure property, declare
  `rdfs:subPropertyOf` with a reason, or record why no candidate fits.
- **`validate` reports two new integrity codes.**
  `integrity.local-property-resembles-reference-property` (warning): a local property
  whose name or label matches a closure property (`documentTypeCode` beside
  `documentType`) with no `rdfs:subPropertyOf` / `owl:equivalentProperty` link; the
  exact-same-name case stays with the existing shadowing warning.
  `integrity.property-outside-hub-namespace` (degradable error for a reference module's
  namespace; warning for a sibling hub domain's): a property a hub file declares under
  a namespace that is not its own. Such a term was invisible to every namespace-filtered
  check and present in the compiled graph.
- **`scaffold-extensions --force`.** A `registered-extension` property the owning
  class's closure already offers under a similar name is skipped and listed as a
  closure candidate; `--force` renders it anyway.

### Changed
- **`scaffold-extensions` mints only into a namespace the hub authors.** The namespace
  comes from the domain file's own `owl:Ontology` IRI; the `https://example.com/…`
  fallback is gone, and a `--namespace` naming a reference module or an unknown IRI is
  refused with the fix named.
- **`generate-bindings` classifies a hub-local property by the hub's namespaces**, not by
  "differs from the anchor class's module", so a property the class inherits from a
  second reference module is no longer offered as hub-authored.
- `core/hub_namespace.py` is the one reader of the hub's ontology IRIs; it replaces
  `core/ontology_scope.py` and the `scaffold-extensions` namespace heuristic.
