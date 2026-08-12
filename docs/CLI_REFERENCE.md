# CLI Reference

This is the exact retained v5 root command surface. `kairos-ontology --help` is the
executable authority.

## Canonical generation

| Command | Purpose |
|---|---|
| `compile DOMAIN --check` | Build and validate a `CompilePlan` without writing |
| `compile DOMAIN --explain [--format text\|json]` | Explain that plan without writing |
| `compile DOMAIN --emit` | Atomically render manifest-owned dbt artifacts to the fixed `ontology-hub-publish/medallion/dbt` (not configurable) |

The modes are mutually exclusive. The compiler reads the adapter from `kairos.yaml`;
supported values are `fabric` and `databricks`.

`project` remains registered for retained non-compiler projections. Its `dbt`, `silver`,
`powerbi`/`gold`, and `mdm-profile` targets reject use and direct authors to `compile`;
Gold and MDM are typed downstream consumers of a compiler-produced immutable `CompilePlan`,
never graph-authority project targets. `project --target all` excludes them.
`scaffold-mapping`, `scaffold-silver-ext`, `validate-mapping`, and
`validate-silver-ext` remain only as explicitly legacy, non-authoritative utilities.

## Retained root commands

| Category | Commands |
|---|---|
| Compile/project | `compile`, `project`, `mdm-validate` |
| Author bindings | `scaffold-binding`, `scaffold-system` |
| Validate | `validate`, `validate-dbt`, `catalog-test`, `validate-mapping`, `validate-silver-ext`, `suggest-shapes` |
| Source/discovery | `import-source`, `import-flatfile`, `import-tmdl`, `show-source-schema`, `source-privacy`, `analyse-sources`, `audit-silver-samples`, `audit-column-coverage`, `propose-alignment`, `build-glossary`, `discovery-status`, `discovery-conformance` |
| Inspect/report | `resolve-ontology`, `show-class-inventory`, `list-class-properties`, `fit-report`, `explain-term`, `coverage-report`, `field-mapping-report`, `generate-inventory`, `check-inventory`, `draft-model-report`, `next`, `design-landscape` |
| Legacy scaffold helpers | `scaffold-mapping`, `scaffold-silver-ext` |
| Setup/update | `init`, `new-repo`, `migrate`, `init-dataplatform`, `update`, `update-refmodels` |

`migrate` changes an older folder layout; it does **not** convert v4 authoring to v5.

## `scaffold-binding`

Writes a first-draft v5 `EntityBinding` YAML for one Bronze source table (authoring one is
otherwise 100% manual). Reuses DD-144 accelerator-direct targeting (no local subclass is
minted), DD-139 `technicalFields:` for unmapped key/FK-shaped columns, and `fit-report`'s
class/property resolution; never mints a decorative local property for a column with no real
match (C2) -- such columns are reported as orphans.

```
kairos-ontology scaffold-binding --system <system> --table <table> \
  --archetype {passthrough,single-source-master,merged-master,event-stream,line-item-child} \
  [--target-class <IRI-or-qname>] [--domain <domain>] [--from-binding <path>] \
  [--out <path>] [--force]

kairos-ontology scaffold-binding --list-unscaffolded --system <system>
kairos-ontology scaffold-binding --list-archetypes
```

* `passthrough` (tier `passthrough`): fully automatic and ready to `compile --check` unedited
  -- grain/identity are derived from Bronze metadata (declared primary key, or the highest
  `distinct_count` non-nullable column), and a conservative dbt staging model is written to
  `integration/transforms/dbt/models/intermediate/<domain>/stg_<system>__<table>.sql`.
* `single-source-master`, `merged-master`, `event-stream`, `line-item-child` (tier `canonical`):
  write a **skeleton**. `grain.columns`, `identity.sourceKey`, and (`merged-master` only) the
  `conformance:` survivorship policy carry irreducible modeling judgement and are always
  written as obviously-invalid `<CONFIRM_...>` placeholders -- `compile --check` rejects them
  until a human supplies the real answer. `line-item-child` additionally scaffolds one
  heavily-commented DD-138 `externalReference` relationship as a worked example.
* `--from-binding <path>` seeds a `merged-master` skeleton's `fields:` from an existing
  `passthrough` binding (the promotion path for a tier-1 table that later needs to join a
  multi-source merge); grain/identity/conformance still require confirmation.
* If `model/ontologies/<domain>.ttl` does not exist yet, it is generated as a
  machine-managed stub (`owl:Ontology` + one `owl:imports` for the accelerator module that
  owns `--target-class`, zero local classes); if it already exists, only a missing
  `owl:imports` is appended -- every other line is left untouched.
* `--list-unscaffolded --system <system>` is a read-only report of tables under
  `integration/sources/<system>/` with no `EntityBinding` yet (any tier).

## `scaffold-system`

Batch entry point that composes `scaffold-binding`, `propose-alignment` evidence, and
`compile --check` across every table in `integration/sources/<system>/` in one pass, producing
a single review report instead of one-table-at-a-time `scaffold-binding` calls.

```
kairos-ontology scaffold-system --system <system> [--accelerator <name>] [--dry-run]
  [--format text|json] [--limit N]
```

For every table with no `EntityBinding` yet:

* Looks up that table's `propose-alignment` evidence (`<domain>-alignment.yaml` under
  `integration/sources/_analysis/`) and re-resolves its `ref_class` (a bare accelerator class
  name) to a full class URI. A table with no alignment evidence, or whose `ref_class` no longer
  resolves, is **declined** -- a `--target-class` is never guessed.
* Applies a first-cut "mechanical passthrough candidate" heuristic: the alignment's
  `ref_class_confidence` must clear a floor, and no other table in the same alignment run may
  claim the same `ref_class` (a multi-source-merge signal that calls for a `merged-master`
  design instead). This is a narrow heuristic, not a sophisticated classifier -- override it by
  hand with plain `scaffold-binding` when it declines a table that is actually fine.
* Scaffolds every remaining candidate with the `passthrough` archetype (`run_scaffold_binding`),
  then runs `compile --check` once per domain touched and attributes diagnostics back to the
  binding that produced them.

The report lists every table's outcome: scaffolded, or declined with one of
`already-covered`, `no-alignment-evidence`, `ambiguous-class`/`ambiguous-domain`,
`non-mechanical`, or `scaffold-failed`, plus any compile diagnostics. `--format json` is always
complete; `--format text` (default) caps the declined rows shown per reason at `--limit` (default
20; `0` = unlimited) and states how many were omitted.

`--dry-run` computes and reports the same outcomes without writing any binding, dbt staging
model, or ontology stub -- and (since nothing was written) skips the `compile --check` step,
noting so in the report. Running `scaffold-system` again after a real run is safe: every
previously-scaffolded table reports as `already-covered`.

## `design-landscape`

Read-only, deterministic synthesis report: joins several already-existing evidence signals
**by accelerator class** so an author can see, before doing any design work, which classes
have real multi-source coverage and confirmed business demand versus which have none.

```
kairos-ontology design-landscape [--accelerator <name>] [--domain <domain>] [--format text|json]
```

For every class in the activated accelerator module(s) that at least one `propose-alignment`
table, `discovery-conformance` entry, or existing `EntityBinding` references, it joins:

* **Source coverage** -- `fit-report`'s set-difference logic, generalized from one table to
  every `<system>.<table>` already recorded under `integration/sources/_analysis/*-alignment.yaml`.
* **Business-discovery demand** -- the committed `integration/discovery/core-concepts-conformance.yaml`
  artifact (DD-090); `conforms`/`conforms-with-rename` count as *confirmed* demand, `partial`/
  `deviates` still count as real evidence, and `not-applicable` (an SME explicitly said "we
  don't need this") never counts as demand.
* **BI/report weight** -- `import-tmdl`'s Concept Mapping YAML output
  (`integration/discovery/bi/**/*-concept-mapping.yaml`; the legacy `integration/sources/**`
  location is still read for back-compat), read only for rows where a modeler has
  already filled in `reference_model_match`. **Advisory only, never fact**: this evidence is
  always reported in its own structurally separate `bi_weight` field and may only nudge a
  class's rank within the `demanded-but-unbound` backlog -- it never contributes to a class's
  classification, its `bound` state, or its `discovery_demand`.
* **Current binding state** -- existing `EntityBinding`s' `target.class`/`metadata.tier`,
  resolved through the binding's own domain-ontology closure (including a local
  `rdfs:subClassOf` accelerator ancestor, DD-144's normal authoring pattern).

Each in-scope class is classified into exactly one of: `canonical-candidate` (multi-source +
confirmed demand), `passthrough-candidate` (single-source, mechanical), `demanded-but-unbound`
(real backlog, ranked by confirmed-demand then source count then BI weight), `bound-but-undemanded`,
or `no-evidence`. A class with genuinely zero evidence anywhere that is still in scope (e.g. an
explicit `not-applicable` discovery outcome) is reported as `no-evidence`, never silently
dropped.

Deterministic aggregation only -- no LLM calls, no raw TTL text reads (DD-103). This is the
"0a" minimal cut: a flat, per-class report. It does not attempt domain-clustering/regrouping
suggestions or an LLM narrative pass.

## Removed commands

The following commands do not exist and must not appear in active procedures:

`status`, `lifecycle`, `check-projection`, `check-release`, `check-claims`,
`derive-claims`, `decide-claims`, `migrate-claims`, `claims-to-silver-ext`,
`capture-dbt-contract-evidence`, `check-transformation-readiness`,
`inventory-dbt-candidates`, `migrate-column-iris`, `reconstruct-dbt-transformation`,
and `sync-dbt-contracts`.

Use `compile --check` for compiler safety and `compile --explain` for plan diagnostics.
Neither is a runtime, deployment, or release-certification claim.

## Unreleased commit testing

`update --test-ref BRANCH-OR-SHA` resolves an immutable commit and saves the exact prior
dependency source. `update --restore` restores it. These options are mutually exclusive
with `--upgrade` and do not publish a release.
