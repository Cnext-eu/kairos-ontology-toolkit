# SCD Type-Aware dbt Silver Models

## Problem

The silver DDL projector correctly differentiates SCD Type 1 and Type 2:
- **SCD1:** No `valid_from`, `valid_to`, `is_current` columns → simple overwrite
- **SCD2:** Adds temporal tracking columns → insert new row, close prior row

However, the **dbt silver model generator** (`_gen_silver_models` in
`medallion_dbt_projector.py`) does NOT adapt its load/MERGE strategy based on
`scdType`. Both SCD1 and SCD2 classes generate identical dbt models — a plain
incremental upsert that overwrites in place.

## Current State

| Layer | SCD1 | SCD2 | Status |
|-------|------|------|--------|
| Silver DDL (`medallion_silver_projector.py`) | No SCD columns | `valid_from`, `valid_to`, `is_current` | ✅ Correct |
| Gold DDL + views (`medallion_gold_projector.py`) | No view | `v_{table} WHERE is_current = 1` | ✅ Correct |
| Gold dbt model (gold section of `medallion_dbt_projector.py`) | No WHERE clause | `WHERE is_current = 1` | ✅ Correct |
| **Silver dbt model** (`silver_model.sql.jinja2`) | Upsert | **Same upsert** | ❌ Gap |

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
WHERE {incremental_column} > (SELECT MAX({incremental_column}) FROM {{ this }})
{% endif %}
```

### SCD Type 2 (insert + close)

```sql
-- materialized: incremental, unique_key = composite (SK + valid_from)
-- Strategy: dbt snapshot-style — detect changes, insert new row, close old
{{ config(materialized='incremental', unique_key=['{table}_sk', 'valid_from']) }}

WITH source_data AS (
    SELECT
        {{ generate_sk(natural_key_cols) }} AS {table}_sk,
        ...columns...,
        {{ row_hash(change_columns) }} AS _row_hash
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

## Implementation Plan

### 1. Pass `scd_type` to the dbt silver template

In `_gen_silver_models()`, read `kairos-ext:scdType` for each class and pass
it to `template.render(scd_type=...)`.

### 2. Create a second template (or conditional block)

Option A: Single `silver_model.sql.jinja2` with `{% if scd_type == "2" %}` blocks
Option B: Separate `silver_model_scd2.sql.jinja2` template

Recommendation: **Option A** — keeps it in one file, the conditional logic
is localized to the incremental strategy section.

### 3. Handle the `_row_hash` column

`_row_hash` is already generated in silver DDL (S5 rule). The dbt model needs to:
- Compute `SHA2_HEX(CONCAT_WS('|', col1, col2, ...))` for change detection
- Compare against existing `_row_hash` to detect actual changes

### 4. Handle `valid_from` / `valid_to` / `is_current`

- New/changed rows: `valid_from = CURRENT_DATE`, `valid_to = NULL`, `is_current = 1`
- Closed rows: `valid_to = CURRENT_DATE`, `is_current = 0`
- The `unique_key` for incremental must be composite: `[sk, valid_from]`

### 5. Update scenario tests

Add a test case with `kairos-ext:scdType "2"` and verify the generated dbt
model includes the SCD2 logic (close + insert pattern).

## Files to Change

| File | Change |
|------|--------|
| `src/kairos_ontology/projections/medallion_dbt_projector.py` | Read scdType, pass to template |
| `src/kairos_ontology/templates/dbt/silver_model.sql.jinja2` | Add SCD2 conditional logic |
| `tests/scenarios/acme-hub/model/extensions/` | Add SCD2 test class |
| `tests/scenarios/test_scenario_dbt.py` | Assert SCD2 model output |

## References

- Silver projector SCD handling: `medallion_silver_projector.py:425, 496-502`
- Gold projector SCD handling: `medallion_gold_projector.py:428-430, 837`
- dbt gold SCD2 filter: `medallion_dbt_projector.py:2155-2157`
- `_row_hash` column (S5): `medallion_silver_projector.py:508`
