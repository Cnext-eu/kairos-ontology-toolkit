# Kairos Ontology Toolkit — Improvement Specification v2

> **Purpose:** Revised improvement specification based on analysis of v2.16.0 codebase
> and the original `TOOLKIT_IMPROVEMENT_SPEC 1.md`. This version incorporates design
> decisions specific to our deployment target (Microsoft Fabric) and corrects findings
> that were partially inaccurate based on actual code inspection.
>
> **Scope:** The toolkit's dbt projection engine (medallion_dbt_projector.py) and
> supporting vocabulary schemas (kairos-bronze.ttl, kairos-ext.ttl, kairos-map.ttl).

---

## Summary of Original Findings vs Actual Code

The original spec identified 18 findings. Code analysis reveals a more nuanced picture:

| Finding | Original Claim | Actual Code State | Revised Assessment |
|---------|---------------|-------------------|-------------------|
| **F1** | Silver refs non-existent `stg_<domain>__<entity>` | Silver correctly builds `class_to_staging` and refs `stg_{source}__{table}` when mappings exist. **But**: falls back to non-existent model when no mapping exists, and `_extract_silver_columns` emits `CAST(NULL AS STRING)` for SK/IRI. | **Partially valid** — the disconnect exists only for unmapped classes and the SK/transform logic is incomplete |
| **F2** | No physical storage awareness | Confirmed — no JSON/denorm handling | **Valid** |
| **F3** | JSON schemas not describable | Confirmed — no JSON vocabulary | **Valid** |
| **F4** | Hardcoded types | Confirmed — `_SOURCE_TO_SPARK` and `_XSD_TO_SPARK` emit Spark SQL types (STRING, BOOLEAN) | **Valid** — critical for Fabric which needs VARCHAR, BIT |
| **F5** | Vocabulary from API docs, not bronze reality | Process concern — valid but lower priority | **Valid but deferred** |
| **F6** | Discriminators not modeled | Confirmed | **Valid** |
| **F7** | Enums not modeled | Confirmed | **Valid** |
| **F8** | No population requirement tags | Confirmed — no required/optional/derived annotation | **Valid** |
| **F9** | No coverage reports | Confirmed | **Valid** |
| **F10–F18** | Various quality gaps | Confirmed | **Valid, lower priority** |

### Key Correction

The original spec's most dramatic claim — "100% of silver models reference non-existent
staging tables" — is **overstated**. The current code *does* correctly wire silver to
source-aligned staging when mapping TTL exists. The actual issues are:

1. Unmapped classes get a broken fallback reference
2. `_extract_silver_columns` doesn't fully apply transforms (SK is always NULL)
3. Types are Spark SQL, not Fabric-compatible

---

## Design Decisions

### Decision 1: SQL Dialect Handling — dbt Adapter + Generated Fabric SQL

**Choice**: Generate Fabric Warehouse-compatible SQL directly. Do NOT build a
multi-platform abstraction layer.

**Rationale**:
- Our target is exclusively Microsoft Fabric Warehouse
- dbt-fabric adapter handles most dialect differences (materialization, schema creation)
- Type mapping is the one thing the adapter does NOT handle for us — we must emit correct
  types in our CAST expressions and column definitions
- Building platform profiles for 7 engines (as the original spec suggests) is over-engineering
  for our use case
- If multi-platform is needed later, we can introduce a `target_platform` config parameter
  and swap type dictionaries — but not now

**What this means for the projector**:
- Replace `_SOURCE_TO_SPARK` → `_SOURCE_TO_FABRIC` (VARCHAR, BIT, DATETIME2, etc.)
- Replace `_XSD_TO_SPARK` → `_XSD_TO_FABRIC`
- Use `TRY_CAST` (Fabric-supported) for safe type conversion in silver
- Use `OPENJSON` + `CROSS APPLY` for JSON extraction (Fabric-supported)

### Decision 2: Layer Architecture — Silver References Source-Staging Directly

**Choice**: Option B from the original spec — silver models reference
`stg_{source}__{table}` directly and apply mapping transforms inline.

**Rejected**: Option A (generate intermediate `stg_<domain>__<entity>` bridge models).

**Rationale**:
- Option A creates an extra layer of models that adds complexity without clear benefit
- The mapping transforms (filter, rename, type cast) fit naturally in a single silver SELECT
- When multiple sources feed one entity, silver uses UNION ALL across staging CTEs
  (already partially implemented in the current `source_ctes` pattern)
- Fewer dbt models = faster `dbt run`, simpler DAG, easier debugging
- The silver template already supports multiple CTEs + joins — we just need to use it fully

**What this means for the projector**:
- Silver model generation applies `kairos-map:filterCondition` as WHERE clauses
- Silver model generation applies `kairos-map:transform` as SELECT expressions
- Multi-source entities get UNION ALL pattern
- No intermediate `stg_<domain>__<entity>` models generated

### Decision 3: Naming Convention — Keep "Staging" (Not "Bronze")

**Choice**: Keep dbt model prefix as `stg_` and folder as `models/staging/`.

**Rationale**:
- In medallion architecture, "bronze" = the **raw ingested data** in the lakehouse
- "Staging" = the **first dbt transformation layer** that reads FROM bronze
- They are semantically different: bronze is raw, staging applies basic cleaning/typing
- dbt community convention uses `stg_` universally
- The `integration/sources/` folder already describes what's IN bronze
- Renaming would break all existing hub repos and contradict dbt best practices

**Mapping**:
```
Fabric Lakehouse tables  = "Bronze" (raw data, loaded by Data Factory)
dbt models/staging/      = "Staging" (cleaned, typed, renamed — reads from bronze)
dbt models/silver/       = "Silver" (domain-aligned, transformed)
dbt models/gold/         = "Gold" (star schema, aggregated)
```

### Decision 4: Physical Storage Annotations — Minimal Scope

**Choice**: Only model two physical storage types: `"table"` (default/implicit) and
`"json-column"` (for columns Data Factory leaves as raw JSON strings).

**Rejected**: Full spec proposal with `inline`, `json-array`, `json-object`, `parentTable`.

**Rationale**:
- Our ingestion path is: API → Data Factory → Fabric Lakehouse
- Data Factory typically flattens most JSON into tabular columns
- The only case we need to handle is: columns that remain as JSON strings after ingestion
- For those columns, we need OPENJSON extraction in staging
- The `inline` pattern (denormalized columns) doesn't apply when DF handles flattening
- If needed later, we extend the vocabulary — but don't build what we don't use

**What this means for the vocabulary**:
```turtle
# Only needed for JSON columns that DF doesn't flatten:
kairos-bronze:contentType    — "json-array" | "json-object" | absent (= scalar)
kairos-bronze:jsonSchema     — links to field definitions for extraction
```

### Decision 5: Population Requirements — Extend kairos-ext (Not New Ontology)

**Choice**: Add `populationRequirement` and related properties to the existing
`kairos-ext.ttl` vocabulary, not a new `kairos-ont.ttl`.

**Rationale**:
- `kairos-ext.ttl` already contains layer-specific annotations (goldTableType, scdType, etc.)
- Population requirements are a projection concern, not a core ontology concern
- Keeping all projection annotations in one namespace simplifies discovery
- The original spec proposed `kairos-ont:` namespace but this creates unnecessary fragmentation

---

## Implementation Plan

### Phase 1: Fix Layer Contracts + Apply Mapping Transforms

**Priority**: P0 — Blocks everything
**Goal**: Silver models are functional, reference correct staging, apply transforms.

| # | Task | File(s) |
|---|------|---------|
| 1.1 | Remove broken fallback in silver generation (line ~525) — when no mapping exists, skip model or emit clear warning | `medallion_dbt_projector.py` |
| 1.2 | Fix `_extract_silver_columns` to generate real SK (using `dbt_utils.generate_surrogate_key`) and IRI construction | `medallion_dbt_projector.py` |
| 1.3 | Ensure silver applies `filterCondition` from mapping as WHERE clause on CTE | `medallion_dbt_projector.py`, `silver_model.sql.jinja2` |
| 1.4 | Ensure silver applies all `transform` expressions (not just first match) | `medallion_dbt_projector.py` |
| 1.5 | Add `kairos-ext:populationRequirement` property (required/optional/derived/unmapped) | `kairos-ext.ttl` |
| 1.6 | Add `kairos-ext:naturalKey` property for SK generation | `kairos-ext.ttl` |
| 1.7 | Add generation-time validation: warn if required property has no mapping | `medallion_dbt_projector.py` |
| 1.8 | Generate coverage report JSON alongside dbt models | New: `coverage_reporter.py` |

**Acceptance criteria**:
- Silver models reference only existing staging models
- All mapped properties use transform expressions (no NULL placeholders for mapped columns)
- SK columns use surrogate key generation based on natural key
- Coverage report shows mapped/unmapped/required-missing counts

### Phase 2: Fix Type System for Fabric

**Priority**: P0 — Generated SQL won't run without this
**Goal**: All CAST expressions and type references use Fabric Warehouse-compatible types.

| # | Task | File(s) |
|---|------|---------|
| 2.1 | Replace `_SOURCE_TO_SPARK` with `_SOURCE_TO_FABRIC` dict | `medallion_dbt_projector.py` |
| 2.2 | Replace `_XSD_TO_SPARK` with `_XSD_TO_FABRIC` dict | `medallion_dbt_projector.py` |
| 2.3 | Use `TRY_CAST` instead of `CAST` in silver for type safety | `medallion_dbt_projector.py` |
| 2.4 | Update silver projector DDL types if needed | `medallion_silver_projector.py` |
| 2.5 | Add `target_platform` parameter (default "fabric") for future extensibility | `medallion_dbt_projector.py` |

**Acceptance criteria**:
- No `STRING`, `BOOLEAN`, `TIMESTAMP` in generated dbt models
- All types are valid Fabric Warehouse types (VARCHAR, BIT, DATETIME2, etc.)
- `dbt run` on Fabric does not fail due to type errors

### Phase 3: JSON Column Handling

**Priority**: P1 — Needed for sources with non-flattened JSON
**Goal**: Columns containing JSON strings are properly extracted in staging.

| # | Task | File(s) |
|---|------|---------|
| 3.1 | Add `kairos-bronze:contentType` property to vocabulary | `kairos-bronze.ttl` |
| 3.2 | Add `kairos-bronze:JsonSchema` class and field properties | `kairos-bronze.ttl` |
| 3.3 | Detect JSON columns during staging generation | `medallion_dbt_projector.py` |
| 3.4 | Generate `CROSS APPLY OPENJSON(...)` pattern for json-array columns | `medallion_dbt_projector.py` |
| 3.5 | Add JSON validation guards (ISJSON check) | `medallion_dbt_projector.py` |
| 3.6 | Extract all JSON fields as VARCHAR (safety rule) | `medallion_dbt_projector.py` |
| 3.7 | Generate `TRY_CAST` in silver for JSON-extracted fields | `medallion_dbt_projector.py` |
| 3.8 | Update staging template with json_extractions block | `staging_model.sql.jinja2` |

**Acceptance criteria**:
- JSON columns generate OPENJSON extraction in staging
- All extracted values are VARCHAR (type casting in silver only)
- Invalid JSON rows are filtered, not errored

### Phase 4: Vocabulary Enrichment

**Priority**: P2 — Improves output quality
**Goal**: Discriminators and enums are modeled and auto-generate correct SQL.

| # | Task | File(s) |
|---|------|---------|
| 4.1 | Add `kairos-bronze:discriminatorColumn` and value annotations | `kairos-bronze.ttl` |
| 4.2 | Add `kairos-bronze:Enumeration` class and enum value annotations | `kairos-bronze.ttl` |
| 4.3 | Generate semantic discriminator-based WHERE clauses | `medallion_dbt_projector.py` |
| 4.4 | Generate CASE statements for enum-typed columns in silver | `medallion_dbt_projector.py` |
| 4.5 | Optionally generate dbt seed CSV for large enums (>10 values) | `medallion_dbt_projector.py` |

**Acceptance criteria**:
- Discriminator-based filtering uses vocabulary values (not hardcoded literals in mappings)
- Enum columns produce human-readable labels in silver
- Large enums generate seed files + JOIN pattern instead of inline CASE

### Phase 5: Quality of Life

**Priority**: P3 — Polish
**Goal**: Validation tooling, test generation, SCD2, incremental, lineage.

| # | Task | File(s) |
|---|------|---------|
| 5.1 | New CLI: `kairos-ontology validate-vocabulary` | New: `cli/validate_vocabulary.py` |
| 5.2 | Generate dbt schema.yml tests from vocabulary constraints | `medallion_dbt_projector.py` |
| 5.3 | Generate incremental materialization when `incrementalColumn` is set | `medallion_dbt_projector.py` |
| 5.4 | Generate dbt snapshot config for SCD Type 2 entities | `medallion_dbt_projector.py` |
| 5.5 | Generate column-level lineage in schema.yml descriptions | `medallion_dbt_projector.py` |
| 5.6 | Generate reusable Jinja macros (dedup, audit columns, GDPR masking) | New: `templates/dbt/macros/` |

---

## What We Are NOT Doing (Explicit Exclusions)

| Excluded | Reason |
|----------|--------|
| Multi-platform profiles (7 engines) | Only targeting Fabric; dbt adapter handles rest |
| Intermediate `stg_<domain>__<entity>` bridge layer | Over-engineering; silver handles transforms directly |
| `inline` / `json-object` physical storage types | Data Factory flattens these; not needed |
| `kairos-ont:` new namespace | Using existing `kairos-ext:` instead |
| Renaming staging to bronze | Incorrect semantics; breaks dbt convention |
| GDPR satellite isolation (Finding 13) | Deferred to Phase 5 as optional enhancement |
| Full sample data validation pipeline | Deferred; manual vocabulary QA sufficient for now |

---

## Backward Compatibility

All changes are **additive**:
- New annotations are optional — hubs without them generate output as before
- Type mapping change (Spark → Fabric) is the one breaking change, but current output
  doesn't run anyway (wrong types), so this is a fix, not a regression
- Existing `kairos-ext:scdType`, `kairos-ext:goldTableType` etc. remain unchanged
- Silver model improvements only activate when mapping TTL provides the data

---

## Test Strategy

Each phase requires:
1. Unit tests for new/modified projector functions
2. Integration test: sample ontology + bronze vocab + mapping → generated dbt models
3. Validation that generated SQL is syntactically correct for Fabric
4. Regression test: existing test fixtures produce same or better output
