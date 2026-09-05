# DD-095: derive-claims deterministic multi-source evidence aggregation

**Status:** Accepted

**Date:** 2026-07-21

**Affects:** `model/claims/{domain}-claims.yaml`,
`src/kairos_ontology/core/derive_claims.py`, `derive-claims` CLI command,
`claim_registry.merge_preserving_decisions`, `_concurrency.py` / `_cache.py`,
evidence-led design skills (`kairos-design-source`, `kairos-execute-project`)

**Implementation:** Deterministic evidence aggregator on top of DD-094.
Canonicalized from the archived evidence-led decision log
(`docs/archive/evidence-led-modeling/decision-log.md` §DD-EL-5); see also
`docs/archive/evidence-led-modeling/slice-3-derive-claims.md`.

### Context

With the Claim Registry (DD-094) as the governance authority, authoring candidate
claims is still largely manual: the evidence needed to propose them is scattered
across already-produced artifacts (`analyse-sources` affinity, `propose-alignment`
column→property output, `import-tmdl` concept-mapping dispositions, SKOS mapping
TTL, sample-derived signals, and committed Core Concepts Conformance outcomes).
The semantically hard interpretation already happened upstream; what is missing is
a single deterministic step that joins those evidence streams into a richer
candidate set for human curation.

### Decision

Add a **`derive-claims`** CLI command: a **deterministic, AI-free** aggregator that
merges/enriches the Claim Registry with additional deterministic evidence streams
and attaches **multiple `evidence_sources` per claim**. It joins six streams on
`(system, table[, column])` and ref_class/ref_property names: (1) the existing
claims registry, (2) `analyse-sources` affinity, (3) `import-tmdl` concept-mapping,
(4) SKOS mappings, (5) sample-derived enum/FK signals, and (6) validated Core
Concepts Conformance outcomes using DD-090's proposed-only policy. **C4 guard —
all derived/new claims are `status: proposed`, never auto-`approved`.** Human
decisions survive re-runs via `merge_preserving_decisions()`; conflicting evidence
is surfaced (low-confidence proposed claims / rationale notes), never silently
resolved. It reuses `_concurrency.map_concurrent` (`--max-workers`) and the
`_cache` sidecar (`--force`, including conformance in the input digest), and is
skill-managed (soft skill-gate; `KAIROS_SKILL_CONTEXT=1` silences the warning).

### Rationale

The hard interpretation already happened upstream, so this step is pure
deterministic plumbing: a reproducible join with no model variance and no token
spend. Keeping it AI-free makes re-runs free, fast, and diffable, and preserves the
strong (anchored) vs weak (affinity-only) evidence distinction. No cost banner is
printed because nothing is billed — printing one here would train users to ignore
the banner where it actually matters (the paid AI commands).

### Consequences

- One command turns already-produced customer assets into a richer candidate claim
  set, reducing hand-authoring before human curation/approval.
- No claim is ever auto-approved; the `check-claims` approval gate is unchanged.
- Evidence granularity is preserved: each claim may carry multiple
  `evidence_sources`.
- Conformance evidence records tier, outcome, rename, and deviation traceability;
  optional-tier concepts are not filtered out, while `not-applicable` creates no
  candidate.
- A future opt-in `--llm-reconcile` (LLM tie-breaking / rationale synthesis, with a
  cost banner) is explicitly deferred.
