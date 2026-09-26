### Changed
- **AI prompts say what they left out (DD-244).**
  - `propose-alignment` marks inherited properties, says "… N more not listed" on a class it
    cut and ends with one line telling the model not to read absence from the list as
    absence from the reference model. Its response schema and pair check are built from the
    same cut pool, so the model can no longer answer with a property it was never shown.
    Recorded alignments are stale by contract and re-align on the next run.
  - `draft-gap-decisions` no longer asserts that a column has "no reference-model property";
    it says the aligner found no match among the properties it was shown.
  - `analyse-sources` lists a domain's own classes before imported ones and says
    "(+N more not listed)" when capped.
  - `scaffold-domain --ai` shows the model the classes its imports already provide and tells
    it to subclass rather than redeclare; the call now goes through the traced, redacting
    wrapper like every other AI call.
  - The `prompt` projection reports `truncated: true` and the omitted modules when imported
    classes are left out, and draws relationships from every declared domain.
- **`explain-term` says which fields the chosen profile does not carry (#937).** Under
  `--profile rdfs`, `inverse_properties: []` no longer reads as "declares no inverse":
  `not_carried_by_profile` names it, and `coverage` maps every profile-dependent field.
  `show-class-inventory --all` now includes each domain's slice metadata.

### Fixed
- **Glossary `rdfs:seeAlso` links written as prefixed names are read.** The regex only saw
  `<iri>` forms, so such concepts reached the alignment prompt without their reference link.
