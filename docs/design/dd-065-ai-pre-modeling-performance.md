# DD-065: Concurrent, Cached AI Pre-Modeling (`analyse-sources` + `propose-alignment`)

| Field | Value |
|-------|-------|
| **Status** | Accepted |
| **Date** | 2026-06-14 |
| **Scope** | `analyse-sources` (affinity) and `propose-alignment` CLI commands |
| **Impact** | Run time, AI spend, new CLI flags, two new internal helper modules |

> **Implementation:** `src/kairos_ontology/_concurrency.py`,
> `src/kairos_ontology/_cache.py`, `src/kairos_ontology/_cost.py`,
> `src/kairos_ontology/analyse_sources.py`,
> `src/kairos_ontology/propose_alignment.py`, `src/kairos_ontology/cli/main.py`.
> Tests: `tests/test_perf_optimizations.py`, plus concurrency/caching cases in
> `tests/test_analyse_sources.py` and `tests/test_propose_alignment.py`.

---

## Context

Two pre-modeling steps narrow the modeling surface so a modeler never has to load
an entire client schema or an entire reference-model TTL at once:

1. **`analyse-sources`** classifies every source table to the domain(s) it most
   contributes to (the *affinity* reports), so each domain works against only its
   relevant tables.
2. **`propose-alignment`** aligns the columns of those tables to reference-model
   class properties, so modeling drills into the right properties of both source
   and reference models.

Both are **table-centric**: exactly one LLM call per source table. Both ran the
loop **strictly serially**, one blocking call at a time, and `propose-alignment`
additionally issued a **conditional second full-inventory retry** per weak table.

On a real field hub (`cldn-ontology-hub`: **546 source tables**, captured in
`changerequest.md`), this produced ~1090 back-to-back calls and **~45–65 minutes**
of wall time, dominated entirely by serial network latency — the per-call work is
cheap, but nothing overlapped. Re-runs re-billed and re-waited for every table even
when only one domain (or one table) had changed.

Three concrete inefficiencies were code-verified:

- `run_propose_alignment` / `analyse_source_system` looped serially with no
  concurrency.
- `align_table` **blanked** an invalid model-returned `ref_class` to `""` instead
  of falling back to the affinity `likely_entity`, and the prompt only passed
  `likely_entity` as a soft hint — so the model paid to re-derive a class that
  `analyse-sources` had already determined.
- The freshness hash `affinity_sha256` (DD-061) was already computed and written
  but never used to **skip** unchanged work.

## Decision

Apply a symmetric performance treatment to **both** commands while preserving the
`schema_version: 2` output contract exactly (no YAML schema change — a hard
constraint, because `check-alignment` / `check-source-coverage` parse these files).

### 1. Concurrency (CR-1)

A shared `map_concurrent(fn, items, *, max_workers, ordered=True)` helper
(`_concurrency.py`) wraps a bounded `ThreadPoolExecutor`. Per-table workers run
concurrently; results are collected in **input order** and the deterministic
`TableAlignment` / `TableAssignment` objects are built on the main thread, so the
output YAML stays diff-stable. Each worker isolates its own exceptions so a single
table failure cannot abort the pool. A single thread-safe OpenAI/Azure client is
reused across workers.

New `--max-workers` flag (default **8**) on both commands. `--max-workers 1`
reproduces the original serial path exactly (escape hatch for low-TPM Azure
deployments).

`call_with_backoff(fn, *, retries, base_delay)` adds exponential back-off on
HTTP 429 / rate-limit errors (provider-agnostic detection), so higher worker counts
degrade gracefully instead of failing.

### 2. Affinity-anchored class selection (CR-2)

`propose-alignment` uses the affinity `likely_entity` to **anchor** the prompt: when
`likely_entity` matches a candidate class, STEP 1 asks the model to *confirm* it
(overriding only if clearly wrong) rather than re-derive from scratch; otherwise it
is passed as a hint. When the model returns an invalid/empty `ref_class`,
`align_table` now **falls back** to `likely_entity` instead of blanking it.

### 3. Two-level incremental caching (CR-5 + per-table)

- **Domain-level skip** reuses the existing `affinity_sha256`: if a domain's
  alignment file is already fresh against the affinity set, the whole domain is
  skipped with zero LLM calls.
- **Per-table sidecar cache** (`_cache.py`) handles the large-domain case where one
  changed table would otherwise flip the domain hash and re-run hundreds of
  unchanged tables. A JSON sidecar at `<analysis-dir>/.cache/<command>.json` maps a
  stable SHA-256 input hash → the previously computed result payload. The key
  covers everything that affects the answer (system, table, columns + types +
  samples, model, candidate/shortlist signature, `likely_entity`, retry
  thresholds). The cache lives **outside** the output YAML, so the schema contract
  is untouched.

`--force` bypasses **both** cache layers.

### 4. Retry retuning (CR-3 Option B)

The full-inventory retry already required **both** low confidence **and** low
mapped-ratio. Only the defaults are retuned to fire less often:
`--retry-min-confidence` 0.75→0.6, `--retry-min-mapped-ratio` 0.55→0.4, removing
most redundant 2× calls on large reference models.

### 5. Prompt slimming (CR-4)

`--max-prompt-classes` default 18→12. Gated on the scenario tests — acme-hub matched
counts must not regress.

### 6. Cost banner

Because concurrency now fans out many paid calls quickly, both commands print a
prominent, hard-to-miss cost banner on stderr **before any LLM call**
(`_cost.py: print_cost_warning`). It states this is a COSTLY operation, shows the
scale up front (table count × ≥1 call each, up to `--max-workers` in parallel),
strongly recommends a cost/value-optimized model (**`gpt-5.4-mini`**, the default),
and notes the cost-savers (caching skips unchanged work; `--force` re-spends;
`--max-workers 1` for the slow/cheap serial path). Suppressed by `--quiet`.

## Rationale

- The bottleneck was **serial latency**, not token cost or CPU; bounded concurrency
  is the highest-leverage, lowest-risk fix and collapses ~1 h to a few minutes.
- Anchoring on `likely_entity` reuses the affinity result we already paid for, both
  speeding up and stabilizing class selection.
- Two cache levels cover both the "one domain changed" and "one table in a huge
  domain changed" cases without touching the output schema that downstream gates
  depend on.
- Keeping `--max-workers 1` as an exact reproduction of the old path makes the
  change safe to adopt incrementally and easy to debug.

## Consequences

- **New CLI surface:** `--max-workers` and `--force` on both commands; changed
  `propose-alignment` defaults (`--max-prompt-classes`, `--retry-min-confidence`,
  `--retry-min-mapped-ratio`).
- **New `.cache/` directory** under the analysis dir. It is regenerable and should
  be git-ignored by hubs; deleting it only forces a recompute.
- **Cost visibility:** users now see an explicit spend warning every run (unless
  `--quiet`), nudging them toward `gpt-5.4-mini`.
- Three new internal helper modules (`_concurrency`, `_cache`, `_cost`) are now
  shared infrastructure available to future LLM-powered commands.
- Output contract (`schema_version: 2`, `affinity_sha256`, `reference_rollup`,
  `tables[].columns` / `custom_columns`, DD-045 hints) is unchanged;
  `check-alignment` / `check-source-coverage` semantics are untouched.

## Related decisions

- **DD-061** — the `affinity_sha256` freshness hash reused for domain-level skip and
  the coverage gates whose contract this DD preserves.
- **DD-045** — mapping hints carried through unchanged in the alignment output.
- **DD-032** — reference-model alignment, the workflow `propose-alignment` serves.

## Deferred

- **CR-6** batch tiny tables into one prompt — only if concurrency + caching don't
  hit the target.
- **CR-3 Option A** column-scoped retry (re-map only uncertain columns with the
  class pinned) — stretch goal behind the CR-2 anchor.
