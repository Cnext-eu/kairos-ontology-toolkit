### Fixed
- **A relationship's "one" side now needs a declared unique key (issue #794).** Analysis Services
  enforces uniqueness on that side when it builds the relationship index — not at validation — so
  a model with a non-unique key published, refreshed green, answered any measure that stayed on
  one table, and failed on the first query whose plan traversed the relationship with
  `Column <key> in Table <fact> contains a duplicate value`. Nothing offline caught it: the
  projector checked only that the target *had* a key, and `_primary_key` never consulted a
  declared one — it walks a role priority list and then falls back to "first non-nullable column,
  else first column". On the toolkit's own `invoice` fixture that produced
  `fact_invoice_line.invoice_sk -> fact_invoice._source_system`, putting a source-system name on
  the one side. The projector now requires a declared single-column key on the target's Silver
  model, and emits the relationship inactive when there is none rather than refusing the whole
  emit — an unproven relationship is a modelling smell, not necessarily an error, and the model
  stays loadable. Every deactivation is named in the Gold product report with a `reason`, either
  `unproven-key` or `ambiguous-path`. A composite key is not evidence about a single-column
  endpoint, and an SCD2 key predicated on `is_current` counts only where the emitted table applies
  that filter. See DD-227.

  `kairos-ext:factGrain` is deliberately not used for this: it is free text, emitted only as a
  comment, and cannot be parsed. Nor is a DAX probe against the published model reliable —
  `DISTINCTCOUNT` reported no duplicates on a column a `SUMMARIZE`-based count found many of.
