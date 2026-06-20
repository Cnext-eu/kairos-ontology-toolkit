# Slice 3 — derive-claims (richer evidence aggregation)

**Status:** ✅ done · **Depends on:** 1 · **Gates:** 5

## Goal

Reduce hand-authoring by aggregating all available evidence into candidate
claims. Pure enhancement on top of the working slice-1/2 path — never blocks it.

## Scope

- **`derive-claims`** CLI — aggregate into candidate (`proposed`) claims:
  - `import-tmdl` Engineering Pack / concept-mapping dispositions,
  - `analyse-sources` affinity (table→class→domain routing),
  - `propose-alignment` column→property + disposition,
  - existing mapping analyses (SKOS / concept-mapping YAML),
  - sample-derived signals (cardinality, enums, FK shape).
- Reuse `_concurrency.py` (`--max-workers`), `_cache.py` (sidecar cache,
  `--force`), `_cost.py` (cost warning).
- **Human-confirm only** — all output is `proposed`; never auto-`approved`.

## Affected modules

`import_tmdl.py`, `analyse_sources.py`, `propose_alignment.py`, new
`derive_claims.py`, `cli/main.py`.

## Tests

- [x] aggregation merges multi-source evidence into one claim with multiple
      `evidence_sources`
- [x] all derived claims are `proposed`
- [x] cache + concurrency parity with existing AI commands

## Acceptance criteria

- [x] One command turns customer assets into a candidate claim set.
- [x] No auto-approval; evidence granularity preserved.
- [x] version + CHANGELOG + ruff + tests.

## Risks / notes

- Guard against probabilistic evidence (affinity/alignment) being treated as
  approval — concept C4. Keep strong vs weak evidence distinguishable.

## Implementation note (2026-06-15)

Slice 3 landed **`derive-claims`** (DD-EL-5): a **deterministic, AI-free** CLI
command that aggregates already-produced evidence into `proposed` candidate claims
in `model/claims/{domain}-claims.yaml`, reducing hand-authoring. The
semantically-hard LLM work already happened **upstream** in `analyse-sources`
(affinity) and `propose-alignment` (column→property, which already writes the
claims file); `derive-claims` is the deterministic merge/enrich layer that joins
**five evidence streams** — the existing claims registry, `analyse-sources`
affinity, `import-tmdl` concept-mapping, SKOS mappings, and sample-derived signals
— deterministically on `(system, table[, column])` and ref_class/ref_property
names, attaching **multiple `evidence_sources` per claim**. All derived/new claims
are `status: proposed` and are **never** auto-`approved` (the C4 guard);
human decisions survive re-runs via the existing `merge_preserving_decisions()` in
`claim_registry.py`, and conflicting evidence is surfaced rather than silently
resolved. For parity with the AI commands it reuses `_concurrency.map_concurrent`
(`--max-workers`, default 8) and the `_cache` sidecar (`--force` bypasses), but
**deliberately omits** the `_cost.print_cost_warning` cost banner because nothing
is billed. A future opt-in **`--llm-reconcile`** flag (LLM tie-breaking / rationale
synthesis, with a cost banner) is explicitly **deferred** to a later slice.
