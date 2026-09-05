# DD-028: Multi-Table Same-Source Union Model Disambiguation

**Status:** Accepted
**Date:** 2026-05-27
**Affects:** `projections/medallion_dbt_projector.py`, dbt silver model naming
**Implementation:** Per-source model naming logic in `_gen_silver_models()`

### Context

DD-018 established entity-centric silver models with multi-source split (one per-source model
per source system, combined via UNION ALL). The per-source model naming used only the entity
name and source system name: `{entity}__from_{source_system}`.

When two tables from the **same** source system map to the **same** domain class (e.g.,
`sales_invoices` and `purchase_invoices` both from `QargoTms` → `Invoice`), the naming
produced identical model names. The second model silently overwrote the first in the
artifact dict, and the UNION ALL referenced the same model twice.

### Decision

When multiple tables from the same source system map to the same entity, append a
sanitized table name suffix to disambiguate:

- **No collision (common case):** `{entity}__from_{source}` (unchanged)
- **Collision detected:** `{entity}__from_{source}__{table_name}`

Detection uses a `Counter` over source system names in the entity's source_refs list.
The table suffix is only added when `count > 1` for that source system.

### Rationale

| Approach | Pros | Cons |
|----------|------|------|
| Always include table name | Unambiguous | Long names; breaking change for all hubs |
| **Conditional suffix (chosen)** | Short names by default; disambiguates only when needed | Slightly more logic |
| Numeric suffix (\_1, \_2) | Short | Unstable (order-dependent); not self-documenting |
| Error on collision | Safe | Blocks projection; poor UX |

### Consequences

- Hubs with multi-table-same-source patterns get correctly disambiguated model files
- Hubs without collisions see zero change in output (backward-compatible)
- Model names may be longer for collision cases — warehouse name limits (128 chars) should
  be monitored for edge cases
- This is a **minor breaking change** for hubs that previously generated colliding names:
  their model filenames change (from the incorrect duplicate to two distinct files)

### Amendment — v5 conformance branches (issue #284)

The v5 compiler (`merge_bound_sources`) emits one branch per conformance contributor and
always uses the full `{entity}__from_{source}__{table}` form — it does not apply the
conditional-suffix rule above, because every member of a conformance group targets the same
entity and so would always collide.

A contributor sourced from a contracted dbt model (`source.dbtModel`) names its branch
`{entity}__from_dbt__{dbt_model_name}`: `dbt` is that relation's system label and the model
name is its table name, matching the `dbt:<name>` source identity used by conformance
validation and the `('dbt', '<model>', ...)` inputs to `_source_record_key`. Consequently
`_source_system` is `'dbt'` for all such branches — constant by design, exactly as two
tables from one `crm` system share `'crm'`; `_source_record_key` carries the discriminating
model name.

The failure this section originally described recurred in the v5 kernel because these fields
were blanked for dbt-model sources, so every branch collapsed onto one name. Duplicate branch
names are now a hard error rather than a silent last-write-wins.
