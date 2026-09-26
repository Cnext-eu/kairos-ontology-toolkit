### Added
- **The toolkit now checks that ontology meaning is read from the `owl:imports` closure (DD-243).**
  A domain `.ttl` read alone is missing the classes and properties it imports. Three tests
  enforce the DD-103 contract from now on:
  - every rdflib parse in production code is inventoried with a reason
    (`docs/dev/dd103-single-file-parse-inventory.json`); a new single-file parse fails the
    suite until it goes through `load_ontology` or is listed;
  - every AI prompt call site is inventoried (`docs/dev/ai-prompt-inventory.json`); a prompt
    that lists ontology terms must render them through the new `core.prompt_context` helper,
    which reads the closure index, marks inherited properties with their origin and discloses
    any cut;
  - a managed skill that talks about the ontology names a closure-aware inspection command.
- **`SemanticIndex.carries(field)` and a `coverage` map in `slice()` metadata (#937, part).**
  They say which profile-dependent fields (`inherited_properties`, `equivalent_classes`,
  `restrictions`, `inverse_properties`, …) the index's profile populates, so an empty tuple
  can be read as "declares none" only when the profile looked.

### Notes
- The readers the audit found (`project --target report`, `coverage-report`, `validate --gdpr`,
  the reference-model shadowing check) and the prompt builders are listed as known gaps in
  the inventories and are fixed in follow-up releases.
