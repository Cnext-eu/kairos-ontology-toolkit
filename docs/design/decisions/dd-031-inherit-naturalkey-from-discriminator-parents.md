# DD-031: Inherit naturalKey from Discriminator Parents

**Status:** Accepted
**Date:** 2026-05-29
**Affects:** dbt projector — SK/IRI generation for discriminator subtypes
**Implementation:** `src/kairos_ontology/projections/medallion_dbt_projector.py`

### Context

When a parent class uses `kairos-ext:inheritanceStrategy "discriminator"`, its subtypes
are flattened into the parent's silver table. The dbt projector generates per-mapping-target
models (which may target subtypes directly via SKOS mappings). Previously, `_get_natural_key`
only checked the direct class annotation — subtypes without their own `kairos-ext:naturalKey`
produced `CAST(NULL...)` for SK and IRI columns, even when the parent declared a valid key.

### Decision

`_get_natural_key` now walks `rdfs:subClassOf` upward when no direct annotation is found.
It only inherits the parent's naturalKey when the parent declares
`inheritanceStrategy "discriminator"`. Direct annotations on the subclass always win.

A companion function `_get_raw_natural_key` provides the same hierarchy walk but returns
the raw camelCase literal (used by `_get_nk_property_uris` for property URI resolution).

### Rationale

- Discriminator subtypes share the parent's table → they logically share the same NK
- `class-per-table` subtypes get their own tables → they need their own NK definitions
- Recursion guard (`_visited` set) prevents infinite loops from cyclic `rdfs:subClassOf`
- The fix benefits all call sites: SK generation, IRI generation, FK target resolution

### Consequences

- Hub authors can remove redundant `naturalKey` annotations from discriminator subtypes
- Existing hubs with explicit subtype annotations continue to work (direct wins)
- FK resolution to discriminator subtypes now correctly generates join conditions
- The silver projector is unaffected (it skips subtypes entirely and projects only the parent)
