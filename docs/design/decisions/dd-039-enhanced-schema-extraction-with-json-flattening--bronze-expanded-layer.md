# DD-039: Enhanced Schema Extraction with JSON Flattening & Bronze Expanded Layer

**Status:** ~~Superseded by [DD-106](dd-106-immutable-bronze-and-mandatory-logical-source-preparation.md)~~
**Date:** 2026-06-02
**Affects:** `extract-schema` CLI command, `import_source.py`, `kairos-develop-dataplatform` skill, dataplatform staging models, dbt projector
**Implementation:** `src/kairos_ontology/extract_schema.py`, `src/kairos_ontology/generate_staging.py`, `scaffold/dataplatform/`, `medallion_dbt_projector.py`

### Context

DD-035 introduced a basic introspection pipeline (dbt macro → YAML → import-source).
However, the current macro only captures column names and data types. Real-world bronze
tables (especially in Fabric Warehouse) contain JSON-encoded columns (`varchar(max)`)
with nested structures that need:

1. **Detection** — identify which columns contain JSON
2. **Classification** — determine structure (flat, nested, array, polymorphic)
3. **Flattening** — pre-process JSON into typed columnar tables before silver
4. **Vocabulary enrichment** — generate accurate bronze vocabulary with JSON-derived properties

Parsing JSON directly in silver models is expensive on analytical engines (re-evaluates
`JSON_VALUE`/`OPENJSON` on every query) and violates DRY when multiple models need
the same fields.

### Decision

1. **New `extract-schema` CLI command** replaces dbt macro as primary extraction path.
   Uses Python database drivers (pyodbc for Fabric) to:
   - Query INFORMATION_SCHEMA for full column metadata (nullable, precision, etc.)
   - Sample 5 rows per table for format detection and JSON inference
   - Classify JSON columns (flat/nested/array_object/array_primitive/polymorphic)
   - Output **one YAML per table** in `extracted/<system>/` directory:
     - `_manifest.yaml` — system-level metadata (platform, connection, extracted_at)
     - `<table_name>.yaml` — columns, samples, JSON structure per table
   - Enables incremental re-extraction and clean git diffs

2. **Bronze expanded staging layer** for JSON handling:
   ```
   bronze (raw) → bronze_expanded (JSON flattened) → silver (ontology-generated)
   ```
   - Flat JSON → expanded columns as a `view`
   - Array of objects → `CROSS APPLY OPENJSON` as child `table` with FK
   - Polymorphic → left in bronze, flagged for manual review
   - Auto-generated from `extract-schema` output via `--generate-staging`

3. **Schema YAML v1.1** extends v1.0 with:
   - `row_count`, `distinct_count`, `nullable`, `samples` (5 values)
   - `json_detected`, `json_classification`, `json_structure` (keys + types)
   - Backward compatible: v1.0 YAML (no samples/JSON) still valid

4. **`import-source` extended** to handle v1.1:
   - `flat` → expanded datatype properties on parent class
   - `nested`/`array_object` → linked class with own properties
   - `polymorphic` → `xsd:string` + review flag annotation
   - Samples stored in `kairos-bronze:sampleValues`

5. **Vocabulary enrichment** (`--enrich`, default ON for v1.1):
   - **Enum detection**: `distinct_count ≤ 25 && row_count ≥ 100 && ratio < 0.1`
     → `kairos-bronze:suggestedEnum`, `kairos-bronze:enumValues`
   - **Format detection**: regex on samples → `kairos-bronze:formatHint`
     (uuid, email, date, url, phone, numeric_code)
   - **FK inference**: column naming patterns (`*_id`, `*Id`, `*_key`) + table name matching
     → `kairos-bronze:suggestedForeignKey` + `kairos-bronze:fkConfidence`
   - **Comment enrichment**: top 3 samples in `rdfs:comment`
   - **Row count**: `kairos-bronze:rowCount` on SourceTable
   - All annotations are *suggestions* — design-source skill uses them interactively

6. **Platform-generic design** — driver abstraction:
   - Fabric Warehouse/Lakehouse (pyodbc + Azure CLI/SPN token)
   - Databricks (databricks-sql-connector + PAT or Azure CLI token)
   - Future: Snowflake, PostgreSQL

### Rationale

- **Performance**: flattening once in bronze_expanded avoids repeated JSON parsing in
  silver; materialized tables enable statistics and predicate pushdown
- **Testability**: typed columns in staging models can have dbt tests (not_null, unique)
- **Automation**: JSON structure metadata enables auto-generation of staging models
- **Reuse**: same YAML serves both dataplatform (`_sources.yml` update) and
  ontology-hub (vocabulary import) — single extraction, two consumers
- **5 samples** balances metadata richness vs extraction speed and YAML size

### Consequences

- New optional dependency: `pyodbc` (via `kairos-ontology-toolkit[fabric]` extra)
- Two extraction paths coexist: dbt macro (lightweight, SQL-only) and CLI (rich, Python)
- Bronze_expanded layer adds maintenance for JSON-heavy sources, but is optional
- **Silver source routing:** `kairos-ext:silverSourceRef` annotation on a class makes the
  dbt projector emit `{{ ref('stg_...') }}` instead of `{{ source() }}`. This is opt-in
  via the silver extension file — absent annotation = backward-compatible `source()` behavior.
- JSON classification heuristic (5 samples) may misclassify rare polymorphic columns;
  user review step mitigates this
- Flat JSON staging views are row-preserving (no WHERE filter on NULL JSON) so that
  switching to `ref()` never drops rows silently

### Amendment (2026-08-15): schema YAML v1.2 splits cardinality from window (#422, DD-156)

The v1.1 fields above gave `row_count` two meanings — full-table `COUNT(*)` on
the warehouse extraction path, capped-read window size on the flatfile path.
Schema YAML **v1.2** splits them: `row_count` = true table cardinality only
(omitted when unknown), new `rows_sampled` = profiling-window size, and
`kairos-bronze:rowCount` is emitted only for real cardinality (with new
`kairos-bronze:rowsSampled` / `kairos-bronze:distinctScope` carrying the window
evidence). The enum-detection rule in item 5 now additionally requires the
evidence to be exhaustive (`distinctScope = table`). See DD-156.
