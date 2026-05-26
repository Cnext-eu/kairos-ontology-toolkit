# SCD Type-Aware dbt Silver Models

## Problem

The silver DDL projector correctly differentiates SCD Type 1 and Type 2:
- **SCD1:** No `valid_from`, `valid_to`, `is_current` columns → simple overwrite
- **SCD2:** Adds temporal tracking columns → insert new row, close prior row

However, the **dbt silver model generator** (`_gen_silver_models` in
`medallion_dbt_projector.py`) does NOT adapt its load/MERGE strategy based on
`scdType`. Both SCD1 and SCD2 classes generate identical dbt models — a plain
table materialization that always overwrites.

## Current State

| Layer | SCD1 | SCD2 | Status |
|-------|------|------|--------|
| Silver DDL (`medallion_silver_projector.py`) | No SCD columns | `valid_from`, `valid_to`, `is_current` | ✅ Correct |
| Gold DDL + views (`medallion_gold_projector.py`) | No view | `v_{table} WHERE is_current = 1` | ✅ Correct |
| Gold dbt model (gold section of `medallion_dbt_projector.py`) | No WHERE clause | `WHERE is_current = 1` | ✅ Correct |
| **Silver dbt model** (`silver_model.sql.jinja2`) | Table materialization | **Same table materialization** | ❌ Gap |

## Desired Behavior

### SCD Type 1 (overwrite)

```sql
-- materialized: incremental, unique_key = '{table}_sk'
-- Strategy: MERGE/upsert — new data overwrites existing row
{{ config(materialized='incremental', unique_key='{table}_sk') }}

SELECT
    {{ generate_sk(natural_key_cols) }} AS {table}_sk,
    ...columns...
FROM {{ source(...) }}
{% if is_incremental() %}
WHERE _loaded_at > (SELECT MAX(_loaded_at) FROM {{ this }})
{% endif %}
```

**Note:** The incremental filter column (`_loaded_at`) is a bronze-layer audit
column that indicates when data was ingested. This is a platform convention —
not a kairos-ext annotation. Every bronze table has this column by default.

### SCD Type 2 (insert + close)

```sql
-- materialized: incremental, unique_key = composite (SK + valid_from)
-- Strategy: dbt snapshot-style — detect changes, insert new row, close old
{{ config(materialized='incremental', unique_key=['{table}_sk', 'valid_from']) }}

WITH source_data AS (
    SELECT
        {{ generate_sk(natural_key_cols) }} AS {table}_sk,
        ...columns...,
        SHA2_HEX(CONCAT_WS('|', col1, col2, ...)) AS _row_hash
    FROM {{ source(...) }}
),

{% if is_incremental() %}
existing AS (
    SELECT {table}_sk, _row_hash
    FROM {{ this }}
    WHERE is_current = 1
),

changed AS (
    SELECT s.*
    FROM source_data s
    LEFT JOIN existing e ON s.{table}_sk = e.{table}_sk
    WHERE e.{table}_sk IS NULL           -- new records
       OR e._row_hash != s._row_hash     -- changed records
),

-- Close old records
closed AS (
    SELECT e.{table}_sk, e.valid_from,
           CURRENT_DATE AS valid_to,
           0 AS is_current
    FROM existing e
    INNER JOIN changed c ON e.{table}_sk = c.{table}_sk
)
{% endif %}

SELECT
    {table}_sk,
    ...columns...,
    CURRENT_DATE AS valid_from,
    NULL AS valid_to,
    1 AS is_current,
    _row_hash
FROM {% if is_incremental() %}changed{% else %}source_data{% endif %}

{% if is_incremental() %}
UNION ALL
SELECT * FROM closed
{% endif %}
```

### Key Design Points

1. **`_row_hash` computation:** The silver DDL projector adds a `_row_hash VARCHAR`
   column to all tables (audit column, S5 rule). The dbt model must **compute**
   `SHA2_HEX(CONCAT_WS('|', ...))` over the change-detection columns. The DDL
   provides the storage target; the model generates the value.

2. **Hash column selection:** The hash is computed over all business columns,
   excluding: the surrogate key (`_sk`), temporal columns (`valid_from`,
   `valid_to`, `is_current`), and `_row_hash` itself. This logic lives in the
   projector (Python), not the template.

3. **`unique_key` for SCD2:** The composite key `[{table}_sk, valid_from]`
   ensures dbt's MERGE can: (a) insert new current rows (new SK+date combo),
   and (b) update closed rows via the `UNION ALL` pattern (matching on existing
   SK+valid_from to update `valid_to` and `is_current`).

4. **Full-refresh behavior:** On first load (non-incremental), ALL source rows
   are inserted with `is_current = 1`. This is correct — the first load
   represents the baseline state. The `{% if is_incremental() %}` guard
   ensures closed-row logic only runs after initial load.

5. **Incremental filter (SCD1 only):** SCD1 models use `_loaded_at` (bronze
   audit column) to filter new records. SCD2 models do NOT need this — they
   rely on `_row_hash` comparison against existing current rows to detect
   changes, processing the full source each run.

## Implementation Plan

### 1. Pass `scd_type` and hash columns to the dbt silver template

In `_gen_silver_models()` (~line 1065), read `kairos-ext:scdType` for each
class (same pattern as `medallion_silver_projector.py:425`) and pass:
- `scd_type` (string: "1" or "2", default "1")
- `hash_columns` (list of column target_names to include in `_row_hash`)

The `hash_columns` list is derived by excluding from the full column list:
- The SK column (`{table}_sk`)
- `valid_from`, `valid_to`, `is_current`
- `_row_hash`
- Any FK columns (`*_sk` from joins — these are derived, not source data)

### 2. Extend `silver_model.sql.jinja2` with SCD2 conditional logic

Use **Option A** — single template with `{% if scd_type == "2" %}` blocks:

- Change `materialized` from `'table'` to `'incremental'` when scd_type is set
- Add `unique_key` config based on scd_type
- SCD1: `unique_key='{table}_sk'`
- SCD2: `unique_key=['{table}_sk', 'valid_from']`
- Add `_row_hash` computation in SELECT for SCD2
- Add the `existing` → `changed` → `closed` CTE chain for SCD2 incremental
- Add `UNION ALL closed` for SCD2 incremental

### 3. Handle `_row_hash` column expression

The projector must generate the hash expression:
```sql
SHA2_HEX(CONCAT_WS('|', COALESCE(CAST(col1 AS VARCHAR), ''), ...))
```

This is passed as a column entry with `target_name = '_row_hash'` and
`expression = 'SHA2_HEX(...)'`. The template renders it like any other column.

### 4. Handle temporal columns for SCD2

The projector adds three extra columns to the `columns` list for SCD2:
- `{ target_name: 'valid_from', expression: 'CURRENT_DATE' }`
- `{ target_name: 'valid_to', expression: 'NULL' }`
- `{ target_name: 'is_current', expression: '1' }`

These are overridden in the `closed` CTE (valid_to = CURRENT_DATE, is_current = 0).

### 5. Update scenario tests

Add a test class with `kairos-ext:scdType "2"` to `acme-hub` extensions and
verify the generated dbt model includes:
- `materialized='incremental'`
- `unique_key` composite
- `_row_hash` computation
- `existing`/`changed`/`closed` CTEs
- `UNION ALL` pattern

Existing SCD2 silver DDL tests in `test_scenario_silver.py:253-259` already
exercise the extension annotations — reuse the same test class.

## Files to Change

| File | Change |
|------|--------|
| `src/kairos_ontology/projections/medallion_dbt_projector.py` | Read scdType, compute hash columns, pass to template |
| `src/kairos_ontology/templates/dbt/silver_model.sql.jinja2` | Add SCD2 conditional logic (incremental + change detection) |
| `tests/scenarios/acme-hub/model/extensions/` | Add/verify SCD2 test class annotations |
| `tests/scenarios/test_scenario_dbt.py` | Assert SCD2 model output (CTEs, unique_key, hash) |

## References

- Silver projector SCD handling: `medallion_silver_projector.py:425, 496-502`
- Silver projector `_row_hash` (audit): `medallion_silver_projector.py:508`
- Gold projector SCD handling: `medallion_gold_projector.py:428-430, 837-844`
- dbt gold SCD2 filter: `medallion_dbt_projector.py:2153-2157`
- dbt silver model generation: `medallion_dbt_projector.py:1061-1075`
- Silver template: `src/kairos_ontology/templates/dbt/silver_model.sql.jinja2`
