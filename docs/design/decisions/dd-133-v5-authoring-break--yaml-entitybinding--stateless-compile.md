# DD-133: V5 Authoring Break — YAML EntityBinding + Stateless `compile`

**Status:** Accepted
**Date:** 2026-07-27
**Affects:** new `src/kairos_ontology/core/compiler/`, new
`src/kairos_ontology/cli/compile.py`, existing
`core/projections/dbt/` (reused phases), `kairos-design-domain` +
`kairos-design-mapping` skills, `tests/scenarios/v5-hub/`
**Implementation:** `src/kairos_ontology/core/compiler/`,
`src/kairos_ontology/cli/compile.py`, the lean packaged hub scaffold, and the companion
contract [`dd-133-v5-entity-binding-compile.md`](../dd-133-v5-entity-binding-compile.md).

### Context

The v4 authoring/operating experience accumulated too many overlapping authorities —
claims, mapping TTL, preparation TTL, Silver-extension TTL, transformation contracts,
virtual sources, readiness reports, lifecycle/phase state, and release evidence — layered
on top of an otherwise capable immutable dbt projection pipeline. Authoring a single
canonical entity required editing several TTL authorities and passing multiple gates.

V5 collapses this to **one** authoring authority and **one** execution path. Because this
is a clean break, **no v4 hub compatibility, dual-format authoring, migration command, or
upgrade path is provided** — existing client hubs are **rebuilt from fresh** as v5 hubs.

### Decision

1. **One authoring authority:** a concise, closed **YAML `EntityBinding`** is the single
   source-to-canonical execution authority. OWL/TTL remains authoritative for the canonical
   Silver model; source vocabularies remain authoritative for Bronze; hand-authored dbt
   remains authoritative for complex relational transforms. The binding *references* these;
   it never copies or replaces them, and it is validated by a packaged JSON Schema then
   converted directly into frozen dataclasses and the existing graph-free mapping AST —
   **never** serialized to intermediate RDF.
2. **One execution path:** a **stateless `compile`** command with mutually exclusive
   `--check` / `--explain` / `--emit` modes. `--check`/`--explain` never write hub files;
   `--emit` builds a complete in-memory plan then writes atomically via same-volume
   stage-then-swap over a manifest-owned target subtree. Kairos persists **no** lifecycle,
   readiness, proposal, claim, or verification state.
3. **Reuse, don't rebuild:** the new `core/compiler/` package adapts the existing immutable
   `bind → normalize → shape → materialize → render` dbt phases via graph-free authored
   facts — there is no second renderer. `core/compiler` must never import
   `kairos_ontology.mdm` (layering rule).
4. **Minimal non-suppressible safety kernel** gates emission; focused data-quality checks
   are evidence emitted as ordinary dbt tests, not a Kairos runtime-result contract.
5. **Superseded-for-the-v5-path at acceptance** (then deprecated-but-operative, not
   deleted from decision history): the
   lifecycle/readiness/release, claims/synchronization, and mandatory-preparation/
   virtual-source/contract-identity decisions listed in the companion doc §9. Their v4
   command paths were to keep working until retirement. Stage 4 subsequently removed them
   under DD-135/DD-136 and the retirement inventory. DD-107's graph-free scalar AST
   is **retained and reused**; only its RDF-authored, preparation-routed acquisition path is
   superseded.
6. **Stage 2 closed contract:** `load` is discriminated between full refresh and complete
   incremental SCD1/SCD2 policy; relationships are discriminated between non-temporal,
   current, and as-of policy; multi-source materialization requires explicit conformance,
   precedence, conflict, and union/dedup policy; and `source.dbtModel` carries required SQL
   and authoritative dbt-contract paths. All values load into frozen types. Unknown fields,
   duplicate YAML keys, incomplete variants, and ambiguous CDC operation values fail with
   source-located diagnostics. No v4 shape is accepted.

The full normative contract — hub layout, closed YAML schema, scalar-expression grammar,
safety kernel, atomic-emission contract, scope/provenance rules, and a canonical example —
lives in the companion doc.

### Rationale

- A single closed binding removes the multi-authority coordination cost and the classes of
  bug that came from claims/preparation/virtual-source drift, while the closed grammar and
  allow-list keep it from becoming a new dumping ground.
- Reusing the already-immutable, already-graph-free mapping AST (`AuthoredExpressionFact` is
  a "graph-free structural copy") means v5 inherits the tested typed/deterministic rendering
  behavior instead of forking a second pipeline.
- Statelessness makes builds reproducible and eliminates the readiness/lifecycle/evidence
  persistence that coupled authoring to operational state.
- A clean break (no compatibility) is acceptable because client hubs are rebuilt from fresh,
  so migration machinery would be pure cost.

### Consequences

- The complete strict kernel is implemented, including
  incremental/SCD canonical hashing, temporal relationships, explicit conformance, adapter
  capabilities, and direct contracted dbt SQL/YAML sources.
- The one-binding-per-source rule remains: each document selects one relation or one
  contracted dbt model. Multi-source materialization uses separate bindings with one explicit,
  deterministic conformance contract.
- Stage 3 establishes immutable `CompilePlan` as the sole canonical Silver/dbt planning
  authority and `compile` as the only generation path. Optional Gold/MDM consumers reuse the
  typed plan. Immutable phases, typed policy/expression structures, adapters, canonical
  hashing, and deterministic renderers are retained.
- Stage 4 retired every inventoried v4 operational wave and its commands/tests/assets; it did
  not add v4 compatibility, dual authoring, or migration. The earlier
  deprecated-but-operative state is preserved above as cutover history.
- The adapter seam into the existing phases was de-risked by `v5-seam-spike` before the YAML
  schema was locked.
- Skills become thin LLM loops over deterministic primitives — no second proposal DB or
  session-state subsystem is introduced.
- The lean scaffold, active documentation, CLI navigation, downstream-consumption guidance,
  and managed skills describe the implemented clean-break architecture.
- Documentation consolidation is not v5 GA publication; version/tag/assets and publication
  verification remain a separate maintainer release operation.
