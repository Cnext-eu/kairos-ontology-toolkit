# DD-019: Cross-Domain FK Resolution via Surrogate Key Joins

**Status:** Accepted
**Date:** 2026-05-01
**Affects:** `medallion_dbt_projector.py`, silver model SQL generation, schema YAML
**Implementation:** `src/kairos_ontology/projections/medallion_dbt_projector.py` `_extract_fk_columns_and_joins()`

### Context

When an `owl:ObjectProperty` maps a source column to a class in another domain (e.g.,
`Relation.id` maps to `client:representsParty` → `Party`), the silver model needs a
surrogate key column (`party_sk`) that resolves the source natural key to the target
table's SK via a lookup join. Previously, the dbt projector only processed
`DatatypeProperty` — object properties were silently skipped.

### Decision

Generate cross-domain FK columns as `left join {{ ref('{target_model}') }}` lookups
in the silver SQL model. The join condition uses the source column (from SKOS mapping)
matched against the target class's `kairos-ext:naturalKey` column.

**Guards (safe first cut):**
- Only for single-source models (multi-source models are skipped — too complex)
- Only when the target class has a single-column natural key (composite NK → NULL + warning)
- Only for qualifying properties: `owl:FunctionalProperty` or explicit `silverColumnName`
- Missing SKOS mapping → NULL placeholder + warning

### Rationale

| Approach | Pros | Cons |
|----------|------|------|
| Pass-through natural key | Simple | Misleading column name (`_sk` but contains NK) |
| **Join to ref() (chosen)** | Correct semantics; silver is self-consistent | Requires target model to exist; join overhead |
| Gold-layer only | Clean separation | Silver schema doesn't match DDL projector output |

The join approach was chosen because:
1. The DDL silver projector already declares these as `_sk STRING` FK columns
2. The dbt template already supports `joins` (just wasn't being used)
3. Makes silver layer self-consistent: all `_sk` columns are surrogate keys

### Consequences

- FK columns now appear in generated SQL and schema YAML
- Target silver models must exist (dbt will error on dangling `ref()` if target ontology
  is not projected) — this is correct behaviour (surface missing dependencies early)
- Multi-source and composite-NK cases degrade gracefully (NULL + warning)
- Future work: support composite natural keys via multi-column join conditions
