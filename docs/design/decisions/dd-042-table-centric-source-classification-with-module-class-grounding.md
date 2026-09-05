# DD-042: Table-centric source classification with module-class grounding

**Status:** Accepted
**Date:** 2026-06-05
**Affects:** `analyse_sources.py`, `analyse-sources` CLI, `kairos-design-domain` + `kairos-design-source` skills (+ scaffold copies)
**Implementation:** `src/kairos_ontology/analyse_sources.py`

### Context

DD-041's `analyse-sources` was **domain-centric**: it looped `N_tables × N_domains`,
making one LLM call per (table, domain) pair and emitting a `domain_contributions[]`
report where a table could appear under many domains with `domain_relevance` scores.
Two problems surfaced in the logistics accelerator (22 data domains):

1. **Cost & ambiguity** — 22 calls per table, and tables ended up "belonging" to many
   domains, giving the modeler no clear primary home per table.
2. **Opaque domain semantics** — data-domain-first mode classified against the curated
   `owns`/`does_not_own` YAML text only; the actual reference-model class semantics
   (e.g. `TradeParty`, `Consignee` from `bsp/party`) never reached the LLM, even though
   the `data-domains.yaml` import URIs resolve to local module TTLs via the catalog.

### Decision

Rewrite to **table-centric, one-call-per-table** classification:

- ONE LLM call per table passes ALL candidate domains; the model returns exactly ONE
  primary `domain` + up to two `secondary_domains`. Invalid ids fall back deterministically
  to `FALLBACK_DOMAIN_IDS = ["mdm", "reference-data"]` (first present), else `unclassified`.
- Output is **table-centric** (`schema_version: 2`): a flat `tables[]` list (each with its
  primary `domain`, `domain_group`, `domain_uris`, `secondary_domains[]`) plus a
  `domain_summary[]` rollup. The affinity matrix reports per-system primary `table_count`.
- **Semantic grounding (direct modules only):** before classification, each data domain's
  `imports[].uri` is resolved via the XML catalog to its local module TTL, and that file's
  *directly declared* `owl:Class` labels are extracted (provenance-based) and capped
  (`MAX_DOMAIN_CLASSES = 18`) into a `class_summary` fed to the prompt. Resolution is done
  **once per run** with a module-path-keyed cache shared across all domains/tables/sources.

### Rationale

- One call per table is cheaper on both call-count and tokens, and yields one unambiguous
  primary domain per table — exactly what the modeling skill needs to scope context.
- `owl:imports` closure was deliberately **not** followed: the full FIBO closure is large and
  slow, and those transitive classes would never fit inside the capped prompt anyway. The
  directly-imported module classes carry the business-meaningful labels the LLM benefits from.
- Provenance-based extraction (classes asserted in the module file itself) is more reliable
  than namespace-prefix matching against import URIs, which is fragile in OWL ecosystems.

### Consequences

- **Breaking output-schema change.** Both consuming skills (`kairos-design-domain` Step 0a/0c,
  `kairos-design-source` §4c) and their scaffold copies were migrated in lockstep to read the
  table-centric schema (select tables where `domain == X` or `X ∈ secondary_domains`).
- The `threshold` parameter is retained for signature compatibility but no longer gates a
  per-table primary (one primary is always returned).
- Grounding is best-effort: unresolvable URIs or a missing catalog degrade gracefully to
  `owns`/`does_not_own` text alone. `--shallow` skips grounding entirely.
