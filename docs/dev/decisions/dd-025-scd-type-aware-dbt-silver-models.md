# DD-025: SCD Type-Aware dbt Silver Models

**Status:** ~~Superseded by [DD-109](dd-109-temporal-execution-canonical-hashing-and-fk-resolution.md)~~
**Date:** 2026-05-26
**Affects:** `medallion_dbt_projector.py`, `silver_model.sql.jinja2`, silver dbt output
**Implementation:** `src/kairos_ontology/projections/medallion_dbt_projector.py`, `src/kairos_ontology/templates/dbt/silver_model.sql.jinja2`

### Context

The silver DDL projector (`medallion_silver_projector.py`) correctly differentiates SCD
Type 1 and Type 2 — adding `valid_from`, `valid_to`, `is_current`, and `_row_hash`
columns for SCD2 classes. The gold projector and gold dbt model also handle SCD2 correctly
(filtering `WHERE is_current = 1`).

However, the dbt silver model generator (`_gen_silver_models`) does not read
`kairos-ext:scdType` and produces the same plain table materialization for both SCD1 and
SCD2. This means:
- SCD2 silver tables have the correct DDL schema but no change-detection or temporal-tracking logic in the dbt pipeline
- The silver model overwrites data rather than inserting new versions and closing prior rows

### Decision

Extend the silver dbt model generator to produce SCD-type-aware incremental models:

1. **SCD1 (default):** `materialized='incremental'` with `unique_key='{table}_sk'`.
   Simple upsert — new data overwrites existing rows. Filtered by `_loaded_at` for
   incremental runs.

2. **SCD2:** `materialized='incremental'` with `unique_key=['{table}_sk', 'valid_from']`.
   Change-detection via `_row_hash` comparison. New/changed rows inserted with
   `is_current = 1`; prior versions closed with `valid_to = CURRENT_DATE, is_current = 0`.

Implementation uses a **single template** (`silver_model.sql.jinja2`) with conditional
blocks (`{% if scd_type == "2" %}`), keeping the logic localized and avoiding template
proliferation.

The projector computes `hash_columns` (all business columns excluding SK, temporal, and
derived FK columns) and passes them to the template for `_row_hash` generation.

### Rationale

| Approach | Pros | Cons |
|----------|------|------|
| Keep plain table (current) | Simple | SCD2 schema mismatch; no temporal tracking |
| **Incremental with SCD-aware logic (this)** | Matches DDL; end-to-end SCD2 | More complex template |
| dbt snapshots | Native SCD2 support | Different materialization; doesn't align with silver schema |
| Separate SCD2 template file | Clean separation | Maintenance of two templates; most logic is shared |

The single-template incremental approach was chosen because:
- It aligns the dbt pipeline with the DDL projector's output (schema consistency)
- It uses standard dbt incremental patterns (no custom materializations)
- The conditional logic is localized to the incremental strategy section
- It keeps all silver model logic in one discoverable file

### Consequences

- SCD2 classes will generate incremental models with change detection and temporal tracking
- The silver template grows in complexity but remains a single file
- `_row_hash` is computed in the model SQL, not stored from source (source doesn't have it)
- Full refresh produces all rows with `is_current = 1` (correct baseline behavior)
- SCD1 classes change from `table` to `incremental` materialization (performance improvement)
- Scenario tests must be added for SCD2 dbt model generation

The long-form design document for this decision was removed: DD-025 is superseded by [DD-109](dd-109-temporal-execution-canonical-hashing-and-fk-resolution.md), which is the current record.
