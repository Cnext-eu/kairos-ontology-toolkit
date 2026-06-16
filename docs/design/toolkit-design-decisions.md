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
| [DD-048](#dd-048-business-discovery-phase--company-skos-glossary) | Business Discovery Phase & Company SKOS Glossary | Accepted | 2026-06-13 |
| [DD-049](#dd-049-self-upgrade-re-exec--running-vs-pinned-version-guard) | Self-Upgrade Re-exec & Running-vs-Pinned Version Guard | Accepted | 2026-06-13 |
| [DD-050](#dd-050-parquet-source-import) | Parquet Source Import | Accepted | 2026-06-13 |
| [DD-051](#dd-051-start-modeling-routes-to-lifecycle-start--restart-pre-flight) | Start-Modeling Routes to Lifecycle Start & Restart Pre-flight | Accepted | 2026-06-13 |
| [DD-052](#dd-052-import-commands-auto-write-an-import-results-session-file) | Import Commands Auto-Write an Import-Results Session File | Accepted | 2026-06-13 |
| [DD-053](#dd-053-cli-soft-skill-gate) | CLI Soft Skill-Gate | Accepted | 2026-06-13 |
| [DD-054](#dd-054-reference-model-inventories-namespaced-by-owning-model) | Reference-Model Inventories Namespaced by Owning Model | Accepted | 2026-06-13 |
| [DD-055](#dd-055-business-discovery-materializes-reference-model-breadth--links-glossary-to-ref-model-iris) | Business Discovery Materializes Reference-Model Breadth & Links Glossary to Ref-Model IRIs | Accepted | 2026-06-13 |
| [DD-056](#dd-056-relocate-glossary--inventory-folders-to-hub-root-new-hubs-only) | Relocate Glossary & Inventory Folders to Hub Root (New Hubs Only) | Accepted | 2026-06-13 |
| [DD-057](#dd-057-windows-update---upgrade-uses-a-detached-self-healing-managed-file-refresh) | Windows `update --upgrade` Uses a Detached Self-Healing Managed-File Refresh | Accepted | 2026-06-13 |
| [DD-058](#dd-058-modeling-pre-flight-gates-on-source-analysis-unpack-reference-models-before-analyse-sources) | Modeling Pre-Flight Gates on Source Analysis; Unpack Reference Models Before `analyse-sources` | Accepted | 2026-06-13 |
| [DD-059](#dd-059-modeling-pre-flight-adds-a-discovery-completeness-gate-independent-of-source-state) | Modeling Pre-Flight Adds a Discovery-Completeness Gate (Independent of Source State) | Accepted | 2026-06-13 |
| [DD-060](#dd-060-per-document-extraction-tracking-for-business-discovery) | Per-Document Extraction Tracking for Business Discovery | Accepted | 2026-06-13 |
| [DD-061](#dd-061-deterministic-source-coverage-gates-check-alignment--check-source-coverage) | Deterministic Source-Coverage Gates (check-alignment + check-source-coverage) | Accepted | 2026-06-13 |
| [DD-062](#dd-062-update-resolves-an-upward-walked-managed-root-no-silent-split-hub) | `update` Resolves an Upward-Walked Managed Root (No Silent Split-Hub) | Accepted | 2026-06-13 |
| [DD-063](#dd-063-deterministic-skos-glossary-builder-build-glossary) | Deterministic SKOS Glossary Builder (`build-glossary`) | Accepted | 2026-06-13 |
| [DD-064](#dd-064-validate--project-resolve-paths-from-the-hub-root-not-cwd) | `validate` / `project` Resolve Paths From the Hub Root (Not CWD) | Accepted | 2026-06-13 |
| [DD-065](#dd-065-concurrent-cached-ai-pre-modeling-analyse-sources--propose-alignment) | Concurrent, Cached AI Pre-Modeling (`analyse-sources` + `propose-alignment`) | Accepted | 2026-06-14 |
| [DD-066](#dd-066-no-pypi-publishing--git-tag--wheel-url-distribution) | No PyPI Publishing — Git-Tag + Wheel-URL Distribution | Accepted | 2026-06-14 |
| [DD-067](#dd-067-single-line-release-management-with-ephemeral-hotfix-branches) | Single-Line Release Management with Ephemeral Hotfix Branches | Accepted | 2026-06-14 |
| [DD-068](#dd-068-custom-column-triage-in-domain-modeling-issue-164) | Custom-column triage in domain modeling (issue #164) | Accepted | 2026-06-14 |
| [DD-069](#dd-069-propose-alignment-plausibility--address-review-flags-issues-167168) | propose-alignment plausibility & address review flags (issues #167/#168) | Accepted | 2026-06-14 |
| [DD-070](#dd-070-cross-module-candidate-properties-in-propose-alignment-issue-166) | Cross-module candidate properties in propose-alignment (issue #166) | Accepted | 2026-06-14 |
| [DD-071](#dd-071-file-management-hygiene-session-log-archival--non-authoritative-glossary) | File-management hygiene: session-log archival + non-authoritative glossary | Accepted | 2026-06-14 |
| [DD-072](#dd-072-provenance-comment-header-on-toolkit-generated-ttl) | Provenance comment header on toolkit-generated TTL | Accepted | 2026-06-14 |
| [DD-073](#dd-073-transitive-discriminator-folding--silverexclude-issue-172) | Transitive discriminator folding + silverExclude (issue #172) | Accepted | 2026-06-14 |
| [DD-074](#dd-074-multi-source-merge--canonical-superset--per-source-fk-joins-issue-175) | Multi-source merge — canonical superset + per-source FK joins (issue #175) | Accepted | 2026-06-14 |
| [DD-075](#dd-075-sample-grounded-mapping-evidence-masked-example-values--transform-compatibility) | Sample-grounded mapping evidence (masked example values + transform compatibility) | Accepted | 2026-06-14 |
| [DD-076](#dd-076-suggest-shapes--draft-shacl-from-source-profiling) | `suggest-shapes` — draft SHACL from source profiling | Accepted | 2026-06-14 |
| [DD-077](#dd-077-custom-column-triage-hardening-issue-182) | Custom-column triage hardening (issue #182) | Accepted | 2026-06-15 |
| [DD-078](#dd-078-user-facing-extras-packaging--foundry-token-credential-fallback) | User-facing extras packaging + Foundry token-credential fallback | Accepted | 2026-06-14 |
| [DD-079](#dd-079-dbt-cross-table-warning-conflates-inherited-vs-own-properties-issue-181) | dbt cross-table warning conflates inherited vs own properties (issue #181) | Accepted | 2026-06-15 |
| [DD-080](#dd-080-evidence-led-accelerator-first-modeling-consolidates-dd-el-110) | Evidence-Led Accelerator-First Modeling (consolidates DD-EL-1..10) | Accepted | 2026-06-16 |

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

> **Superseded in part by [DD-066](#dd-066-no-pypi-publishing--git-tag--wheel-url-distribution):**
> the toolkit is **never** published to PyPI (the publish job was never wired up and
> has since been removed from CI). References below to "skips PyPI publish" are
> historical — distribution is git-tag / wheel-URL only for *all* releases.

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

## DD-048: Business Discovery Phase & Company SKOS Glossary

**Status:** Accepted  
**Date:** 2026-06-13  
**Affects:** new `kairos-design-discovery` skill (both copies), `kairos-design-mapping`, `kairos-design-domain`, `kairos-help`, `kairos-setup-init`, `copilot-instructions.md` (both copies), `cli/main.py` (`init` + `new-repo`), scaffold (`import/businessdiscovery/`, `ontology-hub/model/glossary/`)  
**Implementation:** `.github/skills/kairos-design-discovery/SKILL.md`, `src/kairos_ontology/scaffold/skills/kairos-design-discovery/SKILL.md`, `src/kairos_ontology/cli/main.py`, `src/kairos_ontology/scaffold/ontology-hub/model/glossary/`, `src/kairos_ontology/scaffold/import/businessdiscovery/`

> **Update 2026-06-13:** the repo-root artifacts folder was renamed from
> `.imports/` (plural) to **`.import/`** (singular); the dotless scaffold source
> folder is correspondingly `scaffold/import/`. All references below use the
> new name.

### Context

Modeling previously started at source/domain design with no structured capture of
*who the company is* or *how they talk about their business*. Two gaps mattered:
(1) company context (what they do, business model, offerings) was never written
down to ground naming/modeling decisions; (2) business-specific terminology — acute
in freight forwarding/logistics, where industry terms carry different in-house
meanings — was lost, even though it is exactly what makes source-to-domain mapping
accurate. Capturing those alternative names directly on the domain ontology would
pollute the canonical model.

### Decision

Introduce **business discovery** as the first phase of the design lifecycle, owned by
a new interactive skill **`kairos-design-discovery`**:

1. **Phase 1 — company research:** read drop-in artifacts plus optional public web
   research; synthesize a confirmed company-context summary.
2. **Phase 2 — terminology capture:** record the company's alternative names in a
   **SKOS glossary** (`skos:prefLabel` = canonical term, `skos:altLabel` = the
   business's name(s)), linked to the domain by **IRI reference only**
   (`rdfs:seeAlso`) — the domain `.ttl` is never modified.

Two artifact locations (both git-committed):

- **Raw artifacts** → `.import/businessdiscovery/` at the **repository root**
  (alongside `ontology-reference-models/`, since both are *imported inputs* rather
  than hub deliverables — NOT under `ontology-hub/`).
- **Synthesized context** → `ontology-hub/.sessions-design/businessdiscovery-*.md`
  (hub-scoped, like all design session logs).
- **Glossary** → `ontology-hub/model/glossary/{company}-glossary.ttl`.

`kairos-design-mapping` loads the glossary and uses `skos:altLabel` matches as
**advisory, user-confirmed candidates** for column→property mapping.
`kairos-design-domain` reads the context/glossary as background only (Gate 6
source-grounding is unchanged). The canonical Fresh Hub Lifecycle becomes
`discovery → source → domain → mapping → silver → gold → validate → project →
diagnose → consume`.

### Rationale

A SKOS **overlay** keeps alternative names out of the canonical ontology while still
making them machine-readable for tooling (and reusable later by projections such as
azure-search synonyms or prompt). Placing `.import/` at the repo root reuses the
existing `ontology-reference-models/` precedent for imported inputs and keeps the
hub deliverable tree clean. Discovery is interactive/no-autopilot because company
facts and glossary terms require human confirmation; web-sourced claims stay marked
inferred until approved.

### Consequences

- `kairos-ontology init` and `new-repo` now create `.import/businessdiscovery/`
  (repo root) and `ontology-hub/model/glossary/` and install the glossary template +
  READMEs.
- New skill is distributed via the scaffold; routing/no-autopilot/lifecycle tables
  updated in both `copilot-instructions.md` copies and the help/setup-init skills.
- Tests: `tests/test_init.py` asserts the new directories + skill for `init` and
  `new-repo`; a glossary-template TTL parse test guards the scaffold sample.

---

## DD-049: Self-Upgrade Re-exec & Running-vs-Pinned Version Guard

**Status:** Accepted  
**Date:** 2026-06-13  
**Affects:** `cli/main.py` (`update --upgrade`, `cli()` group callback), `kairos-toolkit-ops` skill (both copies)  
**Implementation:** `src/kairos_ontology/cli/main.py` (`update`, `_read_pinned_toolkit_version`, `_warn_if_version_mismatch`), `tests/test_cli_update_upgrade.py`, `tests/test_cli_version_guard.py`

### Context

Two related failure modes left hubs silently running the wrong toolkit version:

1. **Stale in-process refresh after `--upgrade`.** `kairos-ontology update --upgrade`
   bumps the `pyproject.toml` pin and runs `uv lock`/`uv sync`, then refreshes the
   hub's managed files **in the same process**. But that process still has the
   *old* package imported (`_toolkit_version`, `_SCAFFOLD_DIR`,
   `_managed_scaffold_map()` are bound to the previously-loaded module). On Windows
   the new wheel isn't even active until the next `uv run`. So the managed-file
   refresh compared/stamped against the **old** version, forcing the user to
   manually re-run `update` to actually pick up new/changed scaffold files.

2. **Running a different toolkit than the hub pins.** Users who run
   `python -m kairos_ontology` / a globally-installed `kairos-ontology` instead of
   `uv run kairos-ontology` could silently execute an older global toolkit. The
   existing `_warn_if_outside_venv()` heuristic is mechanism-based and misses the
   case where the running interpreter is in *some* environment with a different
   pinned version.

### Decision

1. **Auto re-exec the refresh under the new version.** After `--upgrade` performs
   the lock/sync, if the resolved target version differs from the running
   `_toolkit_version`, the command re-execs `uv run kairos-ontology update
   [--check]` (a fresh process that loads the new package), propagates that exit
   code, and skips the stale in-process refresh. It never re-passes `--upgrade`
   (no recursion), preserves `--check`, and falls back to a clear message if the
   re-exec cannot be launched. A no-op upgrade (target == running) keeps the
   in-process path.
2. **Exact version guard.** A new `_warn_if_version_mismatch()` (wired into the
   `cli()` group callback alongside the venv heuristic) reads the toolkit version
   pinned in the hub's `pyproject.toml` (`.whl` URL or legacy `git+…@<tag>` via
   `_read_pinned_toolkit_version()`) and emits a non-blocking stderr warning when
   it differs from the running version, highlighting when the running version is
   older and pointing at `uv run` / `uv sync`.

### Consequences

- `update --upgrade` is now a single seamless command: it upgrades **and**
  refreshes managed files against the new version.
- Every CLI invocation in a hub cross-checks the running version against the pin,
  surfacing global/stale-toolkit usage without blocking.
- Tests: `tests/test_cli_update_upgrade.py` (re-exec on change, `--check`
  passthrough, exit-code propagation, no-op no-reexec) and
  `tests/test_cli_version_guard.py` (pin parsing + warning behaviour).
- `packaging.version` is used for older/newer comparison (already an indirect
  dependency); a string-inequality fallback keeps it non-fatal.

---

## DD-050: Parquet Source Import

**Status:** Accepted  
**Date:** 2026-06-13  
**Affects:** `import_flatfile.py`, `cli/main.py` (`import-flatfile`), `pyproject.toml`, `kairos-design-source` skill (both copies)  
**Implementation:** `src/kairos_ontology/import_flatfile.py` (`_arrow_type_to_sql`, `read_parquet_table`, `run_import_flatfile` dispatch), `tests/test_import_flatfile.py`

### Context

The flat-file importer (`import-flatfile`) supported CSV and Excel only. Several
source systems (warehouse/logistics exports in particular) deliver data as
**Parquet** files, which previously had to be converted to CSV first — losing the
reliable typed schema Parquet carries.

### Decision

Add native Parquet support to `import-flatfile`:

1. **`read_parquet_table()`** reads a single `.parquet` file into the same table
   data dict shape as `read_csv_table()`. Like CSV/Excel, it reads **only sample
   data** — at most `max_rows` rows via a single
   `ParquetFile.iter_batches(batch_size=max_rows)` batch — and never materialises
   the full file. `row_count` reflects the rows actually read.
2. **Direct Arrow→SQL type mapping** (`_arrow_type_to_sql()`): because Parquet
   carries a reliable typed schema, column data types are mapped directly to the
   SQL-like vocabulary (`bigint`/`int`/`decimal`/`date`/`datetime`/`bit`/
   `varchar(max)`) rather than inferred from stringified values. Sample/distinct
   values are still stringified to match the YAML output format.
3. **Optional `parquet` dependency-group** (`pyarrow`), lazy-imported with a clear
   `ImportError` pointing at `pip install kairos-ontology-toolkit[parquet]`,
   mirroring the openpyxl/`[flatfile]` pattern. CI installs it via
   `uv sync --all-groups`.
4. `.parquet` is wired into both the single-file and directory dispatch in
   `run_import_flatfile()`; directories may freely mix CSV/Excel/Parquet.

### Consequences

- Parquet files import with one command, producing the standard
  `_manifest.yaml` + per-table YAML + samples that feed `import-source`.
- Type fidelity is higher for Parquet than CSV (schema-driven, not heuristic).
- pyarrow (~26 MB) is opt-in; CSV-only users are unaffected.
- Downstream post-read logic (technical-column detection, exclusion) applies to
  Parquet automatically.
- Tests in `tests/test_import_flatfile.py` cover the type mapping, the reader
  (nullability, sampling cap, date/timestamp), single-file + mixed-directory
  imports, and the missing-pyarrow `ImportError`.

---

## DD-051: Start-Modeling Routes to Lifecycle Start & Restart Pre-flight

**Status:** Accepted  
**Date:** 2026-06-13  
**Affects:** `copilot-instructions.md` (both copies), `kairos-design-domain` skill (both copies)  
**Implementation:** `.github/copilot-instructions.md`, `.github/skills/kairos-design-domain/SKILL.md` (+ scaffold copies via `scripts/sync_dev_skills.py`)

### Context

`kairos-design-domain` is **data-first**: Gate 6 / the Source Evidence Table
(Step 0c) require imported, analysed source evidence before any class/property may
be proposed. But two routing/UX gaps remained:

1. The Copilot **instructions** mapped "Model / design …" straight to
   `kairos-design-domain` with no framing that domain modeling is a **mid-lifecycle**
   step (`discovery → source → domain → …`). On a fresh hub, "start modeling" could
   send a user into the modeling skill with an empty `integration/sources/`.
2. When **restarting/extending** an existing model, nothing reminded the user that
   **additional source systems** might need importing first. Step 0a only handled a
   missing `_analysis/` directory, implicitly assuming `integration/sources/` was
   already populated.

### Decision

Add lifecycle framing + pre-flight guidance (deliberately **guidance, not a new
blocking gate** — Gate 6 remains the hard constraint):

1. **Instructions.** The "Modeling skill" section and routing guide now state that
   domain modeling follows discovery + source, and that "start modeling" means
   **beginning the modeling lifecycle**. On a fresh hub the agent **auto-hands off**
   to `kairos-design-source` (offering `kairos-design-discovery`) first; when sources
   already exist it runs an explicit source-completeness check.
2. **Skill pre-flight.** `kairos-design-domain` gains a **"Pre-flight checks
   (lifecycle position)"** block, run before any modeling:
   - **P2a (fresh / empty `integration/sources/`): auto-hand off.** Invoke
     `kairos-design-source` (offer `kairos-design-discovery`) to import
     (`import-source` / `import-flatfile`, incl. Parquet) + `analyse-sources`, then
     resume modeling. Start-modeling is treated as the lifecycle entry, not a jump
     into class design.
   - **P2b (sources exist): MANDATORY always-on Source-Completeness Checkpoint.**
     On **every** modeling start where sources exist — **first pass or
     restart/extension** — the agent must list the imported/analysed source systems
     and explicitly ask whether **additional/other** sources need importing before
     building the Source Evidence Table. If yes → route to `kairos-design-source` +
     `analyse-sources`; if complete → continue. Wired into "Session Management → On
     start" (Continue/Review) and cross-referenced from Step 0a.

> **Refinement (2026-06-13, same day):** P2b supersedes the original restart-only
> "Mode B" — the completeness question is now posed on the **first modeling pass
> too**, closing the gap where some-but-not-all sources had been analysed. P2a was
> strengthened from "advise" to an **auto-handoff** to the source skill.

### Consequences

- Users starting on a fresh hub are auto-routed into the lifecycle start instead of
  an evidence-less modeling session, reducing invented classes (the failure mode
  Gate 6 guards against).
- The completeness question now fires on **every** modeling start (not just
  restart), so partially-imported source sets are surfaced before modeling.
- The mandatory **question** is always posed; the user's **answer** is not
  hard-blocked (Gate 6 remains the hard evidence constraint).
- No behavioural/code change — instructions + skill guidance only, distributed to
  hubs via the sync-managed scaffold copies. Parity is enforced by
  `tests/test_scaffold_sync.py`.

---

## DD-052: Import Commands Auto-Write an Import-Results Session File

**Status:** Accepted  
**Date:** 2026-06-13  
**Affects:** `import_session.py` (new), `import_source.py`, `import_flatfile.py`,
`cli/main.py` (init/new-repo), `kairos-design-source` skill

### Context

The `import-flatfile` and `import-source` CLI commands produced vocabulary/YAML
artifacts but left **no audit record** of what each run imported. Every
interactive design skill (`kairos-design-source`, `-domain`, `-discovery`)
already drops a markdown session file under `ontology-hub/.sessions-design/`, but
the *non-interactive* import commands did not.

### Decision

The import commands now **auto-write a machine-generated import-results file** to
a dedicated hub folder, using a template consistent with the existing session
files:

```
ontology-hub/.sessions-design-import/
  └── import-{system-name}-{YYYY-MM-DD}.md
```

- A new module `import_session.py` provides a pure `render_import_session_md()`
  renderer and a best-effort `write_import_session()` writer.
- `run_import_source` (method `yaml-import`, including the change report and
  enrichment flag) and `run_import_flatfile` (method `flatfile`) call the writer
  after writing their artifacts.
- The write is **best-effort and hub-root-gated**: it is skipped (never raised)
  when no hub is detected, so it cannot break an import or pollute unit tests
  that run outside a hub.
- `.sessions-design-import/` is created at hub `init`/`new-repo` with a
  `.gitkeep`, consistent with `.sessions-design/`.

### Rationale

- Separates the **auto-generated import audit log** from the **interactive
  design session file**, keeping each concern in its own folder.
- Same-day re-runs overwrite the file, mirroring the session-file convention.
- Best-effort gating preserves the existing pure behaviour of the import
  functions outside a hub.

---

## DD-053: CLI Soft Skill-Gate

**Status:** Accepted  
**Date:** 2026-06-13  
**Affects:** `cli/main.py` (group + skill-covered commands), gated `*/SKILL.md`
files, `.github/copilot-instructions.md` (+ scaffold copy)  
**Implementation:** `_warn_if_no_skill_context()` + `_SKILL_COVERED_COMMANDS`
in `src/kairos_ontology/cli/main.py`

### Context

The toolkit's "skill-first" rule lived **only in prose**
(`copilot-instructions.md`). Prose guardrails are advisory and are weakest
exactly when the raw CLI succeeds, because nothing pushes back: Copilot runs
e.g. `python -m kairos_ontology project` directly, gets a correct result, and
silently bypasses the skill's pre-flight checks and interactive validation
gates. Reliable skill adoption needs **friction at the CLI layer**, not just
more instructions.

### Decision

Add a **soft skill-gate** to the CLI. Skill-managed commands (`validate`,
`project`, `init`, `new-repo`, `migrate`, `update`, `update-refmodels`,
`import-source`, `import-flatfile`, `generate-staging`, `analyse-sources`,
`init-dataplatform`) emit a loud stderr warning that names the owning skill,
then **still run** (soft, non-blocking). The check is wired once into the Click
group via `ctx.invoked_subcommand`, so individual command bodies are untouched.

A sentinel env var (`KAIROS_SKILL_CONTEXT`, also `KAIROS_VIA_SKILL`) suppresses
the warning. Each gated `SKILL.md` instructs setting it, so the **skill path is
silent and only the raw path nags**. CLI-only commands (`import-tmdl`,
`coverage-report`, `propose-alignment`, `generate-inventory`, `check-inventory`,
`catalog-test`, `lifecycle`) are not gated.

### Rationale

- A soft gate redirects the agent without breaking automation, scripts, or CI.
- Single insertion point (group context) keeps the map declarative and testable.
- The env-var escape hatch lets skills, power users, and CI opt out explicitly.
- Chosen over a hard gate (exit non-zero) — selected by the maintainer — to avoid
  breaking existing non-interactive flows.

### Consequences

- New gated commands must be added to `_SKILL_COVERED_COMMANDS`, and the owning
  `SKILL.md` must set `KAIROS_SKILL_CONTEXT=1` (else it warns during legit use).
- Skill edits must be mirrored to `scaffold/skills/` via `sync_dev_skills.py`.

---

## DD-054: Reference-Model Inventories Namespaced by Owning Model

**Status:** Accepted  
**Date:** 2026-06-13  
**Affects:** `generate-inventory`, `check-inventory`, `model/inventory/*.yaml`  
**Implementation:** `inventory.py` (`inventory_filename`, `check_inventories`),
`cli/main.py` (`generate-inventory` command)

### Context

Materialized inventories (DD-044) were named purely from the source TTL **stem**
(`{stem}-inventory.yaml`). Many reference models contribute a same-named module —
e.g. `party.ttl` exists in BSP, DCSA, IMO, MMT, TIC, and WCO. All six mapped to a
single `party-inventory.yaml`, so generation was **last-write-wins** (alphabetical
→ WCO survived) and the other five models' classes (`bsp:TradeParty` and its role
subclasses, `imo:MaritimeParty`, `mmt:TransportParty`, …) were silently dropped.
The collision also affected `documents`, `locations`, `events`, and `equipment`.

A modeler trusting the inventory (per DD-046) would conclude those classes don't
exist and recreate them locally — exactly the Gate-6 anti-pattern inventories are
meant to prevent. Contrary to the original bug report, the DD-047 staleness gate
did **not** report a false green: it surfaced the collision as *spurious* `STALE`
entries (the single file's stored hash matched only one source), producing an
**unfixable deadlock** — re-running `generate-inventory` could never clear it —
and a reporting glitch where the same stem appeared in both the `ok` and `stale`
lists.

### Decision

Namespace reference-model inventory files by their owning model via a single
shared helper `inventory_filename(ttl_path, *, ref_models_dir)`:

- Reference-model TTL under `derived-ontologies/` →
  `{model}-{stem}-inventory.yaml` (e.g. `bsp-party-inventory.yaml`), where *model*
  is the path segment directly after `derived-ontologies` (intermediate segments
  such as DCSA's `shared-kernel` are ignored).
- Hub-owned ontologies (`model/ontologies/`) keep `{stem}-inventory.yaml` — their
  stems are unique within a hub.

Both `generate-inventory` and `check_inventories` use this helper so the
source→inventory mapping always agrees, which removes the deadlock and the
double-listing glitch. `generate-inventory` gains a default `--prune` that removes
inventory files no longer produced by any source (self-heals legacy stem-named
files), and aborts loudly on any residual same-name collision rather than silently
overwriting.

### Rationale

Per-model filenames give each source TTL a 1:1, sha-verifiable inventory — the
simplest scheme that keeps the DD-047 freshness check sound. The alternative
(merging same-domain modules into one file with per-class provenance) was rejected
as more complex for the freshness gate. Consumers (`propose-alignment`,
`coverage-report`) already glob and merge **all** `*.yaml` in `model/inventory/`,
so they transparently pick up the now-complete set with no code change.

### Consequences

- Existing hubs must re-run `generate-inventory`; `--prune` deletes the stale
  stem-named files and writes the per-model set (commit the result).
- Supersedes the stem-keyed naming established in DD-044 and hardens DD-047.
- Any future same-model/same-stem collision is a loud error (a deterministic
  disambiguation guard can be added if such a case ever arises).

---

## DD-055: Business Discovery Materializes Reference-Model Breadth & Links Glossary to Ref-Model IRIs

**Status:** Accepted  
**Date:** 2026-06-13  
**Affects:** `kairos-design-discovery` skill (+ scaffold copy), `kairos-design-domain`
skill (step 2a note)  
**Implementation:** `.github/skills/kairos-design-discovery/SKILL.md` (Phase 1a,
Phase 1 breadth, Phase 2 IRI resolution, Phase 4 rerun), mirrored to
`src/kairos_ontology/scaffold/skills/`

### Context

Business discovery (DD-048) is meant to be a **company-wide** first step, but its
glossary linking was scoped to the hub: Phase 2 confirmed a term's IRI only against
`model/ontologies/`. Early in a hub only the *first* domain is modeled, so terms
belonging to later domains could not be linked — they all fell into "flagged for
domain modeling". Discovery had no view of the **full** domain model, so the user's
business understanding and terminology capture were implicitly narrowed to the first
domain, risking lost information when subsequent domains were modeled. Materialized
reference-model inventories (DD-044/DD-054) already provide a complete, read-only map
of every available class/property but discovery did not use them.

### Decision

1. **Materialize first (read-only).** Add **Phase 1a** to discovery: run
   `generate-inventory` over `ontology-reference-models/` so discovery has the full
   reference-model breadth as `referencemodels-unpacked/*.yaml` before research. Read-only —
   no hub-graph import, no `.ttl` edits (discovery Gate 4 intact).
2. **Breadth over depth.** Phase 1 research is explicitly company-wide — cover the
   whole offering/operating model and capture out-of-scope-for-now terms.
3. **Three-tier IRI resolution.** Phase 2 resolves a term's IRI in priority order:
   hub IRI (`model/ontologies/`) → existing **reference-model** IRI (from Phase 1a
   inventories) → flag as truly novel. Linking to an existing ref-model IRI is now
   allowed and preferred; only inventing IRIs remains forbidden.
4. **Idempotent reruns.** Add **Phase 4**: on rerun, re-materialize, re-link flagged
   terms to hub IRIs once their domain is modeled, and append new terms. Handoff
   tells the user to revisit discovery on each new domain.

### Rationale

The reference-model inventories are the canonical full-breadth view, and they are
already read-only and sha-verifiable — using them for glossary linking costs nothing
extra and resolves links immediately rather than deferring everything to "flagged".
Keeping it skill-content only (no `generate-inventory` change) is the smallest change
that closes the gap. Importing all reference models into the hub graph was rejected:
it would violate discovery's read-only Gate 4 and bloat the hub with unclaimed classes.

### Consequences

- Discovery now depends on `generate-inventory` having run; the skill invokes it
  (and instructs `update-referencemodels.ps1` if the reference models are absent).
- Supersedes the hub-only linking constraint of DD-048; builds on DD-044/DD-054.
- Glossary entries may carry `rdfs:seeAlso` to a ref-model IRI; these are reconciled
  to hub IRIs on later reruns as domains are modeled — nothing is lost across domains.
- `kairos-design-domain` step 2a notes that glossary terms may point at ref-model
  IRIs and that reconciliation happens on the next discovery rerun (not in the domain
  skill).

---

## DD-056: Relocate Glossary & Inventory Folders to Hub Root (New Hubs Only)

**Status:** Accepted  
**Date:** 2026-06-13  
**Affects:** `init`, `new-repo`, `migrate`, `generate-inventory`, `check-inventory`,
hub scaffold layout, design skills (discovery/domain/mapping/source/help/setup-init)  
**Implementation:** `src/kairos_ontology/cli/main.py`,
`src/kairos_ontology/scaffold/ontology-hub/businessdiscovery/` (moved),
skills (both copies), `CHANGELOG.md`

### Context

Two hub folders lived under `model/`: the company business glossary
(`model/glossary/`, DD-048) and the materialized reference-model inventories
(`model/inventory/`, DD-044/DD-054). Neither is part of the **domain model** itself —
the glossary is a business-discovery artifact (a SKOS overlay) and the inventory is an
unpacked, read-only view of the reference models. Nesting them under `model/` (which
holds the authored ontologies, shapes, extensions, mappings) blurred that distinction.

### Decision

Move both folders up to the hub root and rename them to reflect their purpose:

| Old | New |
|-----|-----|
| `ontology-hub/model/glossary/` | `ontology-hub/businessdiscovery/` |
| `ontology-hub/model/inventory/` | `ontology-hub/referencemodels-unpacked/` |

`init`/`new-repo` scaffolding, the `generate-inventory`/`check-inventory` default
paths, and all design skills now use the new locations. The `migrate` command creates
the new inventory directory name for layout consistency.

Scope is **new hubs only** — no automatic relocation of existing-hub data. Existing
hubs move the two folders manually (the inventory can simply be regenerated with
`generate-inventory`).

### Rationale

The names are self-describing: `businessdiscovery/` pairs with the
`.sessions-design/businessdiscovery-*.md` session files and the repo-root
`.import/businessdiscovery/` inputs, and `referencemodels-unpacked/` makes clear the
folder is a derived/unpacked view rather than authored model content. Limiting the
change to new hubs avoids destructive moves in existing repos; an explicit
auto-migration was rejected as out of scope and risky for committed data.

### Consequences

- New hubs no longer have `model/glossary/` or `model/inventory/`.
- `referencemodels-unpacked/` continues to hold **both** hub-ontology and
  reference-model inventories (single-folder behaviour unchanged; only the path moved).
- Existing hubs keep working only after a manual move/regeneration; the CHANGELOG
  documents the manual step.

---

## DD-057: Windows `update --upgrade` Uses a Detached Self-Healing Managed-File Refresh

**Status:** Accepted  
**Date:** 2026-06-13  
**Affects:** `update --upgrade` (Windows)  
**Implementation:** `src/kairos_ontology/cli/main.py`
(`_schedule_windows_refresh`, `update()` upgrade branch),
`tests/test_cli_update_upgrade.py`

### Context

`kairos-ontology update --upgrade` bumps the `pyproject.toml` pin, runs `uv lock`, and
then refreshes the toolkit-managed files under the **new** version. Because the running
process has the *old* toolkit module loaded in memory (`_toolkit_version` /
`_SCAFFOLD_DIR`), the refresh must happen under a freshly-installed version. Previously
this was done by synchronously re-exec'ing `uv run kairos-ontology update` via
`subprocess.run`.

On Windows this is impossible: the running `kairos-ontology.exe` holds an exclusive lock
on its own executable for its entire lifetime. The synchronous re-exec keeps the parent
alive (blocked in `subprocess.run`), so the child's implicit `uv sync` cannot overwrite
the locked `kairos-ontology.exe` and the refresh fails with a file-lock error — leaving
the pin bumped but managed files stale.

### Decision

On Windows, when the target version differs from the running version, the upgrade no
longer re-execs synchronously. Instead it spawns a **detached** PowerShell helper
(`_schedule_windows_refresh`) that:

1. `Wait-Process -Id <parent-pid>` — blocks until the current process exits, releasing
   the `.exe` lock;
2. runs `uv sync` to install the newly-pinned version;
3. runs `uv run kairos-ontology update` (propagating `--check`) to refresh managed files.

The parent prints a "refresh scheduled" message and exits 0 immediately. Output is
mirrored to a transcript log at `.kairos/upgrade-refresh.log` so the result is durable
after the spawned console closes. If the helper cannot be launched, the command falls
back to printing manual guidance and exits non-zero.

Non-Windows platforms keep the existing inline `uv sync` + blocking re-exec, which has no
lock constraint.

### Rationale

The parent process can never release its own `.exe` lock while alive, so an in-process or
synchronously-chained refresh is fundamentally unworkable on Windows. Deferring the
sync+refresh until after the process exits is the only reliable single-command path, and a
detached helper keeps the upgrade fully automatic ("self-healing") rather than forcing the
user into a manual two-step. A wheel-extract refresh (reading scaffold from the downloaded
`.whl` without syncing) was considered but rejected as more complex and leaving the venv
out of sync with the pin.

### Consequences

- Windows upgrades complete automatically without a file-lock error; the refresh appears in
  a new console window shortly after the command returns.
- A transcript log (`.kairos/upgrade-refresh.log`) records the deferred refresh outcome.
- The detached helper depends on `uv` being on the system `PATH` (it is, since the upgrade
  itself ran via uv).
- `--upgrade --check` is honoured: the scheduled refresh runs `update --check`.

---

## DD-058: Modeling Pre-Flight Gates on Source Analysis; Unpack Reference Models Before `analyse-sources`

**Status:** Accepted  
**Date:** 2026-06-13  
**Affects:** `kairos-design-domain` skill (pre-flight branches), `kairos-design-source`
skill (Phase 4)  
**Implementation:** `.github/skills/kairos-design-domain/SKILL.md`,
`.github/skills/kairos-design-source/SKILL.md` (+ scaffold copies)

### Context

Two adjacent workflow gaps were observed in a client hub:

1. **Modeling started without source analysis.** "Start modeling" routed straight into
   `kairos-design-domain` and proceeded toward the Source Evidence Table even though
   `integration/sources/_analysis/` contained no affinity reports. The skill's pre-flight
   only distinguished *no sources* (P2a → hand off to import) from *sources exist* (P2b →
   completeness checkpoint); it had **no branch for "sources imported but not analysed"**,
   so the data-first analysis (a Gate 6 prerequisite) was silently skipped and Step 0c.1
   fell back to naming heuristics.
2. **Reference-model unpacking happened too late.** `generate-inventory` (the deterministic,
   AI-free materialization of `referencemodels-unpacked/*-inventory.yaml`) was only a *tip*
   before `analyse-sources` and was otherwise enforced as the DD-047 gate at modeling Step
   0c.1b — i.e. mid-modeling. Because it is cheap and AI-free, there was no reason to defer
   it, and deferring it risked failing the DD-047 gate after the long AI analysis had run.

### Decision

1. **Add a modeling pre-flight branch (P2b) that gates on source analysis.** In
   `kairos-design-domain`, the pre-flight now has three branches: **P2a** (no sources →
   hand off to import), **P2b** (sources imported but `_analysis/*-affinity.yaml` missing →
   **auto-hand off to `kairos-design-source` Phase 4** to run the analysis before any class
   design), and **P2c** (sources imported *and* analysed → the existing mandatory
   Source-Completeness Checkpoint, formerly P2b).
2. **Unpack reference models first in source Phase 4.** `kairos-design-source` Phase 4a now
   makes `generate-inventory` (+ `check-inventory`) a **required up-front step** run
   **before** `analyse-sources`, rather than an optional tip. The documented order is
   `generate-inventory` (quick, AI-free) → `analyse-sources` (the long AI run). The
   `kairos-design-domain` Step 0a `_analysis/`-missing handoff was updated to the same
   order.

### Rationale

Domain modeling is data-first: classes/properties must be grounded in analysed source
evidence (Gate 6). A skill that proceeds without affinity reports produces invented
classes, defeating the reference-model-first design. Unpacking the reference models is
deterministic and AI-free, so doing it up front costs nothing and removes a mid-modeling
failure mode (the DD-047 inventory gate) — it is strictly better to unpack before the
expensive analysis.

### Consequences

- "Start modeling" on a hub with imported-but-unanalysed sources now auto-routes through
  `analyse-sources` first instead of silently skipping it.
- The reference-model inventory is materialized before `analyse-sources`, so the later
  Step 0c.1b / DD-047 gate is already green.
- Pre-flight branch labels shifted: the Source-Completeness Checkpoint is now **P2c**
  (was P2b); cross-references in the skill were updated accordingly.
- No CLI/code change — `generate-inventory`, `check-inventory`, and `analyse-sources`
  already exist (DD-044/DD-047/DD-054); this is a skill-flow correction.

---

## DD-059: Modeling Pre-Flight Adds a Discovery-Completeness Gate (Independent of Source State)

**Status:** Accepted  
**Date:** 2026-06-13  
**Affects:** `kairos-design-domain` skill (pre-flight + Step 2a)  
**Implementation:** `.github/skills/kairos-design-domain/SKILL.md` (+ scaffold copy)

### Context

The canonical lifecycle is `discovery → source → domain → …` (kairos-help §2), so
business discovery should precede modeling. But `kairos-design-domain` only hard-gated on
**sources**, not discovery: the discovery offer lived **only** in the no-sources branch
(P2a, where it hands off to `kairos-design-source` and offers discovery). When sources
were already imported, the skill landed in the sources-exist path (P2b/P2c) — which ran
only the source checks and never surfaced discovery. The sole other touchpoint was Step 2a
("read business-discovery context *if present*"), passive context rather than a gate. As a
result, on a hub with imported sources but no `businessdiscovery/` artifacts, nothing ever
prompted discovery, and modeling proceeded without the company model + glossary.

### Decision

Add a **Discovery-Completeness Checkpoint (P1b)** to the modeling pre-flight, symmetric to
the P2c Source-Completeness Checkpoint and **independent of source state** so it fires in
**every** branch (P2a and the sources-exist branches):

1. Detect discovery artifacts — `businessdiscovery/*.ttl` and
   `.sessions-design/businessdiscovery-*.md`.
2. If absent, prompt to run **kairos-design-discovery** first (recommended, not a hard
   block — Gate 6 remains authoritative). The user's decline is recorded in the session
   file.
3. Upgrade Step 2a from "read if present" to an explicit gate that assumes P1b has already
   fired and **must** read discovery artifacts when present.

The Continue/Review extension pre-flight note now also runs P1b alongside P2c.

### Rationale

Discovery is the documented lifecycle start but was only enforced in the empty-sources
branch — an asymmetry that let real hubs skip it. Making the gate independent of source
state (a hub can have sources without ever running discovery) closes the gap. It stays a
recommendation rather than a hard block because discovery improves naming alignment but is
not the authoritative evidence source (that is Gate 6 / source data).

### Consequences

- "Start modeling" now surfaces discovery even when sources are already imported.
- Discovery and source completeness are checked symmetrically (P1b + P2c), once per
  session start.
- No CLI/code change — `kairos-design-discovery` already exists; this is a skill-flow
  correction. Pairs with DD-055 (discovery materialization) and DD-058 (source-analysis
  gate).

---

## DD-060: Per-Document Extraction Tracking for Business Discovery

**Status:** Accepted  
**Date:** 2026-06-13  
**Affects:** `kairos-design-discovery` skill, `.import/businessdiscovery/`,
`ontology-hub/businessdiscovery/_extractions/`, new `discovery-status` CLI command  
**Implementation:** `src/kairos_ontology/discovery_extraction.py`,
`discovery-status` command in `src/kairos_ontology/cli/main.py`,
`.github/skills/kairos-design-discovery/SKILL.md` (Phase 1 / Phase 4) + scaffold copy

### Context

Business discovery reads raw artifacts (PDFs, decks, notes) dropped in
`.import/businessdiscovery/` and extracts company-specific terminology. There was **no
record of what was extracted from which document** and **no way to tell which documents
are new or unprocessed** when more are added later. On a rerun the skill re-read
everything with no provenance and no incremental signal — terminology could be lost or
silently duplicated, and there was no audit trail behind the glossary.

### Decision

Introduce **per-document extraction files** plus a deterministic, hash-based status
command, mirroring the inventory-freshness pattern (DD-047):

- For every processed document, the discovery skill writes one
  `ontology-hub/businessdiscovery/_extractions/{slug}.extraction.yaml` recording the
  `source_sha256`, a summary, the extraction `strategy`, and the `extracted_terms`
  (with a `company_specific` flag). `{slug}` is the slugified source filename **including
  its extension**, so same-stem documents (`report.pdf` vs `report.docx`) never collide.
- A new **`discovery-status`** CLI command (backed by `discovery_extraction.py`) scans
  the import folder, compares each document's current hash to the stored
  `source_sha256`, and classifies it **unprocessed / changed / up-to-date / orphan**.
  Informational by default; `--strict` exits non-zero when there is work to do.
- The skill (Phase 1 + Phase 4) runs `discovery-status` and processes **only** new or
  changed documents, leaving up-to-date ones untouched.

The AI extraction itself stays in the skill; only the deterministic bookkeeping is
implemented in code so it is unit-testable. `discovery-status` is a read-only helper and
is **not** added to the soft skill-gate set (consistent with `check-inventory` /
`generate-inventory`).

### Rationale

Reusing the proven `compute_source_hash` freshness model keeps behaviour consistent and
cheap (no AI for the "what changed?" question). Per-document files give full provenance
that travels with the hub in git, and the hash-based diff makes reruns incremental
instead of re-reading the whole corpus. Storing the files under
`ontology-hub/businessdiscovery/_extractions/` (next to the glossary output) keeps the
provenance committed alongside the deliverable it explains.

### Consequences

- Discovery now has an auditable trail: every glossary term can be traced to a source
  document and its extraction file.
- Adding new artifacts is a cheap, detectable event (`discovery-status` flags them); only
  the delta is reprocessed.
- New hubs get a `businessdiscovery/_extractions/` folder + README via `init`/`new-repo`;
  existing hubs get it via the on-demand `mkdir` in `write_extraction` and the scaffold
  README on `update`.
- The extraction schema is intentionally generic — company-terminology extraction is the
  worked example, not a hard requirement.

---

## DD-061: Deterministic Source-Coverage Gates (check-alignment + check-source-coverage)

**Status:** Accepted  
**Date:** 2026-06-13  
**Affects:** `kairos-design-domain` skill (Step 0a.2), `kairos-design-silver` +
`kairos-execute-project` skills, `propose-alignment` output (alignment YAML
`schema_version` 1 → 2), two new read-only CLI commands  
**Implementation:** `src/kairos_ontology/alignment_coverage.py`,
`src/kairos_ontology/source_coverage.py`, `check-alignment` +
`check-source-coverage` commands in `src/kairos_ontology/cli/main.py`,
`write_alignment_output` in `src/kairos_ontology/propose_alignment.py`

### Context

Reference-model coverage is protected by a **deterministic blocking gate**
(DD-047 `check-inventory`): a modeler cannot proceed until every reference TTL has
a fresh materialized inventory. Source coverage had **no equivalent gate**. The
modeling skill's Step 0a.2 treated a missing `{domain}-alignment.yaml` as
*advisory* ("instruct the user to run `propose-alignment`"), and nothing verified
that the modeled ontology actually represented every source table assigned to a
domain.

This asymmetry let a real shortcut slip through silently: in a client hub the
modeler hand-read 2 of ~67 tables that the affinity reports assigned to the
`party` domain, because `propose-alignment` had never been run (no
`*-alignment.yaml` files existed at all) and nothing blocked.

A naive fix — "gate the Source Evidence Table" — is **not feasible** at
`check-inventory` fidelity: that table is unstructured markdown in a session file
and cannot be deterministically parsed for completeness. The structured artifacts
that *can* be checked are the affinity reports, the alignment YAML, and the
mapping TTLs.

### Decision

Add **two deterministic, AI-free CLI gates**, each modeled on `check-inventory`
(hard-block by default, `--warn-only` escape hatch, read-only → **not** added to
the soft skill-gate set):

1. **`check-alignment`** (pre-modeling input completeness) — for every domain in
   `_analysis/*-affinity.yaml` (schema_version 2, which enumerates every
   `(system, table)` per domain), require a `{domain}-alignment.yaml` that
   **covers all** the domain's tables and is **fresh**. Classification:
   *missing / incomplete / stale* (blocking), *unverifiable / orphan* (warn),
   *ok*. To support freshness, `write_alignment_output` now stores a
   `source_sha256` digest of the affinity `(system, table)` set and bumps the
   alignment `schema_version` 1 → 2; pre-existing v1 files (no hash) classify as
   **unverifiable** (warn, non-blocking) so existing hubs do not hard-break on
   upgrade. Wired as a hard gate in `kairos-design-domain` Step 0a.2.

2. **`check-source-coverage`** (pre-silver output completeness) — compares the
   affinity-assigned `(system, table)` set for each in-scope domain against the
   source tables actually mapped to a domain entity. A table is **covered** when
   its bronze table URI — or any of its column URIs (`kairos-bronze:sourceTable` /
   `belongsToTable`) — is the subject of a SKOS match in `model/mappings/*.ttl`.
   Uncovered tables are blocking. Wired as a mandatory pre-flight before silver in
   `kairos-design-silver` and `kairos-execute-project`.

### Rationale

Both gates operate on **committed, structured** data (affinity YAML, alignment
YAML, bronze vocab + mapping TTLs), so "did propose-alignment cover every domain
table, and is it still fresh?" and "is every domain table mapped before silver?"
become objective set-difference + hash questions — exactly the property that makes
`check-inventory` reliable. The unstructured Source Evidence Table is deliberately
**not** the gate target. Reusing the hard-block-with-`--warn-only` shape keeps the
operator experience consistent across all deterministic gates.

### Consequences

- The exact client-hub shortcut is now caught: zero alignment files →
  `check-alignment` blocks immediately; a partially-mapped domain →
  `check-source-coverage` blocks before silver.
- `propose-alignment` output is versioned (`schema_version` 2) and carries a
  freshness hash; re-running it after sources change is detectable as *stale*.
- Existing v1 alignment files remain valid (reported as *unverifiable* until
  regenerated) — no forced migration.
- Two new read-only commands join `check-inventory` / `coverage-report` as
  skill-gate-exempt deterministic helpers.

---

## DD-062: `update` Resolves an Upward-Walked Managed Root (No Silent Split-Hub)

**Status:** Accepted  
**Date:** 2026-06-13  
**Affects:** `src/kairos_ontology/hub_utils.py`, `src/kairos_ontology/cli/main.py` (`update`)  
**Implementation:** `find_managed_root()` in `hub_utils.py`; re-root + guards in the `update` command

### Context

A hub user ran `uv run kairos-ontology update --upgrade` from the `ontology-hub/`
*content* subdirectory of their hub. Instead of updating the real hub at the repo
root, the command **scaffolded an entire second hub** under `ontology-hub/`
(`pyproject.toml`, `uv.lock`, `.venv`, `.github/`, skills) and left the real
repo-root pin untouched — a silent split-hub.

Three root causes:

1. **`update` trusted `Path.cwd()` and never walked up.** It hard-coded
   `Path.cwd()` for both the toolkit pin and the managed-file root. Unlike git,
   uv, npm, and cargo, it did not search ancestors for the project root.
   Even `find_hub_root` only inspects `cwd` and `cwd/ontology-hub`, never parents.
2. **Silent legacy `pyproject.toml` fabrication.** When `cwd/pyproject.toml` was
   missing, `--upgrade` generated a brand-new hub pin from the scaffold template —
   the actual trigger that manufactured the second hub from a non-hub subdir.
3. **No nested-execution guardrail.** Nothing detected that an ancestor already
   *was* a hub (had the `[tool.kairos]` pin / managed `.github/`).

Note the dual layout in such hubs: the *managed root* (pin + `.github/`) is the
repo root, while the *content root* is `ontology-hub/`. `update` only ever touches
managed files + the pin, so it must anchor on the **managed root**, independent of
the content root.

### Decision

Add `find_managed_root(cwd)` to `hub_utils.py` that walks **up** from `cwd` and
returns the first ancestor that is a managed root — detected by any positive
anchor: a `pyproject.toml` referencing `kairos-ontology-toolkit` or `[tool.kairos]`,
a `.github/copilot-instructions.md` carrying the managed marker, or a dataplatform
root (`dbt_project.yml` + a `.github/`).

The `update` command now, before doing anything:

- Resolves `managed_root = find_managed_root(cwd)`. If found and different from
  `cwd`, it prints a notice (`↪ Detected hub root at … — operating there.`) and
  `os.chdir`s to it, so the existing `Path.cwd()`-based pin write, `uv lock`/`sync`,
  re-exec, and Windows detached refresh all target the real root.
- **Refuses to fabricate** a `pyproject.toml` (and refuses the plain refresh) when
  `managed_root is None` — it hard-errors with guidance to run from a hub root or
  use `new-repo`/`init`. Legacy fabrication is kept **only** when a managed root is
  positively detected (e.g. a `.github`-marked hub that predates the pin file).

### Rationale

Auto-re-rooting (chosen over hard-erroring on subdir invocation) matches familiar
project-tool ergonomics — users can run `update` from anywhere inside the hub. The
hard guard against fabrication-without-evidence eliminates the destructive failure
mode (a second hub) while preserving the legitimate legacy-migration path.
`find_hub_root` (content-command resolution) is intentionally left unchanged; this
fix is scoped to `update`'s managed-root resolution.

### Consequences

- Running `update`/`--upgrade` from a content subdir now correctly updates the real
  hub and never creates a second one.
- Running in a non-hub directory hard-errors instead of silently scaffolding.
- Legacy hubs (managed `.github`, no pin) still get a generated `pyproject.toml`.

---

## DD-063: Deterministic SKOS Glossary Builder (`build-glossary`)

**Status:** Accepted  
**Date:** 2026-06-13  
**Affects:** `src/kairos_ontology/glossary_builder.py`, `src/kairos_ontology/cli/main.py` (`build-glossary`), `kairos-design-discovery` skill  
**Implementation:** `build_glossary()` + helpers in `glossary_builder.py`; `build_glossary_cmd` in `cli/main.py`

### Context

The `kairos-design-discovery` skill (Phase 2) captures a company's
alternative/business terminology as structured records in per-document extraction
files (`businessdiscovery/_extractions/*.extraction.yaml`, DD-060). Each
`extracted_terms` entry already carries `altLabel`, `prefLabel`, `definition`,
`category`, `company_specific` and a resolved `linked_iri`.

To turn those records into the company glossary TTL, the skill instructed the
agent to **hand-write a one-off `rdflib` script every run**. That serialization is
purely mechanical and identical each time, yet being agent-authored it was
non-deterministic, untestable, and risked drift (PascalCase local names,
`rdfs:seeAlso` vs `skos:relatedMatch`, splitting/grouping, deduping altLabels).
This mirrors the bookkeeping that DD-060 already moved out of the skill into a
deterministic, unit-tested module.

### Decision

Add a deterministic, AI-free `kairos-ontology build-glossary` command backed by a
new `glossary_builder.py` module. It reads the confirmed extraction files,
aggregates `extracted_terms` into deduplicated SKOS concepts (grouped by
`linked_iri`, else normalized `prefLabel`), and emits
`businessdiscovery/{company}-glossary.ttl` as a SKOS `ConceptScheme` overlay via
`rdflib` (never string concatenation). `linked_iri` becomes `rdfs:seeAlso`, or
`skos:relatedMatch` when the term sets `link_relation: relatedMatch` (e.g. a
reference-model cross-reference). Company name/domain and the glossary namespace
(`https://{company-domain}/glossary#`) are auto-detected from the hub `README.md`
and overridable via flags.

The *judgement* (prefLabel choice, IRI resolution, multi-IRI splitting, term
confirmation) stays interactive in the skill; only the TTL writing is delegated to
the command. Like `discovery-status` and the `check-*` gates, `build-glossary` is a
deterministic helper and is **not** in `_SKILL_COVERED_COMMANDS` (no soft
skill-gate warning).

### Rationale

Splitting "decide" (agent) from "serialize" (toolkit) yields consistent, testable,
idempotent output and removes a recurring source of agent-authored variance. It
keeps the glossary an overlay (Gate 4 — the domain `.ttl` is never touched) and
reuses the existing extraction schema as the single source of truth.

### Consequences

- The discovery skill now calls `build-glossary` instead of hand-writing Python.
- Glossary serialization is unit-tested (`tests/test_glossary_builder.py`) and
  reruns are idempotent.
- The extraction schema gains an optional `link_relation` field
  (`seeAlso` default | `relatedMatch`).

---

## DD-064: `validate` / `project` Resolve Paths From the Hub Root (Not CWD)

**Status:** Accepted  
**Date:** 2026-06-13  
**Affects:** `src/kairos_ontology/cli/main.py` (`validate`, `project`, `_resolve_catalog`)  
**Implementation:** `find_hub_root()`-based default resolution in the `validate`/`project` command bodies; hub-root-aware `_resolve_catalog()`

### Context

The `validate` and `project` commands hardcoded CLI option defaults relative to the
current working directory, assuming invocation from the **repo root**:

- `validate`: `--ontologies ontology-hub/model/ontologies`, `--shapes ontology-hub/model/shapes`
- `project`: `--ontologies ontology-hub/model/ontologies`, `--output ontology-hub/output`
- shared `_resolve_catalog` candidates: `ontology-hub/catalog-v001.xml`,
  `ontology-reference-models/catalog-v001.xml`

Running from **inside** `ontology-hub/` (a common workflow) broke both commands
through the same cwd-relative root cause, with two observed symptoms:

1. **`validate` hard-errored before running.** `--ontologies`/`--shapes` used
   `click.Path(exists=True)`, so Click validated the (now wrong) **default** and
   exited 2 ("Path '…' does not exist") before the body ran. The same failure hit
   any hub legitimately lacking a `shapes/` directory (SHACL shapes are optional).
2. **`project` nested its output.** `--output ontology-hub/output` resolved to
   `ontology-hub/ontology-hub/output/`, so generated silver/dbt/powerbi artifacts
   and `projection-report.json` landed doubly-nested instead of under
   `ontology-hub/output/medallion/…`.

Newer commands (`coverage-report`, `discovery-status`, `build-glossary`,
`generate-inventory`) already avoid this by resolving from `find_hub_root()`, which
detects the hub whether cwd is the repo root or the hub itself.

### Decision

Resolve `validate`/`project` default paths from `find_hub_root(cwd)` (mirroring
`coverage-report`):

- Change `--ontologies` / `--shapes` / `--output` / `--catalog` defaults to `None`
  and resolve them in the command body from the detected hub root
  (`hub_root/model/ontologies`, `hub_root/model/shapes`, `hub_root/output`).
- Drop `exists=True` on `--shapes` (optional; `run_validation` already guards with
  `shapes_path.exists()`) and on `--ontologies` (replaced by a manual existence
  check that emits a clear, actionable error).
- Make `_resolve_catalog(explicit, hub_root, cwd)` search the hub catalog
  (`hub_root/catalog-v001.xml`) and the reference-models catalog (via
  `_resolve_ref_models_dir`) first, keeping the legacy cwd-relative candidates as a
  fallback.
- Explicit user-supplied paths always win.

### Rationale

Reusing the established `find_hub_root` pattern makes both commands work identically
from the repo root or from inside `ontology-hub/`, matching the rest of the CLI.
Dropping `exists=True` in favour of manual checks turns Click's opaque
default-validation `UsageError` into a clear message and supports shapes-less hubs.
`project` output anchored at `hub_root/output` permanently eliminates the
doubly-nested output directory.

### Consequences

- `validate` no longer exits 2 when run inside `ontology-hub/` or in a hub without
  `shapes/`; `project` writes to `<hub>/output` regardless of cwd.
- Regression coverage in `tests/test_cli_path_resolution.py` exercises both commands
  from the repo root and from inside the hub, with/without a `shapes/` dir.
- This fixes only *future* runs; a hub that already has a stray nested
  `ontology-hub/ontology-hub/output/` should delete it and regenerate.

---

## DD-065: Concurrent, Cached AI Pre-Modeling (`analyse-sources` + `propose-alignment`)

**Status:** Accepted  
**Date:** 2026-06-14  
**Affects:** `analyse-sources` + `propose-alignment` CLI commands, `kairos-design-source`
+ `kairos-design-domain` skills, `kairos-help` CLI listing  
**Implementation:** `src/kairos_ontology/_concurrency.py`, `src/kairos_ontology/_cache.py`,
`src/kairos_ontology/_cost.py`, `src/kairos_ontology/analyse_sources.py`,
`src/kairos_ontology/propose_alignment.py`, `src/kairos_ontology/cli/main.py`

The two LLM-powered pre-modeling steps issued one **blocking** LLM call per source
table, strictly serially. On a large hub (546 tables) this ran ~45–65 min. This DD
parallelizes both commands (bounded `ThreadPoolExecutor`, `--max-workers` default 8,
deterministic input-order YAML), adds two-level incremental caching (domain-level
skip via the existing `affinity_sha256` + a schema-neutral per-table sidecar under
`<analysis-dir>/.cache/`), anchors alignment class selection on the affinity
`likely_entity`, retunes the full-inventory retry gate, slims prompts, and prints a
prominent cost banner recommending `gpt-5.4-mini`. `--force` bypasses both cache
layers; `--max-workers 1` reproduces the original serial path.

**Full ADR:** see the companion file
[`dd-065-ai-pre-modeling-performance.md`](dd-065-ai-pre-modeling-performance.md).

---

## DD-066: No PyPI Publishing — Git-Tag + Wheel-URL Distribution

**Status:** Accepted  
**Date:** 2026-06-14  
**Affects:** `.github/workflows/release.yml`, `README.md`, `kairos-toolkit-ops` +
`SC-merge-pr` skills (and scaffold copies)  
**Implementation:** `release.yml` `build` + `github-release` jobs (no `publish-pypi`
job, no `id-token` permission)

### Context

The `release.yml` workflow carried a `publish-pypi` job (and an `id-token: write`
permission for OIDC trusted publishing), but it was **commented out** and its own
note read *"trusted publisher not configured for this project."* The project has
never been published to PyPI. In practice the toolkit is distributed and consumed
entirely through **GitHub Releases**: `release.yml` attaches the built wheel + sdist
to the release, and hub repos pin the toolkit to a git tag / `.whl` asset URL that
`kairos-ontology update --upgrade` resolves via the GitHub Releases API (DD-013).

The dormant PyPI scaffolding was dead weight and actively misleading: skills claimed
a stable release "Publishes to PyPI", and the README advertised
`pip install kairos-ontology-toolkit` plus a non-functional PyPI version badge.

### Decision

Drop PyPI publishing from the toolkit entirely:

- Remove the commented-out `publish-pypi` job and the now-unused `id-token: write`
  permission from `release.yml` (keep `contents: write` for the GitHub Release).
- The `build` + `github-release` jobs are unchanged — every tagged release still
  produces a GitHub Release with the wheel + sdist attached, for **both** stable and
  pre-release tags.
- Correct all docs/skills: install + upgrade instructions reference the git-tag /
  wheel-URL flow, not `pip install` from PyPI.

### Rationale

- `pip install git+https://…@vX.Y.Z` (and the wheel-URL pin used by hubs) already
  covers every install/upgrade path — PyPI adds nothing for this internal/community
  toolkit.
- Removing the inert job eliminates a confusing "is this published?" question and an
  unnecessary high-privilege (`id-token`) permission on the release workflow.
- Keeping artifacts on the GitHub Release preserves the existing, working
  `update --upgrade` resolution (DD-013) with zero behavioural change.

### Consequences

- The toolkit is **not** installable from PyPI; the README and skills now reflect
  this. No PyPI version badge.
- Re-enabling PyPI later means registering the project and adding a publish job back
  (configure OIDC trusted publishing, gate on non-pre-release tags) — a deliberate
  future decision, not a default.
- Supersedes the PyPI-publish aspects of **DD-013** (its "skips PyPI publish" wording
  is now historical; no release publishes to PyPI).

---

## DD-067: Single-Line Release Management with Ephemeral Hotfix Branches

**Status:** Accepted  
**Date:** 2026-06-14  
**Affects:** `docs/RELEASING.md` (new), `CONTRIBUTING.md`, `kairos-toolkit-ops` skill
(+ scaffold copy)  
**Implementation:** Documentation + process only — no tooling or CI changes

### Context

The toolkit ships frequently, and the team (~5 people) needs to patch the
**currently released** version without dragging in unreleased feature work that has
already landed on `main`. Until now the process was purely trunk-based (PR → `main`
→ tag on `main`) with no documented answer for "a bugfix is needed but `main`
already contains the next minor's features." Tagging `main` in that state would
publish those features inside what should be a patch release.

The team confirmed it supports **only the latest release line** — once a new minor
ships, older lines are dropped. Heavier models (per-minor `release/X.Y` maintenance
branches, GitFlow, release automation bots) would be over-engineering at this scale.

### Decision

Adopt **trunk-based development + ephemeral hotfix branches**, documented in a new
`docs/RELEASING.md` (the single source of truth):

- **SemVer discipline:** `fix:` → patch, `feat:` → minor, breaking → major. A bugfix
  always ships as its own patch tag and is **never** bundled into a feature/minor
  release.
- **Bugfix decision tree:**
  - If `main` has **no** unreleased features (`git log vX.Y.Z..main` is empty/chore)
    → fix on `main` via a `fix/*` PR, bump patch, tag `main`.
  - If `main` **already carries** unreleased features → cut `hotfix/x.y.z` from the
    release **tag** `vX.Y.Z`, fix + patch-bump, tag from that branch (it becomes the
    new *Latest* GitHub Release), then **back-merge to `main`** (keep `main`'s
    in-progress version on conflict; apply the `skip-version` label since the
    back-merge touches `src/` without a `main` bump).
- **Feature releases & pre-releases** stay exactly as before (minor bump + tag on
  `main`; RC tags via the `preview` channel — DD-013).
- **No long-lived maintenance branches.** A `hotfix/*` branch is created only when
  needed and deleted after back-merge.
- **Branch naming:** `feature/*`, `fix/*`, `hotfix/x.y.z`, `chore/*`, `docs/*`.

### Rationale

- Cutting the hotfix from the **tag** (not `main`) is what guarantees a clean patch
  with zero unreleased features — the central requirement.
- Supporting only the latest line means a maintenance branch would sit idle and add
  merge overhead; an ephemeral branch is the minimum that solves the problem.
- Reuses existing machinery (tag-triggered `release.yml`, GitHub-Release
  distribution, `version-check` + `skip-version` label) — no new CI or tooling.

### Consequences

- Contributors have a documented, copy-paste flow for patch vs feature releases;
  `CONTRIBUTING.md` and the `kairos-toolkit-ops` skill link to `docs/RELEASING.md`.
- The back-merge step is mandatory after a Case-B hotfix, or the fix would be lost in
  the next minor; the `skip-version` label is the expected escape hatch there.
- **Future, only if the team/scope grows:** per-minor `release/X.Y` maintenance
  branches, release automation (release-please/semantic-release), artifact signing.
  Explicitly out of scope today.

---

## DD-068: Custom-column triage in domain modeling (issue #164)

**Status:** Accepted  
**Date:** 2026-06-14  
**Affects:** `propose_alignment.py`, `alignment_coverage.py`, `cli/main.py`
(`check-alignment`), `.github/skills/kairos-design-domain/SKILL.md` (+ scaffold copy)  
**Implementation:** `disposition` field on `custom_columns`;
`collect_custom_columns` + `CustomColumn` + `check-alignment --strict`

### Context

When modeling a domain under the Reference Model Enforced strategy, the
`kairos-design-domain` workflow could finalize a domain that reused reference
classes but **silently dropped source-evidenced columns with no reference-model
property** (e.g. `credit_limit`, `currency`, `payment_iban_code`, billing address,
`eori_number`, lifecycle flags). The signal already existed in
`{domain}-alignment.yaml` (`custom_columns:` per table;
`reference_rollup[].custom_extensions_count`) but was never surfaced in a checkpoint,
and nothing forced these columns to be triaged before COMPLETED. The gap only
surfaced later, during `kairos-design-mapping`, as unmappable columns (issue #164).

### Decision

Make custom-column triage **explicit and deterministically verifiable**, without a
new artifact:

1. **Persist a `disposition` field** on each `custom_columns` entry in the existing
   `{domain}-alignment.yaml` (`model` / `silver-passthrough` / `skip`; `null` until
   triaged). `propose-alignment` writes it `null`; the modeling skill fills it.
2. **`check-alignment` surfaces + classifies custom columns** — high-priority
   (business / has `suggested_property`) shown first, likely-operational/audit
   (ETL/surrogate heuristics) listed separately. Identity is `system.table.column`;
   the inflated per-class `custom_extensions_count` is **not** used as a threshold.
3. **`--strict` blocks on *undisposed* custom columns** (not mere presence). Default
   warns; `--warn-only` overrides `--strict` (exit 0). Wired into the skill's
   domain-COMPLETED checkpoint.
4. **Skill** ties it together: every `custom_columns` entry must appear as a
   `❌ Custom` row (Step 0c.4), a mandatory Custom Column Triage table records a
   disposition back into the YAML (Checkpoint 3b), and the completion gate runs
   `check-alignment --strict`. The "Reference Model Enforced" wording is clarified
   (class-hierarchy reuse is enforced, but source-evidenced columns still warrant
   local extension properties; zero-local-property is a special case).

### Rationale

A warn-only report plus skill-only guidance was rejected (rubber-duck review): with
no persisted state a gate can only *count*, never verify triage, leaving the same
silent-drop hole. A **separate disposition file** was also rejected as
over-engineered — annotating the existing alignment YAML is not a new artifact and is
the lightest mechanism that makes `--strict` a real gate. Classifying rather than
threshold-filtering keeps genuine business columns visible without arbitrary cutoffs.

### Consequences

- Re-running `propose-alignment` regenerates the YAML and resets dispositions
  (consistent with the existing freshness model — regeneration implies the source set
  changed and triage should be revisited).
- `--strict` requires every custom column (including audit columns) to carry a
  disposition; operational columns can be bulk-set to `skip`. Nothing is silently
  dropped.
- Deferred: cross-checking `model` dispositions against produced TTL properties; a
  `coverage-report` mode for custom columns; CI hard-enforcement.

---

## DD-069: propose-alignment plausibility & address review flags (issues #167/#168)

**Status:** Accepted  
**Date:** 2026-06-14  
**Affects:** `propose_alignment.py`, `alignment_coverage.py`, `cli/main.py`,
`kairos-design-mapping` skill  
**Implementation:** `src/kairos_ontology/propose_alignment.py`
(`_review_column_alignment`, `_detect_address_part`, `ColumnAlignment.review`),
`src/kairos_ontology/alignment_coverage.py` (`collect_review_columns`,
`AlignmentCheckReport.review_columns`)

### Context

`propose-alignment` scopes its reference-property candidate set **per target
domain**. When a source table is classified into a domain that lacks a concept
(e.g. `party`, which imports only `*/party` modules), columns whose true match
lives in a sibling module fall through — and worse, the LLM **force-fits** them
onto unrelated in-domain scalars. Observed on the CLdN hub:
`SHIPPER_STREET → partyName`, `SHIPPER_ZIP → registrationNumber`,
`FCPAYABLEIND → partyIdentifier`. These structurally implausible maps passed
silently, polluting the matched set and misleading downstream mapping
(issues #167, #168). Cross-module candidate support (#166) is the broader fix
and is **out of scope** here.

### Decision

Add a deterministic, no-LLM **review pass** that runs on the main thread during
table assembly (after sidecar-cache retrieval; the cached raw LLM `result` dict
is never mutated). For each mapped column it sets `review: true` + a precise
`review_reason` when a rule fires — **the mapping is kept, only flagged**:

- **#167 address-part** — `_detect_address_part` fires on strong evidence only
  (unambiguous tokens `street`/`postalCode`/`addressLine*`/`houseNumber`, or a
  weak token `city`/`country`/`zip` together with an address qualifier such as
  `shipper`/`billing`). An address-part column mapped to a **non-address**
  property is flagged; mapped to an address-flavoured property it is exempt.
  The `review_reason` is **generic** — it does not hardcode
  `reference-data#Address`/`hasAddress` (that is #166's job).
- **#168 plausibility** — boolean source → identity/name property;
  financial-flavoured column (`iban`/`bic`/`currency`/…) → generic identity
  property (`partyIdentifier`/`registrationNumber`/`partyName`, with specific
  identifiers like `taxIdentifier`/`vatNumber` excluded); and no shared
  name token between column and property **plus** confidence below
  `REVIEW_MIN_CONFIDENCE` (0.6).

`check-alignment` collects flagged columns into a **report-only**
`review_columns` section that **never blocks** — kept separate from the #164
custom-column `--strict` gate. Output is strictly additive: when no rule fires
the YAML is byte-identical to pre-DD-069. The optional `address_candidate`
structural hint is emitted only under `--include-mapping-hints`.

### Rationale

An earlier proposal **reclassified** address columns into `custom_columns`. A
rubber-duck review rejected it: that would (a) create false `--strict` blockers
because reclassified columns enter the #164 triage queue, (b) distort
reference-rollup matched/custom counts, and (c) break the byte-identical
default-output contract (a scenario fixture legitimately maps a `Country`
column). Flagging-not-reclassifying makes #167 and #168 one consistent
mechanism, keeps the gate non-blocking, and preserves the additive contract.
Strong-evidence address detection and the numeric-identifier carve-out
(`ClientID` int → `partyIdentifier` is **not** flagged) keep false positives low.

### Consequences

- Existing fresh alignment files carry no flags until regenerated
  (`--force` / a changed affinity set), consistent with the freshness model.
- `review`/`review_reason`/`address_candidate` are YAML fields, not `kairos-ext:`
  annotations — no `kairos-ext.ttl` change.
- Deferred to #166: offering the shared `reference-data#Address` class as a real
  candidate so flagged address columns can be mapped via `Party → hasAddress`.

---

## DD-070: Cross-module candidate properties in propose-alignment (issue #166)

**Status:** Accepted  
**Date:** 2026-06-14  
**Affects:** `src/kairos_ontology/propose_alignment.py`,
`src/kairos_ontology/analyse_sources.py`, `src/kairos_ontology/cli/main.py`,
`.github/skills/kairos-design-mapping/SKILL.md` (+ scaffold copy)  
**Implementation:** `--cross-module` / `--accelerator` on `propose-alignment`;
two-pool prompt + `ref_class_id` + `cross_module_matches` in
`run_propose_alignment`; `load_accelerator_uri_modules` in `analyse_sources.py`.

### Context

`propose-alignment` scoped the candidate reference-model pool to the **home
domain's** `domain_uris` only. A column whose true match lives in a sibling /
shared accelerator module — e.g. an `Address` class in `reference-data`,
`PaymentTerms` in `financial`, a shared `currency` property — could not be
matched and was **force-fit** onto an unrelated home-domain scalar
(`SHIPPER_STREET → partyName`). DD-069 (#167/#168) added deterministic review
flags that *detect* these implausible maps, but the column was still force-fit
because the correct class was not in the candidate pool. #166 is the fix: widen
the pool so cross-module properties can be matched, and tag each match with its
owning module.

### Decision

Opt-in, accelerator-scoped, **two-pool** design behind a new `--cross-module`
flag (default OFF, so default output is byte-identical):

1. **Scope source — require `--accelerator`.** The property pool is the UNION of
   the accelerator's data-domain `imports[].uri` (via a new
   `load_accelerator_uri_modules` that preserves the `uri ↔ module` pairing
   `load_data_domains` loses). No silent affinity-union fallback — table-less
   shared modules (the Address case) are invisible to affinity reports, so
   `--cross-module` without a resolvable accelerator errors with guidance.
2. **Two separate candidate pools.** `table_ref_classes` = home domain only →
   STEP 1 (table→class); `property_ref_classes` = widened accelerator pool →
   STEP 2 (column→property). The LLM must classify the *table* only from home
   candidates while a *column* may match a property on any pooled class. The
   property shortlist adds the top cross-module classes scored by column-token
   overlap (bounded; the unbounded full-inventory retry is disabled in
   cross-module mode as a cost guard).
3. **Stable class identity.** Each class records `source_uri`, `module`, and a
   stable `ref_class_id` (`<module>:<Class>`); dedup is keyed on `uri#name`, not
   bare name, so same-named classes across modules stay distinct.
4. **Additive, module-first output.** A matched non-home class adds `ref_module`
   (+ `ref_module_uri`, `belongs_to_domain(s)`) to its column — emitted only when
   set. The home `reference_rollup` is untouched; cross-module matches go in a
   separate `cross_module_matches` section keyed by module/class.
5. **Params-aware freshness.** `alignment_params_sha256` (covering
   cross_module/accelerator/pool signature) is persisted; the domain-level skip
   requires **both** the affinity hash and the params hash to match, and the
   per-table cache key is extended so cross-module results never collide with
   home-only ones.

### Rationale

A rubber-duck review rejected a single shared candidate list (the LLM would
classify the *table* as `Address`/`PaymentTerms`), a default-on behaviour change
(breaks the byte-identical contract and scenario fixtures), and an affinity-union
fallback (misses table-less shared modules — the exact Address case). The two-pool
+ require-accelerator + stable-`ref_class_id` design fixes the force-fit without
distorting coverage or changing default output. Imports are limited to the
explicitly-listed accelerator URIs (no `owl:imports` following → no FIBO blowup).

### Consequences

- `ref_module` / `cross_module_matches` / `alignment_params_sha256` are
  alignment-YAML fields, not `kairos-ext:` annotations — no `kairos-ext.ttl`
  change.
- Cross-module runs cost more (wider prompts) but are bounded by the shortlist
  caps and the disabled retry.
- `alignment_coverage.py` reads only known keys via `.get()`, so it tolerates the
  new fields unchanged.

---

## DD-071: File-management hygiene: session-log archival + non-authoritative glossary

**Status:** Accepted  
**Date:** 2026-06-14  
**Affects:** `src/kairos_ontology/glossary_builder.py`, design-skill SKILL.md
files (`kairos-design-{domain,discovery,mapping,silver,gold,source}`,
`kairos-diagnose-status`) + scaffold copies  
**Implementation:** `_NON_AUTHORITATIVE_NOTE` stamp in `build_glossary_graph`;
`.sessions-design/_archive/` convention documented in the design skills.

### Context

Two independent housekeeping issues shipped alongside #166. (H1) The design
skills already offered "Start fresh (previous archived)" but **no archive folder
or move mechanism was defined** — a fresh start could leave or overwrite the old
log. (H2) The business-discovery glossary (`{company}-glossary.ttl`, DD-063) is
**initial inspiration only** — it is not updated during modeling and its
`seeAlso`/`relatedMatch` links may go stale by design — but nothing in the
artifact said so, risking future sessions treating it as a binding source to
reconcile.

### Decision

- **H1.** Define `ontology-hub/.sessions-design/_archive/`. When a user picks
  "Start fresh" in any design skill that keeps `.sessions-design/*.md` logs,
  **move** the existing log there (preserving the filename, optionally
  timestamp-suffixed) before creating the new one — never silently delete.
  `kairos-diagnose-status` ignores `_archive/` when locating the most recent
  session log.- **H2.** Stamp every generated glossary `skos:ConceptScheme` with a constant
  `rdfs:comment` **and** `skos:editorialNote` disclaimer
  (`_NON_AUTHORITATIVE_NOTE`) stating the glossary is non-authoritative
  inspiration whose links are not reconciled during modeling. Document the status
  in `kairos-design-discovery` (owner) and reference it from
  `kairos-design-domain`.

### Rationale

Both are low-risk, additive conventions that prevent data loss (H1) and
prevent a generated inspiration artifact from being mistaken for a maintained
mapping (H2). The glossary disclaimer is constant text emitted for every build,
so it needs no configuration.

### Consequences

- H1 is primarily a documented skill convention (no enforced CLI move); the
  archive folder is git-ignorable like the rest of `.sessions-design/`.
- H2 adds two triples to every glossary; a `test_glossary_builder.py` assertion
  guards their presence.

### Amendment (3.21.0) — automated projection-log archival

The H1 convention is now **enforced in code for projection session logs**. When a
projection run writes new per-domain logs into `.sessions-projection/`
(`projection-{domain}-*.md` and `dbt-{domain}-*.md`), any pre-existing logs for
the in-scope domains are first **moved** into `.sessions-projection/_archive/`
(collision-safe `-{n}` suffix; never deleted) by
`_archive_prior_projection_logs()` in `projector.py`, called from
`_run_projection`. This mirrors the design-session `_archive/` convention but
removes the manual step for projection logs. `kairos-diagnose-status` ignores the
`_archive/` subfolder for `.sessions-projection` as well.

---

## DD-072: Provenance comment header on toolkit-generated TTL

**Status:** Accepted  
**Date:** 2026-06-14  
**Affects:** `src/kairos_ontology/_provenance.py` (new),
`src/kairos_ontology/import_source.py`, `src/kairos_ontology/glossary_builder.py`,
`src/kairos_ontology/cli/main.py` (`init` / `new-repo` scaffold writers),
`kairos-design-domain` + `kairos-setup-config` SKILL.md (+ scaffold copies)  
**Implementation:** `provenance_comment()` / `prepend_provenance()` /
`strip_provenance()` in `_provenance.py`; call sites in the generators above.

### Context

When the toolkit deterministically writes a `.ttl` artifact (source vocabulary,
SKOS glossary, scaffold starter ontologies) the file carried no trace of *what
produced it* — no toolkit version, no generation date, no generator name. That
makes it hard to tell a hand-edited file from a regenerated one, or to know which
toolkit version emitted a given artifact when debugging.

### Decision

Add a shared `_provenance` helper that emits a small **Turtle comment header**
(lines starting with `#`) stamping the toolkit version, a UTC generation
timestamp, the generator name and a short edit-policy note. Prepend it to:

- **Generated TTL** (`Do not edit — regenerate`): source vocabulary
  (`generate_vocabulary_ttl`, `generate_vocabulary_per_table`,
  `merge_with_existing`) and the SKOS glossary (`write_glossary_graph`).
- **Scaffold TTL** (`safe to edit`): `_master.ttl` and per-domain `{domain}.ttl`
  written by `init` / `new-repo`.

The header is **plain comments only** — it adds no RDF triples, so `rdflib`
ignores it on re-parse and it cannot affect SHACL validation, merge, or
projection. `prepend_provenance` is idempotent (it strips a prior toolkit header
before stamping a fresh one), so regenerating never stacks headers. The same
helper is exposed for the design skills to stamp hand-authored ontology/SHACL
files; the convention is documented in `kairos-design-domain` and
`kairos-setup-config`.

### Rationale

Comments over RDF triples keeps the change zero-risk for every downstream reader
(validate/projections read triples only). A single shared helper avoids drift
across generators and gives skills one reusable entry point.

### Consequences

- The timestamp makes a regenerated file differ on every run (git-diff churn even
  when the triples are unchanged). Accepted as the cost of recording generation
  time; the idempotent prepend keeps it to a single header. If churn becomes a
  problem we can switch to date-only or make the timestamp opt-out.
- No projection logic or extension annotation changed, so no scenario-test
  updates were required; graph-based tests are unaffected (comments ignored on
  parse). New/extended unit tests live in `test_provenance.py`,
  `test_import_source.py`, `test_glossary_builder.py`, and `test_init.py`.

---

## DD-073: Transitive discriminator folding + silverExclude (issue #172)

**Status:** Accepted  
**Date:** 2026-06-14  
**Affects:** `src/kairos_ontology/projections/medallion_silver_projector.py`,
`src/kairos_ontology/scaffold/kairos-ext.ttl`,
`kairos-design-silver` SKILL.md (+ scaffold copy)  
**Implementation:** `_nearest_claimed_ancestor()` (new), URI-keyed `folded_subtypes`,
bounded-ancestor merge in the S3 post-pass, `silverExclude` filter +
`_warn_silver_exclude_dependents()`.

### Context

Two related gaps in the silver projector:

- **B (bug).** S3 discriminator folding inspected only the **direct**
  `rdfs:subClassOf` parent. A subtype reaching a claimed discriminator ancestor
  only through **unclaimed** intermediates (e.g.
  `VesselCarrier → ShipOperator(unclaimed) → Organization(discriminator)`) was not
  folded and got its own near-empty ROOT table.
- **A.** Silver had no way to keep a class in the ontology (for inheritance /
  semantics) while suppressing its physical table — gold already had `goldExclude`.

### Decision

**B — transitive fold.** `_nearest_claimed_ancestor()` walks `rdfs:subClassOf`
breadth-first, traversing **only unclaimed** intermediates, and returns the
**first claimed ancestor**. The pre-scan classifies a class by that ancestor's
strategy (`discriminator` → fold; else → TPC). The S3 post-pass now merges the
subtype's own properties **plus those of the unclaimed intermediates up to the
claimed fold target** (achieved by passing `class_uris` to `_add_data_properties`
and `inherit_ancestors=True` to `_add_object_property_fk_cols`, since
`_get_class_and_ancestors` already stops at claimed ancestors). `folded_subtypes`
is URI-keyed (not name-keyed) for namespace safety. Traversal is deterministic
(sorted URIs); conflicting strategies among same-depth claimed ancestors emit a
warning and pick the lexicographically smallest URI. **Depth-1 single-inheritance
behaviour is byte-identical.**

**A — `silverExclude`.** A new `kairos-ext:silverExclude` boolean annotation
filters classes out of `domain_classes` (mirroring gold's `goldExclude`). It
**overrides** `silverInclude` / `silverIncludeImports`. An excluded class behaves
like an unclaimed / cross-domain FK target; descendants still inherit its
properties. `_warn_silver_exclude_dependents()` warns when a materialised class
subclasses or FK/junctions to an excluded class.

### Rationale

Walking only through unclaimed intermediates and stopping at the first claimed
ancestor contains the blast radius and keeps existing single-level folds
unchanged, while fixing the multi-level case. Reusing `_get_class_and_ancestors`'
existing "stop at claimed" semantics gives the bounded property merge for free.

### Consequences

- **Out of scope (pre-existing, documented):**
  1. A claimed TPC intermediate that is itself folded and still referenced by a
     descendant produces the same inconsistency today via direct-parent logic;
     this change does not worsen it.
  2. `_has_max_cardinality_1(graph, cls_uri, prop)` checks the child, not the
     property's domain ancestor — an inherited FK arising solely from a
     cardinality restriction on an ancestor is still skipped. Independent of #172;
     the common FK signals (`silverForeignKey`, `owl:FunctionalProperty`,
     `silverColumnName`, datatype properties) all fold correctly.
- Scenario coverage added to `tests/scenarios/acme-hub` additively (a separate
  `Organization → ShipOperator → VesselCarrier` chain + a `BaseMarker`/`ActiveMarker`
  exclude case) so existing logistics asserts stay green. Unit tests added to
  `tests/test_silver_projector.py`.

---

## DD-074: Multi-source merge — canonical superset + per-source FK joins (issue #175)

**Status:** Accepted  
**Date:** 2026-06-14  
**Affects:** `src/kairos_ontology/projections/medallion_dbt_projector.py`,
`src/kairos_ontology/templates/dbt/silver_source_model.sql.jinja2`,
`src/kairos_ontology/templates/dbt/silver_union_model.sql.jinja2`  
**Implementation:** `_build_merge_superset()`, `_build_column_type_map()`,
`_merge_pad_type()` (new); rewired multi-source branch of `_gen_silver_models()`.

### Context

The dbt **merge pattern** (≥2 bronze sources → one silver entity via
`UNION ALL`, with per-source staging views) generated invalid/lossy SQL whenever
sources mapped non-identical property sets (the normal master-data case). Three
defects: (1) the union column list was built from the **first source only**, so
other sources' distinct columns vanished; (2) per-source views projected only
their own mapped columns, so the `UNION ALL` branches had **mismatched column
counts/order** (hard SQL error); (3) FK `_sk` columns were **silently dropped**
because `_extract_fk_columns_and_joins` early-returned for any
`len(source_refs) != 1`.

### Decision

Adopt the canonical dbt "staging-per-source + NULL-padded superset + UNION ALL"
pattern:

- **Canonical superset.** `_build_merge_superset()` merges the scoped per-source
  data columns and per-source FK columns into one deterministic order (all data
  columns in source/property order, then all FK columns) and pads each source's
  missing columns with `CAST(NULL AS <type>)`. Types come from
  `_build_column_type_map()` / `_merge_pad_type()` (range-derived
  `_xsd_to_target`, matching the schema YAML; `_label`/FK `_sk` use the portable
  `{{ dbt.type_string() }}` macro).
- **Explicit union branches.** `silver_union_model.sql.jinja2` now selects the
  explicit canonical column list per branch (no `select *`), so the positional
  `UNION ALL` cannot be corrupted by column drift. The union performs no joins.
- **Per-source FK joins.** Each per-source staging view is single-source, so the
  existing single-source FK machinery runs *inside* it:
  `_extract_fk_columns_and_joins` is called per single source. The mapping source
  emits a real `left join {{ ref(target) }}` + `<fk>_sk`; non-mapping sources pad
  `CAST(NULL AS …) as <fk>_sk`. The FK `_sk` then flows through the `UNION ALL` as
  an ordinary canonical column. `silver_source_model.sql.jinja2` gained join
  rendering (aliased `from … as <source_alias>` + `left join` clauses), mirroring
  the single-source `silver_model.sql.jinja2`.
- **NK-coverage warning.** A loud warning fires when a source does not map a
  natural-key column (rows from it would produce NULL/duplicate surrogate keys).

### Rationale

Deterministic, ontology-driven generation (not dbt-utils `union_relations`
physical introspection) preserves governance and reuses the semantic target
contract. Relocating FK joins from the (impossible) union level to the
single-source staging views makes the existing machinery directly applicable and
strictly better than emitting NULL placeholders — FKs are resolved where mapped
and never silently dropped. This reconciles the rubber-duck review and an
external dbt/medallion review, which both converged on superset + typed NULL pads
+ explicit column lists and (the external review) per-source FK evaluation.

### Consequences

- Per-source views may carry NULL-padded columns they don't populate — expected
  and required for `UNION ALL` consistency; the `_source_system` column
  distinguishes provenance.
- Residual type risk: a real direct-mapping cast uses the **bronze** type while a
  NULL pad uses the **range**-derived type; for `UNION ALL` they must be
  compatible. Pads use the range type for schema-YAML consistency — documented
  limitation.
- NK coverage is **warned, not enforced** (consistent with the toolkit's
  warning-tolerant projection flow); fail-fast remains a considered alternative.
- **Future direction (out of scope, follow-up #176):** split `*_union` (conformed
  multi-source stack) from `*_resolved` (survivorship / golden-record / MDM) and
  add richer source-lineage columns (`source_pk`, record hash, `extracted_at`).
- Scenario tests that encoded the buggy behaviour were updated:
  `test_scenario_dbt.py` (`test_crm_source_includes_null_pad_for_unmapped`,
  `TestUnmappedColumnExclusion`, `TestMultiSourceFKPerSource`) and
  `test_scenario_projection.py` (merge superset non-lossy + FK presence). Unit
  tests added: `TestMergeSupersetPadding`, `TestMergeFKPerSource`,
  `TestMergeNKCoverageWarning` in `tests/test_dbt_projector.py`.
- **Regression follow-ups (issues #178, #179).** Two per-source-merge edge cases
  surfaced after DD-074 and were fixed without changing the core design:
  (#178) an **explicit** FK column-mapping declared by one merge source leaked
  into other sources' per-source views (phantom join/columns) — the
  explicit-mapping branch of `_resolve_fk_source_column` is now scoped to the
  current source's columns (None-sentinel scope; physical-column fallback for
  synthetic/composite subjects via `_mapping_belongs_to_source`); (#179) a table
  mapping whose target class is **not projected** (unclaimed import) was silently
  dropped — `_gen_silver_models` now folds such orphans onto a projected
  discriminator parent when present, otherwise emits a loud warning. Unit tests
  `TestMergeExplicitFKMappingScope`, `TestUnprojectedClassMapping` and scenario
  test `TestMergeExplicitFKNoLeak` were added.

---

## DD-075: Sample-grounded mapping evidence (masked example values + transform compatibility)

**Status:** Accepted  
**Date:** 2026-06-14  
**Affects:** `src/kairos_ontology/_samples.py` (new),
`src/kairos_ontology/propose_alignment.py`, `src/kairos_ontology/cli/main.py`,
`src/kairos_ontology/validator.py`, `.github/skills/kairos-design-mapping/SKILL.md`  
**Implementation:** `_samples.py` (`is_pii_column`, `value_is_pii_shaped`,
`mask_value`, `example_values`); `ColumnAlignment.example_values` /
`ColumnAlignment.transform_compat`; `_parses_as()` / `_transform_compat_note()`;
`run_propose_alignment(include_sample_values=True)`; `--no-sample-values` CLI flag.

### Context

Source **sample values** (5 rows captured at import, stored as bronze
`kairos-bronze:sampleValues`) were the strongest available evidence for a
column→property mapping but were never surfaced to the mapper. They were used
only for enum/format enrichment, affinity analysis, and alignment prompts —
never presented as decision evidence during `kairos-design-mapping`, and never
used to sanity-check a proposed `CAST(...)` transform.

### Decision

- **`example_values` is on by default** in `propose-alignment` output (the user
  directive: "too valuable to be opt-in"). The mapping skill's Phase 2 table now
  carries a **mandatory** masked Examples column.
- **PII is always masked.** A shared policy module (`_samples.py`) is the single
  source of truth: a column is PII if its name keyword-matches, its mapped
  property keyword-matches, it is `gdpr_protected`, or its values are PII-shaped
  (email/IBAN/phone/long-digit regex). PII values are masked length-preservingly
  (`jo***@***.com`) and never enumerated. `validator.PII_KEYWORDS` now imports
  from `_samples` to avoid drift.
- **`transform_compat`** is an advisory note (`"N/M sample values are non-numeric
  — CAST may NULL/fail"`) emitted only for numeric/bool CAST targets. It never
  raises confidence, never auto-sets review, and never blocks.
- **No `schema_version` bump.** Both fields are additive and emitted only when
  populated, so existing v2 alignment files and the freshness gate are unaffected.

### Rationale

Real values disambiguate mappings far better than names/types alone and let the
modeler catch encoding traps before writing SQL. Forcing the feature on (vs.
opt-in) maximises that value; masking PII unconditionally keeps the committed
artifacts safe even though raw `sampleValues` are already in version control.
Keeping `transform_compat` advisory respects the toolkit's warning-tolerant,
human-confirmed mapping flow.

### Consequences

- `propose-alignment` output now contains masked example values by default;
  `--no-sample-values` / `include_sample_values=False` suppresses them.
- The Examples column is for transient display only — skills must never copy raw
  values into committed TTL/comments/session logs.
- A first masking layer now exists, but raw bronze `sampleValues` remain
  committed (pre-existing); tightening that is out of scope here.

---

## DD-076: `suggest-shapes` — draft SHACL from source profiling

**Status:** Accepted  
**Date:** 2026-06-14  
**Affects:** `src/kairos_ontology/suggest_shapes.py` (new),
`src/kairos_ontology/cli/main.py`, `.github/skills/kairos-execute-validate/SKILL.md`,
`.github/skills/kairos-help/SKILL.md`  
**Implementation:** `suggest_shapes.build_shapes_graph()` / `suggest_shapes()`;
`suggest-shapes` CLI command; entry in `_SKILL_COVERED_COMMANDS`.

### Context

SHACL shapes were entirely hand-written — there was no generator. Source
profiling metadata (datatype, nullability, `kairos-bronze:distinctCount`,
samples) already encodes most of a basic shape, so the blank-page cost was
avoidable.

### Decision

Add a deterministic `suggest-shapes` command that builds a **DRAFT** SHACL graph
(via rdflib, never string concatenation) from a bronze vocabulary:
- `sh:datatype` always; `sh:pattern` only when one `FORMAT_PATTERNS` entry
  matches all samples; `sh:minCount 1` only from `nullable:false`; `sh:in` only
  when a reliable `distinctCount` ≤ `--enum-distinct-max` fully matches the
  sampled distinct set **and the column is not PII**. No sample-derived
  min/max ranges.
- Output defaults to `output/shapes-draft/<name>.ttl` — **outside**
  `model/shapes/` and with a `.ttl` (not `.shacl.ttl`) suffix — so
  `validator.py`'s recursive `**/*.shacl.ttl` glob does **not** auto-load drafts.
- Refuses to overwrite without `--force`; reuses the DD-075 `_samples` masking
  policy (PII never enumerated, masked in comments).

### Rationale

A reviewed-draft workflow (generate → curate → move into `model/shapes/`) gives
leverage without letting machine guesses silently become enforced constraints.
Writing outside the loaded shapes dir is the safety mechanism that makes
"draft" real. Gating `sh:in`/`sh:minCount` on reliable metadata (not raw
5-row samples) avoids over-constraining.

### Consequences

- New skill-gated CLI command (owned by `kairos-execute-validate`); emits the
  soft skill-gate warning unless `KAIROS_SKILL_CONTEXT=1`.
- Drafts are advisory and require manual promotion into `model/shapes/`; nothing
  is enforced until a human moves and renames the file.
- `kairos-bronze:distinctCount` is the reliability signal for enums; absent it,
  the command emits only an advisory "possible enum (unverified)" comment.

---

## DD-077: Custom-column triage hardening (issue #182)

**Status:** Accepted  
**Date:** 2026-06-14  
**Affects:** `propose-alignment` generation + `check-alignment` gate; custom-column
triage at Checkpoint 3b of `kairos-design-domain`  
**Implementation:** `src/kairos_ontology/propose_alignment.py`,
`src/kairos_ontology/alignment_coverage.py`, `src/kairos_ontology/_cost.py`,
`src/kairos_ontology/ai_provider.py`, `src/kairos_ontology/cli/main.py`

### Context

Real-world modeling of the CLdN `consignment` and `booking` domains (≈200 and ≈350
custom columns) exposed reproducible, deterministic weaknesses in the
`propose-alignment` → Checkpoint-3b workflow:

1. **Confident-but-wrong fallbacks.** The prompt instructed the model to invent a
   camelCase `ref_property` for *every* unmatched column, so dozens of unrelated
   columns collapsed onto one plausible-looking sink (`stageCode`, `customsID`).
2. **No auto-disposition.** ~40% of columns have a mechanical disposition (audit →
   `skip`; generic vendor slots like `CFSTRING33` → `silver-passthrough`) yet all
   started undisposed, forcing a column-by-column manual grind.
3. **Rollup coverage > 100%.** Matched properties weren't validated against the
   class's real property set, so a class could report 121% coverage (23 matched vs
   19 real props) — an AI-hallucination signal presented as healthy.
4. **Hallucinated anchor classes.** A `Booking` class anchoring 14 tables / 236
   custom columns existed in *no* reference model (real DCSA classes are only
   `BookingRequest` / `ConfirmedBooking`); nothing re-validated an already-written
   alignment against the real class set. Building triage on fictional anchors yields
   a Gate-6-violating model.

The issue mandates **no new AI cost** — every fix is deterministic or
confidence-gated, reusing the existing per-table LLM call.

### Decision

Ship a dependency-ordered set of workstreams (rubber-duck-reviewed):

- **WS0** — emit an explicit `algorithm_version`, fold it (plus
  `custom_confidence_floor` and model id) into the per-table and domain cache keys,
  and fix the latent freshness-hash bug (written as `source_sha256`, read as
  `affinity_sha256`), so the hardened behaviour is never masked by stale cache.
- **WS-NORM** — one canonical discriminator (`alignment == "custom"`). An unmatched
  column is `alignment: custom` + `ref_property: null` + `suggested_property: null`;
  no orthogonal `match` field.
- **WS1** — confidence-gate `suggested_property` (`--custom-confidence-floor`,
  default 0.5) and downgrade any catch-all property proposed for ≥3 dissimilar
  columns.
- **WS2** — two-tier disposition: advisory `recommended_disposition` always written;
  final `disposition` auto-filled (`disposition_source: heuristic`) **only** for
  narrow audit/technical columns. Generic vendor slots are *recommended*
  `silver-passthrough` but stay undisposed unless `--accept-heuristics`.
- **WS4** — validate matched props against the real ref-model set, cap coverage at
  100%, and surface a `hallucinated_properties` sample.
- **WS6** — record a non-clean `ref_class_status` + `rejected_ref_class` at
  generation; add a decoupled `check-alignment --check-anchors` gate that
  re-validates anchors against the real installed class set.
- **WS7** — prompt emits `ref_property: null` for unmatched, allows `ref_class:
  null`, and is steered away from catch-all sinks / >100% over-mapping.
- **WS8** — opt-in `--high-accuracy` model preset for the accuracy-sensitive
  anchoring step (mini stays default). Adds **per-role LLM endpoints**: `affinity`
  (analyse-sources) and `alignment` (propose-alignment) can each use their own
  endpoint/key/model via `KAIROS_AI_{ROLE}_ENDPOINT|KEY|MODEL`, falling back to the
  global provider when unset.
- **WS9** — preserve human-owned dispositions/notes by `(system, table, column)` on
  regeneration; only heuristic-owned fields are recomputed, so `--force` never wipes
  a hand-triaged file.

### Rationale

- A wrong specific guess is worse than a null — it must be individually disproved,
  so low-confidence and catch-all suggestions are dropped rather than emitted.
- Two-tier disposition prevents silently auto-modeling/-skipping real business
  columns: only near-zero-ambiguity audit columns auto-resolve.
- Keeping hallucination signals **visible** (rollup samples, anchor status) rather
  than silently clamping lets the modeler see and correct AI errors.
- Deterministic post-hoc anchor validation is decoupled from the CLI (core takes a
  `valid_ref_classes` set) to avoid a `cli → core` import cycle.

### Consequences

- Alignment YAMLs gain `algorithm_version`; files from an older version are flagged
  stale/unverifiable by `check-alignment`.
- `check-alignment` gains `--check-anchors` (anchor validation) and
  `--accept-heuristics` (treat recommended vendor-slot passthrough as disposed);
  `--strict` keeps meaning only custom-column disposition strictness.
- Cross-domain candidate tagging (WS3) and a non-LLM repair path for existing large
  YAMLs were scoped here but **deferred to follow-up issues** to avoid introducing a
  new class of wrong-domain noise and to keep this change focused.

---

## DD-078: User-facing extras packaging + Foundry token-credential fallback

**Status:** Accepted  
**Date:** 2026-06-14  
**Affects:** `pyproject.toml`, `src/kairos_ontology/ai_provider.py`, scaffold `.env.example` copies  
**Implementation:** `pyproject.toml` (`[project.optional-dependencies]` + `[dependency-groups]`), `ai_provider.py::_create_foundry_client`, `tests/test_packaging_extras.py`, `tests/test_ai_provider.py`

### Context

Two related defects broke the Microsoft Foundry AI provider path used by
`analyse-sources` / `propose-alignment`:

1. **Extras installed nothing.** The four user-facing extras (`azure`, `foundry`,
   `flatfile`, `parquet`) were declared **only** under `[dependency-groups]`
   (PEP 735). The documented `pip install kairos-ontology-toolkit[<extra>]`
   resolves `[project.optional-dependencies]`, and dependency-groups are not
   written into wheel metadata — so the install silently resolved nothing and
   `azure` was never importable.

2. **API-key auth crashed the Foundry path.** `_create_foundry_client` wrapped
   `AZURE_FOUNDRY_API_KEY` in `AzureKeyCredential` and passed it to
   `AIProjectClient`. In azure-ai-projects 2.x, `get_openai_client()` mints an AAD
   token via `credential.get_token(...)`; `AzureKeyCredential` has no `get_token`,
   raising `'AzureKeyCredential' object has no attribute 'get_token'`. Every table
   failed and fell back to `mdm`/0.00, producing garbage analysis output.

### Decision

- **Dual-declare** the four user-facing extras in **both**
  `[project.optional-dependencies]` (so the wheel `[extra]` install works) and
  `[dependency-groups]` (for `uv sync --group`). A parity test
  (`tests/test_packaging_extras.py`) prevents drift; `dev` stays group-only.
- **Foundry credential fallback.** Prefer a real `TokenCredential`
  (`DefaultAzureCredential`). When `AZURE_FOUNDRY_API_KEY` is set, attempt
  `AzureKeyCredential` but catch the `AttributeError` from the SDK's token path and
  **fall back to `DefaultAzureCredential`**, with a clear `EnvironmentError` when
  neither credential is usable.

### Rationale

Key auth is fundamentally incompatible with the Foundry SDK's
`get_openai_client()`, so silently requiring a token (or erroring usefully) is
correct. Keeping both extra declarations avoids breaking either pip or uv
workflows. Defensive try/fallback keeps behavior correct across SDK versions.

### Consequences

- `pip install kairos-ontology-toolkit[foundry]` now pulls `azure-ai-projects` +
  `azure-identity`.
- Foundry users authenticate via `az login` / managed identity; a set API key no
  longer breaks the run (it falls back to token auth).
- Extras must be edited in two places — guarded by the parity test.

---

## DD-079: dbt cross-table warning conflates inherited vs own properties (issue #181)

**Status:** Accepted  
**Date:** 2026-06-15  
**Affects:** `src/kairos_ontology/projections/medallion_dbt_projector.py`  
**Implementation:** `_gen_silver_models` (cross-table classification), `write_dbt_session_log` (`## ℹ️ Info` section), `tests/scenarios/test_scenario_dbt.py::TestCrossTableWarnings`

### Context

When a subtype is claimed as its own silver table (`Child ⊂ Parent`, single
source `tblChild`), `_gen_silver_models` scopes the model's columns to the
subtype's primary table — inherited parent attributes that live on the parent's
table are deliberately excluded (resolving them would require a JOIN). The
cross-table detector, however, flagged **every** mapped property whose domain was
the class **or any ancestor** when its column was not in the primary table. As a
result, each excluded-by-design inherited property emitted a
`Cross-table reference … may need a JOIN` ⚠️ warning — 40+ noise warnings per
subtype — drowning out genuinely actionable own-class cross-table mappings.

### Decision

Classify each cross-table mapped property by its **direct** `rdfs:domain`:

- **own** — direct domains include the class URI → keep the per-column ⚠️ warning
  (a genuine JOIN candidate). Own-precedence: a property declared on the class
  stays a warning even if it is also declared on an ancestor.
- **inherited** — direct domains intersect only ancestors → reclassify
  warning → **info** and collapse all inherited props into **one** consolidated
  ℹ️ note per class, surfaced under a new `## ℹ️ Info` section of the dbt session
  log (and threaded via `entity_metadata["info_notes"]`, so no
  `_gen_silver_models` return-signature change).

RDF permits multiple `rdfs:domain` values, so domains are read with
`graph.objects(prop, RDFS.domain)` and filtered to `URIRef` (blank-node /
`owl:unionOf` domain expressions are ignored, as before). The `## ✅ No issues`
banner now also requires no info notes.

### Rationale

The inherited columns were already excluded on purpose; warning about them is
misleading and noisy. Surfacing a single consolidated, clearly-informational note
preserves discoverability (the user can still choose to enrich the subtype via a
JOIN) without polluting the actionable warning channel or the report's warning
counts.

### Consequences

- WARNING-log volume and projection-report warning counts drop sharply for
  subtype-as-own-table models.
- A new `## ℹ️ Info` session-log section appears when inherited cross-table props
  are detected.
- `_get_class_and_parents` still follows a single `subClassOf` chain (pre-existing
  limitation, shared with column extraction so classification stays consistent
  with what was actually excluded) — multiple inheritance is out of scope here.

---

## DD-080: Evidence-Led Accelerator-First Modeling (consolidates DD-EL-1..10)

**Status:** Accepted  
**Date:** 2026-06-16  
**Affects:** Claim Registry (`model/claims/{domain}-claims.yaml`), `claim_coverage.py` / `check-claims`, `derive-claims`, claim-driven `owl:imports` + `silverInclude`, silver/dbt/powerbi projectors, `pbi-source-fit-gap`, `source-delta-report` + contract version, evidence-led design skills + `kairos-help` §11  
**Implementation:** Slices 0A–8. Canonical methodology: `docs/methodology/accelerator-first-modeling.md`. Per-slice rationale: `docs/implementation/evidence-led-modeling/decision-log.md` (DD-EL-1..10)

### Context

The evidence-led, accelerator-first methodology was implemented as a series of
vertical slices, each with its own `DD-EL-N` decision recorded on the feature
track in `docs/implementation/evidence-led-modeling/decision-log.md`. This entry
consolidates those decisions into the canonical design log at merge, as required
by the index-keeping rules above. It is a **roll-up + cross-reference** entry; the
detailed context/rationale for each sub-decision remains in the decision log.

### Decision

Adopt the evidence-led, accelerator-first modeling methodology as canonical
(`docs/methodology/accelerator-first-modeling.md`), comprising:

- **DD-EL-1** — the **Claim Registry** (`model/claims/{domain}-claims.yaml`)
  replaces alignment YAML as the single governed source of truth (no dual path).
- **DD-EL-2** — **A1:** `owl:imports` are generated deterministically from approved
  claims; the import-all/no-bypass concept (C2) is deferred pending a real
  large-closure perf/FK spike.
- **DD-EL-3 / DD-EL-4** — **A2-lite:** three coherent, generated-and-reviewable
  authored surfaces (thin ontology, extensions, registry); claims drive
  `owl:imports` + `silverInclude`; projection is gated on claim↔projection sync.
- **DD-EL-5** — **`derive-claims`** deterministically aggregates multi-source
  evidence into candidate claims.
- **DD-EL-6** — MDM/reference-data rules + ownership hardening live in
  **`check-claims`**; discovery captures master-data anchors early.
- **DD-EL-7** — Power BI/source fit-gap is treated as **evidence, not authority**.
- **DD-EL-8** — change management: the advisory **`source-delta-report`** + an
  optional registry **contract version** enforce "expand silver, never silently
  mutate".
- **DD-EL-9** — thin-chat **skill interaction modes** + decision-packet convention
  (`kairos-help` §11), presentation-only (C10 guard).
- **DD-EL-10** — methodology promotion + consolidation of all slice work into a
  single **`4.0.0-rc1`** release candidate; everything kept in-repo (no cross-repo
  issues/PRs filed).

### Rationale

A single consolidated DD with a cross-reference table keeps the canonical log
navigable without duplicating the ~650 lines of per-slice rationale already
written and tested on the feature track. The methodology doc is the prose entry
point; this DD is the design-log anchor.

### Consequences

- Future changes to any sub-decision update **both** the `DD-EL-N` entry (history)
  and, if the architectural choice itself changes, this DD-080 roll-up.
- The methodology is canonical for downstream hubs; rollout there proceeds in
  per-domain batches (methodology §11).
- Upstream follow-ups (skill Gate-6 relaxation, scaffold foundation template,
  routing updates) are tracked in methodology §12, not yet filed.

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
