### Changed
- **The gap gate's disposition evaluation now sees the business's own vocabulary.**
  `draft-gap-decisions --suggest` asks the model to name the concept a family of unmapped
  columns represents, and had no access to the authored glossary — so it named concepts
  from column spellings while the client's own term for the same thing sat unused in the
  same hub. The glossary now goes into that prompt with a definition per term, and a term
  that matches is treated as evidence the concept is real and in scope, favouring
  `registered-extension` over `deferred`. New `load_glossary_entries()` returns
  `(prefLabel, definition)` pairs: a label is enough to *reuse* a term, and only the
  definition is enough to *recognise* one.
