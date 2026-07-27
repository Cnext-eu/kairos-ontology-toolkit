# Kairos v5 implementation plan

## Problem and approach

Kairos currently contains a capable immutable dbt projection pipeline, but the authoring
and operating experience around it has accumulated too many authorities and intermediate
steps: claims, mapping TTL, preparation TTL, Silver extension TTL, transformation
contracts, virtual sources, readiness reports, lifecycle state, release evidence, and
phase-oriented skills.

V5 will be built in this repository as a clean authoring break. Existing v4 hubs do not
need compatibility or migration support; they will be rebuilt as v5 hubs.

The implementation will use a strangler approach inside the repository:

1. preserve the reusable ontology, source, typed-expression, immutable compiler, adapter,
   and dbt rendering code;
2. introduce one concise YAML `EntityBinding` as the source-to-canonical execution
   authority;
3. introduce one stateless `compile` path that checks, explains, or atomically emits;
4. deliver a thin Copilot-skill-driven LLM loop in the first vertical slice;
5. prove the design with a fresh v5 scenario hub;
6. move all projection entry points to the new compiler; and
7. retire the v4 lifecycle, claims, readiness, preparation, virtual-source, and evidence
   machinery after the replacement path is covered.

## Confirmed decisions

- Work remains in `C:\code\kairos-ontology-toolkit`; no new product repository.
- The plan covers the full v5 migration, with the first vertical slice specified in detail.
- V5 authoring uses concise YAML entity bindings.
- No v4 hub compatibility, dual-format authoring, or migration command is required.
- The first slice includes a thin end-to-end LLM-assisted canonical-design and mapping
  experience.
- The LLM experience is primarily implemented through Copilot skills calling deterministic
  toolkit primitives. Do not create a second proposal database or session-state subsystem.
- OWL/Turtle remains authoritative for the industry-aligned canonical Silver model.
- Source vocabularies/contracts remain authoritative for Bronze schema and samples.
- Hand-authored dbt SQL/YAML remains authoritative for relational transformations and
  their output contracts.
- dbt and CI remain authoritative for execution, runtime tests, and deployment.
- Kairos persists no lifecycle, readiness, proposal, or current-verification state.
- Incomplete entities may be explained in-session, but executable SQL is emitted only when
  the static safety contract is complete.

## Implementation status (2026-07-27)

The first vertical slice is implemented:

- closed YAML `EntityBinding` schema/loader and graph-free adapter;
- stateless multi-entity compiler kernel with deterministic scope/provenance, safety
  diagnostics, relationship policy, per-entity blocking, and shared explain/render IR;
- `compile <domain> --check|--explain|--emit`, with manifest-owned same-volume
  stage/swap/rollback emission;
- rewritten canonical-design and mapping skills in both managed locations;
- a fresh v5 scenario hub covering deterministic Fabric artifacts and fail-closed sample
  privacy.

Stages 2–4 are also complete:

- Stage 2 completes the strict kernel: full-refresh and complete incremental SCD1/SCD2
  policy, canonical hashing, CDC/order/replay/backfill/schema-evolution checks, temporal
  relationships, deterministic multi-source conformance, Fabric/Databricks capability
  checks, and direct resolution of ordinary contracted dbt SQL/YAML sources.
- Stage 3 makes immutable, graph-free `CompilePlan` the canonical planning authority and
  `compile` the only canonical Silver/dbt generation path. Optional Gold and MDM projections
  consume that same typed plan; they do not resolve or rebuild Silver inputs.
- Stage 4 removes all inventoried v4 operational waves: release/lifecycle/readiness/status,
  transformation evidence/synchronization/candidates, claims and completeness/stubs,
  preparation/Silver RDF authority, persisted projection/import session evidence, release
  baselines, and obsolete commands/tests.

The retained architecture is intentional: ontology and source loading, source analysis,
reference models, the typed scalar-expression and policy structures, immutable
normalize/shape/materialize phases, canonical hashing, adapter capability negotiation,
deterministic dbt renderers, and optional Gold/MDM consumers remain.

Stages 5–8 are complete as of 2026-07-27. The implementation now includes the decomposed
CLI, lean v5 scaffold, rewritten stateless skills, v5-only test architecture, and final
documentation/release cleanup. The release candidate remains unpublished until the human
publication steps and DCO caveat recorded by the final validation are resolved.

## Current codebase assessment

### Reusable foundations

- `src/kairos_ontology/core/ontology_loader.py` already provides catalog-aware ontology
  loading and deterministic import closure.
- `src/kairos_ontology/core/projections/dbt/` already implements a typed immutable
  `bind -> normalize -> shape -> materialize -> render` pipeline.
- `mapping_specs.py`, `mapping_normalize.py`, and `mapping_renderers.py` provide the
  closed, typed, deterministic scalar-expression AST needed by v5.
- `specs.py`, `context.py`, `canonical_hash.py`, `capabilities.py`,
  `runtime_reference.py`, and the model renderers contain the strict identity, SCD/CDC,
  FK, adapter, and deterministic-rendering behavior to retain.
- `ai_provider.py`, `analyse_sources.py`, `propose_alignment.py`, `_samples.py`,
  `source_privacy.py`, `silver_sample_audit.py`, and `tmdl_parser.py` contain useful LLM,
  source-evidence, sample-redaction, and downstream-demand capabilities.
- Existing scenario and projector tests provide extensive characterization of generated
  SQL/YAML and the phase boundaries.
- The `core -> mdm` one-way dependency boundary in `tests/test_layering.py` must remain
  unchanged.

### Replacement seams

- `DbtInputs` currently accepts mapping, preparation, Silver-extension, and transformation
  contract paths. V5 will instead accept immutable entity-binding facts.
- `bind_sources()` currently reads mapping RDF, preparation RDF, claim-driven eligibility,
  and virtual-source contracts. The v5 path will bind YAML directly into existing typed
  expression and Silver facts without generating intermediate TTL.
- `normalize_medallion_policy()` currently combines preparation, identity, runtime,
  temporal-FK, quality, Gold, and release concerns. It will be reduced to the v5 static
  safety kernel.
- `core/projector.py` currently persists projection reports and carries release/stub
  metadata. The v5 compiler will return one invocation result and emit only requested
  artifacts.
- `cli/main.py` is a high-risk monolith with lifecycle, claims, readiness, evidence, and
  projection commands. New v5 commands should live in a separate CLI module before old
  commands are removed.

### Machinery to retire

- Claims and synchronization:
  `claim_registry.py`, `claim_coverage.py`, `claim_projection_sync.py`,
  `claim_check_result.py`, `derive_claims.py`, `decide_claims.py`, `migrate_claims.py`,
  claim-specific parts of `binding_analysis.py` and `completeness_model.py`.
- Lifecycle/readiness/release:
  `status.py`, `lifecycle_gate.py`, `projection_readiness.py`, `release_evaluator.py`.
- Transformation evidence and virtual-source synchronization:
  `dbt_contract_identity.py`, `dbt_contract_sync.py`, `transformation_candidates.py`, and
  the virtual-source authority portions of `dbt_contracts.py`.
- Mandatory preparation authoring:
  `kairos-prep.ttl`, its SHACL shapes/templates, preparation-policy bind/normalize code,
  and preparation-only physical plans. Safe scalar cleanup moves into bindings; complex
  work remains in dbt.
- Persisted projection/session reports, `.kairos-state` scaffold directories, phase logs,
  release baselines, claim registries, readiness files, and evidence folders.
- Commands and skill paths dedicated to those subsystems.

## Target architecture

### Authoritative v5 hub files

```text
model/
  ontologies/<domain>.ttl
  shapes/                         # optional SHACL
integration/
  bindings/<source>-to-<domain>.binding.yaml
  discovery/                      # confirmed business context/glossary only
  sources/<source>/*.ttl          # Bronze schema and redacted samples
  transforms/dbt/
    models/**/*.sql               # only when relational logic is required
    models/**/*.yml               # dbt output contracts and tests
kairos.yaml                       # namespace, catalog, adapters, selected roots
output/                           # derived artifacts only
```

There are no claims, Silver-extension, preparation, planning, readiness, evidence,
governance, or phase-state directories in a new v5 hub.

### Compiler packages

Add `src/kairos_ontology/core/compiler/`:

- `scope.py`: immutable `BuildScope` and provenance paths from requested roots.
- `bindings.py`: YAML schema model, loader, source/ontology symbol resolution, and
  conversion to typed authored facts.
- `ir.py`: graph-free `CanonicalProjectIR` and `EntityBindingSpec`.
- `quality.py`: the minimal non-suppressible static safety kernel.
- `result.py`: ordered diagnostics, explain data, and in-memory artifact plan.
- `compile.py`: orchestration for check, explain, and atomic emit.

The compiler may reuse types from `core/projections/dbt/`, but `core/compiler` must not
import `kairos_ontology.mdm`.

### EntityBinding authority

Each YAML binding identifies:

- one source relation or contracted dbt model;
- one canonical ontology class;
- field-to-property mappings;
- a closed typed scalar-expression tree where needed;
- materialized grain and identity;
- full-refresh or incremental/SCD behavior;
- relationship lookup/cardinality/failure behavior; and
- focused data-quality checks.

The binding references source columns and ontology properties; it does not copy their
definitions. It references a dbt model contract for joins, windows, aggregations,
deduplication, complex fallback, or grain changes.

Use `jsonschema`, already present in the project, for document-shape validation. Convert
validated YAML directly to frozen dataclasses and the existing mapping AST; never
serialize temporary RDF.

### Minimal safety kernel

Non-suppressible checks:

- source relation, source column, target class, and target property resolution;
- canonical source/target type compatibility;
- deterministic, bounded scalar expressions with explicit null/error behavior;
- explicit materialized grain, identity strategy, key scope, and load mode;
- strict separation of source identity, business identity, ontology IRI, and surrogate
  key;
- complete merge identity and CDC/SCD behavior before incremental SQL is emitted;
- explicit current/as-of/non-temporal relationship mode, cardinality, missing-parent
  action, and ambiguous-parent action;
- adapter capability support;
- deterministic artifact planning and rendering.

Focused data-assisted checks:

- source and output contract shape;
- identity non-null/uniqueness;
- source-to-target row-count or amount reconciliation;
- referential coverage;
- selected range/distribution and cross-field invariants.

Use ordinary generated dbt tests for runtime checks. Do not add Kairos-specific runtime
result contracts.

### Command surface

```text
kairos-ontology compile <domain> --check [--format text|json]
kairos-ontology compile <domain> --explain [--format text|json]
kairos-ontology compile <domain> --emit <directory>
```

- Exactly one mode is required.
- `--check` and `--explain` never write hub files.
- `--emit` first creates a complete in-memory plan, then writes through a temporary sibling
  directory and replaces the selected generated target only after success.
- Diagnostics are complete, deterministic, ordered, and printed or returned to the caller.
- No implicit global scope, adapter, catalog, or accelerator fallback is introduced.

## Detailed first vertical slice

### Slice definition

Create a fresh `tests/scenarios/v5-hub/` fixture with:

- confirmed business context for one synthetic company/domain;
- one small industry-aligned canonical ontology slice;
- one Bronze source vocabulary with PII-safe representative samples;
- one YAML entity binding;
- a full-refresh canonical entity with explicit source identity;
- one typed conversion or null policy;
- one relationship to a small reference entity;
- focused uniqueness, non-null, reconciliation, and referential tests; and
- generated dbt SQL/schema YAML for Fabric.

Keep the slice intentionally small. It must prove the complete experience rather than all
SCD and multi-source features.

### First-slice implementation steps

1. **Lock the v5 contract**
   - Add one consolidated v5 design decision to
     `docs/design/toolkit-design-decisions.md`, using the next DD number.
   - Supersede the lifecycle/claims/readiness/release decisions identified in the v5 design
     review without deleting historical entries.
   - Define the YAML schema and one canonical example in the v5 design documentation.

2. **Introduce binding data structures and schema**
   - Add SPDX-compliant `core/compiler` modules.
   - Define frozen dataclasses for source reference, target reference, grain, identity,
     load, field mapping, relationship, and focused quality checks.
   - Add the packaged JSON Schema and a scaffold example.
   - Reject unknown fields, duplicate bindings, unresolved prefixes, and malformed
     expressions with source locations.

3. **Bind YAML directly to existing typed facts**
   - Resolve source tables/columns from source vocabularies.
   - Resolve classes/properties and ranges from the ontology import closure.
   - Convert binding expressions directly into `AuthoredExpressionFact` and then the
     existing normalized mapping AST.
   - Convert grain, identity, load, relationship, and quality declarations directly into
     graph-free facts consumed by normalization.
   - Do not emit intermediate mapping TTL, Silver extension TTL, preparation TTL, or
     virtual-source TTL.

4. **Build the stateless compiler orchestration**
   - Resolve one `BuildScope` from the requested domain/binding roots.
   - Parse and bind each selected input once.
   - Return all independent diagnostics in collect mode.
   - Produce explain output from the same IR used for emission.
   - Adapt the existing immutable dbt phases rather than introducing a second renderer.
   - Block only the affected entity; permit other safe entities in the selected scope.

5. **Add the compile CLI**
   - Create `src/kairos_ontology/cli/compile.py`.
   - Register it from `cli/main.py` while leaving old commands temporarily untouched.
   - Implement mutually exclusive check/explain/emit modes and text/JSON output.
   - Keep command output ephemeral and avoid projection/session report writes.

6. **Deliver the thin LLM canonical-design loop**
   - Rewrite the active `kairos-design-domain` skill around the smallest useful canonical
     slice.
   - Feed it confirmed business context, selected industry references, source vocabulary,
     PII-safe samples, and optional TMDL/Gold demand.
   - Require the proposal to distinguish business authority, industry inspiration, source
     feasibility, and downstream demand.
   - Produce a reviewable ontology patch only; no claims or proposal registry.
   - Validate syntax, ontology conventions, and source feasibility before acceptance.

7. **Deliver the thin LLM mapping loop**
   - Rewrite the active `kairos-design-mapping` skill to author the YAML entity binding.
   - Use `compile --check` after each proposal batch.
   - Use `compile --explain` to present normalized mappings and blocked behavior.
   - Generate or run focused dbt/sample checks when evidence is available, feed failures
     back to the LLM, and persist only the accepted binding/dbt changes.
   - Hand complex relational work to the dbt transformation skill without creating a
     transformation registry or virtual source.

8. **Prove the slice**
   - Unit-test YAML schema validation, symbol resolution, expression conversion, diagnostic
     accumulation, PII masking, and atomic emission.
   - Add error cases for unknown columns/properties, incompatible types, missing identity,
     incomplete relationship policy, unsafe expressions, and unsupported adapter behavior.
   - Add scenario tests for check, explain, emit, deterministic repeat emission, no state
     files, and expected dbt artifacts.
   - Run dbt parse/compile through the existing mocked/optional integration pattern.
   - Add skill contract tests ensuring both skill copies use the new workflow.

### First-slice acceptance gate

- A Copilot session can propose one bounded canonical ontology slice from the permitted
  evidence and produce a validated ontology patch.
- In the same workflow, it can propose a YAML binding for a real fixture source.
- `compile --check` returns all applicable findings without writing files.
- `compile --explain` shows scope, normalized fields, identity, relationship behavior, and
  planned artifacts without writing files.
- `compile --emit` generates deterministic, parseable dbt artifacts only after the static
  safety contract passes.
- Sample data is masked before LLM exposure and never persisted unredacted.
- No `.kairos-state`, phase log, readiness report, proposal record, virtual source,
  preparation TTL, mapping TTL, Silver extension TTL, or release evidence is created.

## Full migration roadmap

### Stage 2: complete the strict binding kernel

- **Status (2026-07-27): complete.**
- Incremental SCD1/SCD2 policy reuses the canonical hash contract and requires explicit
  delete, late-arrival, correction, replay, backfill, schema-change, CDC, lookback, and
  total-order facts; no runtime behavior is inferred.
- Current/as-of temporal relationships require explicit overlap, late-parent, validity, and
  change-detection behavior.
- The one-binding-per-source rule is preserved under conformance: every binding document
  selects exactly one source relation or one contracted dbt model. Multiple sources may
  materialize one class only as separate bindings in an explicit conformance group with
  compatible contracts, unique precedence, conflict behavior, and union/dedup policy.
- Complex or grain-changing transformations are direct contracted dbt sources. The compiler
  resolves the ordinary SQL model and authoritative dbt YAML contract, then validates its
  output columns, types, grain, and identity; there is no virtual-source, evidence, or
  synchronization subsystem between the contract and `EntityBinding`.
- Fabric and Databricks capabilities are negotiated and tested, and binding-owned immutable
  facts replace authored preparation/Silver policy authority.

### Stage 3: move all Silver/dbt projection paths to v5

- **Status (2026-07-27): complete.**
- `compile` is the only canonical Silver/dbt generation entry point. Legacy
  `project --target dbt|silver`, internal projector dispatch, target-registry dispatch, and
  `--target all` dispatch reject or omit Silver/dbt before scope resolution or writes.
- `build_compile_plan(...)` produces the canonical immutable `CompilePlan` after
  normalize/shape/materialize and before byte rendering. Check, explain, emit, and optional
  downstream consumers use this same plan; no parallel planning authority remains.
- Bound v5 inputs replace the legacy `DbtInputs` mapping/preparation/extension/contract path
  facade. Aspirational/stub outcomes, preparation artifacts, DQ runtime-result contracts,
  and release evidence are absent from the canonical pipeline.
- Immutable phase boundaries, typed specs, adapter plans, canonical hashing, and deterministic
  renderers are retained. Gold and MDM remain optional consumers of the typed compile plan,
  not required lifecycle phases.

### Stage 4: remove v4 operational subsystems

**Status (2026-07-27): complete.** All inventory waves were deleted leaf-to-root after
production imports reached zero.

The deterministic wave inventory is
`docs/design/stage4-retirement-import-inventory.json`. Its architecture test parses Python
`Import`/`ImportFrom` nodes, records exact importing modules and symbols, verifies obsolete
Click registrations, and fails when a new production edge reaches a retirement module.
Stage 3's cutover is reflected there: legacy `project` Silver/dbt entry points are
closed, compiler plans own Silver generation, and optional Gold/MDM consumers use the typed
compile plan. Every Stage 4 wave is marked `retired`.

1. release evaluator, lifecycle gate, projection readiness, and status;
2. transformation evidence/synchronization and candidate inventories;
3. claim decision, derivation, synchronization, coverage, and registry modules;
4. claim-driven binding/stub and completeness logic;
5. mandatory preparation vocabulary, shapes, templates, binders, specs, and renderers;
6. projection report/session-log persistence and release-baseline scaffold;
7. obsolete CLI commands and their tests.

Removed command registrations include `status`, `lifecycle`, `check-projection`,
`check-release`, `check-claims`, `derive-claims`, `decide-claims`, `migrate-claims`,
`claims-to-silver-ext`, `capture-dbt-contract-evidence`,
`check-transformation-readiness`, `inventory-dbt-candidates`, `migrate-column-iris`,
`reconstruct-dbt-transformation`, and `sync-dbt-contracts`.

Reusable source analysis, ontology loading, reference-model resolution, typed expressions,
immutable policy phases, adapters, deterministic renderers, and optional Gold/MDM projection
remain. Their retention is architectural, not v4 compatibility. There is no v4 compatibility,
dual-format authoring, migration command, or automated migration path.

### Stage 5: simplify the CLI and scaffold

**Status: pending.** Stage 4 removed obsolete operational registrations and assets; the
broader CLI decomposition and lean-scaffold simplification remain Stage 5 work.

- Reduce `cli/main.py` to group setup and command registration; keep new commands in focused
  modules.
- Keep retired lifecycle/status/readiness/claims/release/preparation/contract-sync
  registrations absent while decomposing the remaining CLI.
- Scaffold only v5 directories and authoritative files.
- Remove `.kairos-state`, claims, preparation, planning, release baseline, and evidence
  directories from init/new-repo.
- Update packaging tests to assert the lean scaffold.

### Stage 6: rewrite the skill surface

**Status: complete (2026-07-27).**

Update both `.github/skills/` and `src/kairos_ontology/scaffold/skills/` copies:

- `kairos-flow`: simple inspect/design/bind/compile routing; no persisted phase state.
- `kairos-design-domain`: bounded canonical-slice loop.
- `kairos-design-mapping`: YAML binding and iterative validation loop.
- `kairos-design-silver`: fold essential execution-policy guidance into entity binding or
  retire the separate skill if it has no remaining authority.
- `kairos-develop-dbt-transformation`: ordinary dbt SQL/YAML contract workflow.
- `kairos-execute-project`: become a thin compile skill or retire in favor of compile.
- `kairos-diagnose-status`: report authored inputs and current compile diagnostics only.
- source, discovery, Gold, setup, validation, help, and operations skills: remove claims,
  lifecycle, readiness, preparation, and release-evidence references.

Update both Copilot instruction copies and the kairos-help skill. Use the existing skill
sync mechanism and packaging tests to prevent drift.

### Stage 7: replace the test architecture

**Status: complete (2026-07-27).**

- Retain and adapt phase immutability, mapping AST, runtime semantics, adapter, renderer,
  ontology loader, AI provider, sample privacy, and deterministic artifact tests.
- Replace v4 `acme-hub` authoring fixtures with fresh v5 hubs; do not write migration tests.
- Delete claims/lifecycle/status/readiness/release/preparation/virtual-source scenarios.
- Replace byte baselines only after reviewing the intentional v5 artifact contract.
- Add negative scenario coverage for each non-suppressible safety rule.
- Keep full scenario coverage for projection changes as required by repository convention.

The v4-only claim, preparation/Silver-authority, lifecycle/readiness/release, operational
state, legacy projection-command, migration, and compatibility tests are retired. Retained
compiler phases, binding AST, canonical hash/runtime, adapters/renderers/loaders, privacy,
Gold, MDM, and reference-model behavior now use v5 `EntityBinding`/`CompilePlan` coverage
and the governed v5 fixture. Architecture gates reject test imports of retired modules and
invocations of retired commands.

### Stage 8: documentation and release cleanup

**Status: complete (2026-07-27).** The documentation/release rewrite and automated release
checks are complete. V5 GA remains unpublished pending reviewed publication and resolution
of the known historical DCO caveat.

Final program validation is currently blocked on two release-path defects found during
high-confidence review: the public legacy `project` path can still rebuild Gold/MDM outside
the canonical `CompilePlan`, and the scaffold release workflow can package an empty Power BI
directory after an optional projection failure. Publishing must wait for those defects and
the DCO caveat to be resolved through review.

- Update the v5 design and consolidated DD.
- Rewrite README, CLI help, hub scaffold docs, data-platform consumption docs, and examples.
- Update `CHANGELOG.md` with the intentional authoring break and removed commands.
- Remove superseded v4 instruction guides from active navigation while retaining historical
  design decisions.
- Run the full test suite, scenario suite, lint, packaging checks, and build before the v5
  release.

## Todo dependency map

1. `v5-decision-contract`
2. `v5-binding-schema` depends on `v5-decision-contract`
3. `v5-binding-adapter` depends on `v5-binding-schema`
4. `v5-compiler-kernel` depends on `v5-binding-adapter`
5. `v5-compile-cli` depends on `v5-compiler-kernel`
6. `v5-llm-canonical-loop` depends on `v5-binding-schema`
7. `v5-llm-mapping-loop` depends on `v5-compiler-kernel` and
   `v5-llm-canonical-loop`
8. `v5-first-scenario` depends on `v5-compile-cli` and `v5-llm-mapping-loop`
9. `v5-strict-kernel` depends on `v5-first-scenario`
10. `v5-projection-cutover` depends on `v5-strict-kernel`
11. `v5-retire-legacy` depends on `v5-projection-cutover`
12. `v5-scaffold-skills` depends on `v5-first-scenario` and can progress alongside
    `v5-strict-kernel`
13. `v5-test-replacement` depends on `v5-projection-cutover` and
    `v5-retire-legacy`
14. `v5-docs-release` depends on `v5-scaffold-skills`, `v5-test-replacement`, and
    `v5-retire-legacy`

## Risks and controls

- **Central-file risk:** avoid rewriting `cli/main.py`, `specs.py`, or
  `policy_normalize.py` wholesale. Add the v5 seam first, then trim in tested waves.
- **New dumping-ground risk:** keep `EntityBinding` closed and narrow; reject source schema,
  ontology definitions, arbitrary SQL, report measures, and governance metadata.
- **False safety risk:** never emit review-only executable SQL. Sample checks are evidence,
  not authority.
- **LLM drift risk:** deterministic validators and compiler output remain independent of
  model/provider; mock all provider calls in tests.
- **PII risk:** reuse `_samples.py` redaction before prompt construction; block unredacted
  sample persistence.
- **Scope leakage risk:** one `BuildScope` instance and provenance closure is passed through
  all compiler stages.
- **Layering risk:** keep all new compiler code in `core`; MDM may consume core but core
  never imports MDM.
- **Over-engineering risk:** no proposal store, workflow engine, policy overlay system,
  evidence ledger, runtime-result schema, parity manifest, or persistent cache is included.
  Add only after measured need.
