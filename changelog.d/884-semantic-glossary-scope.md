### Fixed
- **A glossary term now reaches the prompts where it is relevant, not only where it
  happens to share a word.** Terms were filtered to those sharing a token with the
  table's own name or columns. That is self-defeating on the schemas that need it most: a
  glossary is written in business English and a legacy schema's columns are
  abbreviations, so the two share no tokens *by construction* — which is exactly the gap
  the glossary exists to bridge. Measured on one hub, 39 of 52 authored terms never
  reached a single prompt. A concept's `rdfs:seeAlso` names the reference class the
  business's term corresponds to, so a term whose class is in the table's candidate pool
  is now relevant however it is spelled; reach went from 13 to 35 of 52 terms, and a
  cargo table from 4 to 8. The audited noise case still holds — a vessel term stays out
  of a companies-table prompt, because its class is not in that pool.
- **`anchor-tables` sees the vocabulary at all.** It decides what every table *is* and
  everything downstream inherits that, while the one input naming which class each
  business concept corresponds to was never in its prompt. The 43 concepts carrying an
  `rdfs:seeAlso` are now rendered as evidence, explicitly not as an instruction. Terms
  with no class attached are left out: they are vocabulary for naming, not evidence for
  anchoring.
