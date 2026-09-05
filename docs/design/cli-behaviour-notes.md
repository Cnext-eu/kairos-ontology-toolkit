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
| `emit-gold DOMAIN [--confirm-emit]` | Project the domain's Gold/PowerBI product (TMDL, PBIP, DAX, ERD) from the same `CompilePlan` and atomically write it to the fixed `ontology-hub-publish/powerbi` (not configurable, and never inside the dbt publish tree). Without `--confirm-emit`, reports what would be written without touching disk. Requires an authored Gold profile and, for Direct Lake/Databricks products, the matching `gold.direct_lake_connection`/`gold.databricks_connection` block in `kairos.yaml`. |

The modes are mutually exclusive. The compiler reads the adapter from `kairos.yaml`;
supported values are `fabric-warehouse` and `databricks`. `fabric` still resolves, to
`fabric-warehouse`, with a deprecation warning; `fabric-lakehouse` is recognised and
rejected rather than compiled as T-SQL. There is no default (DD-215).

`project` remains registered for retained non-compiler projections. Its `dbt` and `silver`
targets reject use and direct authors to `compile`. Its `powerbi`/`gold` targets direct
authors to `compile --check|--explain` then `emit-gold --confirm-emit`; `mdm-profile`
remains Python-API-only (`kairos_ontology.mdm.profile_projector.generate_mdm_profile_from_compile_plan`).
Gold and MDM are typed downstream consumers of a compiler-produced immutable `CompilePlan`,
never graph-authority project targets. `project --target all` excludes them.
`scaffold-mapping`, `scaffold-silver-ext`, `validate-mapping`, and
`validate-silver-ext` remain only as explicitly legacy, non-authoritative utilities.

### ERD projections: three different diagrams, three different purposes

| Diagram | Command | Output | Scope | Diagram type |
|---|---|---|---|---|
| Canonical/full ERD | `project --target erd` (or `--target all`) | `ontology-hub-publish/architecture/erd/<domain>-erd.mmd`, one file per domain | Every `owl:Class`/`owl:ObjectProperty` in the ontology graph, regardless of `EntityBinding`/compile-plan coverage (DD-209) | Mermaid `classDiagram` — includes inheritance (`rdfs:subClassOf`) as `Superclass <|-- Subclass` edges (DD-212) |
| Bound per-domain ERD | `compile DOMAIN --emit` (Silver) / `emit-gold DOMAIN --confirm-emit` (Gold) | `medallion/dbt/docs/diagrams/<domain>/<domain>-erd.mmd` / `powerbi/<domain>/<domain>-gold-erd.mmd` | Only classes/relationships actually bound and compiled for that domain | Mermaid `erDiagram` — physical dbt tables have no inheritance concept |
| Bound hub-wide master ERD | automatic, after any `compile --emit` / `emit-gold --confirm-emit` | `medallion/dbt/docs/diagrams/master-erd.mmd` / `powerbi/master-gold-erd.mmd` | Merges every domain's bound ERD emitted so far anywhere in the hub (DD-011, reconnected by DD-211) | Mermaid `erDiagram`, same as the per-domain bound ERDs it merges |

The canonical ERD is the only one of the three with no binding dependency — it is where an
author sees the ontology's actual modeled shape, including classes and relationships not yet
bound to any source. It accepts an optional, plumbing-only `{domain}-erd-ext.ttl` overlay file
under `model/extensions/` (mirroring the `ddd` target's `{domain}-ddd-ext.ttl` convention); no
packaged hint vocabulary exists yet, so an absent overlay leaves output unchanged (DD-212).

The master ERDs are pure disk-scan-and-merge over whatever per-domain bound diagrams already
exist under the shared publish root, so they accumulate correctly across separate,
single-domain `compile`/`emit-gold` invocations — running `compile party --emit` in a hub that
already has a `billing` domain emitted updates the master ERD to include both, not just `party`.

## Retained root commands

| Category | Commands |
|---|---|
| Compile/project | `compile`, `project`, `mdm-validate` |
| Author bindings | `scaffold-binding`, `scaffold-system`, `scaffold-staging`, `propose-relationships` |
| Validate | `validate`, `validate-dbt`, `validate-dbt-contracts`, `catalog-test`, `validate-mapping`, `validate-silver-ext`, `suggest-shapes` |
| Source/discovery | `import-source`, `import-flatfile`, `import-tmdl`, `extract-schema`, `show-source-schema`, `source-privacy`, `analyse-sources`, `audit-silver-samples`, `audit-column-coverage`, `propose-alignment`, `build-glossary`, `list-patterns`, `discovery-status`, `discovery-conformance`, `register-concept` |
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
| Validates | `integration/transforms/dbt/models/` and `integration/transforms/dbt/seeds/` — the **hand-authored** intermediate layer | `ontology-hub-publish/medallion/dbt` — the **emitted** Silver project |
| Needs dbt installed | No | Yes (except `--structural-only`) |
| Needs an adapter | No | Yes — defaults to the hub's `adapter:`, override with `--platform` |
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

Seed-aware since issue #586 (stage b). A hub whose only authored transform content is a seed
CSV is linted rather than reported as having no transforms at all — transforms count as
present when either `models/` or an authored `seeds/*.csv` exists. Three seed findings join
the same `findings` list:

| Code | Severity | Meaning |
|---|---|---|
| `dbt-contract.seed-docs-unmatched` | warning | A `seeds/<name>.yml` lists a `seeds[].name` matching no authored seed CSV stem — a typo or stale docs after a rename. |
| `dbt-contract.seed-unreadable` | warning | A seed CSV cannot be read or is not UTF-8 (the classic cp1252 Excel export), or its header row is empty. |
| `dbt-contract.seed-model-collision` | error | A seed stem collides with an authored model stem. |

The collision is an **error**, not a warning, unlike the other two: dbt resolves `ref()` in a
single resource namespace, so two resources with one name make the generated project fail to
parse outright, and the dbt bundle now hard-fails the same case. A lint that called it
advisory would disagree with the build.

Seed column-docs YAML is dbt's plain `seeds:` properties form and deliberately carries no
`meta.kairos` — a seed is not a bindable virtual source, so it is never contract-parsed.

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

Join columns are matched against the parent's `identity.sourceKey` in three
tiers (DD-220):

* **tier 0** -- a child column the author declared `purpose: relationship`
  (DD-139), by name equality. This is the author stating that the column is a
  foreign key, and it is the one tier exempt from the identity exclusion below;
* **tier 1** -- exact normalized name equality over the child's other authored
  columns, the same high-precision rule as `scaffold-binding`'s cross-source FK
  scanner, **excluding any column that constitutes the child's entire
  identity**;
* **tier 2** -- measured value containment from the DD-189 source profile,
  within one source system.

The tier-1 exclusion is what stops a hub with one uniform surrogate identity
name from proposing `source_record_id = source_record_id`, joining a row to
itself across two relations. It is narrower than "exclude every
`identity.sourceKey` column": a line-item child keyed `[order_id, line_no]`
still contributes `order_id`, which genuinely is the FK. What it costs is a
1:1 extension or subtype table keyed by its parent's key -- indistinguishable
by name from the self-join, and now sentinelled. Declare the column
`purpose: relationship` to resolve it via tier 0.

Tier 0 matches by name too, never positionally: a child routinely carries
several `purpose: relationship` columns aimed at different parents, so pairing
the only carrier with the only parent key would emit a confidently wrong join.
A declared carrier that names no parent key is surfaced as a `join_candidates`
hint on the unresolved proposal instead.

A relationship the child binding **already authors** is not re-proposed
(DD-220). Matching is on `(property, target)`, compared by local name so an
authored qname target matches a parent whose `target.class` is the full URI.
Suppressed pairs are counted in the text header and listed under
`already_authored` in JSON -- the local-name comparison is deliberately
tolerant, so what was withheld has to stay reviewable. Skipping rather than
re-rendering is the point: `to_yaml` hard-codes `cardinality`, `mode`,
`missingParent` and `ambiguousParent`, so a re-rendered entry pasted back over
an authored one silently replaces deliberate policy (a hub's
`missingParent: null`) with the default (`error`).

A cross-domain parent additionally gets a draft `externalReference` block whose
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

## `register-concept`

Registers a source-discovered concept the archetype catalog does not contain (issue #505
Layer B, DD-162).

```
kairos-ontology register-concept --uri <IRI> --label <label> \
  --source-system <system> --source-evidence <table[.column]> ... \
  --rationale <text> [--domain <id> ...] [--decided-by user|ai|autopilot] \
  [--confidence <0.0-1.0>] [--needs-confirmation] [--reference <text> ...] \
  [--force] [--archetype <id>] [--refmodels-root <path>] [--format json|yaml]
```

Discovery only ever iterates the archetype catalog, so a concept that exists in the source data
and nowhere in the catalog could not be judged, could not carry a `likely_domains` tag, never
reached `design-landscape`, and never became an authored domain. This command records it
hub-side, in `integration/discovery/registered-concepts.yaml`, which
`discovery-conformance build` mirrors into the artifact's `registered_concepts` list.

* That list is a **sibling** of `core_concepts`, never merged into it — `validate_artifact`'s
  coverage/identity checks require every `core_concepts` entry to be a real catalog concept, and
  `concept_set_hash` staleness would fire on every registration. Registering a concept must not
  make the archetype look wrong. A URI in both is an error.
* A URI already in the archetype catalog is **rejected**: it belongs in `core_concepts` with a
  real discovery judgment, not routed around the coverage checks.
* Registered concepts always carry tier `optional`, and are counted separately from the
  archetype scorecard so conformance percentages stay comparable across hubs.
* `--source-evidence` and `--rationale` are mandatory.
* An `ai`/`autopilot` registration without `--confidence`, or with `--needs-confirmation`,
  blocks `compile`/`validate` until a human confirms it (DD-148) — adding a concept the
  blueprint deliberately omitted is a larger authority than judging one it included.
* Surfaced afterwards by `design-landscape` (with `discovery.registered: true`) and by
  `kairos-ontology next` as `model-registered-concept`. Registration records that the concept
  belongs; authoring the class is still a domain-design decision.

## `discovery-conformance`

Subcommands supporting the Core Concepts Conformance phase (Phase 2.5, DD-090) of
`kairos-design-discovery`: `list-archetypes`, `load`, `judgments-template`, `build`, `validate`.
`list-archetypes`/`load`/`validate` are read-only/machine-output helpers (`--format json|yaml`,
default `json`); `judgments-template` and `build` write files.

```
kairos-ontology discovery-conformance judgments-template --archetype <id> \
  [--mode interactive|fleet] [--output <path>] [--overwrite] [--no-source-evidence] \
  [--format json|yaml] [--refmodels-root <path>]

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

### Source-evidence-aware judgments (issue #507)

Run from **inside the hub**, `judgments-template` joins the hub's own Stage-1 source analysis
(`integration/sources/_analysis/*-alignment.yaml`, falling back to `*-affinity.yaml` via a
concept's `likely_domains`) to the concept list:

* every concept with evidence gains a read-only `source_evidence` block naming the actual
  `<system>.<table>` values;
* an **`optional`-tier** concept with evidence is pre-filled `outcome: conforms`, with the
  evidence written into its `rationale` — *if data exists and the concept is optional, model it*.
  `required`/`recommended` concepts keep their sentinel: they are in scope regardless of what the
  sources happen to contain, so pre-filling them would replace a judgment with a tautology.

`--no-source-evidence` opts out (running outside a hub does the same thing implicitly).

`build` then **rejects** an `optional`-tier `not-applicable` that contradicts source evidence
unless the entry records an explicit, non-sentinel `rationale`. `validate` reports the same
situation as a stderr warning and never fails — `build` is new authoring, where overriding
deterministic evidence should be an explained decision, while `validate` also re-reads artifacts
written long ago, where the same rule would be an unconvergeable gate on work already done.

`summarize` gains `by_evidence` (`blueprint` vs `data-driven`) in its payload. This is
deliberately *not* part of the artifact's own `scorecard`: `validate_artifact` recomputes that
scorecard and compares it for equality against the stored one, so a new key there would fail
every artifact already on disk. No artifact schema change is involved in any of this.

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

## Sample redaction is opt-in (`--redact-pii`)

`extract-schema`, `import-source` and `import-flatfile` write sample values **as-is by default**.
Pass `--redact-pii` to apply the `redact-detected-pii` policy. See DD-214 for why the default
flipped: the detector's false positives destroyed the sample evidence binding design reads, while
protecting nothing, because the real values were present in a sibling artifact regardless.

```
kairos-ontology extract-schema  ... [--redact-pii] [--no-redact-pii]
kairos-ontology import-source   ... [--redact-pii]
kairos-ontology import-flatfile ... [--redact-pii]
```

- `--no-redact-pii` (`extract-schema` only) is a **deprecated no-op**, kept because it shipped as a
  real flag in 5.15.0rc12 and asks for what is now the default.
- `--emit-seed` **requires** `--redact-pii`: seed CSVs are not gitignored, and the emitted copy under
  `ontology-hub-publish/medallion/dbt/` is explicitly un-ignored and packaged into a GitHub Release.
- Artifacts record the policy that actually ran (`sample_privacy.policy: none`), and carry no policy
  *version* when no policy ran.

What this changes elsewhere:

- Committed artifacts under `integration/sources/**` may contain raw client PII and enter git history.
- `analyse-sources` **reports and proceeds** rather than refusing, so sample values can reach the
  configured AI provider. It still reports paths and kinds only, never a value.
- `source-privacy` treats findings in artifacts declaring `policy: none` as *acknowledged* rather
  than failures, so an opted-out hub is not permanently red. A missing `sample_privacy` block is not
  treated as consent.
- `audit-column-coverage` still redacts its sample value unconditionally, because that value is
  printed to stdout and `--format json`.

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
