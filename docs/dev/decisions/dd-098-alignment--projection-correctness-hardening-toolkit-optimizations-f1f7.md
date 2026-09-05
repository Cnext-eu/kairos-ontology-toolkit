# DD-098: Alignment & projection correctness hardening (toolkit-optimizations F1–F7)

**Status:** Accepted
**Date:** 2026-07-21
**Affects:** `src/kairos_ontology/core/propose_alignment.py`,
`src/kairos_ontology/core/migrate_claims.py`,
`src/kairos_ontology/core/claim_registry.py`,
`src/kairos_ontology/core/completeness_model.py`,
`src/kairos_ontology/core/claim_coverage.py`,
`src/kairos_ontology/core/source_coverage.py`,
`src/kairos_ontology/core/inventory.py`,
`src/kairos_ontology/cli/main.py`,
`src/kairos_ontology/core/projections/shared.py`,
`src/kairos_ontology/core/projections/medallion_dbt_projector.py`,
`src/kairos_ontology/core/projections/medallion_silver_projector.py`
**Implementation:** `docs/draft/toolkitoptimizations.md` (issue #219 for F1)

### Context

Real hub work surfaced seven independent correctness/governance gaps in the
source→domain alignment and medallion projection pipeline. Each was reproducible
and mapped to a specific module. They are implemented together because they share
the registry-write and coverage-gate surfaces.

### Decision

- **F4 — URI backfill.** `write_claims_output` now threads an optional
  `inventory_dir` (default `hub_root/referencemodels-unpacked`) and builds a
  `load_inventory_uri_index(...)` passed to `alignment_to_registry`, so proposed
  claims carry resolved `class_uri`/`property_uri` without manual repair. No new
  CLI flag (backward-compatible default).
- **F5 — inventory scope.** `check-inventory` gains `--domains`/`--explain-scope`;
  the domain→inventory map is resolved through the catalog (source paths/model
  names), not guessed from affinity. Repo-wide checking stays the default;
  active-domain readiness is reported separately.
- **F6 — truncation integrity.** The 80-column prompt cap could silently drop
  columns. A deterministic **source column-set count + sha256** is persisted per
  `(system,table)` (`CoverageTable.source_column_count`/`source_column_sha256`);
  alignment post-processing reconciles **every** source column and synthesizes
  passthrough candidates for any unaccounted one; `ClaimCheckReport` gains a
  **blocking** `column_omissions` signal (not overloaded on `anchor_state`) that
  compares registry-covered columns against the affinity `total_columns` through
  the canonical completeness facts.
- **F2/F7 — grain conflict.** `likely_entity` (candidate-entity provenance) is now
  carried on `TableAlignment`, serialized in `alignment_to_dict`, and consumed in
  `alignment_to_registry` **before** class dedup. When ≥2 tables with *different*
  candidate entities collapse onto one `ref_class`, a blocking `grain_conflicts`
  record is emitted (new `ClaimRegistry`/`ClaimCheckReport` representation + gate).
  `class_claim_id` is deliberately **unchanged** (would disrupt property IDs and
  merges).
- **F3 — object-property target.** A deterministic range resolver
  (`_resolve_object_property_target`) detects object properties (PascalCase
  `rdfs:range` or curated name hints). When the governed target class resolves, the
  scalar mapping is kept (byte-identical); when it does **not**, the scalar column
  is downgraded to a passthrough custom claim and an
  `object_property_relationship_candidate` (target + cardinality) is emitted — one
  governed disposition per source column, no double count.
- **F1 — naming parity (#219).** A single shared physical-naming helper
  (`silver_schema_name`/`silver_table_name`/`silver_naming_convention` in
  `projections/shared.py`) is now consumed by **both** the silver DDL projector and
  the dbt projector, which previously hardcoded `silver_{domain}` and
  `camel_to_snake(local)`. The dbt gold `ref()` registry uses the actually-generated
  model name. Both targets now honour `silverSchema`/`silverTableName`/
  `isReferenceData`/`namingConvention` identically.

### Rationale

Each fix keeps default output **byte-identical when no new condition fires**
(mirrors DD-045/DD-070 gating): F1 defaults reproduce the old names, F3 only
downgrades when the target is ungoverned, F6 only blocks on a real shortfall, and
F2/F7 only fires on a genuine multi-entity collapse. All new gate/resolver paths
are deterministic (no LLM). `core` still never imports `mdm`.

### Consequences

- `check-claims`/`check-inventory` can now block on previously-silent omissions and
  grain collapses; hubs using the 80+ column path or ambiguous entity anchoring get
  actionable, deterministic diagnostics.
- dbt and silver physical names can no longer drift (issue #219).
- Regression coverage: `tests/scenarios/test_scenario_truncation_integrity.py`,
  `tests/scenarios/test_scenario_object_property_target.py`,
  `tests/scenarios/test_scenario_naming_parity.py`, plus unit tests in
  `tests/test_propose_alignment.py`, `tests/test_migrate_claims.py`,
  `tests/test_claim_coverage.py`, `tests/test_cli_inventory.py`.
