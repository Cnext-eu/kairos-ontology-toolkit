# DD-026: Silver Layer Accuracy — Mapped-Only Columns, FK Parity, and SCD2 History Preservation

**Status:** Accepted
**Date:** 2026-05-27
**Affects:** `medallion_dbt_projector.py`, `silver_model.sql.jinja2`, `silver_source_model.sql.jinja2`, `silver_union_model.sql.jinja2`
**Implementation:** `src/kairos_ontology/projections/medallion_dbt_projector.py`, `src/kairos_ontology/templates/dbt/`

### Context

Three accuracy issues were identified in the dbt silver projector output:

1. **Unmapped columns**: All ontology properties were emitted as `CAST(NULL AS ...)` even when no source mapping existed, creating schemas with 70%+ NULL columns.
2. **FK qualification gap**: The dbt projector's `_infer_fk_targets()` only qualified properties as FKs if they were `owl:FunctionalProperty` or had `silverColumnName`. Properties with `kairos-ext:silverForeignKey true` (DD-022) were ignored — even though the silver DDL projector already handled them.
3. **SCD2 history erasure**: The SCD2 `closed` CTE set all business columns to `CAST(NULL AS VARCHAR)`, defeating the purpose of SCD Type 2 (which exists to preserve historical values).

### Decision

1. **Exclude unmapped properties**: If a property has no SKOS mapping to a bronze column and no `derivationFormula`, it is excluded from the silver model entirely. Only columns with actual data sources are emitted.
2. **Align FK qualification**: `_infer_fk_targets()` now checks `kairos-ext:silverForeignKey true` and also skips properties with `silverForeignKeyOn` (which redirect the FK to a different table), matching the silver DDL projector's logic.
3. **Preserve SCD2 history**: The `closed` CTE reads all column values from `{{ this }}` (the existing materialized table), preserving business data. Only `valid_to` and `is_current` are modified.
4. **Add `_source_system` discriminator**: Per-source union models now include a `_source_system` column for provenance tracking.

### Rationale

- **Mapped-only**: Downstream consumers (gold layer, Power BI) get honest schemas. NULL columns are never queried and create false expectations about data availability.
- **FK parity**: DD-022 introduced `silverForeignKey` as the standard annotation for FK qualification. The dbt projector must honour it to generate correct joins.
- **SCD2 preservation**: The entire purpose of SCD2 is historical analysis ("what was the status last month?"). NULLing history makes that impossible.
- **Discriminator**: When multiple sources feed a single entity, traceability requires knowing which source produced each row.

### Consequences

- Silver models will have **fewer columns** than before (only mapped ones). Downstream schemas may need regeneration.
- Properties annotated with `silverForeignKey true` will now correctly generate LEFT JOINs in dbt models.
- SCD2 incremental runs produce accurate historical records.
- Union models include `_source_system` as an additional column — gold layer transforms may need to account for it.
