# DD-068: Custom-column triage in domain modeling (issue #164)

**Status:** Accepted
**Date:** 2026-06-14
**Affects:** `propose_alignment.py`, `alignment_coverage.py`, `cli/main.py`
(`check-alignment`), `.github/skills/kairos-design-domain/SKILL.md` (+ scaffold copy)
**Implementation:** `disposition` field on `custom_columns`;
`collect_custom_columns` + `CustomColumn` + `check-alignment --strict`

### Context

When modeling a domain under the Reference Model Enforced strategy, the
`kairos-design-domain` workflow could finalize a domain that reused reference
classes but **silently dropped source-evidenced columns with no reference-model
property** (e.g. `credit_limit`, `currency`, `payment_iban_code`, billing address,
`eori_number`, lifecycle flags). The signal already existed in
`{domain}-alignment.yaml` (`custom_columns:` per table;
`reference_rollup[].custom_extensions_count`) but was never surfaced in a checkpoint,
and nothing forced these columns to be triaged before COMPLETED. The gap only
surfaced later, during `kairos-design-mapping`, as unmappable columns (issue #164).

### Decision

Make custom-column triage **explicit and deterministically verifiable**, without a
new artifact:

1. **Persist a `disposition` field** on each `custom_columns` entry in the existing
   `{domain}-alignment.yaml` (`model` / `silver-passthrough` / `skip`; `null` until
   triaged). `propose-alignment` writes it `null`; the modeling skill fills it.
2. **`check-alignment` surfaces + classifies custom columns** — high-priority
   (business / has `suggested_property`) shown first, likely-operational/audit
   (ETL/surrogate heuristics) listed separately. Identity is `system.table.column`;
   the inflated per-class `custom_extensions_count` is **not** used as a threshold.
3. **`--strict` blocks on *undisposed* custom columns** (not mere presence). Default
   warns; `--warn-only` overrides `--strict` (exit 0). Wired into the skill's
   domain-COMPLETED checkpoint.
4. **Skill** ties it together: every `custom_columns` entry must appear as a
   `❌ Custom` row (Step 0c.4), a mandatory Custom Column Triage table records a
   disposition back into the YAML (Checkpoint 3b), and the completion gate runs
   `check-alignment --strict`. The "Reference Model Enforced" wording is clarified
   (class-hierarchy reuse is enforced, but source-evidenced columns still warrant
   local extension properties; zero-local-property is a special case).

### Rationale

A warn-only report plus skill-only guidance was rejected (rubber-duck review): with
no persisted state a gate can only *count*, never verify triage, leaving the same
silent-drop hole. A **separate disposition file** was also rejected as
over-engineered — annotating the existing alignment YAML is not a new artifact and is
the lightest mechanism that makes `--strict` a real gate. Classifying rather than
threshold-filtering keeps genuine business columns visible without arbitrary cutoffs.

### Consequences

- Re-running `propose-alignment` regenerates the YAML and resets dispositions
  (consistent with the existing freshness model — regeneration implies the source set
  changed and triage should be revisited).
- `--strict` requires every custom column (including audit columns) to carry a
  disposition; operational columns can be bulk-set to `skip`. Nothing is silently
  dropped.
- Deferred: cross-checking `model` dispositions against produced TTL properties; a
  `coverage-report` mode for custom columns; CI hard-enforcement.
