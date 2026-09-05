# DD-077: Custom-column triage hardening (issue #182)

**Status:** Accepted
**Date:** 2026-06-14
**Affects:** `propose-alignment` generation + `check-alignment` gate; custom-column
triage at Checkpoint 3b of `kairos-design-domain`
**Implementation:** `src/kairos_ontology/propose_alignment.py`,
`src/kairos_ontology/alignment_coverage.py`, `src/kairos_ontology/_cost.py`,
`src/kairos_ontology/ai_provider.py`, `src/kairos_ontology/cli/main.py`

### Context

Real-world modeling of the CLdN `consignment` and `booking` domains (≈200 and ≈350
custom columns) exposed reproducible, deterministic weaknesses in the
`propose-alignment` → Checkpoint-3b workflow:

1. **Confident-but-wrong fallbacks.** The prompt instructed the model to invent a
   camelCase `ref_property` for *every* unmatched column, so dozens of unrelated
   columns collapsed onto one plausible-looking sink (`stageCode`, `customsID`).
2. **No auto-disposition.** ~40% of columns have a mechanical disposition (audit →
   `skip`; generic vendor slots like `CFSTRING33` → `silver-passthrough`) yet all
   started undisposed, forcing a column-by-column manual grind.
3. **Rollup coverage > 100%.** Matched properties weren't validated against the
   class's real property set, so a class could report 121% coverage (23 matched vs
   19 real props) — an AI-hallucination signal presented as healthy.
4. **Hallucinated anchor classes.** A `Booking` class anchoring 14 tables / 236
   custom columns existed in *no* reference model (real DCSA classes are only
   `BookingRequest` / `ConfirmedBooking`); nothing re-validated an already-written
   alignment against the real class set. Building triage on fictional anchors yields
   a Gate-6-violating model.

The issue mandates **no new AI cost** — every fix is deterministic or
confidence-gated, reusing the existing per-table LLM call.

### Decision

Ship a dependency-ordered set of workstreams (rubber-duck-reviewed):

- **WS0** — emit an explicit `algorithm_version`, fold it (plus
  `custom_confidence_floor` and model id) into the per-table and domain cache keys,
  and fix the latent freshness-hash bug (written as `source_sha256`, read as
  `affinity_sha256`), so the hardened behaviour is never masked by stale cache.
- **WS-NORM** — one canonical discriminator (`alignment == "custom"`). An unmatched
  column is `alignment: custom` + `ref_property: null` + `suggested_property: null`;
  no orthogonal `match` field.
- **WS1** — confidence-gate `suggested_property` (`--custom-confidence-floor`,
  default 0.5) and downgrade any catch-all property proposed for ≥3 dissimilar
  columns.
- **WS2** — two-tier disposition: advisory `recommended_disposition` always written;
  final `disposition` auto-filled (`disposition_source: heuristic`) **only** for
  narrow audit/technical columns. Generic vendor slots are *recommended*
  `silver-passthrough` but stay undisposed unless `--accept-heuristics`.
- **WS4** — validate matched props against the real ref-model set, cap coverage at
  100%, and surface a `hallucinated_properties` sample.
- **WS6** — record a non-clean `ref_class_status` + `rejected_ref_class` at
  generation; add a decoupled `check-alignment --check-anchors` gate that
  re-validates anchors against the real installed class set.
- **WS7** — prompt emits `ref_property: null` for unmatched, allows `ref_class:
  null`, and is steered away from catch-all sinks / >100% over-mapping.
- **WS8** — opt-in `--high-accuracy` model preset for the accuracy-sensitive
  anchoring step (mini stays default). Adds **per-role LLM endpoints**: `affinity`
  (analyse-sources) and `alignment` (propose-alignment) can each use their own
  endpoint/key/model via `KAIROS_AI_{ROLE}_ENDPOINT|KEY|MODEL`, falling back to the
  global provider when unset.
- **WS9** — preserve human-owned dispositions/notes by `(system, table, column)` on
  regeneration; only heuristic-owned fields are recomputed, so `--force` never wipes
  a hand-triaged file.

### Rationale

- A wrong specific guess is worse than a null — it must be individually disproved,
  so low-confidence and catch-all suggestions are dropped rather than emitted.
- Two-tier disposition prevents silently auto-modeling/-skipping real business
  columns: only near-zero-ambiguity audit columns auto-resolve.
- Keeping hallucination signals **visible** (rollup samples, anchor status) rather
  than silently clamping lets the modeler see and correct AI errors.
- Deterministic post-hoc anchor validation is decoupled from the CLI (core takes a
  `valid_ref_classes` set) to avoid a `cli → core` import cycle.

### Consequences

- Alignment YAMLs gain `algorithm_version`; files from an older version are flagged
  stale/unverifiable by `check-alignment`.
- `check-alignment` gains `--check-anchors` (anchor validation) and
  `--accept-heuristics` (treat recommended vendor-slot passthrough as disposed);
  `--strict` keeps meaning only custom-column disposition strictness.
- Cross-domain candidate tagging (WS3) and a non-LLM repair path for existing large
  YAMLs were scoped here but **deferred to follow-up issues** to avoid introducing a
  new class of wrong-domain noise and to keep this change focused.
