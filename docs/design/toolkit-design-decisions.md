# Toolkit Design Decisions

This document is the **canonical log** of architectural and design decisions for the
Kairos Ontology Toolkit. Each decision is recorded as an Architecture Decision Record
(ADR) with context, rationale, and current status.

> **Maintenance rule:** Update this file in every PR that introduces or modifies a
> design decision. See `.github/copilot-instructions.md` for the PR checklist.

## How to Keep This File Organised

### Adding a new decision

1. **Assign the next sequential DD number** — check the last entry in the Index below.
2. **Add a row to the Index table** — keep it in numeric order.
3. **Add the full entry** at the bottom of the file (above the Template section),
   using the template provided at the end.
4. **Companion doc** (optional) — if the decision needs a longer architectural
   specification, create `docs/design/dd-NNN-short-slug.md` and reference it in
   the `Implementation:` field. Always prefix the file with `dd-NNN-`.

### Keeping the Index in sync

The Index table below **must** match the `## DD-NNN` headings in the body:
- Same DD number, same title, same status, same date.
- The anchor link format is: `#dd-nnn-title-in-lowercase-with-dashes`.
- When you update a status (e.g., Proposed → Accepted), update **both** the Index
  row and the `**Status:**` line in the body.

### Superseding a decision

- Set the old decision's status to `~~Superseded by [DD-XXX](#dd-xxx-...)~~`.
- Keep the old entry in the file (don't delete) — it provides historical context.
- The new decision should mention what it supersedes in its Context section.

### Companion files naming

Files in `docs/design/` that elaborate on a specific decision **must** be named:
```
dd-NNN-descriptive-slug.md
```
This makes it immediately clear which decision they belong to. Files without a
`dd-NNN-` prefix will be considered orphaned and may be removed during cleanup.

---

## Index

| ID | Title | Status | Date |
|----|-------|--------|------|
| [DD-001](#dd-001-gold-layer-inheritance--class-per-table) | Gold Layer Inheritance — Class-Per-Table | Proposed | 2026-04-25 |
| [DD-002](#dd-002-dbt-sql-dialect--platform-specific-generation) | dbt SQL Dialect — Platform-Specific Generation | Accepted | 2026-04-30 |
| [DD-003](#dd-003-staging--platform-specific-silver--portable) | Staging = Platform-Specific, Silver = Portable | ~~Superseded by DD-014~~ | 2026-04-30 |
| [DD-004](#dd-004-keep-staging-naming-not-bronze) | Keep "staging" Naming (Not "bronze") | ~~Superseded by DD-014~~ | 2026-04-30 |
| [DD-005](#dd-005-silver-references-staging-directly) | Silver References Staging Directly | ~~Superseded by DD-014~~ | 2026-04-30 |
| [DD-006](#dd-006-column-level-json-not-table-level-physicalstorage) | Column-Level JSON, Not Table-Level physicalStorage | Accepted | 2026-04-30 |
| [DD-007](#dd-007-extend-kairos-ext-namespace) | Extend kairos-ext Namespace | Accepted | 2026-04-30 |
| [DD-008](#dd-008-generated-macros-alongside-models) | Generated Macros Alongside Models | Accepted | 2026-04-30 |
| [DD-009](#dd-009-fabric-first-default-platform) | Fabric-First Default Platform | Accepted | 2026-04-30 |
| [DD-010](#dd-010-branch-protection-on-new-repo) | Branch Protection on new-repo | Accepted | 2026-04-30 |
| [DD-011](#dd-011-silver-output-inside-dbt-tree) | Silver Output Inside dbt Tree | Accepted | 2026-04-28 |
| [DD-012](#dd-012-non-fatal-github-operations) | Non-Fatal GitHub Operations | Accepted | 2026-04-30 |
| [DD-013](#dd-013-pre-release-publishing-via-git-tags--channel-system) | Pre-Release Publishing via Git Tags + Channel System | Accepted | 2026-05-01 |
| [DD-014](#dd-014-eliminate-staging--silver-reads-bronze-directly) | Eliminate Staging — Silver Reads Bronze Directly | Accepted | 2026-05-14 |
| [DD-015](#dd-015-vocabulary-ttl-as-bronze-contract) | Vocabulary TTL as Bronze Contract | Accepted | 2026-05-14 |
| [DD-016](#dd-016-stale-managed-skill-cleanup-during-update) | Stale Managed Skill Cleanup During Update | Accepted | 2026-05-14 |
| [DD-017](#dd-017-dataplatform-integration--two-deliverable-packages--copilot-agent) | Dataplatform Integration — Two Deliverable Packages + Copilot Agent | Accepted | 2026-04-30 |
| [DD-018](#dd-018-silver-model-granularity--entity-centric-with-multi-source-split) | Silver Model Granularity — Entity-Centric with Multi-Source Split | Accepted | 2026-04-30 |
| [DD-019](#dd-019-cross-domain-fk-resolution-via-surrogate-key-joins) | Cross-Domain FK Resolution via Surrogate Key Joins | Accepted | 2026-05-01 |
| [DD-020](#dd-020-stable-ontology-iris--no-version-in-namespace) | Stable Ontology IRIs — No Version in Namespace | Accepted | 2026-05-01 |
| [DD-021](#dd-021-extension-as-whitelist-for-imported-class-projection) | Extension-as-Whitelist for Imported Class Projection | Proposed | 2026-05-01 |
| [DD-022](#dd-022-simplified-fk-annotations-for-silver-projection) | Simplified FK Annotations for Silver Projection | Proposed | 2026-05-01 |
| [DD-023](#dd-023-shared-extension-defaults-for-reference-models) | Shared Extension Defaults for Reference Models | Proposed | 2026-05-19 |
| [DD-024](#dd-024-hash-tolerant-catalog-resolution) | Hash-Tolerant Catalog Resolution | Accepted | 2026-05-26 |
| [DD-025](#dd-025-scd-type-aware-dbt-silver-models) | SCD Type-Aware dbt Silver Models | Proposed | 2026-05-26 |
| [DD-026](#dd-026-silver-layer-accuracy--mapped-only-columns-fk-parity-and-scd2-history-preservation) | Silver Layer Accuracy — Mapped-Only Columns, FK Parity, and SCD2 History Preservation | Accepted | 2026-05-27 |
| [DD-027](#dd-027-cross-domain-peer-extension-loading-for-fk-resolution) | Cross-Domain Peer Extension Loading for FK Resolution | Accepted | 2026-05-27 |
| [DD-028](#dd-028-multi-table-same-source-union-model-disambiguation) | Multi-Table Same-Source Union Model Disambiguation | Accepted | 2026-05-27 |
| [DD-029](#dd-029-silver-model-registry-for-gold-ref-resolution) | Silver Model Registry for Gold ref() Resolution | Accepted | 2026-05-28 |
| [DD-030](#dd-030-rewriteuri-catalog-resolution-with-extension-fallback) | rewriteURI Catalog Resolution with Extension Fallback | Accepted | 2026-05-29 |
| [DD-031](#dd-031-inherit-naturalkey-from-discriminator-parents) | Inherit naturalKey from Discriminator Parents | Accepted | 2026-05-29 |
| [DD-032](#dd-032-reference-model-inspired--local-pattern-adoption-from-reference-models) | Reference Model Inspired — Local Pattern Adoption from Reference Models | Accepted | 2026-05-30 |
| [DD-033](#dd-033-replace-alignment-files-with-rdfsseealso-on-inspired-classes) | Replace Alignment Files with rdfs:seeAlso on Inspired Classes | Accepted | 2026-05-30 |
| [DD-034](#dd-034-extension-vocabulary-is-the-single-source-of-truth-defer-identitystrategy) | Extension Vocabulary is the Single Source of Truth; Defer `identityStrategy` | Accepted | 2026-05-30 |
| [DD-035](#dd-035-silver-s3-inheritance-gate--respect-inheritancestrategy-annotation) | Silver S3 Inheritance Gate — Respect `inheritanceStrategy` Annotation | Accepted | 2026-05-30 |
| [DD-036](#dd-036-drop-git-submodules-for-reference-models) | Drop Git Submodules for Reference Models | Accepted | 2026-05-31 |
| [DD-037](#dd-037-uv-as-standard-environment-manager-for-hub-repos) | uv as Standard Environment Manager for Hub Repos | Accepted | 2026-05-31 |
| [DD-038](#dd-038-bronze-source-introspection--layered-dbt-architecture) | Bronze Source Introspection & Layered dbt Architecture | Proposed | 2026-06-01 |
| [DD-039](#dd-039-enhanced-schema-extraction-with-json-flattening--bronze-expanded-layer) | Enhanced Schema Extraction with JSON Flattening & Bronze Expanded Layer | Accepted | 2026-06-02 |
| [DD-040](#dd-040-skill-lifecycle-architecture--design--execute-separation) | Skill Lifecycle Architecture — Design / Execute Separation | Accepted | 2026-05-30 |
| [DD-041](#dd-041-llm-powered-source-affinity-analysis--coverage-reporting) | LLM-powered Source Affinity Analysis & Coverage Reporting | Accepted | 2026-06-04 |
| [DD-042](#dd-042-table-centric-source-classification-with-module-class-grounding) | Table-centric source classification with module-class grounding | Accepted | 2026-06-05 |
| [DD-043](#dd-043-propose-alignment--pre-modeling-column-to-property-matching) | Propose-alignment — pre-modeling column-to-property matching | Accepted | 2026-06-05 |
| [DD-044](#dd-044-reference-model-specialization-discovery--materialized-inventories) | Reference Model Specialization Discovery & Materialized Inventories | Proposed | 2026-06-12 |
| [DD-045](#dd-045-mapping-hints-for-propose-alignment) | Mapping Hints for propose-alignment | Accepted | 2026-06-13 |
| [DD-046](#dd-046-reference-model-specialization-visibility-in-domain-modeling) | Reference Model Specialization Visibility in Domain Modeling | Accepted | 2026-06-13 |
| [DD-047](#dd-047-deterministic-inventory-freshness-pre-flight-gate) | Deterministic Inventory Freshness Pre-flight Gate | Accepted | 2026-06-13 |

---

## DD-001: Gold Layer Inheritance — Class-Per-Table

**Status:** Proposed  
**Date:** 2026-04-25  
**Affects:** `gold_projector.py`, TMDL output, Power BI relationships  
**Implementation:** `src/kairos_ontology/projections/medallion_gold_projector.py`

### Context

The gold projector (G5 rule) originally flattened OWL `rdfs:subClassOf` hierarchies
into a single parent table with a discriminator column (mirroring silver S3). This
creates wide, sparse tables that don't align with the ontology structure.

### Decision

Change G5 default to **class-per-table**: each subclass becomes a separate gold
table extending the parent table via a shared primary key.

### PK/FK Design — Shared PK

The subtype table's PK is the same surrogate key column as the parent table (1:1 FK):

```
dim_party (party_sk PK)
    ↑ 1:1
dim_legal_entity (party_sk PK+FK, registration_number, ...)
```

**Rationale:**
- Mirrors the ontological 1:1 subclass relationship
- Simpler JOINs, no surrogate key proliferation
- Standard star-schema pattern for type-2 subtypes

### Opt-out

`kairos-ext:goldInheritanceStrategy "discriminator"` switches back at ontology or class level.

### Open Questions

1. Should some hierarchies use own SK instead of shared PK?
2. Should parent include discriminator column even in class-per-table mode?
3. SCD Type 2 interaction with class-per-table?

---

## DD-002: dbt SQL Dialect — Platform-Specific Generation

**Status:** Accepted  
**Date:** 2026-04-30  
**Affects:** `medallion_dbt_projector.py`, silver/gold templates, type maps  
**Implementation:** Type maps `_SOURCE_TO_FABRIC`, `_SOURCE_TO_DATABRICKS`, `_PLATFORM_TYPE_MAPS`

### Context

dbt Core does NOT abstract SQL dialects. Model `.sql` files are sent verbatim to
the target warehouse engine. Different platforms use fundamentally different:
- Type names (VARCHAR vs STRING, BIT vs BOOLEAN)
- JSON functions (OPENJSON + CROSS APPLY vs EXPLODE(FROM_JSON(...)))
- String concatenation, row limiting

### Decision

Generate **platform-specific SQL** controlled by a `target_platform` parameter:
- `"fabric"` (default) — T-SQL dialect for `dbt-fabric` adapter
- `"databricks"` — Spark SQL dialect for `dbt-databricks` adapter

### What dbt DOES Abstract (safe to share)

- CTE syntax, CASE WHEN, `dbt_utils.generate_surrogate_key()`
- Materialization strategies, `ref()` / `source()` resolution

### What dbt Does NOT Abstract (must be platform-specific)

| Concern | Fabric (T-SQL) | Databricks (Spark SQL) |
|---------|----------------|------------------------|
| String type | VARCHAR | STRING |
| Boolean | BIT | BOOLEAN |
| Timestamp | DATETIME2 | TIMESTAMP |
| JSON array | `CROSS APPLY OPENJSON(col) WITH (...)` | `LATERAL VIEW EXPLODE(FROM_JSON(col, schema))` |
| JSON value | `JSON_VALUE(col, '$.path')` | `GET_JSON_OBJECT(col, '$.path')` |

---

## DD-003: Staging = Platform-Specific, Silver = Portable

**Status:** ~~Superseded by [DD-014](#dd-014-eliminate-staging--silver-reads-bronze-directly)~~  
**Date:** 2026-04-30  
**Affects:** Template selection logic in `_gen_staging_models()`, silver model generation  
**Implementation:** `staging_model.sql.jinja2` (Fabric), `staging_model_databricks.sql.jinja2`

### Context

Should we generate one set of models for all platforms or separate per platform?

### Decision

**Superseded.** The staging layer has been removed entirely (see DD-014).
Silver now reads directly from bronze and handles all platform-specific logic
via `dbt_utils` macros and generated platform macros.

Original decision was: Platform-specific staging templates, portable silver via `dbt_utils`.

---

## DD-004: Keep "staging" Naming (Not "bronze")

**Status:** ~~Superseded by [DD-014](#dd-014-eliminate-staging--silver-reads-bronze-directly)~~  
**Date:** 2026-04-30  
**Affects:** dbt model naming convention, folder structure  
**Implementation:** N/A — staging layer removed

### Context

Medallion architecture uses "bronze" but dbt community uses "staging" for the first
transform layer.

### Decision

**Superseded.** There is no staging layer in the dbt project. Bronze is managed by
the data platform (outside dbt). Silver is the first dbt layer and reads from bronze
directly via `{{ source() }}`. See DD-014.

---

## DD-005: Silver References Staging Directly

**Status:** ~~Superseded by [DD-014](#dd-014-eliminate-staging--silver-reads-bronze-directly)~~  
**Date:** 2026-04-30  
**Affects:** Silver model generation, dbt DAG structure  
**Implementation:** Silver models use `{{ source('system', 'table') }}` directly

### Context

Should silver models reference staging directly or go through a bridge layer?

### Decision

**Superseded.** Silver now references bronze directly via `{{ source() }}` — there
is no staging layer at all. See DD-014.

---

## DD-006: Column-Level JSON, Not Table-Level physicalStorage

**Status:** Accepted  
**Date:** 2026-04-30  
**Affects:** `kairos-bronze:` vocabulary, staging template JSON handling  
**Implementation:** `kairos-bronze:contentType` annotation on columns

### Context

When Data Factory lands data, some columns remain as JSON strings. How to annotate?

### Decision

Use **column-level** `kairos-bronze:contentType`:
- `"json-array"` — JSON array to be expanded (OPENJSON / EXPLODE)
- `"json-object"` — JSON object to be destructured
- (default: scalar, no annotation)

Do NOT add a table-level `physicalStorage` property.

### Rationale

- Data Factory flattens most structures at ingestion
- Only individual columns end up as embedded JSON
- Column-level is more precise and actionable for code generation

---

## DD-007: Extend kairos-ext Namespace

**Status:** Accepted  
**Date:** 2026-04-30  
**Affects:** Annotation vocabulary, `scaffold/kairos-ext.ttl`  
**Implementation:** New properties in `kairos-ext:` namespace

### Context

New annotations needed (`populationRequirement`, `derivationFormula`, `naturalKey`).
Should these go in a new namespace or extend `kairos-ext:`?

### Decision

Extend `kairos-ext:` namespace.

### Rationale

- Same domain as existing kairos-ext properties (projection control)
- Fewer prefixes for hub authors
- `kairos-ext:` is well-established

---

## DD-008: Generated Macros Alongside Models

**Status:** Accepted  
**Date:** 2026-04-30  
**Affects:** dbt output structure, `macros/` folder generation  
**Implementation:** `templates/dbt/macros/kairos_*.sql`

### Context

Silver models need platform-abstraction macros. How to deliver them?

### Decision

Generate a `macros/` folder inside the dbt output directory with:
- `kairos_safe_cast(column, type)` — platform-aware TRY_CAST
- `kairos_json_extract(column, path)` — JSON_VALUE vs GET_JSON_OBJECT
- `kairos_surrogate_key(columns)` — dbt_utils wrapper
- `kairos_concat(values)` — string concatenation

Macros use `{% if target.type == '...' %}` for platform dispatch.

### Rationale

- No external package dependency beyond dbt-utils
- Macros versioned with generated output
- Hub repos don't need separate dbt package installs
- Regenerated with `kairos-ontology project`

---

## DD-009: Fabric-First Default Platform

**Status:** Accepted  
**Date:** 2026-04-30  
**Affects:** `DEFAULT_PLATFORM` constant, dbt_project.yml scaffold  
**Implementation:** `medallion_dbt_projector.py: DEFAULT_PLATFORM = "fabric"`

### Context

Need a sensible default when `target_platform` is not explicitly set.

### Decision

Default to **Microsoft Fabric** (`"fabric"`).

### Rationale

- Primary deployment target for Kairos Community Edition users
- T-SQL is the dominant SQL dialect in the Microsoft data ecosystem
- Databricks users must opt-in with `target_platform="databricks"`
- Fabric is the target for DirectLake + Power BI gold layer

---

## DD-010: Branch Protection on new-repo

**Status:** Accepted  
**Date:** 2026-04-30  
**Affects:** `cli/main.py` new-repo command, `_configure_branch_protection()`  
**Implementation:** `gh api` REST calls for repo settings + branch protection rules

### Context

New ontology hub repos should follow Git best practices from creation. Manual setup
of branch protection is error-prone and often forgotten.

### Decision

Automatically configure branch protection on `main` during `new-repo`:

1. **Enable `delete_branch_on_merge`** — auto-cleanup after PR merge
2. **Branch protection on main:**
   - Require PR (no direct push)
   - 1 required reviewer
   - Dismiss stale reviews on new commits
   - Require branch up-to-date before merge
   - Block force push & branch deletion
   - Allow admin bypass for emergencies
3. **Verify protection is active**

### Opt-out

`--skip-protection` flag for users without admin rights or when using GitHub Free
(which doesn't support all protection features).

### Non-fatal Design

Protection failures warn but do not abort repo creation (see DD-012).

---

## DD-011: Silver Output Inside dbt Tree

**Status:** Accepted  
**Date:** 2026-04-28  
**Affects:** Output directory structure, `projector.py` path logic  
**Implementation:** Silver DDL → `output/medallion/dbt/analyses/{domain}/`, ERD → `docs/diagrams/`

### Context

Previously, silver DDL and ERD lived in a separate `output/medallion/silver/`
directory outside the dbt project. This created confusion about which location
was authoritative for the silver schema.

### Decision

Consolidate all silver artifacts inside the dbt project tree:

| Artifact | Location |
|----------|----------|
| Silver DDL (CREATE TABLE) | `output/medallion/dbt/analyses/{domain}/` |
| ALTER TABLE (FK scripts) | `output/medallion/dbt/analyses/{domain}/` |
| ERD diagrams | `output/medallion/dbt/docs/diagrams/{domain}/` |
| Master ERD | `output/medallion/dbt/docs/diagrams/` |

### Rationale

- Single dbt project tree as source of truth
- `analyses/` is dbt's convention for reference SQL that isn't part of the DAG
- Diagrams in `docs/` are linkable from schema YAML documentation
- No separate `medallion/silver/` directory to confuse users

---

## DD-012: Non-Fatal GitHub Operations

**Status:** Accepted  
**Date:** 2026-04-30  
**Affects:** `_configure_branch_protection()`, `_add_reference_models()`  
**Implementation:** try/except with warning prints, non-zero exit avoided

### Context

Several operations in `new-repo` depend on external services (GitHub API, network)
or features that may not be available (e.g., branch protection on free plan).

### Decision

GitHub API operations that are **supplementary** (not core to repo creation) use a
**warn-and-continue** pattern:

```python
try:
    subprocess.run([...], check=True)
    print("  ✓ Operation succeeded")
except subprocess.CalledProcessError as exc:
    print(f"  ⚠ Operation failed: {reason}")
    # Continue — don't abort repo creation
```

### Which operations are non-fatal?

| Operation | Fatal? | Rationale |
|-----------|--------|-----------|
| `gh repo create` | ✅ Fatal | Repos must be on GitHub |
| `git init` / `git commit` | ✅ Fatal | Core functionality |
| Branch protection | ⚠️ Non-fatal | Free plan can't use it |
| Reference models submodule | ⚠️ Non-fatal | Not required for a valid hub |
| SmartCoding update script | ⚠️ Non-fatal | Optional enhancement |

### Rationale

- Users shouldn't lose a fully scaffolded repo because branch protection failed
- Clear warning messages tell users what to fix manually
- `--skip-protection` provides explicit opt-out

---

## DD-013: Pre-Release Publishing via Git Tags + Channel System

**Status:** Accepted  
**Date:** 2026-05-01  
**Affects:** `release.ps1`, `.github/workflows/release.yml`, scaffold `pyproject.toml.template`, `cli/main.py` update command  
**Implementation:** Tag-based pre-releases, `[tool.kairos] channel` in hub pyproject.toml

### Context

The toolkit needs a mechanism to publish pre-release versions that hub repos can
opt into for testing before a GA release. Options considered:
1. TestPyPI — adds infrastructure complexity, separate index config
2. Git tags only — simple, already supported by pip's git URL scheme
3. Separate branches — complex merge workflow, version confusion

### Decision

Use **git tag-based pre-releases** with a **channel system**:

| Component | Mechanism |
|-----------|-----------|
| Pre-release tagging | `release.ps1` option [4], tags like `v2.17.0-rc.1` |
| PEP 440 version | `2.17.0rc1` (in pyproject.toml / __init__.py) |
| GitHub Release | Marked as pre-release, skips PyPI publish |
| Channel config | `[tool.kairos] channel = "stable"` or `"preview"` in hub pyproject.toml |
| Resolution | `kairos-ontology update --upgrade` resolves via `gh api /repos/.../releases` |
| Dependency pin | Hub pyproject.toml pins to `@v2.17.0` (tag-based, not `@main`) |

### Version format mapping

| Label | Git tag | PEP 440 |
|-------|---------|---------|
| Release candidate | `v2.17.0-rc.1` | `2.17.0rc1` |
| Beta | `v2.17.0-beta.1` | `2.17.0b1` |
| Alpha | `v2.17.0-alpha.1` | `2.17.0a1` |

### Rationale

- No TestPyPI infrastructure needed — `pip install git+...@tag` works natively
- Channels are per-repo (version-controlled in pyproject.toml), not per-user
- `stable` (default) = existing behavior for production hubs
- `preview` = explicit opt-in for testing pre-releases
- Pre-releases skip PyPI publish (avoids polluting the public index)
- `@main` deprecated in favor of tag pins for reproducibility

---

## DD-014: Eliminate Staging — Silver Reads Bronze Directly

**Status:** Accepted  
**Date:** 2026-05-14  
**Affects:** `medallion_dbt_projector.py`, dbt templates, generated project structure  
**Implementation:** `_gen_silver_models()` uses `{{ source() }}`, `_gen_staging_models()` removed from pipeline  
**Supersedes:** DD-003, DD-004, DD-005

### Context

The original dbt projector generated a **staging layer** (`stg_*` models) between
bronze sources and silver entity models. Staging performed rename + type cast as
materialized views, and silver then referenced staging via `{{ ref('stg_...') }}`.

This created several issues:
1. **Redundant layer** — the rename/cast logic is simple enough to inline in silver
2. **Confusing ownership** — staging models were dbt-managed but conceptually part
   of the source-system world, blurring the platform ↔ dbt boundary
3. **Double materialization** — views still have execution cost in some platforms
4. **Maintenance burden** — two template families (Fabric + Databricks staging)

### Decision

**Remove the staging layer entirely.** Silver is the first dbt layer and reads
directly from bronze tables via `{{ source('system', 'table') }}`.

| Before | After |
|--------|-------|
| Bronze → `stg_*` (view) → Silver (table) → Gold | Bronze → Silver (table) → Gold |
| `models/staging/{source}/stg_{source}__{table}.sql` | ❌ Removed |
| `_sources.yml` with full column detail | Minimal `_sources.yml` (table refs only) |
| Silver uses `{{ ref('stg_...') }}` | Silver uses `{{ source('...', '...') }}` |

### What Silver Absorbs

Silver models now handle all transform logic inline:
- Column renaming (bronze name → domain snake_case name)
- Type casting via `TRY_CAST` (using original bronze column names)
- Transform expressions from SKOS mappings (applied directly)
- Multi-source UNION/JOIN from multiple bronze tables

### Generated Project Structure

```
models/
├── silver/
│   ├── _sources.yml         # Minimal: database + schema + table only
│   └── {domain}/
│       ├── {entity}.sql     # Reads from {{ source() }}
│       └── _models.yml      # Schema + tests
└── gold/
    └── {domain}/
        ├── dim_{entity}.sql
        └── fact_{entity}.sql
```

### Breaking Change

Existing hub repos with generated dbt artifacts must **regenerate** after upgrading.
The `models/staging/` directory and all `stg_*` files should be deleted.

### Rationale

- Simpler DAG (fewer nodes, less materialization cost)
- Clear boundary: Bronze = platform, Silver = dbt
- Vocabulary TTL is the authoritative bronze contract (see DD-015)
- One fewer template family to maintain
- Silver SQL is still readable — transforms are column expressions, not complex joins

---

## DD-015: Vocabulary TTL as Bronze Contract

**Status:** Accepted  
**Date:** 2026-05-14  
**Affects:** `integration/sources/`, `_sources.yml` generation, silver model generation  
**Implementation:** `_parse_bronze()` reads vocabulary TTL; `_gen_sources()` generates minimal YAML

### Context

With the staging layer removed (DD-014), dbt `_sources.yml` becomes minimal — it only
declares database, schema, and table names for `{{ source() }}` resolution. But the dbt
pipeline still needs to know bronze table structure (columns, types, keys) to generate
correct silver SQL.

### Decision

The **`*.vocabulary.ttl`** files in `integration/sources/{system}/` are the **single
source of truth** for bronze table structure. This is a foundational contract:

| Artifact | Role | Column detail? |
|----------|------|----------------|
| `*.vocabulary.ttl` (kairos-bronze: namespace) | **Authoritative** — tables, columns, types, keys | ✅ Yes |
| `_sources.yml` (dbt) | **Minimal reference** — connection info only | ❌ No |
| SKOS mappings (`model/mappings/`) | **Transform rules** — how bronze maps to domain | References vocab URIs |

### Implications

1. **Vocabulary must stay in sync with actual bronze tables** — if the data platform
   team adds/removes/renames a column, the vocabulary TTL must be updated first.
2. **Regeneration workflow**: update vocabulary → update mappings → run `kairos-ontology project`
   → commit generated silver SQL.
3. **dbt `_sources.yml` is NOT the documentation layer** — use vocabulary TTL for
   column-level documentation and lineage.
4. **Silver SQL references original bronze column names** — transforms use actual column
   names from the vocabulary (e.g., `ClientID`, not `client_id`).

### Rationale

- Single source of truth avoids drift between dbt YAML and actual bronze schema
- Vocabulary TTL is version-controlled alongside mappings in the ontology hub
- RDF/OWL tooling can validate vocabulary completeness and consistency
- Minimal `_sources.yml` reduces noise and maintenance

---

## DD-016: Stale Managed Skill Cleanup During Update

**Status:** Accepted  
**Date:** 2026-05-14  
**Affects:** `cli/main.py` update command  
**Implementation:** Stale skill scan after managed-file sync in `update()`

### Context

When the toolkit renames or removes a skill from the scaffold, the `update`
command previously only added/updated files — it never removed stale skills.
This left orphaned skill directories in hub repos (e.g., `kairos-toolkit-update`
persisting when the scaffold renamed it to `kairos-ontology-toolkit-ops`).

### Decision

After syncing managed files, `update` scans `.github/skills/` for directories
whose `SKILL.md` contains the managed marker (`kairos-ontology-toolkit:managed`)
but whose name is NOT in the current scaffold skills list. These are removed.

| Skill type | Has managed marker? | In scaffold? | Action |
|------------|-------------------|--------------|--------|
| Current toolkit skill | ✅ | ✅ | Updated normally |
| Renamed/removed toolkit skill | ✅ | ❌ | **Deleted** |
| User custom skill | ❌ | ❌ | Left untouched |

### `--check` Mode

In `--check` mode, stale skills are reported but not removed, and the exit
code is non-zero (same as outdated/missing files).

### Rationale

- Safe: only removes files the toolkit created (marker-based identification)
- Automatic: no manual list of removed skills to maintain
- Consistent: `update` is already the explicit user action for syncing

---

## DD-017: Dataplatform Integration — Two Deliverable Packages + Copilot Agent

**Status:** Accepted  
**Date:** 2026-04-30  
**Affects:** scaffold workflows, issue templates, CLI `init`/`new-repo` commands  
**Implementation:** `scaffold/github-workflows/release-projections.yml`, `assign-copilot.yml`, `copilot-setup-steps.yml`, `scaffold/github-issue-templates/ontology-gap-request.yml`, `cli/main.py`

### Context

The ontology-hub generates medallion projections (dbt models, Power BI TMDL, DDL) that
a downstream **dataplatform** repo needs to consume. There was no defined integration
mechanism — no release pipeline, no feedback loop for gap requests, and no automation
for implementing ontology changes requested by the dataplatform team.

### Decision

Introduce a **two-deliverable packaging model** with a **tag-triggered release pipeline**
and **Copilot coding agent automation** for gap-request implementation:

| Component | Mechanism |
|-----------|-----------|
| **Deliverable 1: dbt package** | Consumed via `dbt deps` with git package + `revision:` tag pin |
| **Deliverable 2: Power BI semantic model** | Zip artifact attached to GitHub Release (TMDL files) |
| **Release pipeline** | Tag-triggered (`v*`) workflow: project → validate → package → GitHub Release |
| **Feedback loop** | Structured issue template (`ontology-gap-request.yml`) for cross-repo gap requests |
| **Copilot agent** | Label `copilot-implement` → assign `@copilot` → agent implements → draft PR |
| **Agent environment** | `copilot-setup-steps.yml` installs Python + toolkit + Node.js |

### Scaffold Files Added

| File | Purpose |
|------|---------|
| `github-workflows/release-projections.yml` | Tag-triggered release: projections + validate + zip + GitHub Release |
| `github-workflows/assign-copilot.yml` | Label-triggered: assigns `@copilot` to implement gap requests |
| `github-workflows/copilot-setup-steps.yml` | Agent development environment (Python 3.12, toolkit, Node.js) |
| `github-issue-templates/ontology-gap-request.yml` | Structured form: domain, layer, description, justification |

### Key Design Choices

1. **Copilot creates a draft PR** (not "no PR") — this is native agent behaviour and
   cannot be suppressed. The draft PR is the review mechanism.

2. **`copilot-setup-steps.yml` is critical** — without it, the agent cannot install the
   toolkit, validate ontologies, or run projections. The job MUST be named
   `copilot-setup-steps` for GitHub to recognise it.

3. **Cross-repo issue creation is the dataplatform's responsibility** — the ontology-hub
   only receives issues. The dataplatform repo uses a PAT or GitHub App to create issues
   on the ontology-hub via `gh issue create --repo`.

4. **Label-triggered assignment is optional** — maintainers can assign `@copilot` directly
   from the GitHub UI. The workflow adds automation for teams preferring label-based triage.

5. **Both deliverables share a single version tag** — if independent versioning is needed
   later, the release workflow can be split.

### Rationale

- **dbt deps** is the native, standard mechanism for dbt package consumption (vs git submodules)
- **Tag-triggered** releases are intentional (not every merge creates a release)
- **Copilot agent** reduces human effort for routine ontology changes (add property, add constraint)
- **Issue templates** enforce structured gap requests — giving the agent clear context
- **`copilot-setup-steps.yml`** follows GitHub's official best practice for agent environment config

### Consequences

- Hub repos must have Copilot Business/Enterprise for the agent features
- The Power BI package format is concept-level; deployment tooling will be refined later
- The `copilot-implement` label must be created manually in new repos (not auto-created by scaffold)

---

## DD-018: Silver Model Granularity — Entity-Centric with Multi-Source Split

**Status:** Accepted  
**Date:** 2026-04-30 (updated 2026-05-01)  
**Affects:** `medallion_dbt_projector.py`, silver model generation, dbt package structure  
**Implementation:** `src/kairos_ontology/projections/medallion_dbt_projector.py`

### Context

When multiple integration sources map to the same domain class (e.g., `Harmoney.Customers`
and `AdminPulse.Klanten` both map to `domain:Client`), the dbt projector must decide how
to structure the silver SQL models:

- **Entity-centric** — one `client.sql` per domain class, with multiple source CTEs inside.
- **Source-centric** — one model per source-entity combination (`client__from_harmoney.sql`,
  `client__from_adminpulse.sql`), plus a union model.

### Decision

**Single source (default):** Entity-centric silver models. Each domain class produces
exactly one `.sql` file under `models/silver/{domain}/`.

**Multi-source (automatic):** When two or more bronze tables map to the same domain class,
the projector automatically generates:

1. Per-source view models: `models/silver/{domain}/{entity}__from_{source}.sql`
   — materialized as views, rename/cast/normalize columns to match target schema
2. A union model: `models/silver/{domain}/{entity}.sql`
   — `UNION ALL` of per-source refs, adds SK/IRI columns on normalised target names

The split is triggered automatically by mapping count, not by a CLI flag.

### Rationale

| Approach | Pros | Cons |
|----------|------|------|
| Entity-centric (single source) | Single source of truth for gold; built-in dedup; fewer files | Harder per-source debugging with many sources |
| Per-source views + union (multi-source) | Per-source lineage & testing; independent source ownership; `dbt run -s client__from_adminpulse` | Extra union step; more generated files |

The entity-centric model is preserved as the default for the common single-source case.
Multi-source automatically splits to enable per-source debugging and lineage. SK/IRI
columns are computed in the union model on normalised target column names, ensuring
consistent keys regardless of source column naming.

### Key design choices

1. **Per-source models are views** — zero materialization cost; the union model is the
   materialized `table`.
2. **Unmapped optional columns → `CAST(NULL AS type)`** — maintains column alignment
   across UNION ALL branches.
3. **SK/IRI only in union model** — avoids duplicate key computation; keys are
   source-agnostic.
4. **FK joins only in union model** — applied after union on normalised column names.
5. **Naming convention:** `{entity}__from_{snake_source}` (double underscore matches
   dbt convention for cross-concern models).

### Consequences

- No breaking change — single-source entities generate identically to before.
- Multi-source entities produce N+1 files (N per-source views + 1 union table).
- The gold layer remains unchanged (it reads from the entity-level model regardless).
- `_sources.yml` separation already supports this pattern (one per source system).
- FK joins are still empty for multi-source (planned follow-up).

---

## DD-019: Cross-Domain FK Resolution via Surrogate Key Joins

**Status:** Accepted  
**Date:** 2026-05-01  
**Affects:** `medallion_dbt_projector.py`, silver model SQL generation, schema YAML  
**Implementation:** `src/kairos_ontology/projections/medallion_dbt_projector.py` `_extract_fk_columns_and_joins()`

### Context

When an `owl:ObjectProperty` maps a source column to a class in another domain (e.g.,
`Relation.id` maps to `client:representsParty` → `Party`), the silver model needs a
surrogate key column (`party_sk`) that resolves the source natural key to the target
table's SK via a lookup join. Previously, the dbt projector only processed
`DatatypeProperty` — object properties were silently skipped.

### Decision

Generate cross-domain FK columns as `left join {{ ref('{target_model}') }}` lookups
in the silver SQL model. The join condition uses the source column (from SKOS mapping)
matched against the target class's `kairos-ext:naturalKey` column.

**Guards (safe first cut):**
- Only for single-source models (multi-source models are skipped — too complex)
- Only when the target class has a single-column natural key (composite NK → NULL + warning)
- Only for qualifying properties: `owl:FunctionalProperty` or explicit `silverColumnName`
- Missing SKOS mapping → NULL placeholder + warning

### Rationale

| Approach | Pros | Cons |
|----------|------|------|
| Pass-through natural key | Simple | Misleading column name (`_sk` but contains NK) |
| **Join to ref() (chosen)** | Correct semantics; silver is self-consistent | Requires target model to exist; join overhead |
| Gold-layer only | Clean separation | Silver schema doesn't match DDL projector output |

The join approach was chosen because:
1. The DDL silver projector already declares these as `_sk STRING` FK columns
2. The dbt template already supports `joins` (just wasn't being used)
3. Makes silver layer self-consistent: all `_sk` columns are surrogate keys

### Consequences

- FK columns now appear in generated SQL and schema YAML
- Target silver models must exist (dbt will error on dangling `ref()` if target ontology
  is not projected) — this is correct behaviour (surface missing dependencies early)
- Multi-source and composite-NK cases degrade gracefully (NULL + warning)
- Future work: support composite natural keys via multi-column join conditions

---

## DD-020: Stable Ontology IRIs — No Version in Namespace

**Status:** Accepted  
**Date:** 2026-05-01  
**Affects:** all ontology files, `detect_ontology_uri()`, projections, `owl:imports`  
**Implementation:** `src/kairos_ontology/projections/shared.py:136-141`, hub ontology conventions

### Context

OWL 2 offers two versioning mechanisms:
1. **`owl:versionIRI`** — encodes the version in the IRI itself (e.g., `https://example.org/ont/1.0.0`)
2. **`owl:versionInfo`** — stores the version as a literal annotation on a stable IRI

In a data-platform context where ontologies drive generated artifacts (dbt models, DDL, Power BI
semantic models, FK scripts), the choice of versioning mechanism has cascading effects on downstream
stability.

### Decision

Use **stable, versionless ontology IRIs** with `owl:versionInfo` as the version annotation.
Do not use `owl:versionIRI`.

```turtle
<https://acme.example/ontology/client> a owl:Ontology ;
    owl:versionInfo "1.0.0" .
```

Version tracking is handled by git tags and releases on the hub repository, not by IRI changes.

### Rationale

| Concern | Why versionless IRIs are better |
|---------|-------------------------------|
| **Generated artifact stability** | Table names, column references, and FK scripts derive from namespace prefixes. Versioned IRIs would change all generated names on every version bump. |
| **`owl:imports` fragility** | Cross-domain imports (`owl:imports <.../client>`) would break when the imported ontology bumps its version. |
| **`detect_ontology_uri()` logic** | The toolkit matches ontology subjects by namespace prefix. Versioned IRIs would require version-aware lookup or regex matching. |
| **Hub git history** | Git already provides complete version history. Embedding version in IRIs duplicates this without benefit. |
| **Downstream consumers** | dbt `ref()` calls, Power BI table names, and search indexes all assume stable identifiers. |

Alternatives considered:
- **Versioned IRI + `owl:versionIRI`**: rejected — too much downstream churn for a data platform use case
- **Version in namespace path** (e.g., `/v1/client#`): rejected — same churn issues, plus complicates prefix declarations

### Consequences

- Ontology files MUST declare `owl:versionInfo` as a string literal for traceability
- Ontology files MUST NOT use `owl:versionIRI`
- Breaking ontology changes are managed via hub release process (CHANGELOG, git tags), not IRI changes
- The `detect_ontology_uri()` helper can rely on simple prefix matching without version parsing

---

## DD-021: Extension-as-Whitelist for Imported Class Projection

**Status:** Proposed  
**Date:** 2026-05-01  
**Affects:** silver projector, gold projector, `projector.py`, `kairos-ext:` annotation vocabulary  
**Implementation:** `src/kairos_ontology/projections/projector.py`, extension annotation handling

### Context

The reference-model-first workflow encourages hub authors to build domain ontologies primarily via `owl:imports` of reference models (BSP, MMT, DCSA, FIBO). When a domain ontology imports a reference model, `load_graph_with_catalog()` resolves the import and loads all triples into the same rdflib.Graph. However, the silver and gold projectors filter classes by namespace — only classes whose URI starts with the domain's own namespace produce DDL output. This means imported classes are loaded but ignored.

This creates a gap: import-only domains (e.g., `party.ttl` that imports BSP/Party) generate no silver DDL at all, forcing hub authors to create extension files that duplicate what the projector could infer.

However, auto-including ALL imported classes is dangerous. Large ontologies like FIBO contain hundreds of classes; importing FIBO for a few concepts would pollute the silver layer with unwanted tables.

### Decision

Imported classes are only projected when **explicitly claimed** via extension annotations:

1. **Per-class claiming**: `kairos-ext:silverInclude true` (or `goldInclude`) on individual imported classes in the domain's extension file.
2. **Bulk claiming**: `kairos-ext:silverIncludeImports true` (or `goldIncludeImports`) on the `owl:Ontology` resource — includes all classes from first-level `owl:imports`, excluding peer hub domain imports.

Four new `kairos-ext:` annotation properties:

| Annotation | Level | Type | Purpose |
|------------|-------|------|---------|
| `silverInclude` | Class | boolean | Claim an imported class for silver projection |
| `silverIncludeImports` | Ontology | boolean | Bulk-claim all first-level imported classes for silver |
| `goldInclude` | Class | boolean | Claim an imported class for gold projection |
| `goldIncludeImports` | Ontology | boolean | Bulk-claim all first-level imported classes for gold |

Peer hub domain detection: `run_projections()` collects namespaces of all hub `.ttl` files into a `hub_domain_namespaces` set. The bulk flag excludes any import whose namespace matches a peer hub domain — preventing cross-domain table duplication.

### Rationale

| Approach | Pros | Cons |
|----------|------|------|
| Auto-include all imports | Zero config | FIBO pollution; no control over scope |
| Extension-as-whitelist | Explicit; prevents pollution; gradual adoption | Requires extension file for imports |
| Whitelist + bulk flag | Best of both: explicit per-class OR convenient bulk | Slightly more complex |

The whitelist + bulk flag approach was chosen because:
- It prevents pollution from large upstream ontologies
- It gives hub authors explicit control over their silver/gold scope
- The bulk flag provides convenience for import-only domains
- Peer hub exclusion prevents cross-domain table duplication
- It preserves backward compatibility — existing hubs with only local classes are unaffected

### Consequences

- Extension files become the control point for imported class projection
- Import-only domains need at minimum one extension annotation (bulk or per-class)
- Local classes (domain namespace) continue to be auto-projected (unchanged)
- The BUG-3/IMP-1 namespace filter moves from the silver/gold projectors to `_run_projection()` in projector.py
- New helper functions: `_discover_whitelisted_imports()`, `_get_reference_model_namespaces()`
- Schema for adopted imported classes comes from the hub domain name, not the reference model namespace

### Property Inheritance Clarification

The DD-021 notice is **informational only** — properties from unclaimed parents are
**always inherited automatically**. The projector's `_get_class_and_ancestors()` function
traverses the full `rdfs:subClassOf` chain and includes datatype + FK properties from
all ancestor classes that are NOT separately projected.

**Architectural decision matrix:**

| Scenario | Action required | Result |
|----------|----------------|--------|
| Want parent properties in child table | None — automatic | Child table includes all inherited properties via ancestor traversal |
| Want parent as its own separate table (S3) | Add `silverInclude "true"` on parent class | Parent gets own table; child is folded into it with discriminator column |
| Want all imported classes as separate tables | Add `silverIncludeImports "true"` on ontology | All first-level imports get tables (use sparingly) |

**Key insight:** `silverInclude` does NOT mean "inherit properties" — inheritance
always works. It means "project this class as its own table". When a parent IS
projected as its own table, S3 single-table inheritance kicks in: the child class
is folded into the parent table with a discriminator column (the child does NOT get
its own table).

**When to ignore the DD-021 notice:**
- Your domain class extends a reference model class
- You want your domain class as its own table with all inherited parent properties
- You do NOT want the reference model parent as a separate table
- → Properties already flow through; the notice is confirming this is intentional

### Examples

**Import-only domain (bulk):**
```turtle
# party-silver-ext.ttl
<https://frachtgroup.com/ont/party> kairos-ext:silverIncludeImports true .
```

**Selective claiming:**
```turtle
# party-silver-ext.ttl
bsp-party:TradeParty kairos-ext:silverInclude true .
bsp-party:Buyer      kairos-ext:silverInclude true .
```

**Mixed domain (local + imports):**
```turtle
# booking-silver-ext.ttl — only need claims for imported classes
bsp-party:TradeParty kairos-ext:silverInclude true ;
    kairos-ext:scdType "2" ;
    kairos-ext:naturalKey "partyCode" .
```

---

## DD-022: Simplified FK Annotations for Silver Projection

**Status:** Proposed  
**Date:** 2026-05-01  
**Affects:** `medallion_silver_projector.py`, `kairos-ext.ttl`  
**Implementation:** `_add_object_property_fk_cols()`, `_add_redirected_fk_cols()`

### Context

The silver projector generates FK columns (R12) only when an object property
has one of three signals: `kairos-ext:silverColumnName`, `owl:FunctionalProperty`,
or `owl:maxQualifiedCardinality 1` restriction. Reference models imported via
`owl:imports` (BSP, MMT, DCSA, FIBO) typically lack all three, producing tables
without FK columns — every table becomes an isolated island.

The existing workaround requires hub authors to define inverse properties and
add verbose OWL restriction syntax in extension files (5+ lines per FK). This is
error-prone and creates drift risk when reference models add new properties.

### Decision

Introduce two new `kairos-ext:` annotations for simplified FK declaration:

1. **`kairos-ext:silverForeignKey`** (boolean on `owl:ObjectProperty`):
   Acts as a 4th FK trigger. When `true`, the domain class's table gets a FK
   column pointing to the range class — equivalent to `owl:FunctionalProperty`
   but usable in extension files on imported properties.

2. **`kairos-ext:silverForeignKeyOn`** (class URI on `owl:ObjectProperty`):
   Overrides which class receives the FK column. Must be either the domain or
   range of the property. When set to the range class, the FK is placed on the
   range table pointing back to the domain table (reverse placement). Implies
   `silverForeignKey true`.

Usage examples:

```turtle
# Simple: Order.placedBy → Customer (FK on Order table)
ex:placedBy kairos-ext:silverForeignKey true .

# Reverse: Consignment.hasItem → Item (FK on Item table, not Consignment)
ex:hasConsignmentItem kairos-ext:silverForeignKeyOn mmt:ConsignmentItem .

# With column name override
ex:placedBy kairos-ext:silverForeignKey true ;
            kairos-ext:silverColumnName "buyer_sk" .
```

### Rationale

| Approach | Pros | Cons |
|----------|------|------|
| OWL restrictions (current) | Ontologically pure | Verbose (5+ lines/FK), reference models lack them |
| `silverForeignKey` annotation | 1 line, works on imports | Slightly less OWL-pure |
| Auto-infer from property names | Zero config | Unreliable, model-dependent |

The annotation approach is the best trade-off: explicit (no guessing), minimal
syntax (1 line vs 5), and compatible with the DD-021 import whitelisting
workflow where extension files already claim imported classes.

### Consequences

- **Extension files become the FK control point** for imported reference models.
  Hub authors annotate the exact properties they want as FKs.
- **Backward compatible**: existing `owl:FunctionalProperty` and cardinality
  restrictions continue to work unchanged.
- **`silverForeignKeyOn` eliminates inverse property definitions** for
  parent→child relationships — the most common FK pattern in reference models.
- **Validation warnings** are emitted for invalid `silverForeignKeyOn` targets
  (class not in domain/range) or missing domain/range declarations.
- **No gold equivalent** — the gold projector uses different relationship
  semantics (dimension keys). A `goldForeignKey` may be added later if needed.

---

## DD-023: Shared Extension Defaults for Reference Models

**Status:** Proposed  
**Date:** 2026-05-19  
**Affects:** silver projector, gold projector, dbt projector, `projector.py`, `catalog_utils.py`, `shared.py`  
**Implementation:** `src/kairos_ontology/projector.py`, `src/kairos_ontology/catalog_utils.py`, `src/kairos_ontology/projections/shared.py`

### Context

When a hub domain imports a reference model via `owl:imports` and claims imported classes for silver projection (DD-021), the hub must still provide per-class silver extension annotations (scdType, naturalKey, silverDataType, silverForeignKey, etc.). When multiple hub domains — or multiple hub repos — import the same reference model, the same extension annotations are duplicated in each hub's extension file.

This creates maintenance burden and inconsistency risk: if the reference model evolves, every downstream hub must independently update their extension annotations.

### Decision

Reference model repositories may ship **default extension files** alongside their ontologies:

- `{ontology-stem}-silver-defaults.ttl` — default silver annotations
- `{ontology-stem}-gold-defaults.ttl` — default gold annotations

The toolkit's projection pipeline discovers these via catalog resolution and loads them as a **fallback layer** beneath the hub's own domain extension.

**Merge priority (highest → lowest):**

1. Hub domain extension (`model/extensions/{domain}-silver-ext.ttl`)
2. Reference model defaults (discovered alongside catalog-resolved imports)
3. Built-in projector conventions (rdfs:range → SQL type inference)

**Override semantics:** Fallback triples are only added when the subject+predicate pair is NOT already declared in the hub domain extension. This ensures hub-local annotations always win.

**Discovery mechanism:** When the catalog resolves an `owl:imports` URI to a local file path, the toolkit looks for a sibling file matching `{stem}-silver-defaults.ttl`. Falls back to checking a sibling `extensions/` directory.

**Key capability:** `silverInclude` may be declared in defaults files — allowing reference models to pre-declare which classes are suitable for silver materialization, eliminating the need for each hub to repeat these claims.

### Rationale

| Approach | Pros | Cons |
|----------|------|------|
| Manual extension per hub | Full control | Duplication, inconsistency across hubs |
| Auto-include all imports | Zero config | Pollution from large ref models (FIBO) |
| Shared defaults (this) | Single source of truth, hub can override | Requires convention; ref model repo must be toolkit-enabled |
| Domain-local subclasses | Full OWL control | Semantic drift, property duplication |

The shared defaults pattern was chosen because:
- It eliminates duplication across hubs importing the same reference model
- Hub authors retain full override capability (domain ext always wins)
- It is fully backward-compatible (hubs without defaults work unchanged)
- Reference model repos are just standard ontology-hubs with the toolkit installed
- The convention is simple and discoverable (sibling file naming)

### Consequences

- Reference model repos should ship `*-silver-defaults.ttl` and/or `*-gold-defaults.ttl` alongside their ontology files.
- The `merge_ext_graph()` function gains a `fallback_paths` parameter for layered merging.
- A new `resolve_import_paths()` utility in `catalog_utils.py` exposes catalog-resolved paths.
- A new `_discover_ref_model_defaults()` helper in `projector.py` locates sibling defaults files.
- `silverInclude` / `goldInclude` annotations in defaults files are inherited by downstream hubs.
- No changes required for existing hubs — the feature is purely additive.

---

## DD-024: Hash-Tolerant Catalog Resolution

**Status:** Accepted  
**Date:** 2026-05-26  
**Affects:** `catalog_utils.py`, import resolution, projection pipeline  
**Implementation:** `src/kairos_ontology/catalog_utils.py`

### Context

Ontology IRIs may or may not end with a `#` fragment separator. In RDF/OWL
practice, the ontology IRI (subject of `a owl:Ontology`) and the namespace
prefix used for classes/properties often differ by a trailing `#`:

```turtle
@prefix : <https://example.org/ont/booking#> .
: a owl:Ontology .  # IRI is https://example.org/ont/booking#
```

vs.

```turtle
<https://example.org/ont/cargo> a owl:Ontology .  # IRI without #
@prefix : <https://example.org/ont/cargo#> .       # But classes use #
```

When domain ontologies import reference models, the `owl:imports` URI may
or may not include the trailing `#`, and the XML catalog `name` attribute
may independently include or omit it. This creates silent resolution
failures where the catalog knows about the file but can't match the URI.

### Decision

1. **Convention:** `owl:imports` should reference the ontology IRI as
   declared in the target file. The catalog `name` attribute must exactly
   match the value used in `owl:imports`. Prefer ontology IRIs **without**
   trailing `#`.

2. **Defensive resolution:** `CatalogResolver` normalizes both `#` and `/`
   variants during catalog loading (storing bare, with-hash, and with-slash
   forms). The `resolve()` method tries all variants as fallback.

3. **Diagnostic warning:** When resolution succeeds only via hash fallback,
   a warning is logged advising the user to align their catalog and import
   URIs for clarity.

### Rationale

| Approach | Pros | Cons |
|----------|------|------|
| Strict exact match only | Simple, predictable | Breaks on common IRI variations |
| Normalize on load + fallback (this) | Resilient to real-world inconsistency | Slightly more mappings in memory |
| Always strip `#` | Simpler logic | Loses information, may create false matches |

The normalization approach was chosen because:
- Third-party reference models cannot always be edited
- The mismatch between ontology IRI and import URI is an extremely common
  real-world pattern (especially in hash-namespace ontologies)
- The warning provides a clear path to fix the root cause

### Consequences

- Existing catalogs with exact matches continue to work unchanged.
- Mismatched catalogs that previously caused silent "No catalog mapping"
  failures will now resolve correctly with a diagnostic warning.
- Users are guided to fix the root cause (align catalog `name` with `owl:imports`).

---

## DD-025: SCD Type-Aware dbt Silver Models

**Status:** Proposed  
**Date:** 2026-05-26  
**Affects:** `medallion_dbt_projector.py`, `silver_model.sql.jinja2`, silver dbt output  
**Implementation:** `src/kairos_ontology/projections/medallion_dbt_projector.py`, `src/kairos_ontology/templates/dbt/silver_model.sql.jinja2`

### Context

The silver DDL projector (`medallion_silver_projector.py`) correctly differentiates SCD
Type 1 and Type 2 — adding `valid_from`, `valid_to`, `is_current`, and `_row_hash`
columns for SCD2 classes. The gold projector and gold dbt model also handle SCD2 correctly
(filtering `WHERE is_current = 1`).

However, the dbt silver model generator (`_gen_silver_models`) does not read
`kairos-ext:scdType` and produces the same plain table materialization for both SCD1 and
SCD2. This means:
- SCD2 silver tables have the correct DDL schema but no change-detection or temporal-tracking logic in the dbt pipeline
- The silver model overwrites data rather than inserting new versions and closing prior rows

### Decision

Extend the silver dbt model generator to produce SCD-type-aware incremental models:

1. **SCD1 (default):** `materialized='incremental'` with `unique_key='{table}_sk'`.
   Simple upsert — new data overwrites existing rows. Filtered by `_loaded_at` for
   incremental runs.

2. **SCD2:** `materialized='incremental'` with `unique_key=['{table}_sk', 'valid_from']`.
   Change-detection via `_row_hash` comparison. New/changed rows inserted with
   `is_current = 1`; prior versions closed with `valid_to = CURRENT_DATE, is_current = 0`.

Implementation uses a **single template** (`silver_model.sql.jinja2`) with conditional
blocks (`{% if scd_type == "2" %}`), keeping the logic localized and avoiding template
proliferation.

The projector computes `hash_columns` (all business columns excluding SK, temporal, and
derived FK columns) and passes them to the template for `_row_hash` generation.

### Rationale

| Approach | Pros | Cons |
|----------|------|------|
| Keep plain table (current) | Simple | SCD2 schema mismatch; no temporal tracking |
| **Incremental with SCD-aware logic (this)** | Matches DDL; end-to-end SCD2 | More complex template |
| dbt snapshots | Native SCD2 support | Different materialization; doesn't align with silver schema |
| Separate SCD2 template file | Clean separation | Maintenance of two templates; most logic is shared |

The single-template incremental approach was chosen because:
- It aligns the dbt pipeline with the DDL projector's output (schema consistency)
- It uses standard dbt incremental patterns (no custom materializations)
- The conditional logic is localized to the incremental strategy section
- It keeps all silver model logic in one discoverable file

### Consequences

- SCD2 classes will generate incremental models with change detection and temporal tracking
- The silver template grows in complexity but remains a single file
- `_row_hash` is computed in the model SQL, not stored from source (source doesn't have it)
- Full refresh produces all rows with `is_current = 1` (correct baseline behavior)
- SCD1 classes change from `table` to `incremental` materialization (performance improvement)
- Scenario tests must be added for SCD2 dbt model generation

See full design: [`docs/design/dd-025-scd-type-aware-dbt-silver.md`](dd-025-scd-type-aware-dbt-silver.md)

---

## DD-026: Silver Layer Accuracy — Mapped-Only Columns, FK Parity, and SCD2 History Preservation

**Status:** Accepted  
**Date:** 2026-05-27  
**Affects:** `medallion_dbt_projector.py`, `silver_model.sql.jinja2`, `silver_source_model.sql.jinja2`, `silver_union_model.sql.jinja2`  
**Implementation:** `src/kairos_ontology/projections/medallion_dbt_projector.py`, `src/kairos_ontology/templates/dbt/`

### Context

Three accuracy issues were identified in the dbt silver projector output:

1. **Unmapped columns**: All ontology properties were emitted as `CAST(NULL AS ...)` even when no source mapping existed, creating schemas with 70%+ NULL columns.
2. **FK qualification gap**: The dbt projector's `_infer_fk_targets()` only qualified properties as FKs if they were `owl:FunctionalProperty` or had `silverColumnName`. Properties with `kairos-ext:silverForeignKey true` (DD-022) were ignored — even though the silver DDL projector already handled them.
3. **SCD2 history erasure**: The SCD2 `closed` CTE set all business columns to `CAST(NULL AS VARCHAR)`, defeating the purpose of SCD Type 2 (which exists to preserve historical values).

### Decision

1. **Exclude unmapped properties**: If a property has no SKOS mapping to a bronze column and no `derivationFormula`, it is excluded from the silver model entirely. Only columns with actual data sources are emitted.
2. **Align FK qualification**: `_infer_fk_targets()` now checks `kairos-ext:silverForeignKey true` and also skips properties with `silverForeignKeyOn` (which redirect the FK to a different table), matching the silver DDL projector's logic.
3. **Preserve SCD2 history**: The `closed` CTE reads all column values from `{{ this }}` (the existing materialized table), preserving business data. Only `valid_to` and `is_current` are modified.
4. **Add `_source_system` discriminator**: Per-source union models now include a `_source_system` column for provenance tracking.

### Rationale

- **Mapped-only**: Downstream consumers (gold layer, Power BI) get honest schemas. NULL columns are never queried and create false expectations about data availability.
- **FK parity**: DD-022 introduced `silverForeignKey` as the standard annotation for FK qualification. The dbt projector must honour it to generate correct joins.
- **SCD2 preservation**: The entire purpose of SCD2 is historical analysis ("what was the status last month?"). NULLing history makes that impossible.
- **Discriminator**: When multiple sources feed a single entity, traceability requires knowing which source produced each row.

### Consequences

- Silver models will have **fewer columns** than before (only mapped ones). Downstream schemas may need regeneration.
- Properties annotated with `silverForeignKey true` will now correctly generate LEFT JOINs in dbt models.
- SCD2 incremental runs produce accurate historical records.
- Union models include `_source_system` as an additional column — gold layer transforms may need to account for it.

---

## DD-027: Cross-Domain Peer Extension Loading for FK Resolution

**Status:** Accepted  
**Date:** 2026-05-27  
**Affects:** `projections/shared.py`, `projections/medallion_dbt_projector.py`, `projector.py`  
**Implementation:** `merge_ext_graph()` peer_ext_paths parameter; `_run_projection()` peer ext discovery

### Context

DD-019 introduced cross-domain FK resolution via surrogate key joins. However, when a FK
targets a class in another domain (e.g., `financial:chargeForShipment` → `consignment:Shipment`),
the projector could not resolve the target class's `kairos-ext:naturalKey` because it only
loaded the current domain's silver extension file. This forced hub authors to duplicate
naturalKey declarations in every referencing domain's extension file.

DD-023 introduced shared defaults as a fallback layer for reference models, but that mechanism
only addresses shared reference models — not peer hub domains.

### Decision

The dbt projector now loads **all** `*-silver-ext.ttl` files from the hub's `extensions/`
directory as "peer extension paths" for each domain projection. This enables cross-domain
naturalKey resolution without redundant declarations.

**Extended merge priority (highest → lowest):**

1. Hub domain extension (`{domain}-silver-ext.ttl`) — always wins
2. **Peer domain extensions** (other `*-silver-ext.ttl` files) — cross-domain annotations
3. Reference model defaults (DD-023 fallback layer)
4. Built-in projector conventions (rdfs:range inference)

**Override semantics:** Peer extension triples are only added when the subject+predicate pair
is NOT already declared in the domain's own extension (same as fallback semantics).

**Error handling:** Parse failures in peer extension files are silently skipped (graceful
degradation). A broken peer file does not break the current domain's projection.

### Rationale

| Approach | Pros | Cons |
|----------|------|------|
| Manual duplication | Explicit, self-contained | Doesn't scale; drift risk |
| **Peer ext loading (chosen)** | Zero duplication; works automatically | Cross-domain coupling |
| Shared global ext | Flexible | No clear ownership; hard to maintain |
| Require naturalKey in base ontology | Clean | Pollutes domain model with projection concerns |

The peer loading approach was chosen because:
- NaturalKey is inherently a projection annotation (belongs in ext files, not base ontology)
- Hub authors already have all ext files in one directory — the toolkit should leverage this
- Priority rules ensure domain-own annotations always win (no surprises)
- Existing workaround (manual duplication) remains valid but becomes unnecessary

### Consequences

- `merge_ext_graph()` gains a `peer_ext_paths` parameter (backward-compatible: defaults to None)
- `generate_dbt_artifacts()` gains a `peer_ext_paths` parameter
- `projector.py` collects all `*-silver-ext.ttl` paths before the domain loop and passes
  the peer list (excluding current domain's file) to each projection
- Existing hubs with duplicated cross-domain NK declarations continue working (redundant
  declarations are harmless — domain ext wins via priority)
- Future: same pattern could be applied to gold projector for cross-domain goldInclude resolution

---

## DD-028: Multi-Table Same-Source Union Model Disambiguation

**Status:** Accepted  
**Date:** 2026-05-27  
**Affects:** `projections/medallion_dbt_projector.py`, dbt silver model naming  
**Implementation:** Per-source model naming logic in `_gen_silver_models()`

### Context

DD-018 established entity-centric silver models with multi-source split (one per-source model
per source system, combined via UNION ALL). The per-source model naming used only the entity
name and source system name: `{entity}__from_{source_system}`.

When two tables from the **same** source system map to the **same** domain class (e.g.,
`sales_invoices` and `purchase_invoices` both from `QargoTms` → `Invoice`), the naming
produced identical model names. The second model silently overwrote the first in the
artifact dict, and the UNION ALL referenced the same model twice.

### Decision

When multiple tables from the same source system map to the same entity, append a
sanitized table name suffix to disambiguate:

- **No collision (common case):** `{entity}__from_{source}` (unchanged)
- **Collision detected:** `{entity}__from_{source}__{table_name}`

Detection uses a `Counter` over source system names in the entity's source_refs list.
The table suffix is only added when `count > 1` for that source system.

### Rationale

| Approach | Pros | Cons |
|----------|------|------|
| Always include table name | Unambiguous | Long names; breaking change for all hubs |
| **Conditional suffix (chosen)** | Short names by default; disambiguates only when needed | Slightly more logic |
| Numeric suffix (\_1, \_2) | Short | Unstable (order-dependent); not self-documenting |
| Error on collision | Safe | Blocks projection; poor UX |

### Consequences

- Hubs with multi-table-same-source patterns get correctly disambiguated model files
- Hubs without collisions see zero change in output (backward-compatible)
- Model names may be longer for collision cases — warehouse name limits (128 chars) should
  be monitored for edge cases
- This is a **minor breaking change** for hubs that previously generated colliding names:
  their model filenames change (from the incorrect duplicate to two distinct files)

---

## DD-029: Silver Model Registry for Gold ref() Resolution

**Status:** Accepted  
**Date:** 2026-05-28  
**Affects:** `projections/medallion_dbt_projector.py`, gold dbt model generation  
**Implementation:** `_build_silver_model_registry()`, updated `_silver_model_name_for_class()`

### Context

When `goldIncludeImports "true"` adds imported reference-model classes to the gold
projection, `_silver_model_name_for_class()` resolves imported class URIs to their own
local names (e.g., `purchase_order`). However, silver models are generated under hub
domain class names (e.g., `hub_order`), causing broken `{{ ref() }}` calls in gold dbt
models.

Additionally, gold models were selecting ALL ontology properties regardless of whether
silver actually generates those columns (post DD-026 unmapped-column exclusion).

### Decision

Build an in-memory **silver model registry** after silver generation:

1. **Name registry** (`dict[str, str]`): maps class URIs (including imported parent URIs)
   to actual silver model file names.
2. **Columns registry** (`dict[str, set[str]]`): maps silver model names to the set of
   column names they actually generate.

Parent URI mapping uses a **single-child rule**: a parent URI is only registered when
exactly one hub class extends it. Ambiguous parents (multiple children) trigger a warning
and are not registered.

Gold column filtering: gold models only SELECT columns that exist in the referenced
silver model's column set (structural columns like `_sk`, `_type`, `valid_from/to`,
`is_current` are exempt from filtering).

### Rationale

| Approach | Pros | Cons |
|----------|------|------|
| **Registry (chosen)** | O(1) lookup; built once; no graph traversal at call time | Small memory overhead |
| Walk rdfs:subClassOf at call time | No extra data structure | Complex; must handle cycles; slow |
| Manifest file between phases | Explicit contract | File I/O; ordering fragility |
| Cross-domain global registry | Handles cross-domain gold refs | Unnecessary — gold refs are per-domain |

### Consequences

- Gold `{{ ref() }}` calls now correctly resolve to the actual silver model name
- Gold models only SELECT columns that silver provides — no broken column references
- Backward-compatible: registry is additive; existing behavior unchanged when registry is empty
- Cross-domain gold refs remain unsupported (separate concern, not affected by this change)

---

## DD-030: rewriteURI Catalog Resolution with Extension Fallback

**Status:** Accepted  
**Date:** 2026-05-29  
**Affects:** `src/kairos_ontology/catalog_utils.py` (CatalogResolver)  
**Implementation:** `CatalogResolver._resolve_via_rewrite()` + `_rewrite_rules` list

### Context

The OASIS XML Catalog standard supports `<rewriteURI>` elements that perform prefix-based
URI-to-path rewriting. FIBO and other large reference ontologies use a single rewrite rule
to map hundreds of ontology URIs to a local directory tree. The toolkit only supported
`<uri>` (exact mapping) elements, causing all FIBO imports to fail with "No catalog mapping
for" warnings.

Additionally, FIBO URIs use trailing slashes (e.g., `.../Agents/`) while the actual files
use `.rdf` extensions (e.g., `Agents.rdf`), so even after prefix rewriting the path doesn't
directly point to a file.

### Decision

1. Parse `<rewriteURI>` elements and store them sorted by descending `uriStartString`
   length (longest-prefix-wins, per OASIS XML Catalog 1.1 §6.5).
2. Apply rewrite rules in `resolve()` only after all exact `<uri>` lookups fail.
3. When the rewritten path doesn't exist as a file, apply an **extension fallback**:
   strip trailing slash, then probe `.rdf` → `.ttl` → `.owl` in order.
4. Only return paths where `Path.is_file()` is True — never return directories.
5. Emit an info-level diagnostic when extension fallback is used; emit a warning when
   multiple extensions match (ambiguity).

### Rationale

- **Longest-prefix-wins** follows the OASIS spec and prevents ambiguous resolution when
  multiple rewrite rules overlap (e.g., a general FIBO rule + a specific FND rule).
- **Extension fallback** is necessary because FIBO URIs use trailing slashes but files use
  `.rdf` extensions — a pure string rewrite cannot produce the correct file path.
- **Fixed priority order** (`.rdf` → `.ttl` → `.owl`) is deterministic and matches the
  publishing conventions of FIBO/OMG/W3C (RDF/XML) while supporting Kairos TTL files.
- **Exact `<uri>` always wins** — this ensures existing catalogs with explicit entries
  are unaffected (zero-cost path for already-working catalogs).

### Consequences

- FIBO and other reference ontologies with `<rewriteURI>` catalogs now resolve without
  requiring per-module `<uri>` entries
- Extension fallback emits diagnostics that flow into `projection-report.json` via
  `CatalogLoadResult` (see DD-030's companion fix for report propagation)
- Ambiguous cases (both `.rdf` and `.ttl` exist) are logged as warnings — users can add
  an explicit `<uri>` entry to override
- No performance concern: rewrite rules are only checked when O(1) dict lookups fail,
  and typical catalogs have 1-3 rewrite rules

---

## DD-031: Inherit naturalKey from Discriminator Parents

**Status:** Accepted  
**Date:** 2026-05-29  
**Affects:** dbt projector — SK/IRI generation for discriminator subtypes  
**Implementation:** `src/kairos_ontology/projections/medallion_dbt_projector.py`

### Context

When a parent class uses `kairos-ext:inheritanceStrategy "discriminator"`, its subtypes
are flattened into the parent's silver table. The dbt projector generates per-mapping-target
models (which may target subtypes directly via SKOS mappings). Previously, `_get_natural_key`
only checked the direct class annotation — subtypes without their own `kairos-ext:naturalKey`
produced `CAST(NULL...)` for SK and IRI columns, even when the parent declared a valid key.

### Decision

`_get_natural_key` now walks `rdfs:subClassOf` upward when no direct annotation is found.
It only inherits the parent's naturalKey when the parent declares
`inheritanceStrategy "discriminator"`. Direct annotations on the subclass always win.

A companion function `_get_raw_natural_key` provides the same hierarchy walk but returns
the raw camelCase literal (used by `_get_nk_property_uris` for property URI resolution).

### Rationale

- Discriminator subtypes share the parent's table → they logically share the same NK
- `class-per-table` subtypes get their own tables → they need their own NK definitions
- Recursion guard (`_visited` set) prevents infinite loops from cyclic `rdfs:subClassOf`
- The fix benefits all call sites: SK generation, IRI generation, FK target resolution

### Consequences

- Hub authors can remove redundant `naturalKey` annotations from discriminator subtypes
- Existing hubs with explicit subtype annotations continue to work (direct wins)
- FK resolution to discriminator subtypes now correctly generates join conditions
- The silver projector is unaffected (it skips subtypes entirely and projects only the parent)

---

## DD-032: Reference Model Inspired — Local Pattern Adoption from Reference Models

**Status:** Accepted  
**Date:** 2026-05-30  
**Affects:** modeling workflow, skill guidance, scaffold, alignment file conventions  
**Implementation:** No code changes required — Inspired classes are regular local classes already supported by all projectors. Guidance lives in skills and `docs/design/dd-032-reference-model-alignment.md`.

### Context

Kairos hubs face a tension when working with industry reference models (FIBO, HL7 FHIR,
GS1, Schema.org):

- **Reference Model Enforced** (`owl:imports` + `rdfs:subClassOf`): Full structural coupling.
  Works well for small, projection-compatible reference models (Kairos reference model repos
  like BSP, TIC). Fails for large, axiom-heavy models (FIBO imports 1000+ classes; DD-021
  whitelisting and DD-023 shared defaults exist specifically to manage this complexity).

- **SKOS alignment file only** (no structural adoption): Zero runtime cost,
  clean projections, but the alignment is *documentation only* — it never influences the
  silver schema. The alignment file says "we're like FIBO" but the silver tables don't
  benefit from FIBO's structural patterns (Identifier, PartyInRole, Classification).

**The gap:** There is no supported pattern for adopting the *structural intent* and
*semantic patterns* of a reference model while keeping a fully local, projection-optimized
ontology.

### Decision

> **⚠ AMENDED by DD-044 (2026-06-12):** The default strategy has been flipped.
> **Enforced** (`owl:imports` + `silverInclude`) is now the default for all reference
> models. **Inspired** is an opt-in override for cases where import is impossible or
> undesirable. See DD-044 for full rationale.

Introduce **Reference Model Inspired** as the ~~**default**~~ **opt-in** strategy for
reference model alignment. **Reference Model Enforced** (full `owl:imports`) is the
~~override~~ **default**, with `silverInclude` whitelisting (DD-021) ensuring only
claimed classes are projected.

**Reference Model Inspired definition:**

> Mirror reference model structural patterns as local classes (own namespace), with
> `rdfs:seeAlso` back-references (DD-033). No `owl:imports` at runtime.

**The simplified strategy model (2 strategies):**

| Strategy | When | What |
|----------|------|------|
| **Reference Model Enforced** (default — amended by DD-044) | All reference models; `silverInclude` whitelisting prevents projection noise | `owl:imports` + DD-021 whitelist |
| **Reference Model Inspired** (opt-in) | When import is impossible (proprietary model, no TTL); deliberate structural deviation | Local patterns + `rdfs:seeAlso` |

**Enforced eligibility** (ALL must be true):
- Published in `ontology-reference-models/` central repo
- Small (< 50 classes), focused domain
- Ships `*-silver-defaults.ttl` (DD-023 compatible)
- Has `catalog-v001.xml` entry
- No transitive imports pulling in unrequested concepts

**Core principles:**

1. **Local ownership** — All classes and properties are in the hub's own namespace.
   No `owl:imports` of external ontologies at runtime.
2. **Selective pattern adoption** — Cherry-pick only patterns that provide business
   value. Zero adoption is valid (no local class created).
3. **Projection-first gate** — Only adopt a pattern as a local class when it produces
   a **structurally different silver schema** (new table or new relationship).
4. **Inline traceability** — Use `rdfs:seeAlso <reference-model-class-URI>` on each
   inspired local class for machine-readable back-reference to the source pattern.
5. **rdfs:seeAlso is ignored by projectors** — It is documentation for
   designers revisiting extension properties, not a runtime input.

**Silver structural difference criterion** (the key decision gate):

| Question | Answer | Action |
|----------|--------|--------|
| Does adopting this pattern create a new silver table? | Yes | Adopt as local class ✅ |
| Does it create a new FK relationship? | Yes | Adopt as local class ✅ |
| Does it inline to the same flat columns (S4, embedded)? | Yes | Optional — ontology clarity only ⚠️ |
| Does it have no projection target at all? | Yes | Do NOT adopt ❌ |

**Practical examples:**

| Pattern | Silver impact | Adopt? |
|---------|--------------|--------|
| `Identifier` (replaces 6 flat string properties) | New `identifier` table with scheme + validity | ✅ Yes |
| `PartyInRole` (role hierarchy) | New `party_in_role` table with discriminator | ✅ Yes |
| `LegalFormClassifier` (replaces flat `legalForm`) | Inlined via S4 — same `legal_form` column | ⚠️ Optional |
| `QuantityValue` (value + unit) | Inlined as two columns on parent | ⚠️ Optional |
| `DatePeriod` (temporal qualification) | Handled by SCD2 — no separate table | ❌ Skip |

### Rationale

| Approach | Pros | Cons |
|----------|------|------|
| Enforced for everything | Full OWL reasoning | FIBO imports 1000+ classes; DD-021 noise; slow |
| Alignment file only (no adoption) | Zero cost | Zero structural benefit; silver schema doesn't improve |
| **Reference Model Inspired (this)** | Selective structural benefit; clean projections; formal alignment | Requires judgment on which patterns to adopt |
| Domain-local subclasses of imported classes | OWL-correct | Property inheritance issues; namespace confusion |

**Industry best practices supporting this decision:**

| Pattern | Source | How it maps |
|---------|--------|-------------|
| FHIR Profiling | HL7 | Constrain/extend base spec without forking = adopt pattern, own namespace |
| DDD Anti-Corruption Layer | Evans | Alignment file = ACL at domain boundary |
| SSN/SOSA Modularization (MOMo) | W3C | Lightweight core + optional alignment modules |
| Canonical Data Model | EIP (Hohpe & Woolf) | Hub ontology = CDM; SKOS mappings = translators |
| "Conformance = what you use" | W3C DCAT v2 | Align to patterns you USE, not everything in ref model |
| Domain ownership | Data Mesh (Dehghani) | Hub domain owns its silver schema; aligns formally but doesn't couple |

**Why Inspired is the default (not Enforced):**

1. Inspired with zero patterns adopted = no local classes, just documentation (minimum case).
2. The silver structural difference criterion answers "how much to adopt?" on a
   per-pattern basis — no separate strategy needed.
3. Simplifies skill guidance and decision flowcharts.
4. Skills only need one question: "Does this pattern pass the silver structural
   difference test?" — if yes, adopt (with `rdfs:seeAlso`); if no, skip.

### Consequences

**Immediate (this PR):**
- Reference Model Inspired is the default approach for all reference models
- Reference Model Enforced is the override for Kairos-managed ref model repos only
- See `docs/design/dd-032-reference-model-alignment.md` for full specification

**Future work (separate PRs):**

| Component | Update needed |
|-----------|---------------|
| `kairos-design-domain` skill | Use Inspired/Enforced terminology; `rdfs:seeAlso` (DD-033) |
| `kairos-setup-config` skill | Scaffold guidance (no `model/alignments/` — see DD-033) |
| `kairos-diagnose-status` skill | Detect `rdfs:seeAlso` on inspired classes |
| `kairos-execute-project` skill | Clarify `rdfs:seeAlso` is never used in projections |
| `kairos-design-silver` skill | Present Inspired as alternative to imports + whitelisting |
| `kairos-design-gold` skill | Same |
| `kairos-execute-validate` skill | Optional: validate `rdfs:seeAlso` URIs resolve |
| `kairos-help` skill | Update conceptual overview with 2-strategy model |
| `kairos-design-mapping` skill | Document that Inspired patterns change mapping structure |

**No projector code changes required.** Inspired classes are regular local classes —
the projector already handles them identically to any hub-defined class. The alignment
file lives in `model/alignments/` and is never loaded during projection.

**Relationship to DD-021/DD-023:**
- DD-021 (extension-as-whitelist) applies to **Enforced** only — when you `owl:imports` a
  reference model, you whitelist which imported classes to project.
- DD-023 (shared extension defaults) applies to **Enforced** only — reference model repos
  ship `*-silver-defaults.ttl` for imported classes.
- DD-032 (this) applies when you do NOT import — you create local equivalents instead.
- A hub may use Enforced for Kairos reference models AND Inspired for industry standards
  simultaneously.

---

## DD-033: Replace Alignment Files with rdfs:seeAlso on Inspired Classes

**Status:** Accepted  
**Date:** 2026-05-30  
**Affects:** modeling workflow, skill guidance, scaffold, DD-032 alignment mechanism  
**Supersedes:** DD-032 §4 (alignment file convention)  
**Implementation:** Skill docs updated; `model/alignments/` removed from scaffold and scenario tests.

### Context

DD-032 introduced the Reference Model Inspired strategy with SKOS alignment files
(`model/alignments/{domain}-{standard}-alignment.ttl`) as the formal traceability mechanism.
In practice, these files:

- Were **never loaded** by any projector, validator, or design skill
- Required maintaining a **separate file** that could drift from the domain ontology
- Provided no **inline context** when editing silver/gold extensions for an inspired class
- Duplicated information already expressible with standard RDFS predicates

### Decision

**Replace alignment files with `rdfs:seeAlso` directly on inspired class definitions.**

```turtle
# BEFORE (separate file, not loaded, high maintenance)
# model/alignments/party-fibo-alignment.ttl:
:LegalEntity skos:exactMatch fibo-be:LegalPerson .

# AFTER (inline, machine-readable, zero overhead)
# model/ontologies/party.ttl:
:LegalEntity a owl:Class ;
    rdfs:label "Legal Entity"@en ;
    rdfs:comment "A legal entity / company."@en ;
    rdfs:seeAlso <https://spec.edmcouncil.org/fibo/ontology/BE/LegalEntities/LegalPersons/LegalPerson> .
```

**Why `rdfs:seeAlso`:**
- Part of core RDFS — no extra imports needed
- Non-committal — no logical entailments (unlike `owl:equivalentClass` or `rdfs:subClassOf`)
- Machine-readable — tooling can resolve the URI to check reference model alignment
- Loaded with the domain ontology — visible during silver/gold design sessions
- Already used for property-level references to standards (established pattern)

### Rationale

| Approach | Loaded by tooling? | Inline context? | Maintenance? |
|----------|---|---|---|
| Alignment file (DD-032 original) | ❌ Never loaded | ❌ Separate file | High |
| `rdfs:comment` provenance text | ✅ Loaded | ✅ Inline | Low but not machine-readable |
| **`rdfs:seeAlso` (this decision)** | ✅ Loaded | ✅ Inline | Low + machine-readable |

### Consequences

- `model/alignments/` folder is **removed** from scaffold and skill guidance
- Existing hubs with alignment files can migrate by adding `rdfs:seeAlso` to classes
  and deleting the alignment folder
- Design skills can now read `rdfs:seeAlso` to show reference model context
- Projectors continue to ignore `rdfs:seeAlso` (no code change needed)
- DD-032 principles 1-3 remain unchanged; principle 4 is replaced by this decision

---

## DD-034: Extension Vocabulary is the Single Source of Truth; Defer `identityStrategy`

**Status:** Accepted  
**Date:** 2026-05-30  
**Affects:** `scaffold/kairos-ext.ttl`, `medallion_dbt_projector.py`, `medallion_gold_projector.py`, CR-3, `tests/test_ext_vocabulary_coverage.py`  
**Implementation:** Vocabulary declarations + FK-child warning in projectors; coverage guard test.

### Context

A consistency review (`docs/draft/extension-vocabulary-review-2026-05-30.md`) found
that several `kairos-ext:` annotations consumed by the gold projector
(`perspective`, `generateTimeIntelligence`, `olsRestricted`, and a now-reserved
`incrementalColumn`) were **never declared** in `kairos-ext.ttl`. Hub authors got no
`rdfs:comment`, no SHACL, and no IDE help for them. The review also challenged CR-3's
proposal to add a new `kairos-ext:identityStrategy` annotation for FK-child entities.

### Decision

1. **The vocabulary file is the single source of truth.** Every annotation a
   projector reads MUST be declared in `kairos-ext.ttl`. The previously-undeclared
   gold annotations are now declared; `incrementalColumn` (gold) and
   `surrogateKeyStrategy` are declared but marked **RESERVED** (read-but-not-rendered
   / declared-but-not-consumed). A guard test
   (`tests/test_ext_vocabulary_coverage.py`) greps the projectors and fails if any
   consumed `kairos-ext` annotation is undeclared.
2. **Layer-prefix naming convention.** Layer-specific annotations are prefixed
   (`silver*` / `gold*` / `bronze*`); bare names are reserved for cross-layer
   concepts. Local names are never reused across the `kairos-ext` / `kairos-bronze` /
   `kairos-map` vocabularies (the duplicate `incrementalColumn` is flagged for
   future rename).
3. **Defer `identityStrategy` (CR-3).** Implement Option 4 — an improved missing-
   `naturalKey` warning that detects FK-child context (`silverForeignKeyOn`) and
   explains the weak-entity / source-identity / embedded options — instead of adding
   new vocabulary that has no projector consumer.

### Rationale

- Discoverability and validation depend on the vocabulary being complete; a cheap
  grep-based invariant prevents silent drift.
- CR-3's "composite" case is already derivable from `silverForeignKeyOn` + a
  `naturalKey`; "embedded" has no projector that would honour it; `identityParent`
  duplicates topology already in the graph. The real pain was a confusing warning,
  which Option 4 fixes without new annotations (principle: don't ship vocabulary
  with no consumer).

### Consequences

- New `kairos-ext` annotations must be declared in `kairos-ext.ttl` or the coverage
  test fails — a deliberate speed-bump that keeps the vocabulary authoritative.
- RESERVED annotations remain declared (documented) but inert until wired up;
  `kairos-ext:incrementalColumn` (gold) is a render-or-remove decision left open.
- `identityStrategy` / `identityParent` are deferred; revisit only if improved
  warnings prove insufficient. See CR-3 Resolution (2026-05-30).
- Full conceptual reference for hub authors lives in
  `docs/design/dd-034-extension-explanation.md`.

---

## DD-035: Silver S3 Inheritance Gate — Respect `inheritanceStrategy` Annotation

**Status:** Accepted  
**Date:** 2026-05-30  
**Affects:** `medallion_silver_projector.py`, `medallion_dbt_projector.py`, `gold_model.sql.jinja2`, scenario tests  
**Implementation:** Silver pre-scan gate + TPC property inheritance; dbt sources scoping, dim_date CTE, SK validation, FK-child inverse lookup.

### Context

The silver projector unconditionally flattened ALL subtype hierarchies (S3 rule),
merging every child class into its parent table regardless of the ontology author's
intent. This contradicted the dbt and gold projectors, which already gated S3 on
`kairos-ext:inheritanceStrategy "discriminator"` — only folding subtypes when
explicitly annotated.

A change request (`cr-remove-s3-discriminator-default.md`) identified this
inconsistency plus four additional independent bugs:

1. **Sources YAML scoping** — `_gen_sources` emitted ALL vocabulary tables, not just
   those with SKOS mappings to the domain.
2. **dim_date placeholder** — referenced a non-existent `seed_dim_date` model;
   emitted all-NULL columns.
3. **SK validation** — `naturalKey` columns referenced in the surrogate key hash
   were never validated against the actual column list.
4. **FK-child inverse** — properties with `silverForeignKeyOn` were skipped on the
   domain class but never emitted on the target class.

### Decision

1. **Silver S3 gate:** The pre-scan now only folds subtypes into `folded_subtypes`
   when the parent class has `kairos-ext:inheritanceStrategy "discriminator"`.
   Without the annotation, subtypes get their own tables (TPC) and inherit parent
   properties via the `inherit_from` parameter on `_get_class_and_ancestors`.

2. **Sources YAML scoping:** `_gen_sources` now accepts `mappings` and filters
   tables to only those whose URI appears in `mappings["table_maps"]`. Empty
   source systems (no mapped tables) are skipped entirely.

3. **dim_date inline CTE:** Replaced the broken `seed_dim_date` reference with an
   inline date-spine CTE using `TABLE(GENERATOR(ROWCOUNT => 36525))`. The gold
   template now supports `cte` (raw SQL) as an alternative to `model` (ref) in
   `source_ctes`.

4. **SK validation:** After assembling all columns, a warning is logged if any
   `naturalKey` column name doesn't appear in the generated column list.

5. **FK-child inverse:** New `_infer_fk_on_targets` function collects properties
   where `silverForeignKeyOn` points to the current class, ensuring FK columns
   appear on the correct target table.

### Rationale

- Aligns silver with dbt/gold: all three projectors now use the same opt-in
  discriminator pattern. TPC (separate tables per concrete class) is the safe
  default that preserves information.
- Sources scoping prevents dbt compilation errors from undeclared source tables.
- The dim_date CTE makes the gold model self-contained (no seed dependency).
- SK validation catches annotation mistakes early (at projection time).
- FK-child inverse completes the DD-022 `silverForeignKeyOn` contract.

### Consequences

- **Breaking change for silver:** Hubs that relied on unconditional S3 flattening
  must add `kairos-ext:inheritanceStrategy "discriminator"` to parent classes in
  their silver extension. The kairos-design-silver skill guides this.
- dim_date uses Snowflake-specific `GENERATOR()` syntax; a platform switch may be
  needed for other warehouses (already guarded by `target_platform` in other code).
- The `gold_model.sql.jinja2` template now supports both `cte.model` (ref-based)
  and `cte.cte` (raw SQL) — backward compatible.

---

## DD-036: Drop Git Submodules for Reference Models

**Status:** Accepted  
**Date:** 2026-05-31  
**Affects:** `cli/main.py` (init, new-repo, update-refmodels), scaffold workflows, hub repos  
**Implementation:** `_run_reference_models_update()` in cli/main.py

### Context

Reference models were distributed to hub repos as a git submodule at
`ontology-reference-models/`. This caused friction: CI needed `submodules: true`,
users forgot `git submodule update`, `.gitmodules` got stale, and the Copilot
cloud agent couldn't resolve imports without explicit submodule checkout.

Meanwhile, the `update-refmodels` CLI command already implemented a cleaner
approach: sparse-clone the upstream repo, copy files directly, commit them.

### Decision

Remove all git submodule logic. Reference models are committed directly into
`ontology-reference-models/` as regular files. Updated via `kairos-ontology update-refmodels`.

### Rationale

- Simpler developer experience (no submodule commands needed)
- CI is faster (no recursive submodule checkout)
- Copilot agent can read reference models without special config
- Single update mechanism (`update-refmodels`) instead of two (submodule + script)
- Files are version-controlled in the hub repo — easy to diff/track changes

### Consequences

- Existing hubs must remove their submodule: `git rm ontology-reference-models`,
  delete from `.gitmodules`, then run `kairos-ontology update-refmodels`
- Hub repo size slightly increases (reference model .ttl files are committed)
- `update-refmodels` becomes the single way to refresh reference models

---

## DD-037: uv as Standard Environment Manager for Hub Repos

**Status:** Accepted  
**Date:** 2026-05-31  
**Affects:** scaffold/setup-env.ps1, scaffold/setup-env.sh, CLI update --upgrade,
copilot-setup-steps.yml, kairos-setup-init skill, kairos-toolkit-ops skill

### Context

Hub repos are ontology content repositories that depend on the kairos-ontology-toolkit
CLI. Previously, environment setup used a custom `setup-env.ps1` that:
1. Manually created a `.venv` via `py -m venv`
2. Ran `pip install -e ".[dev]"` (wrong — hub repos aren't editable Python packages)
3. Was Windows-only (no Linux/macOS/CI support)
4. Had no lock file for reproducible installs
5. The `update --upgrade` command used `pip install` directly, bypassing any venv

This caused recurring "stale install" issues where `pip install` in one hub
silently overwrote the toolkit in a shared global Python environment.

### Decision

Adopt **uv** (https://docs.astral.sh/uv/) as the sole environment manager for hub repos:
- `uv sync` replaces `py -m venv` + `pip install` (creates `.venv` automatically)
- `uv run <cmd>` replaces manual venv activation
- `uv.lock` provides reproducible installs (committed to the hub repo)
- `update --upgrade` updates `pyproject.toml` then runs `uv lock` + `uv sync`
- No backward compatibility with pip-based setup (clean break)

### Rationale

- **Cross-platform:** uv works on Windows, Linux, macOS — single workflow for all
- **Fast:** 10-100x faster than pip for dependency resolution and install
- **Reproducible:** `uv.lock` ensures all developers and CI get identical environments
- **No stale installs:** `uv sync` always installs exactly what `pyproject.toml` + lock declare
- **PEP 621 compatible:** Our `pyproject.toml` template works with uv natively
- **CI-native:** `astral-sh/setup-uv` action provides one-line CI integration
- **Eliminates confusion:** `uv run kairos-ontology <cmd>` is clearer than
  "activate venv, then run python -m kairos_ontology"

Alternatives considered:
- **pipx / uv tool:** Only installs CLI tools globally, can't pin per-repo or include pytest
- **Keep pip + fix bugs:** Still leaves Windows-only, no lock file, manual venv management
- **Docker / devcontainer:** Too heavy for a CLI tool dependency

### Consequences

- **Breaking change:** Hub repos must install `uv` before using the toolkit.
  Install instructions provided in setup scripts and skill docs.
- `setup-env.ps1` and `setup-env.sh` are now thin wrappers that check uv and run `uv sync`.
- `copilot-setup-steps.yml` uses `astral-sh/setup-uv@v4` action.
- Existing hub repos need to run `kairos-ontology update --force` to get the new scripts.
- The editable install stale-guard in `tests/conftest.py` (toolkit dev repo) remains
  as a safety net for toolkit development itself (which still uses Poetry).

---

## DD-038: Bronze Source Introspection & Layered dbt Architecture

**Status:** Proposed  
**Date:** 2026-06-01  
**Affects:** `integration/sources/`, `_sources.yml` generation, dataplatform repos, dbt projector  
**Implementation:** See `docs/design/dd-038-bronze-introspection-architecture.md` for full ADR

### Context

Vocabulary TTL files (DD-015) are manually maintained bronze contracts. Actual lakehouse
tables drift over time. The hub's dbt projector generates `_sources.yml` with physical
database/schema info, coupling the hub to a specific environment.

### Decision

1. **Hybrid introspection pipeline**: Dataplatform extracts schema via dbt's
   `adapter.get_columns_in_relation()` → YAML → toolkit's `import-source` refreshes
   vocabulary TTL.
2. **Layered source separation**: Hub generates logical `{{ source() }}` refs without
   database/schema; dataplatform owns physical `_sources.yml` binding.
3. **Dataplatform scaffold**: New `init-dataplatform` CLI + skill to bootstrap consumer repos
   with dbt project, extraction macro, and toolkit as uv dependency.

### Rationale

- dbt adapter layer provides platform-agnostic introspection (no custom SQL)
- YAML intermediate is dbt-ecosystem aligned and human-readable
- Source separation follows dbt multi-project best practices
- Vocabulary remains the semantic contract; introspection keeps it current

### Consequences

- Existing dataplatforms need to add their own `_sources.yml` (breaking change, requires
  major version bump)
- Two-step refresh (extract + import) rather than fully automated
- JSON content_type requires manual annotation (adapters don't expose this)

  ---

## DD-039: Enhanced Schema Extraction with JSON Flattening & Bronze Expanded Layer

**Status:** Accepted  
**Date:** 2026-06-02  
**Affects:** `extract-schema` CLI command, `import_source.py`, `kairos-develop-dataplatform` skill, dataplatform staging models, dbt projector  
**Implementation:** `src/kairos_ontology/extract_schema.py`, `src/kairos_ontology/generate_staging.py`, `scaffold/dataplatform/`, `medallion_dbt_projector.py`

### Context

DD-035 introduced a basic introspection pipeline (dbt macro → YAML → import-source).
However, the current macro only captures column names and data types. Real-world bronze
tables (especially in Fabric Warehouse) contain JSON-encoded columns (`varchar(max)`)
with nested structures that need:

1. **Detection** — identify which columns contain JSON
2. **Classification** — determine structure (flat, nested, array, polymorphic)
3. **Flattening** — pre-process JSON into typed columnar tables before silver
4. **Vocabulary enrichment** — generate accurate bronze vocabulary with JSON-derived properties

Parsing JSON directly in silver models is expensive on analytical engines (re-evaluates
`JSON_VALUE`/`OPENJSON` on every query) and violates DRY when multiple models need
the same fields.

### Decision

1. **New `extract-schema` CLI command** replaces dbt macro as primary extraction path.
   Uses Python database drivers (pyodbc for Fabric) to:
   - Query INFORMATION_SCHEMA for full column metadata (nullable, precision, etc.)
   - Sample 5 rows per table for format detection and JSON inference
   - Classify JSON columns (flat/nested/array_object/array_primitive/polymorphic)
   - Output **one YAML per table** in `extracted/<system>/` directory:
     - `_manifest.yaml` — system-level metadata (platform, connection, extracted_at)
     - `<table_name>.yaml` — columns, samples, JSON structure per table
   - Enables incremental re-extraction and clean git diffs

2. **Bronze expanded staging layer** for JSON handling:
   ```
   bronze (raw) → bronze_expanded (JSON flattened) → silver (ontology-generated)
   ```
   - Flat JSON → expanded columns as a `view`
   - Array of objects → `CROSS APPLY OPENJSON` as child `table` with FK
   - Polymorphic → left in bronze, flagged for manual review
   - Auto-generated from `extract-schema` output via `--generate-staging`

3. **Schema YAML v1.1** extends v1.0 with:
   - `row_count`, `distinct_count`, `nullable`, `samples` (5 values)
   - `json_detected`, `json_classification`, `json_structure` (keys + types)
   - Backward compatible: v1.0 YAML (no samples/JSON) still valid

4. **`import-source` extended** to handle v1.1:
   - `flat` → expanded datatype properties on parent class
   - `nested`/`array_object` → linked class with own properties
   - `polymorphic` → `xsd:string` + review flag annotation
   - Samples stored in `kairos-bronze:sampleValues`

5. **Vocabulary enrichment** (`--enrich`, default ON for v1.1):
   - **Enum detection**: `distinct_count ≤ 25 && row_count ≥ 100 && ratio < 0.1`
     → `kairos-bronze:suggestedEnum`, `kairos-bronze:enumValues`
   - **Format detection**: regex on samples → `kairos-bronze:formatHint`
     (uuid, email, date, url, phone, numeric_code)
   - **FK inference**: column naming patterns (`*_id`, `*Id`, `*_key`) + table name matching
     → `kairos-bronze:suggestedForeignKey` + `kairos-bronze:fkConfidence`
   - **Comment enrichment**: top 3 samples in `rdfs:comment`
   - **Row count**: `kairos-bronze:rowCount` on SourceTable
   - All annotations are *suggestions* — design-source skill uses them interactively

6. **Platform-generic design** — driver abstraction:
   - Fabric Warehouse/Lakehouse (pyodbc + Azure CLI/SPN token)
   - Databricks (databricks-sql-connector + PAT or Azure CLI token)
   - Future: Snowflake, PostgreSQL

### Rationale

- **Performance**: flattening once in bronze_expanded avoids repeated JSON parsing in
  silver; materialized tables enable statistics and predicate pushdown
- **Testability**: typed columns in staging models can have dbt tests (not_null, unique)
- **Automation**: JSON structure metadata enables auto-generation of staging models
- **Reuse**: same YAML serves both dataplatform (`_sources.yml` update) and
  ontology-hub (vocabulary import) — single extraction, two consumers
- **5 samples** balances metadata richness vs extraction speed and YAML size

### Consequences

- New optional dependency: `pyodbc` (via `kairos-ontology-toolkit[fabric]` extra)
- Two extraction paths coexist: dbt macro (lightweight, SQL-only) and CLI (rich, Python)
- Bronze_expanded layer adds maintenance for JSON-heavy sources, but is optional
- **Silver source routing:** `kairos-ext:silverSourceRef` annotation on a class makes the
  dbt projector emit `{{ ref('stg_...') }}` instead of `{{ source() }}`. This is opt-in
  via the silver extension file — absent annotation = backward-compatible `source()` behavior.
- JSON classification heuristic (5 samples) may misclassify rare polymorphic columns;
  user review step mitigates this
- Flat JSON staging views are row-preserving (no WHERE filter on NULL JSON) so that
  switching to `ref()` never drops rows silently

---

## DD-040: Skill Lifecycle Architecture — Design / Execute Separation

**Status:** Accepted  
**Date:** 2026-05-30  
**Affects:** All Copilot skills, skill naming, routing, scaffold distribution  
**Implementation:** See `docs/design/dd-040-skill-lifecycle-architecture.md` for full ADR

### Context

Skills were originally monolithic (one skill did both interactive design and code
generation). This led to confusion: users invoked a "design" skill expecting output,
or a "generation" skill expecting interactive guidance.

### Decision

Separate all skills into two categories:
1. **Design skills** (`kairos-design-*`) — interactive, require user confirmation at
   checkpoints, produce/modify source files (TTL, YAML)
2. **Execute skills** (`kairos-execute-*`) — run projections/validations/reports,
   produce output artifacts, no interactive gates

### Consequences

- Clear routing: user intent maps unambiguously to skill category
- Design skills are never run in autopilot mode (hard gates require user input)
- Execute skills can be safely automated in CI/CD pipelines
- Existing skills renamed from long-form (`kairos-ontology-modeling`) to short-form
  (`kairos-design-domain`)

---

## DD-041: LLM-powered Source Affinity Analysis & Coverage Reporting

**Status:** Accepted  
**Date:** 2026-06-04 (updated 2026-06-04)  
**Affects:** `analyse_sources.py`, `coverage_report.py`, `ai_provider.py`, CLI, `kairos-design-domain` skill  
**Implementation:** `src/kairos_ontology/analyse_sources.py`, `src/kairos_ontology/coverage_report.py`, `src/kairos_ontology/ai_provider.py`

### Context

When modeling with the `kairos-design-domain` skill, all source vocabulary is loaded into the
LLM context window. This leads to:
- Context overflow with many sources
- Poor reference model reuse (~18% data property coverage on average)
- No automated correlation between source columns and reference model properties
- No post-modeling feedback loop to measure alignment quality

Name-only matching (tokenized, fuzzy) catches only a fraction of semantic overlaps.
E.g., `arrivalEstimated` ↔ `estimatedArrivalTime`, `MAFINR` ↔ `mafiNumber` require
semantic understanding.

Additionally, reference models are modular (root files declare `owl:imports` to sub-modules).
The original flat `glob("*.ttl")` only found root stubs with almost no class definitions.

### Decision

Introduce two new CLI commands powered by LLM (gpt-5.4-mini, configurable via AI provider):

1. **`analyse-sources`** (pre-modeling) — semantically matches source table/columns against
   reference model domains. Outputs per-source affinity reports to
   `integration/sources/_analysis/`. The modeling skill uses these to scope context
   (only load relevant tables) and seed the Source Evidence Table.

2. **`coverage-report`** (post-modeling) — measures how well the final ontology aligns with
   reference models, with source evidence tracing. Shows class/property coverage %,
   identifies custom vs. industry-standard concepts, and suggests improvements.

**AI Provider abstraction** (`ai_provider.py`):
- Configurable via `KAIROS_AI_PROVIDER=github|azure` env var
- GitHub Models: `GITHUB_TOKEN` + `https://models.inference.ai.azure.com`
- Azure AI Foundry: `AZURE_AI_ENDPOINT` + `AZURE_AI_KEY` (or managed identity)
- Both return OpenAI-compatible client (same SDK)

**Recursive reference model resolution** (`resolve_reference_models()`):
- Discovers TTLs recursively (`**/*.ttl`)
- Groups sub-modules by top-level directory (= domain)
- Merges all files in each domain into a single rdflib.Graph
- Skips pure import-stub files
- `--max-domains` CLI option caps LLM calls for rate limit protection

### Rationale

- LLM semantic matching far exceeds tokenized name matching — understands naming conventions,
  abbreviations, sample data patterns, and domain context from labels/comments
- gpt-5.4-mini provides excellent quality at efficient cost for column→property matching
- Pre-analysis scopes the modeling context → better quality, fewer custom classes
- Post-modeling report creates a feedback loop to iteratively improve coverage
- Sample values (from extract-schema) are key input — `BEANR, NLRTM` → Port.unlocode
- AI provider abstraction allows teams to use their existing Azure AI Foundry deployments
- Recursive resolution handles real-world modular reference models (48 files → 8-10 domains)

### Consequences

- AI provider env var is required for source analysis (GITHUB_TOKEN or AZURE_AI_ENDPOINT)
- New prerequisite gate in modeling skill — sources must be analysed before design
- Output stored in `integration/sources/_analysis/` (gitignored or committed per preference)
- Coverage reports in `output/reports/` provide actionable improvement guidance
- `azure-identity` is an optional dependency (`[azure]` extra group)
- `.env.example` scaffolded into new hub repos with provider documentation

---

## DD-042: Table-centric source classification with module-class grounding

**Status:** Accepted
**Date:** 2026-06-05
**Affects:** `analyse_sources.py`, `analyse-sources` CLI, `kairos-design-domain` + `kairos-design-source` skills (+ scaffold copies)
**Implementation:** `src/kairos_ontology/analyse_sources.py`

### Context

DD-041's `analyse-sources` was **domain-centric**: it looped `N_tables × N_domains`,
making one LLM call per (table, domain) pair and emitting a `domain_contributions[]`
report where a table could appear under many domains with `domain_relevance` scores.
Two problems surfaced in the logistics accelerator (22 data domains):

1. **Cost & ambiguity** — 22 calls per table, and tables ended up "belonging" to many
   domains, giving the modeler no clear primary home per table.
2. **Opaque domain semantics** — data-domain-first mode classified against the curated
   `owns`/`does_not_own` YAML text only; the actual reference-model class semantics
   (e.g. `TradeParty`, `Consignee` from `bsp/party`) never reached the LLM, even though
   the `data-domains.yaml` import URIs resolve to local module TTLs via the catalog.

### Decision

Rewrite to **table-centric, one-call-per-table** classification:

- ONE LLM call per table passes ALL candidate domains; the model returns exactly ONE
  primary `domain` + up to two `secondary_domains`. Invalid ids fall back deterministically
  to `FALLBACK_DOMAIN_IDS = ["mdm", "reference-data"]` (first present), else `unclassified`.
- Output is **table-centric** (`schema_version: 2`): a flat `tables[]` list (each with its
  primary `domain`, `domain_group`, `domain_uris`, `secondary_domains[]`) plus a
  `domain_summary[]` rollup. The affinity matrix reports per-system primary `table_count`.
- **Semantic grounding (direct modules only):** before classification, each data domain's
  `imports[].uri` is resolved via the XML catalog to its local module TTL, and that file's
  *directly declared* `owl:Class` labels are extracted (provenance-based) and capped
  (`MAX_DOMAIN_CLASSES = 18`) into a `class_summary` fed to the prompt. Resolution is done
  **once per run** with a module-path-keyed cache shared across all domains/tables/sources.

### Rationale

- One call per table is cheaper on both call-count and tokens, and yields one unambiguous
  primary domain per table — exactly what the modeling skill needs to scope context.
- `owl:imports` closure was deliberately **not** followed: the full FIBO closure is large and
  slow, and those transitive classes would never fit inside the capped prompt anyway. The
  directly-imported module classes carry the business-meaningful labels the LLM benefits from.
- Provenance-based extraction (classes asserted in the module file itself) is more reliable
  than namespace-prefix matching against import URIs, which is fragile in OWL ecosystems.

### Consequences

- **Breaking output-schema change.** Both consuming skills (`kairos-design-domain` Step 0a/0c,
  `kairos-design-source` §4c) and their scaffold copies were migrated in lockstep to read the
  table-centric schema (select tables where `domain == X` or `X ∈ secondary_domains`).
- The `threshold` parameter is retained for signature compatibility but no longer gates a
  per-table primary (one primary is always returned).
- Grounding is best-effort: unresolvable URIs or a missing catalog degrade gracefully to
  `owns`/`does_not_own` text alone. `--shallow` skips grounding entirely.

---

## DD-043: Propose-alignment — pre-modeling column-to-property matching

**Status:** Accepted  
**Date:** 2026-06-05  
**Affects:** `propose_alignment.py`, `cli/main.py`, `kairos-design-domain` skill  
**Implementation:** `src/kairos_ontology/propose_alignment.py`

### Context

After DD-042 (table-centric classification), each source table is assigned to a data
domain. But the classification is domain-level — it doesn't tell you which source
*columns* map to which reference model *properties*. The modeling skill
(`kairos-design-domain`) had to do this matching manually during the Source Evidence
Table step, often without the reference model's property inventory in context. This
led to:
- Custom local classes being created when reference model classes already covered the
  concept
- Property naming that diverged from reference model property names
- No machine-readable alignment proposal for the modeling skill to consume

### Decision

Add a new `propose-alignment` CLI command that performs **LLM-powered, per-table
column-to-property alignment** against the reference model. The command:

1. Reads affinity reports (`*-affinity.yaml`) to scope tables by domain
2. Resolves `domain_uris` via the OASIS XML catalog to local reference model TTLs
3. For each table: sends ONE LLM call with the table's columns + the domain's
   reference model classes+properties → gets back per-column alignment
4. Produces per-domain `*-alignment.yaml` files (table-centric schema) plus a
   reference class rollup

Design choices:
- **One call per table** (not per domain) — avoids context window overflow for
  domains with many tables/columns, adopted from rubber-duck critique
- **Two-stage in a single prompt** — first table→class, then column→property,
  using the `likely_entity` hint from affinity reports
- **Table-centric output** with reference rollup — consistent with affinity report
  structure and easier to consume alongside it
- **Affinity reports required** — must run `analyse-sources` first; alignment
  reports go into the same `_analysis/` directory

### Rationale

- Bridges the gap between domain-level classification (DD-042) and property-level
  modeling — the missing "middle layer" in the analysis→modeling pipeline
- Pre-computed alignment removes the need for the modeling skill (an LLM itself) to
  do property-level matching in real-time, which can exceed context windows
- Table-centric schema mirrors affinity reports for consistency and easy consumption
- Reuses existing infrastructure: `parse_reference_model`, `parse_source_vocabulary`,
  `CatalogResolver`, `ai_provider`

### Consequences

- The `kairos-design-domain` skill's Step 0a now checks for `*-alignment.yaml` and
  uses it to pre-populate the Source Evidence Table's Ref Match column
- The `reference_rollup` section shows per-class coverage gaps, helping the modeler
  focus on unmatched areas
- `custom_columns` entries (alignment=custom) identify source columns that will need
  new local properties — the modeling skill can focus review there
- Output is additive: does not modify or replace affinity reports

---

## DD-044: Reference Model Specialization Discovery & Materialized Inventories

**Status:** Proposed  
**Date:** 2026-06-12  
**Affects:** `analyse_sources.py`, `propose_alignment.py`, `coverage_report.py`, `inventory.py` (new), `cli/main.py`, DD-032 (amended)  
**Implementation:** `src/kairos_ontology/inventory.py`, `src/kairos_ontology/analyse_sources.py`

### Context

Design-time tools (`analyse-sources`, `propose-alignment`, `coverage-report`) only collect
properties where `rdfs:domain` directly equals a class URI. Properties defined on
**subclasses** of a reference model class are invisible to designers, preventing them from
discovering specialization patterns (e.g., that `registrationNumber` belongs to
`Organisation`, a subclass of `Party`).

Additionally, multiple LLM-based tools re-parse the same reference model TTL files
independently, which is wasteful and opaque.

### Decision

1. **Enforced as default strategy** (amends DD-032): `owl:imports` + `silverInclude`
   whitelisting becomes the default for all reference models. Inspired (`rdfs:seeAlso`)
   becomes an opt-in override. This is safe because `silverInclude` (DD-021) prevents
   projection noise from unused imported classes.

2. **Materialized YAML inventories**: A `generate-inventory` CLI command produces YAML
   files in `model/inventory/` containing classes, properties, and specialization trees.
   These are committed to git and consumed by LLM tools.

3. **Specialization semantics**: Descendant properties are **specialization evidence**,
   not inherited properties. In OWL/RDFS, `rdfs:domain ref:Organisation` does not mean
   Party has that property. Specializations produce refinement suggestions
   ("consider aligning to Organisation") but do NOT inflate coverage percentages.

4. **Validation warnings**: Two new checks — "mapped but not whitelisted" and
   "whitelisted but not mapped" — catch mismatches between `silverInclude` annotations
   and SKOS source mappings.

### Rationale

| Alternative | Why rejected |
|-------------|-------------|
| Treat descendant properties as inherited | Semantically wrong in OWL; inflates coverage |
| PropertyIndex + projector refactor | Over-engineered; projectors work correctly |
| Implicit projection from mappings | Risk of "surprise tables" undermines shift-left |
| On-the-fly computation only | Wasteful re-parsing; no designer visibility |

### Consequences

- `parse_reference_model()` gains an `include_specializations` parameter
- `resolve_reference_models()` gains an `include_specializations` parameter
- `coverage-report` has a new "specialization" alignment category (not counted in coverage %)
- `propose-alignment` prompt includes specialization properties for better LLM matching
- `validate_whitelist_mapping()` function added to `validator.py`
- Hub scaffold should include `model/inventory/` directory
- Skills guidance should default to Enforced strategy

---

## DD-045: Mapping Hints for `propose-alignment`

**Status:** Accepted  
**Date:** 2026-06-13  
**Affects:** `propose_alignment.py`, `cli/main.py`, `kairos-design-mapping` skill, `kairos-design-source` skill  
**Implementation:** `src/kairos_ontology/propose_alignment.py` (hint functions + `include_mapping_hints`), `src/kairos_ontology/cli/main.py` (`--include-mapping-hints`)

### Context

The `design-mapping` skill (GitHub Copilot, interactive) re-derives every SKOS
predicate and SQL transform from scratch inside the conversation, even though
`propose-alignment` already performed the hard semantic column→property matching in
the prior step. This re-derivation is uncontrolled (no versioned prompt, shares the
conversation context window) and repetitive. We want to give `design-mapping` a
richer starting point **without** pretending the LLM can author production SQL
unaided, and **without** breaking the separate pre-modeling role of
`propose-alignment` (its default `*-alignment.yaml` feeds `design-domain`'s Source
Evidence Table — DD-043).

### Decision

1. **Keep `propose-alignment`; do not deprecate it.** Add an opt-in
   `--include-mapping-hints` flag. The default output is **byte-unchanged**,
   preserving the `design-domain` pre-modeling contract.

2. **Deterministic, non-authoritative hints** when the flag is on:
   - Column-level `transform_hint` derived from logical-type compatibility:
     passthrough (`source.Col`) for exact-name + same-logical-type matches; a
     `CAST(...)` candidate when types differ; flag-only when type is unclear.
     Every non-trivial hint carries `requires_human_confirmation: true`; only an
     exact-name + same-logical-type passthrough may set it `false`.
   - Table-level `structural_hints` (`split_candidate`, `dedup_candidate`,
     `merge_candidate`, `multi_target_candidate`) detected by lightweight
     heuristics. All advisory, all require confirmation.

3. **No `skos_hint` field.** The SKOS predicate is a trivial relabel of the existing
   `alignment` category, so the `design-mapping` skill derives it itself. Emitting
   it would add a redundant, authoritative-looking field whose only non-mechanical
   case (`partial` → `closeMatch` vs `narrowMatch`) is exactly where human judgement
   matters — risking rubber-stamping.

4. **`design-mapping` stays reasoning + validation.** Hints accelerate the
   conversation; Gates 4 (read bronze + ontology independently) and 5 (confirm every
   non-trivial transform and structural hint) still apply.

### Rationale

| Alternative | Why rejected |
|-------------|-------------|
| New `propose-mapping` command (LLM authors transforms + deprecates propose-alignment) | LLM can't author production SQL safely (parser only exposes name/type/nullable/samples); one-table-one-target schema can't express split/merge/multi-target; deprecation breaks `design-domain` pre-modeling; weakened gates; negative cost/benefit |
| Emit a `skos_hint` field | Pure relabel of `alignment`; redundant; authoritative-looking default risks rubber-stamping |
| Make transforms authoritative | Transforms encode business policy (encodings, defaults, dedup ordering) the parser cannot infer; must stay human-confirmed |

This applies the deterministic / promptable / judgment tiering documented in
`docs/instruction-guides/context-engineer-methodology-guide.md`: SKOS derivation and
type comparison are deterministic (Tier 1), transform/structural candidates are
advisory (Tier 2 shape), and the final transform/split decision stays human (Tier 3).

### Consequences

- `ColumnAlignment` gains optional `transform_hint`, `transform_confidence`,
  `requires_human_confirmation`, `transform_rationale`; `TableAlignment` gains
  `structural_hints`. Serialized only when populated → default output unchanged.
- `run_propose_alignment()` gains `include_mapping_hints` (default `False`);
  `propose-alignment` CLI gains `--include-mapping-hints`.
- `kairos-design-mapping` and `kairos-design-source` skills (both copies) updated to
  consume hints while keeping confirmation gates.
- Tests: `tests/test_propose_alignment_hints.py` (unit) and
  `tests/scenarios/test_scenario_mapping_hints.py` (acme-hub adminpulse→client,
  including a regression guard that default output has no hint keys).

---

## DD-046: Reference Model Specialization Visibility in Domain Modeling

**Status:** Accepted  
**Date:** 2026-06-13  
**Affects:** `kairos-design-domain` skill (both copies)  
**Implementation:** `.github/skills/kairos-design-domain/SKILL.md` + `src/kairos_ontology/scaffold/skills/kairos-design-domain/SKILL.md`

### Context

Reference models now ship richer specialization trees: a parent class such as
`Party` has subclasses (`Organisation`, `Person`) that carry subclass-specific
properties (`registrationNumber` on `Organisation`; `firstName`/`lastName` on
`Person`). The `design-domain` skill, however, built its **Reference Model Class
Inventory** (Step 0c.1b) by manually reading module TTL and listing only classes
with properties whose `rdfs:domain` points **directly** at the class. It never
unpacked the subclass closure, nor referenced the DD-044 materialized inventories
(`model/inventory/*.yaml`) that already contain the full specialization tree with
subclass properties.

Result: during modeling, a parent class appears to have **none** of its subclasses'
properties. The only indirect path (the alignment YAML, Step 0a.2) surfaces a
subclass property **only if a source column happens to hit it**, so unused subclass
properties stay invisible. The modeler could therefore re-create a local class or
redefine a property that already exists on an imported subclass — silently
duplicating the reference model and undermining the reference-model-first principle
(DD-043).

### Decision

Make reference-model **subclasses and their subclass-specific properties** visible
at every point in the `design-domain` flow where the modeler could otherwise create
a local duplicate:

1. **Step 0c.1b — Reference Model Class Inventory**: prefer the DD-044 materialized
   inventory (`model/inventory/*.yaml`), which contains the specialization tree;
   fall back to raw TTL. List each class's subclasses as nested rows with their
   subclass-specific properties.
2. **Checkpoint 1 (anti-local-class)**: include specialization subclasses in the
   "available reference model classes" table so the modeler sees an existing
   subclass before inventing a similarly-named local class.
3. **Checkpoint 3b (property reuse, Step 2)**: list properties defined on existing
   **subclasses** of the parent, not just the direct `rdfs:domain` chain, and add a
   rule to subclass-and-reuse rather than create a local duplicate.

### Rationale

The fix lives entirely in the skill (documentation/guidance), reusing the inventory
artifacts DD-044 already produces — no new code, no new command, no runtime closure
resolution during modeling (the inventories are pre-materialized, per DD-044). This
keeps the deterministic tier doing the unpacking and the LLM-guided skill simply
presenting it, consistent with the three-tier methodology
(`docs/instruction-guides/context-engineer-methodology-guide.md`).

### Consequences

- `design-domain` Step 0c.1b, Checkpoint 1, and Checkpoint 3b now surface
  subclass-defined properties; the modeler is steered to subclass-and-reuse.
- Depends on DD-044 materialized inventories being present; the skill falls back to
  raw TTL (without subclass closure) when they are absent.
- Documentation-only change to the skill (both copies kept in sync); no projector or
  CLI behavior changes.

---

## DD-047: Deterministic Inventory Freshness Pre-flight Gate

**Status:** Accepted  
**Date:** 2026-06-13  
**Affects:** `inventory.py`, `cli/main.py`, `kairos-design-domain` skill (both copies)  
**Implementation:** `src/kairos_ontology/inventory.py` (`compute_source_hash`, `source_sha256` envelope field, `check_inventories`), `src/kairos_ontology/cli/main.py` (`check-inventory` command)

### Context

DD-046 made reference-model subclass properties visible during domain modeling by
reading the DD-044 materialized inventories (`model/inventory/*.yaml`). But that
visibility is only as good as the inventory: the `design-domain` skill's "prefer
inventories" guidance was a **soft** instruction with no enforcement. A modeler
could proceed against a **missing** inventory (falling back to raw TTL, which hides
subclass closure) or a **stale** inventory (reference models changed since the YAML
was generated), silently reintroducing the exact duplication DD-046 set out to
prevent. The skill's "mandatory" language lived on the checkpoints, but nothing
deterministically verified the inventory was present and current.

### Decision

Add a deterministic, code-level pre-flight gate:

1. **Provenance hash** — `generate_inventory()` now stores `source_sha256` (SHA-256
   of the source TTL bytes) in the inventory envelope.
2. **`check_inventories()`** — classifies every source TTL as `ok`, `missing`
   (has classes but no inventory → blocking), `stale` (stored hash ≠ current →
   blocking), `unverifiable` (pre-DD-047 inventory with no hash → warn), or `orphan`
   (inventory with no source → warn). Class-less TTLs are skipped (mirrors
   `generate-inventory`).
3. **`kairos-ontology check-inventory`** — CLI wrapper that exits non-zero on
   missing/stale; `--strict` also fails on unverifiable; `--warn-only` never blocks.
4. **Skill hard gate** — `design-domain` Step 0c.1b now opens with a 🚦 pre-flight
   instructing the LLM to run `check-inventory` and **STOP** (propose nothing) until
   it passes, regenerating + committing the inventory if needed.

### Rationale

The enforcement is deterministic (Tier 1) — a content-hash comparison, reproducible
and unit-testable — rather than relying on the LLM to honor a soft "prefer
inventories" hint (which is exactly the kind of judgment that should not gate
correctness). Storing a content hash, not an mtime, makes the check robust across
git clones where timestamps are meaningless. Backward compatibility is preserved:
inventories generated before DD-047 lack the hash and are reported as `unverifiable`
(warn, not block) unless `--strict` is used. The gate is still *invoked* by the
skill (the skill harness has no Python entry point), but the pass/fail decision is
now made by code, not by the model.

### Consequences

- Inventory envelope gains `source_sha256` (optional; `None` for graph-sourced
  inventories). Existing readers ignore unknown keys.
- New CLI command `check-inventory`; `design-domain` skill (both copies) gains the
  pre-flight gate at Step 0c.1b.
- Tests: `tests/test_inventory_freshness.py` (hash, `check_inventories`
  classification, CLI exit codes for fresh/missing/warn-only/strict).
- A true blocking gate still depends on the operator/agent actually running
  `check-inventory`; CI hubs may additionally wire it as a pipeline step.

---

## Template for New Decisions

```markdown
## DD-NNN: Title

**Status:** Proposed | Accepted | Deprecated | Superseded by DD-XXX  
**Date:** YYYY-MM-DD  
**Affects:** which components / files  
**Implementation:** where the code lives

### Context

What is the problem or requirement?

### Decision

What did we decide?

### Rationale

Why this approach over alternatives?

### Consequences

What are the trade-offs or follow-on effects?
```
