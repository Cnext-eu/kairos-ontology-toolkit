# DD-140: Canonical Emit Layout and dbt-Package Topology

**Status:** Accepted
**Date:** 2026-07-28
**Affects:** `compile --emit`, scaffold `output/` slots, dbt project/package generation,
manifest ownership, `.gitignore`, downstream dataplatform consumption, and cross-domain refs
**Implementation:** Accepted. `--emit` becomes projection-aware and targets the scaffolded
slots; the dbt projection materializes into a single canonical medallion project with per-domain
manifest ownership so stateless `compile <domain>` replaces only the files it owns.

### Context

V5 currently emits a domain-centric tree under `output/<domain>/`, while scaffolded hub layouts
reserve projection-aware slots such as `output/medallion/dbt`, `output/medallion/powerbi`,
`output/neo4j`, and `output/azure-search`. Maintainers need to decide whether canonical emit should
follow those projection slots or continue to own a domain subtree.

The dbt topology is coupled to this layout. A unified dbt project can make cross-domain `ref()`
wiring reachable inside one project graph, while standalone-per-domain dbt projects keep domain
emission isolated but require package dependencies or external contracts for references. This
affects whether DD-138 can ever generate physical cross-domain `ref()` calls rather than only
contract-level relationship tests.

The corrected repository fact is that `output/` is currently un-ignored but not git-tracked. A
future blanket `.gitignore` entry for generated output must either preserve scaffold `.gitkeep`
slot markers with negated exceptions or intentionally remove those placeholders; otherwise the
scaffolded projection slots will disappear from fresh clones.

### Decision

Adopt **projection-aware emit into the scaffolded slots** combined with a **single canonical
medallion dbt project** that retains **per-domain manifest ownership**. The chosen options from
those considered are (1) projection-aware layout and (3) unified dbt project:

1. **Projection-aware emit layout (chosen).** Emit each projection into the scaffolded slot it
   serves, such as `output/medallion/dbt` for dbt, `output/medallion/powerbi/<product>` for
   semantic models, and analogous folders for search or graph projections.
3. **Unified dbt project (chosen).** Emit all domains into one canonical medallion dbt project so
   cross-domain `ref()` calls are ordinary dbt graph edges, while each `compile <domain> --emit`
   owns and replaces only its manifest-listed files (statelessness preserved, per DD-097
   multi-domain reconciliation).

The rejected alternatives are (2) domain-centric `output/<domain>/` and (4) standalone-per-domain
dbt projects. Standalone packages would keep cross-domain relationships as package-management
concerns and force DD-138's external-reference contract to remain contract-only rather than
emitting physical refs.

`output/` is added to `.gitignore` with negated exceptions that preserve scaffold `.gitkeep` slot
markers (e.g. `output/**` plus `!output/**/.gitkeep`) so fresh clones keep the projection slots
while generated artifacts stay untracked.

### Rationale

Projection-aware slots match the scaffold and downstream consumption model. A unified dbt project
maximizes deterministic compile-time relationship wiring, but it increases coordination and stale
artifact risk. Standalone projects preserve isolation and simpler ownership, but make cross-domain
relationships package-management concerns rather than local compiler refs.

### Consequences

- Maintainers must decide the emit tree before broadening generated artifacts beyond current dbt
  outputs.
- `.gitignore` changes for generated `output/` must preserve or intentionally remove scaffold slot
  placeholders.
- The chosen dbt topology constrains whether ISSUE-7 can produce physical cross-domain dbt refs or
  only declared external-reference contracts.

### Amendment (2026-08-20): CompilePlan-owned contracted dependencies (#580)

The unified project must be self-contained when generated Silver models call `ref()` for an
authored contracted model. Resolution now closes the selected model's authored SQL dependency
graph during compilation, fails when a transitive `ref()` is missing or ambiguous, and stores the
stable project path plus exact UTF-8 content for selected SQL/properties files on the immutable,
graph-free `CompilePlan`. Projection never searches the authored hub for these files.

Sequential domain emits reconcile compiler-owned per-domain dependency selections into one
dependency manifest. Identical shared dependencies may have multiple domain owners; re-emitting
one domain removes a stale dependency only when no other emitted domain still selects it.
Conflicting bytes, case-insensitive paths, or dbt model names fail closed rather than overwriting
another domain's contract.

### Amendment (2026-08-21): contracted source() declarations and seed dependencies (#584, #586)

The #580 amendment carried the contracted `ref()` SQL closure onto the `CompilePlan` but never
extracted the `{{ source('name', 'table') }}` calls inside it, so nothing declared those physical
sources and the emitted project failed offline `dbt parse` (#584). And a `ref()` pointing at an
authored dbt seed CSV failed `dbt-source.dependency-unresolved` outright, blocking the whole
domain (#586, stage a).

**Contracted `source()` extraction happens at resolution time, and declarations flow through the
existing shared per-system catalogs.** `resolve_scope` resolves contracted bindings *before* the
vocabulary scan and widens vocabulary discovery to files whose relations satisfy
`camel_to_snake(system_label).replace(" ", "_") == source_name and tableName == table` — exactly
the naming rule `_source_catalogs` uses — so a purely-contracted domain (which has no
`source.relation` refs) still parses the vocabularies its closure reads, and those vocabularies
join `scope.inputs`/provenance. During `build_compile_plan`, one plan-authoritative walk
(`_dbt_dependency_closures`, sharing `REF_RE`/`SOURCE_RE` with `dbt_source.py` and
`dbt_lineage.py`) extracts each valid binding's pairs; `_contracted_source_tables` validates them
against physical vocabulary relations (`dbt-source.source-unresolved` when no relation matches,
`dbt-source.source-ambiguous` when distinct tables match) and builds each declaration through the
same `system_fact_for_relation` helper relation-backed bindings use, so contracted-domain
declarations are byte-identical to relation-backed ones and dbt sees exactly one definition per
source name. `dbt_bundle.py`/`dbt_validation.py` deliberately keep their own ref/source regexes
(two-argument package refs, IGNORECASE — different semantics); the stage-(b) amendment below
settles that as permanent rather than pending, and shares only `strip_jinja_comments`.

**A new `contracted_input_uris` field carries the declared table URIs** on
`BoundSources`/`NormalizedProjectFacts`, consumed only by `_source_catalogs`.
`replacement_input_uris` was deliberately **not** reused: tables in that set lose direct-mapping
authority (`mapping.replaced-source-direct-authority`), which would outlaw the legal combination
of a direct binding on a table plus a contracted model reading the same table via `source()`.
The virtual `"dbt"` system is unaffected — its tables stay excluded via `virtual_table_uris`,
so `models/silver/_dbt__sources.yml` is still never emitted.

**The cross-domain shared-catalog union now fails closed.** `_union_sources_yaml` raises
`SourcesUnionError` on conflicting non-`tables` source headers or conflicting same-name table
entries (previously silent first-wins); `compile --emit` surfaces it as an
`ArtifactCollisionError` before any file is written. Non-conflicting output is byte-identical to
the historical union, preserving AB/BA multi-domain emit determinism.

**Seed `ref()` targets are closure leaves and are emitted (#586a).** Both walks — the filesystem
walk in `dbt_source._dependency_sql_paths` and the plan walk over `scope.inputs` — resolve
`ref('<name>')` against `models/**/<name>.sql` *and* `integration/transforms/dbt/seeds/<name>.csv`;
a name matching both is `dbt-source.dependency-ambiguous` (models and seeds share dbt's ref
namespace). A seed leaf is never text-scanned. Seeds emit as
`PlannedDbtDependency(kind="seed", path="seeds/<name>.csv", model_name=<stem>)` — no plan
dataclass changes — because emitting a model whose `ref()` points at a non-emitted seed would
violate this DD's self-containment rule; `validate-dbt`'s dangling-ref check accordingly counts
`seeds/**/*.csv` stems as known ref targets. Seed authoring polish (scaffolding, bundle/lint
awareness, docs) is #586 stage (b), settled in the amendment below.

**Review hardening (same PR).** Jinja `{# ... #}` comment blocks are stripped before every
`ref()`/`source()` extraction (dbt never renders them, so a commented-out call must not create a
phantom dependency or a false blocking source diagnostic). `source()` extraction goes through one
shared `extract_sources` helper that also recognizes dbt's keyword form
(`source_name=`/`table_name=`, either argument order). `ref()` names match authored stems
**case-exactly**, as dbt itself does — both walks index authored files once per walk keyed by the
real on-disk stem, which states the exact-match rule in the data structure instead of delegating
it to whatever case sensitivity the filesystem and glob implementation happen to provide;
casefolding survives only in duplicate/collision detection. Unreadable or non-UTF-8 dependency
bytes (the cp1252 seed-export case) fail as binding-attributed
`dbt-source.dependency-unresolved` diagnostics in both the filesystem walk and scope resolution
instead of escaping as a `UnicodeDecodeError` crash.

**Unparseable `source()` calls fail closed (`dbt-source.source-unparsed`).** Rather than
enumerating ever more call shapes, `extract_sources` counts `source(` call sites (a `\b`-anchored
probe, so a macro merely *ending* in `source` such as `my_source(` is not a call site) and
compares that with the number of spans it actually matched. Any surplus means at least one call
used a form static analysis cannot resolve — mixed positional/keyword arguments, `var()` or
variable arguments, string concatenation, macro-generated names — and both closure walks turn
that into a blocking, binding-attributed diagnostic naming the supported forms. This follows
#584's own acceptance criterion that *"if arbitrary SQL source extraction is unsupported ...
compilation must fail clearly when declarations are missing"*: a silently-unextracted `source()`
is exactly the defect #584 exists to prevent, because the emitted project then fails offline
`dbt parse` with no compile diagnostic at all. An explicit compile error naming the unsupported
form is strictly more actionable than that. Matched spans (not deduplicated pairs) are counted so
a file legitimately repeating one identical call is not mistaken for an unparsed one.

Explicitly **deferred to the #586 stage-(b) follow-up**: a dependency-kind registry, a single
parameterized closure walker shared by the filesystem and plan walks, consolidation of
`dbt_bundle`/`dbt_validation`'s ref/source regexes, unifying `medallion_dbt_projector`'s two local
source-name copies with `uri_utils.dbt_source_name`, and remaining perf polish. The amendment
below closes the first two of those (registry: shipped; regex consolidation: resolved as a
deliberate *non*-consolidation) and restates what still remains.

### Amendment (2026-08-21): authored dbt seeds are a first-class hub input (#586 stage b)

Stage (a) made a seed resolvable from an authored `ref()` and emitted it. It did not make a seed
an input the rest of the toolkit knows about, and the gap was not cosmetic: `compile --emit`
succeeded on a seed-backed hub while `run_projections`/`generate` hard-failed on the same hub.

**Bundle assembly now scans `seeds/`, which is what actually fixes the fatal projection.**
`core/dbt_bundle.py` only ever walked `models/`, `macros/`, and `tests/`, so an authored seed CSV
never entered `available_artifacts` and its stem was absent from the ref-closure `known` set. An
authored model's `{{ ref('country_codes') }}` therefore raised `DbtContractError: unresolved dbt
ref targets`, which `core/projector.py` escalates into a fatal *"dbt assembly failed; no dbt
artifacts were written"* for the entire dbt/silver target — one seed took down every model in the
projection. The bundle now collects `seeds/*.csv` plus sibling `*.yml`/`*.yaml` seed docs into
`bundle.artifacts` keyed `seeds/<name>.csv`, exposes them as a new `DbtBundle.seed_names:
frozenset[str]` field rather than making callers re-derive stems from paths, includes those stems
in the `known` ref-closure set, and allow-lists a `seeds:` key in `_filter_properties` for scoped
mode. A seed stem colliding with an authored or generated model stem **fails the bundle closed**:
dbt models and seeds share one `ref()` namespace, so the alternative is a project that does not
parse, which is strictly worse than a build error naming the two files.

**Seed column docs are a first-class artifact with a sibling-stem convention, and are
deliberately kept out of the contract-parsing path.** `seeds/<name>.yml` (or `.yaml`) next to
`seeds/<name>.csv` is dbt's plain `seeds: - name: ... columns: ...` properties form. It is *not*
a `meta.kairos` contract, and cannot be one: `dbt_contracts._parse_contract` requires a paired
SQL file and would reject the document outright. That is the right shape rather than an
accommodation — a seed is not a bindable virtual source, so it declares no output contract for a
binding to select. Selecting a seed into the closure selects its sibling properties document too,
and both are emitted together, so the generated project documents its seeds exactly as the hub
authored them.

**A dependency-kind registry replaces a boolean ladder and a lying ternary.**
`cli/compile.py::_load_dependency_states` hand-expanded per-kind validation and then computed
`expected_prefix = "seeds/" if kind == "seed" else "models/"`, whose else-branch silently asserted
that every kind yet to be invented lives under `models/` — a claim that stage (b)'s own new kind
falsifies. The registry maps each kind to its allowed suffixes, whether a `model_name` is
required, and its expected path prefix, so an unknown kind fails closed for free instead of being
mis-validated against a default. The kinds are `sql` (`.sql`, `model_name` required, `models/`),
`properties` (`.yml`/`.yaml`, no `model_name`, `models/`), `seed` (`.csv`, `model_name` required,
`seeds/`), and the new `seed_properties` (`.yml`/`.yaml`, no `model_name`, `seeds/`). Seed docs
carry no `model_name` for the same reason model properties YAML does not: the CSV owns the
resource name and the properties document only describes it. Giving both the same `model_name`
would trip the plan's own model-name collision check — the data model would contradict itself.

**Scaffolding, hub inspection, and the contract lint all learn about seeds, and the lint's one
error is an error on purpose.** `cli/shared.py::_V5_HUB_DIRECTORIES` now creates
`integration/transforms/dbt/seeds`, so `init`/`new-repo` produce the slot.
`core/hub_inspection.py`'s `dbt_transforms` presence probe was `.sql`-only, so a hub whose only
authored transform content was a seed reported *missing* to `kairos-ontology next`; an authored
seed CSV now counts. `core/dbt_contract_lint.py` returned early with `transforms_present=False`
whenever `models/` was absent, making a seeds-only hub look empty; transforms now count as
present when either `models/` or an authored seed exists. Three findings join the existing
`findings` list: `dbt-contract.seed-docs-unmatched` (**warning**) for seed docs whose
`seeds[].name` entries match no authored CSV stem — a typo or docs left behind by a rename;
`dbt-contract.seed-unreadable` (**warning**) for a CSV that is unreadable, not UTF-8, or has an
empty header row; and `dbt-contract.seed-model-collision` (**error**). The severity split is the
substantive choice. The first two describe authored content that is merely wrong or stale and
still leaves a buildable project. The collision does not: dbt resolves `ref()` in a single
resource namespace, so two resources sharing a name make the generated project fail to parse, and
`dbt_bundle` now hard-fails that exact case. A lint that called it advisory would disagree with
the build, and a lint that disagrees with the build teaches maintainers to ignore it.
`core/dbt_contracts.py`'s scan is unchanged; a `seeds:`-only document simply is not a contract
and it does not choke on one.

**The deferred ref/source regex consolidation is resolved as a deliberate, permanent
non-consolidation; only `strip_jinja_comments` is shared.** The two regexes look like duplication
but encode opposite obligations. `dbt_source.REF_RE` is a *selection* rule that builds the
dependency closure, so it must match dbt's own resolution exactly: case-sensitive (Jinja is
case-sensitive, and `REF('x')` is an undefined-function error in dbt, not a ref) and
single-argument. `dbt_bundle._REF_RE` is a *fail-closed validation* rule asking "does every ref
target resolve?", so it is deliberately over-broad: IGNORECASE, and it accepts dbt's two-argument
package form `ref('pkg','model')`. Merging in either direction loses something real. Adding
IGNORECASE to the selection walk would make `REF('x')` create a phantom dependency and a spurious
blocking compile diagnostic for a call dbt never makes. Adding the package form to the selection
walk would demand that a cross-package ref target exist as an authored hub artifact, turning a
legal (if rare) `ref('dbt_utils','x')` into `dbt-source.dependency-unresolved`. Dropping either
IGNORECASE or the package form from the bundle would relax a fail-closed check. What *did*
consolidate is the one genuine defect the duplication caused: `dbt_bundle` now routes every
extraction through the shared `dbt_source.strip_jinja_comments`, so a commented-out
`{# ref('x') #}` is no longer read as a real dependency or as an unresolved-ref error. On the
compiler side, the two `REF_RE.findall(strip_jinja_comments(...))` call sites — the filesystem
walk in `dbt_source` and the plan walk in `kernel` — collapse onto one shared `extract_refs()`
helper, mirroring what #584 did for `extract_sources`.

**Open question, deliberately not answered here: seed materialization and typing.** Emitted seeds
land in the profile's default target schema with dbt's default column-type inference, because
this change does *not* add a `seeds:` config block to `templates/dbt/dbt_project.yml.jinja2`.
Choosing a schema, quoting policy, and explicit `column_types` for seeds is a materialization
design decision with its own adapter-portability consequences (Fabric and Databricks disagree on
string and decimal defaults), and settling it as a side effect of making seeds resolvable would
be the wrong place to decide it.

**Operationally, `update` does not backfill hub directories.** Only `init`/`new-repo` create
them, so an existing hub must `mkdir integration/transforms/dbt/seeds` itself before authoring
its first seed. This is the scaffold's standing contract, not a seed-specific gap.

Still **deferred** after stage (b): a single parameterized closure walker shared by the
filesystem and plan walks (the two walks now share `extract_refs`/`extract_sources` and
`strip_jinja_comments`, but not their traversal), unifying `medallion_dbt_projector`'s two local
source-name copies with `uri_utils.dbt_source_name`, and remaining performance polish.

### Amendment (2026-08-23): seed schema and quoting are declared (#596)

`templates/dbt/dbt_project.yml.jinja2` now emits a `seeds:` config block:
`+schema: 'reference'`, `+quote_columns: true`, `+tags: ['reference']`. `reference` is a
new, dedicated hub-wide layer — seeds are business-supplied reference/lookup data, not raw
Bronze extracts (Bronze is platform-managed and outside dbt's control in this toolkit) nor
domain-scoped Silver/Gold models, so reusing either name would misdescribe the layer.
Seeds are hub-wide rather than per-domain, so there is no `{{ domain.name }}`-style
sub-block the way `models:` has one per domain.

`column_types` deliberately remains on adapter-default inference for now. Deriving it from
the optional authored `seeds/<name>.yml` column-docs (added in stage (b) above) would mean
adding a new `data_type` property to a document this DD explicitly kept as dbt's plain,
non-`meta.kairos` properties form — that stays a distinct, explicitly-scoped follow-up
rather than a default chosen here.

Forward-looking note, not yet built: reference-data *sourcing* is expected to evolve
toward a separate Kairos MDM Hub platform, with the Ontology Hub retaining the semantics
layer. This amendment does not build toward that — it only names the direction so a future
change has context when seeds stop being purely hand-authored CSVs.
