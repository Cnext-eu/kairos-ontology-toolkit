### Changed
- **`draft-gap-decisions --suggest` now characterises the single names too, not only the
  families.** It read `sheet["families"]` and nothing else, and families are formed by
  shared name tokens — so a column whose name shares no token with another was a
  singleton forever and no model call ever considered it. On one real hub that was the
  overwhelming majority: 7 families covering 64 of 357 distinct names, and 293 singletons
  left with a deterministic reasoning line and no proposal. Those are also the harder
  ones, since token grouping had already solved the easy case. Only names with no
  rule-based proposal are sent, so a deterministic answer is never second-guessed; the
  aligner's drafted property is offered as evidence where one exists; large lists are
  batched rather than truncated; and an empty disposition remains a valid answer, because
  "this is an opaque legacy abbreviation" beats a guess. As with families, it fills
  `proposed_disposition` and `reasoning` and never `decision`.
