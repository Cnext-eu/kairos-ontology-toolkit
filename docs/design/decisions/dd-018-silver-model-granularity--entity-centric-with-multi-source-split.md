# DD-018: Silver Model Granularity — Entity-Centric with Multi-Source Split

**Status:** Accepted
**Date:** 2026-04-30 (updated 2026-05-01)
**Affects:** `medallion_dbt_projector.py`, silver model generation, dbt package structure
**Implementation:** `src/kairos_ontology/projections/medallion_dbt_projector.py`

### Context

When multiple integration sources map to the same domain class (e.g., `Harmoney.Customers`
and `AdminPulse.Klanten` both map to `domain:Client`), the dbt projector must decide how
to structure the silver SQL models:

- **Entity-centric** — one `client.sql` per domain class, with multiple source CTEs inside.
- **Source-centric** — one model per source-entity combination (`client__from_harmoney.sql`,
  `client__from_adminpulse.sql`), plus a union model.

### Decision

**Single source (default):** Entity-centric silver models. Each domain class produces
exactly one `.sql` file under `models/silver/{domain}/`.

**Multi-source (automatic):** When two or more bronze tables map to the same domain class,
the projector automatically generates:

1. Per-source view models: `models/silver/{domain}/{entity}__from_{source}.sql`
   — materialized as views, rename/cast/normalize columns to match target schema
2. A union model: `models/silver/{domain}/{entity}.sql`
   — `UNION ALL` of per-source refs, adds SK/IRI columns on normalised target names

The split is triggered automatically by mapping count, not by a CLI flag.

### Rationale

| Approach | Pros | Cons |
|----------|------|------|
| Entity-centric (single source) | Single source of truth for gold; built-in dedup; fewer files | Harder per-source debugging with many sources |
| Per-source views + union (multi-source) | Per-source lineage & testing; independent source ownership; `dbt run -s client__from_adminpulse` | Extra union step; more generated files |

The entity-centric model is preserved as the default for the common single-source case.
Multi-source automatically splits to enable per-source debugging and lineage. SK/IRI
columns are computed in the union model on normalised target column names, ensuring
consistent keys regardless of source column naming.

### Key design choices

1. **Per-source models are views** — zero materialization cost; the union model is the
   materialized `table`.
2. **Unmapped optional columns → `CAST(NULL AS type)`** — maintains column alignment
   across UNION ALL branches.
3. **SK/IRI only in union model** — avoids duplicate key computation; keys are
   source-agnostic.
4. **FK joins only in union model** — applied after union on normalised column names.
5. **Naming convention:** `{entity}__from_{snake_source}` (double underscore matches
   dbt convention for cross-concern models).

### Consequences

- No breaking change — single-source entities generate identically to before.
- Multi-source entities produce N+1 files (N per-source views + 1 union table).
- The gold layer remains unchanged (it reads from the entity-level model regardless).
- `_sources.yml` separation already supports this pattern (one per source system).
- FK joins are still empty for multi-source (planned follow-up).
