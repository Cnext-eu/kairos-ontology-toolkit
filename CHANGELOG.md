# Changelog

All notable changes to the Kairos Ontology Toolkit are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Removed
- **FastAPI service** — removed the `service/` directory and `tests/service/` tests.
  The REST API backend (ontology CRUD, validation, projection, AI chat endpoints) was
  built to support a frontend UI that has been removed. The toolkit CLI and Copilot
  skills are the primary interfaces. (DD-045)

### Added
- **`kairos-int:` integration extension vocabulary** — new `kairos-int:` namespace
  (`https://kairos.cnext.eu/integration#`) with 22 annotation properties for
  integration pipeline behaviour: load strategy, batching, error handling, retry,
  scheduling, data validation, FK lookup, and sensitive data masking. (DD-045)
- Integration projector emits a new `"integration"` section in mapping JSON (schema v2)
- Dapr projector uses `schedule` and `retryPolicy` annotations for cron bindings
  and resiliency policies
- Scenario tests for integration extension annotations (`test_scenario_integration.py`)
- Vocabulary coverage test for `kairos-int:` annotations

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

## [3.6.1] — 2026-07-27

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
