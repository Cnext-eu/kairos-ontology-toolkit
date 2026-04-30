# Toolkit Design Decisions

This document is the **canonical log** of architectural and design decisions for the
Kairos Ontology Toolkit. Each decision is recorded as an Architecture Decision Record
(ADR) with context, rationale, and current status.

> **Maintenance rule:** Update this file in every PR that introduces or modifies a
> design decision. See `.github/copilot-instructions.md` for the PR checklist.

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
persisting when the scaffold renamed it to `kairos-toolkit-ops`).

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
