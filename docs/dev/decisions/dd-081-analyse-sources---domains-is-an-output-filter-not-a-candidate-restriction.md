# DD-081: `analyse-sources --domains` is an output filter, not a candidate restriction

**Status:** Accepted
**Date:** 2026-06-20
**Affects:** `src/kairos_ontology/analyse_sources.py`, `cli/main.py`
(`analyse-sources`), `kairos-design-source` skill
**Implementation:** `run_analyse_sources` (remove candidate prune; add
`_filter_analysis_by_domain` post-classification); issue #189

### Context

`--domains` pruned the LLM **candidate** domain set *before* classification. Because
each source table is classified in a single call against all candidates and must pick
one primary domain, restricting candidates to e.g. `party` forced every table into
`party` or `unclassified`. This produced false modeling evidence (cargo/vessel/route
tables labelled `party`) and inflated downstream `check-claims --domains party` counts.

### Decision

Treat `--domains` as a **post-classification output focus**:

- Always classify every table against the **full** accelerator/reference domain set so
  each table gets its true primary domain.
- After classification, write only the tables whose **primary** domain matches
  `--domains` (substring match), in each per-system `*-affinity.yaml` and the matrix.
  Secondary domains are deliberately ignored, matching downstream coverage bucketing
  (`alignment_coverage.load_affinity_domain_tables`, which keys on primary `domain`).
- A system with zero matching tables writes an empty (`schema_version: 2`, `tables: []`)
  report instead of raising.
- `--max-domains` still truncates the candidate set (rate-limit guard) but now emits a
  warning that classification may be biased; it is unsuitable for modeling evidence.

### Consequences

- Fixes the evidence pollution at the source; no change needed in `check-claims` /
  coverage (they already bucket by primary domain).
- The per-table cache key includes the candidate signature, so switching between
  filtered and unfiltered runs does not reuse stale (candidate-pruned) classifications.
- Behaviour change: scripts relying on the old exclusive-candidate semantics now get
  full-set classification with a focused output (the correct evidence).
