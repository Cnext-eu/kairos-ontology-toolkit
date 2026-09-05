# DD-065: Concurrent, Cached AI Pre-Modeling (`analyse-sources` + `propose-alignment`)

**Status:** Accepted
**Date:** 2026-06-14
**Affects:** `analyse-sources` + `propose-alignment` CLI commands, `kairos-design-source`
+ `kairos-design-domain` skills, `kairos-help` CLI listing
**Implementation:** `src/kairos_ontology/_concurrency.py`, `src/kairos_ontology/_cache.py`,
`src/kairos_ontology/_cost.py`, `src/kairos_ontology/analyse_sources.py`,
`src/kairos_ontology/propose_alignment.py`, `src/kairos_ontology/cli/main.py`

The two LLM-powered pre-modeling steps issued one **blocking** LLM call per source
table, strictly serially. On a large hub (546 tables) this ran ~45–65 min. This DD
parallelizes both commands (bounded `ThreadPoolExecutor`, `--max-workers` default 8,
deterministic input-order YAML), adds two-level incremental caching (domain-level
skip via the existing `affinity_sha256` + a schema-neutral per-table sidecar under
`<analysis-dir>/.cache/`), anchors alignment class selection on the affinity
`likely_entity`, retunes the full-inventory retry gate, slims prompts, and prints a
prominent cost banner recommending `gpt-5.4-mini`. `--force` bypasses both cache
layers; `--max-workers 1` reproduces the original serial path.

**Full ADR:** see the companion file
[`dd-065-ai-pre-modeling-performance.md`](../dd-065-ai-pre-modeling-performance.md).
