# Changelog

All notable changes to the Kairos Ontology Toolkit are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [4.7.0rc4] — 2026-07-23

### Fixed
- Hub-local ontology inventories no longer conflict with namespaced reference-module
  inventories that share the same source stem.

## [4.7.0rc3] — 2026-07-22

### Added
- **Governed imported-dbt candidate assessment (DD-105):** explicit repository-contained
  SQL/dbt roots can be inventoried as non-executable planning evidence, surfaced in
  deterministic status, and checked before Mapping, Silver, and release.

### Changed
- Custom dbt contracts may declare a valid subset of Fabric/Databricks adapters; projection
  still rejects a selected adapter the model does not support.
- Validation and projection resolve accelerator context from the explicit CLI option, hub
  configuration, or an unambiguous installed pack.

### Fixed
- Managed virtual-source vocabularies now preserve explicit non-key `not_null`
  tests/constraints instead of marking every non-key contract column nullable.

## [4.7.0rc2] — 2026-07-22

### Added
- **Typed reference-module activation and managed imports (DD-104):** version-pinned
  module profiles now drive deterministic ontology-document imports and activation
  inventories without copying imported definitions into authored domain ontologies.
- **Portable Silver lineage and temporal contracts:** generated dbt models now retain
  Bronze-primary-key source identity and load context, support explicit current/as-of
  SCD2 FK resolution and relationship change detection, and emit contract metadata and
  generic tests consistently for Fabric and Databricks.

### Changed
- Bound incremental Silver models now reject missing or partially mapped natural
  keys, use timestamp-precision SCD2 windows, and enforce portable physical identifiers.
- Multi-source Silver models now implement the declared SCD1/SCD2 lifecycle instead of
  advertising history semantics over a plain table.

### Fixed
- SCD2 parent lookups no longer fan out across historical rows, and generated lineage
  columns no longer duplicate names supplied by a custom audit envelope.
- **Nested business-discovery imports (DD-060 amendment):** `discovery-status` now
  scans `.import/businessdiscovery/` **recursively** and matches extractions by
  normalized `source_path` provenance, so valid records for documents in subfolders
  are no longer misreported as orphaned. New nested records get collision-safe,
  path-derived extraction filenames; existing records are preserved and never
  renamed. Duplicate provenance is surfaced as a new `conflict` warning.

## [4.7.0rc1] — 2026-07-22

### Added
- **Canonical ontology closure loading (DD-103):** recursive catalog-aware
  `owl:imports` traversal now provides deterministic manifests, diagnostics,
  cross-machine-stable closure hashes, cycle handling, and explicit strict or
  degraded semantics.
- **Versioned semantic index:** asserted, RDFS, Kairos design, and OWL RL profiles
  expose class/property hierarchies, restrictions, equivalence, inverses,
  individuals, and module provenance without consumer-specific reparsing.
- **Structured semantic inspection:** new `resolve-ontology`,
  `show-class-inventory`, `show-source-schema`, and `explain-term` CLI commands
  provide authoritative machine-readable context for users and managed skills.

### Changed
- Semantic consumers now share the canonical closure and semantic index across
  validation, inventory, analysis, alignment, projection, and prompt generation.
- Inventory schema 2.0 records semantic profile, closure freshness, import
  completeness, and direct versus inherited properties.
- Required imports fail closed by default; callers that intentionally accept
  partial semantics must explicitly enable degraded mode.

### Fixed
- Transitive dependency changes now invalidate generated inventories.
- Projection failures propagate when every ontology fails closure loading instead
  of returning a successful process status.

## [4.6.0] — 2026-07-21

### Added
- **Deterministic Silver-first lifecycle:** confirmed conformance outcomes now
  deterministically produce proposed-only claims, approved unbound claims can emit
  target-first dbt stubs, and `check-release` composes claim, mapping, synchronization,
  validation, projection, binding, and release-eligibility gates without duplicating
  their rules.
- **Canonical projection facts:** shared completeness, materialization, target, and
  foreign-key models now provide one deterministic interpretation across status,
  coverage, synchronization, Silver DDL, dbt, Gold/Power BI, and release gates.
- **Five-phase dbt pipeline (DD-102):** dbt generation now orchestrates typed immutable
  `bind → normalize → shape → materialize → render` phases while preserving existing
  public facades and byte-identical artifacts.
- **Authoritative Silver-first lifecycle scenario:** the copied `acme-hub`
  integration now proves validated conformance → proposed-only claims → explicit
  governance approval → managed extension sync → aspirational stubs → selected
  source binding → strict release, including deterministic output and real dbt
  parse/compile tooling.

### Fixed
- Fresh scaffold placeholders no longer falsely complete source or projection phases,
  and validation reports are written where deterministic status expects them.
- Projection timestamps are resolved once per run, malformed reproducibility inputs
  fail explicitly, and generated reports use stable manifest-managed paths.
- Claim regeneration now enforces preservation of every declared human-curated field.
- Silver, dbt, and Gold projectors now share one FK classifier, including redirected
  and inferred relationships.
- Catalog-resolved approved imported classes now participate in the same
  `BindingAnalysis` used by `status` and `check-release`.
- SHACL-derived dbt generic-test arguments render as nested YAML instead of
  sibling keys that dbt rejects during parse.

### Changed
- **Legacy inventory and Claim Registry projection layouts now require an explicit
  migration.** Runtime inventory readers no longer self-heal or dual-read retired
  stem-named reference inventories, and claim projection sync no longer converts
  inline controlled triples during normal operation. Run
  `kairos-ontology migrate --hub <hub>` first; `--check` / `--dry-run` preview every
  change. The migration is idempotent, preserves non-managed authored Turtle, and
  retains rollback copies in `.kairos-migrations/legacy-format-backups/`.
- Runtime source/claim coverage now evaluates one canonical per-table completeness
  snapshot; the retired alignment-coverage runtime and its parallel authority have
  been removed.

### Removed
- Unused Silver/projector helpers and four obsolete dbt staging/date templates.

## [4.5.0rc4] — 2026-07-21

### Fixed
- **`update --upgrade` now rewrites optional-extras toolkit pins.** The
  pin-rewriter previously only matched the primary
  `kairos-ontology-toolkit @ …` dependency, leaving
  `[project.optional-dependencies]` pins such as
  `kairos-ontology-toolkit[flatfile] @ …` on the old version. With the primary
  pin advanced and extras pins stale, `uv lock` failed with conflicting URLs for
  the same package. The rewriter now preserves any `[extra]` marker and updates
  every occurrence. The scaffold `pyproject.toml.template` also gains `azure`,
  `foundry`, and `parquet` extras pins alongside `flatfile`.

## [4.5.0rc3] — 2026-07-21

### Fixed
- **Alignment & projection correctness hardening** (DD-098,
  `docs/draft/toolkitoptimizations.md`; F1 fixes #219). Seven independent
  correctness/governance gaps in the source→domain alignment and medallion
  projection pipeline, each keeping default output byte-identical when no new
  condition fires:
  - **F1 naming parity (#219):** the dbt silver projector no longer hardcodes
    `silver_{domain}` / `camel_to_snake(local)`. A shared physical-naming helper
    (`silver_schema_name` / `silver_table_name` / `silver_naming_convention` in
    `projections/shared.py`) is now consumed by both the silver DDL and dbt
    projectors, so `silverSchema` / `silverTableName` / `isReferenceData` /
    `namingConvention` produce identical schema, table, and SK-key names across
    targets; the gold `ref()` registry uses the generated model name.
  - **F4:** URI backfill threads an optional inventory index into
    `write_claims_output` so proposed claims carry resolved `class_uri` /
    `property_uri`.
  - **F5:** `check-inventory` gains `--domains` / `--explain-scope` with a
    catalog-resolved domain→inventory map (repo-wide check stays the default).
  - **F6:** truncation integrity — a deterministic source column count + sha256
    is persisted per `(system,table)`, every source column is reconciled into a
    passthrough candidate, and a blocking `column_omissions` signal is added.
  - **F2/F7:** grain-conflict detection — `likely_entity` provenance is carried
    on `TableAlignment` and a blocking `grain_conflicts` record is emitted when
    distinct candidate entities collapse onto one `ref_class`.
  - **F3:** object-property target resolver — a scalar column attached to an
    object property whose governed target does not resolve is downgraded to a
    passthrough custom claim plus an `object_property_relationship_candidate`.

## [4.5.0rc2] — 2026-07-21

### Fixed
- **Multi-domain dbt projection collisions & peer-import drift** (DD-097, #220):
  full-hub `project --target dbt` no longer aborts with a false artifact
  collision on shared/package-level files (README, `dbt_project.yml`,
  `models/gold/shared/dim_date.sql`, `_shared__gold_models.yml`, per-system
  `_{sys}__sources.yml`). Shared gold artifacts are now domain-neutral
  (materialized to a stable `gold_shared` schema), per-system `_sources.yml`
  files are reconciled via a deterministic union, and package-level config is
  merged last-wins. Domain-only projection (`--ontology <domain>.ttl`) now
  collects hub domain namespaces from the full ontologies directory, so required
  peer-domain `owl:imports` are no longer flagged as claim/projection drift.
- **S3-folded subtype SHACL constraints lost on parent model**: when a subtype
  using the discriminator inheritance strategy is S3-folded into its parent
  silver model, its SHACL property constraints (e.g. `sh:pattern` →
  `dbt_expectations.expect_column_values_to_match_regex`) now propagate onto the
  parent model's folded columns instead of being dropped.

### Changed
- **dbt package source**: generated `packages.yml` and the approved-package list
  now reference `metaplane/dbt_expectations` (the maintained namespace for
  versions ≥0.10) instead of the deprecated `calogica/dbt_expectations`,
  silencing dbt's hub-namespace deprecation warning. Version constraint and the
  in-package `dbt_expectations.*` macro namespace are unchanged.

### Added
- **Target-first aspirational Silver stub → bind loop** (DD-096): opt-in
  `project --emit-aspirational-stubs` flag (also `KAIROS_EMIT_ASPIRATIONAL_STUBS`)
  emits typed, zero-row Silver stub models (`where 1 = 0`, `cast(null as <type>)`,
  tagged `kairos_aspirational_stub`, `meta.is_aspirational`) for approved,
  materialization-eligible claims that have no bronze mapping yet — so downstream
  Silver/Gold can be built target-first. Adding a source mapping transparently
  **binds** the stub on the next projection. `aspirational` is **derived** at
  projection time from the Claim Registry + mappings (never persisted). Feature-off
  output is byte-identical to prior releases. Backed by a new canonical
  `BindingAnalysis` service.
- **Release gate for unbound approved claims** (DD-096 / DEC-1): `project --strict`
  (env fallback `KAIROS_PROJECT_STRICT`, dbt/all only) fails when any approved,
  materialization-eligible claim has no bronze mapping (an *unbound target*), so an
  incomplete hub cannot be released with vacuous zero-row stubs. Wired into the
  scaffold `release-projections.yml` workflow. Independent of stub emission —
  release-eligibility, not artifact existence, is the gate.
- **Status-scan awareness of stubs** (DD-096 D4): `kairos-ontology status` distinguishes
  stub vs bound by running the canonical `BindingAnalysis` over the hub's authorities
  (Claim Registry + graph + sources + mappings), not generated `meta.is_aspirational`. A
  silver domain with an approved-but-unbound claim now reports `in-progress`
  ("aspirational stub(s) pending binding") instead of `done`, keeping `kairos-flow` and
  `kairos-diagnose-status` correct.
- **Obsolete dbt output reconciliation** (DD-096 C3): the dbt projector records a
  `.kairos-projection-manifest.json` and deletes previously generated files it no
  longer produces (e.g. a stale aspirational stub after the feature is disabled or its
  claim is deferred), pruning emptied directories. Only toolkit-recorded files are
  removed — hand-authored files are never touched.
- **Deterministic projection output**: generated artifacts embed an injected
  `generated_at` + `toolkit_version` context (env-overridable via
  `KAIROS_GENERATED_AT` / `SOURCE_DATE_EPOCH`) and all RDFLib iteration is sorted, so
  re-projection is byte-identical across processes and Python hash seeds.

## [4.4.0] — 2026-07-19

### Added
- **Contracted advanced dbt transformations** (DD-092): package handwritten,
  contract-first intermediate models for joins, windows, aggregation, fallback logic,
  JSON expansion, and grain changes while retaining generated ontology-aligned Silver
  wrappers. Adds managed virtual-source vocabulary synchronization, Fabric/Databricks
  platform selection, offline dbt graph validation, and the interactive
  **kairos-develop-dbt-transformation** skill.
- **Governed source replacement coverage** (DD-093, #215): contracted dbt models can
  declare canonical Bronze `replaces_sources` without unsafe direct SKOS mappings.
  Coverage requires an approved matching claim, synchronized replacement RDF,
  table-level `skos:exactMatch`, matching `silverSourceRef`, and no competing source
  authority; generated dbt sources retain declared contract inputs.
- **Privacy-safe source sample persistence** (DD-075): source import, schema
  extraction, and Bronze vocabulary generation now replace supported detected PII
  with opaque source-aware tokens before writing. The skill-gated `source-privacy`
  check/fix command remediates existing YAML and vocabulary artifacts without
  printing raw values.
- **Canonical Bronze source discovery** (DD-093): source analysis, coverage, and
  dbt-contract validation now share source identity rules. Generated contract
  vocabularies no longer create redundant affinity obligations, legacy reports are
  archived, split-source reports are consolidated, equivalent monolithic/split
  vocabularies are reconciled, and divergent definitions remain blocking.
- **Design-time MDM layer** (MDM-DD-001..003, mdmhubdesignv2.md ADR-1): a new,
  additive Master Data Management design layer expressed in
  `model/extensions/{domain}-mdm-ext.ttl` overlays, driven by the managed
  `kairos-mdm` vocabulary (`https://kairos.cnext.eu/mdm#`) — mastered concepts +
  MDM style, match attributes/identifiers, attribute authority + survivorship,
  deterministic match rules/thresholds, a content-addressed probabilistic-artifact
  reference (weights never in Turtle), maker/checker + SLA workflow policy, abstract
  steward roles, reference-data policy, and six-dimension DQ rules.
  - `kairos-ontology project --target mdm-profile` projects an **immutable,
    runtime-neutral** MDM profile (`{domain}-mdm-profile.json` with a reproducible
    `content_digest`, plus a `{domain}-mdm-profile.md` review summary) to
    `output/mdm/`. The target is opt-in (not part of `--target all`).
  - `kairos-ontology mdm-validate` runs a structural design-time gate over
    `*-mdm-ext.ttl` (controlled enumerations, thresholds, match rules, DQ
    dimensions, probabilistic-artifact digest). Skill-managed via **kairos-design-mdm**.
  - **Source split**: ontology functionality moved into `kairos_ontology.core`;
    the new `kairos_ontology.mdm` design-time package is an *additive consumer* of
    core. A one-way boundary is enforced — `core` never imports `mdm` (registry
    pattern; `tests/test_layering.py` guard). Public API is preserved via top-level
    `kairos_ontology` re-exports.
  - New scaffold asset `kairos-mdm.ttl`. See **MDM-DD-001..003** and
    `docs/mdm/`.
  - New **kairos-design-mdm** skill (`.github/skills/` + scaffold mirror) for
    interactive `*-mdm-ext.ttl` authoring, plus MDM docs under `docs/mdm/`
    (`mdm-design-decisions.md`, `user-stories.md`, `mdm-navigator-spec.md`).

### Changed
- **Docs housekeeping**: reorganised `docs/` for navigability. Added a
  `docs/README.md` documentation map; consolidated all MDM docs under `docs/mdm/`
  (moved `mdmhubdesignv2.md` from `docs/design/`); archived unreferenced historical
  material (former `docs/draft/` and the `evidence-led-modeling` tracker) under
  `docs/archive/` with a `README.md` frozen-history marker; removed a duplicate
  `ddd-governance-implementation-plan.md`; and repathed all inbound references. Pure
  relocation via `git mv` — no doc content was rewritten.

## [4.4.0rc17] — 2026-07-05

### Added
- **Optional DDD governance overlay** (DD-091): a new, additive Domain-Driven
  Design design layer expressed in `model/extensions/{domain}-ddd-ext.ttl`
  overlays, driven by the managed `kairos-ddd` vocabulary
  (`https://kairos.cnext.eu/ddd#`) with typed bounded contexts, reified context
  relationships, and controlled tactical-pattern individuals.
  - `kairos-ontology validate --ddd` (also run by `validate --all`) validates
    overlays through a dedicated path that merges each overlay with its domain
    ontology + the `kairos-ddd` vocabulary and applies packaged DDD SHACL shapes.
    Overlays that leak `kairos-ext:silver*`/`gold*` predicates fail.
  - `kairos-ontology project --target ddd` renders one-way documentation
    (Mermaid context map + aggregate overview + Markdown report) to
    `output/architecture/ddd/`. It never changes silver/gold/dbt/Power BI output.
  - Governance (ownership, approval, disposition, materialization) stays in the
    claim registry; XMI / Enterprise Architect round-trip is out of scope.
  - New modules `ddd.py`, `projections/ddd_projector.py`; scaffold assets
    `kairos-ddd.ttl` and `kairos-ddd-shapes.shacl.ttl`. See **DD-091**.

## [4.4.0rc16] — 2026-06-22

### Added
- **Core Concepts Conformance** (archetype + discovery contract v0.2, ref-models
  v1.11.0): new `discovery-conformance` CLI command group (`list-archetypes`,
  `load`, `validate`) and supporting modules `archetype_loader.py`,
  `archetype_topology.py`, `conformance_artifact.py`. Loads a business archetype's
  machine catalog (modules + core concepts + tiers), validates it against the
  shipped JSON Schema, derives relationship topology by parsing each
  `ref_model_modules[].iri` directly, and persists a validated
  `integration/discovery/core-concepts-conformance.yaml` artifact.
- `kairos-design-discovery` gains a **Phase 2.5 — Core Concepts Conformance**
  interview (interactive by default; fleet pre-fill); `kairos-design-domain` now
  reads the conformance artifact during reference-model selection (warn-only).
- New scaffold dir `ontology-hub/integration/discovery/` created by `init` /
  `new-repo`. New `KAIROS_REFMODELS_ROOT` env var for refmodels-root resolution.
- New runtime dependency `jsonschema>=4.0.0`. See **DD-090**.

## [4.4.0rc15] — 2026-06-22

### Fixed
- Silver FK metadata now resolves S3 discriminator-folded FK targets to the
  projected parent table, so DDL comments, ALTER documentation, and ERD lineage no
  longer point at skipped child tables.
- dbt projection now routes table mappings targeting S3-folded subtypes into the
  projected parent model while preserving subtype discriminator values, mapped
  subtype columns, and mapping filters.
- `audit-silver-samples` now accepts dbt lineage comments and full target URIs
  when checking mapped-target SQL presence, avoiding false positives for object
  properties rendered as FK columns.
- Power BI projection claim-sync gating now validates `silverInclude` against the
  exact domain silver extension while still passing gold extensions to the
  Power BI projector.
- Power BI gold projection now emits Fabric semantic-model wrapper files and
  parser-ready TMDL directly, so generated SemanticModel folders no longer need
  downstream sanitation before deployment.
- Per-domain Power BI SemanticModel output now omits cross-domain relationships
  to tables that are absent from the local model, avoiding invalid TMDL while a
  future master SemanticModel covers cross-domain reporting.

## [4.4.0rc14] — 2026-06-22

### Added
- `analyse-sources` now reports advisory sample-data coverage in affinity YAML and
  warns non-blockingly when fewer than half of a source system's analysed tables
  have sample values, because schema-only analysis can be semantically ambiguous.
- Design skills now support a skill- and invocation-scoped **design fleet mode**
  override for test runs. Fleet consent never propagates across lifecycle phases;
  AI decisions preserve evidence, validation, and traceable AI-approved logs.
- Source design now asks for the LLM provider and authentication mode at every
  invocation, including Azure AI or Microsoft Foundry through
  `DefaultAzureCredential`; a complete `.env` configuration is the recommended
  default and is confirmed before the first LLM call.
- Added `audit-silver-samples`, an offline advisory QA command that checks
  generated dbt silver mappings against source sample values without a warehouse
  connection.

## [4.4.0rc13] — 2026-06-21

### Added
- Scaffolded hub repos now expose a `flatfile` optional dependency that installs
  the toolkit's Excel support (`openpyxl`) via `kairos-ontology-toolkit[flatfile]`,
  enabling `uv sync --extra flatfile` before Excel `import-flatfile` runs.

### Changed
- `kairos-design-source` now recommends analysing all ready source systems in one
  `analyse-sources` pass by default, reserving scoped `--sources` runs for
  explicit exclusions, rate-limit workarounds, or targeted retries.
- `kairos-design-discovery` now treats image-heavy artifacts as first-class
  discovery evidence, including screenshots, diagrams, scanned PDFs, embedded slide
  images, and OCR/visible text, with optional visual provenance in extraction YAML.
- `kairos-flow` and `kairos-design-domain` now offer a governed data-product
  vertical-slice route for report/TMDL/semantic-model intent while preserving source
  analysis, claim, mapping, silver, and gold confirmation gates.
- `kairos-design-domain` now batch-scans in-scope domains for stale, missing,
  incomplete, empty, or unverifiable claim evidence and proposes one costed refresh
  plan using scoped `--domains ... --max-workers` runs instead of one-domain-at-a-time
  refresh loops.

### Fixed
- `generate-inventory` and `check-inventory` now ignore archived reference-model TTLs,
  preventing current/archive duplicates from fighting over the same inventory file and
  falsely marking fresh inventories stale.
- `decide-claims` now blocks unsafe approvals before writing: materializing
  `claim`/`specialize` claims cannot be approved without required URI/evidence, while
  reviewed `passthrough` approvals remain URI-free.

## [4.4.0rc12] — 2026-06-21

### Changed
- Clarified the V3 stable hotfix workflow while V4 release-candidate work lives
  on `main`, including worktree setup, tag-from-stable guardrails, and
  stable/preview channel expectations.

## [4.4.0rc11] — 2026-06-21

### Added
- **Data-product vertical-slice planning reports (DD-087).**
  `draft-model-report` now accepts a planning-only data-product contract to emit
  scoped `data-product-plan.yaml`, Markdown, and Mermaid ERD artifacts under
  `model/planning/data-products/{product}/`. The slice remains advisory
  (`projection_authority: false`) and derives triage from DD-086 evidence
  statuses instead of bypassing claims, mappings, silver, or gold design.

## [4.4.0rc10] — 2026-06-21

### Added
- **Reporting-informed draft model reports (DD-086).** New deterministic,
  advisory `draft-model-report` command builds all-domain draft evidence packs
  from claim extraction inputs, richer TMDL evidence, source affinity, mappings,
  and glossary terms. It writes YAML/Markdown plus one cross-domain Mermaid ERD
  under `model/planning/draft-model/` and is explicitly non-authoritative:
  no claim auto-approval, no TTL writes, and no projection authority.
- **Deterministic address relationship candidates surfaced during alignment
  (issue #192, Phase A1).** `propose-alignment` now promotes clustered address-part
  columns (e.g. `billing_street` + `billing_city` + `billing_postal_code`) into a
  machine-readable, **advisory** `relationship_candidates` entry on the Claim Registry
  (`hasBillingAddress → Address`), in addition to the existing scalar column
  dispositions. The detector is role-aware (`billing_*` vs `shipping_*` are separate
  relationships), always-on, additive, and uses **no LLM / no cross-module widening**;
  candidates carry the source columns and `requires_human_confirmation: true` but no
  resolvable target URI. A new MANDATORY *Checkpoint 3c — Relationship &
  Satellite-Entity Review* in `kairos-design-domain` blocks TTL generation until each
  candidate has an explicit model/relate/defer decision. Concrete target-URI naming
  (A2) and FK-driven satellite detection (Phase B) are deferred. See DD-084.
- **`decide-claims` CLI — query + bulk-curate claim status/disposition (issue #190).**
  A new AI-free command (`decide_claims.py`) to list claims by selector
  (`--status`/`--disposition`/`--type`/`--origin`/`--id`/`--column` globs) and to
  bulk-set status via `--by-disposition` or `--set-status` (`--dry-run` for counts).
  Writes back through the canonical `write_registry`, so curation produces minimal,
  reviewable diffs instead of hand-edited YAML noise.

### Changed
- **`analyse-sources` now reports table completions as concurrent LLM workers finish.**
  The command already used up to 8 per-table LLM calls by default; progress is now
  streamed per completed table while output YAML remains deterministic.
- **OKF phase logs replace interactive `.sessions-design` logs (DD-085).** New hubs
  use `.kairos-state/phases/...` as the required design-session memory for
  discovery/source/domain/mapping/silver/gold skills. Legacy `.sessions-design/*.md`
  files are historical only and are not auto-migrated. Import audit logs
  (`.sessions-design-import/`) and projection reports (`.sessions-projection/`)
  remain separate.
- **`project --ontology` supports single-domain projection.** Operators can now run
  `kairos-ontology project --ontology model/ontologies/party.ttl --target silver`
  to regenerate one ontology file while preserving hub-root discovery for
  extensions, mappings, sources, shapes, and claims. Existing `--ontologies`
  directory mode remains unchanged.
- **Hub-side offline dbt validation guidance.** Ontology-hub scaffolds now include
  a `dbt-validate` optional dependency group (`dbt-core` + Fabric adapter in the
  1.9 family) and `.env.example` version guidance so `kairos-execute-project` can
  run `dbt deps` + `dbt parse` against `output/medallion/dbt/` after dbt
  projection. Downstream dataplatform repos are not given extra validation-only
  dependencies.

### Fixed
- **dbt SCD2 FK joins stay in scope for inherited role/subclass relationships
  (issue #194).** SCD2 silver models now select FK lookup columns in the
  `mapped` CTE where the FK join aliases are visible, then reference the mapped
  FK aliases from `source_data`. This fixes invalid SQL such as
  `address_ref.address_sk` being emitted after `address_ref` has gone out of
  scope.
- **Claim projection sync now fails loudly on invalid intra-hub ontology bases.**
  `_collect_hub_domain_bases` no longer silently skips malformed Turtle while
  collecting `_foundation.ttl` / `_master.ttl` imports, avoiding false "in sync"
  reports when a shared hub base is broken.
- **Intra-hub shared bases (`_foundation.ttl`, `_master.ttl`) are no longer stripped
  from domain `owl:imports` (issue #190).** `_collect_hub_domain_bases` skipped every
  `_`-prefixed file, so foundation/master imports were flagged as `extra` and removed
  by projection sync. It now treats any `owl:Ontology`-declaring `*.ttl` under
  `model/ontologies/` as an allowed intra-hub base (only `-ext.ttl` surfaces are skipped).
- **`migrate-claims` now back-fills `class_uri`/`property_uri` from the reference-model
  inventory (issue #190),** so anchored claims can be approved without manual URI lookup.
  Ambiguous names stay null (never guessed); resolved/unresolved counts are printed.
  `--no-resolve-uris` opts out; `--inventory-dir` overrides discovery.
- **`claims-to-silver-ext` now scaffolds a minimal valid ontology / `*-silver-ext.ttl`
  skeleton for a fresh domain instead of silently writing nothing (issue #190).**
  The skeleton carries a provenance header and inferred hub base / foundation import;
  `--no-scaffold` disables it.
- **The MDM-anchor warning in `check-claims` now prints a concrete `mdm_anchor: true`
  reference_data claim example and points to the skill / `--no-mdm-anchor` (issue #190).**
- **`claims-to-silver-ext` no longer destroys authored TTL when syncing projection
  surfaces (issue #191).** The destructive whole-graph rdflib re-serialize is replaced
  by a **block-delimited managed region** (`# >>> kairos-managed … # <<< kairos-managed`)
  that the tool regenerates with full URIs; the provenance header, comments, prefix
  layout, local subclasses, and triple ordering outside the block are preserved
  verbatim. Managed import/include sync is unchanged and still enforced by `check-claims`.
  Repeated syncs are idempotent, and legacy inline imports migrate into the block on the
  next sync. Also closes the DD-082 item-5 limitation (scaffolded header survives the
  first sync with approved imported claims). See DD-083.

> ~~The destructive whole-graph rdflib rewrite of projection surfaces (issue #190 item 6)
> is tracked separately as **issue #191**.~~ Resolved above (issue #191).

## [4.4.0] — 2026-06-20

### Fixed
- **`analyse-sources --domains` no longer forces unrelated tables into the filtered
  domain (issue #189).** `--domains` previously pruned the LLM **candidate** domain
  set before classification, so every table was forced into the requested domain (or
  `unclassified`), polluting affinity evidence and downstream `check-claims` counts.
  It is now a pure **post-classification output filter**: tables are always classified
  against the full accelerator/reference domain set (getting their true primary domain),
  then only tables whose primary domain matches `--domains` are written. A system with
  no matching tables now writes an empty affinity report instead of erroring. `--max-domains`
  (which still truncates candidates as a rate-limit guard) now warns when it truncates.
- **`release.yml` now normalizes the release tag to PEP 440 before comparing it to
  `__version__`**, mirroring `_tag_to_version()`. Both `vX.Y.Zrc1` and the
  SemVer-style `vX.Y.Z-rc.1` (the form the channel resolver and `_whl_url` already
  expect) now validate, instead of only the exact PEP 440 string.

### Added
- **Two-layer lifecycle state, deterministic `status` CLI, and the `kairos-flow`
  single entry point (DD-080).** Introduces a formal, resumable lifecycle state model
  for ontology hubs.
  - **`kairos-ontology status`** — a new read-only, AI-free CLI (`status.py`) that
    deterministically scans committed hub artifacts and reports a per-phase /
    per-instance objective state (`not-started` / `in-progress` / `done`) for the
    whole lifecycle (`discovery, source, domain, mapping, claims, silver, gold,
    validate, project`). Supports `--format text|json|markdown`; exempt from the
    skill-gate like the other deterministic gates.
  - **`kairos-flow` skill** — the single entry point ("start / where are we /
    continue / resume"). Runs the scan, reconciles it against the saved continuation
    state, presents a lifecycle overview, offers clean-start vs continue, and hands
    off to the correct phase skill. Interactive-only; it is the only writer of
    `status.md`.
  - **OKF continuation-state bundle** at `ontology-hub/.kairos-state/` (created by
    `init` / `new-repo`): `status.md` (scan-derived / continuation / phase-index
    regions) plus per-instance `phases/<phase>/<instance>.md` logs with an Open
    Questions resume anchor, following the Open Knowledge Format v0.1 as a storage
    convention.

### Changed
- **`kairos-diagnose-status`** now defers objective status to `kairos-ontology
  status` (deterministic backbone) and focuses on enrichment/diagnostics.
- **Phase design/execute skills** (discovery, source, domain, mapping, silver, gold,
  validate, project) gain a lightweight read-state + state-proposal contract against
  `.kairos-state/`; they no longer maintain global status themselves.
- Methodology doc gains §21 (lifecycle state model and single-entry orchestration);
  skill routing table, `kairos-help`, and the CLI lifecycle table point to
  `kairos-flow`.

## [4.3.0] — 2026-06-15

### Added
- **MDM/reference-data rules + ownership hardening in `check-claims` (DD-EL-6).**
  Slice 4 adds four deterministic governance checks to the single `check-claims`
  gate plus the Claim Registry schema they need.
  - **MDM-anchor gate (§5.4).** A *broad domain claim* (an approved class claim
    with disposition claim/specialize) is blocked with `anchor_pending` when the
    domain declares `mdm_anchor` reference-data claims that are still `proposed`,
    and warned with `anchor_missing` (pragmatic — anchors must be *known*, not
    fully implemented) when broad claims have no declared anchors at all.
  - **deviation-log check (§12/§14).** Approved `gap` (client-native) claims that
    lack a deviation record (owner + reason) block with `deviation_missing`.
  - **ownership-boundary check (§14).** Approved claims whose `class_uri` falls
    under another data-domain's `data-domains.yaml` `uris` prefix block with
    `ownership_conflicts` unless an `ownership_override` (owner + rationale) is
    present.
  - **passthrough-review check (§11.2).** High-use passthrough claims (evidence
    across ≥2 source systems, a powerbi measure/slicer/filter/hierarchy/join/fk/
    sample_signal evidence type, or any evidence carrying a `measure`) that are not
    yet `passthrough_reviewed` warn with `passthrough_review`.
  - **Shared-conformed-dimension escape hatch.** Cross-file same-URI approved
    claims now route to a `shared_dimensions` warning instead of the
    `duplicate_approved` block when either claim carries an `ownership_override`.
- **Claim Registry schema fields (DD-EL-6).** New `ReferenceData`
  (`authority_system` / `code_system` / `key` / `scd_type`), `Deviation`
  (`reason` / `owner` / `gap_request`), and `OwnershipOverride`
  (`owner` / `rationale`) dataclasses, plus `Claim` fields `reference_data`,
  `mdm_anchor`, `deviation`, `ownership_override`, and `passthrough_reviewed`. All
  are omitted from serialized output when default (byte-stable golden output
  preserved) and preserved across re-runs by `merge_preserving_decisions`.
  `validate_registry` gains structural checks (warns on `reference_data`/`mdm_anchor`
  set on a non-`reference_data` claim; errors on an `ownership_override` missing owner
  or rationale).
- **`check-claims` flags.** `--no-mdm-anchor` and `--no-ownership` skip the
  respective gates.

## [4.2.0] — 2026-06-15

### Added
- **`derive-claims` command (DD-EL-5).** A **deterministic, AI-free** aggregator
  that merges/enriches the Claim Registry (`model/claims/{domain}-claims.yaml`)
  into `proposed` candidate claims, reducing hand-authoring. The
  semantically-hard LLM work already happened upstream in `analyse-sources`
  (affinity) and `propose-alignment` (column→property); `derive-claims` is the
  deterministic merge/enrich layer. It joins **five evidence streams**
  deterministically on `(system, table[, column])` and ref_class/ref_property
  names — the existing claims registry, `analyse-sources` affinity,
  `import-tmdl` concept-mapping, SKOS mappings, and sample-derived signals —
  attaching **multiple `evidence_sources` per claim**. All derived/new claims are
  `status: proposed` and are **never** auto-`approved` (the C4 guard); human
  decisions survive re-runs via the existing `merge_preserving_decisions()`. For
  parity with the AI commands it reuses `--max-workers` (default 8) and `--force`
  (`_concurrency` / `_cache`), but **deliberately omits the cost banner** because
  nothing is billed. A future opt-in `--llm-reconcile` flag (LLM tie-breaking /
  rationale synthesis, with a cost banner) is **deferred** to a later slice.

## [4.1.0] — 2026-06-15

### Added
- **`claims-to-silver-ext` command (DD-EL-4).** Deterministically generates/
  regenerates a domain's external `owl:imports` set and per-class
  `kairos-ext:silverInclude` assertions in `{domain}-silver-ext.ttl` from the
  **approved imported** class claims in `model/claims/{domain}-claims.yaml`
  (realizing A1 — claims drive imports). `--check-only` reports drift and exits 1
  without writing.
- **Foundation/thin-ontology scaffold (A2-lite).** New
  `scaffold/ontology-hub/model/ontologies/foundation.ttl.template`; the starter
  domain ontology now `owl:imports` the thin `_foundation` ontology.

### Changed
- **`check-claims` claim↔projection sync gate (DD-EL-4).** `check-claims` now
  blocks when a domain's `owl:imports` / `silverInclude` surfaces drift from its
  approved claims, or when a `silverIncludeImports` bulk-bypass flag is present.
  Add `--no-extension-sync` to skip the gate.
- **Projector claim-authority gate for silver/dbt/powerbi (DD-EL-4).** For those
  targets, if `model/claims/{domain}-claims.yaml` exists, projection of that domain
  fails (records a projection error) when the claim-derived imports/includes are out
  of sync. Retains the DD-021 no-bypass guarantee but makes materialization
  claim-driven.

## [4.0.0] — 2026-06-15

### Changed (BREAKING)
- **Claim Registry replaces the alignment YAML (DD-EL-1).** The evidence-led
  cutover retires `{domain}-alignment.yaml` in favour of a single governed
  `model/claims/{domain}-claims.yaml` registry as the source of truth for which
  concepts are approved to materialize.
  - `propose-alignment` now emits candidate (`proposed`) claims into the registry
    (default output `model/claims/`) instead of alignment YAML, preserving
    table/column coverage, the freshness digest, and custom-column disposition
    triage. Re-runs merge over existing claims without clobbering human decisions.
  - **New `check-claims` gate** replaces **both** `check-alignment` and
    `check-source-coverage` (now removed). It verifies, per affinity domain, that a
    `{domain}-claims.yaml` exists, is structurally valid, covers every affinity
    table, and is fresh; it blocks on cross-file duplicate `approved` claims and
    (unless `--no-source-coverage`) on unmapped tables, and — with `--strict` —
    on undecided (`proposed`) claims. It rejects any leftover `*-alignment.yaml`
    with a migration message (no dual path).
  - **New `migrate-claims`** command performs the one-way
    `{domain}-alignment.yaml` → `{domain}-claims.yaml` conversion.
  - Design/help skills updated to the claims workflow (`check-claims`,
    registry-based curation).

### Removed (BREAKING)
- `check-alignment` and `check-source-coverage` CLI commands (folded into
  `check-claims`).
- Alignment-YAML reader machinery in `alignment_coverage` (the module now provides
  only the reused affinity/freshness primitives and triage heuristics).

## [3.24.1] — 2026-06-14

### Changed
- **Alignment `--high-accuracy` now prefers `gpt-5.4` (non-reasoning).** The
  `propose-alignment` high-accuracy tier dropped from `gpt-5.5` to `gpt-5.4`:
  alignment is deterministic closed-vocabulary matching, so a non-reasoning model
  is preferred (lower latency/cost, no reasoning-model overhead). gpt-5.4 is also
  the recommended `KAIROS_AI_ALIGNMENT_MODEL` in the scaffold `.env.example`.

### Fixed
- **Foundry AI provider: extras packaging + API-key auth crash (DD-078).** Two
  related defects that made the Microsoft Foundry provider unusable for
  `analyse-sources` / `propose-alignment`:
  - The user-facing extras (`azure`, `foundry`, `flatfile`, `parquet`) were declared
    **only** under `[dependency-groups]`, so the documented
    `pip install kairos-ontology-toolkit[foundry]` resolved nothing (extras are not
    written into wheel metadata). They are now also declared under
    `[project.optional-dependencies]`; a parity test
    (`tests/test_packaging_extras.py`) keeps the two in sync.
  - `_create_foundry_client` passed an `AzureKeyCredential` (from
    `AZURE_FOUNDRY_API_KEY`) to `AIProjectClient`, but azure-ai-projects 2.x
    `get_openai_client()` requires a token credential (`get_token`) — crashing every
    table to `mdm`/0.00. The Foundry path now prefers `DefaultAzureCredential` and,
    when an API key is set, tries it then **falls back to `DefaultAzureCredential`**,
    with a clear error if neither works.
- **dbt cross-table warning conflated inherited vs own props (issue #181, DD-079).**
  For a subtype claimed as its own silver table (`Child ⊂ Parent`), every inherited
  parent property mapped on the parent's table fired a `Cross-table reference … may
  need a JOIN` ⚠️ warning — even though those columns are excluded from the subtype
  model **by design** — producing 40+ noise warnings per subtype. Cross-table
  properties are now classified by their **direct** `rdfs:domain`: **own** props
  (declared on the subtype) still emit a per-column ⚠️ warning (genuine JOIN
  candidates, own-precedence), while **inherited** props are reclassified
  warning → **info** and collapsed into one consolidated ℹ️ note per class (surfaced
  under a `## ℹ️ Info` section of the dbt session log). WARNING-log volume and report
  warning counts drop accordingly.

## [3.24.0] — 2026-06-14

### Added
- **Custom-column triage hardening (issue #182, DD-082).** A set of deterministic
  / confidence-gated fixes to `propose-alignment` and the `check-alignment` gate
  that make the Checkpoint-3b custom-column triage reliable at scale (hundreds of
  custom columns) — **no new AI cost** (DD-077):
  - **Confidence-gated suggestions (WS1).** An unmatched custom column only keeps a
    `suggested_property` when the model is confident enough
    (`--custom-confidence-floor`, default `0.5`); below the floor it is dropped to
    `null` rather than emitting a confident-but-wrong guess. A catch-all detector
    downgrades any property proposed for ≥3 dissimilar columns (the
    `stageCode`/`customsID` sink problem).
  - **Two-tier auto-disposition (WS2).** Every custom column gets an advisory
    `recommended_disposition` (`skip` / `silver-passthrough` / `""`). A final
    `disposition` is auto-filled **only** for narrow, near-zero-ambiguity
    audit/technical columns (`created_on`, `tenant_id`, surrogate `id`, …), stamped
    `disposition_source: heuristic`. Generic vendor slots (`CFSTRING33`, …) are
    *recommended* `silver-passthrough` but stay undisposed (still block under
    `--strict`) unless `check-alignment --accept-heuristics` is passed.
  - **Reference-rollup integrity (WS4).** Matched properties are validated against
    the class's real reference-model property set; coverage is capped at 100% and a
    `hallucinated_properties` sample is surfaced instead of silently clamping.
  - **Hallucinated-anchor detection (WS6).** Generation records a non-clean
    `ref_class_status` (`fallback` / `rejected` / `unmatched`) + `rejected_ref_class`
    so a force-fit or unanchored table is visible without re-running the LLM. A new
    `check-alignment --check-anchors` gate re-validates `ref_class` anchors against
    the real installed reference-model class set and blocks on hallucinated anchors
    (e.g. a `Booking` class that exists in no reference model).
  - **Prompt hardening (WS7).** For an unmatched column the model now emits
    `alignment: custom` + `ref_property: null` (never an invented camelCase name),
    may return `ref_class: null` when no class fits, and is steered away from
    catch-all sinks and >100% over-mapping.
  - **Opt-in high-accuracy preset (WS8).** `propose-alignment --high-accuracy`
    selects a higher-tier model for the accuracy-sensitive class-anchoring step;
    mini stays the default and the cost banner notes alignment is accuracy-sensitive.
  - **Per-role LLM endpoints.** The two pre-modeling steps can now use independent
    endpoints/models via `KAIROS_AI_AFFINITY_*` and `KAIROS_AI_ALIGNMENT_*`
    (`_ENDPOINT` / `_KEY` / `_MODEL`): keep `analyse-sources` on a cheap mini
    endpoint while pointing `propose-alignment` at a stronger model/deployment. A
    role with no override falls back to the global provider. Documented in both
    `.env.example` scaffolds.
  - **Disposition preservation on regeneration (WS9).** Re-running
    `propose-alignment` (including `--force`) no longer wipes a modeler's
    hand-triaged dispositions: human-owned `disposition`/`note` values are merged
    back by `(system, table, column)`; only heuristic-owned fields are recomputed.
  - **Schema/cache/version contract (WS0).** An explicit `algorithm_version` is
    emitted and folded into the per-table and domain cache keys, so the hardened
    prompt/heuristics take effect instead of serving stale cache. Fixes a latent bug
    where the freshness hash was written as `source_sha256` but read as
    `affinity_sha256` (dead domain-level cache skip).

### Notes
- Cross-domain candidate tagging and a non-LLM repair path for existing large
  alignment YAMLs were scoped under issue #182 but deferred to follow-up issues.

## [3.23.0] — 2026-06-14

### Added
- **Sample-grounded mapping evidence (DD-075).** `propose-alignment` now emits
  masked `example_values` for each mapped column **by default** (real source
  sample values are the strongest mapping evidence), plus an advisory
  `transform_compat` note when a proposed numeric/bool `CAST(...)` looks
  incompatible with the sampled values (e.g. *"2/5 sample values are
  non-numeric — CAST may NULL/fail"*). A shared `_samples` policy module is the
  single source of truth for PII detection and masking: PII columns (by name,
  mapped property, `gdpr_protected`, or value shape) are **always masked**
  (`jo***@***.com`) and never enumerated. Both fields are additive — no
  `schema_version` bump. Suppress with `--no-sample-values`. The
  `kairos-design-mapping` skill gains a **mandatory** masked Examples column in
  its Phase 2 proposal table and a privacy rule (never copy raw values into
  committed TTL/comments/session logs).
- **`suggest-shapes` — draft SHACL from source profiling (DD-076).** New
  deterministic CLI command that builds a **DRAFT** SHACL file from bronze
  profiling metadata: `sh:datatype` always; `sh:pattern` when one format matches
  all samples; `sh:minCount 1` from `nullable:false`; `sh:in` only when a
  reliable `kairos-bronze:distinctCount` ≤ `--enum-distinct-max` fully matches
  the sampled distinct set (never for PII). Output defaults to
  `output/shapes-draft/<name>.ttl` — **outside** `model/shapes/` and with a
  `.ttl` (not `.shacl.ttl`) suffix — so the validator does not auto-load drafts;
  the user reviews and promotes them. Surfaced via the `kairos-execute-validate`
  skill (skill-gated; set `KAIROS_SKILL_CONTEXT=1`).

### Fixed
- **dbt merge: explicit FK mapping no longer leaks across sources (issue #178).**
  When two bronze sources merged into one silver entity and only one source
  declared an **explicit** SKOS FK column-mapping (`bronze:<col> skos:exactMatch
  <fkProperty>`), the dbt projector applied that mapping to *every* source's
  per-source staging view — producing a phantom `left join` and a join predicate
  referencing a column the other source does not have. `_resolve_fk_source_column`
  now scopes the explicit-mapping branch to the current source's columns (using a
  None sentinel so legacy non-merge callers are unaffected, and a physical-column
  fallback so synthetic/composite/transform-only mapping subjects are still
  attributed to the declaring source). Non-declaring sources emit a typed
  `CAST(NULL AS …)` placeholder; the declaring source keeps its real join.
- **dbt silver: table mapping to an unprojected class is no longer silently
  dropped (issue #179).** A `skos:exactMatch` table mapping whose target class is
  not in the projected set (e.g. an unclaimed imported subtype —
  `silverIncludeImports=false` and no `silverInclude`) was discarded with no
  model and no warning. `_gen_silver_models` now detects such orphaned targets and
  either **folds** their source(s) onto a projected discriminator parent (when one
  exists) or emits a loud warning naming the table and class, so the contribution
  is never lost without notice.

## [3.22.0] — 2026-06-14

### Fixed
- **Silver/dbt merge pattern no longer generates invalid/lossy `UNION ALL`
  (issue #175).** When two or more bronze sources merged into one silver entity
  with non-identical mapped column sets (the normal master-data case), the dbt
  projector produced broken SQL: the union column list was taken from the first
  source only, per-source views projected only their own mapped columns (so the
  `UNION ALL` branches had mismatched column counts), and FK `_sk` columns were
  silently dropped. The merge pattern now builds a **canonical column superset**
  across all sources, projects every per-source staging view to that superset
  with explicitly-typed `CAST(NULL AS <type>)` pads for unmapped columns, and
  emits **explicit per-branch column lists** (no `select *`) so the `UNION ALL`
  is positionally consistent. A loud warning fires when a source does not map a
  natural-key column (which would yield NULL/duplicate surrogate keys).
- **Silver/dbt FK auto-inference no longer mis-resolves same-range FK properties
  (issue #174).** When a class declared two or more FK object properties whose
  natural-key signature was identical (e.g. `hasBillingAddress` and
  `hasShippingAddress`, both ranged on `Address`), NK-based auto-inference would
  silently resolve an *unmapped* role to the *mapped* sibling's source columns,
  producing a semantically wrong join with no warning. The dbt projector now
  detects FK targets that share a natural-key signature (keyed on resolved NK
  property URIs, so discriminator-folded subtypes and `silverForeignKeyOn`
  redirects are covered too) and **disables auto-inference** for them — they are
  resolved only from explicit SKOS mappings; unmapped roles emit a NULL
  placeholder plus an explicit ambiguity warning directing the user to add an
  explicit mapping. Correctly-mapped roles are unaffected.

### Changed
- **Foreign keys are now resolved in the merge pattern (issue #175).** Because
  each per-source staging view is single-source, the existing single-source FK
  machinery now runs *inside* each view: the source that maps a FK emits a real
  `left join {{ ref(target) }}` and the resulting `_sk` column, while sources
  that don't map it emit a NULL pad. The FK `_sk` flows through the `UNION ALL`
  as an ordinary canonical column — no union-level join, no hidden columns, no
  silent drop. The union model itself performs no joins. See DD-074.

## [3.21.0] — 2026-06-14

### Added
- **`kairos-ext:silverExclude` annotation (DD-073, issue #172).** A new boolean
  class annotation that suppresses a class's silver table while keeping it in the
  ontology for inheritance/semantics. It overrides `silverInclude` /
  `silverIncludeImports`; descendants still inherit the excluded class's
  properties (it is treated as an unclaimed / cross-domain FK target). The
  projector warns when a materialised class subclasses or FK/junctions to an
  excluded class. Declared in `scaffold/kairos-ext.ttl`; documented in the
  `kairos-design-silver` skill.
- **Automated projection session-log archival (DD-071 amendment).** Each
  projection run now moves any pre-existing per-domain logs
  (`projection-{domain}-*.md`, `dbt-{domain}-*.md`) for the in-scope domains into
  `.sessions-projection/_archive/` before writing the new logs (collision-safe,
  never deleted), mirroring the design-session `_archive/` convention.
  `kairos-diagnose-status` ignores the `_archive/` subfolder for
  `.sessions-projection`.

### Fixed
- **Transitive S3 discriminator folding (DD-073, issue #172).** Discriminator
  folding now walks `rdfs:subClassOf` through **unclaimed** intermediate classes
  and folds a subtype into the nearest **claimed** discriminator ancestor, instead
  of inspecting only the direct parent. Properties of the unclaimed intermediates
  fold into the parent table too (previously they were silently dropped).
  `folded_subtypes` is now URI-keyed for namespace safety, traversal is
  deterministic, and conflicting strategies among same-depth claimed ancestors
  emit a warning. Single-level (depth-1) folding behaviour is unchanged.

## [3.20.0] — 2026-06-14

### Added
- **Provenance comment header on toolkit-generated TTL (DD-072).** Files the
  toolkit writes itself now begin with a small Turtle `#`-comment block stamping
  the toolkit version, a UTC generation timestamp, the generator name and an
  edit-policy note. Applied to source vocabulary (`*.vocabulary.ttl`), the SKOS
  glossary (`*-glossary.ttl`), and the scaffold ontologies (`_master.ttl`,
  per-domain `{domain}.ttl`) written by `init` / `new-repo`. The header is plain
  comments only — it adds no RDF triples, so it never affects parsing, SHACL
  validation, merge, or projection. A new shared helper
  (`kairos_ontology._provenance.provenance_comment` / `prepend_provenance`) is
  exposed and idempotent (regenerating never stacks headers); the design skills
  (`kairos-design-domain`, `kairos-setup-config`) document the convention for
  hand-authored ontology/SHACL files.

## [3.19.0] — 2026-06-14

### Added
- **Cross-module candidate properties in `propose-alignment` (DD-070, issue #166).**
  The actual fix for the limitation #167/#168 only *detected*: a column whose true
  reference-model match lives in a sibling/shared accelerator module (e.g. a shared
  `Address`, `PaymentTerms`, or `currency`) could not be matched and was force-fit
  onto an unrelated home-domain scalar. A new opt-in `--cross-module` flag (requires
  `--accelerator <name>`) widens the **STEP-2 property candidate pool** to the whole
  accelerator while keeping **STEP-1 table classification home-only** (two separate
  pools). Each matched non-home class is tagged with its owning `ref_module`
  (+ `ref_module_uri`, `belongs_to_domain(s)`) and accumulated into a separate
  `cross_module_matches` section that tells the modeler which module to import. The
  home `reference_rollup` is unchanged. Classes carry a stable `ref_class_id`
  (`<module>:<Class>`) and are deduped by URI so same-named classes across modules
  stay distinct. Freshness/cache keys include a cross-module params signature
  (`alignment_params_sha256`) so a cross-module run is never skipped after a prior
  home-only run, and the unbounded full-inventory retry is disabled in cross-module
  mode (cost guard). **Default output (no `--cross-module`) is byte-identical.**
- **Business-discovery glossary marked non-authoritative (DD-071).** Every generated
  `{company}-glossary.ttl` `skos:ConceptScheme` is now stamped with an `rdfs:comment`
  + `skos:editorialNote` disclaimer making explicit that the glossary is initial
  inspiration only — not kept in sync with the domain ontology, and its
  `seeAlso`/`relatedMatch` links are not reconciled during modeling.

### Changed
- **Design-skill session logs are archived, not overwritten, on "Start fresh" (DD-071).**
  When a user starts a fresh design session, existing `.sessions-design/*.md` logs are
  moved to `ontology-hub/.sessions-design/_archive/` before the new log is created
  (never silently deleted). `kairos-diagnose-status` ignores `_archive/` when locating
  the most recent session log.

## [3.18.0] — 2026-06-14

### Added
- **propose-alignment plausibility & address review flags (DD-069, issues #167/#168).**
  A deterministic, no-LLM review pass now flags structurally implausible column
  maps for human review instead of letting them pass silently. Each flagged column
  in `{domain}-alignment.yaml` gains `review: true` + a `review_reason`
  (emitted only when a rule fires, so default output is unchanged). Rules cover:
  address-part columns (`street`/`postalCode`/`addressLine*`/qualified
  `city`/`zip`) force-fit onto non-address party scalars (#167); boolean source →
  identity/name property; financial-flavoured column → generic identity property;
  and no-name-token-overlap + low-confidence maps (#168). `check-alignment` collects
  these into a new **report-only** "flagged for review" section — it never blocks
  (separate from the #164 custom-column `--strict` gate). The column mapping is
  kept (only flagged), and no cross-module `reference-data#Address` target is
  hardcoded (that remains #166's scope).

## [3.17.0] — 2026-06-14

### Added
- **Custom-column triage in domain modeling (DD-068, issue #164).** Source-evidenced
  columns with no reference-model property are no longer silently dropped before
  mapping. `propose-alignment` now writes a `disposition` field (`model` /
  `silver-passthrough` / `skip`; `null` until triaged) on each `custom_columns`
  entry. `check-alignment` surfaces and classifies these columns (business vs likely
  operational/audit) and gains a `--strict` flag that **blocks** until every custom
  column is dispositioned (default warns; `--warn-only` overrides `--strict`). The
  `kairos-design-domain` skill now requires every custom column to appear in the
  Source Evidence Table, records a per-column disposition back into the alignment
  YAML in Checkpoint 3b, runs `check-alignment --strict` at the completion gate, and
  clarifies that "Reference Model Enforced" governs class-hierarchy reuse — not
  "add nothing local".

## [3.16.1] — 2026-06-14

### Added
- **Release-management guide + policy (DD-067).** New `docs/RELEASING.md` documents
  SemVer discipline, the "support only the latest line" policy, and a bugfix decision
  tree that keeps patches out of feature releases via ephemeral `hotfix/x.y.z`
  branches cut from the release tag (with a mandatory back-merge to `main`).
  `CONTRIBUTING.md` gains a branch-naming table and the `kairos-toolkit-ops` skill
  links to the guide. Docs/process only — no tooling or CI changes.

### Removed
- **PyPI publishing scaffolding removed from release CI (DD-066).**
  The dormant (commented-out) `publish-pypi` job and the unused `id-token: write`
  permission are removed from `.github/workflows/release.yml`. The toolkit was never
  published to PyPI; it is distributed via GitHub Releases (wheel + sdist assets) and
  consumed through git-tag / wheel-URL pins. README and skills updated to drop the
  PyPI badge and `pip install kairos-ontology-toolkit` instructions in favour of the
  git-tag install. No behavioural change to the `build` / `github-release` jobs.

## [3.16.0] — 2026-06-14

### Added
- **Concurrent, cached AI pre-modeling for `analyse-sources` and `propose-alignment` (DD-065).**
  Both commands now parallelize their per-table LLM calls with a bounded thread pool
  (`--max-workers`, default `8`; `--max-workers 1` reproduces the old serial path),
  collapsing large-hub runs from tens of minutes to a few. Two-level incremental
  caching skips unchanged work: a domain-level skip via the existing `affinity_sha256`
  freshness hash plus a schema-neutral per-table sidecar cache under
  `<analysis-dir>/.cache/`. `--force` bypasses both cache layers. Both commands now
  print a prominent cost banner before running (showing table count × workers and
  recommending `gpt-5.4-mini`), suppressed by `--quiet`. Rate-limit (HTTP 429) errors
  are retried with exponential back-off.

### Changed
- **`propose-alignment` anchors class selection on the affinity `likely_entity` (DD-065).**
  The prompt now asks the model to confirm the affinity-derived entity rather than
  re-derive it, and falls back to `likely_entity` when the model returns an invalid
  class (previously blanked). Defaults retuned for fewer redundant calls:
  `--max-prompt-classes` `18`→`12`, `--retry-min-confidence` `0.75`→`0.6`,
  `--retry-min-mapped-ratio` `0.55`→`0.4`.

## [3.15.5] — 2026-06-14

### Fixed
- **AI provider `.env` auto-loading now resolves repo-root settings when running from `ontology-hub/`.**
  AI-dependent commands could miss credentials when only repo-root `.env` existed.
  Dotenv discovery now checks cwd, hub dir, and repo root deterministically.

### Changed
- **`propose-alignment` retry + prompt payload optimized further for runtime.**
  Full-inventory retry now triggers only when shortlist output is truly weak
  (both low confidence and low mapped-column ratio, or missing class). Source
  sample values in prompts are also compacted by filtering noisy ID-like values
  and clipping long text, reducing token payload while preserving semantic signal.

## [3.15.4] — 2026-06-13

### Changed
- **`propose-alignment` prompt payload is now token-optimized with quality safeguards.**
  Per table, the first pass now uses a deterministic shortlist of reference classes
  (`--max-prompt-classes`, default `18`) instead of always sending the full class
  inventory. If the shortlist result is weak, the command retries once against the
  full inventory using configurable gates
  (`--retry-min-confidence`, `--retry-min-mapped-ratio`). This keeps default behavior
  quality-safe while reducing runtime/token cost on large domains.

## [3.15.3] — 2026-06-13

### Fixed
- **`validate` / `project` now resolve paths from the hub root, not the CWD (DD-064).**
  Both commands hardcoded option defaults relative to the current directory
  (`ontology-hub/model/...`, `ontology-hub/output`), assuming you ran them from the
  repo root. Run from inside `ontology-hub/` (or in a hub without a `shapes/` dir),
  `validate` hard-errored with Click exit 2 ("Path '…' does not exist") before
  running, and `project` wrote artifacts to a doubly-nested
  `ontology-hub/ontology-hub/output/`. Defaults are now resolved via
  `find_hub_root()` (like `coverage-report`), so both work whether invoked from the
  repo root or inside the hub; `--shapes` is optional (SHACL skipped if absent);
  catalog auto-detection is hub-root-aware. Explicit `--ontologies`/`--shapes`/
  `--output`/`--catalog` still win. Note: this prevents *future* nesting — a hub
  with an existing stray `ontology-hub/ontology-hub/output/` should delete it and
  regenerate.

### Added
- **Deterministic SKOS glossary builder (DD-063).** New read-only, AI-free CLI
  command `kairos-ontology build-glossary` reads the confirmed business-discovery
  extraction files (`businessdiscovery/_extractions/*.extraction.yaml`) and emits
  the company glossary overlay (`businessdiscovery/{company}-glossary.ttl`) as a
  SKOS `ConceptScheme` via `rdflib`. It aggregates `extracted_terms` into
  deduplicated concepts (grouped by `linked_iri`, else `prefLabel`), maps
  `linked_iri` to `rdfs:seeAlso` (or `skos:relatedMatch` when a term sets
  `link_relation: relatedMatch`), and auto-detects the company namespace from the
  hub `README.md`. The `kairos-design-discovery` skill now calls this command
  instead of hand-writing a one-off `rdflib` script each run. The domain ontology
  is never modified (overlay only).

## [3.15.2] — 2026-06-13

### Fixed
- **`update`/`--upgrade` no longer scaffolds a second hub from a subdirectory (DD-062).**
  The command now resolves the hub via an upward-walking `find_managed_root()`
  (anchored on the `[tool.kairos]` / toolkit pin or the managed
  `.github/copilot-instructions.md` marker) and auto-re-roots to it with a notice,
  instead of trusting `Path.cwd()`. Running it inside a content subdirectory (e.g.
  `ontology-hub/`) now updates the real repo-root hub. Fabricating a `pyproject.toml`
  is restricted to positively-detected (legacy) hubs; in a non-hub directory the
  command now hard-errors with guidance instead of manufacturing a spurious hub.


## [3.15.1] — 2026-06-13

### Added
- **Deterministic source-coverage gates (DD-061).** Two new read-only, AI-free CLI
  commands close the asymmetry where reference-model coverage was hard-gated
  (`check-inventory`) but source coverage was only advisory.
  `kairos-ontology check-alignment` (pre-modeling) verifies that every data domain
  in the affinity reports has a `{domain}-alignment.yaml` from `propose-alignment`
  that **covers all** the domain's tables and is **fresh** — blocking on
  *missing / incomplete / stale*. `kairos-ontology check-source-coverage`
  (pre-silver) verifies that every affinity-assigned source table is mapped to a
  domain entity (a SKOS match on the bronze table or one of its columns) — blocking
  on any unmapped table. Both hard-block by default with a `--warn-only` escape
  hatch and stay out of the soft skill-gate set (like `check-inventory`).
  `check-alignment` is wired as a hard pre-flight in `kairos-design-domain`
  (Step 0a.2); `check-source-coverage` as a mandatory pre-flight before silver in
  `kairos-design-silver` and `kairos-execute-project`.

### Changed
- **`propose-alignment` output is versioned and carries a freshness hash (DD-061).**
  Alignment YAML `schema_version` is bumped 1 → 2 and now stores a `source_sha256`
  digest of the affinity `(system, table)` set so `check-alignment` can detect
  staleness. Pre-existing v1 alignment files remain valid and are reported as
  *unverifiable* (warn, non-blocking) until regenerated.
- **`pypdf` and `pyarrow` are now core dependencies.** Business-discovery document
  parsing (DD-060) needs to extract text from PDF artifacts in
  `.import/businessdiscovery/`, and Parquet source import needs `pyarrow`. Because
  hubs install the toolkit as a bare wheel, optional extras don't reach them — so
  both libraries are promoted to core `[project.dependencies]` and now arrive
  automatically on `update --upgrade`. `pyarrow` remains exposed via the `[parquet]`
  extra for backward compatibility. (pypdf: BSD-3-Clause; pyarrow: Apache-2.0 —
  both Apache-2.0-compatible.)

## [3.15.0] — 2026-06-13

### Added
- **Per-document extraction tracking for business discovery (DD-060).** The
  `kairos-design-discovery` skill now writes one extraction file per processed
  document to `ontology-hub/businessdiscovery/_extractions/{slug}.extraction.yaml`,
  recording the document's `source_sha256`, a summary, the extraction strategy, and the
  extracted terms — so you always know **what was extracted from which document**. A new
  deterministic, AI-free command `kairos-ontology discovery-status` scans
  `.import/businessdiscovery/` and reports which documents are **new**, **changed**, or
  **up to date** (hash-based, mirroring `check-inventory`); `--strict` exits non-zero
  when there is work to do. Reruns now reprocess only new/changed documents instead of
  re-reading everything. New hubs get a `businessdiscovery/_extractions/` folder + README
  via `init`/`new-repo`.

### Changed
- **Modeling now gates on source analysis and unpacks reference models first
  (DD-058).** `kairos-design-domain` gains a pre-flight branch (**P2b**) that detects
  imported-but-unanalysed sources (`integration/sources/_analysis/` has no
  `*-affinity.yaml`) and auto-hands off to `kairos-design-source` Phase 4 before any
  class design — closing a gap where "start modeling" could skip the data-first source
  analysis. `kairos-design-source` Phase 4 now makes `generate-inventory` (+
  `check-inventory`) a required up-front step run **before** the AI `analyse-sources`
  pass (cheap/AI-free first), which also de-risks the Step 0c.1b / DD-047 inventory gate.
  The Source-Completeness Checkpoint is renumbered P2b → **P2c**.
- **Modeling pre-flight adds a Discovery-Completeness gate (DD-059).**
  `kairos-design-domain` now checks for business-discovery artifacts
  (`businessdiscovery/*.ttl`, `.sessions-design/businessdiscovery-*.md`) in a new **P1b**
  checkpoint that fires **independent of source state** — so a hub with imported sources
  but no discovery context is now prompted to run `kairos-design-discovery` first
  (recommended, not hard-blocked). Step 2a is upgraded from "read if present" to an
  explicit gate. Closes a gap where discovery (the canonical lifecycle start) was only
  surfaced in the empty-sources branch.

### Fixed
- **Inventory class entries now include their canonical `uri` (schema 1.1).**
  `generate-inventory` previously emitted each class with `name`/`label`/`comment`/
  `properties`/`specializations` but no top-level URI, forcing consumers to reconstruct
  IRIs from the domain namespace + class name. Each class now carries a `uri` field
  (matching the `class_uri` already present on specializations). `INVENTORY_VERSION`
  bumped `1.0` → `1.1`; regenerate inventories with `kairos-ontology generate-inventory`
  to pick up the field.
- **Windows `update --upgrade` no longer fails the managed-file refresh with a
  file-lock error (DD-057).** The running `kairos-ontology.exe` locks its own
  executable, so the previous synchronous re-exec could not `uv sync` to the new
  version. The upgrade now schedules a **detached** helper that waits for the current
  process to exit, then runs `uv sync` + `kairos-ontology update` automatically. A
  transcript is written to `.kairos/upgrade-refresh.log`. Non-Windows behaviour is
  unchanged.

## [3.14.0] — 2026-06-13

### Changed
- **Business discovery now materializes the full reference-model breadth and links
  glossary terms to reference-model IRIs (DD-055).** The `kairos-design-discovery`
  skill gains a read-only "Phase 1a" that runs `generate-inventory` over the
  reference models first, makes Phase 1 research explicitly company-wide, and
  resolves glossary IRIs in priority order hub → reference-model → flag-as-novel.
  Reruns are idempotent: previously-flagged terms are re-linked to hub IRIs as each
  domain is modeled, so terminology is no longer lost across domains.
- **Hub folders relocated & renamed (new hubs only, DD-056).** The business
  glossary folder moved from `ontology-hub/model/glossary/` to
  `ontology-hub/businessdiscovery/`, and the materialized inventory folder from
  `ontology-hub/model/inventory/` to `ontology-hub/referencemodels-unpacked/`.
  `init`/`new-repo` scaffolding, `generate-inventory`/`check-inventory` default
  paths, and all design skills now use the new locations. Existing hubs are **not**
  auto-migrated — move the two folders manually (or recreate the inventory with
  `kairos-ontology generate-inventory`).
- **CHANGELOG is now enforced as part of the release process.** Previously
  `release.yml` generated GitHub Release notes purely from merged PRs
  (`--generate-notes`) and never consulted or updated `CHANGELOG.md`, so the file
  silently drifted (e.g. `3.10.x`/`3.11.x` shipped with no entry). Now
  `release.yml` fails a tagged GA release whose version has no `## [X.Y.Z]`
  `CHANGELOG.md` section, and `version-check.yml` fails a PR that bumps
  `__version__` without the matching entry. Pre-releases (`rc`/`beta`/`alpha`) are
  exempt. The `kairos-toolkit-ops` release steps now include promoting
  `[Unreleased]` to a dated heading.

### Fixed
- **Reference-model inventories are now namespaced by their owning model
  (DD-054).** `generate-inventory` previously named every inventory from the TTL
  stem (`{stem}-inventory.yaml`), so same-named modules across reference models
  (e.g. `party.ttl` in BSP, DCSA, IMO, MMT, TIC, WCO) collapsed into one
  last-write-wins file and silently dropped five models' classes (`TradeParty`,
  `MaritimeParty`, `TransportParty`, …); `documents`, `locations`, `events`, and
  `equipment` were affected too. Reference-model files are now written as
  `{model}-{stem}-inventory.yaml` (e.g. `bsp-party-inventory.yaml`) via a shared
  `inventory_filename()` helper used by both `generate-inventory` and
  `check-inventory`. This also fixes the DD-047 staleness **deadlock** (colliding
  stems reported as permanently `STALE` with no way to clear them) and the glitch
  where a stem appeared in both the `ok` and `stale` lists. `generate-inventory`
  gains a default `--prune` that removes inventory files no longer produced by any
  source (self-heals legacy stem-named files). Re-run `generate-inventory` and
  commit the regenerated `model/inventory/`.
- **Reference-model auto-detection now consistently uses the repo-root
  `ontology-reference-models/` directory.** `generate-inventory` and
  `check-inventory` previously defaulted to the non-existent
  `model/reference-models/`, so the `kairos-design-domain` pre-flight silently
  found zero reference models. All four commands (`generate-inventory`,
  `check-inventory`, `analyse-sources`, `coverage-report`) now share a single
  `_resolve_ref_models_dir()` resolver that prefers the repo-root location
  (legacy `model/reference-models/` kept as a last-resort fallback). Help text
  and the `kairos-toolkit-ops` skill corrected accordingly.

### Added
- **Import commands auto-write an import-results session file.** `import-flatfile`
  and `import-source` now write a machine-generated
  `import-{system}-{YYYY-MM-DD}.md` to `ontology-hub/.sessions-design-import/`
  (created at `init`/`new-repo`), capturing tables, columns, change report, and
  enrichment using a template consistent with the existing session files. The
  write is best-effort and skipped when no hub root is detected. (DD-052)
- **CLI soft skill-gate.** Skill-managed commands (`validate`, `project`, `init`,
  `new-repo`, `migrate`, `update`, `update-refmodels`, `import-source`,
  `import-flatfile`, `generate-staging`, `analyse-sources`, `init-dataplatform`)
  now emit a loud stderr warning redirecting to the owning Copilot skill when run
  directly, then still run (soft gate). Set `KAIROS_SKILL_CONTEXT=1` to silence
  it; gated skills set it automatically. (DD-053)

### Changed
- **Renamed the business-discovery artifacts folder `.imports/` → `.import/`**
  (singular). `kairos-ontology init` / `new-repo` now create
  `.import/businessdiscovery/` at the repo root; the dotless scaffold source
  folder is `scaffold/import/`. Skills, docs (DD-048), and tests updated. (DD-048)

## [3.13.2] — 2026-06-13

### Changed
- **Start-modeling now auto-hands off to the lifecycle start, and the
  source-completeness check is always-on.** Refines v3.13.1 (DD-051): on a fresh
  hub, "start modeling" auto-routes to `kairos-design-source` (offering
  `kairos-design-discovery`) before domain modeling. When sources already exist,
  the `kairos-design-domain` skill now poses a **mandatory Source-Completeness
  Checkpoint on every modeling start** — including the first pass — asking whether
  additional/other sources should be imported first (previously only on
  restart/extension). (DD-051)

## [3.13.1] — 2026-06-13

### Changed
- **"Start modeling" now points to the lifecycle start.** The Copilot instructions
  and the `kairos-design-domain` skill now frame domain modeling as a mid-lifecycle
  step (`discovery → source → domain → …`): on a fresh hub, "start modeling" routes
  the user to discovery + source import first. The modeling skill gains advanced
  pre-flight checks — a *fresh* mode (empty `integration/sources/` → go import
  sources) and a *restart/extension* mode (prompt to import additional sources and
  re-run `analyse-sources` before continuing). Guidance only; Gate 6 unchanged.
  (DD-051)

## [3.13.0] — 2026-06-13

### Added
- **Parquet source import.** `import-flatfile` now accepts `.parquet` files
  (single file or mixed into a directory of CSV/Excel/Parquet). Column types are
  mapped directly from the Parquet schema, and only sample data (`--max-rows`) is
  read — the full file is never loaded. Requires the new optional `[parquet]`
  extra (`pyarrow`). (DD-050)

## [3.12.1] — 2026-06-13

### Fixed
- **`update --upgrade` now refreshes managed files under the new version.**
  Previously the post-upgrade managed-file refresh ran in the same process, which
  still had the *old* toolkit loaded, so skills/instructions were stamped against
  the old version and a manual second `update` was needed. The command now
  re-execs the refresh in a fresh `uv run` when the version changes. (DD-049)

### Added
- **Running-vs-pinned version guard.** The CLI now warns (non-blocking) when the
  running toolkit version differs from the version pinned in the hub's
  `pyproject.toml` — catching users who run a global/older `kairos-ontology`
  instead of `uv run kairos-ontology`. (DD-049)

## [3.12.0] — 2026-06-13

### Removed
- **FastAPI service** — removed the `service/` directory and `tests/service/` tests.
  The REST API backend (ontology CRUD, validation, projection, AI chat endpoints) was
  built to support a frontend UI that has been removed. The toolkit CLI and Copilot
  skills are the primary interfaces. (DD-045)

### Added
- **Business discovery phase + company SKOS glossary** — new `kairos-design-discovery`
  skill at the front of the design lifecycle: explores company context and captures the
  company's alternative/business terminology (esp. logistics jargon) as a SKOS glossary
  overlay, without modifying the domain ontology. `kairos-design-mapping` consumes
  `skos:altLabel` as advisory mapping candidates. `init`/`new-repo` create repo-root
  `.imports/businessdiscovery/` and `ontology-hub/model/glossary/`. Added a "clear
  Copilot session" recommendation at the modeling entry points. (DD-048)
- **`kairos-int:` integration extension vocabulary** — new `kairos-int:` namespace
  (`https://kairos.cnext.eu/integration#`) with 22 annotation properties for
  integration pipeline behaviour: load strategy, batching, error handling, retry,
  scheduling, data validation, FK lookup, and sensitive data masking. (DD-045)
- Integration projector emits a new `"integration"` section in mapping JSON (schema v2)
- Dapr projector uses `schedule` and `retryPolicy` annotations for cron bindings
  and resiliency policies
- Scenario tests for integration extension annotations (`test_scenario_integration.py`)
- Vocabulary coverage test for `kairos-int:` annotations
- **`propose-alignment` mapping hints** — opt-in `--include-mapping-hints` flag emits
  deterministic transform hints (passthrough/CAST) and structural candidates
  (split/dedup/multi-target) to seed the `design-mapping` skill. Default output is
  unchanged. (design log DD-045)
- **Reference-model specialization visibility in `design-domain`** — the modeler now
  surfaces reference-model subclasses and their subclass-specific properties (from the
  materialized inventories) at Step 0c.1b, Checkpoint 1, and Checkpoint 3b, steering
  reuse over local duplication. (DD-046)
- **`kairos-ontology check-inventory`** — deterministic pre-flight gate that verifies
  `model/inventory/*.yaml` exists and is current (via a stored `source_sha256`),
  blocking domain modeling against a missing/stale inventory. `generate_inventory()`
  now stamps `source_sha256` into the inventory envelope. (DD-047)
- Tests: `test_propose_alignment_hints.py`, `test_scenario_mapping_hints.py`,
  `test_inventory_freshness.py`, `test_design_domain_skill_contract.py`,
  `test_scenario_specialization.py`
- `docs/instruction-guides/context-engineer-methodology-guide.md` — two-design-model
  methodology + three-tier (deterministic/promptable/judgment) guide

### Removed
- Dead `--catalog` option / `catalog_path` parameter from the `generate-inventory`
  command and `generate_inventory()` (reserved-for-future, never wired)

## [3.9.2] — 2026-06-08

### Fixed
- **CR-005 — SCD2 `source_data` CTE uses aliased column names for SK/IRI** — in SCD2
  silver models, the `source_data` CTE reads `FROM mapped`, where columns are already
  aliased. The projector previously used the original source column name (e.g.
  `uniqueIdentifier`) in `generate_surrogate_key()` and the IRI `CONCAT`, causing a
  runtime T-SQL error (`Invalid column name`). The fix passes `scd_type` into
  `_extract_silver_columns` and skips the source-expression substitution for SCD2 models,
  so SK/IRI correctly reference the aliased names available in `mapped`.

## [3.6.2] — 2026-05-31

### Fixed
- **Single-source column scoping** — entities with one source table now only include
  columns from that table. Previously, inherited properties from other tables generated
  invalid column references in the SQL SELECT.
- **Cross-domain ref() validation** — the post-generation validator no longer emits
  false-positive warnings for `ref()` targets used in FK JOIN clauses (cross-domain
  references). Genuine typos still trigger warnings.

## [3.6.1] — date not recorded

> Date metadata reconciled on 2026-07-21. The previous future date was invalid,
> and no reliable historical release date was available.

### Fixed
- **Cross-table warnings filtered by domain** — the dbt projector's cross-table
  column warning now only fires for properties whose `rdfs:domain` matches the
  current class (or its parents). Previously it warned for ALL column_maps regardless
  of domain, causing 100+ spurious warnings in hubs with many source tables.

### Added
- **Scenario tests for cross-table warnings** — two tests verify the domain filter:
  warnings fire for legitimate cross-table references and stay silent for properties
  belonging to other entities.

## [3.3.0] — 2026-05-30

### Added
- **Extension vocabulary coverage guard** — `tests/test_ext_vocabulary_coverage.py`
  fails if any `kairos-ext` annotation consumed by a projector is undeclared in
  `kairos-ext.ttl`, keeping the vocabulary the single source of truth (DD-034).
- **`docs/design/dd-034-extension-explanation.md`** — hub-author reference for the full
  `kairos-ext:` vocabulary (per-layer annotations, naming conventions, FK-child
  identity guidance, RESERVED list).
- **Context-aware `naturalKey` warning** — the dbt projector now detects FK-child
  entities (targeted by `silverForeignKeyOn`) and names the parent + explains the
  weak-entity / source-identity / embedded options (CR-3 Option 4).

### Changed
- **Declared previously-undeclared gold annotations** in `kairos-ext.ttl`:
  `perspective`, `generateTimeIntelligence`, `olsRestricted` (plus RESERVED
  `incrementalColumn`); marked `surrogateKeyStrategy` and `rolePlayingAs` RESERVED;
  fixed the stale "Silver Layer" header and documented the layer-prefix convention.
- **Standardized** `KAIROS_EXT.term("x")` → `KAIROS_EXT.x` within the dbt projector.

### Decisions
- **DD-034** — extension vocabulary is the single source of truth; `identityStrategy`
  (CR-3) deferred in favour of improved warnings.

### Fixed
- **CI lockfile drift** — raised the `ruff` floor to `>=0.5.0` and regenerated
  `poetry.lock` (ruff `0.1.15` → `0.15.15`). The previously locked ruff `0.1.15`
  was too old for `pytest-ruff 0.5`, which passes `--output-format=full`, breaking
  the `test` job for all files regardless of code changes.

## [2.36.0] — 2026-05-26

### Added

- **Per-domain projection markdown reports** — After projections complete, a
  human-readable markdown report is written to
  `ontology-hub/.sessions-projection/projection-{domain}-{YYYY-MM-DD_HH-MM-SS}.md`
  containing domain info, projection results, warnings, and errors.
- **`.sessions-projection/` folder** — New dedicated folder in the hub for
  projection session reports, created by `init` and `new-repo` commands.
- **Hash-tolerant catalog resolution (DD-024)** — `CatalogResolver` now
  resolves `owl:imports` URIs with or without trailing `#`, preventing silent
  failures when catalog entries and import statements disagree on hash usage.
  A diagnostic warning is logged when hash fallback is needed.

### Changed

- **Renamed `.modeling-sessions/` → `.sessions-modeling/`** — The modeling
  session folder now uses the `.sessions-*` naming convention for consistency.
- **Renamed modeling session files** — From `{domain}-config-{timestamp}.md`
  to `modeling-{domain}-{YYYY-MM-DD}.md` to mirror projection report naming.

## [2.31.0] — 2026-05-19

### Added

- **Shared extension defaults for reference models (DD-023)** — Reference model
  repositories can now ship `*-silver-defaults.ttl` and `*-gold-defaults.ttl`
  files alongside their ontologies. The toolkit auto-discovers these via catalog
  resolution and merges them as a fallback layer beneath hub domain extensions.
- **`resolve_import_paths()` utility** — New public function in `catalog_utils.py`
  that exposes catalog-resolved local paths for `owl:imports` URIs.
- **Layered extension merge** — Merge priority: hub domain ext > reference model
  defaults > built-in projector conventions. Hub annotations always win.

### Changed

- Silver/gold projectors support `silverInclude`/`goldInclude` declared in
  reference model defaults files (inherited by downstream hubs).
- Updated silver and modeling skill documentation with DD-023 guidance.

### Removed

- Obsolete draft documents (`docs/MIGRATION.md`, `docs/TOOLKIT_IMPROVEMENT_SPEC*.md`,
  `docs/medallion-restructure-advisory.md`).

## [2.28.0] — 2026-05-17

### Added

- **Import whitelisting (DD-021)** — Silver and gold projectors now support
  projecting imported classes from reference models (BSP, MMT, DCSA).
  Imported classes require explicit claiming via `kairos-ext:silverInclude` /
  `goldInclude` (per-class) or `silverIncludeImports` / `goldIncludeImports`
  (bulk, ontology-level). Peer hub domain imports are automatically excluded
  from bulk inclusion. See DD-021 in `docs/design/toolkit-design-decisions.md`.
- **4 new `kairos-ext:` annotations** — `silverInclude`, `silverIncludeImports`,
  `goldInclude`, `goldIncludeImports` added to the extension vocabulary.
- **Pre-release publishing** — `release.ps1` supports rc/beta/alpha pre-releases
  with auto-incrementing sequence numbers and PEP 440 version format.
- **Channel system** — hub repos can set `[tool.kairos] channel` in `pyproject.toml`
  to `"stable"` (default), `"preview"`, or an explicit version tag.
- **`update --upgrade`** — resolves the channel to a git tag and upgrades the
  toolkit via pip, updating the `pyproject.toml` dependency pin automatically.
- **Multi-platform dbt** — Fabric (default) and Databricks staging templates
  with platform-specific type maps and cross-platform macros.
- **Branch protection** — `new-repo` auto-configures branch protection on `main`
  (require PR, 1 reviewer, dismiss stale reviews, block force push).
- **Design decisions log** — `docs/design/toolkit-design-decisions.md` (ADR format).

### Fixed

- **Jinja2 `loop.parent`** — replaced invalid attribute with `{% set outer_last %}`
  pattern in staging templates.
- **Empty columns guard** — `columns[0]` unique_key fallback now handles empty lists.

## [2.27.0] — 2026-05-17

### Changed

- **Consolidated modeling skill** — removed separate `kairos-ontology-modeling-config`
  skill; its logic (business alignment checkpoints, session persistence, validation
  gates) is now embedded in the unified `kairos-ontology-modeling` skill with a
  quick-edit mode for minor changes.

## [2.26.1] — 2026-05-17

### Fixed

- **Skill folder naming** — renamed `kairos-ontology-modelling-config` to
  `kairos-ontology-modeling-config` for consistent US English spelling across
  all skill folders, scaffold copies, and copilot-instructions references.

## [2.26.0] — 2026-05-17

### Added

- **Modeling configurator skill** (`kairos-ontology-modeling-config`) — interactive
  modeling workflow with business alignment checkpoints, session persistence
  (`.modeling-sessions/`), and structured validation gates.
- **Reference-model-first workflow** — updated `kairos-ontology-modeling` skill with
  accelerator pack selection, domain mapping tables, OWL catalog imports, and
  business validation steps before any custom modeling.
- **`.modeling-sessions/` folder** — added to scaffold and CLI `init`/`new-repo`
  commands for persisting modeling session state across conversations.

## [2.6.1] — 2026-04-23

### Fixed

- **Mapping terminology** — clarified "source-to-silver mappings (SKOS + kairos-map:)"
  vs "ontology alignment" across medallion-projection, hub-setup, and quickstart skills.
- **Stale directory trees** — fixed hub-setup and quickstart skills still showing old
  `integration/mappings/` and `output/medallion/bronze/` paths.

## [2.6.0] — 2026-04-23

### Added

- **`<nextCatalog>` chaining** — `CatalogResolver` now follows `<nextCatalog>` elements
  recursively, enabling hub-local catalogs to chain to shared reference catalogs.
- **Hub-local catalog support** — `init` and `new-repo` generate
  `ontology-hub/catalog-v001.xml` with `<nextCatalog>` pointing to the shared
  `ontology-reference-models/catalog-v001.xml`. Auto-discovered by `--catalog`.

### Changed

- **Bronze vocabulary relocated** — moved from `output/medallion/bronze/` to
  `integration/sources/{system-name}/` as it is a discovery artifact, not a projection
  output. `_parse_bronze()` now uses `rglob("*.ttl")` on the sources directory.
- **Mappings relocated** — moved from `integration/mappings/` to `model/mappings/` with
  per-source-system subfolders (`model/mappings/{system-name}/`).
- **Mappings README** — clarified dual-purpose design: each mapping file contains both
  SKOS alignment and `kairos-map:` dbt transform annotations.
- Updated all skills (×10), MIGRATION.md, and copilot-instructions.md for new paths.

## [2.3.0] — 2026-04-23

### Added

- **dbt projector rewrite** — complete dbt Core project generation from ontology + bronze
  source system descriptions + SKOS mappings. Generates staging models (views), silver
  entity models (tables), schema YAML with SHACL-derived tests, `dbt_project.yml`, and
  `packages.yml`.
- **`kairos-bronze:` vocabulary** — new namespace (`https://kairos.cnext.eu/bronze#`)
  for describing source system schemas (SourceSystem, SourceTable, SourceColumn).
- **`kairos-map:` vocabulary** — new namespace (`https://kairos.cnext.eu/mapping#`)
  for technical mapping annotations (transform expressions, deduplication, filtering).
- **Bronze directory scaffold** — `bronze/` directory with README and template for
  describing source systems in hub repositories.
- **Updated mappings scaffold** — `mappings/README.md` now documents both external
  vocabulary alignment and bronze-to-silver SKOS mapping patterns.
- **`kairos-dbt-projection` skill** — 4-phase guide for describing bronze sources,
  creating SKOS mappings, running the projection, and validating dbt output.
- **19 new dbt projector tests** — covers bronze parsing, SKOS mapping, SHACL test
  extraction, and full artifact generation (225 total tests).
- **6 new Jinja2 templates** — `sources.yml`, `staging_model.sql`, `silver_model.sql`,
  `schema_models.yml`, `dbt_project.yml`, `packages.yml`.

### Changed

- **dbt staging models materialized as views** (per dbt best practices).
- **SHACL → dbt test mapping** now uses `dbt_expectations` package for regex, length,
  and range constraints (previously used `dbt_utils.expression_is_true`).
- **Projector orchestrator** now auto-discovers `bronze/` and `mappings/` directories
  and passes them to the dbt projector.

## [2.2.2] — 2025-07-26

### Added

- **`update` creates `package.json` if missing** — ensures Mermaid CLI is available
  for silver projection SVG export on existing client repos.
- **`.devcontainer/` scaffold** — new Dev Container config with Python 3.12, Node.js
  LTS, and GitHub CLI. Created by both `init` and `update` commands.

## [2.2.1] — 2025-07-26

### Fixed

- **Namespace detection for hash-fragment ontologies** — `_auto_detect_namespace()`
  now correctly returns `{ontologyURI}#` when classes use `#`-fragment naming
  (e.g. `https://example.com/ont/client#Client`). Previously it truncated to the
  parent path (`https://example.com/ont/`), causing the IMP-1 domain filter to
  match ALL domains with a shared path prefix.

## [2.2.0] — 2025-07-26

### Added

- **GDPR PII validation** (`validate --gdpr`) — scans domain ontologies for
  properties matching PII keywords (first_name, national_id, iban, email, etc.)
  and warns when the owning class lacks a `kairos-ext:gdprSatelliteOf` annotation.
  Runs as part of `validate --all` or standalone with `validate --gdpr`.
- **Projection-time GDPR warning** — the silver projector now emits `logging.warning`
  messages when classes with PII-like properties lack GDPR satellite protection.
- **Explicit annotation mandate** — silver projection skill (Phase 2) updated to
  instruct Copilot to always write every annotation explicitly, even defaults.
  Includes new Phase 2f "Annotation completeness check" step.
- `validate_gdpr()` function added to public API.

### Changed

- **Scaffold template** (`silver-ext.ttl.template`) — audit envelope example now
  uses Spark SQL types (TIMESTAMP, STRING) instead of T-SQL (DATETIME2, NVARCHAR).
  Added `kairos-ext:inlineRefThreshold` ontology-level annotation. All class-level
  examples now show explicit `isReferenceData "false"` for non-reference classes.

## [2.1.1] — 2025-07-26

### Fixed

- **BUG-1: S5/S6 columns on all domains** — `_row_hash` and `_deleted_at` are now
  fixed structural columns, always appended after the audit envelope. Previously
  they were part of the customizable `auditEnvelope` string and could be missing
  when a domain used a pre-v2.1.0 custom audit annotation.
- **BUG-2: Duplicate subtype names** — S3 flattening comment no longer lists the
  same subtype multiple times when a class is reachable via multiple import paths.
- **BUG-3: GDPR satellite breach in imported tables** — Imported classes from
  other namespaces are no longer materialized as tables. This prevents GDPR
  satellite columns (e.g. NaturalPerson PII) from being flattened into
  cross-domain copies where the GDPR annotation is not visible.
- **BUG-4: S4 inlined column names** — Smarter prefix merging avoids redundant
  segments (e.g. `shareholder_property_right_property_right_name_en` →
  `shareholder_property_right_name_en`).

### Changed

- **IMP-1: Canonical schema only** — The projector now only generates tables for
  classes whose URI belongs to the current domain namespace. Imported classes
  become cross-domain FK comment references (e.g. `-- FK: party_sk →
  silver_party.party`). This typically reduces table count by 40-60%.
- `_resolve_external_table` now handles `ref_` prefix for cross-domain reference
  data classes.

## [2.1.0] — 2025-07-26

### Changed

- **Silver Fabric Warehouse rules (S1–S8)** — Major overhaul of silver projector
  targeting MS Fabric Warehouse:
  - **S1**: Spark SQL types — BOOLEAN, TIMESTAMP, STRING, DOUBLE replace T-SQL types
  - **S2**: PK/FK/UNIQUE constraints emitted as DDL comments (Fabric cannot enforce)
  - **S3**: Full inheritance flattening — ALL subtypes merge into parent table with
    auto-generated discriminator column (supersedes R16 empty-subtype-only suppression)
  - **S4**: Inline small reference tables (≤3 business columns) into parent table
  - **S5**: `_row_hash BINARY` column added to audit envelope for incremental MERGE
  - **S6**: `_deleted_at TIMESTAMP` column added for soft-delete tracking
  - **S7**: Canonical schema ownership — no cross-domain table duplication
  - **S8**: No dim_/fact_ prefixes in silver (reserved for Gold layer)

### Added

- **Three-layer rule architecture** — R1–R16 common annotations + S1–S8 Silver
  Fabric behaviours + G1–G8 Gold placeholder rules
- **Gold projection placeholder** — G1–G8 rules documented in skill file for
  future Power BI / dimensional model projector
- `kairos-ext:inlineRefThreshold` annotation property for S4 configuration
- `ref_` prefix now included in `table_name_for()` for consistent FK references

### Fixed

- FK columns to reference tables now correctly use `ref_` prefix in column and
  constraint names (was generating `gender_sk` instead of `ref_gender_sk`)

## [2.0.2] — 2025-07-25

### Fixed

- **Duplicate FK column** — Self-referential properties (e.g. reportsTo, supervisor)
  no longer generate duplicate column names
- **PK/FK collision** — Self-referential FK no longer collides with table PK name
- **Duplicate constraints** — ALTER TABLE no longer emits duplicate FK constraints
- **Nullable annotations** — `kairos-ext:nullable "false"` now correctly generates
  NOT NULL on FK columns

## [2.0.1] — 2025-07-25

### Fixed

- **Non-domain TTL filter** — Projector now skips `*-silver-ext.ttl` and
  `_master.ttl` files when discovering domain ontologies

## [2.0.0] — 2025-07-25

### Changed

- **License**: Migrated from MIT to **Apache License 2.0** as part of Kairos
  Community Edition
- SPDX headers added to all Python source files

### Added

- `NOTICE` file with copyright attribution
- `CONTRIBUTING.md` with contribution guidelines
- `CODE_OF_CONDUCT.md` (Contributor Covenant v2.1)
- `SECURITY.md` with vulnerability reporting policy
- GitHub issue and PR templates

## [1.9.0] — 2025-07-25

### Added

- **Ontology IRI traceability** — All 6 projection targets now include ontology
  IRI, version, and toolkit version in their output
- Per-domain `projection-manifest.json` generated alongside projections
- `extract_ontology_metadata()` helper in projector module

## [1.8.0] — 2025-07-25

### Added

- **R16 — Empty subtype suppression** — Subtypes with no own properties under a
  discriminator-strategy parent are folded into the parent table
- `_has_own_properties()` helper for silver projector

## [1.7.0] — 2025-07-24

### Added

- **Silver ERD generation** — Mermaid ERD diagrams for silver layer
- **SVG export** — Mermaid CLI integration for ERD SVG rendering
- Cross-domain FK relationship labels in ERD diagrams

## [1.6.0] — 2025-07-23

### Added

- **Silver layer projection** — Full DDL generation (R1–R15)
- SCD Type 2 audit envelope columns
- GDPR satellite tables
- Junction tables for many-to-many relationships
- Discriminator-based inheritance

## [1.5.0] — 2025-07-22

### Added

- Multi-domain architecture support
- Domain-scoped projection output folders
- `_master.ttl` catalog for domain registration

## [1.4.0] — 2025-07-21

### Added

- A2UI message schema projection
- Prompt projection for AI chat context

## [1.3.0] — 2025-07-20

### Added

- Azure Search index projection
- Neo4j Cypher schema projection

## [1.2.0] — 2025-07-19

### Added

- dbt model + schema.yml projection
- Jinja2 template system for projections

## [1.1.0] — 2025-07-18

### Added

- SHACL validation support
- Ontology validation CLI command

## [1.0.0] — 2025-07-17

### Added

- Initial release
- OWL/Turtle ontology loading and parsing
- Syntax validation
- CLI with `validate` and `project` commands
- FastAPI service with GitHub repository integration
- Hub scaffolding (`kairos init`)
