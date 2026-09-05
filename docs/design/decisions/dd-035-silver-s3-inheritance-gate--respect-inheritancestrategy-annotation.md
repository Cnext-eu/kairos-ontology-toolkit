# DD-035: Silver S3 Inheritance Gate — Respect `inheritanceStrategy` Annotation

**Status:** Accepted
**Date:** 2026-05-30
**Affects:** `medallion_silver_projector.py`, `medallion_dbt_projector.py`, `gold_model.sql.jinja2`, scenario tests
**Implementation:** Silver pre-scan gate + TPC property inheritance; dbt sources scoping, dim_date CTE, SK validation, FK-child inverse lookup.

### Context

The silver projector unconditionally flattened ALL subtype hierarchies (S3 rule),
merging every child class into its parent table regardless of the ontology author's
intent. This contradicted the dbt and gold projectors, which already gated S3 on
`kairos-ext:inheritanceStrategy "discriminator"` — only folding subtypes when
explicitly annotated.

A change request (`cr-remove-s3-discriminator-default.md`) identified this
inconsistency plus four additional independent bugs:

1. **Sources YAML scoping** — `_gen_sources` emitted ALL vocabulary tables, not just
   those with SKOS mappings to the domain.
2. **dim_date placeholder** — referenced a non-existent `seed_dim_date` model;
   emitted all-NULL columns.
3. **SK validation** — `naturalKey` columns referenced in the surrogate key hash
   were never validated against the actual column list.
4. **FK-child inverse** — properties with `silverForeignKeyOn` were skipped on the
   domain class but never emitted on the target class.

### Decision

1. **Silver S3 gate:** The pre-scan now only folds subtypes into `folded_subtypes`
   when the parent class has `kairos-ext:inheritanceStrategy "discriminator"`.
   Without the annotation, subtypes get their own tables (TPC) and inherit parent
   properties via the `inherit_from` parameter on `_get_class_and_ancestors`.

2. **Sources YAML scoping:** `_gen_sources` now accepts `mappings` and filters
   tables to only those whose URI appears in `mappings["table_maps"]`. Empty
   source systems (no mapped tables) are skipped entirely.

3. **dim_date inline CTE:** Replaced the broken `seed_dim_date` reference with an
   inline date-spine CTE using `TABLE(GENERATOR(ROWCOUNT => 36525))`. The gold
   template now supports `cte` (raw SQL) as an alternative to `model` (ref) in
   `source_ctes`.

4. **SK validation:** After assembling all columns, a warning is logged if any
   `naturalKey` column name doesn't appear in the generated column list.

5. **FK-child inverse:** New `_infer_fk_on_targets` function collects properties
   where `silverForeignKeyOn` points to the current class, ensuring FK columns
   appear on the correct target table.

### Rationale

- Aligns silver with dbt/gold: all three projectors now use the same opt-in
  discriminator pattern. TPC (separate tables per concrete class) is the safe
  default that preserves information.
- Sources scoping prevents dbt compilation errors from undeclared source tables.
- The dim_date CTE makes the gold model self-contained (no seed dependency).
- SK validation catches annotation mistakes early (at projection time).
- FK-child inverse completes the DD-022 `silverForeignKeyOn` contract.

### Consequences

- **Breaking change for silver:** Hubs that relied on unconditional S3 flattening
  must add `kairos-ext:inheritanceStrategy "discriminator"` to parent classes in
  their silver extension. The kairos-design-silver skill guides this.
- dim_date uses Snowflake-specific `GENERATOR()` syntax; a platform switch may be
  needed for other warehouses (already guarded by `target_platform` in other code).
- The `gold_model.sql.jinja2` template now supports both `cte.model` (ref-based)
  and `cte.cte` (raw SQL) — backward compatible.
