# Changelog

All notable changes to the Kairos Ontology Toolkit are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
