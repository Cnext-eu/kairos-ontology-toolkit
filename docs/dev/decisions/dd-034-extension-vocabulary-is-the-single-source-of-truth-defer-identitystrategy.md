# DD-034: Extension Vocabulary is the Single Source of Truth; Defer `identityStrategy`

**Status:** Accepted
**Date:** 2026-05-30
**Affects:** `scaffold/kairos-ext.ttl`, `medallion_dbt_projector.py`, `medallion_gold_projector.py`, CR-3, `tests/test_ext_vocabulary_coverage.py`
**Implementation:** Vocabulary declarations + FK-child warning in projectors; coverage guard test.

### Context

A consistency review (`docs/archive/extension-vocabulary-review-2026-05-30.md`) found
that several `kairos-ext:` annotations consumed by the gold projector
(`perspective`, `generateTimeIntelligence`, `olsRestricted`, and a now-reserved
`incrementalColumn`) were **never declared** in `kairos-ext.ttl`. Hub authors got no
`rdfs:comment`, no SHACL, and no IDE help for them. The review also challenged CR-3's
proposal to add a new `kairos-ext:identityStrategy` annotation for FK-child entities.

### Decision

1. **The vocabulary file is the single source of truth.** Every annotation a
   projector reads MUST be declared in `kairos-ext.ttl`. The previously-undeclared
   gold annotations are now declared; `incrementalColumn` (gold) and
   `surrogateKeyStrategy` are declared but marked **RESERVED** (read-but-not-rendered
   / declared-but-not-consumed). A guard test
   (`tests/test_ext_vocabulary_coverage.py`) greps the projectors and fails if any
   consumed `kairos-ext` annotation is undeclared.
2. **Layer-prefix naming convention.** Layer-specific annotations are prefixed
   (`silver*` / `gold*` / `bronze*`); bare names are reserved for cross-layer
   concepts. Local names are never reused across the `kairos-ext` / `kairos-bronze` /
   `kairos-map` vocabularies (the duplicate `incrementalColumn` is flagged for
   future rename).
3. **Defer `identityStrategy` (CR-3).** Implement Option 4 — an improved missing-
   `naturalKey` warning that detects FK-child context (`silverForeignKeyOn`) and
   explains the weak-entity / source-identity / embedded options — instead of adding
   new vocabulary that has no projector consumer.

### Rationale

- Discoverability and validation depend on the vocabulary being complete; a cheap
  grep-based invariant prevents silent drift.
- CR-3's "composite" case is already derivable from `silverForeignKeyOn` + a
  `naturalKey`; "embedded" has no projector that would honour it; `identityParent`
  duplicates topology already in the graph. The real pain was a confusing warning,
  which Option 4 fixes without new annotations (principle: don't ship vocabulary
  with no consumer).

### Consequences

- New `kairos-ext` annotations must be declared in `kairos-ext.ttl` or the coverage
  test fails — a deliberate speed-bump that keeps the vocabulary authoritative.
- RESERVED annotations remain declared (documented) but inert until wired up;
  `kairos-ext:incrementalColumn` (gold) is a render-or-remove decision left open.
- `identityStrategy` / `identityParent` are deferred; revisit only if improved
  warnings prove insufficient. See CR-3 Resolution (2026-05-30).
- Full conceptual reference for hub authors lives in
  `docs/dev/dd-034-extension-explanation.md`.
