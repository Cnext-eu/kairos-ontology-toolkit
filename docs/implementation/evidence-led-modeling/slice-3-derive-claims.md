# Slice 3 — derive-claims (richer evidence aggregation)

**Status:** ⬜ not started · **Depends on:** 1 · **Gates:** 5

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

- [ ] aggregation merges multi-source evidence into one claim with multiple
      `evidence_sources`
- [ ] all derived claims are `proposed`
- [ ] cache + concurrency parity with existing AI commands

## Acceptance criteria

- [ ] One command turns customer assets into a candidate claim set.
- [ ] No auto-approval; evidence granularity preserved.
- [ ] version + CHANGELOG + ruff + tests.

## Risks / notes

- Guard against probabilistic evidence (affinity/alignment) being treated as
  approval — concept C4. Keep strong vs weak evidence distinguishable.
