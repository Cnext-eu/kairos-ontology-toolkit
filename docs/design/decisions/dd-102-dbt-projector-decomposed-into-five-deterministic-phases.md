# DD-102: dbt projector decomposed into five deterministic phases

**Status:** ~~Superseded by [DD-110](dd-110-typed-projection-contract-and-silver-output-parity.md)~~
**Date:** 2026-07-21
**Affects:** `src/kairos_ontology/core/projections/medallion_dbt_projector.py`,
`src/kairos_ontology/core/projections/dbt/` (new subpackage)
**Implementation:** `core/projections/dbt/{context,bind,normalize,shape,materialize,render}.py`;
`generate_dbt_artifacts` rewritten as a thin orchestrator; phase-level tests in
`tests/test_dbt_phases.py`

### Context

`medallion_dbt_projector.py` had grown to ~3.9k lines and its public entrypoint
`generate_dbt_artifacts` was a monolithic *policy hub*: graph/extension merge, FK
classification, source/mapping parsing, contracted virtual-source resolution,
`SourceBindings`, the canonical `BindingAnalysis`, per-class column/FK shaping, SCD
/ materialization selection, release-gate metadata, and final artifact assembly +
validation were all interleaved in one flow (and, per class, inside
`_gen_silver_models`). Policy was re-derived at several points and the render step
still read the RDF graph, so there was no auditable boundary between "decide" and
"emit". This blocked the shared-tree work (deterministic context, TargetSpec
registry, canonical completeness/materialization, explicit legacy migrations,
shared FK normalization) from landing on a clean seam.

### Decision

Turn `generate_dbt_artifacts` into an **orchestrator** over five explicit,
ordered phases that exchange typed, **immutable** (`frozen=True`) intermediate
models defined in `core/projections/dbt/context.py`:

`bind → normalize → shape → materialize → render`

- **bind** (`bind.py` → `BoundSources`) — takes the committed `DbtInputs`, commits
  the ext-merged working graph (silver-ext / ref-model-default / peer triples are
  merged here because source binding needs them), parses source `systems` + SKOS
  `mappings`, resolves the active contracts + contracted virtual sources
  (`virtual_table_uris` / `replacement_input_uris`), and computes the canonical
  `SourceBindings`.
- **normalize** (`normalize.py` → `ProjectionContract`) — derives the FK
  descriptors (`classify_foreign_keys`) and the canonical `BindingAnalysis`
  **grounded in** the bind phase's `SourceBindings` (never re-derived), plus the
  Silver naming convention + ontology URI.
- **shape** (`shape.py` → `ShapedProject`) — produces sources, Silver models
  (+ warnings + entity metadata), schema YAML, the Silver registry, Gold star
  schema + schema YAML, coverage data, and macros. FK/binding *policy* is read from
  `ProjectionContract`/`SourceBindings` (threaded into `_gen_silver_models` via new
  optional `bindings=` / `analysis=` args) rather than reclassified.
- **materialize** (`materialize.py` → `MaterializationPlan`) — owns the
  orchestration-level release metadata (`unbound_eligible_names` → the
  `__unbound_eligible__` sentinel, DD-096 / DEC-1) and the per-domain project
  configuration.
- **render** (`render.py`) — assembles the final `{path: content}` map from the
  committed `ShapedProject` + `MaterializationPlan` (strings/sets/dicts only) and
  runs post-generation validation. Its signature is `(shaped, plan)` — it is
  structurally incapable of rereading RDF/mappings or reclassifying policy.

**Byte-parity is a hard constraint.** Public output and APIs are unchanged: all
existing public functions and direct test imports (`generate_dbt_artifacts`,
`generate_dbt_project_config`, `write_dbt_session_log`, `compute_source_bindings`,
`SourceBindings`, `_parse_bronze`, `_parse_skos_mappings`, `_gen_silver_models`,
`_extract_silver_columns`, `_validate_dbt_artifacts`, …) remain in
`medallion_dbt_projector.py` as compatibility facades. Feature-off and stub-on
outputs are byte-identical to the pre-refactor baseline (verified by hashing the
full artifact maps of the acme-hub `client` (default + stub-off + stub-on),
`invoice`, and `logistics` scenarios, plus the two-process determinism probe).

### Rationale

Extracting *phase boundaries* first (with the leaf helpers left in place and
invoked by the phase functions via lazy imports) makes the decomposition provably
byte-safe: the same helpers are called with the same arguments in the same order,
so the emitted strings — and the deduplicated projection-report warnings — are
unchanged. Threading the already-committed `SourceBindings`/`BindingAnalysis` into
`_gen_silver_models` (additive, defaulted args) removes the double-derivation
without altering behaviour. A frozen render input is the cheapest possible proof
that emission no longer depends on policy.

### Consequences

- New internal subpackage `core/projections/dbt/`; no public API or artifact path
  changed; no broad renames/deletions.
- **Retained debt (deliberate, documented):** the heavy leaf helpers (notably
  `_gen_silver_models`, `_gen_schema_yaml`, `_gen_gold_models`) still live in
  `medallion_dbt_projector.py`, and per-model shape/materialize/render remains
  interleaved inside `_gen_silver_models` (SQL/templates were **not** redesigned per
  scope). The graph/extension *merge* is committed at the bind boundary (source
  binding needs it) while the derived *contract* is owned by normalize. Further
  lifting of template rendering out of the shaping helpers is future work on this
  now-explicit seam.
- Phase-level regression coverage in `tests/test_dbt_phases.py` (immutability,
  deterministic ordering, phase-boundary/input constraints); output parity is
  covered by the scenario/golden/determinism suites, including the complete
  Silver-first lifecycle in `tests/scenarios/test_scenario_silver_first_e2e.py`.
