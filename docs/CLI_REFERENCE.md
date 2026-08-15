# CLI Reference

This is the exact retained v5 root command surface. `kairos-ontology --help` is the
executable authority.

## Machine output contract

Every command that emits a machine-readable payload (JSON or YAML via `--format`)
follows one contract, enforced by `_emit` in `cli/shared.py`:

* **Diagnostics go to stderr.** Progress messages, warnings, errors, and human-readable
  hints are written with `click.echo(..., err=True)`.
* **Payload goes to stdout.** The serialized JSON/YAML is the *only* content on stdout,
  so `kairos-ontology <cmd> --format json | jq .` works without stripping.
* **`2>&1` defeats this by design.** Merging stderr into stdout (`2>&1`) interleaves
  diagnostics with the payload and corrupts it — this is intentional, not a bug. If you
  need clean machine output, do not redirect stderr into stdout; let diagnostics fall
  through to the terminal or capture them separately.
* **Explicit `--format json | jq .` is the canonical way to consume machine output.**
  Commands without a `--format` option (e.g. `validate`) print human-readable text to
  stdout unconditionally and are not intended for piping to `jq`.

### `validate --format` is `--report-format`

`validate` is the one exception to be aware of: its `--format` flag is an alias for
`--report-format` and selects the *report file* format, not the stdout stream format.
`validate` prints human-readable text to stdout regardless of `--format`. This is by
design — `validate` is an advisory command, not a machine-output command.

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
| Author bindings | `scaffold-binding`, `scaffold-system`, `scaffold-staging`, `propose-relationships` |
| Validate | `validate`, `validate-dbt`, `validate-dbt-contracts`, `catalog-test`, `validate-mapping`, `validate-silver-ext`, `suggest-shapes` |
| Source/discovery | `import-source`, `import-flatfile`, `import-tmdl`, `extract-schema`, `show-source-schema`, `source-privacy`, `analyse-sources`, `audit-silver-samples`, `audit-column-coverage`, `propose-alignment`, `build-glossary`, `list-patterns`, `discovery-status`, `discovery-conformance` |
| Inspect/report | `resolve-ontology`, `show-class-inventory`, `list-class-properties`, `fit-report`, `inverse-scan`, `plan-sources`, `explain-term`, `coverage-report`, `field-mapping-report`, `generate-inventory`, `check-inventory`, `domain-coverage`, `draft-model-report`, `next`, `design-landscape`, `guard-scope`, `check-ai-config`, `suggest-type` |
| Legacy scaffold helpers | `scaffold-mapping`, `scaffold-silver-ext` |
| Setup/update | `init`, `new-repo`, `migrate`, `init-dataplatform`, `scaffold-domain`, `update`, `update-refmodels` |

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

## `validate-dbt-contracts` vs `validate-dbt`

Two different trees, two different lifecycle stages. Neither subsumes the other.

| | `validate-dbt-contracts` | `validate-dbt` |
|---|---|---|
| Validates | `integration/transforms/dbt/models/` — the **hand-authored** intermediate layer | `ontology-hub-publish/medallion/dbt` — the **emitted** Silver project |
| Needs dbt installed | No | Yes (except `--structural-only`) |
| Needs an adapter | No | Yes (`--platform fabric\|databricks`) |
| Runs at | Stage 4, while authoring `int_*` models, *before* binding them | Stage 5, after `compile --emit` |
| Owning skill | `kairos-develop-dbt-transformation` | `kairos-execute-validate` |

```
kairos-ontology validate-dbt-contracts [--format json|yaml]
```

Offline lint of every `meta.kairos` block (issue #504). Errors: incomplete `meta.kairos`,
a `grain_key` naming a column the contract does not declare, missing
`config.contract.enforced: true`, a `target_class` that does not resolve in the hub's
ontology import closure, a `virtual_source_iri` claimed by more than one model, and any
unreplaced `<CONFIRM_...>` scaffold sentinel. Warnings (never blocking): a `stg_*` model
that declares a `meta.kairos` block, an `int_*` model that lacks one, and a contracted model
no `EntityBinding` selects yet.

`virtual_source_iri` uniqueness is the authoritative hub-wide check. `compile --check` also
reports `dbt-source.virtual-source-duplicate`, but only within the domain being compiled —
it never loads peer domains' bindings.

## `propose-relationships`

Derives candidate `relationships:` entries for every authored `EntityBinding`
(issue #493, DD-160). Advisory: nothing is written and it always exits 0.

```
kairos-ontology propose-relationships [--domain <d>] [--accelerator <name>]
  [--ref-models-dir <path>] [--no-unresolved] [--format text|json]
```

The object property is **read, not inferred**. Two deterministic sources feed it:

* the accelerator blueprint's `cross_domain_relationships`, which declares each
  bridge with an exact `property_uri` plus its domain/range class URIs (until now
  consumed only by the legacy v2 report template, never by the v5 binding path);
* the hub's own `owl:ObjectProperty` declarations, resolved through the DD-103
  canonical loader under the `rdfs` profile, so a relationship inherited from an
  imported superclass counts too. This is also what makes the command useful on a
  hub with no accelerator installed.

Join columns are matched by exact normalized name equality between the child
binding's authored columns and the parent's `identity.sourceKey` -- the same
high-precision tier-1 rule as `scaffold-binding`'s cross-source FK scanner. A
cross-domain parent additionally gets a draft `externalReference` block whose
`key[].column` is the parent's materialized output column and whose `name` is the
parent's generated dbt model name (derived from the target class, per DD-138).

Nothing is guessed. Anything not derivable is emitted as `<CONFIRM_JOIN_COLUMN>`
or `<CONFIRM_KEY_TYPE>`. Each proposal reports `endpoint_match`: `uri` (exact
class-URI equality) or `local-name` (the hub authored its own class in its own
namespace) -- confirm a `local-name` match really is the same concept before
accepting it. `--no-unresolved` hides proposals whose join columns are sentinels.

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

## `discovery-conformance`

Subcommands supporting the Core Concepts Conformance phase (Phase 2.5, DD-090) of
`kairos-design-discovery`: `list-archetypes`, `load`, `judgments-template`, `build`, `validate`.
`list-archetypes`/`load`/`validate` are read-only/machine-output helpers (`--format json|yaml`,
default `json`); `judgments-template` and `build` write files.

```
kairos-ontology discovery-conformance judgments-template --archetype <id> \
  [--mode interactive|fleet] [--output <path>] [--overwrite] [--format json|yaml] \
  [--refmodels-root <path>]

kairos-ontology discovery-conformance build --archetype <id> \
  --judgments-file <path> [--output <path>] [--validate/--no-validate] \
  [--allow-unresolved] [--domain <id> ...] [--refmodels-root <path>]
```

`build --judgments-file` is the only hand-authored input in this phase; every other command
(and `--judgments-file`'s own `uri`/`label`/`tier` per concept) derives from the reference-models
archetype catalog. Before this toolkit release, its schema had to be learned by running a failed
`build` -- three requirements were each discoverable only that way (issue #410):

* `label` is required.
* `label` must exactly equal the catalog label for that `uri`.
* `confidence` must be a float between `0.0` and `1.0` -- not the words `high`/`medium`/`low`
  (that scale belongs to a different, unrelated field: extraction `visual_evidence.confidence`
  in `_extractions/*.yaml`; do not reuse it here).

`judgments-template --archetype <id>` scaffolds the file instead of requiring it to be
hand-written or hand-scripted: it emits one `core_concepts` entry per archetype concept,
pre-filled with `uri`/`label`/`tier` from the catalog, and an `<CONFIRM_...>` sentinel
(detectable via `core.hub_utils.is_scaffold_placeholder_text`, the same family
`scaffold-binding`/`scaffold-staging` already use) in every field that still needs a real
business judgment. Writes to stdout by default; `--output` writes to a file and refuses to
overwrite an existing one without `--overwrite` (`scaffold-mapping`'s convention).

`build` now also makes `label`/`tier` **optional** in `--judgments-file`: when a concept's entry
omits either, `build` derives it from the resolved archetype's own catalog for that `uri` before
assembling the artifact. A concept's entry that supplies a *wrong* `label`/`tier` still fails
validation exactly as before -- only a missing/blank value is derived, never a present one
silently corrected.

`--judgments-file`'s full per-concept shape: `uri` (required), `outcome` (required, one of the
codes from `list-archetypes`' `outcome_codes`), `label`/`tier` (optional, derived when absent),
`rename_to`/`deviation_reason` (required together with the matching `outcome`), `confidence`
(optional float `0.0`-`1.0`), `rationale` (optional string), `references` (optional list of
strings), `needs_confirmation` (optional bool, default `false`), `decided_by` (`"user"` or
`"ai"`), `likely_domains` (optional list of lowercase domain-id strings; empty/absent means
cross-cutting -- in scope for every domain).

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
