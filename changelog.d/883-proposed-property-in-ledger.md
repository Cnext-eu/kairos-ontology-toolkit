### Added
- **A `registered-extension` decision now records *which* property it commits to.** The
  hub-local property `propose-alignment` drafts for an unmappable column — its name,
  range, owning class and rationale — reached the disposition ledger only as a sentence
  inside `rationale`, so the one stage that could act on it would have had to parse
  English. Ledger entries now carry a structured `proposed_property` alongside the prose.
  Where the aligner read one column name two different ways across tables, neither draft
  is recorded: the reviewer was asked to pick, and guessing on their behalf is the
  failure this avoids.
