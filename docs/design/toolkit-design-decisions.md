# Toolkit Design Decisions

This document is the **index** of architectural and design decisions for the Kairos
Ontology Toolkit. Each decision is an Architecture Decision Record (ADR) in its own file
under [`decisions/`](decisions/), carrying context, rationale, and current status.

> **Maintenance rule:** add a decision file and an index row in every PR that introduces
> or modifies a design decision. See `.github/copilot-instructions.md` for the PR
> checklist.

## How to Keep This Log Organised

### Adding a new decision

1. **Assign the next sequential DD number** — check the last row of the Index below.
2. **Create the decision file** from [`decisions/TEMPLATE.md`](decisions/TEMPLATE.md). It
   holds exactly one `# DD-NNN: Title` heading. The filename is that whole heading
   lowercased, with every character other than a letter, digit, underscore, space or
   hyphen removed and spaces replaced by hyphens — the same slug GitHub would generate as
   an anchor. If the result would exceed 100 characters, truncate it at a hyphen.
3. **Add a row to the Index table**, in numeric order, linking to the new file. The row's
   title, status and date must match the file exactly;
   `tests/test_design_decisions_consistency.py` enforces this and will fail the build
   otherwise.

Because each decision is its own file, two branches adding a decision conflict only on
adjacent index rows — never on the decision text itself.

### Keeping the Index in sync

The Index table **must** correspond one-for-one with the files in `decisions/`:
- Same DD number, same title, same status, same date.
- Links are relative paths (`decisions/dd-nnn-....md`), never in-page `#anchor` fragments.
- When a status changes (e.g. Proposed → Accepted), update **both** the Index row and the
  `**Status:**` line in the decision file.

### Superseding a decision

- Set the old decision's status to `~~Superseded by [DD-XXX](dd-xxx-slug.md)~~` — a
  sibling path, because both files live in `decisions/` — and mirror it in the Index row.
- Keep the old file. Do not delete it; it is the historical record.
- The new decision should name what it supersedes in its Context section.

### Companion specifications

A decision needing a longer architectural specification gets a companion document one
level up, in `docs/design/`, named:
```
dd-NNN-descriptive-slug.md
```
Reference it from the decision's `Implementation:` field. Companion specs are a different
artifact from the entries in `decisions/` and are not indexed below. Files in
`docs/design/` without a `dd-NNN-` prefix are considered orphaned and may be removed
during cleanup.

---

## Index

> **Current architecture:** start with DD-133. DD-135 and DD-136 record the completed v4
> operational retirement. Earlier accepted entries remain historical records unless a later
> decision explicitly supersedes them; they are not an alternate active authoring path.

| ID | Title | Status | Date |
|----|-------|--------|------|
| [DD-001](decisions/dd-001-gold-layer-inheritance--class-per-table.md) | Gold Layer Inheritance — Class-Per-Table | Proposed | 2026-04-25 |
| [DD-002](decisions/dd-002-dbt-sql-dialect--platform-specific-generation.md) | dbt SQL Dialect — Platform-Specific Generation | Accepted | 2026-04-30 |
| [DD-003](decisions/dd-003-staging--platform-specific-silver--portable.md) | Staging = Platform-Specific, Silver = Portable | ~~Superseded by DD-014~~ | 2026-04-30 |
| [DD-004](decisions/dd-004-keep-staging-naming-not-bronze.md) | Keep "staging" Naming (Not "bronze") | ~~Superseded by DD-014~~ | 2026-04-30 |
| [DD-005](decisions/dd-005-silver-references-staging-directly.md) | Silver References Staging Directly | ~~Superseded by DD-014~~ | 2026-04-30 |
| [DD-006](decisions/dd-006-column-level-json-not-table-level-physicalstorage.md) | Column-Level JSON, Not Table-Level physicalStorage | Accepted | 2026-04-30 |
| [DD-007](decisions/dd-007-extend-kairos-ext-namespace.md) | Extend kairos-ext Namespace | Accepted | 2026-04-30 |
| [DD-008](decisions/dd-008-generated-macros-alongside-models.md) | Generated Macros Alongside Models | Accepted | 2026-04-30 |
| [DD-009](decisions/dd-009-fabric-first-default-platform.md) | Fabric-First Default Platform | ~~Superseded by DD-215~~ | 2026-04-30 |
| [DD-010](decisions/dd-010-branch-protection-on-new-repo.md) | Branch Protection on new-repo | Accepted | 2026-04-30 |
| [DD-011](decisions/dd-011-silver-output-inside-dbt-tree.md) | Silver Output Inside dbt Tree | Accepted | 2026-04-28 |
| [DD-012](decisions/dd-012-non-fatal-github-operations.md) | Non-Fatal GitHub Operations | Accepted | 2026-04-30 |
| [DD-013](decisions/dd-013-pre-release-publishing-via-git-tags--channel-system.md) | Pre-Release Publishing via Git Tags + Channel System | Accepted | 2026-05-01 |
| [DD-014](decisions/dd-014-eliminate-staging--silver-reads-bronze-directly.md) | Eliminate Staging — Silver Reads Bronze Directly | ~~Superseded by DD-106~~ | 2026-05-14 |
| [DD-015](decisions/dd-015-vocabulary-ttl-as-bronze-contract.md) | Vocabulary TTL as Bronze Contract | Accepted | 2026-05-14 |
| [DD-016](decisions/dd-016-stale-managed-skill-cleanup-during-update.md) | Stale Managed Skill Cleanup During Update | Accepted | 2026-05-14 |
| [DD-017](decisions/dd-017-dataplatform-integration--two-deliverable-packages--copilot-agent.md) | Dataplatform Integration — Two Deliverable Packages + Copilot Agent | Accepted | 2026-04-30 |
| [DD-018](decisions/dd-018-silver-model-granularity--entity-centric-with-multi-source-split.md) | Silver Model Granularity — Entity-Centric with Multi-Source Split | Accepted | 2026-04-30 |
| [DD-019](decisions/dd-019-cross-domain-fk-resolution-via-surrogate-key-joins.md) | Cross-Domain FK Resolution via Surrogate Key Joins | Accepted | 2026-05-01 |
| [DD-020](decisions/dd-020-stable-ontology-iris--no-version-in-namespace.md) | Stable Ontology IRIs — No Version in Namespace | Accepted | 2026-05-01 |
| [DD-021](decisions/dd-021-extension-as-whitelist-for-imported-class-projection.md) | Extension-as-Whitelist for Imported Class Projection | Proposed | 2026-05-01 |
| [DD-022](decisions/dd-022-simplified-fk-annotations-for-silver-projection.md) | Simplified FK Annotations for Silver Projection | Proposed | 2026-05-01 |
| [DD-023](decisions/dd-023-shared-extension-defaults-for-reference-models.md) | Shared Extension Defaults for Reference Models | Proposed | 2026-05-19 |
| [DD-024](decisions/dd-024-hash-tolerant-catalog-resolution.md) | Hash-Tolerant Catalog Resolution | Accepted | 2026-05-26 |
| [DD-025](decisions/dd-025-scd-type-aware-dbt-silver-models.md) | SCD Type-Aware dbt Silver Models | ~~Superseded by DD-109~~ | 2026-05-26 |
| [DD-026](decisions/dd-026-silver-layer-accuracy--mapped-only-columns-fk-parity-and-scd2-history-preservation.md) | Silver Layer Accuracy — Mapped-Only Columns, FK Parity, and SCD2 History Preservation | Accepted | 2026-05-27 |
| [DD-027](decisions/dd-027-cross-domain-peer-extension-loading-for-fk-resolution.md) | Cross-Domain Peer Extension Loading for FK Resolution | Accepted | 2026-05-27 |
| [DD-028](decisions/dd-028-multi-table-same-source-union-model-disambiguation.md) | Multi-Table Same-Source Union Model Disambiguation | Accepted | 2026-05-27 |
| [DD-029](decisions/dd-029-silver-model-registry-for-gold-ref-resolution.md) | Silver Model Registry for Gold ref() Resolution | Accepted | 2026-05-28 |
| [DD-030](decisions/dd-030-rewriteuri-catalog-resolution-with-extension-fallback.md) | rewriteURI Catalog Resolution with Extension Fallback | Accepted | 2026-05-29 |
| [DD-031](decisions/dd-031-inherit-naturalkey-from-discriminator-parents.md) | Inherit naturalKey from Discriminator Parents | Accepted | 2026-05-29 |
| [DD-032](decisions/dd-032-reference-model-inspired--local-pattern-adoption-from-reference-models.md) | Reference Model Inspired — Local Pattern Adoption from Reference Models | Accepted | 2026-05-30 |
| [DD-033](decisions/dd-033-replace-alignment-files-with-rdfsseealso-on-inspired-classes.md) | Replace Alignment Files with rdfs:seeAlso on Inspired Classes | Accepted | 2026-05-30 |
| [DD-034](decisions/dd-034-extension-vocabulary-is-the-single-source-of-truth-defer-identitystrategy.md) | Extension Vocabulary is the Single Source of Truth; Defer `identityStrategy` | Accepted | 2026-05-30 |
| [DD-035](decisions/dd-035-silver-s3-inheritance-gate--respect-inheritancestrategy-annotation.md) | Silver S3 Inheritance Gate — Respect `inheritanceStrategy` Annotation | Accepted | 2026-05-30 |
| [DD-036](decisions/dd-036-drop-git-submodules-for-reference-models.md) | Drop Git Submodules for Reference Models | Accepted | 2026-05-31 |
| [DD-037](decisions/dd-037-uv-as-standard-environment-manager-for-hub-repos.md) | uv as Standard Environment Manager for Hub Repos | Accepted | 2026-05-31 |
| [DD-038](decisions/dd-038-bronze-source-introspection--layered-dbt-architecture.md) | Bronze Source Introspection & Layered dbt Architecture | Proposed | 2026-06-01 |
| [DD-039](decisions/dd-039-enhanced-schema-extraction-with-json-flattening--bronze-expanded-layer.md) | Enhanced Schema Extraction with JSON Flattening & Bronze Expanded Layer | ~~Superseded by DD-106~~ | 2026-06-02 |
| [DD-040](decisions/dd-040-skill-lifecycle-architecture--design--execute-separation.md) | Skill Lifecycle Architecture — Design / Execute Separation | Accepted | 2026-05-30 |
| [DD-041](decisions/dd-041-llm-powered-source-affinity-analysis--coverage-reporting.md) | LLM-powered Source Affinity Analysis & Coverage Reporting | Accepted | 2026-06-04 |
| [DD-042](decisions/dd-042-table-centric-source-classification-with-module-class-grounding.md) | Table-centric source classification with module-class grounding | Accepted | 2026-06-05 |
| [DD-043](decisions/dd-043-propose-alignment--pre-modeling-column-to-property-matching.md) | Propose-alignment — pre-modeling column-to-property matching | Accepted | 2026-06-05 |
| [DD-044](decisions/dd-044-reference-model-specialization-discovery--materialized-inventories.md) | Reference Model Specialization Discovery & Materialized Inventories | Proposed | 2026-06-12 |
| [DD-045](decisions/dd-045-mapping-hints-for-propose-alignment.md) | Mapping Hints for propose-alignment | Accepted | 2026-06-13 |
| [DD-046](decisions/dd-046-reference-model-specialization-visibility-in-domain-modeling.md) | Reference Model Specialization Visibility in Domain Modeling | Accepted | 2026-06-13 |
| [DD-047](decisions/dd-047-deterministic-inventory-freshness-pre-flight-gate.md) | Deterministic Inventory Freshness Pre-flight Gate | Accepted | 2026-06-13 |
| [DD-048](decisions/dd-048-business-discovery-phase--company-skos-glossary.md) | Business Discovery Phase & Company SKOS Glossary | Accepted | 2026-06-13 |
| [DD-049](decisions/dd-049-self-upgrade-re-exec--running-vs-pinned-version-guard.md) | Self-Upgrade Re-exec & Running-vs-Pinned Version Guard | Accepted | 2026-06-13 |
| [DD-050](decisions/dd-050-parquet-source-import.md) | Parquet Source Import | Accepted | 2026-06-13 |
| [DD-051](decisions/dd-051-start-modeling-routes-to-lifecycle-start--restart-pre-flight.md) | Start-Modeling Routes to Lifecycle Start & Restart Pre-flight | Accepted | 2026-06-13 |
| [DD-052](decisions/dd-052-import-commands-auto-write-an-import-results-session-file.md) | Import Commands Auto-Write an Import-Results Session File | Accepted | 2026-06-13 |
| [DD-053](decisions/dd-053-cli-soft-skill-gate.md) | CLI Soft Skill-Gate | Accepted | 2026-06-13 |
| [DD-054](decisions/dd-054-reference-model-inventories-namespaced-by-owning-model.md) | Reference-Model Inventories Namespaced by Owning Model | Accepted | 2026-06-13 |
| [DD-055](decisions/dd-055-business-discovery-materializes-reference-model-breadth--links-glossary-to-ref-model-iris.md) | Business Discovery Materializes Reference-Model Breadth & Links Glossary to Ref-Model IRIs | Accepted | 2026-06-13 |
| [DD-056](decisions/dd-056-relocate-glossary--inventory-folders-to-hub-root-new-hubs-only.md) | Relocate Glossary & Inventory Folders to Hub Root (New Hubs Only) | Accepted | 2026-06-13 |
| [DD-057](decisions/dd-057-windows-update---upgrade-uses-a-detached-self-healing-managed-file-refresh.md) | Windows `update --upgrade` Uses a Detached Self-Healing Managed-File Refresh | Accepted | 2026-06-13 |
| [DD-058](decisions/dd-058-modeling-pre-flight-gates-on-source-analysis-unpack-reference-models-before-analyse.md) | Modeling Pre-Flight Gates on Source Analysis; Unpack Reference Models Before `analyse-sources` | Accepted | 2026-06-13 |
| [DD-059](decisions/dd-059-modeling-pre-flight-adds-a-discovery-completeness-gate-independent-of-source-state.md) | Modeling Pre-Flight Adds a Discovery-Completeness Gate (Independent of Source State) | Accepted | 2026-06-13 |
| [DD-060](decisions/dd-060-per-document-extraction-tracking-for-business-discovery.md) | Per-Document Extraction Tracking for Business Discovery | Accepted | 2026-06-13 |
| [DD-061](decisions/dd-061-deterministic-source-coverage-gates-check-alignment--check-source-coverage.md) | Deterministic Source-Coverage Gates (check-alignment + check-source-coverage) | Superseded by DD-094 | 2026-06-13 |
| [DD-062](decisions/dd-062-update-resolves-an-upward-walked-managed-root-no-silent-split-hub.md) | `update` Resolves an Upward-Walked Managed Root (No Silent Split-Hub) | Accepted | 2026-06-13 |
| [DD-063](decisions/dd-063-deterministic-skos-glossary-builder-build-glossary.md) | Deterministic SKOS Glossary Builder (`build-glossary`) | Accepted | 2026-06-13 |
| [DD-064](decisions/dd-064-validate--project-resolve-paths-from-the-hub-root-not-cwd.md) | `validate` / `project` Resolve Paths From the Hub Root (Not CWD) | Accepted | 2026-06-13 |
| [DD-065](decisions/dd-065-concurrent-cached-ai-pre-modeling-analyse-sources--propose-alignment.md) | Concurrent, Cached AI Pre-Modeling (`analyse-sources` + `propose-alignment`) | Accepted | 2026-06-14 |
| [DD-066](decisions/dd-066-no-pypi-publishing--git-tag--wheel-url-distribution.md) | No PyPI Publishing — Git-Tag + Wheel-URL Distribution | Accepted | 2026-06-14 |
| [DD-067](decisions/dd-067-single-line-release-management-with-ephemeral-hotfix-branches.md) | Single-Line Release Management with Ephemeral Hotfix Branches | Accepted | 2026-06-14 |
| [DD-068](decisions/dd-068-custom-column-triage-in-domain-modeling-issue-164.md) | Custom-column triage in domain modeling (issue #164) | Accepted | 2026-06-14 |
| [DD-069](decisions/dd-069-propose-alignment-plausibility--address-review-flags-issues-167168.md) | propose-alignment plausibility & address review flags (issues #167/#168) | Accepted | 2026-06-14 |
| [DD-070](decisions/dd-070-cross-module-candidate-properties-in-propose-alignment-issue-166.md) | Cross-module candidate properties in propose-alignment (issue #166) | Accepted | 2026-06-14 |
| [DD-071](decisions/dd-071-file-management-hygiene-session-log-archival--non-authoritative-glossary.md) | File-management hygiene: session-log archival + non-authoritative glossary | Accepted | 2026-06-14 |
| [DD-072](decisions/dd-072-provenance-comment-header-on-toolkit-generated-ttl.md) | Provenance comment header on toolkit-generated TTL | Accepted | 2026-06-14 |
| [DD-073](decisions/dd-073-transitive-discriminator-folding--silverexclude-issue-172.md) | Transitive discriminator folding + silverExclude (issue #172) | Accepted | 2026-06-14 |
| [DD-074](decisions/dd-074-multi-source-merge--canonical-superset--per-source-fk-joins-issue-175.md) | Multi-source merge — canonical superset + per-source FK joins (issue #175) | Accepted | 2026-06-14 |
| [DD-075](decisions/dd-075-sample-grounded-mapping-evidence-masked-example-values--transform-compatibility.md) | Sample-grounded mapping evidence (masked example values + transform compatibility) | Accepted | 2026-06-14 |
| [DD-076](decisions/dd-076-suggest-shapes--draft-shacl-from-source-profiling.md) | `suggest-shapes` — draft SHACL from source profiling | Accepted | 2026-06-14 |
| [DD-077](decisions/dd-077-custom-column-triage-hardening-issue-182.md) | Custom-column triage hardening (issue #182) | Accepted | 2026-06-14 |
| [DD-078](decisions/dd-078-user-facing-extras-packaging--foundry-token-credential-fallback.md) | User-facing extras packaging + Foundry token-credential fallback | Accepted | 2026-06-14 |
| [DD-079](decisions/dd-079-dbt-cross-table-warning-conflates-inherited-vs-own-properties-issue-181.md) | dbt cross-table warning conflates inherited vs own properties (issue #181) | Accepted | 2026-06-15 |
| [DD-080](decisions/dd-080-two-layer-lifecycle-state-deterministic-status-cli-and-the-kairos-flow-single-entry-point.md) | Two-layer lifecycle state, deterministic `status` CLI, and the `kairos-flow` single entry point | Accepted | 2026-06-20 |
| [DD-081](decisions/dd-081-analyse-sources---domains-is-an-output-filter-not-a-candidate-restriction.md) | `analyse-sources --domains` is an output filter, not a candidate restriction | Accepted | 2026-06-20 |
| [DD-082](decisions/dd-082-claim-curation-ergonomics-decide-claims-uri-back-fill-skeleton-bootstrap-intra-hub.md) | Claim-curation ergonomics: `decide-claims`, URI back-fill, skeleton bootstrap, intra-hub imports (issue #190) | Accepted | 2026-06-20 |
| [DD-083](decisions/dd-083-claims-to-silver-ext-preserves-authored-ttl-via-a-managed-block-issue-191.md) | `claims-to-silver-ext` preserves authored TTL via a managed block (issue #191) | Accepted | 2026-06-20 |
| [DD-084](decisions/dd-084-deterministic-address-relationship-candidates-surfaced-as-advisory-metadata-issue-192.md) | Deterministic address relationship candidates surfaced as advisory metadata (issue #192) | Accepted | 2026-06-20 |
| [DD-085](decisions/dd-085-okf-phase-logs-replace-interactive-sessions-design-logs.md) | OKF phase logs replace interactive `.sessions-design` logs | Accepted | 2026-06-20 |
| [DD-086](decisions/dd-086-reporting-informed-draft-model-planning-report.md) | Reporting-informed draft-model planning report | Accepted | 2026-06-21 |
| [DD-087](decisions/dd-087-data-product-vertical-slice-planning-reports.md) | Data-product vertical-slice planning reports | Accepted | 2026-06-21 |
| [DD-088](decisions/dd-088-skill-scoped-opt-in-design-fleet-mode.md) | Skill-scoped opt-in design fleet mode | Accepted | 2026-06-22 |
| [DD-089](decisions/dd-089-offline-silver-sample-audit.md) | Offline silver sample audit | Accepted | 2026-06-22 |
| [DD-090](decisions/dd-090-core-concepts-conformance--toolkit-runtime-for-the-archetype--discovery-contract-v02.md) | Core Concepts Conformance — toolkit runtime for the archetype + discovery contract (v0.2) | Accepted | 2026-06-22 |
| [DD-091](decisions/dd-091-optional-ddd-governance-overlay-architecture-documentation-only.md) | Optional DDD governance overlay (architecture documentation only) | Accepted | 2026-07-05 |
| [DD-092](decisions/dd-092-contracted-custom-dbt-transformation-boundary.md) | Contracted custom dbt transformation boundary | Accepted | 2026-07-18 |
| [DD-093](decisions/dd-093-governed-contracted-source-replacement-in-source-coverage.md) | Governed contracted-source replacement in source coverage | Accepted | 2026-07-18 |
| [DD-094](decisions/dd-094-claim-registry-is-the-single-materialization-authority.md) | Claim Registry is the single materialization authority | Accepted | 2026-07-21 |
| [DD-095](decisions/dd-095-derive-claims-deterministic-multi-source-evidence-aggregation.md) | derive-claims deterministic multi-source evidence aggregation | Accepted | 2026-07-21 |
| [DD-096](decisions/dd-096-target-first-derived-aspirational-silver-stub--bind-loop.md) | Target-first derived-aspirational Silver stub → bind loop | Accepted | 2026-07-21 |
| [DD-097](decisions/dd-097-multi-domain-dbt-projection--shared-artifact-reconciliation-and-peer-import-authority.md) | Multi-domain dbt projection — shared-artifact reconciliation and peer-import authority (issue #220) | Accepted | 2026-07-21 |
| [DD-098](decisions/dd-098-alignment--projection-correctness-hardening-toolkit-optimizations-f1f7.md) | Alignment & projection correctness hardening (toolkit-optimizations F1–F7) | Accepted | 2026-07-21 |
| [DD-099](decisions/dd-099-single-typed-projection-target-registry.md) | Single typed projection target registry | Accepted | 2026-07-21 |
| [DD-100](decisions/dd-100-explicit-one-shot-migration-for-retired-inventory--projection-layouts.md) | Explicit one-shot migration for retired inventory & projection layouts | Accepted | 2026-07-21 |
| [DD-101](decisions/dd-101-consolidated-deterministic-lifecycle-gate-check-release.md) | Consolidated deterministic lifecycle gate (`check-release`) | Accepted | 2026-07-21 |
| [DD-102](decisions/dd-102-dbt-projector-decomposed-into-five-deterministic-phases.md) | dbt projector decomposed into five deterministic phases | ~~Superseded by DD-110~~ | 2026-07-21 |
| [DD-103](decisions/dd-103-canonical-ontology-closure-and-versioned-semantic-index.md) | Canonical ontology closure and versioned semantic index | Accepted | 2026-07-21 |
| [DD-104](decisions/dd-104-reference-module-activation-managed-imports-and-portable-silver-contracts.md) | Reference-module activation, managed imports, and portable Silver contracts | Accepted | 2026-07-22 |
| [DD-105](decisions/dd-105-imported-dbt-evidence-is-governed-before-mapping-and-silver.md) | Imported dbt evidence is governed before Mapping and Silver | Accepted | 2026-07-22 |
| [DD-106](decisions/dd-106-immutable-bronze-and-mandatory-logical-source-preparation.md) | Immutable Bronze and Mandatory Logical Source Preparation | Accepted | 2026-07-25 |
| [DD-107](decisions/dd-107-safe-mapping-expressions-and-transformation-authority.md) | Safe Mapping Expressions and Transformation Authority | Accepted | 2026-07-25 |
| [DD-108](decisions/dd-108-identity-lineage-multi-source-conformance-and-mdm-boundary.md) | Identity, Lineage, Multi-Source Conformance, and MDM Boundary | Accepted | 2026-07-25 |
| [DD-109](decisions/dd-109-temporal-execution-canonical-hashing-and-fk-resolution.md) | Temporal Execution, Canonical Hashing, and FK Resolution | Accepted | 2026-07-25 |
| [DD-110](decisions/dd-110-typed-projection-contract-and-silver-output-parity.md) | Typed Projection Contract and Silver Output Parity | Accepted | 2026-07-25 |
| [DD-111](decisions/dd-111-adapter-capabilities-and-physical-policy.md) | Adapter Capabilities and Physical Policy | Accepted | 2026-07-25 |
| [DD-112](decisions/dd-112-gold-product-profiles-and-explicit-dimensional-design.md) | Gold Product Profiles and Explicit Dimensional Design | Accepted | 2026-07-25 |
| [DD-113](decisions/dd-113-governed-semantic-model-lifecycle.md) | Governed Semantic-Model Lifecycle | Accepted | 2026-07-25 |
| [DD-114](decisions/dd-114-policy-capability-deviation-and-versioned-release-evidence.md) | Policy, Capability, Deviation, and Versioned Release Evidence | Accepted | 2026-07-25 |
| [DD-115](decisions/dd-115-data-quality-policy-and-runtime-result-contract.md) | Data-Quality Policy and Runtime-Result Contract | Accepted | 2026-07-25 |
| [DD-116](decisions/dd-116-non-writing-projection-readiness.md) | Non-Writing Projection Readiness | Accepted | 2026-07-26 |
| [DD-117](decisions/dd-117-prefixable-virtual-column-iris-and-explicit-migration.md) | Prefixable Virtual-Column IRIs and Explicit Migration | Accepted | 2026-07-26 |
| [DD-118](decisions/dd-118-contracted-dbt-output-as-verified-source-identity.md) | Contracted dbt Output as Verified Source Identity | Accepted | 2026-07-26 |
| [DD-119](decisions/dd-119-unverified-contract-identity-is-review-only-outside-strict-release.md) | Unverified Contract Identity Is Review-Only Outside Strict Release | Accepted | 2026-07-26 |
| [DD-120](decisions/dd-120-additive-validation-reports-and-non-writing-lifecycle-state-suggestion.md) | Additive Validation Reports and Non-Writing Lifecycle-State Suggestion | Accepted | 2026-07-26 |
| [DD-121](decisions/dd-121-failure-safe-alignment-generation-with-typed-per-table-outcomes.md) | Failure-Safe Alignment Generation with Typed Per-Table Outcomes | Accepted | 2026-07-27 |
| [DD-122](decisions/dd-122-unified-claim-activation-predicate-and-a-versioned-claim-check-result.md) | Unified Claim-Activation Predicate and a Versioned Claim-Check Result | Accepted | 2026-07-27 |
| [DD-123](decisions/dd-123-mapping-skill-derived-table-scope-and-visible-out-of-scope-diagnostics.md) | Mapping-Skill-Derived Table Scope and Visible Out-of-Scope Diagnostics | Accepted | 2026-07-26 |
| [DD-124](decisions/dd-124-uri-first-confirmed-anchor-resolution-and-a-versioned-unresolved-anchor-record.md) | URI-First Confirmed-Anchor Resolution and a Versioned Unresolved-Anchor Record | Accepted | 2026-07-26 |
| [DD-125](decisions/dd-125-domain-ownership-inferred-accelerator-resolution-with-diagnostics.md) | Domain-Ownership-Inferred Accelerator Resolution with Diagnostics | Accepted | 2026-07-26 |
| [DD-126](decisions/dd-126-metadata-complete-convergent-scaffolding-with-explicit-createdupdatedunchanged-reporting.md) | Metadata-Complete, Convergent Scaffolding with Explicit Created/Updated/Unchanged Reporting | Accepted | 2026-08-02 |
| [DD-127](decisions/dd-127-domain-ownership-handoffs-and-generalized-stable-cluster-relationship-candidates.md) | Domain-Ownership Handoffs and Generalized, Stable-Cluster Relationship Candidates | Accepted | 2026-08-09 |
| [DD-128](decisions/dd-128-intent-preserving-coverage-classification-run-atomic-registry-writes-and-authoritative.md) | Intent-Preserving Coverage Classification, Run-Atomic Registry Writes, and Authoritative Model Precedence | Accepted | 2026-07-26 |
| [DD-129](decisions/dd-129-domain-scoped-active-source-authority-for-projection-readiness.md) | Domain-Scoped Active Source Authority for Projection Readiness | Accepted | 2026-07-26 |
| [DD-130](decisions/dd-130-silver-ext-shape-discovery-with-packaged-fallback-and-windows-safe-loading.md) | Silver-ext Shape Discovery with Packaged Fallback and Windows-Safe Loading | Accepted | 2026-07-26 |
| [DD-131](decisions/dd-131-multi-class-property-domains-via-a-single-effective-domain-resolver.md) | Multi-Class Property Domains via a Single Effective-Domain Resolver | Accepted | 2026-07-26 |
| [DD-132](decisions/dd-132-fact-extraction-decomposition-guarded-by-a-full-artifact-characterization-baseline.md) | Fact-Extraction Decomposition Guarded by a Full-Artifact Characterization Baseline | Accepted | 2026-07-27 |
| [DD-133](decisions/dd-133-v5-authoring-break--yaml-entitybinding--stateless-compile.md) | V5 Authoring Break — YAML EntityBinding + Stateless `compile` | Accepted | 2026-07-27 |
| [DD-134](decisions/dd-134-immutable-reversible-unreleased-toolkit-testing.md) | Immutable, Reversible Unreleased Toolkit Testing | Accepted | 2026-07-27 |
| [DD-135](decisions/dd-135-retire-v4-release-and-lifecycle-orchestration.md) | Retire V4 Release and Lifecycle Orchestration | Accepted | 2026-07-27 |
| [DD-136](decisions/dd-136-retire-v4-claim-binding-and-completeness-authority.md) | Retire V4 Claim Binding and Completeness Authority | Accepted | 2026-07-27 |
| [DD-137](decisions/dd-137-derived-stateless-readiness-proposal-kairos-ontology-next.md) | Derived, Stateless Readiness Proposal (`kairos-ontology next`) | Accepted | 2026-07-28 |
| [DD-138](decisions/dd-138-cross-domain-relationship-targets-via-external-references.md) | Cross-domain Relationship Targets via External References | Accepted | 2026-07-28 |
| [DD-139](decisions/dd-139-authored-passthrough-technical-columns--dd-107-amendment.md) | Authored Passthrough Technical Columns — DD-107 Amendment | Accepted | 2026-07-28 |
| [DD-140](decisions/dd-140-canonical-emit-layout-and-dbt-package-topology.md) | Canonical Emit Layout and dbt-Package Topology | Accepted | 2026-07-28 |
| [DD-141](decisions/dd-141-adopt-okf-based-per-hub-decision-log-as-a-toolkit-capability.md) | Adopt OKF-based per-hub Decision Log as a toolkit capability | Accepted | 2026-07-29 |
| [DD-142](decisions/dd-142-derived-output-relocated-to-sibling-ontology-hub-publish-dd-140-amendment.md) | Derived Output Relocated to Sibling `ontology-hub-publish/` (DD-140 Amendment) | Accepted | 2026-07-30 |
| [DD-143](decisions/dd-143-standard-conformance-report-output-format-for-kairos-design-discovery.md) | Standard Conformance-Report Output Format for `kairos-design-discovery` | Accepted | 2026-08-01 |
| [DD-144](decisions/dd-144-accelerator-direct-binding-resolution-and-the-machine-managed-domain-stub.md) | Accelerator-Direct Binding Resolution and the Machine-Managed Domain Stub | Accepted | 2026-08-09 |
| [DD-145](decisions/dd-145-local-extension-ontology-and-shacl-derivation-narrowed-cr-2.md) | Local-Extension Ontology and SHACL Derivation (Narrowed CR-2) | Accepted | 2026-08-09 |
| [DD-146](decisions/dd-146-pattern-library-as-an-advisory-authoring-time-consumer.md) | Pattern library as an advisory, authoring-time consumer | Accepted | 2026-08-10 |
| [DD-147](decisions/dd-147-power-bitmdl-analysis-is-demand-evidence-under-integrationdiscoverybi.md) | Power BI/TMDL analysis is demand evidence under integration/discovery/bi | Accepted | 2026-08-10 |
| [DD-148](decisions/dd-148-discovery-before-design-and-fleet-mode-open-question-hard-gates-amends-dd-059.md) | Discovery-Before-Design and Fleet-Mode Open-Question Hard Gates (Amends DD-059) | Accepted | 2026-08-10 |
| [DD-149](decisions/dd-149-human-confirmed-archetype-selection-amends-dd-088dd-090.md) | Human-Confirmed Archetype Selection (Amends DD-088/DD-090) | Accepted | 2026-08-10 |
| [DD-150](decisions/dd-150-reference-models-owns-the-tier-enum-the-toolkit-derives-ontology-tier-amends-dd-146.md) | Reference-models owns the tier enum; the toolkit derives ontology tier (Amends DD-146) | Accepted | 2026-08-10 |
| [DD-151](decisions/dd-151-structured-logging-foundation--opt-in-opentelemetry-bridge.md) | Structured logging foundation + opt-in OpenTelemetry bridge | Accepted | 2026-08-14 |
| [DD-152](decisions/dd-152-reference-models-resolve-from-a-shared-versioned-machine-level-cache-supersedes-dd-036s.md) | Reference Models Resolve From a Shared, Versioned Machine-Level Cache (Supersedes DD-036's Location) | Superseded by DD-158 | 2026-08-14 |
| [DD-153](decisions/dd-153-command-outcome-and-exit-code-contract.md) | Command Outcome and Exit-Code Contract | Accepted | 2026-08-14 |
| [DD-154](decisions/dd-154-content-addressed-inventory-writes-unchanged-counts-as-produced.md) | Content-addressed inventory writes; unchanged counts as produced | Accepted | 2026-08-15 |
| [DD-155](decisions/dd-155-managed-import-completeness-is-mode-independent-and-gates-registration.md) | Managed Import Completeness is mode-independent and gates registration | Accepted | 2026-08-15 |
| [DD-156](decisions/dd-156-profiling-evidence-semantics-row_count-rows_sampled-distinctscope.md) | Profiling evidence semantics: row_count, rows_sampled, distinctScope | Accepted | 2026-08-15 |
| [DD-157](decisions/dd-157-domain-ownership-surfacing-and-demand-evidence-routing.md) | Domain ownership surfacing and demand-evidence routing | Accepted | 2026-08-15 |
| [DD-158](decisions/dd-158-reference-models-resolve-from-an-installed-python-package-supersedes-dd-152-amends-dd-036.md) | Reference Models Resolve From an Installed Python Package (Supersedes DD-152, Amends DD-036) | Accepted | 2026-08-15 |
| [DD-159](decisions/dd-159-llm-judgment-steps-must-never-auto-degrade.md) | LLM Judgment Steps Must Never Auto-Degrade | Accepted | 2026-07-28 |
| [DD-160](decisions/dd-160-source-affinity-domain-coverage-and-relationship-proposal.md) | Source-affinity domain coverage and relationship proposal | Accepted | 2026-08-15 |
| [DD-161](decisions/dd-161-multiple-bindings-per-source-relation-multi-target-bindings-rejected.md) | Multiple bindings per source relation; multi-target bindings rejected | Accepted | 2026-08-15 |
| [DD-162](decisions/dd-162-hub-side-registration-of-source-discovered-concepts.md) | Hub-side registration of source-discovered concepts | Accepted | 2026-08-15 |
| [DD-163](decisions/dd-163-hub-wide-ontology-integrity-is-enforced-not-advised.md) | Hub-wide ontology integrity is enforced, not advised | Accepted | 2026-08-16 |
| [DD-164](decisions/dd-164-every-source-table-needs-a-recorded-disposition.md) | Every source table needs a recorded disposition | Accepted | 2026-08-16 |
| [DD-165](decisions/dd-165-anchoring-is-suggested-deterministically-never-invented.md) | Anchoring is suggested deterministically, never invented | Accepted | 2026-08-16 |
| [DD-166](decisions/dd-166-sample-values-are-evidence-and-are-gated-before-they-leave-the-hub.md) | Sample values are evidence, and are gated before they leave the hub | Accepted | 2026-08-16 |
| [DD-167](decisions/dd-167-conformance-judgment-is-offloaded-retrieval-grounded-and-code-gated.md) | Conformance judgment is offloaded, retrieval-grounded, and code-gated | Accepted | 2026-08-16 |
| [DD-168](decisions/dd-168-alignment-coverage-is-reported-with-a-reason-code-per-unmapped-column.md) | Alignment coverage is reported with a reason code per unmapped column | Accepted | 2026-08-16 |
| [DD-169](decisions/dd-169-the-alignment-gap-is-a-hard-stop-before-entity-binding.md) | The alignment gap is a hard stop before entity binding | Accepted | 2026-08-16 |
| [DD-170](decisions/dd-170-a-model-proposed-hub-local-property-is-validated-not-trusted.md) | A model-proposed hub-local property is validated, not trusted | Accepted | 2026-08-16 |
| [DD-171](decisions/dd-171-the-business-glossary-is-a-preflight-input-to-alignment.md) | The business glossary is a preflight input to alignment | Accepted | 2026-08-16 |
| [DD-172](decisions/dd-172-namespace-constants-are-pinned-by-test-after-domainincludes-never-matched.md) | Namespace constants are pinned by test, after `domainIncludes` never matched | Accepted | 2026-08-16 |
| [DD-173](decisions/dd-173-reference-models-resolve-live-there-is-no-inventory.md) | Reference models resolve live; there is no inventory | Accepted | 2026-08-16 |
| [DD-174](decisions/dd-174-llm-pipeline-stages-are-seeded-and-capability-degradation-is-centralised.md) | LLM pipeline stages are seeded, and capability degradation is centralised | Accepted | 2026-08-16 |
| [DD-175](decisions/dd-175-the-prompt-is-reproducible-because-a-seed-cannot-stabilise-a-moving-question.md) | The prompt is reproducible, because a seed cannot stabilise a moving question | Accepted | 2026-08-16 |
| [DD-176](decisions/dd-176-reasoning-effort-is-a-per-role-knob-defaulted-from-the-shape-of-the-work.md) | Reasoning effort is a per-role knob, defaulted from the shape of the work | Accepted | 2026-08-16 |
| [DD-177](decisions/dd-177-the-alignment-answer-is-shape-constrained-so-a-column-cannot-be-skipped.md) | The alignment answer is shape-constrained, so a column cannot be skipped | Accepted | 2026-08-16 |
| [DD-178](decisions/dd-178-an-ai-generated-artifact-states-its-own-provenance-and-review-status.md) | An AI-generated artifact states its own provenance and review status | Accepted | 2026-08-16 |
| [DD-179](decisions/dd-179-alignment-sees-the-tables-role-structure-and-the-mapping-is-checked-as-a-set.md) | Alignment sees the table's role structure, and the mapping is checked as a set | Accepted | 2026-08-16 |
| [DD-180](decisions/dd-180-an-unanchored-table-is-reported-gated-and-told-where-its-class-lives.md) | An unanchored table is reported, gated, and told where its class lives | Accepted | 2026-08-16 |
| [DD-181](decisions/dd-181-a-declared-cross-domain-bridge-makes-a-class-anchorable-by-default.md) | A declared cross-domain bridge makes a class anchorable, by default | Accepted | 2026-08-16 |
| [DD-182](decisions/dd-182-per-table-vocabulary-is-a-projection-of-the-aggregate-not-a-second-derivation.md) | Per-table vocabulary is a projection of the aggregate, not a second derivation | Accepted | 2026-08-16 |
| [DD-183](decisions/dd-183-affinity-resolves-the-hubs-accelerator-instead-of-scanning-the-whole-tree.md) | Affinity resolves the hub's accelerator instead of scanning the whole tree | Accepted | 2026-08-16 |
| [DD-184](decisions/dd-184-llm-calls-are-traced-to-langfuse-opt-in-with-source-values-masked.md) | LLM calls are traced to Langfuse, opt-in, with source values masked | Accepted | 2026-08-16 |
| [DD-185](decisions/dd-185-tables-are-anchored-globally-in-one-call-before-per-table-alignment.md) | Tables are anchored globally, in one call, before per-table alignment | Accepted | 2026-08-17 |
| [DD-186](decisions/dd-186-the-gap-gate-is-drafted-grouped-by-domain-scoped-family-and-still-decided-by-a-human.md) | The gap gate is drafted, grouped by domain-scoped family, and still decided by a human | Accepted | 2026-08-17 |
| [DD-187](decisions/dd-187-domain-design-runs-as-a-fleet-and-every-refusal-is-recorded-in-the-file-it-belongs-to.md) | Domain design runs as a fleet, and every refusal is recorded in the file it belongs to | Accepted | 2026-08-17 |
| [DD-188](decisions/dd-188-ontology-semantics-live-in-the-reference-models-never-in-the-toolkit.md) | Ontology semantics live in the reference models, never in the toolkit | Accepted | 2026-08-17 |
| [DD-189](decisions/dd-189-sources-are-profiled-deterministically-before-any-model-call.md) | Sources are profiled deterministically before any model call | Accepted | 2026-08-19 |
| [DD-190](decisions/dd-190-the-anchors-artifact-is-a-reviewable-design-sheet-with-sticky-human-decisions.md) | The anchors artifact is a reviewable design sheet with sticky human decisions | Accepted | 2026-08-19 |
| [DD-191](decisions/dd-191-first-draft-bindings-are-generated-from-the-design-sheet-and-validated-before-they-exist.md) | First-draft bindings are generated from the design sheet and validated before they exist | Accepted | 2026-08-19 |
| [DD-192](decisions/dd-192-human-design-rulings-are-durable-transferable-and-outrank-model-judgment.md) | Human design rulings are durable, transferable, and outrank model judgment | Accepted | 2026-08-19 |
| [DD-193](decisions/dd-193-the-profiling-class-catalog-is-scoped-to-the-resolved-accelerator.md) | The profiling class catalog is scoped to the resolved accelerator | Accepted | 2026-08-19 |
| [DD-194](decisions/dd-194-temporal-columns-are-excluded-from-profiling-key-set-candidacy.md) | Temporal columns are excluded from profiling key-set candidacy | Accepted | 2026-08-19 |
| [DD-195](decisions/dd-195-the-scaffold-offers-every-extra-the-toolkit-ships-including-langfuse.md) | The scaffold offers every extra the toolkit ships, including langfuse | Accepted | 2026-08-19 |
| [DD-196](decisions/dd-196-archived-reference-model-snapshots-are-excluded-from-resolution-unconditionally.md) | Archived reference-model snapshots are excluded from resolution unconditionally | Accepted | 2026-08-19 |
| [DD-197](decisions/dd-197---max-workers-gets-a-hub-level-default-in-the-same-place-accelerator-and-channel-already.md) | --max-workers gets a hub-level default, in the same place accelerator and channel already live | Accepted | 2026-08-19 |
| [DD-198](decisions/dd-198-ai-preflight-surfaces-a-missing-sdk-as-a-missing-dependency-with-a-uv-native-fix-not-as.md) | AI preflight surfaces a missing SDK as a missing dependency, with a uv-native fix, not as network unreachability | Accepted | 2026-08-20 |
| [DD-199](decisions/dd-199-per-pr-ci-only-gates-on-the-prs-own-diff-global-state-checks-move-to-a-schedule.md) | Per-PR CI only gates on the PR's own diff; global-state checks move to a schedule | Accepted | 2026-08-20 |
| [DD-200](decisions/dd-200-update---upgrade-also-upgrades-reference-models-resolved-the-same-way-scaffolding-is.md) | `update --upgrade` also upgrades reference models, resolved the same way scaffolding is | Accepted | 2026-08-20 |
| [DD-201](decisions/dd-201-a-cross-domain-class-name-collision-is-resolved-by-richness-and-the-resolution-travels.md) | A cross-domain class-name collision is resolved by richness, and the resolution travels downstream as a URI | Accepted | 2026-08-20 |
| [DD-202](decisions/dd-202-generate-bindings-recognizes-non-generatable-rows-before-asking-the-validator.md) | generate-bindings recognizes non-generatable rows before asking the validator | Accepted | 2026-08-20 |
| [DD-203](decisions/dd-203-the-affinity-ai-provider-role-collapses-into-alignment-one-configured-provider-for-every.md) | The affinity AI-provider role collapses into alignment: one configured provider for every pre-modeling call | Accepted | 2026-08-20 |
| [DD-204](decisions/dd-204-rdfsdomain-owlthing-gets-its-own-diagnostic-on-both-sides-of-the-boundary-instead-of.md) | `rdfs:domain owl:Thing` gets its own diagnostic, on both sides of the boundary, instead of being read as a missing `owl:imports` | Accepted | 2026-08-20 |
| [DD-205](decisions/dd-205-source-sample-values-reach-langfuse-and-the-alignment-review-artifact-by-default-a-new.md) | Source sample values reach Langfuse and the alignment review artifact by default; a new raw-sample channel feeds the alignment prompt itself | Accepted | 2026-08-20 |
| [DD-206](decisions/dd-206-branching-and-collaboration-guide-for-hub-and-dataplatform-repositories.md) | Branching and Collaboration Guide for Hub and Dataplatform Repositories | Accepted | 2026-08-27 |
| [DD-207](decisions/dd-207-skills-move-from-githubskills-to-claudeskills--one-tree-copilot-and-claude-code-both-read.md) | Skills move from `.github/skills/` to `.claude/skills/` — one tree Copilot and Claude Code both read | Accepted | 2026-08-27 |
| [DD-208](decisions/dd-208-the-powerbi-target-registry-entry-becomes-flat-retiring-the-empty-medallionpowerbi.md) | The `powerbi` target registry entry becomes flat, retiring the empty `medallion/powerbi` placeholder | Accepted | 2026-08-29 |
| [DD-209](decisions/dd-209-a-binding-independent-erd-target-projects-the-full-canonical-graph-regardless-of-compile.md) | A binding-independent `erd` target projects the full canonical graph regardless of compile-plan coverage | Accepted | 2026-08-29 |
| [DD-210](decisions/dd-210-version-bump-moves-from-mandatory-per-pr-to-release-time-only.md) | Version bump moves from mandatory-per-PR to release-time-only | Accepted | 2026-08-30 |
| [DD-211](decisions/dd-211-the-hub-wide-bound-master-erd-is-reconnected-to-compileemit-gold-the-dead-run_projections.md) | The hub-wide bound master ERD is reconnected to `compile`/`emit-gold`; the dead `run_projections` dbt/silver/powerbi branch is retired in place | Accepted | 2026-08-30 |
| [DD-212](decisions/dd-212-the-canonical-erd-target-renders-a-mermaid-classdiagram-instead-of-erdiagram-and-gains-a.md) | The canonical `erd` target renders a Mermaid `classDiagram` instead of `erDiagram`, and gains a plumbing-only overlay hook | Accepted | 2026-08-30 |
| [DD-213](decisions/dd-213-the-silver-contract-is-declared-not-derived--bindings-conform-to-it.md) | The Silver contract is declared, not derived — bindings conform to it | Accepted | 2026-09-01 |
| [DD-214](decisions/dd-214-sample-redaction-is-opt-in-at-import-the-pre-send-scan-advises-instead-of-refusing.md) | Sample redaction is opt-in at import; the pre-send scan advises instead of refusing | Accepted | 2026-09-01 |
| [DD-215](decisions/dd-215-the-target-platform-names-the-engine-and-boolean-ness-is-rendered-per-adapter.md) | The target platform names the engine, and boolean-ness is rendered per adapter | Accepted | 2026-09-03 |
| [DD-216](decisions/dd-216-the-declared-silver-contract-gets-its-own-diagram.md) | The declared Silver contract gets its own diagram | Accepted | 2026-09-04 |
| [DD-217](decisions/dd-217-gold-projection-is-controllable-at-the-column.md) | Gold projection is controllable at the column | Accepted | 2026-09-04 |
| [DD-218](decisions/dd-218-emitted-artifacts-carry-their-own-provenance-sidecar-not-a-manifest-schema-bump.md) | Emitted artifacts carry their own provenance sidecar, not a manifest schema bump | Accepted | 2026-09-05 |

---
