# DD-074: Multi-source merge — canonical superset + per-source FK joins (issue #175)

**Status:** Accepted
**Date:** 2026-06-14
**Affects:** `src/kairos_ontology/projections/medallion_dbt_projector.py`,
`src/kairos_ontology/templates/dbt/silver_source_model.sql.jinja2`,
`src/kairos_ontology/templates/dbt/silver_union_model.sql.jinja2`
**Implementation:** `_build_merge_superset()`, `_build_column_type_map()`,
`_merge_pad_type()` (new); rewired multi-source branch of `_gen_silver_models()`.

### Context

The dbt **merge pattern** (≥2 bronze sources → one silver entity via
`UNION ALL`, with per-source staging views) generated invalid/lossy SQL whenever
sources mapped non-identical property sets (the normal master-data case). Three
defects: (1) the union column list was built from the **first source only**, so
other sources' distinct columns vanished; (2) per-source views projected only
their own mapped columns, so the `UNION ALL` branches had **mismatched column
counts/order** (hard SQL error); (3) FK `_sk` columns were **silently dropped**
because `_extract_fk_columns_and_joins` early-returned for any
`len(source_refs) != 1`.

### Decision

Adopt the canonical dbt "staging-per-source + NULL-padded superset + UNION ALL"
pattern:

- **Canonical superset.** `_build_merge_superset()` merges the scoped per-source
  data columns and per-source FK columns into one deterministic order (all data
  columns in source/property order, then all FK columns) and pads each source's
  missing columns with `CAST(NULL AS <type>)`. Types come from
  `_build_column_type_map()` / `_merge_pad_type()` (range-derived
  `_xsd_to_target`, matching the schema YAML; `_label`/FK `_sk` use the portable
  `{{ dbt.type_string() }}` macro).
- **Explicit union branches.** `silver_union_model.sql.jinja2` now selects the
  explicit canonical column list per branch (no `select *`), so the positional
  `UNION ALL` cannot be corrupted by column drift. The union performs no joins.
- **Per-source FK joins.** Each per-source staging view is single-source, so the
  existing single-source FK machinery runs *inside* it:
  `_extract_fk_columns_and_joins` is called per single source. The mapping source
  emits a real `left join {{ ref(target) }}` + `<fk>_sk`; non-mapping sources pad
  `CAST(NULL AS …) as <fk>_sk`. The FK `_sk` then flows through the `UNION ALL` as
  an ordinary canonical column. `silver_source_model.sql.jinja2` gained join
  rendering (aliased `from … as <source_alias>` + `left join` clauses), mirroring
  the single-source `silver_model.sql.jinja2`.
- **NK-coverage warning.** A loud warning fires when a source does not map a
  natural-key column (rows from it would produce NULL/duplicate surrogate keys).

### Rationale

Deterministic, ontology-driven generation (not dbt-utils `union_relations`
physical introspection) preserves governance and reuses the semantic target
contract. Relocating FK joins from the (impossible) union level to the
single-source staging views makes the existing machinery directly applicable and
strictly better than emitting NULL placeholders — FKs are resolved where mapped
and never silently dropped. This reconciles the rubber-duck review and an
external dbt/medallion review, which both converged on superset + typed NULL pads
+ explicit column lists and (the external review) per-source FK evaluation.

### Consequences

- Per-source views may carry NULL-padded columns they don't populate — expected
  and required for `UNION ALL` consistency; the `_source_system` column
  distinguishes provenance.
- Residual type risk: a real direct-mapping cast uses the **bronze** type while a
  NULL pad uses the **range**-derived type; for `UNION ALL` they must be
  compatible. Pads use the range type for schema-YAML consistency — documented
  limitation.
- NK coverage is **warned, not enforced** (consistent with the toolkit's
  warning-tolerant projection flow); fail-fast remains a considered alternative.
- **Future direction (out of scope, follow-up #176):** split `*_union` (conformed
  multi-source stack) from `*_resolved` (survivorship / golden-record / MDM) and
  add richer source-lineage columns (`source_pk`, record hash, `extracted_at`).
- Scenario tests that encoded the buggy behaviour were updated:
  `test_scenario_dbt.py` (`test_crm_source_includes_null_pad_for_unmapped`,
  `TestUnmappedColumnExclusion`, `TestMultiSourceFKPerSource`) and
  `test_scenario_projection.py` (merge superset non-lossy + FK presence). Unit
  tests added: `TestMergeSupersetPadding`, `TestMergeFKPerSource`,
  `TestMergeNKCoverageWarning` in `tests/test_dbt_projector.py`.
- **Regression follow-ups (issues #178, #179).** Two per-source-merge edge cases
  surfaced after DD-074 and were fixed without changing the core design:
  (#178) an **explicit** FK column-mapping declared by one merge source leaked
  into other sources' per-source views (phantom join/columns) — the
  explicit-mapping branch of `_resolve_fk_source_column` is now scoped to the
  current source's columns (None-sentinel scope; physical-column fallback for
  synthetic/composite subjects via `_mapping_belongs_to_source`); (#179) a table
  mapping whose target class is **not projected** (unclaimed import) was silently
  dropped — `_gen_silver_models` now folds such orphans onto a projected
  discriminator parent when present, otherwise emits a loud warning. Unit tests
  `TestMergeExplicitFKMappingScope`, `TestUnprojectedClassMapping` and scenario
  test `TestMergeExplicitFKNoLeak` were added.
