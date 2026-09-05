# DD-014: Eliminate Staging — Silver Reads Bronze Directly

**Status:** ~~Superseded by [DD-106](dd-106-immutable-bronze-and-mandatory-logical-source-preparation.md)~~
**Date:** 2026-05-14
**Affects:** `medallion_dbt_projector.py`, dbt templates, generated project structure
**Implementation:** `_gen_silver_models()` uses `{{ source() }}`, `_gen_staging_models()` removed from pipeline
**Supersedes:** DD-003, DD-004, DD-005

### Context

The original dbt projector generated a **staging layer** (`stg_*` models) between
bronze sources and silver entity models. Staging performed rename + type cast as
materialized views, and silver then referenced staging via `{{ ref('stg_...') }}`.

This created several issues:
1. **Redundant layer** — the rename/cast logic is simple enough to inline in silver
2. **Confusing ownership** — staging models were dbt-managed but conceptually part
   of the source-system world, blurring the platform ↔ dbt boundary
3. **Double materialization** — views still have execution cost in some platforms
4. **Maintenance burden** — two template families (Fabric + Databricks staging)

### Decision

**Remove the staging layer entirely.** Silver is the first dbt layer and reads
directly from bronze tables via `{{ source('system', 'table') }}`.

| Before | After |
|--------|-------|
| Bronze → `stg_*` (view) → Silver (table) → Gold | Bronze → Silver (table) → Gold |
| `models/staging/{source}/stg_{source}__{table}.sql` | ❌ Removed |
| `_sources.yml` with full column detail | Minimal `_sources.yml` (table refs only) |
| Silver uses `{{ ref('stg_...') }}` | Silver uses `{{ source('...', '...') }}` |

### What Silver Absorbs

Silver models now handle all transform logic inline:
- Column renaming (bronze name → domain snake_case name)
- Type casting via `TRY_CAST` (using original bronze column names)
- Transform expressions from SKOS mappings (applied directly)
- Multi-source UNION/JOIN from multiple bronze tables

### Generated Project Structure

```
models/
├── silver/
│   ├── _sources.yml         # Minimal: database + schema + table only
│   └── {domain}/
│       ├── {entity}.sql     # Reads from {{ source() }}
│       └── _models.yml      # Schema + tests
└── gold/
    └── {domain}/
        ├── dim_{entity}.sql
        └── fact_{entity}.sql
```

### Breaking Change

Existing hub repos with generated dbt artifacts must **regenerate** after upgrading.
The `models/staging/` directory and all `stg_*` files should be deleted.

### Rationale

- Simpler DAG (fewer nodes, less materialization cost)
- Clear boundary: Bronze = platform, Silver = dbt
- Vocabulary TTL is the authoritative bronze contract (see DD-015)
- One fewer template family to maintain
- Silver SQL is still readable — transforms are column expressions, not complex joins
