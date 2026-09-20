### Added
- **Generated artifacts record which business glossary they were grounded in, and a
  changed glossary is reported.** `*-alignment.yaml` already fingerprinted its affinity
  input and its resolved import closure so either going stale was visible; the glossary
  was the one input nothing recorded — and it is the one a human maintains between runs,
  so it is the one most likely to move underneath an artifact built from it.
  `table-anchors.yaml` and `*-alignment.yaml` now carry `glossary_sha256`, digested over
  the `(prefLabel, definition)` pairs that actually reach a prompt, so adding a term or
  correcting a definition is drift while reformatting the Turtle is not. A literal
  `"none"` records a run that had no glossary in scope — the `--without-discovery`
  escape, previously visible only on the terminal that produced it.
  `kairos-ontology next` reports artifacts grounded in an older vocabulary.
- **The autopilot has a second Stage 0 pre-flight: business discovery.** It stops on a
  missing glossary, on DD-233 findings, and on glossary drift, and may never pass
  `--without-discovery` — that flag is a deliberate human escape. A run that proceeded
  without business discovery carries **BLOCKED** in its transparency report, for the same
  reason a skipped LLM judgment step does.
