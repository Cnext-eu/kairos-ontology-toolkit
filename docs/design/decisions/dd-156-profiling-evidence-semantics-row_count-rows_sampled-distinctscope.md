# DD-156: Profiling evidence semantics: row_count, rows_sampled, distinctScope

**Status:** Accepted
**Date:** 2026-08-15
**Affects:** `import-flatfile`, `extract-schema`, `import-source`, vocabulary enrichment; schema YAML v1.2; `kairos-bronze` vocabulary
**Implementation:** `src/kairos_ontology/core/import_flatfile.py`, `core/extract_schema.py`, `core/import_source.py` (`normalize_profiling_evidence`, `_distinct_scope`, `_sync_managed_profiling_predicates`), `core/enrich_vocabulary.py`, `scaffold/kairos-bronze.ttl`

### Context

`row_count` meant two different things depending on which importer produced it (#422). The
warehouse path (`extract-schema`) recorded full-table `COUNT(*)` and full-table
`COUNT(DISTINCT)` — true population facts. The flatfile path (`import-flatfile`) recorded
the number of rows read into a capped profiling window (default 1,000) under the **same
field name**, with `distinct_count` counted within that window. Every downstream consumer
that thresholds on `row_count` or trusts `distinctCount` (enum suggestion, FK cardinality
matching, and — via #424 — `suggest-shapes` `sh:in` enums) therefore treated window-local
observations as population truth. The dogfooding hub shipped provably wrong `sh:in` enums
derived from 5-row samples. As DD-089 already put it for a sibling artifact: **source
samples are not equivalent to full production data** — the fields must say which one they
carry.

### Decision

One meaning per field, from schema YAML **v1.2** onward:

| Field (YAML) | Predicate (RDF) | Meaning |
|---|---|---|
| `row_count` | `kairos-bronze:rowCount` | TRUE table cardinality, always. **Omitted when unknown** — never a window size, never a defaulted `0`. |
| `rows_sampled` | `kairos-bronze:rowsSampled` | Rows read into the profiling window. Always present on flatfile-read tables; absent on warehouse extraction (profiling there is full-table). |
| — | `kairos-bronze:distinctScope` | `"table"` or `"sample"`: whether distinct/sample evidence covers the full relation. RDF-only, derived at emission. |

Producer rules:

- **CSV/XLSX**: cap-hit is detected structurally — the read loop's `break` fires only when a
  row *beyond* the cap exists, so natural exhaustion (even at exactly `max_rows` rows) is a
  full read with a true count. Full read → `row_count = rows_sampled`. Capped →
  `row_count` omitted, `rows_sampled = max_rows`. openpyxl "ghost" rows (formatting-only
  trailing rows) can make a boundary-sized sheet look capped; the cost is a conservative
  `row_count` omission, never a false count.
- **Parquet**: `row_count` from `ParquetFile.metadata.num_rows` — free, true, and covering
  all row groups (this also fixed a latent undercount where only the first batch of a
  multi-row-group file was reported). `rows_sampled` = the single batch actually read.
- **Warehouse (`extract-schema`)**: unchanged semantics (already true cardinality); writes
  v1.2 and no `rows_sampled`.

**Scope derivation (H2 guard):** `distinctScope = "table"` iff `row_count` is known AND
(`rows_sampled` is absent OR `rows_sampled == row_count`); `"sample"` otherwise; when BOTH
fields are absent the predicate is **omitted** — zero evidence must never be asserted as
`"table"`. Absence therefore reads as legacy/unknown, which consumers must treat as
untrusted (#424 consumes exactly this contract).

**Legacy normalization (H3 allowlist):** v1.0/1.1 YAML is reinterpreted at a single choke
point (`normalize_profiling_evidence`, after parse, before enrichment). Trust is decided by
platform **allowlist** — only the values `extract-schema` actually emits
(`fabric-warehouse`, `fabric-lakehouse`, `databricks`, `snowflake`, `postgres`) keep
`row_count`; `flatfile`, `unknown`, or a missing platform mean the legacy `row_count` was a
window size and it becomes `rows_sampled`. Unknown provenance is never promoted to truth.

**Merge-managed predicates (H1):** `rowCount`/`rowsSampled`/`distinctScope` are
introspection-owned and replaced on merge (`merge_with_existing`), like
`dataType`/`nullable`/`sampleValues`. Without this, re-running `import-source` over an
existing monolithic TTL would keep the legacy window-sized `rowCount` forever while the
per-table files carried fresh v1.2 semantics — two contradicting claims in one combined
graph, and the "regenerate to migrate" advisory would be false.

### Accepted advisory losses on capped flatfiles (H4)

- **Enum suggestions**: `detect_enums` now requires exhaustive evidence (`row_count` known
  and window covering it) before the existing min-rows/threshold/ratio gates run. Capped
  flatfile tables produce no `suggestedEnum` — a windowed distinct count proves value
  concentration in the window, not that the enumeration is complete.
- **FK cardinality matching**: `infer_foreign_keys` treats an unknown `row_count` as 0,
  which disables cardinality-based (medium-confidence) FK matching for capped flatfile
  tables. Accepted: the signal is advisory-only, and matching against a window size would
  manufacture false positives. Name-based (high-confidence) matching is unaffected.

Both losses restore honesty rather than remove capability: the suggestions they suppress
were exactly the ones the old semantics fabricated.

### Consequences

- Schema YAML v1.2 joins `SUPPORTED_VERSIONS`; flatfile manifests write `version: "1.2"`.
- Migration is regeneration: re-running `import-flatfile` + `import-source` updates the
  managed predicates in place (H1). Untouched legacy TTLs keep their old `rowCount` but
  carry no `distinctScope`, so v1.2-aware consumers treat them as untrusted.
- `column-coverage-audit` display renders an unknown denominator as `distinct=N/?`.
- DD-050 and DD-039 amended; DD-076's "distinctCount is the reliability signal" is
  falsified for windowed evidence and is addressed by #424 (suggest-shapes reads
  `distinctScope` — see DD-076's 2026-08-15 amendment).
