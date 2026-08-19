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

> **Current architecture:** start with DD-133. DD-135 and DD-136 record the completed v4
> operational retirement. Earlier accepted entries remain historical records unless a later
> decision explicitly supersedes them; they are not an alternate active authoring path.

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
| [DD-014](#dd-014-eliminate-staging--silver-reads-bronze-directly) | Eliminate Staging — Silver Reads Bronze Directly | ~~Superseded by DD-106~~ | 2026-05-14 |
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
| [DD-025](#dd-025-scd-type-aware-dbt-silver-models) | SCD Type-Aware dbt Silver Models | ~~Superseded by DD-109~~ | 2026-05-26 |
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
| [DD-039](#dd-039-enhanced-schema-extraction-with-json-flattening--bronze-expanded-layer) | Enhanced Schema Extraction with JSON Flattening & Bronze Expanded Layer | ~~Superseded by DD-106~~ | 2026-06-02 |
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
| [DD-061](#dd-061-deterministic-source-coverage-gates-check-alignment--check-source-coverage) | Deterministic Source-Coverage Gates (check-alignment + check-source-coverage) | Superseded by DD-094 | 2026-06-13 |
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
| [DD-080](#dd-080-two-layer-lifecycle-state-deterministic-status-cli-and-the-kairos-flow-single-entry-point) | Two-layer lifecycle state, deterministic `status` CLI, and the `kairos-flow` single entry point | Accepted | 2026-06-20 |
| [DD-081](#dd-081-analyse-sources---domains-is-an-output-filter-not-a-candidate-restriction) | `analyse-sources --domains` is an output filter, not a candidate restriction | Accepted | 2026-06-20 |
| [DD-082](#dd-082-claim-curation-ergonomics-decide-claims-uri-back-fill-skeleton-bootstrap-intra-hub-imports-issue-190) | Claim-curation ergonomics: `decide-claims`, URI back-fill, skeleton bootstrap, intra-hub imports (issue #190) | Accepted | 2026-06-20 |
| [DD-083](#dd-083-claims-to-silver-ext-preserves-authored-ttl-via-a-managed-block-issue-191) | `claims-to-silver-ext` preserves authored TTL via a managed block (issue #191) | Accepted | 2026-06-20 |
| [DD-084](#dd-084-deterministic-address-relationship-candidates-surfaced-as-advisory-metadata-issue-192) | Deterministic address relationship candidates surfaced as advisory metadata (issue #192) | Accepted | 2026-06-20 |
| [DD-085](#dd-085-okf-phase-logs-replace-interactive-sessions-design-logs) | OKF phase logs replace interactive `.sessions-design` logs | Accepted | 2026-06-20 |
| [DD-086](#dd-086-reporting-informed-draft-model-planning-report) | Reporting-informed draft-model planning report | Accepted | 2026-06-21 |
| [DD-087](#dd-087-data-product-vertical-slice-planning-reports) | Data-product vertical-slice planning reports | Accepted | 2026-06-21 |
| [DD-088](#dd-088-skill-scoped-opt-in-design-fleet-mode) | Skill-scoped opt-in design fleet mode | Accepted | 2026-06-22 |
| [DD-089](#dd-089-offline-silver-sample-audit) | Offline silver sample audit | Accepted | 2026-06-22 |
| [DD-090](#dd-090-core-concepts-conformance--toolkit-runtime-for-the-archetype--discovery-contract-v02) | Core Concepts Conformance — toolkit runtime for the archetype + discovery contract (v0.2) | Accepted | 2026-06-22 |
| [DD-091](#dd-091-optional-ddd-governance-overlay-architecture-documentation-only) | Optional DDD governance overlay (architecture documentation only) | Accepted | 2026-06-22 |
| [DD-092](#dd-092-contracted-custom-dbt-transformation-boundary) | Contracted custom dbt transformation boundary | Accepted | 2026-07-18 |
| [DD-093](#dd-093-governed-contracted-source-replacement-in-source-coverage) | Governed contracted-source replacement in source coverage | Accepted | 2026-07-18 |
| [DD-094](#dd-094-claim-registry-is-the-single-materialization-authority) | Claim Registry is the single materialization authority | Accepted | 2026-07-21 |
| [DD-095](#dd-095-derive-claims-deterministic-multi-source-evidence-aggregation) | derive-claims deterministic multi-source evidence aggregation | Accepted | 2026-07-21 |
| [DD-096](#dd-096-target-first-derived-aspirational-silver-stub--bind-loop) | Target-first derived-aspirational Silver stub → bind loop | Accepted | 2026-07-21 |
| [DD-097](#dd-097-multi-domain-dbt-projection--shared-artifact-reconciliation-and-peer-import-authority-issue-220) | Multi-domain dbt projection — shared-artifact reconciliation and peer-import authority (issue #220) | Accepted | 2026-07-21 |
| [DD-098](#dd-098-alignment--projection-correctness-hardening-toolkit-optimizations-f1f7) | Alignment & projection correctness hardening (toolkit-optimizations F1–F7) | Accepted | 2026-07-21 |
| [DD-099](#dd-099-single-typed-projection-target-registry) | Single typed projection target registry | Accepted | 2026-07-21 |
| [DD-100](#dd-100-explicit-one-shot-migration-for-retired-inventory--projection-layouts) | Explicit one-shot migration for retired inventory & projection layouts | Accepted | 2026-07-21 |
| [DD-101](#dd-101-consolidated-deterministic-lifecycle-gate-check-release) | Consolidated deterministic lifecycle gate (`check-release`) | Accepted | 2026-07-21 |
| [DD-102](#dd-102-dbt-projector-decomposed-into-five-deterministic-phases) | dbt projector decomposed into five deterministic phases | ~~Superseded by DD-110~~ | 2026-07-21 |
| [DD-103](#dd-103-canonical-ontology-closure-and-versioned-semantic-index) | Canonical ontology closure and versioned semantic index | Accepted | 2026-07-21 |
| [DD-104](#dd-104-reference-module-activation-managed-imports-and-portable-silver-contracts) | Reference-module activation, managed imports, and portable Silver contracts | Accepted | 2026-07-22 |
| [DD-105](#dd-105-imported-dbt-evidence-is-governed-before-mapping-and-silver) | Imported dbt evidence is governed before Mapping and Silver | Accepted | 2026-07-22 |
| [DD-106](#dd-106-immutable-bronze-and-mandatory-logical-source-preparation) | Immutable Bronze and Mandatory Logical Source Preparation | Accepted | 2026-07-25 |
| [DD-107](#dd-107-safe-mapping-expressions-and-transformation-authority) | Safe Mapping Expressions and Transformation Authority | Accepted | 2026-07-25 |
| [DD-108](#dd-108-identity-lineage-multi-source-conformance-and-mdm-boundary) | Identity, Lineage, Multi-Source Conformance, and MDM Boundary | Accepted | 2026-07-25 |
| [DD-109](#dd-109-temporal-execution-canonical-hashing-and-fk-resolution) | Temporal Execution, Canonical Hashing, and FK Resolution | Accepted | 2026-07-25 |
| [DD-110](#dd-110-typed-projection-contract-and-silver-output-parity) | Typed Projection Contract and Silver Output Parity | Accepted | 2026-07-25 |
| [DD-111](#dd-111-adapter-capabilities-and-physical-policy) | Adapter Capabilities and Physical Policy | Accepted | 2026-07-25 |
| [DD-112](#dd-112-gold-product-profiles-and-explicit-dimensional-design) | Gold Product Profiles and Explicit Dimensional Design | Accepted | 2026-07-25 |
| [DD-113](#dd-113-governed-semantic-model-lifecycle) | Governed Semantic-Model Lifecycle | Accepted | 2026-07-25 |
| [DD-114](#dd-114-policy-capability-deviation-and-versioned-release-evidence) | Policy, Capability, Deviation, and Versioned Release Evidence | Accepted | 2026-07-25 |
| [DD-115](#dd-115-data-quality-policy-and-runtime-result-contract) | Data-Quality Policy and Runtime-Result Contract | Accepted | 2026-07-25 |
| [DD-116](#dd-116-non-writing-projection-readiness) | Non-Writing Projection Readiness | Accepted | 2026-07-26 |
| [DD-117](#dd-117-prefixable-virtual-column-iris-and-explicit-migration) | Prefixable Virtual-Column IRIs and Explicit Migration | Accepted | 2026-07-26 |
| [DD-118](#dd-118-contracted-dbt-output-as-verified-source-identity) | Contracted dbt Output as Verified Source Identity | Accepted | 2026-07-26 |
| [DD-119](#dd-119-unverified-contract-identity-is-review-only-outside-strict-release) | Unverified Contract Identity Is Review-Only Outside Strict Release | Accepted | 2026-07-26 |
| [DD-120](#dd-120-additive-validation-reports-and-non-writing-lifecycle-state-suggestion) | Additive Validation Reports and Non-Writing Lifecycle-State Suggestion | Accepted | 2026-07-26 |
| [DD-121](#dd-121-failure-safe-alignment-generation-with-typed-per-table-outcomes) | Failure-Safe Alignment Generation with Typed Per-Table Outcomes | Accepted | 2026-07-27 |
| [DD-122](#dd-122-unified-claim-activation-predicate-and-a-versioned-claim-check-result) | Unified Claim-Activation Predicate and a Versioned Claim-Check Result | Accepted | 2026-07-27 |
| [DD-123](#dd-123-mapping-skill-derived-table-scope-and-visible-out-of-scope-diagnostics) | Mapping-Skill-Derived Table Scope and Visible Out-of-Scope Diagnostics | Accepted | 2026-07-26 |
| [DD-124](#dd-124-uri-first-confirmed-anchor-resolution-and-a-versioned-unresolved-anchor-record) | URI-First Confirmed-Anchor Resolution and a Versioned Unresolved-Anchor Record | Accepted | 2026-07-26 |
| [DD-125](#dd-125-domain-ownership-inferred-accelerator-resolution-with-diagnostics) | Domain-Ownership-Inferred Accelerator Resolution with Diagnostics | Accepted | 2026-07-26 |
| [DD-126](#dd-126-metadata-complete-convergent-scaffolding-with-explicit-createdupdatedunchanged-reporting) | Metadata-Complete, Convergent Scaffolding with Explicit Created/Updated/Unchanged Reporting | Accepted | 2026-08-02 |
| [DD-127](#dd-127-domain-ownership-handoffs-and-generalized-stable-cluster-relationship-candidates) | Domain-Ownership Handoffs and Generalized, Stable-Cluster Relationship Candidates | Accepted | 2026-08-09 |
| [DD-128](#dd-128-intent-preserving-coverage-classification-run-atomic-registry-writes-and-authoritative-model-precedence) | Intent-Preserving Coverage Classification, Run-Atomic Registry Writes, and Authoritative Model Precedence | Accepted | 2026-07-26 |
| [DD-129](#dd-129-domain-scoped-active-source-authority-for-projection-readiness) | Domain-Scoped Active Source Authority for Projection Readiness | Accepted | 2026-07-26 |
| [DD-130](#dd-130-silver-ext-shape-discovery-with-packaged-fallback-and-windows-safe-loading) | Silver-ext Shape Discovery with Packaged Fallback and Windows-Safe Loading | Accepted | 2026-07-26 |
| [DD-131](#dd-131-multi-class-property-domains-via-a-single-effective-domain-resolver) | Multi-Class Property Domains via a Single Effective-Domain Resolver | Accepted | 2026-07-26 |
| [DD-132](#dd-132-fact-extraction-decomposition-guarded-by-a-full-artifact-characterization-baseline) | Fact-Extraction Decomposition Guarded by a Full-Artifact Characterization Baseline | Accepted | 2026-07-27 |
| [DD-133](#dd-133-v5-authoring-break--yaml-entitybinding--stateless-compile) | V5 Authoring Break — YAML EntityBinding + Stateless `compile` | Accepted | 2026-07-27 |
| [DD-134](#dd-134-immutable-reversible-unreleased-toolkit-testing) | Immutable, Reversible Unreleased Toolkit Testing | Accepted | 2026-07-27 |
| [DD-135](#dd-135-retire-v4-release-and-lifecycle-orchestration) | Retire V4 Release and Lifecycle Orchestration | Accepted | 2026-07-27 |
| [DD-136](#dd-136-retire-v4-claim-binding-and-completeness-authority) | Retire V4 Claim Binding and Completeness Authority | Accepted | 2026-07-27 |
| [DD-137](#dd-137-derived-stateless-readiness-proposal-kairos-ontology-next) | Derived, Stateless Readiness Proposal (`kairos-ontology next`) | Accepted | 2026-07-28 |
| [DD-138](#dd-138-cross-domain-relationship-targets-via-external-references) | Cross-domain Relationship Targets via External References | Accepted | 2026-07-28 |
| [DD-139](#dd-139-authored-passthrough-technical-columns--dd-107-amendment) | Authored Passthrough Technical Columns — DD-107 Amendment | Accepted | 2026-07-28 |
| [DD-140](#dd-140-canonical-emit-layout-and-dbt-package-topology) | Canonical Emit Layout and dbt-Package Topology | Accepted | 2026-07-28 |
| [DD-141](#dd-141-adopt-okf-based-per-hub-decision-log-as-a-toolkit-capability) | Adopt OKF-based per-hub Decision Log as a toolkit capability | Accepted | 2026-07-29 |
| [DD-142](#dd-142-derived-output-relocated-to-sibling-ontology-hub-publish-dd-140-amendment) | Derived Output Relocated to Sibling `ontology-hub-publish/` (DD-140 Amendment) | Accepted | 2026-07-30 |
| [DD-143](#dd-143-standard-conformance-report-output-format-for-kairos-design-discovery) | Standard Conformance-Report Output Format for `kairos-design-discovery` | Accepted | 2026-08-01 |
| [DD-144](#dd-144-accelerator-direct-binding-resolution-and-the-machine-managed-domain-stub) | Accelerator-Direct Binding Resolution and the Machine-Managed Domain Stub | Accepted | 2026-08-09 |
| [DD-145](#dd-145-local-extension-ontology-and-shacl-derivation-narrowed-cr-2) | Local-Extension Ontology and SHACL Derivation (Narrowed CR-2) | Accepted | 2026-08-09 |
| [DD-146](#dd-146-pattern-library-as-an-advisory-authoring-time-consumer) | Pattern library as an advisory, authoring-time consumer | Accepted | 2026-08-10 |
| [DD-147](#dd-147-power-bitmdl-analysis-is-demand-evidence-under-integrationdiscoverybi) | Power BI/TMDL analysis is demand evidence under integration/discovery/bi | Accepted | 2026-08-10 |
| [DD-148](#dd-148-discovery-before-design-and-fleet-mode-open-question-hard-gates-amends-dd-059) | Discovery-Before-Design and Fleet-Mode Open-Question Hard Gates (Amends DD-059) | Accepted | 2026-08-10 |
| [DD-149](#dd-149-human-confirmed-archetype-selection-amends-dd-088dd-090) | Human-Confirmed Archetype Selection (Amends DD-088/DD-090) | Accepted | 2026-08-10 |
| [DD-150](#dd-150-reference-models-owns-the-tier-enum-the-toolkit-derives-ontology-tier-amends-dd-146) | Reference-models owns the tier enum; the toolkit derives ontology tier (Amends DD-146) | Accepted | 2026-08-10 |
| [DD-151](#dd-151-structured-logging-foundation--opt-in-opentelemetry-bridge) | Structured logging foundation + opt-in OpenTelemetry bridge | Accepted | 2026-08-14 |
| [DD-152](#dd-152-reference-models-resolve-from-a-shared-versioned-machine-level-cache-supersedes-dd-036s-location) | Reference Models Resolve From a Shared, Versioned Machine-Level Cache (Supersedes DD-036's Location) | Superseded by DD-158 | 2026-08-14 |
| [DD-153](#dd-153-command-outcome-and-exit-code-contract) | Command Outcome and Exit-Code Contract | Accepted | 2026-08-14 |
| [DD-154](#dd-154-content-addressed-inventory-writes-unchanged-counts-as-produced) | Content-addressed inventory writes; unchanged counts as produced | Accepted | 2026-08-15 |
| [DD-155](#dd-155-managed-import-completeness-is-mode-independent-and-gates-registration) | Managed Import Completeness is mode-independent and gates registration | Accepted | 2026-08-15 |
| [DD-156](#dd-156-profiling-evidence-semantics-rowcount-rowssampled-distinctscope) | Profiling evidence semantics: row_count, rows_sampled, distinctScope | Accepted | 2026-08-15 |
| [DD-157](#dd-157-domain-ownership-surfacing-and-demand-evidence-routing) | Domain ownership surfacing and demand-evidence routing | Accepted | 2026-08-15 |
| [DD-158](#dd-158-reference-models-resolve-from-an-installed-python-package-supersedes-dd-152-amends-dd-036) | Reference Models Resolve From an Installed Python Package (Supersedes DD-152, Amends DD-036) | Accepted | 2026-08-15 |
| [DD-159](#dd-159-llm-judgment-steps-must-never-auto-degrade) | LLM Judgment Steps Must Never Auto-Degrade | Accepted | 2026-07-28 |
| [DD-160](#dd-160-source-affinity-domain-coverage-and-relationship-proposal) | Source-affinity domain coverage and relationship proposal | Accepted | 2026-08-15 |
| [DD-161](#dd-161-multiple-bindings-per-source-relation-multi-target-bindings-rejected) | Multiple bindings per source relation; multi-target bindings rejected | Accepted | 2026-08-15 |
| [DD-162](#dd-162-hub-side-registration-of-source-discovered-concepts) | Hub-side registration of source-discovered concepts | Accepted | 2026-08-15 |
| [DD-163](#dd-163-hub-wide-ontology-integrity-is-enforced-not-advised) | Hub-wide ontology integrity is enforced, not advised | Accepted | 2026-08-16 |
| [DD-164](#dd-164-every-source-table-needs-a-recorded-disposition) | Every source table needs a recorded disposition | Accepted | 2026-08-16 |
| [DD-165](#dd-165-anchoring-is-suggested-deterministically-never-invented) | Anchoring is suggested deterministically, never invented | Accepted | 2026-08-16 |
| [DD-166](#dd-166-sample-values-are-evidence-and-are-gated-before-they-leave-the-hub) | Sample values are evidence, and are gated before they leave the hub | Accepted | 2026-08-16 |
| [DD-167](#dd-167-conformance-judgment-is-offloaded-retrieval-grounded-and-code-gated) | Conformance judgment is offloaded, retrieval-grounded, and code-gated | Accepted | 2026-08-16 |
| [DD-168](#dd-168-alignment-coverage-is-reported-with-a-reason-code-per-unmapped-column) | Alignment coverage is reported with a reason code per unmapped column | Accepted | 2026-08-16 |
| [DD-169](#dd-169-the-alignment-gap-is-a-hard-stop-before-entity-binding) | The alignment gap is a hard stop before entity binding | Accepted | 2026-08-16 |
| [DD-170](#dd-170-a-model-proposed-hub-local-property-is-validated-not-trusted) | A model-proposed hub-local property is validated, not trusted | Accepted | 2026-08-16 |
| [DD-171](#dd-171-the-business-glossary-is-a-preflight-input-to-alignment) | The business glossary is a preflight input to alignment | Accepted | 2026-08-16 |
| [DD-172](#dd-172-namespace-constants-are-pinned-by-test-after-domainincludes-never-matched) | Namespace constants are pinned by test, after `domainIncludes` never matched | Accepted | 2026-08-16 |
| [DD-173](#dd-173-reference-models-resolve-live-there-is-no-inventory) | Reference models resolve live; there is no inventory | Accepted | 2026-08-16 |
| [DD-174](#dd-174-llm-pipeline-stages-are-seeded-and-capability-degradation-is-centralised) | LLM pipeline stages are seeded, and capability degradation is centralised | Accepted | 2026-08-16 |
| [DD-175](#dd-175-the-prompt-is-reproducible-because-a-seed-cannot-stabilise-a-moving-question) | The prompt is reproducible, because a seed cannot stabilise a moving question | Accepted | 2026-08-16 |
| [DD-176](#dd-176-reasoning-effort-is-a-per-role-knob-defaulted-from-the-shape-of-the-work) | Reasoning effort is a per-role knob, defaulted from the shape of the work | Accepted | 2026-08-16 |
| [DD-177](#dd-177-the-alignment-answer-is-shape-constrained-so-a-column-cannot-be-skipped) | The alignment answer is shape-constrained, so a column cannot be skipped | Accepted | 2026-08-16 |
| [DD-178](#dd-178-an-ai-generated-artifact-states-its-own-provenance-and-review-status) | An AI-generated artifact states its own provenance and review status | Accepted | 2026-08-16 |
| [DD-179](#dd-179-alignment-sees-the-tables-role-structure-and-the-mapping-is-checked-as-a-set) | Alignment sees the table's role structure, and the mapping is checked as a set | Accepted | 2026-08-16 |
| [DD-180](#dd-180-an-unanchored-table-is-reported-gated-and-told-where-its-class-lives) | An unanchored table is reported, gated, and told where its class lives | Accepted | 2026-08-16 |
| [DD-181](#dd-181-a-declared-cross-domain-bridge-makes-a-class-anchorable-by-default) | A declared cross-domain bridge makes a class anchorable, by default | Accepted | 2026-08-16 |
| [DD-182](#dd-182-per-table-vocabulary-is-a-projection-of-the-aggregate-not-a-second-derivation) | Per-table vocabulary is a projection of the aggregate, not a second derivation | Accepted | 2026-08-16 |
| [DD-183](#dd-183-affinity-resolves-the-hubs-accelerator-instead-of-scanning-the-whole-tree) | Affinity resolves the hub's accelerator instead of scanning the whole tree | Accepted | 2026-08-16 |
| [DD-184](#dd-184-llm-calls-are-traced-to-langfuse-opt-in-with-source-values-masked) | LLM calls are traced to Langfuse, opt-in, with source values masked | Accepted | 2026-08-16 |
| [DD-185](#dd-185-tables-are-anchored-globally-in-one-call-before-per-table-alignment) | Tables are anchored globally, in one call, before per-table alignment | Accepted | 2026-08-16 |
| [DD-186](#dd-186-the-gap-gate-is-drafted-grouped-by-domain-scoped-family-and-still-decided-by-a-human) | The gap gate is drafted, grouped by domain-scoped family, and still decided by a human | Accepted | 2026-08-16 |
| [DD-187](#dd-187-domain-design-runs-as-a-fleet-and-every-refusal-is-recorded-in-the-file-it-belongs-to) | Domain design runs as a fleet, and every refusal is recorded in the file it belongs to | Accepted | 2026-08-17 |
| [DD-188](#dd-188-ontology-semantics-live-in-the-reference-models-never-in-the-toolkit) | Ontology semantics live in the reference models, never in the toolkit | Accepted | 2026-08-17 |
| [DD-189](#dd-189-sources-are-profiled-deterministically-before-any-model-call) | Sources are profiled deterministically before any model call | Accepted | 2026-08-19 |
| [DD-190](#dd-190-the-anchors-artifact-is-a-reviewable-design-sheet-with-sticky-human-decisions) | The anchors artifact is a reviewable design sheet with sticky human decisions | Accepted | 2026-08-19 |
| [DD-191](#dd-191-first-draft-bindings-are-generated-from-the-design-sheet-and-validated-before-they-exist) | First-draft bindings are generated from the design sheet and validated before they exist | Accepted | 2026-08-19 |
| [DD-192](#dd-192-human-design-rulings-are-durable-transferable-and-outrank-model-judgment) | Human design rulings are durable, transferable, and outrank model judgment | Accepted | 2026-08-19 |
| [DD-193](#dd-193-the-profiling-class-catalog-is-scoped-to-the-resolved-accelerator) | The profiling class catalog is scoped to the resolved accelerator | Accepted | 2026-08-19 |
| [DD-194](#dd-194-temporal-columns-are-excluded-from-profiling-key-set-candidacy) | Temporal columns are excluded from profiling key-set candidacy | Accepted | 2026-08-19 |
| [DD-195](#dd-195-the-scaffold-offers-every-extra-the-toolkit-ships-including-langfuse) | The scaffold offers every extra the toolkit ships, including langfuse | Accepted | 2026-08-19 |
| [DD-196](#dd-196-archived-reference-model-snapshots-are-excluded-from-resolution-unconditionally) | Archived reference-model snapshots are excluded from resolution unconditionally | Accepted | 2026-08-19 |
| [DD-197](#dd-197---max-workers-gets-a-hub-level-default-in-the-same-place-accelerator-and-channel-already-live) | --max-workers gets a hub-level default, in the same place accelerator and channel already live | Accepted | 2026-08-19 |
| [DD-198](#dd-198-ai-preflight-surfaces-a-missing-sdk-as-a-missing-dependency-with-a-uv-native-fix-not-as-network-unreachability) | AI preflight surfaces a missing SDK as a missing dependency, with a uv-native fix, not as network unreachability | Accepted | 2026-08-20 |
| [DD-199](#dd-199-per-pr-ci-only-gates-on-the-prs-own-diff-global-state-checks-move-to-a-schedule) | Per-PR CI only gates on the PR's own diff; global-state checks move to a schedule | Accepted | 2026-08-20 |
| [DD-200](#dd-200-update---upgrade-also-upgrades-reference-models-resolved-the-same-way-scaffolding-is) | `update --upgrade` also upgrades reference models, resolved the same way scaffolding is | Accepted | 2026-08-20 |
| [DD-201](#dd-201-a-cross-domain-class-name-collision-is-resolved-by-richness-and-the-resolution-travels-downstream-as-a-uri) | A cross-domain class-name collision is resolved by richness, and the resolution travels downstream as a URI | Accepted | 2026-08-20 |

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

**Status:** ~~Superseded by [DD-106](#dd-106-immutable-bronze-and-mandatory-logical-source-preparation)~~
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
**Affects:** `projections/shared.py`, all three medallion projectors, `kairos-ext.ttl`
**Implementation:** `classify_foreign_keys()` / `ForeignKeyDescriptor` in
`src/kairos_ontology/core/projections/shared.py`

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

The OWL direction, qualification signals, redirection, authored physical column
names, nullability, and holder/target class endpoints are normalized once into
an immutable internal FK descriptor. Silver DDL, dbt Silver, and Gold consume
that descriptor rather than independently interpreting the annotations. Each
layer still applies its existing physical key type and naming rules.

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
- **No separate gold annotation is required** — Gold consumes the same normalized
  relationship while retaining Gold-specific dimension-key naming and types.

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

**Status:** ~~Superseded by [DD-109](#dd-109-temporal-execution-canonical-hashing-and-fk-resolution)~~
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

### Amendment — v5 conformance branches (issue #284)

The v5 compiler (`merge_bound_sources`) emits one branch per conformance contributor and
always uses the full `{entity}__from_{source}__{table}` form — it does not apply the
conditional-suffix rule above, because every member of a conformance group targets the same
entity and so would always collide.

A contributor sourced from a contracted dbt model (`source.dbtModel`) names its branch
`{entity}__from_dbt__{dbt_model_name}`: `dbt` is that relation's system label and the model
name is its table name, matching the `dbt:<name>` source identity used by conformance
validation and the `('dbt', '<model>', ...)` inputs to `_source_record_key`. Consequently
`_source_system` is `'dbt'` for all such branches — constant by design, exactly as two
tables from one `crm` system share `'crm'`; `_source_record_key` carries the discriminating
model name.

The failure this section originally described recurred in the v5 kernel because these fields
were blanked for dbt-model sources, so every branch collapsed onto one name. Duplicate branch
names are now a hard error rather than a silent last-write-wins.

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

A consistency review (`docs/archive/extension-vocabulary-review-2026-05-30.md`) found
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

### Amendment (2026-08-14): the location, not the mechanism, is superseded by DD-152 (proposed)

DD-152 proposes fetching reference models into a shared, versioned, per-user cache
(`%LOCALAPPDATA%\kairos\rm\<version>\`, XDG equivalent elsewhere) instead of committing them into the
hub. It reverses **where** the files live and nothing else. Precisely:

**Still holds, unchanged.** Git submodules stay gone permanently — no `.gitmodules`, no
`submodules: true`, no recursive checkout, and no second update path. `update-refmodels` remains the
single way to refresh reference models, and its implementation
(`_fetch_reference_models`: sparse shallow clone → validate → swap into place) is reused verbatim by
DD-152, including the clone-root `VERSION` copy and `FETCH_PROVENANCE.json`. The migration note above
("existing hubs must remove their submodule…") is still correct for any hub still carrying one. The
Copilot/agent-can-read-the-models property is also preserved — DD-152 keeps the models resolvable
through the catalog, just from outside the workspace.

**Superseded by DD-152.** Only the Decision's destination — "committed directly into
`ontology-reference-models/` as regular files" — and the two statements that follow from it: the
accepted consequence *"hub repo size slightly increases"* (at 17.5 MB / 560 files per hub, permanently
in history, this proved not to be slight) and the rationale bullet *"files are version-controlled in
the hub repo — easy to diff/track changes"*, which DD-152 explicitly gives up and replaces with a
committed version pin plus a reference-models stamp in the DD-047 inventory envelope.

**Not invalidated.** DD-152 adds the cache as the **last** entry in `resolve_refmodels_root`'s existing
precedence chain (explicit flag → `KAIROS_REFMODELS_ROOT` → sibling/hub-relative folder scan → cache).
A hub with `ontology-reference-models/` on disk keeps resolving from it exactly as DD-036 specifies. The
vendored layout therefore ceases to be the *default*; it does not become unsupported, and migration is
opt-in per hub.

**Status of this amendment.** DD-152 is `Proposed` and was never implemented. DD-158 (Accepted,
2026-08-15) supersedes DD-152 and takes the package approach DD-152 rejected. Under DD-158,
reference models resolve from an installed Python package (`kairos-ontology-referencemodels`);
the vendored `ontology-reference-models/` directory, the sparse-clone fetch, and the
folder-scan fallback are removed entirely (no backward compatibility). DD-036's destination
("committed directly into `ontology-reference-models/`") is therefore superseded by DD-158
in the same way DD-152 proposed. Until hubs migrate to the package, DD-036 is in force.

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

**Status:** ~~Superseded by [DD-106](#dd-106-immutable-bronze-and-mandatory-logical-source-preparation)~~
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

### Amendment (2026-08-15): schema YAML v1.2 splits cardinality from window (#422, DD-156)

The v1.1 fields above gave `row_count` two meanings — full-table `COUNT(*)` on
the warehouse extraction path, capped-read window size on the flatfile path.
Schema YAML **v1.2** splits them: `row_count` = true table cardinality only
(omitted when unknown), new `rows_sampled` = profiling-window size, and
`kairos-bronze:rowCount` is emitted only for real cardinality (with new
`kairos-bronze:rowsSampled` / `kairos-bronze:distinctScope` carrying the window
evidence). The enum-detection rule in item 5 now additionally requires the
evidence to be exhaustive (`distinctScope = table`). See DD-156.

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
**Date:** 2026-06-04 (updated 2026-07-18)
**Affects:** `analyse_sources.py`, `coverage_report.py`, `ai_provider.py`, CLI,
`kairos-design-source` and `kairos-design-domain` skills
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
- Configurable via `KAIROS_AI_PROVIDER=github|azure|foundry` env var
- GitHub Models: `GITHUB_TOKEN` + `https://models.inference.ai.azure.com`
- Azure AI Foundry: `AZURE_AI_ENDPOINT` + `AZURE_AI_KEY` or
  `DefaultAzureCredential`
- Microsoft Foundry: `AZURE_FOUNDRY_ENDPOINT` + `DefaultAzureCredential`
- Both return OpenAI-compatible client (same SDK)

At the beginning of every `kairos-design-source` invocation, the skill asks the
user to select the provider and authentication mode for that invocation. Existing
`.env` configuration is summarized without exposing values and, when complete,
is the recommended default; the user still confirms it before the first LLM call.
The override choices include GitHub Models, Azure AI with a key, Azure AI with
Azure identity, Microsoft Foundry with Azure identity, or skipping AI analysis.
The skill must not silently fall back to another configured provider or
credential mode.

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
- Provider/authentication consent is invocation-scoped and recorded without secrets
  in the source phase log.
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

### Amendment (2026-08-14): read-only sources that change wholesale (DD-152, proposed)

Under DD-152 reference models resolve from a shared, versioned, out-of-repo cache. Source ontologies
become **read-only** and stop changing file-by-file: they change **wholesale**, at the moment a hub
resolves a different reference-models version. The mechanism of this gate survives that intact; its
classification guidance and its remedy do not.

**Unchanged.** `compute_source_hash` and the `source_sha256` envelope field are indifferent to where the
source lives — bytes are bytes, and a cache path hashes exactly like a repo path. The `ok`/`stale`
distinction, the deterministic content-hash-not-mtime rationale, `--strict`/`--warn-only`, and the
non-zero exit on missing/stale all stand.

**`stale` changes cause and remedy.** Under vendoring, `stale` meant "a source TTL in this repo was
edited or refreshed", and the Decision's step 4 remedy — regenerate the inventory and commit it —
addressed one or a few files. Under DD-152 nothing edits a source in place; instead **every** inventory
reclassifies to `stale` simultaneously the first time a hub runs against a new cached version. The
`design-domain` Step 0c.1b 🚦 gate must say this, or a routine reference-models bump reads to an operator
(and to an LLM) as N independent failures rather than one expected upgrade step. The remedy is a
deliberate bulk regeneration performed *as part of* the version upgrade, and it is the inventories that
get committed — the sources no longer can be.

**`unverifiable` must not absorb resolution failures.** It means exactly one thing: a pre-DD-047
inventory with no stored hash. It must never be reached because a source could not be *found*. A source
that the cache or catalog fails to resolve is a resolution failure and must surface as one (a
`missing_import`/resolver diagnostic), because `unverifiable` only warns and `--strict` is the sole thing
that escalates it — classifying an unresolvable source as `unverifiable` would convert DD-152's principal
hazard, silent partial closure resolution, into a warning nobody reads. `check_inventories` should be
explicit that an unresolvable source root is a hard error, not a classification.

**`orphan` gains a second legitimate cause.** An inventory with no source now also occurs when the newly
resolved reference-models version no longer publishes that module. Still warn rather than block, but the
message should distinguish "the source was removed from this hub" from "the upstream version dropped it",
since the second is normal during an upgrade and the first is not.

**Addition: stamp the reference-models identity in the envelope.** `generate_inventory()` should record
the reference-models identity it was generated against — the resolved version/ref, and the commit from
`FETCH_PROVENANCE.json` where available — alongside `source_sha256`. Optional and additive, `None` for
graph-sourced inventories, and safe on the same compatibility argument `source_sha256` itself relied on
(existing readers ignore unknown keys). It buys two things: `check-inventory` can report "40 inventories
are stale because this hub moved from v1.15.0 to v1.16.0" instead of 40 unexplained hash mismatches, and
— once the models are no longer committed — the envelope becomes the **only durable record in the hub of
which reference-model bytes the model was authored against**. The stamp must not participate in inventory
filenames or in `_closure_hash` inputs; DD-152's additive-only overlay requirement exists precisely so
those stay byte-stable across the move, and an envelope field that fed either would defeat it.

**Still true.** The pass/fail decision remains code-level and deterministic, and a truly blocking gate
still depends on the operator, agent or CI pipeline actually invoking `check-inventory`.

**Status of this amendment.** DD-152 is `Proposed`; none of the above applies until it is Accepted.

### Amendment (2026-08-14): the `unbuildable` classification, and why it deliberately weakens a gate

This gate had no bucket for *"this source cannot be built at all"*. A source whose closure fails to resolve
was collapsed into one of two existing buckets, both **blocking**: into `missing`, because
`_source_has_classes` deliberately returned `True` when it could not parse a file ("treat as having classes
so the check surfaces it"), or into `stale`, when regeneration raised during the freshness comparison. Both
are indistinguishable from *"you forgot to regenerate"*.

That mattered because `check-inventory`'s remediation names exactly one command — `generate-inventory` — and
for these sources that command **cannot help**. The user is told to run a fix that reports success and clears
nothing, so the pair `check-inventory` → `generate-inventory` → `check-inventory` never converges (#405).
The reporter was accurate about severity and wrong about cause.

**Decision.** Add an `unbuildable` classification: a source that was enumerated but cannot be parsed or have
its closure resolved. It is **non-blocking by default and `--strict`-eligible**, exactly mirroring
`unverifiable`, and `check-inventory` selects a third remediation message naming the real remedy — fix the
source TTL — rather than the generic one.

**This is a deliberate weakening of a gate, and the rationale is ownership, not convenience.**
`iter_reference_inventory_sources` enumerates the **vendored** reference-models tree. A hub author cannot fix
an unparseable TTL in there, and a gate that blocks on it blocks every hub that resolves that version, with
no available remedy. That is the same reasoning already recorded for `catalog-test` — fail only for what the
hub author owns and can fix — and for `init`'s pre-generation loop, where a source TTL's failure "only
reduces coverage, never aborts". A hub that genuinely wants CI teeth escalates with `--strict`.

**What did not change.** `unverifiable` keeps its single meaning (a pre-DD-047 inventory with no stored hash)
and must not absorb build failures. Freshness still compares `closure_hash` only. Both `is_blocking`
properties explicitly exclude `unbuildable`; `has_warnings` includes it. `scope_inventory_report` and
`classify_domain_scope` compose it, so the domain-scoped check remains the authority for a given design and
an out-of-scope unbuildable source stays out of scope.

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
   the full file. ~~`row_count` reflects the rows actually read.~~ *(Amended
   2026-08-15, see below: `row_count` is now the true cardinality from the file
   metadata; the window is recorded as `rows_sampled`.)*
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

### Amendment (2026-08-15): `row_count` from file metadata, window as `rows_sampled` (#422, DD-156)

"`row_count` reflects the rows actually read" is struck. It made `row_count`
mean *window size* on this path while the warehouse path recorded a full-table
`COUNT(*)` under the same field name — the dual meaning DD-156 removes.
`read_parquet_table` now takes the true cardinality from
`ParquetFile.metadata.num_rows` (free — footer metadata, no body read; it also
fixes a latent undercount where only the **first** batch of a multi-row-group
file was reported) and records the profiling window separately as
`rows_sampled`. Everything derived from the read rows (nullability, distinct
counts, sample slicing) still uses the window size. The reading strategy —
sample-only, one batch, never the whole file — is unchanged.

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

### Amendment (2026-08-14): the collision was not loud, and `--prune` deleted good inventories

Two claims above did not hold in the implementation. Recording both, and what replaced them.

**"Aborts loudly on any residual same-name collision" was not true.** The generator printed a `❌ Inventory
name collision … Report this (DD-054 disambiguation gap)` line to stderr and then `continue`d, touching no
counter and no exit code — a `❌` in a command that exits 0. The colliding source was silently absent from
the run, and because the *checker* still enumerated it and compared against the winner's stored hash, the
losing key was reported **permanently `STALE`**: unfixable by any number of `generate-inventory` runs (#406).
A collision now routes to a real failure bucket and blocks, which is what this DD always claimed.

**The collision was not a two-file accident, and the root cause is here in the naming rule.** `_ref_model_id`
namespaces only paths containing a `derived-ontologies` segment, so a reference-model TTL outside that tree
falls through to bare `{stem}-inventory.yaml`. Every `blueprints/patterns/*/template.ttl` therefore collapses
to the same `template-inventory.yaml` — the collision scales with the pattern library. Those files are
copyable stubs carrying `https://example.org/` placeholder namespaces and deliberately no `owl:versionInfo`;
a semantic-index inventory of one has no consumer. They are now **excluded from inventory enumeration**, in
`iter_reference_inventory_sources` rather than at any call site, so generator and checker agree by
construction (the same reason the `archive/` exclusion lives there).

**`--prune` was a data-loss path, and the obvious guard would not have closed it.** Prune unlinked every
`*-inventory.yaml` absent from the set of files the run wrote. Two ways that set was wrongly incomplete:

1. a source that **failed** never entered it, so its previously-good committed inventory was deleted —
   turning a transient closure failure into a `missing` on the next check, i.e. the fix command destroyed the
   evidence that the source had ever been fine;
2. worse, **scope**: only *one* of the ontology / reference-model roots need resolve, so a run scoped to the
   hub alone reported **zero failures** and deleted every reference-model inventory, with no warning at all.

Because of (2), gating prune on "no failures this run" is insufficient — that path has no failures. Prune is
now defined by what the run could positively account for: it **hard-skips with an explanation** when either
scope root was unresolved, and otherwise reuses the checker's own orphan notion, which is built from the
sources it enumerated regardless of parse success. A source that merely fails is still *seen*, so it can
never be mistaken for orphaned.

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
- **Amended by DD-148**: the "recommendation, not a hard block" framing above is
  superseded once a hub has started modeling (or discovery ran under fleet mode with
  unresolved items) — `kairos-ontology compile`/`validate` now hard-fail in those cases.

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

### Amendment (2026-08-14): `status` becomes load-bearing, and content is linted

Three gaps in this design surfaced together during an unattended delivery run (#416, #417).

**`status` was documented and read nowhere.** The schema defines
`status: processed | partial | skipped`, and the design's whole posture is that partial coverage should be
recorded honestly rather than overstated. But no code read the field: `discovery-status` validated
`source_path` and `source_sha256` only, and printed one unqualified success line. On a real hub 23 of 56
records were legitimately `partial` — long documents where only decision-bearing sections were read — and
that judgment was invisible to every gate. The schema offered an honesty mechanism that nothing consumed.
`status` is now read and reported.

**The gate validated provenance, not content.** A record whose `strategy` and `summary` were literally
`TODO` with `extracted_terms: []`, but whose path and digest were correct, passed `discovery-status --strict`.
For interactive use that is minor; for an unattended run these records **are** the deliverable — the thing a
human is asked to trust instead of watching the run — and an empty stub was indistinguishable from real work.
Content is now linted, generalising the principle already established for the glossary TTL (DD-103 amendment,
#288): scaffold-provided or placeholder content is not authored evidence.

**Severity is deliberately asymmetric.** Extraction content findings **warn** and are `--strict`-eligible;
they never error. `partial` is an author's judgment with no automated remedy, and a hub carrying 23 honest
partials must not acquire 23 unclearable errors — the same advisory rationale recorded for `catalog-test`.
New findings route into a **separate** strict-eligible property rather than the existing work signal:
widening that would have made `--strict` unconvergeable on such a hub, recreating precisely the
non-converging loop that #405 reports, and would have counted already-processed documents as needing work.

**Duplicate documents are now detected.** The status check hashes each staged document, but never compared
digests *across* documents; 7 of 56 tracked documents on the same hub were byte-identical and were reported as
7 independent units of work. Duplicates are reported **additively** — a duplicate with no extraction record
still needs processing, so the work count is unchanged. Note the digest was previously computed only for
already-matched records, so this costs one full read per unmatched document; that cost is accepted knowingly.

**Consequence for `build-glossary`.** It read `extracted_terms` from every record regardless of `status`, so a
`skipped` record's terms landed in the company glossary. Harmless while `status` was inert; a contradiction the
moment it became load-bearing. `skipped` records are now excluded and the count surfaced; `partial` records are
still included, because partial coverage is coverage.

**Still open.** This DD names `kairos-design-discovery` (Phase 1 / Phase 4) as the producer of extraction
records, but no skill currently references `discovery-status`, `_extractions/`, or `build-glossary` at all —
the producer contract is undocumented in the place meant to produce it.

### Amendment (2026-07-22): recursive discovery + provenance-based matching

The original implementation scanned only the **top level** of
`.import/businessdiscovery/` (`iter_discovery_documents` used `Path.iterdir()`) and matched
each document to its extraction purely by a **basename-derived filename**. Documents placed
in subfolders were therefore invisible, and any extraction already written for a nested
source was reported as an **orphan** even though its `source_path`, `source_sha256`, and
schema were valid.

`discovery-status` now:

- discovers documents **recursively**, skipping READMEs and dotfiles at every depth and any
  file under a dot-prefixed directory, ordered by normalized source-relative POSIX path;
- treats a document's **normalized source-relative path** as its canonical identity and
  matches extractions primarily by normalized `source_path` provenance (tolerating the
  documented relative form, absolute paths, and Windows separators), falling back to the
  legacy basename filename and then the path-derived nested filename — so **existing records
  are preserved and never renamed**;
- assigns **collision-safe** filenames to *new* nested records
  (`{path-slug}-{sha1(rel)[:8]}.extraction.yaml`) so identical filenames in different folders
  and slug-colliding paths stay distinct while extraction files remain flat; and
- adds a **conflict** classification when more than one extraction claims the same source
  path.

`source_path` (not `source_file`) is authoritative for nested identity, and new records
should store the repository-relative form `.import/businessdiscovery/<nested/path>`.

---

## DD-061: Deterministic Source-Coverage Gates (check-alignment + check-source-coverage)

**Status:** Superseded by DD-094 on 2026-07-21
**Date:** 2026-06-13
**Affects:** `kairos-design-domain` skill (Step 0a.2), `kairos-design-silver` +
`kairos-execute-project` skills, `propose-alignment` output (alignment YAML
`schema_version` 1 → 2), two new read-only CLI commands
**Implementation:** `src/kairos_ontology/alignment_coverage.py`,
`src/kairos_ontology/source_coverage.py`, `check-alignment` +
`check-source-coverage` commands in `src/kairos_ontology/cli/main.py`,
`write_alignment_output` in `src/kairos_ontology/propose_alignment.py`

> **Supersession note:** DD-094 retires alignment YAML and makes the Claim
> Registry plus canonical completeness facts authoritative. The source-coverage
> intent survives in the current `check-claims` / `check-source-coverage` views;
> the alignment-YAML authority and `check-alignment` path described below are
> historical.

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
**Affects:** `src/kairos_ontology/core/_samples.py`,
`src/kairos_ontology/core/source_privacy.py`,
`src/kairos_ontology/core/import_flatfile.py`,
`src/kairos_ontology/core/extract_schema.py`,
`src/kairos_ontology/core/import_source.py`,
`src/kairos_ontology/core/propose_alignment.py`, `src/kairos_ontology/cli/main.py`,
`src/kairos_ontology/validator.py`, `.github/skills/kairos-design-mapping/SKILL.md`
**Implementation:** `_samples.py` (`is_pii_column`, `value_is_pii_shaped`,
`mask_value`, `example_values`, opaque persistence redaction);
`source-privacy [--fix]`; `ColumnAlignment.example_values` /
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
- **Persisted samples use opaque typed redaction, not display masking.** Before
  source YAML or Bronze RDF is written, a detected value is replaced as a whole
  with a token such as
  `<redacted kind=email source=contacts.email datatype=varchar(255)>`. The token
  retains source context but no original characters and no hash. Detection is
  recursive for row/JSON values and idempotent for existing tokens.
- **Supported residual findings block publication.** Source writers sanitize before
  persistence and verify that no supported raw pattern remains. Existing artifacts
  are checked or deterministically rewritten with `source-privacy --fix`; reports
  identify only path/table/column/kind/count.
- **`transform_compat`** is an advisory note (`"N/M sample values are non-numeric
  — CAST may NULL/fail"`) emitted only for numeric/bool CAST targets. It never
  raises confidence, never auto-sets review, and never blocks.
- **No `schema_version` bump.** Both fields are additive and emitted only when
  populated, so existing v2 alignment files and the freshness gate are unaffected.

### Rationale

Real values disambiguate mappings far better than names/types alone and let the
modeler catch encoding traps before writing SQL. Forcing the feature on (vs.
opt-in) maximises that value; masking PII unconditionally keeps the committed
artifacts safe. Persist-time opaque redaction closes the earlier gap where raw
sample values could enter version control before display masking.
Keeping `transform_compat` advisory respects the toolkit's warning-tolerant,
human-confirmed mapping flow.

### Consequences

- `propose-alignment` output now contains masked example values by default;
  `--no-sample-values` / `include_sample_values=False` suppresses them.
- The Examples column is for transient display only — skills must never copy raw
  values into committed TTL/comments/session logs.
- New source artifacts persist supported detected patterns only as opaque,
  source-aware tokens. Non-PII examples remain available as semantic evidence.
- Existing generated YAML and vocabulary TTL can be remediated with the
  deterministic, value-free `source-privacy --fix` workflow.
- Detection is deliberately bounded to supported patterns and PII-related column
  names; this policy does not claim universal discovery of sensitive information.

### Amendment (2026-08-14): the bound must be stated in the output, not only here

The consequence above — "does not claim universal discovery" — was recorded in this document and **not** in
the command. `source-privacy` printed `✅ Source sample artifacts are privacy-safe for supported patterns.`,
which names no patterns, so a reader could not tell which ones. The concrete case that surfaced it (#415): a
road-haulage export where three address components were correctly redacted while `CoordinateLatitude` /
`CoordinateLongitude` persisted at six decimal places (~0.1 m) in the same row — the address recoverable by
reverse-geocoding the two columns beside it, under an unqualified all-clear.

**Decision.** A clean result now states its coverage: the number of artifacts scanned, the redaction kinds
actually looked for, and the known gap. The kind list is **derived from the detectors** (`DETECTED_PII_KINDS`,
built from the same table `_kind_from_name` iterates) rather than maintained beside them, because a
hand-written coverage list would eventually claim detection the code does not have — which is the failure this
amendment exists to prevent, one level up.

**The detector itself is deliberately deferred** to #423, not skipped. Three separate mechanisms make the
obvious implementations wrong, and each is recorded there: blanket-redacting decimals would regress #302
(whose exemption is value-shape, not datatype — gating on datatype was explicitly rejected); a range-only rule
breaks existing fixtures, since `3.14159265358979` and `0.123456789` are both valid latitudes; and precision
reduction cannot work through `is_redaction_token`, the sole idempotence mechanism, without forcing a 2-decimal
threshold — roughly 1.1 km, which still identifies a rural facility. A privacy gate must be binary; "coarser"
is not "safe".

Stating the bound is therefore the honest interim: the guarantee is unchanged, but it is no longer
overstated at the point of use.

### Second amendment (2026-08-15): the deferred coordinate detector ships (#423)

The interim above ends: the persistence path now detects geographic coordinates by **pairing the column
name with the value shape**, which is what the three recorded wrong-fix mechanisms all lacked. The detector
never touches declared datatypes (the #302 exemption stays value-shape; the residual gate receives no
`column_types`, so a datatype-keyed rule would make the redactor and the gate disagree — the exact failure
`test_redacted_rows_pass_the_persistence_gate` pins), and it is binary: a matched value is replaced with an
opaque `<redacted kind=location …>` token, never coarsened.

**Shipped.**
- **Tokens** (full-word matches via `_name_tokens` only, never substrings): `latitude` → [-90, 90];
  `longitude`, `lng` → [-180, 180]; `coordinate(s)` or multiple location tokens → the union range
  [-180, 180], because a generic coordinate column can hold either axis.
- **Value shape**: a numeric literal whose **string form carries a fractional part**
  (`_NUMERIC_LITERAL_RE`'s fraction group — not `float.is_integer()`, which would exempt real coordinates
  like `51.0`) inside the applicable range; or a comma-separated `"lat,lon"` pair whose two parts both
  satisfy that rule within the union range (a common single-column export format that would otherwise
  silently escape).
- **Containment**: the check lives in `detect_sample_pii_kind` (persistence path), between the name-keyword
  and nested/text checks — name kinds keep priority (`health_latitude` stays `health`) and shaped values in
  location columns are still caught. It is **not** in `_kind_from_name`, so `is_pii_column` and the
  display/suggestion paths (`propose_alignment`, `suggest_shapes`) gain no location awareness; tests pin
  `is_pii_column("latitude")` False. Nested `{"latitude": 51.33}` values are detected because
  `_kind_from_nested`'s dict branch now routes through `detect_sample_pii_kind`, which also makes the
  redactor and every residual gate provably share one classifier.
- `"location"` enters `DETECTED_PII_KINDS` derived from the token table (`_LOCATION_TOKEN_RANGES`), never
  hand-appended — the same discipline the first amendment established for the coverage report.

**Deferred.**
- The abbreviations `lat`, `lon`, `geo`: as bare tokens they false-positive on `latency`/`geo_score`-class
  names once range-filtered values appear beside them; they move to the sibling-address follow-on of #423
  (which can use row context to disambiguate).
- WKT geometries (`POINT(4.12 51.33)`) and other structured spatial encodings.

`SAMPLE_PRIVACY_VERSION` bumps "1" → "2" as **inert bookkeeping** — nothing reads it back and no migration
keys on it; it only records which policy generated an artifact. Existing hubs therefore keep persisted
coordinates until `source-privacy --fix` is run once.

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
  *(Amended 2026-08-15, see below: distinctCount alone is NOT the signal — it
  must carry `distinctScope="table"`.)*

### Amendment (2026-08-15): `sh:in` requires full-table distinct evidence (#424, DD-156)

"distinctCount is the reliability signal for enums" is falsified for windowed
profiling. On a real hub, 82% of 217 generated `sh:in` enums were single-value
and several were provably wrong (`booking_status` → only `"TO_REQUEST"` of 5
real values): the flatfile path counted distincts inside an n≤1000 (and
sample-persisted n=5) window, and `suggest-shapes` treated that as population
truth. DD-156 gives the graph the evidence to tell the difference; this
amendment makes `suggest-shapes` read it:

- **distinctCount is trusted for `sh:in` only when the table asserts
  `kairos-bronze:distinctScope="table"`.** Sample-scoped evidence
  (`distinctScope="sample"`) and legacy evidence (scope absent — vocabulary
  predates DD-156) produce **advisory comments only**, never a constraint:
  - saturated window (`distinctCount >= rowsSampled`): the evidence cannot
    distinguish an enum from an open value set;
  - window below the enum floor (`rowsSampled < DEFAULT_ENUM_MIN_ROWS` = 100):
    re-import with a larger `--max-rows` or profile the warehouse table;
  - unsaturated ≥100-row window with `distinctCount ≤ --enum-distinct-max`:
    "possible enum … not verified against full data";
  - legacy (scope absent, distinctCount present): "regenerate the source
    vocabulary with import-source".
- **Temporal (`xsd:date`/`dateTime`/`time`), decimal/float/double, boolean, and
  UUID columns are never enumerated**, regardless of scope. Boolean `sh:in`
  adds nothing over `sh:datatype` and brittle lexical forms cause false
  violations; UUID detection uses `kairos-bronze:formatHint == "uuid"` OR the
  sample-derived format pattern — load-bearing because SQL Server
  `uniqueidentifier` maps to `xsd:string`. Integer stays eligible (integer
  status codes are legitimate enums). These columns get no enum comment either
  (`sh:datatype` already carries the signal).
- **Floor rule, precedence pinned:** when the table's true cardinality
  (`kairos-bronze:rowCount`) is KNOWN, `sh:in` additionally requires
  `rowCount >= DEFAULT_ENUM_MIN_ROWS` (100, shared with `enrich_vocabulary`).
  When `rowCount` is absent but `distinctScope="table"` is explicitly asserted
  (warehouse-shaped evidence), the floor does NOT apply — the scope assertion
  itself is the trust anchor.
- Unchanged: PII columns are never enumerated; `sh:in` still requires
  `0 < distinctCount ≤ --enum-distinct-max` and the ≤5 persisted samples to
  cover the full distinct set (the values come from the samples).

Consequence for existing hubs: legacy vocabularies produce advisories instead
of enums until regenerated (`import-flatfile` + `import-source`); capped
flatfile imports never produce `sh:in`. The suggestions this suppresses are
exactly the ones the old rule fabricated.

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

## DD-080: Two-layer lifecycle state, deterministic `status` CLI, and the `kairos-flow` single entry point

**Status:** Accepted
**Date:** 2026-06-20
**Affects:** `src/kairos_ontology/status.py`, `cli/main.py` (`status` command),
`.github/skills/kairos-flow/`, `.github/skills/kairos-diagnose-status/`, scaffold
skills, `kairos-help`, methodology doc §21
**Implementation:** `src/kairos_ontology/status.py` (scanner),
`status` CLI command, `kairos-flow` skill (state owner + orchestrator)

### Context

Each design phase was a separate skill with its own bespoke pre-flight and its own
ad-hoc `.sessions-design/{phase}-{name}-{date}.md` log. There was no single formal
status overview, no resumable per-step state that captured open questions, and no
single "start" instruction. Status was re-derived by LLM scanning in
`kairos-diagnose-status`, which is non-deterministic and not authoritative.

### Decision

Split lifecycle state into **two layers**:

1. **Objective** — derived deterministically from committed artifacts by a new
   read-only, AI-free CLI `kairos-ontology status` (module `status.py`). It emits
   per-phase / per-instance `not-started | in-progress | done`. Exempt from the
   skill-gate (like `check-alignment`). `kairos-diagnose-status` becomes a thin
   wrapper that runs it and enriches the result.
2. **Continuation** — an **OKF v0.1** markdown bundle at
   `ontology-hub/.kairos-state/` (`status.md` with scan/continuation/phase-index
   regions + per-instance `phases/<phase>/<instance>.md` logs with an Open
   Questions resume anchor). OKF is used purely as a storage convention.

A new **`kairos-flow`** skill is the single entry point: it runs the scan, loads
and reconciles the continuation state, presents the overview, offers clean-start
vs continue, and **hands off** to the correct phase skill (interactive-only).
`kairos-flow` is the only writer of `status.md`; phase skills only read state and
append a "state update proposal" to their own instance log.

### Rationale

A persisted hand-maintained status file risks drifting from the real artifacts, so
objective facts are computed deterministically and the markdown layer is confined
to intent/open-questions. Centralizing `status.md` writes in `kairos-flow` (rather
than a write-contract spread across eight prose skills) avoids reliance on
distributed LLM obedience. Per-instance logs match the real cardinality of source/
mapping/silver/gold work. Clean-hub assumption: no `.sessions-design/` migration —
`.kairos-state/` is the only state system going forward.

### Consequences

- New deterministic CLI `kairos-ontology status` (+ unit tests on the acme-hub
  scenario) is the authoritative objective backbone.
- New `kairos-flow` skill is the recommended starting point ("start / where are we
  / continue"); `kairos-help` and the routing table point to it.
- Phase skills gain a lightweight read-state + state-proposal contract (rolled out
  incrementally); they stop writing new `.sessions-design/` logs.
- Reconciliation rules are explicit (scan wins for facts; continuation wins for
  intent).

### Addendum (2026-07-21): Machine-readable per-instance facts + schema versioning (DD-101)

**Affects:** `src/kairos_ontology/core/status.py`, `src/kairos_ontology/core/binding_analysis.py`.

`status.py`'s objective scan stayed limited to a `not-started|in-progress|done`
triad; consumers that needed finer machine-readable state (claim `proposed`/
`approved` counts, Silver `bound`/`aspirational` classes, validation pass/fail)
had to re-derive it themselves (e.g. `kairos-diagnose-status`'s hand-rolled
aspirational-vs-bound section). `InstanceStatus` gains an additive `facts: dict`
bag, populated only where objectively knowable from committed authorities:

- **claims** — `{"proposed": N, "approved": N}`, a raw count of the registry's own
  `status` field (no governance rule re-derived; `check-claims` remains the
  authority for bucket/blocking semantics).
- **silver** — `{"bound_classes": [...], "aspirational_classes": [...],
  "release_eligible": bool}`, from the same canonical
  `binding_analysis.BindingAnalysis` snapshot the state/detail computation already
  used (D4) — one computation, not two.
- **validate** — `{"data_valid": bool}` when the persisted
  `validation-report.json` has recognizable `{section: {"failed": int}}` counts;
  omitted (not guessed) otherwise.

The shared "load hub authorities and build a `BindingAnalysis`" logic previously
inlined in `status._domain_aspirational_stubs` is now the canonical
`binding_analysis.analyze_domain_from_hub(hub_root, domain)`, reused by both the
scan and the new DD-101 lifecycle gate; `_domain_aspirational_stubs` is now a
thin, behavior-preserving wrapper (same signature, same return value, still
directly unit-tested). `HubStatus.to_dict()` gains `"schema_version": 2`
(v1 had neither the version key nor `facts`); every v1 key is unchanged, so v1
consumers keep working — only additive keys were introduced, hence no
backward-compatibility break.

---

## DD-081: `analyse-sources --domains` is an output filter, not a candidate restriction

**Status:** Accepted
**Date:** 2026-06-20
**Affects:** `src/kairos_ontology/analyse_sources.py`, `cli/main.py`
(`analyse-sources`), `kairos-design-source` skill
**Implementation:** `run_analyse_sources` (remove candidate prune; add
`_filter_analysis_by_domain` post-classification); issue #189

### Context

`--domains` pruned the LLM **candidate** domain set *before* classification. Because
each source table is classified in a single call against all candidates and must pick
one primary domain, restricting candidates to e.g. `party` forced every table into
`party` or `unclassified`. This produced false modeling evidence (cargo/vessel/route
tables labelled `party`) and inflated downstream `check-claims --domains party` counts.

### Decision

Treat `--domains` as a **post-classification output focus**:

- Always classify every table against the **full** accelerator/reference domain set so
  each table gets its true primary domain.
- After classification, write only the tables whose **primary** domain matches
  `--domains` (substring match), in each per-system `*-affinity.yaml` and the matrix.
  Secondary domains are deliberately ignored, matching downstream coverage bucketing
  (`alignment_coverage.load_affinity_domain_tables`, which keys on primary `domain`).
- A system with zero matching tables writes an empty (`schema_version: 2`, `tables: []`)
  report instead of raising.
- `--max-domains` still truncates the candidate set (rate-limit guard) but now emits a
  warning that classification may be biased; it is unsuitable for modeling evidence.

### Consequences

- Fixes the evidence pollution at the source; no change needed in `check-claims` /
  coverage (they already bucket by primary domain).
- The per-table cache key includes the candidate signature, so switching between
  filtered and unfiltered runs does not reuse stale (candidate-pruned) classifications.
- Behaviour change: scripts relying on the old exclusive-candidate semantics now get
  full-set classification with a focused output (the correct evidence).

---

## DD-082: Claim-curation ergonomics: `decide-claims`, URI back-fill, skeleton bootstrap, intra-hub imports (issue #190)

**Status:** Accepted
**Date:** 2026-06-20
**Affects:** `src/kairos_ontology/decide_claims.py` (new),
`claim_projection_sync.py`, `migrate_claims.py`, `cli/main.py`,
`kairos-design-domain` skill
**Implementation:** issue #190 (items 1–5, 7); item 6 split to issue #191

### Context

Curating `*-claims.yaml` and running `claims-to-silver-ext` on a real hub
(`cldn-ontology-hub`, party domain, 1183 claims) surfaced one hard blocker plus
several workflow-friction gaps:

1. Intra-hub shared bases (`_foundation.ttl`, `_master.ttl`) were flagged as
   `extra owl:imports` and stripped, because `_collect_hub_domain_bases` skipped
   every `_`-prefixed file.
2. There was no CLI to query or bulk-curate claim `status`/`disposition` — the
   skill told users to curate but provided no command, so they hand-edited YAML
   (producing huge, unreviewable diffs).
3. `migrate-claims` always left `class_uri`/`property_uri` empty, but the validator
   requires those URIs before an anchored claim can be approved.
4. `claims-to-silver-ext` silently refused to bootstrap a domain whose ontology /
   `*-silver-ext.ttl` files did not yet exist (it set `status.error` and wrote
   nothing).
5. The MDM-anchor warning gave no concrete example of how to satisfy it.

### Decision

Keep `*-claims.yaml` as the canonical, **git-tracked** source of truth — no
database (in-memory or on-disk). The runtime already loads the full registry into
memory; a DB would sacrifice git-diff governance (DD-094) without solving the real
gap, which is a missing **query + bulk-update API**. Address each item:

- **Intra-hub imports (item 1):** `_collect_hub_domain_bases` now treats any
  `owl:Ontology`-declaring `*.ttl` under `model/ontologies/` (including
  `_`-prefixed shared bases) as an allowed intra-hub base; it only skips
  `-ext.ttl` extension surfaces. Such imports are neither flagged nor stripped.
- **`decide-claims` (items 2/3):** new `decide_claims.py` provides a pure,
  AI-free query layer (`select_claims` with status/disposition/type/origin/id-glob/
  column-glob selectors) and a bulk-status mutator (`apply_decisions`) that honors
  `STATUS_TRANSITIONS` and reports skipped/invalid transitions. The CLI writes back
  through the existing canonical `write_registry` (deterministic `safe_dump`,
  `width=100`), so curation diffs stay minimal — no new serializer needed (item 3
  was solved by routing through the existing one).
- **URI back-fill (item 4):** `migrate-claims` loads the reference-model inventory
  and resolves `class_uri`/`property_uri` at claim-creation time. Ambiguous names
  (same name → multiple URIs) stay null rather than guessing; resolved/unresolved
  counts are printed. `--no-resolve-uris` is an escape hatch.
- **Skeleton bootstrap (item 5):** `claims-to-silver-ext` scaffolds a minimal valid
  `owl:Ontology` skeleton (with provenance header and inferred hub base / foundation
  import) for any missing ontology or `*-silver-ext.ttl`, then proceeds with the
  normal sync. `--no-scaffold` disables it.
- **MDM-anchor warning (item 7):** the warning now prints a concrete
  `mdm_anchor: true` reference_data claim example and points to the skill /
  `--no-mdm-anchor`.

### Consequences

- Shared foundation/master bases survive projection sync; multi-domain hubs no
  longer lose their intra-hub imports.
- Claim curation is a reviewable, scriptable CLI flow with minimal diffs.
- Anchored claims migrated from alignment can be approved without manual URI lookup.
- A fresh domain can be bootstrapped end-to-end from claims alone.
- **Out of scope:** the destructive whole-graph rdflib rewrite of projection
  surfaces (item 6) is tracked separately as **issue #191**; the scaffolded
  provenance header can still be stripped by that rewrite when approved imported
  claims exist, which #191 will address.

---

## DD-083: `claims-to-silver-ext` preserves authored TTL via a managed block (issue #191)

**Status:** Accepted
**Date:** 2026-06-20
**Affects:** `src/kairos_ontology/claim_projection_sync.py`,
`kairos-design-domain` skill
**Implementation:** issue #191 (split from #190 item 6); supersedes the
whole-graph rewrite

### Context

`_rewrite_domain_projection_surfaces` synced the managed `owl:imports` /
`kairos-ext:silverInclude` surfaces by re-serializing the **whole** rdflib graph
(`graph.serialize(destination=…)`). But `model/ontologies/{domain}.ttl` and
`{domain}-silver-ext.ttl` are also **hand-authored** (local subclasses, gap
properties, prefix layout, the DD-072 provenance header). Every sync therefore
stripped comments/header, collapsed prefixes, and reordered triples — one file was
simultaneously tool-owned and human-owned, written by a destructive whole-graph
re-serialize. (This was also the root of the DD-082 item-5 limitation: a scaffolded
provenance header was stripped on the first sync that had approved imported claims.)

Two options from the issue were rejected after auditing the loader:

- **Split into a generated `{domain}-imports.ttl` the authored file imports** —
  the projection loader follows `owl:imports` **direct-only, no transitive walk**
  (`catalog_utils.load_graph_with_catalog`; the no-catalog path follows none), and
  extension discovery is a fixed `*-silver-ext.ttl` glob (`projector._discover_extensions`).
  A generated intermediate import file would not resolve, and a separate includes
  file would not be discovered, without broad loader/discovery/sync changes.
- **Surgical rdflib writer** — rdflib preserves no formatting, degenerating into a
  fragile full-Turtle text patcher.

### Decision

Introduce a **block-delimited managed region**. The tool owns only the triples
between sentinel-comment markers; everything else is authored content preserved
verbatim:

```turtle
# >>> kairos-managed (generated from the Claim Registry — do not edit)
<https://acme.com/ont/party> <http://www.w3.org/2002/07/owl#imports> <https://refmodel.example/ontology/party> .
# <<< kairos-managed
```

- The managed block is regenerated **wholesale as text** with **full URIs** (so it
  is independent of the authored prefix declarations) and appended at the end of
  the file. `_strip_managed_block` removes the prior block; `_compose_managed_file`
  re-stitches authored text + fresh block.
- **No loader/discovery/semantic change.** The file keeps its name and structure;
  rdflib ignores the marker comments on parse, so both the projector and
  `check-claims` (`evaluate_domain_projection_sync`) read it exactly as before.
  `owl:imports` stays directly on the ontology subject (no transitivity needed).
- **Managed vs authored split:** external (non-hub-base) `owl:imports` and imported
  (non-local) `silverInclude` plus the forbidden `silverIncludeImports` bulk flag are
  managed; intra-hub `_foundation`/`_master` imports and local-class `silverInclude`
  stay authored.
- **Steady state is byte-stable** outside the block (idempotent). **Historical legacy
  migration (superseded by DD-100):** the original implementation stripped inline
  managed triples during first sync. Current releases require the explicit,
  backed-up `migrate` conversion instead.

### Consequences

- `claims-to-silver-ext` no longer destroys provenance headers, comments, prefix
  layout, or triple ordering; managed import/include sync is unchanged and still
  enforced by `check-claims`.
- Closes the DD-082 item-5 limitation — a scaffolded header now survives the first
  and subsequent syncs.
- Repeated syncs are idempotent (no marker accumulation).

---

## DD-084: Deterministic address relationship candidates surfaced as advisory metadata (issue #192)

> **Superseded in part by DD-188 (2026-08-17).** The detector described here survives, but its vocabulary no longer lives in the toolkit: the address part
> kinds, role qualifiers and weak/context rules now come from the accelerator pack's `client-hub-blueprint/entity-projections.yaml`, and the six
> `_ADDRESS_*` constants have been deleted. The candidate shape below is also out of date — it is now `type: entity_projection_candidate` with
> `projection_id`, `part_kinds`, and a resolved `target_class_uri` / `target_resolved` (the Phase A2 deferral noted below is closed). See DD-188.

**Status:** Accepted
**Date:** 2026-06-20
**Affects:** `src/kairos_ontology/propose_alignment.py`,
`src/kairos_ontology/claim_registry.py`,
`src/kairos_ontology/migrate_claims.py`, `kairos-design-domain` skill
**Implementation:** issue #192 Phase A1 (A2 target-URI naming + Phase B
satellite/child-entity detection deferred)

### Context

During initial domain design a source table that spreads an address across several
scalar columns (`billing_street` / `billing_city` / `billing_postal_code`) was
silently force-fit into unrelated scalar properties. DD-069 already detects
address-part columns and emits a **prose** `review_reason` ("…model an address
relationship / shared Address concept"), but it only *flags* — nothing
machine-readable is produced, so the relationship is easy to miss and there is no
gate that blocks TTL generation until a human decides.

Issue #192 proposed promoting these into relationship claims, defaulting
cross-module LLM widening on for accelerator domains, and adding satellite/child
detection from name suffixes. Auditing the code and the governing methodology
(`evidence-led-accelerator-first-modeling-approach`) showed several of those levers
drift from the methodology: the accelerator must not become an automatic generator
(lines 72/222/1252), LLM output stays candidate-only until approval (1139),
relationships come from **source-confirmed** silver FKs (525), and DD-070 guarantees
the default (non-`--cross-module`) output is byte-identical with a cache signature
that encodes the cross-module params. Also, `relationship` is already a valid claim
`type`, but a `Claim` only carries one URI (`class_uri` / `property_uri` via
`identifying_uri()`) — it has no source/target/cardinality/source-columns fields, so
it cannot yet faithfully encode a 1:n relationship.

### Decision

Ship the smallest evidence-led slice (**Phase A1**): a deterministic, always-on,
**additive** detector that promotes the existing address-part signal into a
machine-readable **advisory candidate**, plus a mandatory skill gate. No LLM, no
cross-module widening, no new claim type, no registry migration.

- **Detector** (`_detect_address_relationship_candidates`): groups address-part
  columns by **role** (the qualifier prefix, e.g. `billing` / `shipping`), requires
  **≥2 distinct complementary part kinds** per role, and emits one candidate per
  qualifying role. Reuses the DD-069 `_detect_address_part` gate (so
  `country_of_origin` and `billing_email` stay excluded) and exact-token matching to
  avoid false positives (e.g. "ethnicity" ≠ city).
- **Candidate shape:** `{type: address_relationship_candidate, source_table, role,
  suggested_relationship (hasAddress / has{Role}Address), target_concept: "Address",
  source_columns, address_parts, requires_human_confirmation: true, rationale}`.
  It carries **no resolvable target URI** — naming a concrete `→ Address` (Phase A2)
  needs the shared/accelerator pack loaded and is deferred.
- **Additive, advisory:** candidates are emitted *in addition to* the scalar column
  dispositions (deleting those would lose columns from silver/gold + coverage). They
  ride along as a registry-level `relationship_candidates` list — **not** as governed
  `relationship` claims — so we don't prematurely encode under-specified relationship
  semantics. `alignment_to_registry` ignores them for claim generation;
  `merge_preserving_decisions` regenerates them deterministically each run while
  preserving human claim decisions.
- **Enforcement is the skill gate, not an LLM default.** A new MANDATORY
  *Checkpoint 3c — Relationship & Satellite-Entity Review* in `kairos-design-domain`
  blocks TTL generation until every candidate has an explicit model / relate / defer
  decision. Issue #192's cross-module default-on is **rejected** (it would break the
  DD-070 byte-identical contract, enlarge the LLM pool/cost, and drift toward
  accelerator-as-generator); `--cross-module` stays an opt-in deep pass invokable
  from the gate.

### Consequences

- The address-relationship gap is now surfaced as reproducible, reviewable metadata
  and gated before TTL generation, without LLM cost or DD-070 breakage.
- The relationship-claim schema gap is documented but untouched: governed
  `relationship` claims (with source/target/cardinality/columns) and FK-driven
  satellite detection remain future work (Phase A2 / Phase B) once the schema
  semantics settle.
- New deterministic surface area: `relationship_candidates` on `TableAlignment`,
  `alignment_to_dict`, and `ClaimRegistry` (round-tripped through `to_dict` /
  `from_dict` and the migrate path). Covered by `tests/test_relationship_candidates.py`
  and `tests/scenarios/test_scenario_relationship_candidates.py`.

---

## DD-085: OKF phase logs replace interactive `.sessions-design` logs

**Status:** Accepted
**Date:** 2026-06-20
**Affects:** `cli/main.py`, design skill instructions, scaffold skill copies,
`kairos-help`, `kairos-diagnose-status`, `tests/test_init.py`
**Implementation:** scaffold and skill cleanup following DD-080

### Context

DD-080 introduced the OKF continuation-state bundle at
`ontology-hub/.kairos-state/` and explicitly states that `.kairos-state/` is the
only state system going forward. The migration was partial: phase skills gained
OKF read/proposal headers, but their hard gates and session-management sections
still required bespoke interactive `.sessions-design/{phase}-*.md` logs. New hubs
also still scaffolded `.sessions-design/`, leaving two competing places for the
same design-session memory.

### Decision

Use `.kairos-state/phases/...` OKF phase logs as the **only required interactive
design-session state** for discovery, source, domain, mapping, silver, and gold
skills. Superseded interactive phase logs move to `.kairos-state/_archive/` when a
user starts fresh. Do not create `.sessions-design/` for new hubs.

Existing `.sessions-design/*.md` files are historical only. There is no automatic
migration helper; when resuming an existing hub, a user or skill may manually
summarize relevant open questions and decisions into the appropriate OKF phase log.

This does **not** migrate the separate machine/audit surfaces:

- `.sessions-design-import/` remains the import-results audit log location for
  source-import commands.
- `.sessions-projection/` remains the projection-run report location.

### Rationale

Keeping both interactive `.sessions-design` logs and OKF phase logs creates
conflicting prerequisites and split resume anchors. OKF already provides
per-instance phase logs, frontmatter status, xrefs, and a shared continuation
index owned by `kairos-flow`; duplicating the same state in `.sessions-design`
adds drift without adding capability. Avoiding automatic migration keeps the
change simple and prevents LLM-generated summaries from rewriting historical
session evidence.

### Consequences

- Design skills must require their OKF phase log before changing design artifacts.
- `init` and `new-repo` scaffold `.kairos-state/` phase directories and no longer
  scaffold interactive `.sessions-design/`.
- Documentation and diagnostics refer to `.sessions-design` only as legacy
  historical context, not as current design state.
- Existing hubs are backward-readable by humans, but current continuation state is
  maintained in `.kairos-state/`.

---

## DD-086: Reporting-informed draft-model planning report

**Status:** Accepted
**Date:** 2026-06-21
**Affects:** `src/kairos_ontology/draft_model_report.py`, `import_tmdl.py`,
`derive_claims.py` evidence workflow, `cli/main.py`, design skills
**Implementation:** `kairos-ontology draft-model-report`

### Context

Real hubs with TMDL/Power BI evidence, glossary terms, source affinity, mappings,
and claim registries can discover high-value reporting concepts late and repeatedly
across domain, silver, and gold design. The first proposal was to generate a silver
seed, but that would drift from evidence-led claim governance and could turn BI joins
into approved natural keys or FKs too early.

### Decision

Add a deterministic, AI-free `draft-model-report` command that extends the claim
extraction evidence workflow with richer TMDL/reporting evidence and emits a
read-only draft model planning report:

- one all-domain summary YAML;
- per-domain draft evidence YAML files;
- a Markdown report;
- one cross-domain Mermaid ERD-style view.

The report is advisory (`projection_authority: false`). It may contain candidate
classes, relationship questions, natural-key/FK questions, gold measure candidates,
mapping gaps, glossary matches, and next actions, but it never approves claims,
writes ontology TTL, or writes silver extension annotations.

The methodology uses it in two passes:

1. early intake after source analysis, before domain design, using only evidence
   available at that point (affinity, TMDL, glossary, resumed claims);
2. post-mapping fit-gap in the existing claims phase, reconciling reporting demand
   with mappings, approved/source-backed claims, and passthrough decisions.

The canonical lifecycle order remains `discovery -> source -> domain -> mapping ->
claims -> silver -> gold -> validate -> project`.

### Rationale

This keeps the useful visual "draft model" experience while avoiding a fourth
claim-like source of truth. Claim state remains in `model/claims/{domain}-claims.yaml`,
projection-facing TTL remains controlled by approved claims and the silver skill,
and TMDL relationships remain questions until source/stakeholder evidence confirms
their semantics.

### Consequences

- Users get an all-domain ERD-style view before committing to domain TTL.
- TMDL concept mappings now carry `domain` and measure metadata to support routing
  and gold review.
- Skills can consume the draft as an agenda, but must still require explicit user
  confirmation before modeling, silver annotations, or gold semantics.
- Future Slice 5 work (`pbi-source-fit-gap`, `tmdl-to-gold-ext`) should reuse this
  evidence/reporting backbone rather than introduce a competing reconciler.

---

## DD-087: Data-product vertical-slice planning reports

**Status:** Accepted
**Date:** 2026-06-21
**Affects:** `src/kairos_ontology/draft_model_report.py`, `cli/main.py`, design skills
**Implementation:** `kairos-ontology draft-model-report --contract ...`

### Context

Some hubs need a quick path from source evidence to a Power BI semantic model for
one report pack or data product. A naive direct source-to-gold workflow would
bypass domain, mapping, claim, silver, and gold design gates and would create a
fourth authority beside the claim registry.

### Decision

Extend the DD-086 draft-model report with a **data-product vertical slice** mode.
The user captures report demand in
`model/planning/data-products/{product}/contract.yaml`, and the command emits a
product-scoped planning view under the same folder:

- `data-product-plan.yaml`;
- `data-product-report.md`;
- `data-product-erd.mmd`;
- `domains/{domain}.yaml`.

All artifacts must declare or inherit `projection_authority: false`. The command
is deterministic, AI-free by default, and derives product triage from the DD-086
evidence statuses (`claim-approved`, `mapping-backed`, `source-backed`,
`tmdl-only`, etc.) rather than introducing a competing evidence vocabulary.

### Rationale

This keeps report-first delivery fast while preserving the canonical lifecycle.
The product slice narrows the agenda for mapping, silver, and gold design; it
does not approve claims, write TTL, or feed projectors. Gold scoping should use
the existing `kairos-ext:perspective` annotation after user confirmation instead
of creating a separate semantic-model grouping mechanism.

### Consequences

- Product contracts live under `model/planning/`, not the governed model
  authority area.
- `gold-only` is not a valid bypass category. The report uses
  `gold-annotation-needed` only when an item is already claim-backed or
  mapping-backed.
- Mapping, silver, and gold skills may consume product plans as scoped agendas,
  but still require explicit confirmation before writing TTL.
- Projectors and validators ignore data-product planning artifacts.

---

## DD-088: Skill-scoped opt-in design fleet mode

**Status:** Accepted
**Date:** 2026-06-22
**Affects:** Copilot instructions, interactive design skills, scaffold managed files
**Implementation:** `.github/copilot-instructions.md`,
`.github/skills/kairos-design-*/SKILL.md`, scaffold copies

### Context

Kairos design skills were originally interactive-only. This protected stakeholder
confirmation gates for discovery terms, source vocabulary descriptions, domain
modeling, mappings, silver annotations, and gold semantic-model choices. However,
testing a complete lifecycle can be slow when every checkpoint must wait for a
human even when the user explicitly wants AI to make decisions for a test run.

### Decision

Keep the lifecycle-wide design autopilot ban. Interactive mode remains the
default, and no fleet-mode authorization may be inferred from an earlier phase,
stored as a global preference, or propagated during a skill handoff.

A user may explicitly override the ban for **one specific design skill
invocation**. The active skill may offer that choice at startup or accept an
explicit fleet/autopilot/AI-approved request while it is active. Authorization
ends when that skill invocation ends or pauses; another skill, or a later resume,
starts interactive unless the user grants a new override.

Within an authorized invocation, the skill may let AI approve normal checkpoint
decisions, but it must still execute the same phases, evidence gates, validations,
and skill routing as interactive mode. Each AI-made decision must be recorded as
AI-approved with rationale, confidence, and evidence references in the relevant
phase log or review output.

### Rationale

This preserves the no-autopilot governance boundary while allowing a user to
accelerate one well-defined phase deliberately. The speedup comes from replacing
repeated human confirmations inside that invocation with traceable AI decisions,
not from granting blanket lifecycle autonomy or skipping evidence, validation, or
review artifacts.

### Consequences

- Interactive remains the normal governance mode for stakeholder-facing design.
- Fleet consent is skill- and invocation-scoped; it never carries into another
  skill or a resumed invocation.
- A skill that offers fleet mode must explain the implications before asking and
  must make interactive mode the recommended default.
- Fleet mode decisions are explicitly marked AI-approved, not user-confirmed.
- Skills must still stop for ambiguity, low confidence, policy-sensitive choices,
  destructive or irreversible actions, and proprietary/PII risk.
- Existing validation and scaffold sync tests guard the instruction copies.
- **Amended by DD-149**: archetype selection in `kairos-design-discovery` is added to
  the never-fleet-eligible list above — it is always confirmed by a human, never
  AI-approved, even within an active fleet-mode override.

---

## DD-089: Offline silver sample audit

**Status:** Accepted
**Date:** 2026-06-22
**Affects:** `src/kairos_ontology/silver_sample_audit.py`, `cli/main.py`,
dbt/silver projection QA, design and packaging skills
**Implementation:** `kairos-ontology audit-silver-samples`

### Context

Generated dbt silver models can be parsed offline, but parse/compile does not
prove that mappings and transforms preserve source semantics. Full validation
against actual bronze data belongs in the downstream dataplatform, but waiting
until then delays feedback on obvious mapping risks such as missing samples,
incompatible casts, cross-source format mismatches, or SQL artifacts that do not
trace back to mapped properties.

### Decision

Introduce an offline advisory **silver sample audit**. The command reads source
vocabulary samples, SKOS mappings, and generated dbt SQL from the ontology hub.
It emits structured YAML and Markdown findings without requiring dbt profiles,
warehouse credentials, network access, or real bronze tables.

The audit is non-blocking by default. It may be made blocking in CI with
`--fail-on warning|error`, but its findings remain advisory because source
samples are not equivalent to full production data.

### Rationale

This creates a low-cost pre-handoff QA layer. It improves hub-side feedback while
preserving the dataplatform as the authority for executed dbt runs, data tests,
row counts, referential integrity, and production distributions.

### Consequences

- Projection users can run `kairos-ontology audit-silver-samples` after dbt
  projection and before releasing/consuming the package.
- Findings are scoped to available sample values and generated artifacts.
- Dataplatform validation remains required for actual bronze data correctness and
  SQL engine behavior.

### Amendment (2026-08-12): v5 EntityBindings as a second mapping source (issue #348)

The audit was written against the v4 RDF-authored `model/mappings/` SKOS surface only. It
never read `integration/bindings/*.binding.yaml` (v5 EntityBindings, DD-133), so on a v5-only
hub it found zero mapped columns and — because `sample_coverage_ratio` special-cased a
zero denominator to `1.0` — printed an unqualified `✅ ... (100% coverage)` for a hub it had
not looked at.

`run_silver_sample_audit` now takes an optional `bindings_dir`/`hub_root` and resolves v5
mappings via the compiler's own `resolve_scope` + `adapt_binding` (`core/compiler/kernel.py`,
`core/compiler/adapter.py`) — the exact functions that turn one `EntityBinding` into
column-level `ColumnMappingFact`s for compilation — rather than re-deriving source-relation or
expression resolution. The resulting facts are folded into the same `mapping_context()` facade
(`core/projections/dbt/mapping_bind.py`) the v4 path already produces, so the rest of the
audit (sample-shape, cross-source, and SQL-lineage checks) is unchanged. `ResolvedRelation`
resolves a binding's source column to a synthesized `{table_uri}/{name}` symbol rather than the
real bronze `SourceColumn` URI, so the join back to persisted samples matches on the real
`(table_uri, column_name)` pair instead of URI equality. A physical column mapped on both
surfaces at once (mid v4-to-v5 migration) is counted once, not twice.

`sample_coverage_ratio` now returns `None`, not `1.0`, when `mapped_columns == 0`; the CLI
prints an explicit `⚠ ... nothing was audited` line naming both authoring surfaces searched
instead of a `✅` success line, and adds a `no_mapping_surface_found` warning finding so
`--fail-on warning` (the recommended CI setting) treats an inert audit as a failure — the same
"a command that checked nothing must not emit the success string of a command that checked
something" rule raised by #309 and #332.

---

## DD-090: Core Concepts Conformance — toolkit runtime for the archetype + discovery contract (v0.2)

**Status:** Accepted
**Date:** 2026-06-22
**Affects:** `src/kairos_ontology/core/archetype_loader.py`,
`src/kairos_ontology/core/archetype_topology.py`,
`src/kairos_ontology/core/conformance_artifact.py`,
`src/kairos_ontology/core/derive_claims.py`, `src/kairos_ontology/cli/main.py`
(`discovery-conformance` group and `derive-claims`), scaffold dir lists,
`kairos-design-discovery` and `kairos-design-domain` skills
**Implementation:** `kairos-ontology discovery-conformance {list-archetypes,load,validate}`
and the proposed-only conformance stream in `kairos-ontology derive-claims`

### Context

Business discovery captured *what a company does* (business model + glossary) but
never asked *which industry-standard concepts MUST exist, and does the business
conform to them?* That gap surfaced mid-modeling as ad-hoc reference-model
selection debates and undocumented deviations. Reference-models **v1.11.0** ships
the **archetype + discovery contract (v0.2)**: a machine catalog per archetype
(`blueprints/archetypes/<id>.yaml`: ref-model modules + core concepts + tiers,
JSON-Schema validated), a shared outcome enum
(`_schema/outcome-codes.yaml`), and SME interview prose
(`accelerator-packs/*/discovery/<id>.md`, paired by filename stem). The toolkit
must implement the consuming runtime.

### Decision

Implement a Python loader/topology/artifact layer plus a skill-wrapped CLI
command group, consumed by a new `kairos-design-discovery` **Phase 2.5 — Core
Concepts Conformance**:

- **Loader** resolves the refmodels root (`--refmodels-root` →
  `KAIROS_REFMODELS_ROOT` env → existing `_resolve_ref_models_dir()` fallback; no
  net-new hub-config key), normalizes repo-root vs `ontology-reference-models/`
  child, validates the archetype YAML against the **shipped JSON Schema** via
  `jsonschema`, and loads the outcome enum from `outcome-codes.yaml` (not
  hardcoded).
- **Topology** parses each `ref_model_modules[].iri` **directly via
  `CatalogResolver`** — not umbrella `owl:imports` — because the latter only
  follows direct imports and yields 0 concepts; direct parsing yields the full
  concept set + domain/range edges with declared cardinality.
- **Artifact**: a validated, hashed
  `integration/discovery/core-concepts-conformance.yaml` (carrying resolved
  `ref_model_modules`, per-concept outcomes/tiers/reasons, scorecard, and a
  `concept_set_hash` for stale-detection).
- **Dual persistence** (DD-080): machine artifact + an OKF `phases/discovery.md`
  conformance section for continuation context.
- **Mode** (DD-088): interactive by default; AI pre-fill only in design fleet mode.
- **Single archetype per session**; multi-archetype companies run a second session.
- **`kairos-design-domain` consumption remains warn-only** (missing/stale artifact
  warns, never blocks).
- A committed, valid artifact may also drive **deterministic proposed-only class
  claims** through `derive-claims`. The outcome policy is:
  `conforms` → `claim`, `conforms-with-rename` → `claim`, `partial` →
  `specialize`, `deviates` → `gap`, and `not-applicable` → no proposal. Required,
  recommended, and optional tiers are all eligible.
- Conformance remains **non-authoritative for approval**: generated claims always
  start as `status: proposed`, never materialize by themselves, and prior human
  decisions survive regeneration through `merge_preserving_decisions()`. The Claim
  Registry remains the sole approval/materialization authority (DD-094).

### Rationale

Catalog-driven conformance shifts reference-model selection rationale left into
discovery, where the business context is freshest, and records it as a machine
artifact the modeling skill can pre-seed from. Loading the outcome enum and JSON
Schema from the shipped contract keeps the toolkit in lock-step with ref-models
versions. Direct module-IRI parsing is required for correctness. Env+fallback
root resolution avoids introducing a hub-config loader that does not exist today.

### Consequences

- New runtime dependency `jsonschema>=4.0.0`; new env var `KAIROS_REFMODELS_ROOT`;
  new scaffold dir `ontology-hub/integration/discovery/`.
- Counts (concepts/modules) are read dynamically from the loaded archetype, never
  hardcoded.
- Missing conformance remains a compatible no-op for claim derivation. A present
  malformed, unknown, or contradictory artifact is an explicit validation error;
  it is never silently ignored.
- A **blocking** design-domain gate is deferred to a future DD.
- CI/tests use a bundled minimal fixture refmodels root — no live checkout needed.

---

## DD-091: Optional DDD governance overlay (architecture documentation only)

**Status:** Accepted
**Date:** 2026-07-05
**Affects:** `src/kairos_ontology/scaffold/kairos-ddd.ttl`,
`src/kairos_ontology/scaffold/kairos-ddd-shapes.shacl.ttl`,
`src/kairos_ontology/ddd.py`,
`src/kairos_ontology/projections/ddd_projector.py`, `projector.py`
(`ddd` target), `cli/main.py` (`project --target ddd`, `validate --ddd`),
`tests/scenarios/acme-hub/model/extensions/*-ddd-ext.ttl`, `kairos-help` skill
**Implementation:** `kairos-ontology validate --ddd`,
`kairos-ontology project --target ddd`

### Context

Teams applying Domain-Driven Design want to record strategic (bounded contexts,
context maps) and tactical (aggregate roots, value objects, domain events)
design intent alongside the domain ontology. The core ontologies must stay
focused on durable business semantics (R1), and data governance — ownership,
approval, disposition, materialization, certification — already lives
authoritatively in the claim registry (R2). Silver/gold projection controls
already live in the `kairos-ext:` extension model (R3). A DDD overlay must be
purely additive design metadata, not a second governance source.

### Decision

Introduce an **optional, additive DDD design overlay** expressed in
`*-ddd-ext.ttl` files under `model/extensions/`, driven by a new managed
vocabulary `kairos-ddd` (namespace `https://kairos.cnext.eu/ddd#`). The overlay
uses typed RDF resources and controlled individuals (not raw strings) for
bounded contexts, tactical patterns, and context-map relationships (R5, R6).

- **Validation** runs through a dedicated path (`validate --ddd`, and as part of
  `validate --all`) that discovers `*-ddd-ext.ttl`, merges each overlay with its
  matching domain ontology plus the packaged `kairos-ddd` vocabulary, and applies
  DDD SHACL shapes (R7). Hubs with no overlay pass with DDD marked not-applicable
  (R4). The shapes reject silver/gold projection predicates inside an overlay to
  keep concerns separate.
- **Projection** adds a one-way documentation target `ddd` that writes Mermaid
  context maps, aggregate overviews, and a Markdown report to
  `output/architecture/ddd/`. It never changes silver, gold, dbt, or Power BI
  output (R8). XMI / Enterprise Architect round-trip is explicitly out of scope
  for the MVP.
- **Packaging:** the vocabulary and shapes are bundled with the package (the
  validator/projector load them from the installed package, so existing hubs work
  without a hub-local copy) and are also shipped in `scaffold/` for new hubs
  (R10). Consistent with the existing `kairos-ext` / `kairos-bronze` / `kairos-map`
  vocabularies, the DDD vocabulary is merged by file path rather than resolved via
  `owl:imports`/XML catalog, so no catalog entry is required.

### Rationale

Keeping the overlay optional and documentation-only preserves the claim registry
as the single governance authority and the `kairos-ext` extensions as the single
projection-control authority, avoiding a competing metadata source. Typed
resources and controlled individuals give context maps enough structure to render
deterministically and let SHACL validate controlled values. Loading vocabulary
and shapes from the package (not the hub) means the feature validates correctly
in hubs that predate it, while scaffold copies keep new hubs self-describing.

### Consequences

- New optional lifecycle step: `discovery → source → domain/claims → optional DDD
  overlay → mapping → silver → gold → validate → project/report`.
- `validate --all` now also runs the DDD path (skipped/not-applicable when no
  overlay exists), and `project --target ddd` is available.
- A DDD overlay that leaks `kairos-ext:silver*`/`gold*` predicates fails
  validation, enforcing the governance/design separation.
- One-way XMI/EA export is deferred to a future, separately-accepted DD.

---

## DD-092: Contracted custom dbt transformation boundary

**Status:** Accepted

**Date:** 2026-07-18

**Affects:** `src/kairos_ontology/core/dbt_contracts.py`,
`src/kairos_ontology/core/dbt_contract_sync.py`,
`src/kairos_ontology/core/dbt_validation.py`,
`src/kairos_ontology/core/projections/medallion_dbt_projector.py`,
`src/kairos_ontology/core/projector.py`, `src/kairos_ontology/cli/main.py`,
hub scaffold and `kairos-develop-dbt-transformation` skill

**Implementation:** `sync-dbt-contracts`, `project --platform`,
`validate-dbt`

### Context

Some Bronze-to-Silver entities require joins, windows, ranking, aggregation,
JSON expansion, fallback rules, source union, or grain changes beyond normal
SKOS column expressions. Encoding an arbitrary execution graph in RDF would
duplicate dbt, while replacing the generated Silver model entirely would lose
ontology-driven keys, relationships, SCD policy, tests, and documentation.

The existing `silverSourceRef` (DD-039) already routes a generated Silver model
through `ref()`, but it does not package user-owned transformations, define and
synchronize their output contract, or validate the assembled dbt graph.

### Decision

Introduce a contracted custom dbt boundary:

- Handwritten dbt SQL under `integration/transforms/dbt/` owns executable
  relational logic.
- dbt model properties YAML is the single physical authority for output column
  names/types, the physical grain assertion, physical key columns, adapter
  support, dependencies, decision provenance, and tests.
- Kairos deterministically generates a managed, committed Bronze-compatible
  virtual-source vocabulary from the contract. `sync-dbt-contracts` is the only
  writer; projection performs a semantic freshness check and never rewrites
  source artifacts.
- Existing SKOS mappings map virtual output columns to ontology properties.
  Existing `kairos-ext:silverSourceRef` selects the bundled dbt model; no second
  routing annotation or output-binding vocabulary is introduced.
- The ontology and Silver extension remain authoritative for business meaning,
  semantic natural-key properties, SK/IRI/FK/SCD policy. Kairos validates their
  alignment with physical key columns through mappings.
- Custom models, schema/unit-test YAML, singular tests, and namespaced macros
  are bundled. Paths, names, collisions, references, and a toolkit-owned package
  allow-list are validated before dbt target files are written.
- Domain-scoped projection assembles only active contracts for the selected
  ontology plus their transitive custom-model `ref()` dependency closure. Model
  properties, verifying tests, required macro files, and governed packages follow
  that closure; unreachable contracts from another domain are not copied.
- `project --platform fabric|databricks` generates one adapter-specific package
  per invocation at the backward-compatible `output/medallion/dbt/` path.
  Dual-adapter CI uses separate temporary output roots.
- `validate-dbt --platform` requires dependency installation and parse, inspects
  manifest edges, and attempts compile. Connection-dependent compile failures
  are environment-blocked; SQL/Jinja/contract/graph failures remain blocking.
- `meta.kairos.decisions` records descriptive rationale, evidence, confidence,
  approval, implementing model, and verifying tests. It is never interpreted as
  executable transformation configuration.
- `kairos-develop-dbt-transformation` provides the interactive authoring
  workflow. It requires grain/identity and contract checkpoints and routes
  ontology, mapping, and Silver changes through their existing design skills.

### Rationale

This creates one explicit semantic boundary without making Kairos a general SQL
compiler. Each concern has one authority, existing mapping and routing machinery
is reused, and the generated Silver wrapper retains governance Kairos can
actually enforce. Adapter-specific generation acknowledges that Fabric and
Databricks types and constraints are not interchangeable. Explicit
synchronization keeps committed mapping inputs reviewable without allowing a
second hand-authored physical schema.

### Consequences

- Advanced transformation authoring is optional; hubs without custom contracts
  retain existing output and Fabric defaults.
- A contract change requires `sync-dbt-contracts` before projection.
- Full-hub projection assembles the union of every active domain contract, while
  `project --ontology` produces a self-contained package without unrelated models.
- Runtime data/grain guarantees still require warehouse-backed tests before
  production publication; toolkit CI supplies hooks but no live credentials.
- Atomic directory replacement and verified internal SQL column lineage remain
  deferred.
- Contracted Silver interface breaks require an explicit downstream migration,
  independent of the toolkit's own release version.

---

## DD-093: Governed contracted-source replacement in source coverage

**Status:** Accepted

**Date:** 2026-07-18

**Affects:** `src/kairos_ontology/core/dbt_contracts.py`,
`src/kairos_ontology/core/dbt_contract_sync.py`,
`src/kairos_ontology/core/source_coverage.py`,
`src/kairos_ontology/core/projections/medallion_dbt_projector.py`,
`src/kairos_ontology/cli/main.py`, advanced dbt/mapping/Silver skills

**Implementation:** `meta.kairos.replaces_sources`,
`kairos-dbt:replacesSource`, `sync-dbt-contracts --bronze-sources`,
`check-claims` source coverage

### Context

A wrong-grain, duplicate-prone, or structurally unsuitable Bronze table may need a
contracted dbt transformation before it is safe as a Silver source. DD-061 previously
required the original table or one of its columns to be a SKOS mapping subject. Adding
that mapping only to satisfy coverage creates a second source-authority path and can
route projection around the governed transformation.

Calling manually declared metadata "lineage" would overstate what the toolkit proves:
Kairos does not parse arbitrary SQL into verified row- or column-level lineage.

### Decision

- A contract may declare `meta.kairos.replaces_sources`, containing canonical absolute
  HTTP(S) Bronze `SourceTable` IRIs. Names, labels, and filenames are not authority.
- The declaration is a governed replacement assertion, not verified SQL lineage.
- `sync-dbt-contracts` validates each IRI against a separate non-generated Bronze input
  root and emits `kairos-dbt:replacesSource` in the managed virtual vocabulary.
- Replacement coverage requires agreement across the canonical source IRI, one approved
  source-table class/reference-data claim, the contract `target_class`, a table-level
  `skos:exactMatch`, synchronized managed RDF, and `silverSourceRef`.
- Direct and replacement mappings for the same domain/source are a blocking conflict.
  Multiple replacement contracts for the same authority path are also blocking.
- Contract replacement inputs are included in generated dbt `_sources.yml` independently
  of SKOS mappings, so executable SQL can use `source()` without granting direct semantic
  mapping authority.
- Hubs and contracts without replacement metadata keep the existing direct-coverage path
  and do not acquire replacement-specific source resolution.

### Rationale

The invariant closes the coverage false negative without weakening the gate or inventing
a second transformation DSL. Canonical IRIs avoid ambiguous source identity. Claims own
semantic approval, SKOS owns virtual-source meaning, Silver extensions own routing, dbt
SQL remains executable truth, and tests verify behavior. Requiring all surfaces to agree
prevents metadata alone from laundering an unrelated joined table into coverage.

### Consequences

- Authors must copy stable Bronze table IRIs into contracts and synchronize before
  mapping or projection.
- `skos:closeMatch`, broader/narrower/related mappings, column-only mappings, and stale
  generated vocabularies cannot authorize replacement.
- A deliberate direct/replacement overlap must be resolved rather than hidden by
  precedence.
- SQL-internal lineage remains deferred; the replacement assertion is reviewable but not
  a mechanical proof of which rows or columns the SQL consumes.
- Source discovery reconciles equivalent monolithic/split RDF views by canonical table
  IRI and exact table/column subgraph equality. Divergent definitions and cross-system
  duplicate authority remain blocking.
- Generated dbt-contract tables are excluded from LLM affinity analysis and active
  affinity obligations. Their contract target and governed replacement evidence already
  form the authority chain; legacy generated affinity reports are archived.
- Split vocabulary files share their top-level source-system identity. Legacy
  filename-derived affinity reports are excluded from gates and archived when source
  analysis is refreshed, preventing stale duplicate obligations.
- Affinity schema v2 remains unchanged. Removing generated virtual systems resolves the
  observed filename/folder mismatch without forcing claim-registry hash churn for
  ordinary sources. Canonical table IRI remains mandatory at the contract boundary; an
  IRI-first affinity schema is deferred until a real-source identity case requires it.

---

## DD-094: Claim Registry is the single materialization authority

**Status:** Accepted

**Date:** 2026-07-21

**Affects:** `model/claims/{domain}-claims.yaml`, `{domain}-alignment.yaml`
(retired), `src/kairos_ontology/core/claim_registry.py`,
`src/kairos_ontology/core/completeness_model.py`,
`src/kairos_ontology/core/claim_coverage.py`,
`src/kairos_ontology/core/source_coverage.py`,
`src/kairos_ontology/core/propose_alignment.py`, silver/dbt projectors,
`check-claims` / `check-source-coverage`, evidence-led design skills

**Implementation:** Claim Registry schema v1 → migration → projector authority.
Canonicalized from the archived evidence-led decision log
(`docs/archive/evidence-led-modeling/decision-log.md` §DD-EL-1); see also
`docs/archive/evidence-led-modeling/0b-claim-registry-schema-v1.md`.

### Context

The evidence-led, accelerator-first methodology needs a single governed artifact
recording *which concepts are approved to materialize*, with evidence, ownership,
dispositions, and silver-contract impact. The legacy `{domain}-alignment.yaml`
carried proposal data but was an AI-output artifact with no approval lifecycle.
Keeping both an alignment file and a registry would create a dual source of truth.

### Decision

Introduce a per-domain **Claim Registry** at `model/claims/{domain}-claims.yaml`
(schema v1) as the single hand-governed source of truth for materialization.
**Retire** `{domain}-alignment.yaml` via a one-way deterministic migration; once a
domain has a claims file, a leftover alignment file is a hard error (no dual path).
Each claim carries an explicit `status` lifecycle (`proposed → approved → …`) and a
`disposition` vocabulary (`claim` / `specialize` / `passthrough` / `skip` / `gap`).
Approved `claim`/`specialize` claims — and only those — authorize silver/dbt
materialization; the projector consumes the registry rather than namespace
selection alone. The retired coverage gates unify into a single **`check-claims`**
command. A canonical per-table completeness snapshot is computed once from committed
affinity, registry, source, mapping, contract, and Silver-extension inputs; the
claim and source gate reports are views over that snapshot.
`migrate_claims.py` is the sole legacy alignment-YAML reader, used only by the
one-shot migration; no runtime completeness evaluator reads alignment YAML.

### Rationale

One governed file with a reviewable, GitHub-PR-based lifecycle gives auditable
governance. A single deterministic completeness model preserves coverage,
freshness, anchor/reference-class, and governed-replacement guarantees while
eliminating duplicate table reconstruction. Golden, parity, and negative-migration
tests enforce fidelity.

### Consequences

- The registry is the authority for what materializes; probabilistic evidence never
  auto-approves a claim.
- `propose-alignment` output becomes migration input, not a parallel artifact.
- Custom-column triage maps: `model`→`specialize`/`claim`,
  `silver-passthrough`→`passthrough`, `skip`→`skip`.
- Claim ids are stable and never reused; deletions become `deprecated`.
- `check-claims` blocks on missing/invalid/incomplete/stale/duplicate-approved and
  (unless `--no-source-coverage`) unmapped tables; `--strict` also blocks undecided
  (`proposed`) claims; leftover `*-alignment.yaml` is always a hard error.
- Conformance-derived proposals remain Claim Registry evidence only: they cannot
  satisfy direct mapping coverage without a committed SKOS mapping or complete
  governed-replacement evidence.

---

## DD-095: derive-claims deterministic multi-source evidence aggregation

**Status:** Accepted

**Date:** 2026-07-21

**Affects:** `model/claims/{domain}-claims.yaml`,
`src/kairos_ontology/core/derive_claims.py`, `derive-claims` CLI command,
`claim_registry.merge_preserving_decisions`, `_concurrency.py` / `_cache.py`,
evidence-led design skills (`kairos-design-source`, `kairos-execute-project`)

**Implementation:** Deterministic evidence aggregator on top of DD-094.
Canonicalized from the archived evidence-led decision log
(`docs/archive/evidence-led-modeling/decision-log.md` §DD-EL-5); see also
`docs/archive/evidence-led-modeling/slice-3-derive-claims.md`.

### Context

With the Claim Registry (DD-094) as the governance authority, authoring candidate
claims is still largely manual: the evidence needed to propose them is scattered
across already-produced artifacts (`analyse-sources` affinity, `propose-alignment`
column→property output, `import-tmdl` concept-mapping dispositions, SKOS mapping
TTL, sample-derived signals, and committed Core Concepts Conformance outcomes).
The semantically hard interpretation already happened upstream; what is missing is
a single deterministic step that joins those evidence streams into a richer
candidate set for human curation.

### Decision

Add a **`derive-claims`** CLI command: a **deterministic, AI-free** aggregator that
merges/enriches the Claim Registry with additional deterministic evidence streams
and attaches **multiple `evidence_sources` per claim**. It joins six streams on
`(system, table[, column])` and ref_class/ref_property names: (1) the existing
claims registry, (2) `analyse-sources` affinity, (3) `import-tmdl` concept-mapping,
(4) SKOS mappings, (5) sample-derived enum/FK signals, and (6) validated Core
Concepts Conformance outcomes using DD-090's proposed-only policy. **C4 guard —
all derived/new claims are `status: proposed`, never auto-`approved`.** Human
decisions survive re-runs via `merge_preserving_decisions()`; conflicting evidence
is surfaced (low-confidence proposed claims / rationale notes), never silently
resolved. It reuses `_concurrency.map_concurrent` (`--max-workers`) and the
`_cache` sidecar (`--force`, including conformance in the input digest), and is
skill-managed (soft skill-gate; `KAIROS_SKILL_CONTEXT=1` silences the warning).

### Rationale

The hard interpretation already happened upstream, so this step is pure
deterministic plumbing: a reproducible join with no model variance and no token
spend. Keeping it AI-free makes re-runs free, fast, and diffable, and preserves the
strong (anchored) vs weak (affinity-only) evidence distinction. No cost banner is
printed because nothing is billed — printing one here would train users to ignore
the banner where it actually matters (the paid AI commands).

### Consequences

- One command turns already-produced customer assets into a richer candidate claim
  set, reducing hand-authoring before human curation/approval.
- No claim is ever auto-approved; the `check-claims` approval gate is unchanged.
- Evidence granularity is preserved: each claim may carry multiple
  `evidence_sources`.
- Conformance evidence records tier, outcome, rename, and deviation traceability;
  optional-tier concepts are not filtered out, while `not-applicable` creates no
  candidate.
- A future opt-in `--llm-reconcile` (LLM tie-breaking / rationale synthesis, with a
  cost banner) is explicitly deferred.

---

## DD-096: Target-first derived-aspirational Silver stub → bind loop

**Status:** Accepted

**Date:** 2026-07-21

**Affects:** `src/kairos_ontology/core/binding_analysis.py`,
`src/kairos_ontology/core/projections/medallion_dbt_projector.py`
(`_gen_silver_models`, `_stub_columns`, `_gen_schema_yaml`, `generate_dbt_artifacts`),
`src/kairos_ontology/core/projector.py` (`run_projections`, `_run_projection`),
`src/kairos_ontology/cli/main.py` (`project --emit-aspirational-stubs`),
`src/kairos_ontology/templates/dbt/silver_stub_model.sql.jinja2`,
`src/kairos_ontology/core/determinism.py`, shipped reference design
`docs/draft/silverfirstdesign.md`

**Implementation:** Flag-gated stub emission on top of the canonical
`BindingAnalysis` service (B0) and the Claim Registry (DD-094). Determinism context
(A) is a prerequisite so re-projection stays byte-identical.

### Context

The silver dbt projector historically **skips** any class with no bronze mapping
("no broken placeholders"). That means an *approved but unmapped* claim has no Silver
**target** until a mapping exists, so downstream models cannot be built target-first.
The Silver-First design (`docs/draft/silverfirstdesign.md`) asks for an approved,
unbound claim to project a **stub** — a stable Silver target that transparently
"binds" once a mapping arrives, all via re-projection with no hand-editing. Two
critiques had to be resolved first: (1) `aspirational` must not become a persisted
field that forks the claim state machine, and (2) empty stubs must not create
false-green CI (vacuous 0-row tests passing).

Five blocking inputs (DEC-1…DEC-5) were resolved before implementation.

### Decision

Add an **opt-in, flag-gated** target-first stub → bind loop:

- **Derived, not persisted.** `aspirational` is computed at projection time by the
  canonical `BindingAnalysis` (B0): a class is aspirational iff it is a
  materialization-eligible approved claim (**DEC-5**: `disposition ∈ {claim,
  specialize}` ∧ `type ∈ {class, reference_data}` ∧ `status == approved`) **and** its
  physical Silver model is unbound (no source, not a folded discriminator subtype). No
  new field is added to `Claim`/`SilverImpact`; the status/disposition state machine is
  untouched.
- **Opt-in flag.** `generate_dbt_artifacts(emit_aspirational_stubs=…,
  eligible_class_uris=…)`, threaded through `run_projections`/`_run_projection` and the
  CLI `project --emit-aspirational-stubs` (dbt/all only), with env fallback
  `KAIROS_EMIT_ASPIRATIONAL_STUBS`. **Feature-off is byte-identical to today.**
- **Typed zero-row stub (DEC-3/DEC-4).** `silver_stub_model.sql.jinja2` emits a
  `materialized='view'` model tagged `kairos_aspirational_stub` with
  `meta.is_aspirational=true`, selecting `cast(null as <type>) as <col>` for the
  surrogate-key + IRI structural columns and every (inherited) datatype-property
  column, guarded by `where 1 = 0`. Columns are **typed where typable** via
  `kairos-ext:silverDataType` → `rdfs:range` (`_xsd_to_target`) → the projector's
  established string fallback `VARCHAR(255)` (the value of `_xsd_to_target(None)`;
  this supersedes the earlier `varchar(4000)` draft to stay consistent with the
  projector default). Binding is a plain re-projection; incremental/SCD models use
  `on_schema_change='sync_all_columns'` and the first bound run is a full refresh
  (safe/cheap — the stub had zero rows).
- **Schema YAML marker.** The stub's `_models.yml` entry carries a read-only, derived
  `meta.is_aspirational`.
- **Obsolete-output reconciliation (C3).** The dbt projector writes a
  `.kairos-projection-manifest.json` at the output root recording the files it
  generated; the next run deletes any manifest-recorded file it no longer produces
  (pruning emptied directories). This converges re-projection on the current output —
  a stale stub is removed when the feature is disabled or its claim is deferred —
  while only ever deleting toolkit-recorded files, so hand-authored files are never
  touched.
- **Release-eligibility, not existence, is the gate (DEC-1/DEC-2).** All approved,
  materialization-eligible, *unbound* claims are release-blocking under the strict
  gate; no required/optional field is added (per-claim waiver deferred). Implemented as
  `project --strict` (env fallback `KAIROS_PROJECT_STRICT`, dbt/all only): the dbt
  projector surfaces the unbound-eligible set via an internal `__unbound_eligible__`
  artifact key (computed from the same `class_to_sources`/eligibility as stub emission,
  independent of whether stubs are emitted), and `run_projections` raises
  `ProjectionRunError` when any remain. The scaffold `release-projections.yml` runs the
  projection step with `--strict` so an incomplete hub cannot ship. Gold/Power BI is
  still generated over a stub dependency (star schema stays stable) but any model in a
  stub's dependency closure is **non-release-eligible**; the strict gate blocks release
  while a release-blocking stub exists.
- **Status-scan awareness (D4).** The deterministic `kairos-ontology status` scan
  distinguishes stub vs bound by running the canonical `BindingAnalysis` over the
  hub's *authorities* — the Claim Registry (materialization-eligibility), the domain
  graph, source vocabulary, and SKOS mappings — **not** by reading generated
  `meta.is_aspirational` (absent when the flag is off or the output is stale). A silver
  domain with an approved-but-unbound eligible claim is reported `in-progress`
  ("N aspirational stub(s) pending binding: …") instead of `done`, so `kairos-flow`
  reconciliation and `kairos-diagnose-status` stay correct. The scan degrades to
  today's file-presence result (`done`) when a domain has no claims registry or on any
  load error, preserving the scanner's robust, LLM-free determinism.
- **Determinism prerequisite (A).** Generated artifacts embed an injected
  `generated_at` + `toolkit_version` context (env-overridable via
  `KAIROS_GENERATED_AT`/`SOURCE_DATE_EPOCH`) and sort all RDFLib iteration, so
  re-projection is byte-identical across processes and hash seeds.

### Rationale

Deriving `aspirational` keeps a single source of truth (the Claim Registry + mappings)
and avoids a parallel persisted state that could drift from governance. The opt-in
flag guarantees zero behaviour change for existing hubs (byte-identical output),
letting the loop roll out incrementally. Typed zero-row stubs give downstream models a
stable contract while `where 1 = 0` prevents vacuous green tests from masking an
unbound target. Gating on release-*eligibility* rather than artifact existence keeps
output byte-stable and avoids cascading suppression of gold. Centralizing bound/stub/
folded/skipped classification in one `BindingAnalysis` service means the projector,
coverage, release gate, and status scan never diverge on "is this bound?".

### Consequences

- Hubs can build Silver/Gold **target-first** against approved claims before mappings
  exist; adding a SKOS mapping transparently binds the stub on the next projection.
- Feature-off output (and absence of the new metadata) is unchanged — a hard
  backward-compat constraint enforced by tests.
- Coverage/status must distinguish stub vs bound (a stub is not "done"); the release
  gate blocks while release-blocking stubs remain.
- Deferred (out of scope): per-claim release waivers, `contract.enforced`
  promotion, and the drift report. DD-095 has since shipped conformance as a
  deterministic **proposed-only** evidence driver; it still cannot approve.
- The authoritative complete lifecycle regression is
  `tests/scenarios/test_scenario_silver_first_e2e.py`.

### Addendum (2026-07-21): `BindingAnalysis` consolidated as the single result; aspirational decoupled from stub emission

**Affects:** `src/kairos_ontology/core/binding_analysis.py`,
`src/kairos_ontology/core/claim_projection_sync.py`,
`src/kairos_ontology/core/status.py`,
`src/kairos_ontology/core/projections/medallion_dbt_projector.py`.

The original write-up derived `STUB` only when the projector's stub flag was on, so a
consumer that needed the aspirational/release facts with stubs **off** (status, the
`--strict` gate) had to force `stubs_enabled=True` — coupling two independent concerns
and risking divergence. `BindingAnalysis` is now the **one canonical materialization
result**, refined as follows (no behaviour change to feature-off output):

- **Aspirational is derived independently of stub emission.** `classify_binding`
  no longer takes `stubs_enabled`: an unbound, materialization-eligible, non-folded
  class is :data:`STUB` (aspirational) regardless of the flag. Stub *byte emission*
  is a separate gate — `BindingAnalysis.should_emit_stub()` = aspirational **and**
  `stubs_enabled`. The projector still emits stubs only under
  `--emit-aspirational-stubs`, so **feature-off output stays byte-identical**.
- **One result, one set of helper APIs.** `BindingAnalysis` exposes
  `is_aspirational`/`aspirational_class_uris` (status), `is_release_blocking`/
  `release_blocking_class_uris` (strict gate), `should_emit_stub`/`is_materialized`/
  `materialized_class_uris` (projection inclusion), plus `state`/`reason`. `build(...)`
  accepts a pre-computed `SourceBindings` so the dbt projector classifies from the
  **same** `compute_source_bindings` result it materializes from (no recompute, no
  divergent inline logic). `status` no longer forces `stubs_enabled=True`; the dbt
  projector's stub-emission and `__unbound_eligible__` release set are read from the
  canonical analysis.
- **Registry-fact filters are canonical too.** `materialization_eligible_class_uris`
  (unchanged rules) and the new `approved_imported_class_uris` are the single claim
  filters; `claim_projection_sync` consumes the latter (applying only its
  external-to-domain rule) instead of reimplementing the approved/imported/disposition
  test. The Claim Registry remains the sole eligibility authority (DD-094) — status,
  disposition, and type rules are unchanged.
- **Still derived, never persisted.** No field is added to `Claim`/`SilverImpact`;
  `core` still never imports `mdm`. Parity is covered by
  `tests/scenarios/test_scenario_binding_parity.py` plus the decoupling/reasons cases
  in `tests/test_binding_analysis.py` and the sync-delegation case in
  `tests/test_claim_projection_sync.py`.

### Addendum (2026-07-21): §11 open decision #4 resolved — one composed release gate (DD-101)

**Affects:** `src/kairos_ontology/core/lifecycle_gate.py`,
`src/kairos_ontology/core/binding_analysis.py`, `src/kairos_ontology/core/status.py`,
`src/kairos_ontology/cli/main.py` (`check-release`).

`docs/draft/silverfirstdesign.md` §11 open decision #4 asked for separate,
named states — *schema-valid vs bound vs data-valid vs release-eligible* — so a
stub's vacuous-green-CI risk could be told apart from real completion, and for
`--strict` to be "part of the design, not deferrable." `--strict` already blocked
release inside `run_projections`; this addendum makes the four states themselves
machine-readable **without duplicating that rule**:

- **schema-valid** — a class exists in the domain ontology (trivially true for any
  projected class; no new fact needed).
- **bound** / **release-eligible** — `binding_analysis.BindingAnalysis.is_bound` /
  `release_blocking_class_uris`, now reachable hub-side (no projection required)
  via `analyze_domain_from_hub`, and surfaced per-domain by both the `status`
  scan (`silver` phase facts) and the new `check-release` CLI / `lifecycle_gate`
  module (DD-101).
- **data-valid** — read (never re-derived) from the persisted
  `validation-report.json` via `status`'s `validate` phase fact.

`check-release` composes these with the existing claim/source-coverage/extension-
sync evaluators into one pass/fail decision, so a CI pipeline has a single command
to consult instead of separately running `check-claims`, `project --strict`, and
inspecting `status` output by hand. `project --strict` remains the enforcement
point for an actual projection run (unchanged); `check-release` is the read-only,
side-effect-free preflight/report that can run *before* a projection is attempted
or in `kairos-diagnose-status`/`kairos-flow` without generating artifacts.

---

## DD-097: Multi-domain dbt projection — shared-artifact reconciliation and peer-import authority (issue #220)

**Status:** Accepted
**Date:** 2026-07-21
**Affects:** `src/kairos_ontology/core/projector.py`,
`src/kairos_ontology/core/projections/medallion_dbt_projector.py`
**Implementation:** issue #220

### Context

A multi-domain hub with cross-domain FKs could not project a governed dbt package in
either supported scope:

1. **Full-hub projection** merged each domain's dbt artifacts with a blunt
   identical-bytes check (`_merge_identical_artifacts`). Several artifacts are
   package-level or shared, not domain-owned, and legitimately differ per domain:
   `dbt_project.yml`/`README.md`/`packages.yml` (per-domain fallback config),
   `models/gold/shared/dim_date.sql` and `_shared__gold_models.yml` (embedded the
   current domain's name/IRI/version), and per-source `models/silver/_{sys}__sources.yml`
   (filtered to *that* domain's mapped tables). Any second domain tripped a collision and
   no dbt artifacts were written.
2. **Domain-only projection** (`project --ontology consignment.ttl`) built the
   `hub_domain_namespaces` whitelist only from the *loaded* domains, so peer-domain
   `owl:imports` (booking/party/reference-data) were absent from the whitelist and the
   claim-authority gate reported them as `extra owl:imports` drift — even though they are
   required intra-hub imports, not claim-driven external reference models.

### Decision

- **Shared/package artifacts are orchestrator-reconciled, not collided.** A new
  `_merge_dbt_artifacts` classifier replaces the identical-bytes merge at the dbt
  per-domain merge site: package-level config is accepted last-wins (the orchestrator
  regenerates the definitive version once after the loop); per-source `_sources.yml`
  files are reconciled via a deterministic stable-sorted **union of their `tables`**
  (`_union_sources_yaml`); all other artifacts keep the strict identical-bytes check.
- **Conformed/shared gold is domain-neutral.** `dim_date.sql` and
  `_shared__gold_models.yml` render with a stable `domain_name="shared"` and a stable
  `gold_shared` schema, omitting per-domain IRI/version, so every domain emits identical
  bytes (the shared artifact is emitted once).
- **Peer-domain bases are always known to the authority gate.** `run_projections`
  collects `hub_domain_namespaces` from *every* on-disk hub domain ontology (via
  `_collect_hub_domain_bases` over the full `model/ontologies/` directory), independent
  of `--ontology` scoping, so required local peer imports are recognised as intra-hub and
  never flagged as drift.

### Rationale

Reconciling at the orchestrator (package-owning) layer preserves per-domain generation for
standalone/test callers while producing a single deterministic package. Making the
conformed dimension domain-neutral is also semantically correct — a shared dimension does
not belong to any one domain's gold schema. Sourcing the hub-domain whitelist from disk
(not from the loaded subset) mirrors the CLI sync path (`evaluate_projection_sync`), which
already scanned the full directory, closing the divergence between the two code paths.

### Consequences

- Full-hub and domain-scoped dbt projection both succeed on a multi-domain hub without
  weakening claim governance or hand-editing output.
- The conformed `dim_date` now materializes to `gold_shared` instead of the first domain's
  gold schema — a deliberate, more-correct placement for a conformed dimension.
- Regression coverage: `tests/scenarios/test_scenario_issue220.py` (full-hub no-collision,
  domain-neutral shared gold, domain-only peer-import gate) and
  `tests/test_dbt_artifact_merge.py` (merge/union helpers).

---

## DD-098: Alignment & projection correctness hardening (toolkit-optimizations F1–F7)

**Status:** Accepted
**Date:** 2026-07-21
**Affects:** `src/kairos_ontology/core/propose_alignment.py`,
`src/kairos_ontology/core/migrate_claims.py`,
`src/kairos_ontology/core/claim_registry.py`,
`src/kairos_ontology/core/completeness_model.py`,
`src/kairos_ontology/core/claim_coverage.py`,
`src/kairos_ontology/core/source_coverage.py`,
`src/kairos_ontology/core/inventory.py`,
`src/kairos_ontology/cli/main.py`,
`src/kairos_ontology/core/projections/shared.py`,
`src/kairos_ontology/core/projections/medallion_dbt_projector.py`,
`src/kairos_ontology/core/projections/medallion_silver_projector.py`
**Implementation:** `docs/draft/toolkitoptimizations.md` (issue #219 for F1)

### Context

Real hub work surfaced seven independent correctness/governance gaps in the
source→domain alignment and medallion projection pipeline. Each was reproducible
and mapped to a specific module. They are implemented together because they share
the registry-write and coverage-gate surfaces.

### Decision

- **F4 — URI backfill.** `write_claims_output` now threads an optional
  `inventory_dir` (default `hub_root/referencemodels-unpacked`) and builds a
  `load_inventory_uri_index(...)` passed to `alignment_to_registry`, so proposed
  claims carry resolved `class_uri`/`property_uri` without manual repair. No new
  CLI flag (backward-compatible default).
- **F5 — inventory scope.** `check-inventory` gains `--domains`/`--explain-scope`;
  the domain→inventory map is resolved through the catalog (source paths/model
  names), not guessed from affinity. Repo-wide checking stays the default;
  active-domain readiness is reported separately.
- **F6 — truncation integrity.** The 80-column prompt cap could silently drop
  columns. A deterministic **source column-set count + sha256** is persisted per
  `(system,table)` (`CoverageTable.source_column_count`/`source_column_sha256`);
  alignment post-processing reconciles **every** source column and synthesizes
  passthrough candidates for any unaccounted one; `ClaimCheckReport` gains a
  **blocking** `column_omissions` signal (not overloaded on `anchor_state`) that
  compares registry-covered columns against the affinity `total_columns` through
  the canonical completeness facts.
- **F2/F7 — grain conflict.** `likely_entity` (candidate-entity provenance) is now
  carried on `TableAlignment`, serialized in `alignment_to_dict`, and consumed in
  `alignment_to_registry` **before** class dedup. When ≥2 tables with *different*
  candidate entities collapse onto one `ref_class`, a blocking `grain_conflicts`
  record is emitted (new `ClaimRegistry`/`ClaimCheckReport` representation + gate).
  `class_claim_id` is deliberately **unchanged** (would disrupt property IDs and
  merges).
- **F3 — object-property target.** A deterministic range resolver
  (`_resolve_object_property_target`) detects object properties (PascalCase
  `rdfs:range` or curated name hints). When the governed target class resolves, the
  scalar mapping is kept (byte-identical); when it does **not**, the scalar column
  is downgraded to a passthrough custom claim and an
  `object_property_relationship_candidate` (target + cardinality) is emitted — one
  governed disposition per source column, no double count.
- **F1 — naming parity (#219).** A single shared physical-naming helper
  (`silver_schema_name`/`silver_table_name`/`silver_naming_convention` in
  `projections/shared.py`) is now consumed by **both** the silver DDL projector and
  the dbt projector, which previously hardcoded `silver_{domain}` and
  `camel_to_snake(local)`. The dbt gold `ref()` registry uses the actually-generated
  model name. Both targets now honour `silverSchema`/`silverTableName`/
  `isReferenceData`/`namingConvention` identically.

### Rationale

Each fix keeps default output **byte-identical when no new condition fires**
(mirrors DD-045/DD-070 gating): F1 defaults reproduce the old names, F3 only
downgrades when the target is ungoverned, F6 only blocks on a real shortfall, and
F2/F7 only fires on a genuine multi-entity collapse. All new gate/resolver paths
are deterministic (no LLM). `core` still never imports `mdm`.

### Consequences

- `check-claims`/`check-inventory` can now block on previously-silent omissions and
  grain collapses; hubs using the 80+ column path or ambiguous entity anchoring get
  actionable, deterministic diagnostics.
- dbt and silver physical names can no longer drift (issue #219).
- Regression coverage: `tests/scenarios/test_scenario_truncation_integrity.py`,
  `tests/scenarios/test_scenario_object_property_target.py`,
  `tests/scenarios/test_scenario_naming_parity.py`, plus unit tests in
  `tests/test_propose_alignment.py`, `tests/test_migrate_claims.py`,
  `tests/test_claim_coverage.py`, `tests/test_cli_inventory.py`.

---

## DD-099: Single typed projection target registry

**Status:** Accepted
**Date:** 2026-07-21
**Affects:** `src/kairos_ontology/core/projector.py`,
`src/kairos_ontology/cli/main.py`, `src/kairos_ontology/mdm/__init__.py`
**Implementation:** `TargetSpec` and `register_target()` in the core projector

### Context

Projection target metadata was repeated across `VALID_TARGETS`, an alias map,
medallion/architecture/post-domain sets, the `all` expansion, CLI choices, and a
separate external-target registry. Adding or renaming a target required coordinated
edits and could silently diverge in validation, dispatch, placement, or help output.

### Decision

Use one ordered, typed `TargetSpec` registry as the source of truth for canonical
names and aliases, exact output subdirectories and categories, execution phase,
`--target all` participation, and optional external discovery/project callbacks.
Derive the historical `VALID_TARGETS` list, canonical `all` expansion, alias
resolution, output routing, post-domain classification, external dispatch, and CLI
choices from that registry.

External packages register all metadata in one idempotent `register_target()` call.
Conflicting canonical names or aliases fail clearly. The CLI continues to import
`kairos_ontology.mdm` to trigger `mdm-profile` registration; core never imports MDM,
preserving the MDM-DD-002 one-way dependency.

### Rationale

One registration record makes target addition atomic and keeps user-visible order,
dispatch, and placement mechanically consistent. A typed external-dispatch field
retains extensibility without weakening the package boundary.

### Consequences

- Existing target order, output paths, `gold` → `powerbi`, CLI choices, and opt-in
  `mdm-profile` behavior remain unchanged.
- `VALID_TARGETS` remains available as a compatibility list but is refreshed only
  from the registry.
- External targets are excluded from `all` by default and can be registered
  repeatedly only when every metadata field and callback is identical.

---

## DD-100: Explicit one-shot migration for retired inventory & projection layouts

**Status:** Accepted
**Date:** 2026-07-21
**Affects:** `core/inventory.py`, `core/claim_projection_sync.py`,
`core/migrate_claims.py`, `core/propose_alignment.py`, `cli/main.py`
**Implementation:** the existing `kairos-ontology migrate` command

### Context

DD-054 introduced namespaced reference-model inventory names, while DD-083 introduced
Claim Registry-managed Turtle blocks. Their transitional runtime behavior still
self-healed old stem-named inventory files and relocated inline controlled Turtle triples
during ordinary reads/sync. That left two live formats, could silently discard ambiguous
collision content, and made routine projection sync a destructive migration path.

### Decision

Retired formats are converted only through the existing `migrate` command. It has an
idempotent `--check`/`--dry-run` plan, validates every input before publication, stages
writes in-place, and retains originals in
`.kairos-migrations/legacy-format-backups/` for rollback. Ambiguous stem collisions,
conflicting canonical files, malformed YAML, malformed managed markers, or Turtle that
cannot be surgically relocated abort the whole format migration without writing.

Canonical inventory readers require model-namespaced reference inventories. Canonical
projection sync requires Claim Registry-controlled imports/includes to be inside one final
managed block; it never converts or drops inline triples. The Claim Registry remains the
only authority for the generated block, while non-managed authored Turtle stays intact.
This supersedes only DD-083's automatic first-sync legacy-conversion clause, not its
managed-block ownership model.

### Consequences

- Existing hubs with retired state receive an actionable migration-required diagnostic
  instead of a best-effort repair. Run `kairos-ontology migrate --hub <hub>` and commit
  the reviewed result before normal inventory generation or claim projection sync.
- Rollback is explicit: restore files from `.kairos-migrations/legacy-format-backups/`
  and use the previous toolkit version if the retired runtime behavior is required.
  Forward correction remains preferred; a second migration run is a no-op.
- Backup creation and staged replacement ensure a failed multi-file conversion restores
  original files rather than leaving a partially migrated hub.

---

## DD-101: Consolidated deterministic lifecycle gate (`check-release`)

**Status:** Accepted
**Date:** 2026-07-21
**Affects:** `src/kairos_ontology/core/lifecycle_gate.py` (new),
`src/kairos_ontology/core/binding_analysis.py`, `src/kairos_ontology/core/status.py`,
`src/kairos_ontology/cli/main.py` (`check-release`), `.github/skills/kairos-flow/`,
`.github/skills/kairos-diagnose-status/`, `.github/skills/kairos-execute-project/`,
`.github/skills/kairos-help/`
**Implementation:** `core/lifecycle_gate.py` (`evaluate_lifecycle_gate`,
`LifecycleGateReport`), `check-release` CLI command

### Context

Release readiness was spread across independently-run checks: `check-claims`
(claim validity/freshness, source completeness, extension sync), `project
--strict` (aspirational release blockers, DD-096), and `kairos-ontology
validate`/`project` (validation, projection artifacts) — each with its own exit
code and text output, and no single machine-readable place to consult "may this
hub ship?". `kairos-diagnose-status` re-derived the bound-vs-aspirational split
by hand (SPARQL-ish TTL reasoning) instead of the canonical `BindingAnalysis`,
risking drift from DD-096's D4 authority. DD-096 §11 open decision #4 explicitly
asked for this consolidation ("make `--strict` block release... this gate is
part of the design, not deferrable").

### Decision

Add one deterministic, read-only, side-effect-free entrypoint,
`lifecycle_gate.evaluate_lifecycle_gate`, exposed as `kairos-ontology
check-release`, that **composes** — never re-derives — the existing evaluators:

- **claim validity/freshness** (+ MDM-anchor/deviation/ownership/passthrough
  governance) — the literal `claim_coverage.check_claims_coverage` result.
- **source completeness** — the literal `source_coverage.check_source_coverage`
  result.
- **extension sync** — the literal `claim_projection_sync.evaluate_projection_sync`
  result (consumed via its public API only; the module itself is not modified).
- **aspirational release blockers** (DD-096) — a new shared
  `binding_analysis.analyze_domain_from_hub(hub_root, domain)`, which lifts the
  "load claims + ontology + Silver-ext + sources + mappings, then run the
  canonical `build()`" logic that was inlined in
  `status._domain_aspirational_stubs` into one reusable, hub-relative entrypoint.
  `status.py`'s D4 behavior is unchanged (`_domain_aspirational_stubs` is now a
  thin wrapper); the gate calls the same function to additionally read
  `bound_classes`/`reasons`, so status and the gate can never diverge on "is this
  bound?".
- **validation** and **projection** — read from `status.scan_hub_status`'s
  `validate`/`project` phases (never re-run).

`LifecycleGateReport.is_blocking` is a pure `OR` of each section's own blocking
signal (`ClaimCheckReport.is_blocking`, `SourceCoverageReport.is_blocking`,
`ProjectionSyncReport.is_blocking`, any domain's `release_eligible is False`,
`validation.passed is False`) — no new blocking rule is invented. Every section's
`to_dict()` projection keeps the original field names, so the reasons a caller
sees are byte-identical to running `check-claims`/inspecting `status` directly.

`core/status.py` gains additive, versioned (`schema_version: 2`) per-instance
`facts` so it remains the sole machine truth for objective per-phase/instance
state (see the DD-080 addendum); `lifecycle_gate.py` is the composition layer on
top, not a second source of truth. No AI/LLM calls; no claim is auto-approved; no
`aspirational`/`bound`/`release_eligible` flag is persisted — everything is
recomputed on every call.

### Rationale

Reusing each evaluator's own return value keeps one implementation of every rule
(claim governance stays in `claim_coverage.py`, mapping coverage in
`source_coverage.py`, sync drift in `claim_projection_sync.py`, binding
classification in `binding_analysis.py`) while still answering the
cross-cutting "ship or not" question in one call. Reading validation/projection
facts from the committed `status` scan rather than re-running either keeps the
gate side-effect-free and fast enough to call from `kairos-flow`/
`kairos-diagnose-status` on every resume. Composing via a pure `OR` means adding
the gate can only ever surface a pre-existing blocking condition earlier — it
cannot introduce a new way to block that a standalone `check-claims`/`project
--strict`/`validate` run would not already have flagged.

### Consequences

- One new CLI command, `check-release` (`--format text|json`, `--warn-only`,
  and the same scope/skip flags as `check-claims`), exempt from the skill-gate
  like `check-claims`/`status` (deterministic, AI-free, read-only).
- `kairos-flow`, `kairos-diagnose-status`, and `kairos-execute-project` are
  updated to consume `status`/`check-release` output for proposed/approved/
  aspirational/bound/release-eligible/validation facts instead of restating or
  hand-deriving them.
- `docs/draft/silverfirstdesign.md` is reconciled as the shipped reference
  design. Its §11 now lists only genuinely deferred extensions.
- Regression coverage: `tests/test_lifecycle_gate.py` (unit + CLI), the
  `facts`-focused additions to `tests/test_status.py`, and the complete
  `tests/scenarios/test_scenario_silver_first_e2e.py` lifecycle.

---

## DD-102: dbt projector decomposed into five deterministic phases

**Status:** ~~Superseded by [DD-110](#dd-110-typed-projection-contract-and-silver-output-parity)~~
**Date:** 2026-07-21
**Affects:** `src/kairos_ontology/core/projections/medallion_dbt_projector.py`,
`src/kairos_ontology/core/projections/dbt/` (new subpackage)
**Implementation:** `core/projections/dbt/{context,bind,normalize,shape,materialize,render}.py`;
`generate_dbt_artifacts` rewritten as a thin orchestrator; phase-level tests in
`tests/test_dbt_phases.py`

### Context

`medallion_dbt_projector.py` had grown to ~3.9k lines and its public entrypoint
`generate_dbt_artifacts` was a monolithic *policy hub*: graph/extension merge, FK
classification, source/mapping parsing, contracted virtual-source resolution,
`SourceBindings`, the canonical `BindingAnalysis`, per-class column/FK shaping, SCD
/ materialization selection, release-gate metadata, and final artifact assembly +
validation were all interleaved in one flow (and, per class, inside
`_gen_silver_models`). Policy was re-derived at several points and the render step
still read the RDF graph, so there was no auditable boundary between "decide" and
"emit". This blocked the shared-tree work (deterministic context, TargetSpec
registry, canonical completeness/materialization, explicit legacy migrations,
shared FK normalization) from landing on a clean seam.

### Decision

Turn `generate_dbt_artifacts` into an **orchestrator** over five explicit,
ordered phases that exchange typed, **immutable** (`frozen=True`) intermediate
models defined in `core/projections/dbt/context.py`:

`bind → normalize → shape → materialize → render`

- **bind** (`bind.py` → `BoundSources`) — takes the committed `DbtInputs`, commits
  the ext-merged working graph (silver-ext / ref-model-default / peer triples are
  merged here because source binding needs them), parses source `systems` + SKOS
  `mappings`, resolves the active contracts + contracted virtual sources
  (`virtual_table_uris` / `replacement_input_uris`), and computes the canonical
  `SourceBindings`.
- **normalize** (`normalize.py` → `ProjectionContract`) — derives the FK
  descriptors (`classify_foreign_keys`) and the canonical `BindingAnalysis`
  **grounded in** the bind phase's `SourceBindings` (never re-derived), plus the
  Silver naming convention + ontology URI.
- **shape** (`shape.py` → `ShapedProject`) — produces sources, Silver models
  (+ warnings + entity metadata), schema YAML, the Silver registry, Gold star
  schema + schema YAML, coverage data, and macros. FK/binding *policy* is read from
  `ProjectionContract`/`SourceBindings` (threaded into `_gen_silver_models` via new
  optional `bindings=` / `analysis=` args) rather than reclassified.
- **materialize** (`materialize.py` → `MaterializationPlan`) — owns the
  orchestration-level release metadata (`unbound_eligible_names` → the
  `__unbound_eligible__` sentinel, DD-096 / DEC-1) and the per-domain project
  configuration.
- **render** (`render.py`) — assembles the final `{path: content}` map from the
  committed `ShapedProject` + `MaterializationPlan` (strings/sets/dicts only) and
  runs post-generation validation. Its signature is `(shaped, plan)` — it is
  structurally incapable of rereading RDF/mappings or reclassifying policy.

**Byte-parity is a hard constraint.** Public output and APIs are unchanged: all
existing public functions and direct test imports (`generate_dbt_artifacts`,
`generate_dbt_project_config`, `write_dbt_session_log`, `compute_source_bindings`,
`SourceBindings`, `_parse_bronze`, `_parse_skos_mappings`, `_gen_silver_models`,
`_extract_silver_columns`, `_validate_dbt_artifacts`, …) remain in
`medallion_dbt_projector.py` as compatibility facades. Feature-off and stub-on
outputs are byte-identical to the pre-refactor baseline (verified by hashing the
full artifact maps of the acme-hub `client` (default + stub-off + stub-on),
`invoice`, and `logistics` scenarios, plus the two-process determinism probe).

### Rationale

Extracting *phase boundaries* first (with the leaf helpers left in place and
invoked by the phase functions via lazy imports) makes the decomposition provably
byte-safe: the same helpers are called with the same arguments in the same order,
so the emitted strings — and the deduplicated projection-report warnings — are
unchanged. Threading the already-committed `SourceBindings`/`BindingAnalysis` into
`_gen_silver_models` (additive, defaulted args) removes the double-derivation
without altering behaviour. A frozen render input is the cheapest possible proof
that emission no longer depends on policy.

### Consequences

- New internal subpackage `core/projections/dbt/`; no public API or artifact path
  changed; no broad renames/deletions.
- **Retained debt (deliberate, documented):** the heavy leaf helpers (notably
  `_gen_silver_models`, `_gen_schema_yaml`, `_gen_gold_models`) still live in
  `medallion_dbt_projector.py`, and per-model shape/materialize/render remains
  interleaved inside `_gen_silver_models` (SQL/templates were **not** redesigned per
  scope). The graph/extension *merge* is committed at the bind boundary (source
  binding needs it) while the derived *contract* is owned by normalize. Further
  lifting of template rendering out of the shaping helpers is future work on this
  now-explicit seam.
- Phase-level regression coverage in `tests/test_dbt_phases.py` (immutability,
  deterministic ordering, phase-boundary/input constraints); output parity is
  covered by the scenario/golden/determinism suites, including the complete
  Silver-first lifecycle in `tests/scenarios/test_scenario_silver_first_e2e.py`.

---

## DD-103: Canonical ontology closure and versioned semantic index

**Status:** Accepted
**Date:** 2026-07-21
**Affects:** ontology loading, catalogs, inventories, validation, projection, alignment,
reporting, status, prompt context, and managed design skills
**Implementation:** `core/ontology_loader.py`, `core/semantic_index.py`, compatibility
facades in `core/catalog_utils.py`, and consumer-specific adapters

### Context

Semantic consumers currently parse different ontology subsets: one file, root plus direct
imports, caller-merged graphs, or materialized single-file inventories. This makes
validation, design, alignment, projection, and LLM context disagree about term identity,
inheritance, provenance, and import completeness. Missing imports are warnings, so a
plausible artifact can be produced from partial knowledge.

### Decision

`load_ontology()` is the single public semantic-loading API. It resolves the complete
catalog-backed `owl:imports` closure with deterministic worklists and cycle guards and
returns a graph, import manifest, structured diagnostics, completeness flag, closure hash,
and versioned semantic index.

Every `owl:imports` edge is required by default. Callers may classify exact import URIs as
optional through explicit loader policy. `file://` imports are unsupported required imports
unless explicitly optional. Missing required imports fail closed; explicit degraded mode
returns `complete=false` and must be disclosed by every resulting report or artifact.
The legacy `load_graph_with_catalog()` facade temporarily opts into degraded mode to
preserve warning-and-continue behavior while consumers migrate.

Closure hashes sort manifest records and hash ontology version, source bytes, and stable
source identity. Identity is the declared ontology IRI, otherwise the import URI, and for
an IRI-less root only, a POSIX path relative to a declared identity root. Absolute paths,
timestamps, and traversal order never enter the hash.

Supported semantic profiles are explicit:

- `asserted`: parsed triples from the complete import closure;
- `rdfs`: transitive class/property hierarchy and supported domain/range consequences;
- `kairos-design`: RDFS plus Kairos-used equivalence, inverse, individual, restriction,
  intersection, and union constructs;
- `owl-rl`: opt-in standards-based OWL RL materialization.

Semantic-index and inventory schemas are independently versioned. Full URI is the sole
identity key; local names are display data. Every derived fact records asserted/inferred
and source/import provenance. Syntax-only validation remains a direct single-file parse.

Imported semantic breadth never widens physical projection breadth. Claims and extension
policy remain the reviewed materialization allow-list.

### Rationale

A complete, deterministic closure makes every consumer reason over the same evidence.
Explicit profiles avoid claiming unrestricted OWL DL support. Fail-closed defaults prevent
silent partial semantics, while the temporary lenient facade allows incremental migration
without breaking existing hubs.

### Consequences

- Semantic consumers must declare a profile and may no longer parse domain/reference
  ontologies independently.
- Existing inventory schema 1.1 requires a one-time explicit regeneration before
  closure-hash freshness is enforced.
- SHACL and projection become stricter when migrated; missing-import diagnostics and
  explicit degraded mode are part of that user-visible transition.
- Catalog/import cycles terminate deterministically and remain visible in diagnostics.
- Structured CLI inspection and prompt slices replace raw Turtle interpretation for
  semantic decisions.
- The v5 `EntityBinding` compiler resolves bound-class properties through this semantic
  index under the `rdfs` profile so subclass-inherited, cross-namespace imported properties
  are bindable without local redeclaration; see the DD-108 amendment (2026-07-28). Per the
  breadth principle above, such inherited properties are physically materialized only when a
  binding field explicitly binds them.

### Amendment (2026-08-14): the agent-facing boundary, and its limits

DD-103 above is a decision about the toolkit's own loading API. The scaffolded
`.claude/settings.json` is a separate, previously undocumented artifact invented to make that
decision hold for one agent runtime. It was never described here, and its original form denied
only `*.ttl` — while the toolkit itself treats `.rdf` as a first-class ontology serialisation
(`core/validator.py`, `core/projector.py` both glob `**/*.rdf` alongside `**/*.ttl`) and a fetched
reference-model tree is 297 `.rdf` files to 112 `.ttl`. The majority of raw ontology was therefore
outside the boundary. Recording the boundary properly:

- **Covered serialisations** are `.ttl`, `.rdf` and `.owl` — the set in `_EXTENSION_FALLBACK`
  (`core/catalog_utils.py`). `.n3`/`.nt`/`.jsonld`/`.trig` are loadable in principle but absent from
  every published tree; add them when they appear rather than pre-emptively.
- **Deliberate carve-outs.** `.json` stays readable: the reference-model tree carries 19 JSON
  *Schemas* consumed by `core/archetype_loader.py` and `core/binding_archetypes.py`, and no JSON-LD
  ontologies exist in it. `.xml` stays readable because the only match is
  `ontology-reference-models/catalog-v001.xml`, which an agent must read to register a domain.
  Bronze source vocabularies under `integration/sources/` and the business-glossary template also
  stay readable — they are required design inputs, not reference ontology.
- **Rule anchoring is load-bearing and was wrong.** A `./`-prefixed permission path anchors to the
  *current working directory*, not the project root, and this toolkit deliberately supports being run
  from inside `ontology-hub/` (DD-064). Rules are now emitted in both `/`-anchored and `./`-anchored
  form so the boundary cannot be escaped by choice of cwd.
- **`Grep(...)` rules may be inert.** Permission matching is documented against `Read`/`Edit` only,
  with `Read` covering search tools on a best-effort basis. Rather than rely on that, both prefixes
  are emitted; the redundancy is intentional and should not be "tidied" away without measuring the
  installed runtime first.
- **This is a guardrail, not a sandbox.** Permission rules scope *tool names*, so shell access
  (`cat`, `Get-Content`, `git show`) still reaches every one of these files, and a subprocess's
  `open()` is unaffected — which is precisely why the toolkit's own in-process rdflib reads keep
  working under a maximal deny list. Agents other than Claude Code are bound only by the prose
  prohibition carried in `copilot-instructions.md` and the design skills.
- **Propagation.** The file cannot use the managed-marker mechanism, because the marker is an HTML
  comment and settings JSON that fails validation is rejected *as a whole* — a stamped marker would
  silently void every rule. `update` therefore recognises previously-shipped generations by SHA-256
  and replaces only those, leaving a hand-extended file untouched with an advisory. A hub that
  predates a boundary change and has local edits will not converge on its own, by design.

---

## DD-104: Reference-module activation, managed imports, and portable Silver contracts

**Status:** Accepted
**Date:** 2026-07-22
**Affects:** claim projection sync, accelerator data-domain parsing, ontology validation,
projection preflight, module activation inventories, and Silver/dbt contract generation
**Implementation:** `core/reference_modules.py`, `core/claim_projection_sync.py`,
`core/validator.py`, `core/projector.py`, `core/projections/medallion_dbt_projector.py`,
`core/projections/medallion_silver_projector.py`, and dbt templates

### Context

Claim-driven import synchronization inferred ontology IRIs by trimming class URIs and
ignored imported property/relationship claims and configured accelerator modules.
`data-domains.yaml` retained only parallel URI/label lists, so it could not enforce module
versions, roots, projection selection, or accepted transitive dependencies. The canonical
loader detects unresolved declared imports, but cannot diagnose a required import edge
that was never written.

### Decision

Reference modules use typed, version-pinned profiles. A profile declares the catalog and
ontology document IRIs, term namespaces, reviewed roots, descendant policy, exclusions,
an explicit projection allow-list, default-annotation sources, accepted transitive
dependencies, and the local-extension boundary. Legacy `imports[].uri/module` entries
remain readable through a compatibility profile.

One deterministic import plan unions approved imported class, property, and relationship
claims external to the domain namespace with data-domain module activation. Catalog
resolution and the ontology's declared
`owl:Ontology` identify document IRIs; term namespaces ending in `#` are never emitted as
managed imports. Claims remain the governed materialization authority, while module
profiles may provide an explicit source-neutral default allow-list.

Module-selection evidence is collected from selected hub ontology files and Claim
Registries before recursive ontology loading. Imports discovered only inside a
loaded reference-module closure are transitive implementation facts, not authored
direct-import evidence, and never force a duplicate direct import into the hub.

Managed synchronization owns only its final generated block and preserves authored Turtle
outside it. Validation and projection preflight report the external term, owning ontology
IRI, managed source, and claim where available. Missing required imports fail semantic
operations unless degraded mode is explicitly selected.

Activation inventories serialize closure/module hashes and available, selected, excluded,
inherited, and projected term states in URI order. They contain references and provenance,
not copied ontology definitions.

Accelerator defaults define semantic contracts, not source-specific SQL. Every bound Silver
model must supply the identity inputs required by its DD-108 strategy on every source branch;
natural keys are never invented. SCD2 validity uses timestamp precision and sequences multiple
source versions into contiguous validity windows; parent FK resolution declares `current` or
`as-of` semantics, and relationship changes participate in child change detection unless
explicitly disabled.
Current joins filter the parent to its current version; as-of joins require an explicitly
mapped parent effective-time column.

Every normal final Silver row carries `_source_system`, `_source_record_key`, and
`_loaded_at`. Source-record identity uses source/table scope plus the declared Bronze primary
key; a missing source primary key is blocking and never falls back to a business or generated
Silver key.
Generated contracts expose grain, lineage, SCD, relationship, accelerator/default-package,
toolkit-version, and hub-override provenance. Fabric and Databricks may render different SQL
and physical types, but must expose the same semantic columns, keys, relationships, and
tests.

### Rationale

Typed profiles remove namespace heuristics, make activation reproducible, and keep broad
semantic imports independent from narrow physical projection. A shared plan prevents the
domain-design workflow, CLI sync, validator, and projector from implementing divergent
import rules.

### Consequences

- New profiles require an exact version pin; legacy profiles remain unpinned for backward
  compatibility.
- Ambiguous ownership, profile term drift, ontology-IRI mismatch, and version mismatch are
  blocking structured diagnostics.
- Claim synchronization and projection preflight share the same direct,
  domain-scoped evidence collector, so closure loading cannot make their import
  expectations diverge.
- Imported definitions remain in their source modules. Self-contained deployment bundles,
  if ever required, must be separate derived output.
- Activation inventory output is deterministic and omits timestamps.
- Bound models without complete natural-key mappings are rejected instead of
  producing invalid incremental rows.
- Multi-source models implement their declared SCD lifecycle and preserve source identity
  before unioning conformed rows.
- Portable identifier validation may reject previously accepted warehouse-specific schema,
  table, column, or FK names.
- As-of FK resolution is unavailable without an explicit effective-time mapping; the
  projector fails rather than silently substituting load-time semantics.

---

## DD-105: Imported dbt evidence is governed before Mapping and Silver

**Status:** Accepted
**Date:** 2026-07-22
**Affects:** source onboarding, transformation planning, lifecycle status and release gates,
Mapping/Silver preflight, custom dbt contracts, adapter validation, and accelerator selection
**Implementation:** `core/transformation_candidates.py`, `core/status.py`,
`core/lifecycle_gate.py`, `core/dbt_contracts.py`, `core/dbt_contract_sync.py`,
`core/reference_modules.py`, CLI commands, and lifecycle skills

### Context

Imported authored SQL can reveal joins, aggregation, ranking, survivorship, or a changed row
grain before a governed custom dbt contract exists. The lifecycle previously considered only
executable contracts under `integration/transforms/dbt/`, so Mapping and Silver could proceed
without assessing imported transformation evidence. SQL found in prototypes or downstream
Power BI parity projects must remain evidence; discovery alone cannot make it executable,
assign a semantic target, or grant source-replacement authority.

Three related contract/preflight defects also surfaced: generated virtual-source nullability
ignored explicit non-key `not_null` tests, contracts were forced to declare both supported
warehouse adapters, and scoped validation/projection did not consistently resolve the hub's
accelerator context.

### Decision

Explicit repository-contained SQL/dbt roots are inventoried into the committed,
non-executable planning artifact
`model/planning/dbt-transformations/candidates.yaml`. The artifact declares
`projection_authority: false`. Normalized repository-relative model paths are stable
candidate identities; SHA-256 is a separate freshness signal. Content changes force
reassessment, while a rename produces an orphan and a new candidate requiring explicit
re-linking.

The inventory separates deterministic observations (path, checksum, model references,
source references, operation signals, and explicit grain metadata) from governed decisions
(grain interpretation, semantic target, authority class, replacement scope, disposition,
rationale, confidence, evidence, and approval). Power BI and migration/parity evidence never
become source authority by location or SQL complexity.

Every governed disposition records the artifact checksum it assessed. Implemented candidates
also record the discovered dbt contract model name explicitly, so contract identity is not
coupled to an imported artifact filename.

`dbt-transformation` remains a checkpoint implemented by the existing
`kairos-develop-dbt-transformation` skill and OKF phase-log directory; it is not added to
`PHASE_ORDER`. `status` reports additive candidate facts but remains observational.
`check-transformation-readiness --stage mapping|silver` is the deterministic, non-writing
preflight authority. Mapping and Silver skills must stop on a non-zero result and route to
the transformation checkpoint.

The readiness evaluator is also a first-class component of `LifecycleGateReport`; its
`is_blocking` participates in the gate's existing OR composition without duplicating rules
inside `lifecycle_gate.py`. Because this broadens the meaning of the aggregate release
decision, the lifecycle-gate report schema is versioned accordingly. Hubs without a
candidate inventory retain existing behavior.

Accepted/implemented candidates reuse the DD-092/DD-093 authority path:
`DbtContractModel`, `meta.kairos.replaces_sources`, synchronized custom-transform vocabulary,
SKOS mapping, and `silverSourceRef`. The candidate inventory does not duplicate executable
contract authority.

Contract columns retain explicit `not_null` tests/constraints. Natural-key membership and
explicit `not_null` independently imply non-null virtual columns. Contracts may declare any
non-empty valid subset of supported adapters; projection configuration selects the active
adapter and rejects a model that does not support it. Accelerator resolution follows
explicit CLI option, then hub configuration, then unambiguous single-pack inference.

### Rationale

A committed planning artifact makes decisions reviewable and machine-readable without
turning raw imports into runtime code. Separating observations from decisions prevents static
SQL heuristics or LLM interpretation from becoming semantic authority. Reusing the existing
contract/replacement path keeps one implementation authority, while a dedicated preflight
command provides a concrete testable gate instead of relying on skill prose.

Keeping the checkpoint outside the canonical phase order avoids destabilizing deterministic
status semantics and mirrors other advisory planning artifacts. Independent adapter,
nullability, and accelerator fixes remain reviewable without coupling them to candidate
inventory internals.

### Consequences

- Source onboarding inventories only roots explicitly selected by the user; broad recursive
  scanning of all imported archives is intentionally unsupported.
- Imported SQL stays in place and is never copied into the executable dbt bundle
  automatically.
- Changed or orphaned candidates remain visible and require reassessment/re-linking.
- Mapping/Silver automation must invoke the deterministic readiness command before writes.
- Release checks can newly fail when governed transformation evidence remains unresolved.
- Single-adapter contracts are valid, but projection fails for a selected unsupported
  adapter.
- Required non-key contract columns now project as non-null in managed virtual vocabularies.
- Ambiguous accelerator installations require explicit CLI or hub configuration.

---

## DD-106: Immutable Bronze and Mandatory Logical Source Preparation

**Status:** Accepted
**Date:** 2026-07-25
**Affects:** source onboarding, dbt projection, source vocabularies, JSON expansion,
scaffold layout, source/Silver skills
**Implementation:** `scaffold/kairos-prep.ttl`,
`integration/preparation/{source}-prep.ttl`, and the typed
`core/projections/dbt/{policy_normalize,shape,materialize,prep_renderers}.py` pipeline.
Normative companion: [`dd-106-medallion-engineering-policy-v1.md`](dd-106-medallion-engineering-policy-v1.md)

### Context

DD-014 removed generated staging and made Silver read Bronze directly. In practice this
mixed physical source cleanup with semantic conformance and made repeated renames, casts,
sentinel handling, reserved identifiers, CDC normalization, and JSON extraction part of
Silver or mappings. DD-039 then added a special `bronze_expanded` exception rather than
a coherent preparation boundary.

### Decision

Supersede DD-014 and DD-039. Bronze remains immutable raw source evidence. Every mapped
source table has a source-owned prep contract under `integration/preparation/` and
declares exactly one mode:

- `passthrough` — no physical prep model, allowed only after fail-closed validation finds
  no normalization rule or known risk; or
- `normalize` — emit a physical `stg_{source}__{table}` model.

Prep may normalize physical names and types, trim values, handle evidenced sentinels,
normalize source CDC fields, create a source-scoped `_source_record_key`, and extract
JSON. It must not join sources, aggregate, assign business meaning, perform survivorship,
or assert cross-source entity equivalence. Parent prep preserves parent grain. Scalar
JSON may flatten into that row; arrays become separately keyed child relations with
declared grain. Raw payload or a replayable raw reference is retained.

The domain ontology remains JSON-agnostic. Source and prep contracts retain JSON
provenance because parsing and schema-drift behavior are physical source concerns.

### Rationale

A mandatory logical boundary gives every source the same review point without paying for
empty physical models. Explicit pass-through prevents absence of configuration from
being mistaken for safety. Technical consistency remains separate from reusable Silver
business semantics.

### Consequences

- Add a new prep vocabulary, shapes, scaffold folder, status evidence, and projection
  specs.
- Remove the standalone JSON-only `generate-staging` path, `bronze_expanded`, and
  ordinary-prep use of manual `silverSourceRef`.
- DD-006 remains valid for column-level JSON detection; processing moves to prep.
- DD-015 remains the raw Bronze authority; prep TTL becomes the technical-normalization
  authority.
- DD-018, DD-026, DD-038, DD-074, DD-092, DD-093, DD-104, and DD-105 are amended by this
  boundary as summarized in the companion policy.
- Existing hubs are not migrated; only fresh scaffold layout is supported.

---

## DD-107: Safe Mapping Expressions and Transformation Authority

**Status:** Accepted
**Date:** 2026-07-25
**Affects:** `kairos-map`, mapping validation/rendering, contracted dbt transformations,
transformation readiness and skills
**Implementation:** `dbt/mapping_{specs,bind,normalize,renderers}.py` provides the
immutable v2 AST, graph-only binding, fail-closed semantic validation, approved macro
registry, Fabric/Databricks rendering, prep symbol binding, capability/release evidence,
and approved-contract transformation routing. `kairos-map` v2 and its SHACL shapes remove
the former raw-SQL terms; source-technical dedupe moved to `kairos-prep:TechnicalDedupe`.

### Context

Normal mappings currently accept free-form SQL transforms and filters. This can hide
adapter-specific behavior, unsafe quoting, nondeterminism, joins, subqueries, row loss,
or grain changes inside a surface intended for column alignment.

### Decision

Normal mapping expressions are typed, deterministic, column-bounded expressions or
approved namespaced macros. Validators resolve every identifier, literal, output type,
null behavior, and adapter capability. Literal values are rendered safely.

Mappings must reject arbitrary SQL, comments or statement separators, subqueries, joins,
windows, aggregation, nondeterministic functions, and undeclared row/grain changes.
Technical cleanup belongs in prep. Relational, grain-forming, complex fallback,
deduplication, and contribution-building logic belongs in DD-092 contracted dbt.

Contracted transformation authoring is iterative: profile evidence, define and approve
grain/identity/output contract, implement against representative fixtures or a working
flow, execute tests, then synchronize and map the proven virtual source. The approved
contract remains acceptance authority; working SQL alone does not establish semantics.

### Rationale

A constrained expression surface is portable and statically reviewable. dbt remains the
right execution language for relational logic without turning RDF annotations into a
second workflow engine.

### Consequences

- Replace free-form mapping SQL with a typed grammar; no compatibility parser is added.
- Amend DD-092, DD-093, and DD-105 to require the iterative evidence/execution order.
- Mapping/Silver readiness blocks unsafe expressions and unresolved transformation
  candidates.

---

## DD-108: Identity, Lineage, Multi-Source Conformance, and MDM Boundary

**Status:** Accepted
**Date:** 2026-07-25
**Affects:** Silver extensions, mappings, dbt contracts, multi-source models, lineage,
MDM boundary and reports
**Implementation:** `EntityIdentitySpec`, `LineageSpec`, and `MultiSourcePolicySpec`
are normalized fail-closed from authored policy. Silver SQL/schema authority, release
metadata, Gold inputs, optional contribution-lineage and reconciliation relations use the
same immutable specs. Integration identity is emitted only for reviewed exact equivalence;
externally mastered identifiers produce routing metadata only.

### Context

“Warehouse identity” conflated business identity, source identity, physical join keys,
and ontology IRIs. Mandatory natural keys can force false identity, while current
multi-source `UNION ALL` can collapse overlapping identifiers without governed
equivalence. Composite rows retain only driving-row lineage.

### Decision

Every materialized entity declares grain, identity strategy, key scope, and
change-detection strategy. Supported identity strategies are:

- business key;
- source-scoped immutable key;
- deterministic integration key;
- externally mastered identifier; or
- surrogate-only identity with an explicit reconciliation limitation.

Prep emits `_source_record_key` from source/table scope and declared source PK; it never
asserts business equivalence. Silver may emit a physical surrogate/integration key only
from approved exact-equivalence rules. Surrogate keys are join keys, not business
identity or an incremental prerequisite.

Ontology document/term IRIs, optional entity-instance IRIs, source-record identity, and
physical SKs are separate fields. Source identity must never silently fall back to a
business SK. `_loaded_at`, `_ingested_at`, `_source_updated_at`, and
`_source_effective_at` remain distinct timestamps.

Multi-source entities declare disjoint/overlapping branches, normalization, exact
equivalence, source precedence, conflicts, deletion, late arrival, and reconciliation.
Contracted transformations expose every contributing source-record fact; the normalized
Silver contract owns the canonical contribution-lineage relation and the generated
Silver wrapper emits it. Probabilistic/fuzzy matching, persistent enterprise IDs,
merge/split, and survivorship remain exclusively in the MDM runtime and existing
`kairos-mdm` policy.

### Rationale

Identity roles have different scopes and lifecycles. Making them explicit prevents a
union, similar display identifier, or schema-level `skos:exactMatch` from becoming
unreviewed row-level equivalence.

### Consequences

- The identity-strategy deferral in DD-034 is superseded.
- DD-018, DD-026, DD-074, DD-092, DD-093, and DD-104 are amended.
- Multi-source schema alignment is no longer described as semantic conformance by
  itself.
- Every composite transformation exposes complete contribution lineage.

### Amendment (2026-07-28): identity keys are target OUTPUT columns; compile-time resolution uses the semantic index

Two coupled compile-time defects are corrected in the v5 `EntityBinding` compiler
(`core/compiler/adapter.py`, `core/compiler/kernel.py`).

**1. Business/natural identity is decoupled from source column names.** `identity.sourceKey`
and `identity.businessKey` enumerate **source** columns, but the identity fact (`naturalKey`,
which drives generated surrogate/integration keys, business grain, identity roles, and render)
previously baked those **source** names into the identity. That only compiled when
`camel_to_snake(source_column) == camel_to_snake(target_property_local_name)` — a coincidence
of the canonical fixture. The adapter now resolves each ordered identity key component to the
**target OUTPUT column** it is mapped to (via the field whose expression is exactly that source
column) *before* constructing `EntityIdentityFact`, so downstream consumers receive coherent
output-named identity. `identity.sourceKey` is unchanged for `_source_record_key` and
conformance. Emitted silver/dbt column names are now the snake-cased target property local name
(`camel_to_snake(...)`), matching the graph projection path and the `naturalKey` normalization;
this is idempotent for already-snake property names. An identity key component that maps to no
field, to more than one target output, or only inside a multi-column expression is a specific,
actionable diagnostic (`identity.authored-key-not-supplied`,
`identity.ambiguous-key-mapping`, `identity.key-column-in-expression`) rather than a silent
source-named key. The quality-column and `identity.authored-key-not-supplied` diagnostics are
made actionable (they name the source column, the mapped target/output, or state that none
maps).

**2. Compile-time binding resolution uses the DD-103 semantic index under a non-asserted
profile.** The kernel previously loaded the ontology under the default `ASSERTED` profile and
resolved a bound class's properties with the exact-domain / exact-namespace helpers in
`ontology_ops` (`list_classes`/`list_properties`), which do not walk `rdfs:subClassOf`. A hub
subclass therefore could not bind an inherited reference property whose `rdfs:domain` is an
ancestor class in an imported namespace without redeclaring it locally. The kernel now loads
with `SemanticProfile.RDFS` (the minimal profile that populates subclass-inherited properties)
and resolves each bound class's direct **and** inherited, cross-namespace properties through the
semantic index closure (`SemanticIndex.class_properties`). Each inherited resolved property is
made applicable to the bound subclass in the resolved-symbol layer (the bound class URI is added
to its `domain_uris`); the ontology graph is never rewritten. The exact-domain/namespace
`ontology_ops` helpers remain for inventory / non-binding uses only and must not be used for
structure-aware binding resolution. Consistent with **DD-103**, imported *semantic* breadth must
not silently widen *physical* projection breadth: inherited properties are materialized **only**
when explicitly bound in an `EntityBinding` field, never auto-emitted. Binding targets remain
hub-namespace classes; imported ancestor classes are not themselves binding targets. Because
inherited cross-namespace properties can share a local name, an authored field ref that resolves
to more than one distinct property URI is a compile diagnostic (`binding.ambiguous-property`);
callers qualify the field with the owning namespace (full URI or a bound prefix) to disambiguate.
Unambiguous resolution is unchanged.

---

## DD-109: Temporal Execution, Canonical Hashing, and FK Resolution

**Status:** Accepted
**Date:** 2026-07-25
**Affects:** incremental dbt models, SCD, CDC, row hashes, temporal FKs, runtime
determinism and generated tests
**Implementation:** complete for the shared typed/dbt runtime authority: fail-closed
`HistorySpec`/incremental/CDC policy, canonical hash codec v1 and golden vectors,
`TemporalRelationshipSpec`, Fabric/Databricks physical plans, dedicated SCD1/SCD2
renderers, generated dbt tests/quarantine artifacts, and release evidence. Shared
Silver DDL parity remains DD-110 follow-on debt.

### Context

DD-025 defined SCD1/SCD2 but not late events, corrections, deletes, replay, backfill,
same-time ordering, or valid time versus load time. Current row hashing conflates values
under adapter-specific casts, and temporal FK joins do not define zero/multiple-match
behavior.

### Decision

Supersede DD-025. Each incremental entity declares CDC operation, source update/effective
time, ingestion time, total-order tie-breaker, lookback, delete, late-arrival,
correction, replay, backfill, and schema-change behavior. SCD2 explicitly declares
`business-valid` or `load-history`; generated run time must not be presented as business
validity. `_loaded_at` comes from one injected run clock.

Hash input uses a versioned, ordered, typed, length-delimited canonical encoding with an
explicit null representation and SHA-256. Changes to the hash contract require a
backfill/migration decision for generated data even though old hub configuration is not
supported.

Windows and deduplication require a complete total order. Temporal relationships declare
interval boundaries, time-zone normalization, expected lookup cardinality, and
missing/ambiguous/late-parent behavior: fail, quarantine, retry, or explicit unknown
member. Multiple matches are never resolved by silently choosing one.

The normalized relationship inventory remains complete for Gold analysis. Silver
temporal policy applies only to relationships that canonically qualify for Silver
on the materialized source class: explicit `silverForeignKeyOn`,
`silverForeignKey`, or `silverColumnName`, `owl:FunctionalProperty`, or an
applicable max-cardinality-one restriction. A complete domain/range-only object
property is not a materialized Silver FK.

### Rationale

Incremental correctness depends on time and ordering semantics, not merely a unique key
and row hash. Canonical serialization and explicit FK failures are required for
cross-adapter reproducibility.

### Consequences

- Amend DD-019 and the Silver runtime provisions of DD-104.
- Generate tests for replay idempotency, insert/update/no-op/delete/reinsert, late
  correction, natural-key change, interval integrity, one current row, and temporal FK
  ambiguity.
- Artifact determinism and runtime determinism are reported separately.
- Silver temporal completeness, capability, DQ scope, and authority generation
  consume the Silver-qualified relationship view; Gold retains the unfiltered
  descriptor inventory.

### Implemented contract

- `canonical_hash.py` defines the reference bytes:
  `KAIROS-CANONICAL-HASH|v1|` followed by ordered
  `{type}:N:0:;` or `{type}:V:{utf8-byte-length}:{utf8-hex};` fields, prevalidated
  NFC text,
  exact fixed-scale decimals, UTC microsecond timestamps, canonical supported JSON,
  binary hex, and lowercase SHA-256. Binary-float and adapter-ambiguous SQL JSON
  inputs are rejected.
- `SilverRuntimeAuthoritySpec` is normalized once and carried into
  `RuntimeModelSpec` and `RuntimePhysicalPlan`. Bind retains relationship/model
  structure only; render consumes typed plans and creates content only.
- SCD1 uses total-order current-state merge. SCD2 recomputes affected history with
  replay deduplication, correction ranking, explicit tombstones, separate
  `_business_valid_from/to` and `_system_from/to`, half-open intervals, and one
  deterministic `is_current` row. `_loaded_at` is only the injected run clock.
- A captured normalized CDC `operation='delete'` is a hard-delete event.
  `hardDeletePolicy='tombstone'` retains an explicit deleted row and `ignore` drops
  that event. Physical deletion, including absence inference from snapshots, is not
  expressible by the current source contract and fails closed rather than being
  reported as applied. A source soft-delete flag is distinct: preparation must map it
  to `operation='soft-delete'`; `softDeletePolicy='apply-operation'` materializes a
  logical tombstone, while `ignore` drops it. Unsupported block/quarantine actions fail
  before rendering.
- SCD2 `append-correction` is rejected with
  `history.scd2-append-correction-unsupported` until a renderer can preserve separate,
  non-overlapping half-open valid/system intervals. It never falls through to
  replace-by-total-order behavior.
- Fabric canonical hashing uses UTF-8 `VARCHAR(MAX)`/`VARBINARY(MAX)` throughout,
  including the `HASHBYTES` input, so values beyond 4 KB and 8 KB are not truncated.
  Databricks packages pin the SQL session to UTC with `SET TIME ZONE 'UTC'`; timestamp
  lexical formatting therefore does not depend on the caller's session time zone.
  Frozen >8 KB text/binary vectors and macro-versus-Python renderer parity tests guard
  both adapter implementations.
- Byte-identical replay is collapsed. Contradictory values or operations at the exact
  same complete event order fail closed in the Python reference and SCD2 SQL runtime
  (adapter-native error guard); generated runtime tests also require the authored total
  order to remain unique. Sources must add a deterministic sequence tie-breaker rather
  than relying on arrival order.
- Bounded lookback is mandatory. Range replay and full rebuild require their
  respective authored approvals; unauthorized dbt variables fail at compile time.
- Temporal joins count matches rather than choosing one. `current`, business-valid
  `as-of`, and `none` modes generate explicit cardinality tests and fail,
  quarantine/retry, or unknown-member behavior. As-of is UTC, microsecond,
  closed-open and never receives a blanket current-row predicate.
- Release data exposes effective ordering/time/hash/delete/replay/backfill/
  correction/schema and temporal-FK actions with DD-109 rule IDs, adapter
  dispositions, and authored/registry evidence.

---

## DD-110: Typed Projection Contract and Silver Output Parity

**Status:** Accepted
**Date:** 2026-07-25
**Affects:** dbt phase architecture, Silver dbt/DDL/ERD/schema/report output, Gold
registry and projection tests
**Implementation:** Gates 3a and 3b introduced typed logical builders and graph-free,
deeply immutable phase records in `core/projections/dbt/`. Gate 3c added the complete
DD-106–DD-115 authoring facts and effective policy specifications in
`dbt/policy_specs.py`, bind-only RDF/file extraction in `dbt/policy_bind.py`, and
fail-closed, provenance-bearing classification in `dbt/policy_normalize.py`. The same
authoritative `MedallionPolicySpec` now flows through `ProjectionContract`,
`NormalizedProjectFacts`, `ShapedProject`, materialization, adapter negotiation, and the
release plan; each shaped Silver model carries its shared column/identity/audit/history/
FK/DQ/capability authority. The `silver-parity` gate extends that authority with exact
ordered canonical columns, key/grain/FK contracts, adapter-mapped physical columns,
unenforced constraint/index metadata, DQ/quarantine links, and deterministic provenance.
The dbt renderer now emits SQL, schema YAML, Fabric/Databricks DDL, constraint metadata,
ERD, and a field-level parity manifest from the same `SilverModelSpec`. The explicit
`silver` target invokes the identical bind/normalize/shape/materialize/render pipeline
and fails closed when source, preparation, mapping, or policy evidence is absent.
`medallion_silver_projector` is a graph-free render facade only.

**Remaining implementation debt:** external adapter compile evidence and the
DD-112/DD-113 Gold renderer redesign remain later gates. Gold must consume the generated
Silver registry and parity evidence; it must not establish a second Silver authority.

### Context

DD-102 created named phases but deliberately retained mutable graphs and interleaved
shape/materialize/render behavior inside a large monolith for byte compatibility. That
compromise cannot support prep, shared Silver dbt/DDL semantics, or strict capability
evidence.

### Decision

Supersede DD-102 while retaining the ordered phase names:

`bind → normalize → shape → materialize → render`

Every handoff is a deeply immutable typed value. RDF and authoring inputs are read only
inside bind. Normalize is the sole policy-classification phase and emits effective
policy with provenance. Shape creates logical specs and no artifact bytes. Materialize
selects physical plans through adapter capabilities. Render accepts physical plans only
and cannot read RDF, reclassify policy, or choose deviations.

`SilverModelSpec` is the sole logical contract for dbt SQL, schema YAML, DDL, ERD, Gold
registry, quality tests, and reports. Differences between outputs are permitted only
when an explicit adapter capability requires them and the deviation is reported.
DDL-only operational promises are removed. Reference inlining becomes an explicit Gold
product optimization rather than Silver behavior.

### Rationale

One typed contract prevents each projector from independently inventing columns, keys,
history, or constraints. Removing byte-compatibility debt is appropriate for fresh hubs.

### Consequences

- Extract builders before adding feature renderers; this is the redesign's hard
  implementation gate.
- Remove rendered content, mutable containers, graphs, and Jinja objects from phase
  results.
- Amend DD-011, DD-026, DD-029, and DD-104.
- Existing private helper imports and byte-golden compatibility are intentionally
  unsupported.

---

## DD-111: Adapter Capabilities and Physical Policy

**Status:** Accepted
**Date:** 2026-07-25
**Affects:** Fabric/Databricks rendering, types, hashes, JSON, merge, constraints,
partitioning/clustering, adapter validation and release gates
**Implementation:** `core/projections/dbt/capabilities.py` provides the versioned v1
Fabric and Databricks registry for canonical types, canonical SHA-256 hashing, scalar and
array JSON, merge/upsert/delete, constraints, deployment-owned physical layout,
quarantine/tests, security, and TMDL. Materialization negotiates exact typed requirements
to `supported`, approved `deviation`, or `blocking` results carrying the normative rule
and evidence; unknown adapters and the former Spark alias fail closed. Authored capability
and compile-evidence statements are normalized separately from registry capability.
Successful adapter compile runs and versioned compile-evidence reporting remain a later
implementation gate, so registry support alone is not strict-release compile proof.

### Context

A shared semantic contract does not make Fabric and Databricks behavior equivalent.
Types, collation, timestamps, JSON, merge, constraints, and physical layout differ.
Conditional code and a default platform can silently degrade unsupported behavior.

### Decision

Every adapter has a versioned capability record. Unknown adapters and unsupported
feature combinations fail with structured diagnostics; no “non-Fabric means
Databricks” fallback is allowed. Semantic types are mapped explicitly with disclosed
lossiness.

`partitionBy`, `clusterBy`, indexes, and storage layout are target deployment-profile
policy based on measured workload, not ontology truth. “Supported/applied” requires
successful compile evidence for every required adapter. `environment_blocked` is not a
strict-pass result.

### Rationale

Capability negotiation makes portability testable without forcing identical physical
SQL or silently lowering guarantees.

### Consequences

- Add Fabric and Databricks golden/compile scenarios for semantic parity.
- Remove unsupported Silver physical annotations from the semantic extension surface.
- Amend DD-002, DD-009, and DD-104 without changing Fabric as the default user choice.

---

## DD-112: Gold Product Profiles and Explicit Dimensional Design

**Status:** Accepted
**Date:** 2026-07-25
**Affects:** Gold/dbt/Power BI projection, target registry, Gold extensions, skills and
scenario models
**Implementation:** `dbt/gold_specs.py`, `gold_shape.py`, `gold_materialize.py`, and
`gold_render.py`; authoritative registry with only `dimensional-powerbi-v1`

### Context

Gold is currently defined as a star-schema/Power BI layer and classifies a class with two
outgoing FKs as a fact. Gold should represent consumption-oriented data products, while
dimensional analytics is one explicit product profile.

### Decision

Every Gold product declares a named, versioned profile. The first and only profile in
this redesign is `dimensional-powerbi-v1`; future profiles require separate decisions
and implementations.

Within the dimensional profile, every materialized class explicitly declares `fact`,
`dimension`, or `bridge`. FK counts never control materialization. Zero-dimension facts
are valid. Facts declare grain and type: transaction, periodic snapshot, or accumulating
snapshot. They also declare correction, late-arrival, dimension-version binding, and
incremental policy. Dimensions state current-only, history-only, or dual exposure.

DD-001 inheritance applies only inside this dimensional profile. The actual generated
Silver registry is mandatory profile input; Gold cannot select unavailable columns.

### Rationale

Explicit profiles preserve dimensional guarantees while allowing other data-product
types later without redefining Gold.

### Consequences

- Remove automatic fact inference and implicit default dimensions.
- Amend DD-001 and DD-029.
- Generic Gold orchestration is separated from Power BI profile rendering.
- Wide tables, feature sets, API/search products, regulatory extracts, and visuals are
  out of scope.

---

## DD-113: Governed Semantic-Model Lifecycle

**Status:** Accepted
**Date:** 2026-07-25
**Affects:** DAX/TMDL, measures, calendar/time intelligence, incremental policy,
RLS/OLS, perspectives and DirectLake readiness
**Implementation:** typed measure/calendar/security contracts, dependency and cycle
validation, fail-closed TMDL/security generation, and strict compile/readiness evidence

### Context

Current measure annotations remove their source columns, generic calendars and time
intelligence are generated without approved business assumptions, and security roles are
scaffolds without entitlement or deployment governance.

### Decision

Measures are first-class semantic resources with stable identity, business definition,
dependencies, lifecycle state (`intent`, `provisional`, `validated`, `approved`), format,
owner role, and tests. Measures never remove required physical input columns. Every DAX
dependency resolves against emitted columns/measures; missing references and cycles
block release.

Production time intelligence requires an approved calendar profile covering date range,
fiscal/week pattern, locale, holidays, time zone, period closure, and role-playing dates.
Generic unapproved calendar defaults are non-production.

RLS/OLS output requires a complete projection-time fail-closed security contract:
entitlement source, identity mapping, role policy, filter direction, bindings, and
positive/negative test definitions. Perspectives are discoverability metadata only and
never security. Successful deployment and runtime enforcement remain downstream facts.
Generated TMDL must parse/compile and DirectLake bindings/types must validate.

### Rationale

Semantic-model artifacts are executable contracts. Compilable DAX or a role block is not
evidence that business semantics or access governance are correct.

### Consequences

- Remove property-replaces-column measure behavior, automatic calendar generation, and
  the unpopulated `is_authorized` role assumption.
- Replace GDPR-specific security framing with general data classification/security
  policy.
- Keep entitlement provisioning and runtime identity administration out of the toolkit.

---

## DD-114: Policy, Capability, Deviation, and Versioned Release Evidence

**Status:** Accepted
**Date:** 2026-07-25
**Affects:** design authority, status, validation/projection/release reports, lifecycle
gate, scaffold workflows and downstream contracts
**Implementation:** `core/release_evaluator.py`, versioned
`model/governance/release-baseline.yaml`, deterministic release manifest/report,
and `project --strict`

### Context

The draft rules treated accepted DDs and current implementation as jointly
authoritative. Current status/release logic often treats file presence, warnings, or
environment-blocked validation as sufficient evidence and lacks an explicit approved
release baseline.

### Decision

Authority order is:

1. accepted DDs and versioned policy profiles;
2. governed ontologies, claims, mappings, extensions, and contracts;
3. approved scope-limited deviation records;
4. implementation capability evidence; and
5. generated artifacts.

Implementation never overrides policy. Unsupported or partial behavior is an explicit
capability gap/deviation, never silent degradation. Deviations record policy reference,
scope, rationale, abstract owner role, approval, review/expiry, and evidence.

Fresh hubs contain a versioned `model/governance/release-baseline.yaml`. Baseline changes
require explicit approval and deterministic diff. Strict release blocks missing/stale/
unknown evidence, unexpected skips or unbinding, design stubs, required-entity changes,
contract or adapter regressions, unsupported capabilities, and warnings/errors that the
active release profile classifies as blocking. Intentional exclusion is explicit policy,
not absence.

Status and reports are schema-versioned and fingerprint their evaluated inputs.
Ownership/stewardship uses abstract roles, not personal identities. Classification and
freshness SLA are required release expectations, not claims of runtime health.

### Existing decision revision map

This table is the normative amendment record for accepted historical DDs. Their original
sections remain unchanged as historical context; readers must apply this map together
with DD-106–DD-115.

| Existing DD | Effect of DD-106–DD-115 |
|---|---|
| DD-001 | Dimensional inheritance is scoped by DD-112. |
| DD-002 / DD-009 | Platform generation is governed by DD-111 capabilities. |
| DD-006 / DD-015 / DD-038 | Raw source authority is retained; prep authority is added by DD-106. |
| DD-011 | Output remains inside the dbt tree, but logical Silver content is governed by the shared DD-110 specification. |
| DD-018 / DD-026 / DD-074 | Entity/multi-source structure remains; conformance, identity, and prep responsibilities change under DD-106/DD-108. |
| DD-019 | FK key resolution remains; temporal failure/restatement policy comes from DD-109. |
| DD-029 | Gold registry becomes a typed profile input under DD-110/DD-112. |
| DD-034 | Extension authority remains; identity-strategy deferral is superseded by DD-108. |
| DD-080 | Status becomes schema v3 and includes prep/evidence readiness. |
| DD-092 / DD-093 / DD-105 | Contract authority remains; expression and iterative readiness rules are amended by DD-107. |
| DD-096 | Entity outcomes are explicit; design stubs always block release. |
| DD-101 | Strict release composes versioned baseline/capability/DQ evidence and treats unknown as blocking. |
| DD-104 | Reference modules remain; identity, temporal, adapter, and lineage provisions are replaced by DD-108/DD-109/DD-111. |

### Rationale

Separating policy from capability allows implementation work to be honest without making
temporary limitations normative. A reviewed baseline makes regressions detectable.

### Consequences

- Replace status/report schemas directly; no compatibility readers or migration path.
- Source cannot be done while required prep/review/transformation evidence is pending.
- Validate/project completion requires current versioned reports, not file presence.
- Release workflow validates, projects, compiles required adapters, runs strict release,
  then packages.

---

## DD-115: Data-Quality Policy and Runtime-Result Contract

**Status:** Accepted
**Date:** 2026-07-25
**Affects:** SHACL/extensions, generated dbt tests, quarantine models, reports, adapter
capabilities and release gates
**Implementation:** typed DQ policy/runtime-result specs, closed declarative
expressions, `kairos_dq_*` dbt macros, persistent result/test artifacts,
row-level quarantine routing, and immutable downstream evidence import

### Context

Generated null, uniqueness, regex, and relationship tests cover contract shape but not
operational fitness. A projection-time toolkit can generate checks and schemas but
cannot claim live freshness, trend health, or alert delivery.

### Decision

Every DQ rule has stable ID/version, category (`contract`, `source`, `business`,
`operational`), scope, severity, tolerance, action (`warn`, `quarantine`, `block`),
abstract owner role, evidence, and executable test reference.

The toolkit generates supported dbt tests, quarantine/reject models, and a portable
runtime-result schema containing run/snapshot/adapter identity, rule ID/version/hash,
status, measured value, threshold, affected/quarantined counts, reconciliation values,
and evidence URI. Runtime observations are imported immutable evidence; the toolkit does
not provide monitoring, alerts, or trend storage.

Prefer toolkit-owned namespaced tests/macros. External packages require approved-package
governance, compatible licensing, and adapter capability evidence. Unsupported checks
block or become approved deviations; uncompilable tests are never emitted.

### Rationale

Static policy and portable results make quality governable without pretending that
generated SQL has executed or that the toolkit operates a data platform.

### Consequences

- Add freshness, volume, duplicate-rate, range/distribution, reconciliation,
  referential-coverage, and cross-field rule types where adapter capabilities permit.
- Missing/stale runtime results block only profiles/rules that explicitly require them.
- DD-089 offline sample audit remains evidence, not runtime telemetry.

### v5 wiring (issue #256)

The v5 stateless compiler collects `kairos-ext:DataQualityRule` individuals that are attached to a
canonical `owl:Class` via `kairos-ext:dataQualityRule`. Collection happens inside `resolve_scope`
while the ontology graph is still loaded; the rules are carried graph-free on
`ResolutionContext.data_quality_rules`, set on the merged `MedallionPolicyFacts.data_quality`, and
normalized into the same `CompilePlan.quality_models` that emit and explain consume. The governing
class is retained on `DataQualityRuleFact`/`DataQualityRuleSpec` so scope resolution can disambiguate
property/relationship-scoped rules and reject attachment/scope conflicts (`dq.scope-owner-conflict`).
`compile --emit` writes the result model, singular test, quarantine relations (row-level actions),
and runtime-result contract; `compile --explain` surfaces each rule per entity (`data_quality[]`).

---

## DD-116: Non-Writing Projection Readiness

**Status:** Accepted
**Date:** 2026-07-26
**Affects:** scoped closure/loading, projection CLI/orchestration, dbt and Gold physical
planning, lifecycle status, design validators/scaffolds, and readiness reports
**Implementation:** `core/projection_readiness.py`, projector check-only execution, and
`check-projection`; `core/reference_modules.py`; `core/design_validation.py`;
`core/authoring_scaffolds.py`; `core/status.py`

### Context

Projection was the first point where scoped ontology closure, synchronized contracts,
bindings, normalized policy, adapter feasibility, and physical plans were evaluated
together. Running it for diagnosis also rendered and wrote generated output.

### Decision

`check-projection` runs the same scope discovery and projection pipeline through physical
artifact planning, then stops before render and every filesystem write. Preparation, mapping, DD-108 identity, incremental runtime, temporal/FK, adapter feasibility,
data quality, and Gold evaluation use the shared `COLLECT` model for dbt, Silver, and Power BI
readiness. Each subsystem is evaluated once; the orchestrator never catches and retries a
whole projection. Stages return partial or unavailable typed results, preserve fail-fast first-
diagnostic parity, and mechanically mark dependent checks `not_evaluated` with prerequisite
diagnostic IDs while unrelated roots continue. Real projection keeps `FAIL_FAST` as its
default. The command returns a schema-versioned text or stable JSON report and exits
nonzero for blockers. The evaluator itself remains non-writing. Callers may preserve its exact
versioned JSON under `.kairos-state/reports/`; status consumes but never fabricates that evidence.

Scope is derived from the selected ontology/import closure plus the explicitly selected
accelerator/module profile. Validation, inventory, claim synchronization, readiness, and
projection share that domain-scoped closure authority: unresolved modules inside the requested
closure fail closed, while unrelated installed accelerator modules are neither instantiated nor
allowed to affect the exit code. `check-inventory --domains ... --explain-scope` remains the sole
reference-inventory freshness authority and reference-model updates are always explicit.

Source, mapping, transformation, and Silver completion gates are scoped views of this same
non-writing evaluation. Scope filters diagnostics only after the shared bind/normalize
authorities have produced them; it does not reimplement their rules. Reports identify the owner
skill and prerequisite phases. Local Turtle/SHACL/design validity remains distinct from bound
readiness.

Lifecycle status is an additive v3 compatibility layer over the legacy phase view. It derives the
monotonic chain `authored`, `design-valid`, `bound-valid`, `projection-ready`, `generated`,
`compile-valid`, `runtime-valid`, and `release-eligible` from authored artifacts and known
versioned reports. A later artifact cannot promote the effective state across an unknown or
blocked predecessor. Missing, stale, malformed, or unknown-schema reports are `unknown` warnings,
not migration failures. Legacy `done` remains readable as legacy/unknown input and is never
interpreted as a failed gate or richer readiness evidence.

Silver is split into logical intent (SCD, identity/grain, FK/temporal, PII and DQ choices) and a
later bound confirmation. Bound confirmation consumes only the Silver-scoped non-writing
evaluator after final transformation and mapping. Complex routing is logical Silver → contracted
dbt transformation → mapping → bound Silver → full readiness → projection; simple direct/scalar
mapping omits only the transformation checkpoint. Flow and project skills never route to
generation while the full readiness report has blockers.

Focused, read-only `validate-mapping` and `validate-silver-ext` commands establish local design
validity without loading unrelated accelerator closure. Evidence-grounded `scaffold-mapping` and
`scaffold-silver-ext` output proposed-only RDF by default and write only when an output is
explicitly requested; existing outputs require `--overwrite`. Scaffolds never authorize business
semantics and must pass the focused validator before review. Class/property lookup uses the shared
semantic index, including inherited properties and ranges.

Regeneration is non-destructive. Managed authorities update only their delimited managed blocks
and preserve authored triples outside those blocks. Operations that must rewrite RDF provide a
non-writing plan first. In particular, legacy whole-graph managed-surface migration stages durable
backups, and column-IRI migration requires explicit apply, validates all collisions first, and
creates a new backup before writing. The lifecycle scanner validates phase-log xrefs and declared
deliverables, reports disagreement with deterministic filesystem state as drift, ignores archived
logs, and never treats a phase-log checkbox as artifact evidence.

### Rationale

Sharing the existing bind, `normalize_contract`, shape, adapter, and materialization
functions preserves first-error parity and avoids a second simulation of projection rules.

### Consequences

- The command cannot detect rendering, output-filesystem, SVG, compile, or runtime failures.
- Existing projection behavior and legacy exception contracts remain unchanged.
- Reports expose stable ordered diagnostics plus the backward-compatible first `blocker`.
  Remediation is dependency ordered and deduplicated by owning skill and root cause; impacted
  FKs share one task when they depend on the same missing target semantic key.
- A collected blocker is valid only when it is reachable through normal `FAIL_FAST` projection
  after its prerequisites are repaired; blockers need not be simultaneously reachable.
- Existing v1/v2 status keys and legacy phase readers remain intact; v3 adds the lifecycle object.
- Readiness blockers participate in the composed release gate, while absent/stale/unknown evidence
  remains advisory for compatibility.
- Authoring scaffolds reduce mechanical TTL work but leave naming, mapping, identity, runtime, and
  governance decisions proposed until their owning design skill confirms them.

---

## DD-117: Prefixable Virtual-Column IRIs and Explicit Migration

**Status:** Accepted
**Date:** 2026-07-26
**Affects:** synchronized dbt virtual vocabularies and source-column mapping references
**Implementation:** `core/dbt_contract_sync.py`, `core/column_iri_migration.py`, and
`migrate-column-iris`

### Context

Slash-delimited virtual-column IRIs such as `#orders/order_id` are valid full IRIs but
cannot be written as Turtle prefixed names because `/` is not allowed in `PN_LOCAL`.
Silently changing managed vocabularies would break existing mappings.

### Decision

New columns use `{virtual_source_iri}__{percent-encoded-column-name}`. The stable `__`
separator is valid in `PN_LOCAL`; dbt contract column names are restricted identifiers.
Synchronization preserves identities found in an existing managed vocabulary.

Legacy full IRIs remain resolvable during a deprecation window. Migration is a separate,
default-preview operation that rewrites source and mapping RDF references with `rdflib`.
Apply requires an explicit new backup directory, reports every old/new IRI, checks all
target collisions before writing, and preserves unrelated triples.

Compatibility is vocabulary-led: legacy mappings resolve against a preserved legacy
vocabulary, but no legacy aliases are added to a newly generated vocabulary. Mixed
new-vocabulary/old-mapping input remains an explicit resolution error. Migration
transitions the legacy vocabulary and its discovered mapping references together.

### Rationale

Double underscore is visually distinct, valid at every `PN_LOCAL` position used here,
and avoids the trailing-dot restrictions of the alternative `.` separator. Explicit
migration keeps compatibility and review separate from routine contract synchronization.

### Consequences

- New mappings can use compact prefixed names such as `virtual:orders__order_id`.
- Existing hubs retain slash IRIs until their owners run the migration.
- Serialized Turtle formatting may change on apply, while graph semantics and unrelated
  triples remain intact.

---

## DD-118: Contracted dbt Output as Verified Source Identity

**Status:** Accepted
**Date:** 2026-07-26

### Context

DD-108 accepted physical `RecordKeyPolicy` and `ArrayChildContract` authorities only. A
keyless raw source whose governed dbt transformation forms a unique output grain could not
represent that identity truthfully. Declared tests were insufficient because they prove no
warehouse result.

### Decision

`sync-dbt-contracts` emits a typed `kairos-dbt:ContractIdentity` containing its contract/model
reference, virtual table, ordered grain columns, contract-output scope, replacement lineage,
required uniqueness/non-null tests, canonical CDC bindings, decision evidence/status, and a
canonical SHA-256 content hash covering contract identity fields and SQL.

DD-108 accepts this as its third `sourceIdentity` authority. It remains source/output-scoped
and never establishes enterprise identity. Actual passing dbt test results are captured from
supplied `run_results.json` plus its manifest in a versioned deterministic evidence artifact.
Evidence v2 requires matching non-empty invocation IDs and dbt versions, an unambiguous model,
and exact executed tests. Ordinary standard dbt manifest v12 and run-results artifacts are the
authority: the model path, raw code, and dbt SHA-256 checksum bind current SQL, while standard
model, column, config/contract, constraint, generic-test, singular-test, and unit-test fields
bind current YAML semantics. Custom manifest fields and post-run current-file attestations are
not accepted. Unbound v1 evidence is rejected rather than upgraded or synthesized.
Missing, incomplete, or hash-stale evidence surfaces `identity.contract-unverified`
(amended by DD-119: review-only outside `--strict`/release evaluation).
Readiness evaluates discovered contracts even with no transformation candidates.
The transformation-scoped readiness view also reuses contract discovery, synchronization,
candidate governance, completeness, and projection normalization to report grain, decision
evidence, replacement, CDC, dependency, implementation, and test blockers. An absent or empty
candidate inventory never suppresses checks for synchronized contracts.

Canonical `__` and legacy slash virtual-column IRIs remain supported.

### Consequences

- Keyless physical input may safely form identity at a verified contracted output boundary.
- Contract, SQL, key, test, CDC, decision, or replacement changes invalidate prior evidence.
- The toolkit never claims warehouse execution without supplied dbt results.

---

## DD-119: Unverified Contract Identity Is Review-Only Outside Strict Release

**Status:** Accepted
**Date:** 2026-07-26
**Affects:** `core/projections/dbt/policy_normalize.py`, `core/projections/dbt/policy_specs.py`,
`core/projections/dbt/materialize.py`, `core/projector.py`, `core/projection_readiness.py`,
`core/transformation_candidates.py`
**Implementation:** `PolicyIssue.projection_blocking`, `ReleasePlan.projection_blocking_rules`,
`evaluate_transformation_readiness`

### Context

DD-118's `identity.contract-unverified` finding raised `PolicyNormalizationError` directly
during normalization, which unconditionally aborted dbt generation — including ordinary,
non-strict `project` runs and `check-projection` — long before any release or strict
evaluation occurred. `evaluate_transformation_readiness` carried the same finding as an
unconditional blocker for every stage, including `mapping`, even though a contracted
transformation's output identity is release/strict-release evidence, not a generation
prerequisite. This made bootstrap generation and everyday mapping/silver readiness checks
fail for a condition (no warehouse evidence yet) that is expected and normal before a
contract has ever been run against a real warehouse.

### Decision

`identity.contract-unverified` is now raised as a `PolicyIssue` (`blocking=True`,
`projection_blocking=False`) instead of a hard `PolicyNormalizationError`. `PolicyIssue`
gains a `projection_blocking` field (default `True`, preserving existing blocker semantics
for every other rule). `ReleasePlan` gains `projection_blocking_rules` — the subset of
`blocking_rules` where `projection_blocking` is true — computed alongside the existing,
unchanged `blocking_rules`/`blocking_reasons` used for DD-114/DD-115 strict-release
evaluation. `_collected_blocker_diagnostics` and `run_projections`'s `check_only` path use
`projection_blocking_rules` to decide pass/fail and diagnostic severity
(`error`/`blocking=True` vs `warning`/`blocking=False`), so ordinary generation and
`check-projection` proceed and surface the finding as a non-blocking diagnostic, while
`project --strict` and release evaluation still fail on it exactly as before (`blocking_rules`
and the `__release_data__.policy_issues` feed into `evaluate_release` unchanged).
`check_projection` in `projection_readiness.py` now always collects a plan's supplied
diagnostics, not only when the plan's status is `"error"`, so review-only diagnostics from a
`"ready"` plan are still reported.

`evaluate_transformation_readiness` mirrors this split for contracted-transformation
readiness: identity-unverified is included in the human-readable `reasons` for every stage,
but only added to the internal blocking-reasons set (and therefore `is_blocking`) when
`stage == "release"`. `mapping`/`silver` readiness — including an otherwise fully in-scope
contract matched by `table_scope` — passes on this reason alone; genuine authored/policy
problems (missing/incomplete decision evidence, contract-sync drift, and, for
`silver`/`release`, incomplete replacement-scope completion) remain blocking at every stage,
unchanged. No evidence is synthesized, waived, or hash-matched incorrectly by this change —
only the failure's blocking scope narrows.

### Rationale

Release/strict-release evaluation (DD-114/DD-115) is the correct, single place to enforce
"no unverified contract identity ships" — it already consumes `blocking_rules` untouched. Any
other consumer that unconditionally blocks on `identity.contract-unverified` duplicates that
gate in a way that stops ordinary, iterative generation before a warehouse has ever run the
contract's tests, which is the normal bootstrap state, not an error.

### Consequences

- Ordinary `project` (non-strict) and `check-projection` succeed with unverified contract
  identity and report it as a `warning`/non-blocking diagnostic; `project --strict` and
  release evaluation remain blocked until current, passing evidence is captured.
- `check-transformation-readiness --stage mapping` (and `silver`, for this reason alone)
  passes for a contract with unverified identity; `--stage release` still blocks.
- Every other `PolicyIssue` and transformation-readiness reason keeps its prior blocking
  behavior; only `identity.contract-unverified` changes scope.

---

## DD-120: Additive Validation Reports and Non-Writing Lifecycle-State Suggestion

**Status:** Accepted
**Date:** 2026-07-26
**Affects:** `core/validator.py`, `cli/main.py`, `core/_provenance.py`,
`core/dbt_contract_sync.py`
**Implementation:** `run_validation(markdown_report_path=...)`,
`render_validation_markdown`, `propose_lifecycle_state`, `LifecycleStateProposal`,
`validate --report-format`/`--report-path`, `sync_dbt_contracts`
(`prior_generator_version`, `running_toolkit_version`)

### Context

`kairos-ontology validate` only ever wrote a fixed JSON report
(`<hub>/output/validation-report.json`), with no way to select a human-readable
format or an explicit destination — unlike `status --format text|json|markdown`,
which already established this pattern. Separately, `sync-dbt-contracts` output gave
no indication of which toolkit version regenerated a drifted artifact, and
terminology for the toolkit-update/refresh/sync operations was inconsistent
(`update`, `refresh`, and `sync` were used interchangeably for distinct operations).

### Decision

`run_validation` gains an additive `markdown_report_path` parameter (default `None`,
preserving the exact pre-existing JSON-only contract) that renders a deterministic
Markdown report via `render_validation_markdown`: toolkit version, effective command
options, catalog, accelerator, scope/files, and findings, sorted for byte-identical
output across runs on identical input (`ontology_files` is now gathered pre-sorted).
`validate` gains `--report-format json|markdown|both` (default `json`) and
`--report-path PATH` (rejected in combination with `both`, which always uses the two
default paths) to select format and destination without touching existing behavior
when omitted.

A typed `LifecycleStateProposal` (`suggested_state`, `achieved`, `reason`) is computed
by the pure function `propose_lifecycle_state` and embedded as `results["state_proposal"]`
in the JSON report and as a Markdown section. It performs no I/O and never reads or
writes `.kairos-state/` — persisting versioned lifecycle evidence (e.g.
`design-validation.json`) remains exclusively the domain of the interactive skills /
`kairos-flow` orchestrator (DD-080). The validator stays free of lifecycle-state
mutation.

`sync_dbt_contracts` now returns `running_toolkit_version` on the report and
`prior_generator_version` per item, read only from an existing artifact's own
`# Generated by kairos-ontology-toolkit vX.Y.Z` provenance comment
(`read_provenance_version`, added to `_provenance.py`) — `None` when no such stamp
exists, never inferred or fabricated. CLI output for `sync-dbt-contracts` now reads
"Contract synchronization" throughout (was "dbt contract sync"), and `kairos-help`/
`kairos-execute-validate` standardize on **toolkit upgrade**, **managed-file refresh**,
and **contract synchronization** as the three canonical operation names.

### Rationale

Mirroring the `status --format` precedent keeps the new option additive and familiar.
Sorting glob results and embedding only in-memory, JSON-serializable values keeps the
Markdown report reproducible without adding any new I/O or timing dependency. Keeping
the lifecycle-state suggestion typed and non-writing preserves the DD-080 invariant
that only `kairos-flow`/interactive skills persist lifecycle evidence, while still
giving a human or a skill a computed starting point. Reporting only a *previously
recorded* provenance stamp — never guessing — keeps the provenance policy honest.

### Consequences

- `validate` with no new flags behaves exactly as before (JSON only, same path).
- `validate --report-format markdown` opts out of the JSON report entirely, writing
  only the Markdown report — an explicit choice, not a silent addition.
- `run_validation`'s JSON report gains one additive `state_proposal` key; existing
  consumers that read specific known keys are unaffected.
- `sync-dbt-contracts` output text changed (`"Contract synchronization complete"`
  instead of `"dbt contract sync complete"`); any external tooling that greps the
  older exact string must update.

---

## DD-121: Failure-Safe Alignment Generation with Typed Per-Table Outcomes

**Status:** Accepted
**Date:** 2026-07-27
**Affects:** `core/propose_alignment.py`, `core/ai_provider.py`,
`core/claim_registry.py`, `core/migrate_claims.py`, `core/completeness_model.py`,
`core/claim_coverage.py`, `cli/main.py`
**Implementation:** `TableAlignment.generation_outcome`/`generation_provider`/
`generation_model`/`generation_error`, `OUTCOME_SEMANTIC_SUCCESS` /
`OUTCOME_PROVIDER_FAILURE` / `OUTCOME_FALLBACK_ONLY`, `AlignmentTotalFailureError`,
`ClaimRegistry.generation_outcomes` (`GenerationOutcome`), `ClaimCheckReport
.incomplete_generation`, `propose-alignment --allow-fallback-output`,
`ai_provider.create_chat_completion`/`sanitize_provider_error`

### Context

`propose-alignment`'s LLM call for a table could fail (provider outage, timeout,
malformed response) or run with zero reference classes to align against (fallback
only, no LLM call at all), and both cases previously looked identical to a genuine
semantic result: the domain claims file was written unconditionally, with no signal
that a table's alignment was incomplete or never actually generated. A total
provider outage across every table in a run still exited 0 and reported success.
There was also no capability-aware handling for a provider rejecting an unsupported
request parameter — any such rejection surfaced as a raw exception.

### Decision

`align_table()` and the per-table pipeline now classify every table into one of
three typed outcomes — `semantic_success`, `provider_failure` (LLM call raised),
or `fallback_only` (no reference classes were available, so the LLM was never
called) — carried on `TableAlignment` plus sanitized `generation_provider`/
`generation_model`/`generation_error` (via `ai_provider.sanitize_provider_error`,
which redacts API keys/bearer tokens and caps message length). `alignment_to_dict`
only emits these fields when the outcome is not `semantic_success`, preserving a
byte-identical happy-path serialization.

A run-level tally (`run_attempted`, `run_semantic_success`, `run_provider_failures`)
drives three behaviors: (1) a failed table's per-table dict is never cached, so a
transient provider outage is retried on the next run instead of being persisted as
a permanent result; (2) a domain where every table came back `provider_failure` is
never written, and failed tables are always reported (not gated behind `--verbose`);
(3) when every attempted table across the whole run fails, `_propose_alignments`
raises `AlignmentTotalFailureError` after flushing the cache — the CLI catches this
distinctly from `EnvironmentError`/`ValueError`, prints no success line, and exits
1. A domain whose tables are 100% `fallback_only` is skipped by default (an
all-placeholder registry must never masquerade as a real proposal); the new
`--allow-fallback-output` flag opts into writing it anyway, with its
`generation_outcomes` recording the incomplete status.

`ClaimRegistry` gains an additive `generation_outcomes: list[GenerationOutcome]`
field (empty list omitted from serialization, matching the schema's existing
sparse-optional convention), populated by `migrate_claims.alignment_to_registry`
from each table's non-success `generation_outcome` key, and threaded through
`merge_preserving_decisions` as fresh per-run reliability metadata (never a curated
decision, so it is always taken from the new run like `coverage`/`freshness`).
`claim_coverage.evaluate_claims_coverage` renders any non-success outcome as a
`ClaimCheckReport.incomplete_generation` warning — included in `has_warnings` but
deliberately excluded from `is_blocking`, since this is a *semantic-generation
completeness* signal distinct from the structural claim validity the gate already
enforces (a table can be structurally valid while still lacking real semantic
content). This is additive to, and does not rewrite, the gate's existing blocking
composition or the separate ontology-binding/release-eligibility notion of
"semantic generation completeness" introduced by the concurrent claim-gates work
(`claim_check_result.py`).

`ai_provider.create_chat_completion` centralizes unsupported-request-parameter
handling: on a provider error that names a specific unsupported parameter, it drops
that one parameter and retries exactly once (no hard-coded per-model capability
table); any other error, or a second failure after the retry, propagates unchanged.
`propose-alignment` preflights the effective role model via
`resolve_provider_config`/`resolve_role_model` before per-table fan-out and reports
it up front, so a misconfiguration is visible before cost is incurred rather than
discovered mid-run on the first table.

### Rationale

Treating "the LLM call did not happen" and "the LLM call happened and produced a
real semantic result" as distinguishable, typed outcomes — rather than both
collapsing into "here is a claims file" — is the only way to prevent an incomplete
or failed run from being indistinguishable from a trustworthy one downstream. Not
caching failures keeps transient provider issues self-healing on retry. Making
total failure a distinct, loud, non-zero-exit condition (never printing success)
follows the same never-invent-success discipline as the rest of the toolkit's
typed-report conventions (DD-106–DD-115, DD-120). Keeping the new fields additive
(sparse, non-empty-only) and the new gate signal warning-only avoids destabilizing
any existing registry, gate, or the concurrent claim-gates work's own composition.

### Consequences

- Existing `propose-alignment` runs where every table succeeds are byte-identical
  (no new keys emitted, no new CLI output beyond the model preflight line).
- A domain with all tables `fallback_only` is no longer written by default — a
  behavioral change from writing an all-placeholder registry unconditionally;
  `--allow-fallback-output` restores the old file-producing behavior explicitly.
- A total-failure run now exits 1 instead of 0; callers/scripts relying on the old
  silent-success behavior on total outage must handle the new exit code.
- `check-claims` output gains a non-blocking `incomplete_generation` warning
  section; existing blocking behavior (`is_blocking`, exit code) is unchanged.
- **Superseded in part by DD-128:** the per-domain write gate alone did not cover a
  domain mixing `provider_failure` with `fallback_only` tables, nor an opted-in
  fallback-only domain. Writes are now staged and committed only after the run-wide
  verdict, so `AlignmentTotalFailureError` guarantees *no* registry was written by
  the run. DD-128 also makes the preflight's provider config endpoint/auth-only —
  the caller-resolved model is authoritative and is never re-derived from
  `KAIROS_AI_{ROLE}_MODEL` here.

---

## DD-159: LLM Judgment Steps Must Never Auto-Degrade

**Status:** Accepted
**Date:** 2026-07-28
**Affects:** `core/ai_provider.py`, `core/ai_preflight.py`,
`core/generation_outcome.py`, `core/propose_alignment.py`,
`core/analyse_sources.py`, `cli/inspection.py` (`check-ai-config`),
`cli/sources.py`
**Implementation:** `AIProviderError`/`NotConfigured`/`Misconfigured`/`Unreachable`
exception hierarchy, `require_ai_provider`/`preflight_ai_provider`,
`check-ai-config` command, `analyse-sources` total-failure guard
(`AffinityTotalFailureError`), `propose-alignment` preflight via
`require_ai_provider`, skill gate 0 (autopilot Stage 0 pre-flight, mapping
Gate 0, source step 11)

### Context

An LLM judgment step (source affinity analysis, alignment proposal) could
previously fall through to a heuristic or a plausible-empty result when the AI
provider was missing, misconfigured, or unreachable.  The toolkit's
`analyse-sources` even cached fabricated fallback domains at `confidence: 0.0`
as if they were real results, poisoning subsequent runs from cache.  The wrong
CLI flag name (`--allow-fallback-registry` instead of `--allow-fallback-output`)
was also documented in error messages and design docs, sending users to a flag
that does not exist.

### Decision

The toolkit now treats any LLM judgment step as a three-tier policy:

1. **Mechanical** — deterministic passes (imports, vocabulary parsing, lexical
   matching) are always available and are not a "fallback."
2. **Judgment** — the LLM is the sole authority.  It must either run or fail fast
   with a typed `AIProviderError`.  It must never auto-degrade to a heuristic or
   produce plausible-empty output.  `require_ai_provider` is the raising
   preflight gates at the entry of each judgment loop.
3. **Blocked** — explicitly-invalid sentinels (`domain: ""`, `confidence: null`,
   `generation_*` keys on `TableAssignment`) or nothing.  Never plausible.

`ai_preflight.require_ai_provider(role, *, model, probe=False)` is the single
raising wrapper commands call before entering a judgment loop.  It returns the
resolved `AIProviderConfig` so callers do not need a second
`resolve_provider_config` call.  `preflight_ai_provider` / `preflight_all_roles`
never raise for config reasons — they return statuses
(`ok` / `not_configured` / `misconfigured` / `unreachable` / `unprobed`) — so
the `check-ai-config` diagnostic command can report without crashing.

A new `check-ai-config` CLI command prints per-role status with computed
remediation, supports `--format text|json`, `--role`, `--model`, `--probe`,
`--strict`, and never prints secret values (env var names only, no `api_key`
field in JSON).  Probe stays opt-in on working commands (`--preflight-probe`);
`check-ai-config` defaults to `--probe` because it is a diagnostic.

`analyse-sources` now: (1) never caches a failed table
(`generation_outcome == SEMANTIC_SUCCESS` gate); (2) records typed outcomes
(`generation_outcome`/`generation_error`/`generation_provider`/`generation_model`)
on `TableAssignment`; (3) hoists the client and prefights before the cost banner;
(4) stages writes and raises `AffinityTotalFailureError` on total failure (exits
1, caught in `cli/sources.py`).  Failed tables persist with `domain: ""` +
`confidence: null` + `generation_*` keys, so both downstream readers skip them
automatically.

`propose-alignment` calls `require_ai_provider` before per-table fan-out and
deleted the old `except EnvironmentError` swallow that silently fell through to
heuristic mode.  The wrong flag name `--allow-fallback-registry` was corrected
to `--allow-fallback-output` everywhere (code, docs, changelog, tests).
`require_ai_provider` now returns the resolved provider config, eliminating the
second `resolve_provider_config` call (and the need to mock it separately in
tests).

Skill documents pin the preflight as a hard gate:
`kairos-flow-autopilot` Stage 0 pre-flight with a **STOP** guardrail,
`kairos-design-mapping` Gate 0, `kairos-design-source` step 11 amendment.

### Rationale

A tool that silently substitutes a heuristic for an LLM judgment step produces
output that looks trustworthy but is not.  The only safe policy is fail-fast:
surface the missing/misconfigured provider up front with a one-line remediation,
and never let a judgment step fall through to plausible-empty output.  Typed
exceptions (subclassing `EnvironmentError`) preserve existing catch sites and
test assertions.  The preflight-then-return pattern avoids a double env lookup
and keeps the test surface minimal (one mock instead of two).

### Consequences

- `analyse-sources` exits 1 on total provider failure (was 0).  Partial failure
    still exits 0 with a visible warning.
- `*-affinity.yaml` gains optional `generation_*` keys and `domain: ""` for
    failed tables.  `schema_version` stays 2.  External consumers assuming every
    table has a non-empty domain will break.
- A hub with `KAIROS_AI_{ROLE}_ENDPOINT` and no `_KEY` now errors instead of
    401-ing every call.  Opt out with `_KEY=none`.
- The wrong flag name `--allow-fallback-registry` is gone from all surfaces.

---

## DD-122: Unified Claim-Activation Predicate and a Versioned Claim-Check Result

**Status:** Accepted
**Date:** 2026-07-27
**Affects:** `core/binding_analysis.py`, `core/reference_modules.py`,
`core/claim_projection_sync.py`, `core/source_coverage.py`,
`core/lifecycle_gate.py`, `core/claim_check_result.py` (new), `cli/main.py`
**Implementation:** `claim_activates_projecting_import`,
`is_decided_non_activating`, `DECIDED_NON_ACTIVATING_STATUSES`,
`DisputedClaimModule`, `ManagedImportPlan.disputed_claims`,
`DomainProjectionSync.disputed_claims`, `ProjectionSyncReport.disputed_claims`/
`.owner_skill`, `SourceCoverageReport.owner_skill`,
`ClaimCheckResult`/`SemanticGenerationSummary`/`SemanticGenerationFact`,
`build_claim_check_result`, `check-claims --format json`, `check-claims --require-mapping`

### Context

Whether a decided claim (`approved`/`deferred`/`rejected`) activates a projecting
reference-module import was checked three separate times — in managed-import
planning (`approved_imported_class_uris`/`approved_imported_term_refs`), in
claims↔projection sync, and in activation-inventory reporting — each re-deriving
the same `status == "approved" and origin == "imported" and disposition in
{"claim", "gap"}`-shaped condition independently. A `deferred` or `rejected`
claim was correctly excluded from *activating* an import everywhere it was
checked, but nothing recorded when the same module stayed active anyway for an
unrelated reason (another claim, or an unconditional data-domain group
activation): a curator who deferred/rejected a claim had no signal that its
module was still present, which reads as a disagreement between the decision
and the generated projection surface.

Separately, `check-claims --strict` blocked on an OR of registry validity,
mapping coverage, and projection-sync drift, conflating three independently
owned concerns into one exit code: mapping gaps are `kairos-design-mapping`'s
concern and sync drift is `kairos-design-domain`'s (enforced by
`claims-to-silver-ext --check-only`), neither of which should fail the
curation-focused `check-claims` gate. There was also no single, versioned,
machine-readable result a skill or CI step could parse — only ad hoc text and
three separately-invoked evaluators.

### Decision

`binding_analysis.py` gains one shared predicate,
`claim_activates_projecting_import(claim) -> bool`, plus its complement
`is_decided_non_activating(claim)` (true for `DECIDED_NON_ACTIVATING_STATUSES =
{"deferred", "rejected"}`). `approved_imported_class_uris` and
`approved_imported_term_refs` now call this predicate instead of repeating the
status/origin/disposition check inline — behavior-preserving, but there is now
exactly one place that answers "does this claim activate a projecting import".

`reference_modules.py` adds `DisputedClaimModule` (`claim_id`, `claim_status`,
`term_uri`, `module_id`, `import_iri`, `reasons`) and a
`ManagedImportPlan.disputed_claims` tuple, populated by scanning the registry
for `is_decided_non_activating` claims whose term resolves to a module that
remains active for another reason (i.e. its import IRI is still present in the
plan's requirement data). `claim_projection_sync.py` threads this through
`DomainProjectionSync.disputed_claims` (each entry tagged with its `domain`)
and exposes a flattened `ProjectionSyncReport.disputed_claims` property, plus an
`owner_skill: str = "kairos-design-domain"` field. `source_coverage.py` gains
the analogous `SourceCoverageReport.owner_skill: str = "kairos-design-mapping"`.
Both `owner_skill` additions and the new `disputed_claims` fields are purely
additive dataclass fields; `lifecycle_gate.py`'s existing `_projection_sync_to_dict`/
`_source_coverage_to_dict` helpers gain the corresponding keys without a schema
version bump (additive-only, per that module's own versioning convention).

A new `core/claim_check_result.py` composes the existing, independently
governed evaluators into one versioned (`CLAIM_CHECK_RESULT_SCHEMA_VERSION = 1`)
`ClaimCheckResult`, with five facets each reported on its own: `registry`
(`ClaimCheckReport`, unchanged), `semantic_generation`
(`SemanticGenerationSummary`/`SemanticGenerationFact`, one per domain), `mapping`
(`SourceCoverageReport | None`), `projection_sync` (`ProjectionSyncReport`), and
the flattened `disputed_claims` list. `semantic_generation` deliberately
consumes DD-121's additive `ClaimCheckReport.incomplete_generation` metadata
(itself sourced from `ClaimRegistry.generation_outcomes`) rather than inventing
a second notion of "generated": a domain with no incomplete-generation entries
— because every table reached `semantic_success`, or because its registry
predates the `generation_outcomes` feature entirely (a legacy artifact) — is
vacuously complete for this facet, so old registries are never penalized.
`curation_complete` is the **only** composite/blocking signal this module
introduces, computed from the registry facet alone: `False` if
`registry.is_blocking`, or (only under `strict=True`) if
`registry.has_undecided_claims()`; otherwise `True`. `semantic_generation`,
`mapping`, and `projection_sync` never gate it — they stay independently
visible (mapping/sync additionally carry `owner_skill`) and block only within
their owning workflow.

`check-claims` (`cli/main.py`) now builds this one `ClaimCheckResult` instead of
invoking the registry/mapping/sync evaluators separately, gains `--format
json|text` (default `text`) to emit `result.to_dict()` verbatim, and its
`should_block` computation drops the previous `source_blocking`/`sync_blocking`
OR — the exit code is now `(report.is_blocking or strict_block or
mapping_block) and not warn_only`, where `mapping_block` is `False` unless the
caller passes the new, opt-in `--require-mapping` flag (see Consequences).
Mapping-gap and sync-drift text
sections remain printed (now with an explicit `owner_skill` line and non-error
`⚠` styling instead of `❌`/`err=True` when not required), and any `disputed_claims` entries are
printed per domain in both `check-claims` and `claims-to-silver-ext`'s existing
sync-reporting loop, so a curator sees exactly which claim IDs retain a
disputed module and why.

### Rationale

A single shared predicate is the only way to guarantee managed-import planning,
projection sync, and activation-inventory reporting can never silently diverge
on what "a decided claim activates an import" means — the original three
independent implementations happened to agree, but nothing enforced that.
Reporting disputes rather than silently dropping them keeps a
deferred/rejected decision from reading as ignored when the module is
legitimately still needed for another reason. Scoping `curation_complete` to
registry/freshness/semantic-policy/undecided-claims — and no further — keeps
each skill's enforcement boundary intact (DD-094's mapping ownership, this
document's projection-sync ownership) instead of one gate silently absorbing
every other gate's blocking behavior. Consuming DD-121's `generation_outcomes`
rather than re-deriving a second "semantic completeness" concept keeps exactly
one authority for that signal.

### Consequences

- `check-claims` (non-`--strict` and `--strict`) no longer exits non-zero on
  mapping gaps or projection-sync drift alone — only `claims-to-silver-ext
  --check-only` (sync) and mapping-owning workflows still block on those.
  Existing CI invocations that relied on `check-claims --strict` catching sync
  drift must instead run `claims-to-silver-ext --check-only`.
  `test_check_claims_blocks_on_sync_drift_and_passes_after_generation` was
  updated to assert the new exit-0 behavior.
- **`--require-mapping` (opt-in, added post-review)**: `kairos-execute-project`'s
  DD-094 pre-silver/dbt mapping gate had no standalone `check-source-coverage`
  command to fall back on — it depended entirely on `check-claims`'s own exit
  code to fail closed on unmapped affinity tables, which this DD's narrowing
  silently broke. Rather than re-widening the default `curation_complete`/exit
  code (which would reintroduce the original conflation), `check-claims` gained
  an explicit `--require-mapping` flag: when passed, `mapping_block =
  result.mapping.is_blocking` is folded into the exit-code OR (both `--format
  text` and `--format json`), without changing `curation_complete` itself or
  the default (no-flag) exit code. `kairos-execute-project`'s SKILL.md now
  documents `check-claims --require-mapping` for this gate; `kairos-design-mapping`
  (the mapping-authoring skill) can use the same flag, or its own review flow,
  as it prefers. `--strict` remains scoped to undecided-claims only, per this
  DD's original intent — `--require-mapping` is the dedicated, separately-named
  escape hatch for the one owning workflow that still needs `check-claims`
  itself to fail closed on mapping.
- `check-claims --format json` is new, additive CLI surface; the default text
  output keeps its existing structure with two additions: an `owner_skill` line
  on the mapping/sync sections and any `disputed_claims` entries.
- Old Claim Registries (no `generation_outcomes` key) and old callers of
  `approved_imported_class_uris`/`approved_imported_term_refs` are unaffected —
  both changes are read-only refactors/additive fields, not schema changes.

---

## DD-123: Mapping-Skill-Derived Table Scope and Visible Out-of-Scope Diagnostics

**Status:** Accepted
**Date:** 2026-07-26
**Affects:** `.github/skills/kairos-design-mapping/SKILL.md` (and its scaffold copy),
`core/transformation_candidates.py`
**Implementation:** `evaluate_transformation_readiness`'s implemented-contract loop

### Context

Gate 6 of **kairos-design-mapping** invoked `check-transformation-readiness --stage
mapping` with no `--table` scope, even though the command already accepted a repeatable
`--table` option and `evaluate_transformation_readiness` already treated direct
table/virtual-source overlap as the sole scope authority (DD-107/DD-118/DD-119). Every
Gate 6 run therefore evaluated the whole hub's contracts, so an unrelated domain's blocked
transformation (e.g. missing decision evidence) could be confused for a blocker on the
table this mapping session actually confirmed, and there was no persisted place to reuse a
derived scope across a pause/resume.

Separately, `evaluate_transformation_readiness`'s loop over discovered (non-inventoried)
dbt contracts skipped a contract entirely (`continue`) when it did not overlap the
requested `table_scope`, rather than surfacing it as a non-blocking diagnostic the way an
out-of-scope inventoried candidate already did. A blocked contract for another domain
simply vanished from a scoped report instead of remaining visible for awareness.

### Decision

**Skill:** Phase 1 (Table-to-Entity Alignment) of `kairos-design-mapping` now derives a
**Confirmed table scope** list — the absolute source-table/virtual-source IRI of every row
confirmed to an entity, excluding `operational`/`deprecated`/`out-of-scope`/`gap` rows —
and persists it in the phase log (`phases/mapping/<source>-to-<domain>.md`) so a resumed
session reuses it verbatim instead of re-deriving it. Gate 6 now passes this list as a
repeatable `--table` per confirmed IRI to `check-transformation-readiness --stage
mapping`. The scope is never widened by following FK/dependency relationships to other
tables — direct table/virtual-source overlap remains the sole authority, matching the
existing evaluator. Unscoped invocation (no `--table`) remains reserved for hub-wide
status/release checks (**kairos-diagnose-status**, **kairos-flow**, `check-release`); the
mapping skill never drops its scope to route around an unrelated blocker.

**Evaluator:** the implemented-contract loop in `evaluate_transformation_readiness` no
longer skips a non-overlapping contract outright. It now evaluates the contract's reasons
exactly as before but records `is_blocking = in_scope and bool(blocking_reasons)`, where
`in_scope` is the existing `_contract_overlaps_table_scope` result. An out-of-scope
contract's blocking reasons (evidence, sync, identity, replacement completion) stay in its
`reasons` tuple for review; only its contribution to `is_blocking`/`report.is_blocking` is
suppressed. When `table_scope` is empty (the unscoped hub-status/release path),
`_contract_overlaps_table_scope` still returns `True` for every contract, so unscoped
behavior is unchanged byte-for-byte.

### Rationale

Deriving the `--table` scope from the same Table Alignment Proposal the user already
confirmed avoids inventing a second, hand-maintained scope list, and persisting it keeps a
resumed session from silently re-scoping mid-flow. Making out-of-scope blockers visible
but non-blocking mirrors the treatment inventory candidates already receive for the
`accepted` status (DD-119's own precedent), so scoped and inventoried findings behave
consistently instead of one path silently dropping information the other already surfaces.

### Consequences

- `test_scoped_readiness_ignores_unrelated_noninventoried_contract` is renamed to
  `test_scoped_readiness_surfaces_unrelated_contract_as_nonblocking_diagnostic` and now
  asserts the unrelated contract is present with `is_blocking is False` and non-empty
  `reasons`, instead of an empty `candidates` tuple.
- A new two-domain regression
  (`test_two_domain_scope_isolates_blocked_domain_from_ready_domain`) confirms one domain's
  blocked contract stays a non-blocking diagnostic while a second domain's scoped,
  contract-clean tables remain mapping-ready, and that an in-scope contract whose only
  issue is unverified identity still follows the DD-119 release-only semantics in this
  multi-domain setting.
- No change to `--stage silver`/`--stage release` blocking semantics for in-scope
  contracts, to candidate-based (inventoried) readiness, or to any consumer that already
  passes an empty/no `table_scope`.

---

## DD-124: URI-First Confirmed-Anchor Resolution and a Versioned Unresolved-Anchor Record

**Status:** Accepted
**Date:** 2026-07-26
**Affects:** `core/anchor_resolution.py` (new), `core/unresolved_anchors.py` (new),
`core/propose_alignment.py`, `core/migrate_claims.py`, `core/claim_registry.py`,
`cli/main.py` (`propose-alignment`)
**Implementation:** `resolve_table_anchor`, `align_table(anchor_override=...)`,
`_process_table`'s anchor-resolution wiring in `_propose_alignments`

### Context

`propose-alignment` chose a table's reference-model class anchor purely from the LLM's
semantic guess (with a lexical name-similarity fallback when that guess was invalid), even
when the business had already **confirmed** — via the `kairos-design-discovery` Core
Concepts Conformance artifact (DD-090; `outcome: conforms` / `conforms-with-rename` +
`rename_to`) — exactly which reference-model concept a business term identifies. Both the
LLM path and the similarity fallback could silently converge on the "nearest" class even
when that confirmed evidence was itself ambiguous (e.g. two archetypes' concepts sharing
one business alias), permanently masking the disagreement instead of surfacing it for
resolution. Property/custom claims were also generated per-column independent of whether
the table's own class anchor was trustworthy, so an unreliable anchor still produced
concrete property claims downstream.

### Decision

A new pure module, `anchor_resolution.py`, builds a **confirmed alias index** from the
conformance artifact (the only input treated as authoritative here — the discovery
glossary remains "inspirational only, not reconciled" and is never consulted for anchor
resolution) and resolves a table's affinity-derived `likely_entity` against it *before* any
class selection runs, with three outcomes: `"confirmed"` (exactly one confirmed URI, present
in the table's candidate class pool — wins over any LLM/lexical guess),
`"ambiguous"` (the confirmed evidence itself names more than one distinct concept URI for
the same alias — never collapsed to the nearest one), or `"none"` (falls through to the
existing, unchanged LLM/lexical path).

`align_table` gained an `anchor_override: str | None` parameter: when the anchor resolves
to `"confirmed"`, `_process_table` passes the resolved class name through, forcing
`ref_class`/`ref_class_status="confirmed"`/`ref_class_confidence=1.0` regardless of what the
model itself proposes (columns without their own LLM-proposed `ref_class` still inherit
this confirmed class as their default). When the anchor is `"ambiguous"`, the table is
short-circuited *before* any LLM call or cache lookup: it is written with
`ref_class_status="unresolved"`, empty `column_alignments`, and the existing F6
column-reconciliation passthrough loop is skipped for it — so an unresolved anchor produces
**zero** property or custom-column claims, never a silent guess. The ambiguous result is
never cached, so a later conformance-artifact correction re-resolves fresh.

A second new pure module, `unresolved_anchors.py`, defines a versioned `UnresolvedAnchor`
record (stable `id` derived from domain/system/table, `status` of `"open"` or `"resolved"`,
`candidate_uris`, human-readable `evidence`, and an optional `resolved_uri`/`resolved_by`)
kept in a separate `{domain}-unresolved-anchors.yaml` file alongside (never inside) the
Claim Registry — decisions about an anchor's identity are provenance/evidence, not claims.
Existing records merge with each run's fresh ones (`merge_preserving_anchor_resolutions`),
so a human resolution recorded in this file is read back and honored by
`_process_table` on the next run (converting the ambiguity to a synthetic `"confirmed"`
result), without needing to touch the alignment source or wait for the conformance artifact
itself to be corrected. The file is written only when non-empty and only alongside an
actual claims-registry write, so hubs that never trigger the feature see no new file.

`CoverageTable` (Claim Registry) gained a sparse `likely_entity_uri` field, populated from
the anchor resolution and preferred over the existing name-based `uri_index` lookup in
`migrate_claims.py` when present. `VALID_ANCHOR_STATES` grew `"confirmed"`/`"unresolved"`.
A new **warning-level** (never error-level) `validate_registry()` check flags imported
`claim`/`specialize` records missing a resolvable `class_uri`/`property_uri` for their type,
without breaking existing error-level-only consumers. `propose_alignment_cmd` auto-detects
the hub's conformance artifact path (mirroring the existing `conformance_validate` command)
and passes it through; a hub with no artifact sees fully unchanged behavior.

### Rationale

Anchoring on the confirmed Core Concepts Conformance artifact — rather than glossary
aliases or model confidence — keeps exactly one human-governed source of truth for "this
business term is this concept," consistent with DD-090's own authority boundary. Treating
ambiguous confirmed evidence as a *first-class, versioned, out-of-band record* rather than
either an error or a silent pick preserves the human decision's provenance and lets it be
resolved once and reused, instead of forcing the same disambiguation choice on every run.
Blocking property-claim generation on an unresolved table anchor prevents a large volume of
claims from being built against a foundation (`ref_class`) the pipeline itself doesn't trust
yet. Keeping the new record in its own file (not inside the Claim Registry) preserves the
Registry's existing contract — every record in it is either a claim or its
generation-outcome telemetry — rather than overloading it with a third, structurally
different kind of open question.

### Consequences

- New files: `src/kairos_ontology/core/anchor_resolution.py`,
  `src/kairos_ontology/core/unresolved_anchors.py`, and a new
  `{domain}-unresolved-anchors.yaml` artifact per domain (written only when at least one
  anchor is or was ambiguous).
- `TableAlignment` gained `likely_entity_uri`/`anchor_candidate_uris`; `DomainAlignment`
  gained `unresolved_anchors`; both are sparse/backward-compatible in
  `alignment_to_dict()` output.
- `CoverageTable.likely_entity_uri` and the `"confirmed"`/`"unresolved"` anchor states are
  additive to the Claim Registry schema; existing registries without them continue to load
  unchanged (tolerant loading verified against the pre-existing "good registry" fixture).
- A domain whose *only* tables are unresolved-anchor tables is gated behind
  `--allow-fallback-output` exactly like any other all-fallback domain
  (DD-121) — an unresolved anchor's synthetic outcome is `fallback_only`, not a distinct
  gate.
- Out of scope for this change: surfacing `unresolved_anchors` in `check-claims`/
  `claim_check_result.py` output. This was deliberately deferred to avoid colliding with
  concurrent claim-gates work (DD-122/DD-123) on that same surface. **Followed up in
  DD-128**, which classifies an unresolved-anchor table's deliberate zero coverage as its
  own non-blocking `check-claims` facet instead of a blocking F6 column omission.
- New tests: `tests/test_anchor_resolution.py`, `tests/test_unresolved_anchors.py`, and
  `TestUriAnchorContract`/`TestUriAnchorContractIntegration` classes added to
  `tests/test_claim_registry.py`, `tests/test_migrate_claims.py`, and
  `tests/test_propose_alignment.py`. All new fixtures use generic accelerator-style class
  names, not Booking/TransportOrder/DCSA-specific ones.

---

## DD-125: Domain-Ownership-Inferred Accelerator Resolution with Diagnostics

**Status:** Accepted
**Date:** 2026-07-26
**Affects:** `core/reference_modules.py`, `core/inventory.py`, `cli/main.py`
(`validate`, `project`/`check-projection`, `check-inventory`, `check-claims`)
**Implementation:** `resolve_hub_accelerator_detailed`, `AcceleratorResolution`,
`_accelerator_domain_owners`, `classify_domain_scope`

### Context

Four CLI surfaces each needed to pick one installed accelerator pack (a
`data-domains.yaml`-bearing `accelerator-packs/<name>/client-hub-blueprint/`) for a hub with
multiple packs installed, but only `validate` and `project`/`check-projection` actually
routed through the shared `resolve_hub_accelerator` helper. `check-inventory` had no
`--accelerator` option at all and hardcoded `accelerator=None` into
`resolve_domain_inventory_keys`, silently scoping against whichever pack
`analyse_sources.load_data_domains` happened to glob first (alphabetical). `check-claims`
had a `--accelerator` option but never consulted `[tool.kairos].accelerator` or inference —
it passed the raw CLI value (or `None`) straight into `load_data_domains`, so a hub with
`[tool.kairos].accelerator` configured, or with only one pack unambiguously owning the
claimed domain, could still have `check-claims` silently check a *different* pack's registry
than the one every other command resolved — producing a spurious "registry domain not found
in data-domains.yaml" warning that disagreed with the actual accelerator registry.
Separately, whenever two or more packs were installed and neither `--accelerator` nor
`[tool.kairos].accelerator` was set, `resolve_hub_accelerator` always raised the ambiguity
error, even when the active domain(s) in scope mapped unambiguously to exactly one pack's
`data-domains.yaml` (including domains nested two levels deep under `groups[].domains[]`) —
forcing an unnecessary `--accelerator` flag on every invocation for hubs where the answer was
already inferable from context. Finally, `check-inventory`'s scoped summary printed a bare
`"(none matched)"` for a requested `--domains` token and then still reported the domain
ready, without saying whether readiness came from an accelerator profile, a directly-matched
inventory stem, or neither.

### Decision

`resolve_hub_accelerator` gained a detailed sibling, `resolve_hub_accelerator_detailed`,
returning a frozen `AcceleratorResolution(accelerator, source, data_domains_path)`. The
precedence is unchanged and preserved exactly (explicit `--accelerator` >
`[tool.kairos].accelerator` > inference > ambiguity error; the original error strings —
`"Unknown accelerator {selected!r} from {source}. Available: {choices}"` and "Accelerator
selection is ambiguous. ..." — are byte-for-byte preserved so existing CLI/test assertions
keep working). No new config key was introduced. What's new is a `domain_hint` parameter:
when multiple packs are installed and neither an explicit value nor hub configuration
selects one, `_accelerator_domain_owners` loads each candidate pack's `data-domains.yaml`
via the *same* `analyse_sources.load_data_domains` parser used by
`resolve_domain_inventory_keys` (inventory) and managed-import planning — reusing one nested
`groups[].domains[]` registry parser everywhere so accelerator disambiguation, inventory
scoping, and claim-registry ownership checks never disagree about which pack owns a domain.
If exactly one installed pack owns a hinted domain, it is inferred (`source: "inferred
(domain ownership)"`); if the hint matches zero or more-than-one pack, or no hint is
available, the original hard ambiguity error is still raised — this never silently guesses
among genuinely plausible candidates. `resolve_hub_accelerator` is kept as a thin
backward-compatible wrapper returning only `.accelerator`.

Each of the four CLI commands now supplies a domain hint appropriate to its own scope
(`validate`/`project`/`check-projection`: `--ontology` file stem or all `model/ontologies/
*.ttl` stems; `check-inventory`: the active `--domains` filter; `check-claims`: the active
`--domains` filter, falling back to `model/claims/*-claims.yaml` stems when no filter is
given) and prints the resolved accelerator, its source, and the resolved
`data-domains.yaml` path as text-mode diagnostics (never added to any JSON `to_dict()`
output, so DD-122's versioned claim-check result and other JSON contracts are untouched).
`check-inventory` gained the previously-missing `--accelerator` option.

`core/inventory.py` gained `classify_domain_scope` (plus `DIRECT_PROFILE` /
`ACCELERATOR_PROFILE` / `NO_PROFILE` status constants), replacing the misleading
`"(none matched)"` scoped-inventory line with one of three explicit states per requested
`--domains` token: matched an accelerator `data-domains.yaml` entry that itself resolved
inventory keys (`ACCELERATOR_PROFILE`), matched no accelerator entry but did directly match
one or more already-materialized inventory stems in the report (`DIRECT_PROFILE` — and the
matching key set is now shown, identifying which inventory set makes the scoped result
ready), or matched neither (`NO_PROFILE`).

`check-claims`'s existing `report.unowned` computation in `claim_coverage.py` (and its
result semantics) were **not modified** — the fix is entirely upstream, in *which*
`data_domains` dict gets passed in; the command's `unowned` warning message was only
extended to also print the checked `data-domains.yaml` path for diagnosability.

### Rationale

Consolidating all four commands on one resolver — rather than four independent
call-sites — guarantees cross-command parity by construction: the same explicit
value, the same `[tool.kairos].accelerator`, and the same domain-ownership registry are
consulted everywhere, so a warning from one command can never disagree with another
command's view of which pack is active. Reusing `analyse_sources.load_data_domains` (rather
than a second nested-groups parser) for domain-ownership disambiguation is what makes the
"nested `groups[].domains[]` ownership" fix a single-parser guarantee instead of a
best-effort approximation. Restricting inference to the *unambiguous* case — and still
raising the original hard error otherwise — avoids trading a loud, correct ambiguity error
for a silent wrong guess; a hub whose domains never map unambiguously to one pack sees
exactly the same behavior as before. Keeping the new diagnostics text-only (never JSON) and
leaving `claim_coverage.py`'s result computation untouched avoids colliding with concurrent
claim-gates work on that same JSON surface (DD-122).

### Consequences

- `core/reference_modules.py`: new `AcceleratorResolution` dataclass,
  `_accelerator_domain_owners`, and `resolve_hub_accelerator_detailed`;
  `resolve_hub_accelerator` gained an optional `domain_hint` parameter (default `None`,
  fully backward compatible).
- `core/inventory.py`: new `classify_domain_scope` plus `DIRECT_PROFILE` /
  `ACCELERATOR_PROFILE` / `NO_PROFILE` constants.
- `cli/main.py`: `check-inventory` gained a new `--accelerator` option; `validate`,
  `check-inventory`, and `check-claims` gained text-mode "Accelerator: ... (source: ...)" /
  "Data domains: ..." diagnostic lines; `check-inventory`'s scoped summary no longer prints
  `"(none matched)"`.
- No new configuration key; precedence and existing ambiguity/unknown-accelerator error
  strings are unchanged, preserving CLI compatibility for existing scripts/tests.
- New tests: `tests/test_accelerator_resolution.py` — resolver precedence/inference/
  ambiguity unit tests, nested `groups[].domains[]` registry-parity tests, `check-inventory`
  scoped-wording tests, `check-claims` registry-ownership diagnostics tests, and
  cross-command (`validate`/`project`/`check-inventory`/`check-claims`) resolver-parity
  tests.

---

## DD-126: Metadata-Complete, Convergent Scaffolding with Explicit Created/Updated/Unchanged Reporting

**Status:** Accepted
**Date:** 2026-08-02
**Affects:** `core/claim_projection_sync.py`, `core/managed_text_block.py` (new),
`cli/main.py` (`claims-to-silver-ext`)
**Implementation:** `scaffold_missing_surfaces`, `ScaffoldSurfacesResult`,
`ScaffoldPartialFailureError`, `_validate_generated_metadata`,
`_sync_master_registration`, `_sync_readme_domain_table`,
`managed_text_block.split_managed_block` / `compose_managed_file` / `replace_managed_block`

### Context

DD-072 (`claims-to-silver-ext` bootstraps fresh domains) only ever wrote a bare
`rdf:type owl:Ontology` plus `rdfs:label` into a scaffolded `{domain}.ttl`, and an
even sparser `owl:Ontology` triple into `{domain}-silver-ext.ttl` — missing the
`rdfs:comment` and `owl:versionInfo` that `kairos-execute-validate`'s Level 3 checks
(and every hand-authored ontology) require, so a freshly scaffolded domain could
fail the same metadata gate a hand-authored one passes. The workflow also silently
left `_master.ttl`'s `owl:imports` registration and the scaffold README's "Domain
model overview" table unregistered for newly scaffolded domains, requiring a manual
follow-up step (documented in `kairos-help`'s "Adding a new domain" workflow) that
was easy to forget. Finally, the command reported success or failure only via exit
code and per-domain sync status — there was no explicit accounting of which paths
were created, updated, or left untouched, no git-status guidance for the new
untracked files, and no defined behavior (nor test coverage) for what happens when
one domain among several fails to scaffold.

### Decision

`_scaffold_ontology_skeleton` / `_scaffold_extension_skeleton` now emit
`rdfs:label`, `rdfs:comment`, `owl:versionInfo`, and correct `:`/`owl:`/`rdfs:`
(and `kairos-ext:` for extensions) prefix bindings, and every generated candidate
graph is validated by `_validate_generated_metadata` (required predicates present,
`https://` IRI, Turtle round-trip) **before** anything is written to disk — a
generated skeleton is held to the identical metadata bar as a hand-authored one.
Domain identifiers are validated against `_DOMAIN_SLUG_RE` up front.

`scaffold_missing_surfaces` now returns a frozen `ScaffoldSurfacesResult`
(`created` / `updated` / `unchanged` / `warnings` / `errors` path/str tuples, a
`.counts` property, and a `.describe()` method producing human-readable summary
lines: per-path buckets, a managed-vs-authored explanation, and a `git status`
hint for newly created — hence untracked — files). Each domain is scaffolded
independently inside a try/except: an invalid slug or a failed metadata check is
recorded in `errors` for that domain only and does **not** stop the others, nor
does it undo files already written for domains that succeeded — no rollback is
ever attempted or claimed. If any domain failed, `scaffold_missing_surfaces`
raises `ScaffoldPartialFailureError(message, result)` (mirroring the existing
`OntologyLoadError(message, result)` convention in `ontology_loader.py`) carrying
the full partial `ScaffoldSurfacesResult` so callers can report exactly what
happened.

After the per-domain loop, two best-effort convergence steps run for every
currently-ready domain (freshly scaffolded or pre-existing): `_sync_master_registration`
regenerates a new, generic sentinel-delimited managed block
(`# >>> kairos-managed (generated domain registration — do not edit)` /
`# <<< kairos-managed` — deliberately distinct marker text from the existing
Claim-Registry managed block so the two never collide) inside `_master.ttl`'s
`owl:imports`, and `_sync_readme_domain_table` inserts a row into the README's
"Domain model overview" table for any domain missing one, removing the sole
`*(add domains here)*` placeholder row on first real insertion. Both steps are
**convergence-only**: neither file is ever created by this workflow, only updated
if it already exists (a missing `_master.ttl` or README table is skipped with a
warning, not an error), and all authored content outside the owned region is
preserved untouched. A new generic module, `managed_text_block.py`
(`split_managed_block` / `compose_managed_file` / `replace_managed_block` /
`ManagedBlockError`), implements the same DD-083 splicing algorithm as the
existing private Claim-Registry implementation but is parametrized on marker text,
so the new master-registration feature reuses proven logic without touching or
risking regression of the well-tested, tightly-coupled original.

`ProjectionSyncReport` gained an optional `scaffold_result` field, populated by
`apply_projection_sync`. The `claims-to-silver-ext` CLI command prints
`scaffold_result.describe()` on success and, on `ScaffoldPartialFailureError`,
prints the same `describe()` output for the partial result plus an explicit
"No rollback is performed" statement, then exits non-zero. The CLI's
activation-inventory JSON write (previously unconditional) now compares existing
content before writing and folds into the same created/updated/unchanged summary.

### Rationale

Holding generated skeletons to the same validation function used to gate
hand-authored ontologies is the only way to guarantee they are indistinguishable
from authored ones for every downstream consumer (`kairos-execute-validate`,
projection, mapping). Per-domain isolation with no rollback was chosen over an
all-or-nothing transaction because file-system operations across independently
named domains have no natural transactional boundary in this codebase, and
silently discarding successfully-written sibling domains on one domain's failure
would be more surprising and harmful than reporting the failure precisely and
leaving good work in place — this mirrors the project's broader "never claim
atomicity you don't have" principle. A parallel generic managed-block module
(rather than generalizing the existing private one) was chosen to avoid
destabilizing the Claim-Registry sync path, which has broad existing test
coverage and different semantics (it drives a fully bulk-replaceable block from
claim data, not a registration list keyed by "currently known domains").
Wholesale convergence of *every* ready domain on each run (not just newly
scaffolded ones) avoids a subtler bug where a later run would inadvertently drop
a previously-registered domain from the managed block.

### Consequences

- `core/claim_projection_sync.py`: new `ScaffoldMetadataError`,
  `_validate_domain_slug` / `_DOMAIN_SLUG_RE`, `_validate_generated_metadata`,
  `_MASTER_IMPORT_BEGIN` / `_MASTER_IMPORT_END`, `_sync_master_registration`,
  `_README_TABLE_HEADER`, `_update_readme_domain_table_row`,
  `_sync_readme_domain_table`, `ScaffoldSurfacesResult`,
  `ScaffoldPartialFailureError`; `scaffold_missing_surfaces`'s return type changed
  from `None` to `ScaffoldSurfacesResult` (breaking change for any direct caller —
  none exist outside this module and its tests); `ProjectionSyncReport` gained
  `scaffold_result: ScaffoldSurfacesResult | None = None`.
- `core/managed_text_block.py` (new): generic, domain-agnostic managed-block
  splicing module, independent of the pre-existing Claim-Registry implementation.
- `cli/main.py`: `claims-to-silver-ext` catches `ScaffoldPartialFailureError`,
  prints the partial result and a no-rollback statement, and exits non-zero;
  prints `scaffold_result.describe()` on success; activation-inventory writes are
  now compared before writing and reported as created/updated/unchanged.
- `.github/skills/kairos-design-domain/SKILL.md` and `.github/skills/kairos-help/SKILL.md`
  (+ their `src/kairos_ontology/scaffold/skills/...` copies via
  `scripts/sync_dev_skills.py`) updated to describe the hardened metadata,
  master/README convergence, explicit reporting, and partial-failure behavior.
- New tests in `tests/test_claim_projection_sync.py`: metadata completeness on
  scaffolded skeletons, idempotence across repeated runs, partial-failure
  isolation (invalid domain slug does not block/rollback siblings), master/README
  convergence (including idempotence and graceful skip when absent), a direct
  `_validate_generated_metadata` error-message unit test, and CLI-level tests for
  the printed created/updated/unchanged summary (with git-status hint) and the
  partial-failure exit path.

---

## DD-127: Domain-Ownership Handoffs and Generalized, Stable-Cluster Relationship Candidates

> **Superseded in part by DD-188 (2026-08-17).** The detector described here survives, but its vocabulary no longer lives in the toolkit: the address part
> kinds, role qualifiers and weak/context rules now come from the accelerator pack's `client-hub-blueprint/entity-projections.yaml`, and the six
> `_ADDRESS_*` constants have been deleted. The candidate shape below is also out of date — it is now `type: entity_projection_candidate` with
> `projection_id`, `part_kinds`, and a resolved `target_class_uri` / `target_resolved` (the Phase A2 deferral noted below is closed). See DD-188.

**Status:** Accepted
**Date:** 2026-08-09
**Affects:** `core/claim_registry.py`, `core/migrate_claims.py`,
`core/propose_alignment.py`, `core/draft_model_report.py`
**Implementation:** `DomainHandoff`, `ClaimRegistry.domain_handoffs`,
`_merge_relationship_candidates`, `_RELATIONSHIP_CANDIDATE_DETECTOR_KEYS`,
`_object_relationship_downgrade_reason`, `_is_technical_actor_column`,
`_looks_like_identifier_column`, `_location_role_token` /
`_has_typed_role_evidence`, `_relationship_cluster_id`,
`_cluster_object_property_candidates`

### Context

A design-session review of `propose-alignment` output (`docs/draft/bookingsession.md`,
findings #7–#9) identified three related quality gaps. First, a column whose match
resolved to a sibling/shared reference-model module outside the current domain
(DD-070's `ref_module` tag) was still turned into an ordinary in-domain property
claim by `migrate_claims.alignment_to_registry` — the accelerator's `owns` /
`does_not_own` boundary (`data-domains.yaml`) was enforced only *after* the fact,
downstream, by `claim_coverage.py`'s governance gate, never *before* claim
emission. Second, issue #192's relationship-candidate detector only ever clustered
address-part columns; every other object-property downgrade (F3) emitted one
relationship candidate per column, so several columns evidencing the same
relationship on the same table fragmented into separate, unmergeable candidates,
and a re-run of the detector fully replaced `relationship_candidates` with no
concept of a stable identity a human decision could be recorded against. Third,
the F3 object-property downgrade only ever checked whether a *target class*
resolved — a `created_by_*`/`updated_by_*` technical-actor column, a plain
descriptive scalar with no identifier evidence, or a specialized location
property (e.g. `hasPlaceOfDischarge`) picked without the column itself naming
that role could all still resolve into a governed-looking object-property mapping
or relationship candidate with no generic safeguard against the false positive.

### Decision

`migrate_claims.alignment_to_registry` now checks each column's `ref_module`
(DD-070) **before** building a property claim: a truthy `ref_module` routes the
column into a `DomainHandoff` (new, versioned — `DOMAIN_HANDOFF_SCHEMA_VERSION =
1` — dataclass carrying `ref_class`, `ref_property`, `owning_domains`,
`ref_module`/`ref_module_uri`, and the source `evidence_sources`) instead of a
claim, and `continue`s the loop — the source evidence is never lost, but it can
never be mis-attributed to a domain that does not own it. `ClaimRegistry` gained
an additive `domain_handoffs: list[DomainHandoff]` field (omitted from
serialization when empty, so a pre-feature registry round-trips byte-identical);
`merge_preserving_decisions` always takes `domain_handoffs` from the new run
(derived evidence, not a curated decision, same rule as `generation_outcomes`).
`draft_model_report.py` surfaces `registry.domain_handoffs` as a new
`cross_domain_handoffs` report key, kept separate from `relationship_questions`
so cross-domain recommendations are never conflated with in-domain claim
candidates.

Every relationship-candidate dict (address clusters and, newly, object-property
clusters) now carries a `cluster_id` — a stable SHA-256-derived id computed ONLY
from `(domain, source_table, role/suggested_relationship, target_concept,
cardinality)`, never from which columns currently contribute. A new
`_cluster_object_property_candidates` groups the previously one-per-column F3
candidates by that same stable key, merging `source_columns` (so one cluster
carries all contributing columns) and regenerating the rationale when more than
one column contributes; `_detect_address_relationship_candidates` gained a
backward-compatible optional `domain` keyword to qualify its own `cluster_id` the
same way. On the registry side, `merge_preserving_decisions` now merges
`relationship_candidates` by `cluster_id` via `_merge_relationship_candidates`:
fields owned by the detector (`_RELATIONSHIP_CANDIDATE_DETECTOR_KEYS` —
membership, rationale, cardinality, ...) always refresh from the new run so a
re-run *reports* membership changes, while any additional key a human curator
attached directly to an existing cluster (anything outside that set) survives
the refresh untouched; a candidate without a `cluster_id` (pre-feature output)
passes through unmerged.

A new, deliberately generic (no accelerator/DCSA-specific vocabulary added)
`_object_relationship_downgrade_reason` dispatcher runs before an F3
object-property column is accepted as a resolved mapping: (1) a
technical/audit-actor column (`_is_technical_actor_column` — `created_by_*` /
`updated_by_*` / `approved_by_*` and analogous "&lt;verb&gt;by" shapes) always
downgrades to passthrough evidence and, uniquely, **never** produces a
relationship candidate (audit evidence is not an in-domain relationship); (2) a
specialized location property (one of the existing, pre-dating
`_OBJECT_PROPERTY_NAME_HINTS`, e.g. `hasPlaceOfReceipt`) requires the column's
own name to carry the property's derived role token (`_location_role_token`
strips a `hasPlaceOf`/`hasPortOf`/`has` prefix, e.g. → `receipt`) via
`_has_typed_role_evidence`, else downgrades with reason
`missing_typed_role_evidence`; the two fully-generic `hasLocation`/`hasAddress`
properties are exempt (no specific role to require evidence for); (3) every
other (non-location) object property requires `_looks_like_identifier_column`
evidence (tokenized name — `id`/`code`/`reference`/`key`/... — or data-type
shape — `int`/`uuid`/...) before being trusted as an entity reference, else
downgrades with reason `missing_identifier_evidence`; (4) only after all of the
above passes is the pre-existing F3 `target_resolved` check applied
(`unresolved_target`), preserving byte-identical behavior for every previously
passing case. `_build_object_property_passthrough` /
`_build_object_property_candidate` gained an optional keyword-only `reason`
parameter (default `"unresolved_target"`) that only changes the rationale text
for a non-default reason, so every existing direct-call test keeps its exact
default rationale.

Finally, `uri-anchor-contract`'s existing "no LLM call / no columns" invariant
for an `"unresolved"` table anchor is now also applied to relationship-cluster
detection: `rel_candidates` computation is skipped entirely
(`is_unresolved_anchor`) so an unresolved table emits neither claims (already
true) nor relationship clusters — a name-based address-part cluster naming an
unresolved class could otherwise smuggle a guess back in through the
relationship-candidate side channel.

### Rationale

Enforcing the ownership boundary at emission time (inside `alignment_to_registry`)
rather than only downstream (the existing post-hoc `claim_coverage.py` gate)
means a domain's registry can never even transiently contain a claim it has no
right to approve — the downstream gate remains as defense-in-depth, not the only
line of defense. A content-addressed `cluster_id` (never derived from column
membership) is the only way to let a re-run *refresh* which columns belong to a
cluster while a human decision recorded against that cluster survives — mirroring
the existing claim-`id`-keyed decision-preservation contract
(`HUMAN_CURATED_FIELDS`) at the relationship-candidate granularity. The
audit-actor / identifier-evidence / typed-role-evidence checks were kept
deliberately generic and ordered so each is scoped to exactly the case it targets
(verified against `tests/scenarios/test_scenario_object_property_target.py`'s
existing `PlaceOfReceipt → hasPlaceOfReceipt` regression case, which continues to
resolve normally because the column name itself supplies the "receipt" role
token) — no new accelerator-specific (DCSA/logistics/Booking) name or heuristic
was introduced; the pre-existing `_OBJECT_PROPERTY_NAME_HINTS` list is reused
unchanged.

### Consequences

- `core/claim_registry.py`: new `DomainHandoff` dataclass +
  `DOMAIN_HANDOFF_SCHEMA_VERSION`; `ClaimRegistry.domain_handoffs` field (additive,
  omitted when empty); `_RELATIONSHIP_CANDIDATE_DETECTOR_KEYS` +
  `_merge_relationship_candidates`; `merge_preserving_decisions` merges
  `relationship_candidates` by `cluster_id` and always carries `domain_handoffs`
  forward from the new run; `validate_registry` gained a warning-level check for
  a handoff naming its own registry's domain as an owner.
- `core/migrate_claims.py`: `alignment_to_registry` routes `ref_module`-tagged
  columns into `DomainHandoff` records instead of property claims.
- `core/propose_alignment.py`: new generic safeguards
  (`_is_technical_actor_column`, `_looks_like_identifier_column`,
  `_location_role_token` / `_has_typed_role_evidence` /
  `_is_location_object_property`, `_object_relationship_downgrade_reason`);
  `_relationship_cluster_id` + `cluster_id`/`cardinality` on address candidates;
  `_cluster_object_property_candidates`; `_detect_address_relationship_candidates`
  gained a backward-compatible `domain` keyword; relationship-cluster detection is
  now skipped for an `"unresolved"` table anchor.
- `core/draft_model_report.py`: new `cross_domain_handoffs` report key per domain,
  kept separate from `relationship_questions`.
- New/updated tests: `tests/test_claim_registry.py` (`TestDomainHandoff`,
  `TestRelationshipCandidateClusterMerge`), `tests/test_migrate_claims.py`
  (`TestDomainHandoffMigration`), `tests/test_propose_alignment.py`
  (`TestTechnicalActorSafeguard`, `TestIdentifierEvidenceSafeguard`,
  `TestTypedLocationEvidenceSafeguard`, `TestRelationshipClusterId`,
  `TestClusterObjectPropertyCandidates`), `tests/test_draft_model_report.py`,
  and new scenario coverage
  (`tests/scenarios/test_scenario_cross_module.py::TestCrossModuleOwnershipHandoff`,
  `tests/scenarios/test_scenario_unresolved_relationship_clusters.py`).

---

## DD-128: Intent-Preserving Coverage Classification, Run-Atomic Registry Writes, and Authoritative Model Precedence

**Status:** Accepted
**Date:** 2026-07-26
**Affects:** `core/claim_coverage.py`, `core/claim_registry.py`, `core/lifecycle_gate.py`,
`core/propose_alignment.py`, `cli/main.py` (`check-claims`, `propose-alignment`)
**Implementation:** `ClaimCheckReport.unresolved_anchor_tables`,
`claim_registry.ANCHOR_STATE_UNRESOLVED`, the staged-write commit phase in
`_propose_alignments`, the provider preflight in `_propose_alignments`

### Context

Three defects surfaced in review of the RC7 lifecycle work (DD-121, DD-122, DD-124):

1. **Intent lost in the coverage gate.** DD-124 makes an unresolved-anchor table emit
   *zero* claims and *zero* covered columns on purpose. DD-121/F6's column-omission gate
   compares registry-covered columns against the affinity `total_columns` and therefore
   read that deliberate emptiness as a **blocking** truncation ("columns were dropped
   before the Claim Registry"), telling the operator to re-run `propose-alignment` for a
   condition re-running can never fix.
2. **A write that contradicted the failure contract.** `AlignmentTotalFailureError` states
   that no registry was written. The per-domain write gate only skipped a domain that was
   *entirely* `provider_failure` or *entirely* `fallback_only`, so a domain **mixing** the
   two (e.g. one table with an ambiguous anchor, one whose provider call failed) — and an
   opted-in `--allow-fallback-output` domain — was written inside the loop, before the
   run-wide verdict existed. The error then claimed nothing had been written.
3. **Model precedence inverted.** `propose_alignment_cmd` resolves model precedence
   (explicit `--model` > `--high-accuracy` preset > `KAIROS_AI_ALIGNMENT_MODEL` >
   default), but `_propose_alignments`' provider preflight reassigned
   `model = provider_config.model`, re-applying `resolve_role_model` and letting the env
   override silently beat an explicitly pinned model — for the real LLM calls, the cache
   params hash, and the recorded `model_used`.

### Decision

**(1) Deliberate emptiness is classified as its own fact.** `claim_registry` names the
state (`ANCHOR_STATE_UNRESOLVED`), and the F6 comparison in
`claim_coverage.evaluate_claims_coverage` skips any table whose registry coverage carries
it. Such tables are reported in a new, **non-blocking**
`ClaimCheckReport.unresolved_anchor_tables` facet (domain → `"system.table (class anchor
unresolved — no claims emitted for N source column(s))"`), included in `has_warnings`,
excluded from `is_blocking`, projected additively into `_claim_report_to_dict` (hence
`check-claims --format json`), and rendered by `check-claims` with remediation that points
at the anchor decision (`{domain}-unresolved-anchors.yaml` / the conformance artifact) —
not at a re-run. Genuine omissions still block, including for a domain that has both.

**(2) Registry writes are run-atomic.** `_propose_alignments` no longer writes inside the
per-domain loop. Each eligible domain is *staged* (registry + unresolved-anchors document,
in domain order, alongside freshness-cache-skipped domains so the returned path order is
unchanged) and committed only **after** the run-wide tally is known and the total-failure
check has passed. The no-write guarantee therefore holds for every total-semantic-failure
run — mixed domains and opted-in fallback-only domains included — and pre-existing files
are never touched by a failed run. The per-domain gates are retained: they still skip
all-`provider_failure` and (without opt-in) all-`fallback_only` domains, and still report
why.

**(3) The caller-resolved model is authoritative.** The preflight keeps
`resolve_provider_config` for provider/endpoint/auth discovery and reporting, but never
reassigns `model`. When the per-role override differs from the caller's model, a verbose
note says it was not applied. `KAIROS_AI_ALIGNMENT_MODEL` keeps its documented role as the
*default* — the CLI still applies it when neither `--model` nor `--high-accuracy` pins one.

### Rationale

A governance gate that cannot distinguish "intentionally empty" from "silently truncated"
trains operators to ignore it; naming the intent (rather than widening the blocking rule)
keeps truncation integrity strict while making the pending anchor decision actionable.
Staging writes is the only way to make the error message and the filesystem agree without
either weakening the message or inventing a rollback of files already written — the run
simply has no side effect until its verdict is known. And precedence must be decided in
exactly one place: the caller that knows whether the operator pinned a model, since an
environment default silently overriding an explicit flag is indistinguishable from a bug
at the point of use.

### Consequences

- `check-claims` gains a non-blocking `⚠ Unresolved class anchors` section and an additive
  `registry.unresolved_anchor_tables` JSON key (additive → no
  `CLAIM_CHECK_RESULT_SCHEMA_VERSION` bump). Registries written before the `"unresolved"`
  anchor state existed never carry one, so their classification is unchanged.
- A domain whose only shortfall was an unresolved anchor no longer blocks `check-claims`;
  it now reaches the ordinary freshness bucketing (`ok`/`stale`/`unverifiable`).
- `propose-alignment`'s `✓ Written` / `🧭 Unresolved anchors` lines are now printed after
  all domains are processed (the commit phase), not interleaved with per-domain analysis.
  Returned paths, file contents, and per-domain skip reporting are unchanged.
- On total semantic failure, an opted-in (`--allow-fallback-output`) fallback-only domain
  is no longer written — a deliberate narrowing of DD-121's stated behavior, in favor of the
  stronger, uniform no-write guarantee.
- `KAIROS_AI_ALIGNMENT_MODEL` no longer overrides `--model`/`--high-accuracy`; a hub that
  relied on it winning must drop the explicit flag (its default behavior is unchanged).
- New tests: `tests/test_claim_coverage.py::TestUnresolvedAnchorCoverage`,
  `tests/test_propose_alignment.py::TestTotalFailureNoWriteGuarantee`, and
  `tests/test_propose_alignment.py::TestModelPrecedence`.

---

## DD-129: Domain-Scoped Active Source Authority for Projection Readiness

**Status:** Accepted
**Date:** 2026-07-26
**Affects:** dbt bind/normalize/materialize phases, projection readiness, source mappings,
preparation and identity evaluation
**Implementation:** `projections/dbt/context.py::ActiveSourceScope`,
`projections/dbt/bind.py::_active_source_inputs`

### Context

The dbt bind phase loaded every source vocabulary and mapping document for every selected
ontology. Downstream preparation and mapping checks then evaluated unrelated-domain mappings.
Generated vocabularies for contracted dbt outputs could also be present on disk but absent
from the effective source set used by a later stage.

### Decision

The bind phase still loads the complete registered source vocabulary before validation, then
derives one immutable active-source scope for the selected ontology. A source table enters
that scope through a selected-domain table mapping, an active contracted virtual source, a
contract replacement input, or an identity dependency required by the selected domain.
Every inclusion carries a deterministic reason.

The scoped systems, mappings, contracts, and preparation policies are the only source
authorities passed to normalization, identity, coverage, and physical planning. Contracted
virtual sources are registered relations but do not acquire physical preparation obligations.
Final custom dbt package assembly uses the union of those active contracts and their declared
custom-model dependency closure rather than re-scanning every hub transformation as selected.

### Rationale

Scoping after source discovery preserves conflict detection and contracted-vocabulary
recognition while preventing unrelated mappings from creating false policy obligations.
Deriving the scope once avoids separate stage-specific interpretations of which source tables
are active and makes readiness diagnostics explainable.

### Consequences

- Domain-scoped readiness ignores mappings that target another ontology.
- Cross-domain sources required by an actual identity/FK dependency remain active and state
  that dependency as their reason.
- Generated contracted dbt vocabularies participate in mapping and identity validation.
- Readiness JSON includes the active source inventory by domain.
- Preparation output is domain-scoped; unrelated array-child preparation models are no longer
  emitted for another domain's projection.
- Domain-scoped dbt output excludes unreachable contracted transformations owned by another
  ontology, while full-hub output remains the union of all selected domain closures.

---




## DD-130: Silver-ext Shape Discovery with Packaged Fallback and Windows-Safe Loading

**Status:** Accepted
**Date:** 2026-07-26
**Affects:** `validate-silver-ext` / `scaffold-silver-ext` CLI commands, `core/design_validation.py`
**Implementation:** `resolve_silver_ext_shapes()` and the shape-load block in
`core/design_validation.py`; `validate_silver_ext_cmd` / `scaffold_silver_ext_cmd` in `cli/main.py`

### Context

`validate-silver-ext` hardcoded the hub-local shape at
`model/shapes/kairos-ext-shapes.shacl.ttl` and passed the absolute `Path` straight to
`rdflib.Graph.parse()`. On a hub missing that managed shape (older or partially migrated
hubs), the missing path fell through to rdflib's URL handling, which on Windows mis-read a
drive letter (`G:\...`) as URI scheme `g` — a misleading error that blocked DD-108/DD-109
validation from ever starting. There was no `--shapes` override and no packaged fallback.

### Decision

1. Add a shared `resolve_silver_ext_shapes(hub)` resolver: prefer the hub-local managed
   shape, else fall back to the packaged canonical shape shipped in the scaffold; report the
   selected source on stderr (stdout stays pure JSON).
2. In `validate_silver_extension`, return a dedicated `silver.shapes-missing` diagnostic when
   the shape file does not exist, and parse via a resolved `file://` URI so a drive-letter
   path is never treated as a URL scheme. Malformed Turtle still yields the existing
   `silver.shapes-load-error`.
3. Add a `--shapes` override validated by `click.Path(exists=True, ...)` so a bad path fails
   at Click parsing, before rdflib. `scaffold-silver-ext` reuses the same resolver.

### Rationale

Centralising transport/existence handling in the core validator fixes every caller at once,
while the packaged fallback keeps older hubs validating without weakening checks. New/updated
hubs still receive the managed shape via scaffold install, so the fallback is additive.

### Consequences

- `validate-silver-ext` runs on Windows when the hub-local shape is absent but the packaged
  shape exists, and reports which shape source was used.
- A missing shape now surfaces as `silver.shapes-missing`, never as URL scheme `g`.
- CLI stdout remains pure JSON; the selected-source line is emitted on stderr, so callers that
  parse output must read stdout (tests updated accordingly).

---

## DD-131: Multi-Class Property Domains via a Single Effective-Domain Resolver

**Status:** Accepted
**Date:** 2026-07-26
**Affects:** `core/projections/shared.py`, `core/semantic_index.py`,
`core/projections/dbt/bind.py`, `core/projections/medallion_dbt_projector.py`,
`validate-mapping` (`core/design_validation.py`)
**Implementation:** `effective_domain_classes()` / `properties_with_domain()` in
`core/projections/shared.py`, consumed by the semantic index, dbt bind, and the
medallion dbt projector's datatype-property membership loops.

### Context

A property whose domain legitimately spans several classes with **no common local
parent** (e.g. a `currency`/`amount` shared by `Invoice` and a parentless charge
line) could not be declared in a DL-correct way that the toolkit honoured
(issue #240). `owl:unionOf` domains and `schema:domainIncludes` were silently
ignored, and repeated `rdfs:domain` only "worked" by accident in SPARQL-based
projectors while being unreliable in dbt, which read a **single-valued**
`graph.value(prop, RDFS.domain)`. Because each projector resolved domains its own
way, the same ontology could be answered differently depending on the target.

### Decision

1. Introduce one shared resolver, `effective_domain_classes(graph, prop)`, that
   returns the union of: (a) direct `rdfs:domain` URIRef objects, (b) members of an
   `rdfs:domain [ owl:unionOf ( ... ) ]` blank node, and (c) `schema:domainIncludes`
   URIRefs. A companion `properties_with_domain(graph)` enumerates every property
   carrying any of these forms. `SCHEMA = Namespace("http://schema.org/")`.
2. Route the semantic index (the `validate-mapping` resolution path), dbt
   `bind.active_properties`, and the medallion dbt projector's datatype-property
   membership loops through this single helper. Repeated `rdfs:domain` is formally
   **treated as union** (not DL intersection) for projection/validation.
3. Scope is intentionally limited to **Silver + dbt + `validate-mapping`** — the
   acceptance-criteria minimum. a2ui / azure-search / neo4j / gold / prompt / MDM
   remain out of scope.

### Rationale

Computing domain membership in exactly one place removes the "answered differently
by accident" trap the issue calls out and makes the single-URIRef case
behaviour-preserving (no baseline churn). The helper lives in `core` and is imported
by `core` consumers only, respecting the one-way `core`↛`mdm` layering (MDM-DD-002).

### Consequences

- A datatype property with a union / `domainIncludes` domain is now recognised on
  **every** member class by the semantic index, so `validate-mapping` accepts a
  column mapped to it from any member class's table (no false
  `mapping.property-outside-target-class`).
- Silver columns remain **mapping-driven** (a property becomes a column only when a
  source column is mapped to it — DD-110 parity manifest), so the projector changes
  affect DDL/analyses/schema-facts and virtual-source (unmapped-table) inclusion,
  while the resolution/validation layer is where multi-class domains take effect.
- Object-property / FK union-domain resolution is **not** changed (datatype-only);
  extending it is a possible follow-up.

---

## DD-132: Fact-Extraction Decomposition Guarded by a Full-Artifact Characterization Baseline

**Status:** Accepted
**Date:** 2026-07-27
**Affects:** `core/projections/medallion_dbt_projector.py`,
`core/projections/dbt/policy_normalize.py`, `tests/scenarios/`
**Implementation:** decomposed helpers in `medallion_dbt_projector.py`
(`_extract_silver_model_facts` / `_extract_schema_model_facts`) and
`_index_preparation_policies()` in `policy_normalize.py`; guarded by
`tests/scenarios/test_scenario_dbt_characterization.py` against the frozen
`tests/scenarios/fixtures/dbt_artifact_baseline.json`, regenerated deliberately via
`tests/scenarios/regenerate_dbt_artifact_baseline.py`.

### Context

The medallion dbt fact-extraction functions had grown large and multi-purpose,
making them hard to read and risky to change. A pure refactor (extracting smaller
helpers) must not alter a single byte of generated dbt output, but the existing
behavioural scenario tests only assert individual columns/warnings/SQL fragments —
they cannot detect subtle artifact drift or emission-order changes across the whole
artifact map.

### Decision

1. Decompose the large fact-extraction / preparation-normalization functions into
   smaller single-purpose helpers with no change to emitted artifacts.
2. Add a **characterization test** that pins the *complete* generated artifact set
   (all file paths + byte content, plus the non-file `__coverage_data__` /
   `__release_data__` / `__unbound_eligible__` facts) for the acme-hub client,
   invoice, and logistics scenarios as one ordered sequence (file and non-file keys
   interleaved in true emission order) against a frozen SHA-256 baseline.
3. Ship an explicit `regenerate_dbt_artifact_baseline.py --write` script so an
   *intentional* output change is a deliberate, reviewable act, never silent drift.

### Rationale

A byte-and-order-level baseline is the strongest possible guard for a
behaviour-preserving refactor: any accidental drift fails loudly, while intentional
changes remain possible through a documented regeneration path. Keeping the baseline
as one interleaved sequence preserves the real file/non-file emission ordering that
splitting into separate lists would silently discard.

### Consequences

- The fact-extraction refactor is provably output-neutral for the covered scenarios;
  future projector edits that change any artifact byte or ordering fail the
  characterization test until the baseline is deliberately regenerated and reviewed.
- Interoperates with DD-131: the `effective_domain_classes` domain resolution is
  behaviour-preserving for the single-domain acme-hub properties, so the baseline is
  unchanged by that logic.

---

## DD-133: V5 Authoring Break — YAML EntityBinding + Stateless `compile`

**Status:** Accepted
**Date:** 2026-07-27
**Affects:** new `src/kairos_ontology/core/compiler/`, new
`src/kairos_ontology/cli/compile.py`, existing
`core/projections/dbt/` (reused phases), `kairos-design-domain` +
`kairos-design-mapping` skills, `tests/scenarios/v5-hub/`
**Implementation:** `src/kairos_ontology/core/compiler/`,
`src/kairos_ontology/cli/compile.py`, the lean packaged hub scaffold, and the companion
contract [`dd-133-v5-entity-binding-compile.md`](dd-133-v5-entity-binding-compile.md).

### Context

The v4 authoring/operating experience accumulated too many overlapping authorities —
claims, mapping TTL, preparation TTL, Silver-extension TTL, transformation contracts,
virtual sources, readiness reports, lifecycle/phase state, and release evidence — layered
on top of an otherwise capable immutable dbt projection pipeline. Authoring a single
canonical entity required editing several TTL authorities and passing multiple gates.

V5 collapses this to **one** authoring authority and **one** execution path. Because this
is a clean break, **no v4 hub compatibility, dual-format authoring, migration command, or
upgrade path is provided** — existing client hubs are **rebuilt from fresh** as v5 hubs.

### Decision

1. **One authoring authority:** a concise, closed **YAML `EntityBinding`** is the single
   source-to-canonical execution authority. OWL/TTL remains authoritative for the canonical
   Silver model; source vocabularies remain authoritative for Bronze; hand-authored dbt
   remains authoritative for complex relational transforms. The binding *references* these;
   it never copies or replaces them, and it is validated by a packaged JSON Schema then
   converted directly into frozen dataclasses and the existing graph-free mapping AST —
   **never** serialized to intermediate RDF.
2. **One execution path:** a **stateless `compile`** command with mutually exclusive
   `--check` / `--explain` / `--emit` modes. `--check`/`--explain` never write hub files;
   `--emit` builds a complete in-memory plan then writes atomically via same-volume
   stage-then-swap over a manifest-owned target subtree. Kairos persists **no** lifecycle,
   readiness, proposal, claim, or verification state.
3. **Reuse, don't rebuild:** the new `core/compiler/` package adapts the existing immutable
   `bind → normalize → shape → materialize → render` dbt phases via graph-free authored
   facts — there is no second renderer. `core/compiler` must never import
   `kairos_ontology.mdm` (layering rule).
4. **Minimal non-suppressible safety kernel** gates emission; focused data-quality checks
   are evidence emitted as ordinary dbt tests, not a Kairos runtime-result contract.
5. **Superseded-for-the-v5-path at acceptance** (then deprecated-but-operative, not
   deleted from decision history): the
   lifecycle/readiness/release, claims/synchronization, and mandatory-preparation/
   virtual-source/contract-identity decisions listed in the companion doc §9. Their v4
   command paths were to keep working until retirement. Stage 4 subsequently removed them
   under DD-135/DD-136 and the retirement inventory. DD-107's graph-free scalar AST
   is **retained and reused**; only its RDF-authored, preparation-routed acquisition path is
   superseded.
6. **Stage 2 closed contract:** `load` is discriminated between full refresh and complete
   incremental SCD1/SCD2 policy; relationships are discriminated between non-temporal,
   current, and as-of policy; multi-source materialization requires explicit conformance,
   precedence, conflict, and union/dedup policy; and `source.dbtModel` carries required SQL
   and authoritative dbt-contract paths. All values load into frozen types. Unknown fields,
   duplicate YAML keys, incomplete variants, and ambiguous CDC operation values fail with
   source-located diagnostics. No v4 shape is accepted.

The full normative contract — hub layout, closed YAML schema, scalar-expression grammar,
safety kernel, atomic-emission contract, scope/provenance rules, and a canonical example —
lives in the companion doc.

### Rationale

- A single closed binding removes the multi-authority coordination cost and the classes of
  bug that came from claims/preparation/virtual-source drift, while the closed grammar and
  allow-list keep it from becoming a new dumping ground.
- Reusing the already-immutable, already-graph-free mapping AST (`AuthoredExpressionFact` is
  a "graph-free structural copy") means v5 inherits the tested typed/deterministic rendering
  behavior instead of forking a second pipeline.
- Statelessness makes builds reproducible and eliminates the readiness/lifecycle/evidence
  persistence that coupled authoring to operational state.
- A clean break (no compatibility) is acceptable because client hubs are rebuilt from fresh,
  so migration machinery would be pure cost.

### Consequences

- The complete strict kernel is implemented, including
  incremental/SCD canonical hashing, temporal relationships, explicit conformance, adapter
  capabilities, and direct contracted dbt SQL/YAML sources.
- The one-binding-per-source rule remains: each document selects one relation or one
  contracted dbt model. Multi-source materialization uses separate bindings with one explicit,
  deterministic conformance contract.
- Stage 3 establishes immutable `CompilePlan` as the sole canonical Silver/dbt planning
  authority and `compile` as the only generation path. Optional Gold/MDM consumers reuse the
  typed plan. Immutable phases, typed policy/expression structures, adapters, canonical
  hashing, and deterministic renderers are retained.
- Stage 4 retired every inventoried v4 operational wave and its commands/tests/assets; it did
  not add v4 compatibility, dual authoring, or migration. The earlier
  deprecated-but-operative state is preserved above as cutover history.
- The adapter seam into the existing phases was de-risked by `v5-seam-spike` before the YAML
  schema was locked.
- Skills become thin LLM loops over deterministic primitives — no second proposal DB or
  session-state subsystem is introduced.
- The lean scaffold, active documentation, CLI navigation, downstream-consumption guidance,
  and managed skills describe the implemented clean-break architecture.
- Documentation consolidation is not v5 GA publication; version/tag/assets and publication
  verification remain a separate maintainer release operation.

---

## DD-134: Immutable, Reversible Unreleased Toolkit Testing

**Status:** Accepted
**Date:** 2026-07-27
**Affects:** `update` CLI, hub `pyproject.toml` / `uv.lock`, managed-file refresh,
toolkit operations and release guidance
**Implementation:** `src/kairos_ontology/cli/main.py` (`update --test-ref`,
`update --restore`, test-ref state and dependency transaction helpers)

### Context

Testing toolkit work in a real hub previously required publishing a formal
pre-release or manually editing dependency pins. A mutable branch pin was not
reproducible, while manual restoration could resolve to a different release or
lose the exact prior source. Same-version test commits also risked skipping the
managed-file refresh, especially around Windows executable locking.

### Decision

`update --test-ref <branch-or-sha>` resolves the GitHub ref before mutation and
accepts only its immutable 40-character commit SHA. It rewrites every PEP 508
toolkit dependency while preserving extras, locks and syncs, and forces managed
files to refresh from the tested commit. The existing release channel remains
unchanged; testing creates no tag, release asset, version bump, or CHANGELOG
entry.

The hub records the requested ref, resolved SHA, and exact prior dependency
source in temporary, visible `[tool.kairos.test-ref]` metadata. `--restore`
restores that exact source, removes the metadata, relocks/resyncs, and refreshes
released managed files. Nested sessions and restore without valid metadata are
rejected. `--upgrade`, `--test-ref`, and `--restore` are mutually exclusive.

Dependency-file changes are transactional: failures restore the original
`pyproject.toml` and `uv.lock` bytes. Windows reuses the detached self-update
helper from DD-057, including forced refresh and its transcript.

### Rationale

Resolving mutable names once combines convenient branch testing with a
reviewable, reproducible pin. Saving the source rather than only a channel or
version guarantees exact restoration. Reusing the established transaction and
Windows refresh mechanisms avoids a second, platform-specific update path.

### Consequences

- During a test, expected hub drift is limited to dependency files and
  toolkit-managed `.github` files (plus the normally ignored Windows refresh
  transcript); ordinary channel selection is unaffected.
- Hubs retain visible restore authority until a successful `--restore`.
- GitHub/`gh` access is required for ref resolution, and Windows users must wait
  for the detached helper before testing or reviewing the final diff.
- Failed synchronous resolution, locking, syncing, scheduling, or refresh does
  not leave a partially changed dependency state. A detached Windows-helper
  failure remains recoverable from its transcript and the saved restore state.

---

## DD-135: Retire V4 Release and Lifecycle Orchestration

**Status:** Accepted
**Date:** 2026-07-27
**Affects:** release evaluation, lifecycle/status scanning, projection readiness, CLI and scaffold
**Implementation:** `docs/design/stage4-retirement-import-inventory.json`,
`tests/test_stage4_retirement_inventory.py`, and the canonical v5 compiler

### Context

DD-133 made `CompilePlan` the canonical Silver/dbt planning authority. The older release
evaluator, lifecycle gate, projection-readiness planner, and status scanner duplicated planning
and persisted heuristic lifecycle evidence after their production consumers had been cut over.

### Decision

Delete those four modules after the deterministic AST inventory proves their production import
edges are zero. Remove their Click commands and lifecycle-state scaffold. Retained diagnostics
and routing consume ordered compiler diagnostics; source analysis, ontology/reference inventory,
update/version diagnostics, and compiler diagnostics remain supported.

### Rationale

One typed planning authority prevents readiness and release heuristics from disagreeing with the
artifacts the compiler can actually emit. A versioned retirement gate makes deletion reviewable
and prevents a removed subsystem from being reintroduced by an unnoticed import.

### Consequences

- `check-projection`, `check-release`, and `status` are no longer CLI commands.
- Importing any retired module raises `ModuleNotFoundError`.
- New hubs do not scaffold `.kairos-state`; flow and diagnostic skills are stateless.
- Compile success is not a runtime-validation or release-certification claim.
- The transformation evidence/synchronization/candidate, preparation/Silver RDF authority,
  report/session persistence, release-baseline, and obsolete-command waves recorded in the
  same inventory are also retired. Ordinary contracted dbt SQL/YAML source contracts and
  reusable source/ontology/compiler/rendering architecture remain.

---

## DD-136: Retire V4 Claim Binding and Completeness Authority

**Status:** Accepted
**Date:** 2026-07-27
**Affects:** claim registry/binding/completeness modules, dbt shared phases, CLI, scaffold,
managed skills, and Stage 4 architecture gates
**Implementation:** `docs/design/stage4-retirement-import-inventory.json`,
`tests/test_stage4_retirement_inventory.py`

### Context

The v5 compiler makes reviewed `EntityBinding` YAML the only materialization authority.
V4 claims, aspirational Silver stubs, and completeness-policy gates duplicated that decision
and left dead authority embedded in otherwise reusable normalization and rendering modules.

### Decision

Delete the claim, binding-analysis, completeness, and source-coverage modules and their command,
scaffold, export, and test surfaces. Remove aspirational/stub and claim-eligibility branches from
shared dbt phases. Retain only source analysis, ontology/reference loading, Gold/MDM consumers,
typed expression/policy structures, renderers, and the ontology-only discriminator predicate
required by active compiler paths.

The deterministic Stage 4 inventory asserts zero production imports, absent retired modules and
commands/assets, mirrored managed skills, and absence of retired production markers.

### Rationale

One binding authority prevents source evidence, claims, stub eligibility, and completeness
heuristics from disagreeing. Extracting narrow shared predicates before deletion preserves the
v5 compiler and downstream consumers without retaining V4 governance semantics.

### Consequences

- V4 claim, aspirational-stub, and completeness commands and Python APIs no longer exist.
- Unbound entities fail through compiler diagnostics; no empty Silver model is emitted.
- Source completeness remains an interactive onboarding question, not projection authority.
- Historical DD-094 through DD-096 describe retired V4 behavior and are superseded here.

---

## DD-137: Derived, Stateless Readiness Proposal (`kairos-ontology next`)

**Status:** Accepted
**Date:** 2026-07-28
**Affects:** CLI (`next`), `core/next_actions.py`, `core/hub_inspection.py`, `kairos-flow` and
`kairos-diagnose-status` skills (and their scaffold copies)
**Implementation:** `src/kairos_ontology/core/next_actions.py`,
`src/kairos_ontology/core/hub_inspection.py`, `src/kairos_ontology/cli/inspection.py`,
`tests/test_next_actions.py`, `tests/test_cli_next.py`

### Context

V5 is stateless (DD-133/DD-135): design skills surface next actions conversationally, but nothing
persists them and `kairos-flow` must never create a continuation record. Two skills independently
encoded a next-action decision tree in non-deterministic, untestable LLM prose, so routing could
drift between sessions and between skills. Users asked for a repeatable, drift-free way to
recompute and present the next action without reintroducing a stored state file.

### Decision

Add a read-only `kairos-ontology next` command that gathers a defensible, in-memory snapshot of
authored inputs and canonical compiler status, then derives an advisory, deterministic
`NextActionProposal`. The pure proposer (`core/next_actions.py`) performs no I/O and holds no
state; the I/O gatherer (`core/hub_inspection.py`) reuses the existing binding loader and compiler
entry points rather than adding an alternate resolver. The command is the **single deterministic
routing authority**: `kairos-flow` and `kairos-diagnose-status` consume its JSON and map stable
action kinds to owning skills instead of re-deriving their own decision tree.

The proposal reports only defensible observations — authored input present/missing/unreadable,
canonical compile status and ordered diagnostics, and authored optional (Gold/MDM) policy presence.
Stages whose completion cannot be proven from authored inputs are emitted as
`human_decision_required`; when the compile check is skipped, downstream readiness is
`indeterminate`. JSON is clean on stdout with the advisory banner on stderr; exit is `0` for any
advisory proposal (including blocking diagnostic actions, which are data) and non-zero only for an
operational error such as an unresolved hub.

### Rationale

One deterministic routing authority prevents the two skills' heuristics from disagreeing and makes
routing testable and byte-stable. Keeping the proposal derived and advisory — recomputed every run,
never persisted — preserves the stateless architecture instead of reviving a state file.

### Contrast with the retired DD-135/DD-136 readiness subsystem

This is explicitly **not** the retired lifecycle/status/completeness authority. It never persists a
continuation record, never claims semantic completeness from file presence, and never becomes an
alternate compile or materialization authority. File presence is reported as presence only; the
canonical compiler remains the sole planning authority and its diagnostics are surfaced verbatim.

### Consequences

- `kairos-ontology next` exists as a read-only advisory command; no state is written.
- `kairos-flow` and `kairos-diagnose-status` stop independently routing and consume the proposal.
- A passing compile check reported here is not a downstream runtime or release guarantee.
- Adding a new action kind requires extending the single `ACTION_SKILLS` routing map.

### Amendment (proposal schema v2): optional offline dbt gate

`SCHEMA_VERSION` is bumped to `2`. The snapshot gains one additional **defensible emitted-output
observation**, `emitted_dbt_project` (presence/unreadable/missing of
`output/medallion/dbt/dbt_project.yml`), plus the configured `adapter` used only to render a
command. When an emitted project is observed **and** at least one domain currently passes the
compile check, the proposer surfaces a single hub-level `validate-dbt` action with status
`optional` (never `blocking`, never a mandatory sequential step). This deliberately does **not**
reintroduce lifecycle state: the observation is presence-only, cannot prove the emitted project is
fresh or that the current CompilePlan produced it, and disappears when the emitted project is
absent. The action routes to `kairos-execute-validate`, matching the opt-in offline
`deps → parse → manifest → compile` gate (see the DD-110 parity check in `core/dbt_validation.py`).
An unreadable emitted project yields `human_decision_required` instead.

---

## DD-138: Cross-domain Relationship Targets via External References

**Status:** Accepted
**Date:** 2026-07-28
**Affects:** V5 `EntityBinding` relationship declarations, compiler BuildScope resolution,
relationship diagnostics, provenance hashing, and generated dbt relationship tests
**Implementation:** Accepted. `RelationshipSpec` gains an external-reference field; the
compiler resolves the declared key contract. Physical cross-domain `ref()` emission is enabled
by the unified topology accepted in DD-140.

### Context

DD-133 §7 already allows a relationship target to be either another entity with a binding and
model in the current domain scope, or an explicitly declared external reference that the compiler
can treat as a resolvable parent without generating that parent. DD-133 §8 deliberately keeps
`compile <domain>` per-domain: the BuildScope includes bindings whose `metadata.domain` matches,
with stable ordering and one `by_target` binding per class. Earlier DD-019, DD-027, and DD-097
record historical demand for cross-domain foreign-key wiring, but they predate the v5 authoring
break and must not be treated as automatic v5 scope-widening requirements.

### Decision

Add an explicit external-reference declaration to a relationship target. The declaration names the
external parent and states its key contract: ordered key column name(s), canonical key type(s), and
optionally the expected package/model identifier once emit topology is decided. The compiler
resolves the relationship against that declared contract and does not generate a model for the
parent.

The contract is fail-closed:

- a missing target declaration remains a missing-target diagnostic;
- a relationship join column that cannot be mapped to an output column is a missing-key
  diagnostic;
- incompatible child and external key types are a type diagnostic;
- composite keys are ordered tuples, and cardinality, order, names, and types must all match;
- runtime names reserved for generated columns remain reserved for the child side of the join.

Resolution is deterministic. The compiler must not search peer-domain bindings or choose an
arbitrary binding from a class-local `by_target` map. The declared external-reference contract is
the authority, even when a peer hub happens to contain a binding for the same ontology class.

The naive alternative, resolving through a peer binding's key output, is rejected. It depends on
which peer bindings are loaded, on peer authoring order, and on `by_target` retaining only one
binding per class, so it can silently select the wrong physical parent. If maintainers ever choose
scope widening instead, that would be a separate decision coupled to the emit/dbt-package topology
in DD-140 because cross-domain `ref()` wiring is only reachable when the generated package layout
contains both domains in a deterministic project graph.

Provenance hashing should include the external-reference declaration because it affects the
compiled contract and generated tests. Peer inputs should not enter the BuildScope hash merely
because they exist elsewhere. They enter provenance only if a future accepted topology decision
explicitly widens scope to load peer bindings or package manifests as compiler inputs.

### Rationale

The explicit contract follows DD-133 §7 without weakening the per-domain BuildScope. It gives
relationship validation enough information to be deterministic and testable while keeping model
ownership clear: the child domain can assert how it references an external parent, but it does not
compile that parent.

### Consequences

- ISSUE-7 / Workstream C should implement the DD-133 external-reference route first.
- Tests should cover missing target, missing key, incompatible types, composite-key ordering, and
  deterministic behavior when peer bindings for the target class also exist.
- Generated docs and diagnostics must make clear that an external reference is a contract, not a
  discovered peer model.
- Cross-domain physical `ref()` generation remains blocked on DD-140 unless the external parent is
  made available by the selected dbt package topology.

---

## DD-139: Authored Passthrough Technical Columns — DD-107 Amendment

**Status:** Accepted (implemented; auto-materialization stays rejected)
**Date:** 2026-07-28
**Affects:** DD-107 materialization authority, v5 `EntityBinding` schema, source-column
ownership, Silver contract parity, manifest/parity hashing, and mapping diagnostics
**Implementation:** Implemented. The closed-schema `technicalFields:` construct is authored
alongside `fields:` (`entity-binding.schema.json` / `TechnicalField` in `bindings.py`) with a
`name`/`expression`/`type`/`nullable`/`purpose` contract (`purpose` one of `identity`, `quality`,
`relationship`). `adapter.py` materializes each technical field exactly like a semantic field
(participates in the Silver schema contract, dbt SQL, and manifest/parity hash) under a synthetic
non-property marker URI, so it is never emitted as OWL and never asserts an ontology property.
Case-insensitive output-name collisions (against semantic fields, other technical fields, and
reserved runtime names) and ambiguous duplicate-source-column reuse are rejected in
`kernel.py`'s `_binding_safety_diagnostics` (`technical-field.output-collision` /
`technical-field.duplicate-source-ambiguous`); a technical field's declared type incompatible
with its bound physical source column is rejected in `adapter.py`
(`technical-field.type-incompatible`). `identity.sourceKey`/`quality.columns`/relationship
`join.local`/`join.foreign` now resolve against authored technical fields exactly as they do
against `fields:`, so the previous "map the FK join column as a scalar field" workaround is no
longer required. **Correction (#334):** the `join.foreign` half of that sentence was aspirational
when this decision was first recorded — `kernel.py`'s `_relationship_output_column` iterated
`binding.fields` only, so a parent join column carried by a technical field was rejected with
`safety.relationship-endpoint` ("relationship foreign column '…' is not mapped by the target
binding"). Any surrogate technical primary key was therefore unauthorable as a parent endpoint
and every relationship pointing at one was silently dropped. That resolution is implemented as
of #334: the lookup falls back to authored technical fields with **no `purpose` filter**
(`adapter.py` materializes every technical field regardless of purpose, so every one is a valid
join target), mapped `fields:` keep precedence, and the match is made on the technical field's
bound source `expression` column while the value returned into the join predicate is its output
`name` — a technical field renames, so returning `join.foreign` verbatim would reference a column
the parent model never emits under that name. Because `(source column, purpose)` is the
technical-field uniqueness key, one source column may legally carry two technical fields with two
output names; that case is rejected as `technical-field.relationship-target-ambiguous` rather than
resolved silently. Two adjacent holes the same change closes: a non-external relationship whose
target class is the binding's own is rejected (`relationship.self-reference-unsupported` — it would
otherwise emit `ref('<own model>')` inside that very model and a duplicate `<model>_sk`), and an
`externalReference` whose `domain` equals the binding's own is rejected
(`relationship.external-reference-same-domain` — it bypasses join validation, model-existence
checking, and the `silently-dropped-relationship` pattern check all at once). Validating that a
referenced *foreign* domain resolves stays deliberately unimplemented: the only available
mechanism ("a domain with bindings exists in this hub") would break the out-of-hub parent case
DD-138 explicitly preserves. `compile --explain` labels technical outputs separately
(`ExplainEntity.technical_fields`), distinct from the semantic `fields` pairs. As originally
decided, implicit auto-materialization remains rejected: the compiler never creates a technical
field on its own — every one must be explicitly authored in the binding YAML.
**Correction (#338, items 1 and 4):** two real dogfood gaps in this construct's boundary are
closed. First, `purpose` gains a fourth enum value, `carried`, for a plain materialized column
that is honestly none of `identity`/`quality`/`relationship` (e.g. an alternate external code
space) — previously an author had to pick a value known to be wrong. Second, `fields:` no longer
requires at least one entry unconditionally: `entity-binding.schema.json` now allows `fields: []`
when `relationships:` is non-empty (`allOf`/`if`/`then`), unblocking a class whose only property is
an object property (a pure junction/link entity, e.g. a many-to-many association row) — its own
identity and any relationship `join.local` columns are still carried via `technicalFields:` exactly
as already described above, no compiler change beyond the schema was needed. `fields: []` alone,
with no `relationships:` entry, still maps nothing at all and remains rejected.

### Context

DD-107 makes source ownership explicit: a source column becomes a materialized Silver output only
when a `fields:` expression references it. Identity, quality, and relationship join columns are
therefore expected to be mapped fields today. That rule is intentional because the `fields:` set is
the deterministic column contract used by parity checks, generated schema, and review.

However, identity keys, quality check columns, and relationship join keys are sometimes technical
columns whose materialization is needed for runtime checks but whose meaning should not invent a
synthetic ontology property. ISSUE-4/5 / Workstream B2 asks whether authors need an ergonomic,
explicit way to carry those columns through.

### Decision

Amend DD-107 to allow an explicit authored passthrough/technical field construct that materializes
a source column without asserting a new ontology property. The construct should be closed-schema,
reviewable, and distinguishable from semantic `fields:` entries. It names the source expression,
the output column, the output type, nullability, and its technical purpose such as identity,
quality, or relationship support.

Implicit auto-materialization is rejected. Automatically adding `identity.sourceKey`,
`quality.columns`, or relationship join columns would change the deterministic parity/manifest
column set behind the author's back, make compiler output depend on policy side effects rather
than the declared projection, and risk exposing PII or other sensitive source columns that were
not intentionally selected for Silver.

Validation rules should include:

- case-insensitive output-name collision checks against semantic fields, other passthrough fields,
  and reserved runtime/generated names;
- duplicate source use checks, allowing the same source column only when outputs and purposes are
  explicitly distinct and non-ambiguous;
- required output names and types, with adapter-normalized types participating in the same Silver
  schema contract as semantic fields;
- fail-closed diagnostics when a passthrough is referenced by identity, quality, or relationships
  but is missing or type-incompatible.

Passthrough columns are materialized Silver outputs and therefore affect the downstream Silver
contract, dbt schema YAML, manifest/parity hash, emitted SQL bytes, and any release evidence that
compares expected and actual columns. They are not ontology properties, are not emitted as OWL, and
must be labelled in explanations as technical outputs.

### Rationale

An explicit construct preserves DD-107's source-ownership rule while avoiding ontology pollution.
It keeps the reviewer in control of which physical columns leave Bronze/prep and makes sensitive
column exposure a conscious authored decision.

### Consequences

- Workstream B1 can remain limited to clearer diagnostics and documentation for the current rule.
- Workstream B2 requires binding-schema, normalization, render, contract, and parity-hash changes
  before authors can rely on passthrough technical outputs.
- Any implementation must treat passthrough outputs as first-class dbt contract columns but not as
  canonical ontology facts.

---

## DD-140: Canonical Emit Layout and dbt-Package Topology

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

---


## DD-141: Adopt OKF-based per-hub Decision Log as a toolkit capability

**Status:** Accepted
**Date:** 2026-07-29
**Affects:** hub scaffold decisions bundle, `decision` CLI, validation, `kairos-help`
skill, and documentation
**Implementation:** `kairos-ontology decision new`, decision-bundle scaffold files under
`ontology-hub/decisions/`, and the decision-profile validation path in
`kairos-ontology validate`

### Context

Material ontology-design decisions were being made during Copilot-assisted design, but their
rationale lived only in ephemeral conversation memory. The authored TTL states *what is true*;
it does not durably explain *why* a maintainer accepted a genuine modeling tension, real gap,
or rejected alternative. The `kairos-design-domain` workflow even described its rationale matrix
as ephemeral, so refreshes and later reviews could preserve classes and properties while losing
the evidence and trade-offs that justified them.

DD-080 and DD-085 previously used OKF-shaped `.kairos-state` phase logs for interactive session
continuation, but DD-135 retired that state structure for v5. The Decision Log is intentionally
separate from that retired session state: it is durable, human-reviewed hub documentation for
material decisions, not a lifecycle or continuation store.

### Decision

Adopt a per-hub **Decision Log** as a toolkit capability. Each v5 hub may carry a Google Cloud
Open Knowledge Format (OKF) v0.2 Markdown + YAML-frontmatter bundle at
`<hub_root>/decisions/` (for scaffolded hubs, `ontology-hub/decisions/`). Decision records are
named `HUB-DD-*.md`; `index.md` is generated; the README and
`HUB-DD-template.md.template` are managed scaffold files.

Authors create records with `kairos-ontology decision new`. `kairos-ontology validate` now lints
an existing bundle with the Kairos decision profile and reports two diagnostic classes:
OKF-conformance findings and Kairos-decision-profile findings. An absent bundle is skipped.

The materiality threshold is strict: log genuine tensions, real gaps, intentional standard
divergence, evidence conflicts, or decisions with persistent consequences and rejected
alternatives. Never log routine confirmations, obvious field additions, or decisions whose
rationale is already fully expressed by the authored model.

### Alternatives rejected

| Option | Why rejected |
|---|---|
| Single hand-rolled hub file like the old `docs/draft/specs.md` pattern | Does not scale beyond one or two decisions, has no machine-checkable structure, and cannot be validated as a bundle. |
| Store rationale in TTL comments | Conflates canonical facts with review rationale, is easy to drop during ontology refresh, and cannot clearly carry rejected alternatives or lifecycle metadata. |
| ADRs only under repository `docs/` | Documents toolkit choices, not per-hub modeling choices, and is not shipped with scaffolded hubs where future maintainers need the rationale. |

### Rationale

OKF gives the hub a familiar, document-oriented record format without inventing a bespoke file
syntax. A Kairos-specific decision profile can enforce the fields that make ontology rationale
reviewable — materiality, sources, status, accepted/rejected state, and rejected alternatives —
while keeping the actual record readable in any Markdown viewer.

Scaffolding the README and template makes the capability discoverable in every new hub. Generating
`index.md` avoids hand-maintained navigation drift, and validating the bundle during
`validate` puts decision quality beside ontology syntax, SHACL, binding, and compile diagnostics.

### Consequences

- Every hub can keep durable rationale for material ontology-design decisions beside its authored
  inputs.
- `kairos-ontology validate` now also lints the decision bundle when it exists; an absent bundle
  remains a compatible skip.
- PR review is the materiality backstop: reviewers should reject routine confirmations and require
  records for consequential design tensions or standard divergences.
- The Decision Log does not revive `.kairos-state`; it is a separate, durable, human-reviewed
  artifact rather than session state.

> **Amendment (2026-08-15, #420):** the resolution base for local `sources[].resource`
> citations is now documented and slightly widened. The base is the **hub root** — the
> convention every other hub path citation follows, chosen (over the `decisions/`
> directory) in issue #349 but stated nowhere until now. On a **nested** hub (a hub
> inside a toolkit-managed repository root, detected via
> `hub_utils.resolve_repo_root` = `find_managed_root(hub_root) or hub_root`),
> citations whose first segment is `.import/` or `ontology-reference-models/` — the
> two repo-root siblings a hub-root join can never reach — additionally fall back to
> the **repository root**. No other path ever probes the repo root, so a rotted hub
> citation cannot be silently satisfied by the repo's own same-named file. Bare/test
> hubs without a toolkit pin degrade to hub-root-only resolution. `_is_local_path`
> is widened to recognize `.import/` citations (either separator; backslashes are
> normalized before joining) and the binary evidence extensions
> `.pdf`/`.docx`/`.xlsx`/`.pptx`, all extensions matched case-insensitively.
> Accepted consequence: a prose citation that merely *ends* in `.pdf` now warns as
> unresolved — the same class of behavior `.md`-suffixed prose already had.

---


## DD-142: Derived Output Relocated to Sibling `ontology-hub-publish/` (DD-140 Amendment)

**Status:** Accepted
**Date:** 2026-07-30
**Affects:** `compile --emit`, `project`, `validate` report/shapes-draft paths, coverage/silver
reports, standalone projector defaults, scaffold `.gitignore`, `packages.yml.template`,
`release-projections.yml`, `init`/`new-repo`/`migrate`, and downstream dataplatform consumption
**Implementation:** `publish_root(hub) = hub.parent / "ontology-hub-publish"` in
`core/hub_utils.py`, routed through every hub-anchored `…/output` path; `output` removed from the
hub marker directories and the fresh-hub directory contract.

### Context

DD-140 placed the derived emit tree **inside** the hub at `<hub>/output/…`. In practice this caused
recurring "wrong output folder" confusion: bare `--emit` was hub-anchored, but an explicit
`--emit <path>` resolved against the process **cwd** and skipped the canonical `…/medallion/dbt`
suffix, so running from a subdirectory produced wrong or duplicate output trees. Derived artifacts
also sat inside the authored hub, mixing generated output with authored inputs.

### Decision

Relocate the **entire** derived output tree to a **sibling** folder at the repository root, named
literally **`ontology-hub-publish`** (`<hub.parent>/ontology-hub-publish/…`). All targets move
together — `medallion/dbt`, `medallion/powerbi`, `neo4j`, `azure-search`, `a2ui`, `prompt`,
`reports/details`, `architecture/ddd`, `mdm`, validation reports, and `shapes-draft`.

The `--emit` contract (superseded by the DD-142 amendment below):

- Bare `--emit` → `publish_root(hub)/medallion/dbt` (the only value that receives the suffix).
- Explicit `--emit DIRECTORY` → the **exact** dbt project directory (no suffix appended); relative
  values are anchored to the **hub root**, never the process cwd, fixing the wandering-output bug.
- The now-inverted "outside this hub" warning is removed — the canonical target is intentionally a
  sibling of the hub.

> **Amendment (2026-07-30):** the explicit `--emit DIRECTORY` argument caused a recurring
> misplacement bug — a relative value such as `--emit ontology-hub-publish/medallion/dbt` was
> anchored to the hub root, nesting the publish tree **inside** the hub
> (`ontology-hub/ontology-hub-publish/medallion/dbt`). The emit target is therefore no longer
> configurable: `--emit` is now a **pure flag** that always writes to the fixed
> `publish_root(hub)/medallion/dbt`. Passing a directory to `--emit` is rejected. This removes the
> last way to place derived output anywhere other than the canonical sibling location.

`output` is no longer a hub marker directory (markers are `model` and `integration`), and the
fresh-hub directory contract no longer scaffolds `output/*` inside the hub. The publish tree is
still scaffolded with `.gitkeep` slot markers, but in the sibling; `.gitignore` ignores
`ontology-hub-publish/**` while preserving those markers. Distribution consumers
(`packages.yml.template` git `subdirectory:`, `release-projections.yml`) simply repoint to the new
location — the tree stays in the repository, so no outside-VCS distribution redesign is introduced.

### Rationale

A single shared `publish_root` seam removes every ad-hoc `…/output` construction and the cwd-vs-hub
ambiguity that caused duplicate trees. Separating derived artifacts from authored inputs makes the
hub directory contain only human-authored content, which is easier to review, diff, and reason
about. Keeping the tree in the repository preserves existing git and distribution behavior with a
one-line path repoint.

### Consequences

- Emitted/derived artifacts now live at `<repo>/ontology-hub-publish/…`, a sibling of
  `ontology-hub/`, not inside the hub.
- Callers must pass the **hub root** to `publish_root`; for an undiscovered hub use the
  `publish_root(cwd / "ontology-hub")` fallback (never `publish_root(cwd)`).
- Existing hubs that emitted under `<hub>/output/…` should migrate; `migrate` retargets the move to
  the sibling. The old in-hub `output/` slot is no longer created.

---

## DD-143: Standard Conformance-Report Output Format for `kairos-design-discovery`

**Status:** Accepted
**Date:** 2026-08-01
**Affects:** `kairos-design-discovery` skill (both copies), archetype conformance report authoring
**Implementation:** `.github/skills/kairos-design-discovery/SKILL.md` (Output format section),
`src/kairos_ontology/scaffold/skills/kairos-design-discovery/SKILL.md` (scaffold copy)

### Context

DD-090 introduced **Phase 2.5 — Core Concepts Conformance**, which persists a machine
`integration/discovery/core-concepts-conformance.yaml` artifact plus an OKF prose section.
The skill, however, never defined an **output format** for the human-readable conformance
report: the reference-model repo owns the interview *questions*
(`accelerator-packs/<domain>/discovery/<archetype>.md`) but not the report *shape*, so every
conformance report was authored ad-hoc. A client-hub run (`shipping-carrier` archetype)
demonstrated that a scannable, visual report (badges, Mermaid diagrams, an at-a-glance
dashboard) materially improved stakeholder review — but that visual structure had to be
hand-created each time and was not reproducible across hubs or archetypes. Because the skill
is toolkit-managed, hubs cannot bake this in locally without failing the managed-files check;
the fix must live in the toolkit.

### Decision

Give `kairos-design-discovery` a **standard conformance-report output format** documented in
its `SKILL.md`. When Phase 2.5 emits a conformance report, the report MUST render the
template structure below (each element renders natively on GitHub, no extra tooling):

1. **Outcome-code legend with badge emojis** — exactly one emoji per outcome, drawn from the
   contract's `outcome-codes.yaml` enum (loaded, never hardcoded):
   - ✅ `conforms` · 🟩 `conforms-with-rename` · 🟨 `partial` · 🟥 `deviates` ·
     ⬜ `not-applicable` · ❓ `open` · 🏗️ `in-scope-modelling-gap` · ⏸️ `on-hold`.
   - Any outcome code added to the contract later gets an emoji assigned in the skill before
     it is used in a report; unknown codes render as ⚠️ so a report never silently drops a
     concept.
2. **"📊 At a glance" dashboard** near the top of the report:
   - a **text coverage bar** (conforms + conforms-with-rename share of total concepts);
   - a **Mermaid `pie`** of core concepts by outcome;
   - a **Mermaid `flowchart`** of the client's canonical spine (the confirmed topology edges);
   - a **Mermaid `flowchart` "scope map"** grouping concepts into In-scope / To-build /
     Out-of-scope / On-hold;
   - a compact **section status matrix** table (section → outcome badge).
3. **Per-section heading badges** — every section heading leads with its outcome emoji for
   scanability, matching the legend.
4. **Interview log** section with date-stamped SME answers, recording rationale, confidence,
   and references per concept as required by fleet mode (DD-088) and the dual-persistence
   contract (DD-090).

**Mermaid label guidance (included in the template):** node labels containing special
characters (`&`, `/`, `→`) MUST be quoted as `["..."]` to avoid Mermaid parser errors — this
was a real failure during the reference run.

The report is a human-authored Markdown artifact that accompanies the machine
`core-concepts-conformance.yaml`; it never replaces the YAML as the execution authority, and
the YAML remains the single machine authority consumed by later lifecycle stages.

### Rationale

A fixed, GitHub-native report shape makes conformance outcomes scannable and comparable across
archetypes and hubs without per-run hand-crafting. Emoji badges plus Mermaid diagrams give a
stakeholder-readable at-a-glance view that the raw YAML cannot, while the YAML stays the
machine authority. Documenting the format in the managed skill (rather than the
reference-model repo) keeps report *shape* in the toolkit and interview *content* in
reference-models, matching the existing ownership split from DD-090.

### Consequences

- Every Phase 2.5 conformance report includes the badge legend, an at-a-glance dashboard with
  at least one Mermaid diagram, per-section badges, and an interview log — with no
  hand-editing.
- The scaffold copy and `.github/skills/...` mirror MUST stay byte-identical; scaffold-sync
  and managed-files tests guard this.
- The report is documentation only; it does not change the conformance artifact schema, the
  outcome enum, claim derivation, or the domain gate.
- New outcome codes in the contract require a skill update (emoji assignment) before use in a
  report; the ⚠️ fallback prevents silent concept loss in the interim.

---

## DD-144: Accelerator-Direct Binding Resolution and the Machine-Managed Domain Stub

**Status:** Accepted
**Date:** 2026-08-09
**Affects:** `core/compiler/kernel.py` (`resolve_scope`, `_ontology_symbols`),
`core/compiler/adapter.py` (`ResolutionContext`), `core/next_actions.py`
(action routing only, not the readiness ladder), `cli/inspection.py` (`coverage-report`)
**Implementation:** a wider class/property lookup inside `_ontology_symbols`'s existing,
already-loaded semantic index (no new resolver, no hub-level accelerator lookup at compile
time), plus a machine-managed domain-ontology stub generated by `scaffold-binding` (new
tooling, no separate design decision needed — see Consequences)

### Context

Raised by `docs/temp/cr-fast-path-to-silver.md` (CR-3) and sharpened in review: today, an
`EntityBinding`'s `target.class` and its properties resolve **only** against classes the
domain's own `model/ontologies/<domain>.ttl` locally declares. `_ontology_symbols`
(`kernel.py`) loads exactly one file (`load_ontology(ontology_path, ...)`), derives a
namespace from that file's own first locally-declared `owl:Class`, and calls
`list_classes(graph, namespace)` — which filters out anything outside that namespace.
Accelerator classes only become bindable today because a local class declares
`rdfs:subClassOf <accelerator class>`, which pulls the accelerator's properties in via the
semantic index's `inherited_properties` (already resolved with full `owl:imports` closure,
per DD-103). The accelerator class itself is never registered as a bindable target unless a
human re-declares it locally — which is exactly the redundant authoring step CR-1/CR-2/CR-3
exist to remove, and directly conflicts with the newer C2 principle (every Silver field
must be ontology-backed, and a decorative local re-declaration of an accelerator concept is
not "real meaning," it's restatement).

A second, harder constraint surfaced during implementation review that the original CR text
did not account for: `resolve_scope` (`kernel.py`) unconditionally requires
`model/ontologies/<domain>.ttl` to exist (`if not binding_paths or not ontology_path.is_file():`)
before compilation can even begin — independent of whether any binding in that domain needs a
local class at all. The two arms of that guard now emit **distinct** codes: a missing ontology
file raises `safety.source-unresolved`, while the ontology-only waypoint (a valid slice exists
but no `EntityBinding` is authored yet, and likewise the case where no authored binding selects
the domain) raises `scope.no-bindings-authored`. Both remain **blocking** (an un-emittable hub
still exits non-zero), but the distinct code lets a CI gate tell an expected early authoring
stage apart from a genuinely broken source, without weakening the guardrail. This means a
domain can never be truly file-less; the earlier working assumption in this initiative's
design notes (that a fully accelerator-direct domain could exist with *zero*
`model/ontologies/<domain>.ttl` file, per DD-137's `binding_only_domains` observation) does
not hold against the actual compiler contract and is corrected here: `binding_only_domains`
is an honest *reporting* observation (no ontology file was found when `next` looked), not a
compilable end state — a file must exist for `resolve_scope` to succeed regardless of this
decision.

### Decision

**1. Accelerator-direct class and property resolution — by using more of the semantic index
this code already loads, not by adding a new resolver.** A verification pass while writing
this decision found the mechanism is simpler than first scoped: `_ontology_symbols` already
calls `load_ontology(ontology_path, ...)` and builds a full semantic index
(`build_semantic_index`, DD-103) over the **entire resolved `owl:imports` closure** — every
class and property the domain ontology transitively imports, including accelerator classes,
is already indexed in `index`/`loaded.semantic_index`, exactly like any other imported term.
The actual gap is narrower than "the compiler cannot see accelerator classes": it is that
`_ontology_symbols` only ever *iterates* `list_classes(graph, namespace)` — the subset of
that already-complete index whose URI falls under the domain's own locally-declared
namespace — when deciding which classes to register as `ResolvedClass`/`ResolvedProperty`
entries. An accelerator class that is imported but never locally subclassed is present in
`index` the whole time; it is simply never looked up.

The fix: `resolve_scope` continues to register local classes/properties from
`list_classes(graph, namespace)` exactly as today (no change to that path — a local
`rdfs:subClassOf` continues to work unmodified). Additively, for each distinct
`target.class` (and relationship target class) among the bindings in compile scope that does
**not** match a locally-collected `ResolvedClass.ref`, the compiler checks whether the raw
token matches a qname/alias of any *other* class already present in the same `index` —
computed with the exact same `_qnames`/`_declared_prefix_aliases` helpers already used for
local classes, against the same already-loaded `graph` (which, because it is the
merged/resolved closure, carries the accelerator ontology's own namespace/prefix bindings
too). On a match, the compiler builds a `ResolvedClass` from the index's `ClassRecord` and
`ResolvedProperty` entries via `_class_index_properties(index, class_uri, graph)` — a
function that is **already fully generic** (it takes any `class_uri` and only reads from
`index`; it does not assume the class is local) and needs no modification at all — using
the exact token the author wrote as the `ref`, so `context.klass()`/`context.property()`
resolve it identically to a locally-declared class. **This lookup is scoped to classes
actually referenced by a binding in the current compile scope** — it computes qnames only
for the (small) set of unresolved target tokens, not for every class in a 50,000-line
accelerator index, so it never floods `context.classes`/`context.properties` or the
diagnostics' "usable class tokens" listing. If the token resolves in neither the local
namespace nor anywhere else in the index, the existing `binding.unknown-class`/
`binding.unknown-property` diagnostics fire exactly as today — this decision only adds a
resolution path, it changes no failure behavior. No hub-level accelerator identification
(`resolve_hub_accelerator_detailed`, DD-125) is needed at compile time at all: resolution
depends only on what the domain ontology file's own `owl:imports` already pulled into the
closure, exactly like resolving any other imported term.

**2. Local subclassing remains exactly as-is, required only for a confirmed deviation.**
An author still may (and, for a genuine deviation — an extra property the accelerator
doesn't model, a restricted grain, a different identity strategy — still must) declare a
local class `rdfs:subClassOf <accelerator class>` in the domain's ontology file. This is the
"local-extension boundary" DD-104/CR-TK-02 already names. Nothing about this path changes;
accelerator-direct resolution is purely a fallback for the case where no local declaration
exists.

**3. The machine-managed domain-ontology stub.** Because `resolve_scope` requires the domain
file to exist, a domain with zero deviations still needs one. `scaffold-binding` (new tooling
built on this decision, not itself a contract change) generates `model/ontologies/<domain>.ttl`
as a minimal, clearly labelled machine-managed
stub — an `owl:Ontology` declaration plus an `owl:imports` triple for each accelerator module
a binding in that domain targets, and **zero locally-declared classes** — whenever the file
does not already exist. The stub carries a header comment identifying it as machine-managed
and never intended for hand-editing, and is regenerated (imports added, never removed
automatically — removal on a claim/target going out of scope is a separate, deliberately
out-of-scope concern) whenever a binding in that domain first targets a new accelerator
module. The moment a human adds a local-extension class to this file, it stops being purely
machine-managed for that class (the file itself is not re-scaffolded away from human edits —
only its managed `owl:imports` block is kept in sync, following the same "managed block,
preserve authored content outside it" pattern DD-104/CR-TK-01 already established for
`claims-to-silver-ext`-style managed imports). `_ontology_symbols` needs no change to handle
an ontology file with zero locally-declared classes — it already falls back gracefully today
(`first_class` is `None` → synthetic `urn:kairos:ontology:` namespace → `list_classes` returns
nothing), which is precisely the correct behavior for a stub that declares no local terms.

**4. Picking *which* accelerator to `owl:import` into a brand-new stub is a scaffold-time
concern, not this decision's compile-time mechanism.** Compile-time resolution (point 1)
never needs to know which accelerator pack is active — it only ever reads whatever
`owl:imports` the domain file already declares, same as resolving any other imported term.
The question "which accelerator's `data-domains.yaml` should `scaffold-binding` write an
`owl:imports` for when a domain has no ontology file yet" belongs to DD-125's existing
`resolve_hub_accelerator_detailed`/domain-ownership inference machinery, extended with a
binding-derived hint (`metadata.domain` on the binding being scaffolded, since there is no
`model/ontologies/*.ttl` stem to hint from yet) — this is scoped as part of the
`scaffold-binding` tooling itself (Phase 2 of this initiative), not part of this compiler
decision.

**5. `next`'s readiness ladder (DD-137) needs no logic change — only its routing guidance
does.** Since the stub is required infrastructure (point 3), "ontology missing" continues to
correctly gate readiness exactly as DD-137 already specifies; a domain is never "done" without
a `model/ontologies/<domain>.ttl` file, machine-managed or not. What changes is only which
skill the `design-domain` action (`core/next_actions.py`'s `ACTION_SKILLS` routing table)
points to: for a domain with no deviation intent, the correct next action is running
`scaffold-binding` (which creates the stub as a side effect of scaffolding the first binding),
not a purely-manual ontology-authoring skill. This is a routing-table update, not a change to
`propose_next_actions`'s decision logic.

**6. `coverage-report` attribution.** Because the stub still exists and still declares the
accelerator `owl:imports` dependency, a binding targeting an accelerator class continues to
attribute to the correct domain/accelerator pack through the same file-presence-based
attribution `coverage-report` already uses — no bespoke new attribution logic is expected to
be necessary. This is called out as something to confirm with a concrete test
(`tests/test_coverage_*`) during implementation rather than asserted definitively here, since
`coverage-report`'s exact attribution mechanics were not exhaustively traced before this
decision was recorded.

### Rationale

The fix is smaller and lower-risk than the original CR framing suggested, because DD-103's
semantic index was already built to cover the full resolved closure — this decision widens
one lookup (`_ontology_symbols`'s class/property registration) to use more of an index the
compiler already loads and pays to build, rather than adding a new resolver, a new
hub-level accelerator lookup, or a new dependency on `reference_modules.py`/DD-125 at compile
time. Reusing `_qnames`/`_declared_prefix_aliases` (for token matching) and
`_class_index_properties` (already fully generic, requiring zero modification) means the
accelerator-fallback path is exercised by exactly the same code local resolution already
exercises — there is no second, parallel resolution implementation to keep in sync. Scoping
the lookup to only the classes a binding actually references (rather than pre-computing
qnames for every class in a 50,000-line accelerator index) preserves the existing
diagnostics' usefulness (a "usable class tokens" list that stays a few dozen entries, not
tens of thousands) and avoids new cross-accelerator name collisions. Keeping the
local-subclass path completely unchanged means this decision has zero migration cost for
existing hubs — every binding that already declares a local class keeps working identically.
Making the domain stub machine-managed (rather than optional or hand-authored) is the only
way to reconcile "no local classes for the non-deviating case" with `resolve_scope`'s
existing hard requirement that the file exist, without weakening that requirement — which
would be a larger, riskier change to a load-bearing safety check with no compensating
benefit. Not changing `next`'s decision logic (only its routing) keeps DD-137's stateless,
no-persisted-state contract completely intact.

### Consequences

- `kernel.py`: `_ontology_symbols` gains a second, narrower lookup pass — for each
  still-unresolved binding target token, check it against the rest of the already-loaded
  `index` using the existing qname-computation helpers, and register a match via the
  existing, unmodified `_class_index_properties`. `adapter.py`'s `ResolutionContext` gains no
  new public shape — it continues to receive a `classes`/`properties` tuple, just populated
  from two passes over the same index instead of one.
- `reference_modules.py`/DD-125 are **not** touched by this decision — see point 4;
  `scaffold-binding` (Phase 2) is where a binding-derived domain hint for accelerator-pack
  selection belongs, when it writes a brand-new stub's `owl:imports`.
- `next_actions.py`: `ACTION_SKILLS` routing entry for `design-domain` updated; no change to
  `propose_next_actions`'s ladder logic or `HubInputSnapshot`/`DomainSnapshot` shape beyond
  what this initiative's `metadata.tier` work already added.
- New tests required: a binding whose `target.class` is an accelerator IRI with no matching
  local `rdfs:subClassOf` anywhere in the domain resolves both the class and its full
  inherited property set and compiles; the same binding still fails with
  `binding.unknown-class` when the class exists in neither the local ontology nor any
  activated accelerator module; a domain with only a machine-managed stub (zero local
  classes) compiles successfully end-to-end; `coverage-report` attributes an
  accelerator-direct binding to the correct domain (confirming point 6 empirically).
- Superseded working assumption: the earlier design-notes premise that a domain could exist
  with *no* `model/ontologies/<domain>.ttl` file at all is corrected — `resolve_scope`'s
  existing requirement is not relaxed by this decision.

---

## DD-145: Local-Extension Ontology and SHACL Derivation (Narrowed CR-2)

**Status:** Accepted
**Date:** 2026-08-09
**Affects:** `core/suggest_shapes.py`, `core/compiler/result.py` (`ExplainEntity`), a new
`derive-ontology --from-binding` CLI surface
**Implementation:** deferred pending accelerator-pack Silver/SHACL defaults content; toolkit
mechanism scoped here with a documented fallback

### Context

CR-2 (`docs/temp/cr-fast-path-to-silver.md`) originally proposed deriving a domain's
ontology TTL and SHACL shapes wholesale from its `EntityBinding` YAML, to stop hand-authoring
three mutually-redundant artifacts per entity. Read literally, this contradicts DD-133's
explicit statement that an `EntityBinding` is "validated ... then converted directly into
frozen dataclasses and the existing graph-free mapping AST — never serialized to intermediate
RDF." Once DD-144 makes accelerator-direct binding the default for both tiers, the scope of
what CR-2 actually needs to solve shrinks: in the non-deviating case there is no local class
or shape to keep in sync with the binding at all (DD-144's machine-managed stub declares no
local terms), so there is nothing to derive. CR-2 only still matters for the **local-extension
case** — a binding whose target class genuinely deviates from the accelerator and therefore
does declare a local subclass with one or more extension properties, which do need *some*
ontology declaration and, if SHACL validation is desired, a shape.

### Decision

Narrow CR-2 to local-extension properties only, and adopt the CR's "option 2" shape uniformly
(never the "derive in place as a reviewable diff" alternative), so DD-133's authored-input
invariant never has an exception to remember: a `derive-ontology --from-binding <path>`
command reads an `EntityBinding`'s local-extension `fields:` (properties whose class is a
locally-declared subclass, per DD-144) and **scaffolds** — never silently writes into the
authored tree — a small TTL fragment (one `owl:DatatypeProperty` per extension field, domain/
range inferred from the source contract and the binding's resolved expression type) for a
human to review and merge into the domain's ontology file by hand. The same command, when
the accelerator pack ships a reviewed SHACL shape for the parent accelerator class (content
that is `docs/temp/logistics-accelerator-dbt-silver-design-plan.md` §7's "pending"
`silver-defaults/*.ttl`, not yet available for logistics), scaffolds a small SHACL fragment
**extending** that shape with constraints for the extension properties only — never a full
per-hub shape derived from scratch. When no accelerator shape default exists, the command
scaffolds a shape for the local-extension properties alone, with the same "advisory, human
reviews" framing `suggest-shapes` (DD-076) already uses, and does not attempt to describe the
accelerator-owned portion of the class at all.

`suggest-shapes`'s existing, currently-unused `mappings:` extension point
(`core/suggest_shapes.py`, "Extension point for DD-076+: mappings may later retarget shapes to
domain properties") is the intended seam: retargeted from raw bronze-profiling input to the
compiler's already-resolved `ExplainEntity.fields`/`target_class`/`grain`
(`compiler/result.py`), scoped to local-extension fields only.

### Rationale

Narrowing to the local-extension case is what DD-144 makes possible: it was the introduction
of accelerator-direct binding that removed the non-deviating case from CR-2's scope entirely,
not a separate decision. Choosing the explicit-scaffold shape uniformly (rather than CR-2's
original per-tier split) means DD-133's "authored TTL is an input, never an output" rule holds
without a carve-out to track and re-justify later. Reusing `suggest-shapes`'s existing,
already-designed-for-this extension point avoids building a second SHACL-generation code path
next to the one that already exists for the bronze-profiling case.

### Consequences

- No change to DD-133's authored-input contract; no intermediate RDF is ever produced from a
  binding except as an explicitly-requested, human-reviewed scaffold output, matching how
  `suggest-shapes` and `scaffold-mapping`'s legacy scaffolds already behave.
- This decision records the mechanism; **implementation is deferred**. The toolkit-side
  scaffold command can be built without waiting on the accelerator pack, with a documented
  fallback (no reused shape, extension-only shape) when no accelerator default exists — but
  the full value of "extend, don't derive" is gated on that content shipping.
- Full CR-2 (deriving a shape for the accelerator-owned portion of a class) is explicitly
  **not** adopted — DD-144 makes it unnecessary, and attempting it would recreate the
  cross-file consistency burden this whole initiative exists to remove.

---
```

## DD-146: Pattern library as an advisory, authoring-time consumer

**Status:** Accepted
**Date:** 2026-08-10
**Context:** #262 §3 (reference-models lueprints/patterns/ gap)

### Context

kairos-ontology-referencemodels ships a sector-neutral **pattern library** under
`blueprints/patterns/<id>/pattern.yaml` — naming conventions and anti-patterns for
recurring modelling shapes (temporal quartets, qualified role assignments, governed code
lists, deferred relationships). Its README states there is *no toolkit consumer yet*.
Issue #262 §3 proposed surfacing patterns through the `discovery-conformance` flow, with
an Option B that would bundle `patterns:` into archetypes behind a `schema_version: 2`
bump.

### Decision

Patterns are consumed as **advisory, authoring-time craft owned by
`kairos-design-domain`**, not by `discovery-conformance`:

- A lenient, offline, best-effort `core/pattern_loader.py` reads the library
  (`yaml.safe_load` only, never over the network), tolerating the `v0.1`
  markdown-first shape (unknown keys preserved) and **skipping a malformed pattern with a
  warning** rather than raising — advisory surfacing must never break the design loop.
- A top-level `kairos-ontology list-patterns` command emits the library (or one pattern)
  as clean machine output for the skill; it is deliberately **not** a
  `discovery-conformance` subcommand, because patterns bite at property-naming time, not
  during the SME concept interview.
- The `kairos-design-domain` skill consults it when reviewing naming: prefer a matching
  pattern's **normative** `naming_conventions`, reject its `anti_patterns` (citing the
  `id` + `rejection_reason`), and treat structural guidance as advisory per each
  pattern's `normativity` block.

### Rejected alternatives

- **Surface patterns via `discovery-conformance`** — wrong phase; discovery drives concept
  coverage, not property naming. Rejected.
- **Option B: `schema_version: 2` + archetype-bundled `patterns:`** — freezes a per-class
  decision at archetype-authoring time behind a MAJOR breaking bump, premature while the
  library is `v0.1`. Rejected.

### Consequences

- Additive and backward-compatible: a checkout with no `blueprints/patterns/` library is a
  silent no-op.
- The reference-models README's trigger condition ("the toolkit gains a consumer for
  patterns") is now met, so a **follow-up in the reference-models repo** should add
  `blueprints/patterns/_schema/pattern.schema.json` and a structural validation. This is
  out of scope for the toolkit change; the lenient loader does not require it.
- **Finding:** the real `temporal-quartet/pattern.yaml` currently has invalid YAML (a list
  and a mapping key as siblings under `naming_conventions`); the lenient loader skips it
  with a warning, which is exactly why the consumer is lenient — but that most-important
  pattern is unusable until the reference-models repo fixes the file. Tracked on #262.

---

## DD-147: Power BI/TMDL analysis is demand evidence under integration/discovery/bi

**Status:** Accepted
**Date:** 2026-08-10

### Context

`import-tmdl` parses Power BI PBIP/TMDL semantic models into an Engineering Pack and a
Concept Mapping template. This is **downstream demand evidence** — how the business already
reports on its data — and `design-landscape` consumes it strictly as an advisory `bi_weight`
signal that may only re-rank the `demanded-but-unbound` backlog, never as a canonical input
source or a class-classification input (DD's C1 guard).

Despite that, the command's default output was `integration/sources/powerbi/`, physically
placing BI evidence under `integration/sources/` where authored source vocabularies live.
That location invited treating a Power BI model as a source system and binding it as a source
relation in an `EntityBinding`, contradicting the intended demand-evidence semantics.

### Decision

Relocate Power BI/TMDL analysis to the demand/discovery tree:

- `import-tmdl --output` defaults to **`integration/discovery/bi/`** (a sibling of the DD-090
  `core-concepts-conformance.yaml` demand artifact), never `integration/sources/`. That path is
  resolved against the **hub root**, not the current working directory (issue #296): the original
  cwd-relative default created a stray top-level `integration/` tree outside `ontology-hub/`
  whenever the command was run from the repository root — which is the natural place to run it,
  since raw BI exports are kept there. An explicit `--output` is still honoured verbatim.
- Only the two derived artifacts are written into the hub. A PBIP archive is expanded in a
  temporary directory, never into the output folder (issue #296): the archive carries the whole
  report — report definitions, local settings, M expressions with server names — and that folder's
  own README forbids committing connection strings or proprietary report content. In-place
  extraction also accumulated stale members across re-runs, since `extractall` never prunes.
- `design-landscape` reads concept-mapping BI weight from `integration/discovery/bi/**` first,
  and still reads the legacy `integration/sources/**` location for back-compat.
- `draft-model-report --tmdl-dir` auto-detects `integration/discovery/bi/`, falling back to the
  legacy `integration/sources/powerbi/` when present.
- `init`/`new-repo` scaffold the folder with a README stating BI/TMDL is demand evidence, not a
  source.
- The `kairos-design-source` import skill offers a Power BI/TMDL import step **after** sources,
  explicitly as demand evidence landing under `integration/discovery/bi/` — never a source.

### Consequences

- Additive and backward-compatible: existing hubs with mappings under
  `integration/sources/powerbi/` continue to work via the legacy read/fallback paths.
- The physical layout now matches the semantics: a Power BI model can no longer be mistaken for
  an authored source relation.

---

## DD-148: Discovery-Before-Design and Fleet-Mode Open-Question Hard Gates (Amends DD-059)

**Status:** Accepted
**Date:** 2026-08-10
**Affects:** `kairos-ontology compile`/`validate`/`discovery-conformance validate`,
`kairos-ontology next`, `kairos-design-domain` skill
**Implementation:** `src/kairos_ontology/core/conformance_artifact.py`,
`src/kairos_ontology/cli/compile.py`, `src/kairos_ontology/cli/validation.py`,
`src/kairos_ontology/cli/sources.py`, `src/kairos_ontology/core/hub_inspection.py`,
`src/kairos_ontology/core/next_actions.py`, `.github/skills/kairos-design-domain/SKILL.md`
(+ scaffold copy)

### Context

DD-059 made discovery-completeness a recommendation, not a hard block, because source data
(Gate 6) remained the authoritative evidence — discovery only improves naming alignment. In
practice this let real design proceed on inferred business terms (order lifecycle states, party
roles, "on-time" definitions) without ever running discovery, surfaced during a client-hub
review of a `TransportOrder` domain slice.

Separately, `kairos-design-discovery`'s own instructions already claimed discovery entries could
carry `confidence`, `rationale`, `references`, and `needs_confirmation`, and that fleet mode
(DD-088, unattended AI pre-fill) must record AI-approved choices distinctly from user-confirmed
ones — but `conformance_artifact.py`, the code that actually builds/validates the artifact,
implemented none of these fields. There was no way to *detect*, let alone block on, "this
discovery artifact has unresolved fleet-mode items."

A prior attempt to relabel `ActionStatus.BLOCKING` inside `kairos-ontology next` was found to
have zero mechanical effect: that status is set only for compile-diagnostics, is never read or
branched on anywhere, and `next` always exits 0 by design (DD-137) — it is advisory, recomputed,
and never authority.

### Decision

1. **Machine-checkable open questions.** `conformance_artifact.py` gains a required
   artifact-level `mode: "interactive" | "fleet"` field, and per-concept `confidence`,
   `rationale`, `references`, `needs_confirmation`, and `decided_by: "user" | "ai"` fields.
   `open_questions(artifact)` returns the AI-decided concepts (explicit `decided_by: "ai"`, or
   absent under `mode: fleet`) that are either `needs_confirmation: true` or have no recorded
   `confidence` — interactive-mode artifacts never produce open questions.
2. **Real enforcement in `compile`/`validate`.** A new `check_discovery_gate(hub_root)` helper
   hard-fails (non-zero exit, no bypass flag) when there is **neither** a `businessdiscovery/`
   narrative (DD-048) **nor** a conformance artifact (DD-090) — the two are independent
   discovery outputs and either satisfies this baseline; a hub with only a narrative and no
   archetype-conformance run is not blocked. When a conformance artifact does exist, the gate
   additionally fails when `open_questions()` is non-empty, regardless of the narrative. It is
   called from `kairos-ontology compile` and `kairos-ontology validate` — the two commands that
   already exit non-zero on failure (Gate 5's syntax check, compile-diagnostics) — deliberately
   without the outcome-codes catalog dependency `validate_artifact()` needs, so the gate never
   requires resolving an accelerator. `discovery-conformance validate` gets the unresolved-items
   check plus a `--allow-unresolved` escape hatch, since that command is also used
   standalone/diagnostically.
3. **`kairos-ontology next` mirrors this as an advisory signal, not the enforcement.** Missing
   discovery and unresolved fleet-mode items are labeled `ActionStatus.BLOCKING` (a new
   `resolve-discovery-open-questions` action, priority 25) purely for visibility — the label has
   no exit-code effect in `next` itself, consistent with the DD-137 advisory contract.
4. **`kairos-design-domain` Gate 1** changes from "offer kairos-design-discovery" to a STOP
   condition: no confirmed discovery artifact, or an unresolved fleet-mode artifact, must invoke
   `kairos-design-discovery` before design proceeds.
5. `ARTIFACT_SCHEMA_VERSION` bumps 1→2 as an accepted breaking change — no hub was in production
   when this landed, so existing fixtures were updated in place rather than dual-supported.

### Consequences

- DD-059's "recommendation, not a hard block" framing is superseded: discovery completeness is
  now enforced the same way Gate 5/compile-diagnostics already are, via `compile`/`validate`
  exit codes, not via skill-prompt discipline alone.
- Every hub fixture used by CLI-level compile/validate tests needed a discovery artifact added;
  fixtures exercising `build_compile_plan`/`compile_domain` directly (library calls, not the CLI
  wrapper) are unaffected, since the gate lives in the CLI layer only.
- Pairs with DD-149 (human-confirmed archetype selection), which closes a related gap in the same
  skill.

---

## DD-149: Human-Confirmed Archetype Selection (Amends DD-088/DD-090)

**Status:** Accepted
**Date:** 2026-08-10
**Affects:** `kairos-design-discovery` skill, `conformance_artifact.py`
**Implementation:** `.github/skills/kairos-design-discovery/SKILL.md` (+ scaffold copy),
`src/kairos_ontology/core/conformance_artifact.py`

### Context

Archetype selection (`kairos-design-discovery` Phase 2.5, `discovery-conformance load
--archetype <id>`) had no confirmation step at all: the skill never documented how `<id>` should
be chosen or that a human must confirm it, and no code path enforced this — `archetype_loader.py`
resolves strictly by the id it's given, with no automatic matching/scoring logic to guard. This
was raised as the likely root cause of "the archetype is not always selected properly," and is a
consequential choice: it scopes the entire downstream reference-model import closure, so getting
it wrong is effectively irreversible once modeling begins.

### Decision

Archetype selection is never fleet-eligible. A new Gate A ("Archetype confirmation") in
`kairos-design-discovery` requires listing candidate archetypes, presenting them to the human, and
stopping for an explicit human reply naming the archetype id — recorded in the interview log —
before proceeding to `discovery-conformance load`. This choice is added to DD-088's list of
decisions fleet mode may never make on its own, alongside ambiguity, low confidence,
policy-sensitive choices, destructive/irreversible actions, and PII risk.

`build_artifact()` requires an explicit `archetype_confirmed_by="human"` value, stamped as
`archetype.confirmed_by` in the artifact; omission and every other value fail before an artifact
is built. The supported CLI mirrors that requirement in the judgments file. Its generated
template contains a blocking `<CONFIRM_HUMAN_ARCHETYPE:...>` sentinel, and
`discovery-conformance build` exits before writing until the field is explicitly changed to
`human`.

### Consequences

- Archetype selection now has the same paper trail as fleet-mode concept judgments (DD-148):
  a machine-checkable field, not just skill-prompt discipline.
- Enforcement is code-level for the evidence available to the toolkit: neither the builder nor
  CLI infers confirmation, and the scaffold remains mechanically incomplete until the explicit
  marker is authored. The toolkit cannot independently verify who typed a value in a YAML file;
  the interview log remains the auditable record of the human reply.
- Pairs with DD-148 (discovery-before-design hard gates), closing both gaps surfaced by the same
  client-hub review.

---

## DD-150: Reference-models owns the tier enum; the toolkit derives ontology tier (Amends DD-146)

**Status:** Accepted
**Date:** 2026-08-10
**Context:** #276 Q1–Q4/Q5/Q3/Q6, merged with the remaining half of #262

### Context

#275 added paired contract tests after a reference-models `pattern.yaml` shipped unparseable and
survived two minor versions. #276 then raised six design questions those tests surfaced but did not
answer. Read against the code and a v1.14.0 checkout, four were not open questions:

- `validate_artifact` rejected any tier outside the hardcoded `VALID_TIERS`, so publishing the
  proposed `not_applicable` tier would invalidate every artifact carrying it. Worse,
  `compute_scorecard` seeded buckets from `VALID_TIERS` and skipped anything else, so such a concept
  was counted in `total` but dropped from every bucket — a scorecard that under-reports silently.
- `freight-forwarder` already declares the blueprint module `required`, and `blueprints/ontology/`
  is at 0.1.0 on its own cadence, yet `_derived_ontology_version` only scanned
  `derived-ontologies/`, so a `Blueprint` pin resolved to `None` and was skipped silently.
- The pattern library's `mode_bindings` / `grain_collisions` already reached the CLI JSON via
  `to_payload()`'s `extra` flatten; only the `kairos-design-domain` prose was narrow.

### Decision

**Tier enum (Q4/Q5).** Reference-models owns `$defs/tier`; `load_valid_tiers()` resolves it from the
checkout at runtime with `VALID_TIERS` as an offline fallback, mirroring `load_outcome_codes`. It
never raises, because the schema is a soft-skip everywhere else in that module.

**Scorecard counting is self-describing, not enum-driven.** `compute_scorecard` seeds `by_tier` from
the supplied tiers **union the tiers actually present**, and never skips a concept — so `total`
always equals the sum of `by_tier`. `validate_artifact` compares scorecards with **empty buckets
normalised away**, which removes an ambient-state dependency that naive injection would have
introduced: an artifact built against a 4-tier checkout and validated against the 3-tier fallback
differs only in an empty bucket, and previously failed with a misleading "'scorecard' contradicts
'core_concepts'" the user could not act on. Net: the tier enum governs *acceptance* only.

A coverage-denominator semantics mapping was **considered and rejected** — no coverage percentage or
denominator exists anywhere in the toolkit, so it would have been designing for absent logic.

**Ontology tier (Q3).** Derived from the path the catalog resolves a module to
(`blueprints/ontology/` → `blueprint`, `derived-ontologies/` → `derived`,
`authoritative-ontologies/` → `authoritative`), reusing the resolution `build_concept_graph` already
performs. Surfaced as **`ontology_tier`** in `discovery-conformance load` — never as `tier`, which in
that same dict already means the *conformance* obligation level. This is what lets a consumer tell
"subclassing a blueprint class is expected" from "subclassing a derived, mode-bound class outside its
mode is the error to flag".

**Pattern surfacing (Q1/Q2).** `grain_collisions` is promoted to a first-class `Pattern` field (all
five published patterns ship it). `mode_bindings`, `participants` and `naming_rule` stay in `extra`:
they already reach consumers through the payload flatten, and promoting a key only one pattern
declares would make the other four emit an empty placeholder in the exact payload an LLM reads. The
substantive change is `kairos-design-domain` prose, now covering four surfaces — normative naming,
**structural** anti-patterns, per-mode `mode_bindings` (`modelled` → bind, `extension-point` → do not
invent a class, `pattern-only` → pattern alone), and `grain_collisions` as do-not-subclass boundaries.

### Rejected alternatives

- **Keep `VALID_TIERS` authoritative and hand-add `not_applicable`** — keeps the duplication #275
  could only detect, and needs a toolkit release per upstream tier. Rejected.
- **Promote `mode_bindings`/`participants` to fields** — churn with negative value (see above).
- **A `module_profiles`/legacy-profile warning in `reference_modules.py` (Q6)** — that module has no
  warning-level diagnostic precedent (every `ModuleDiagnostic` in it is an `error`), so this meant
  either breaking every hub importing the blueprint module through a bare `uri:` or inventing an
  untested severity path — for a fix reference-models owns. Recorded as an ask instead.

### Consequences

- Additive and backward-compatible; all `valid_tiers` parameters default to the existing constant.
- `test_valid_tiers_matches_the_published_schema` (#275) is **superseded**: strict equality is now a
  false alarm, since an added tier is handled at runtime. Replaced by two sharper tests — the
  published enum must *resolve*, and the fallback must never contain a tier the published enum has
  **dropped** (offline, we would keep accepting a retired tier).
- A companion contract test now pins `design_landscape`'s hardcoded `CONFIRMED_DISCOVERY_OUTCOMES` /
  `NON_EVIDENCE_DISCOVERY_OUTCOMES` against the published `outcome-codes.yaml`. `load_outcome_codes`
  never hardcoded the *list*, but those *semantics* were literals with no test — a published rename
  would have left them matching nothing, with green CI.
- The unpinned-blueprint-module warning is **payload-only, never stderr**: until reference-models
  publishes a `Blueprint` pin it fires on every load of an affected archetype and a hub designer
  cannot act on it.
- **`classify_ontology_tier` is a heuristic, not a contracted signal.** Reference-models' directory
  layout is not in the contract table, so a reorganisation would silently degrade every module to
  `unknown` and disable the blueprint warning. `tests/test_refmodels_contract.py` pins the three
  prefixes against a real checkout so this fails loudly, and an explicit tier declaration is the
  standing ask.
- Reference-models asks: publish a `Blueprint` key in `ontology_versions`; declare ontology tier
  explicitly; add `blueprints/patterns/_schema/pattern.schema.json`; relocate
  `attestation.schema.json` to a pack-neutral path; state the intended obligation semantics when
  adding `not_applicable`. DD-146's `temporal-quartet` finding is **resolved** — all five published
  patterns parse in v1.14.0.

## DD-151: Structured logging foundation + opt-in OpenTelemetry bridge

**Status:** Accepted
**Date:** 2026-08-14
**Context:** observability change request (`docs/temp/changerequest.md`)

### Context

The toolkit used `logging.getLogger(__name__)` in ~40 modules but had **no central logging
configuration** and **no root-level `--verbose/--debug/--log-file/--log-format` options**, so
those records effectively went nowhere (Python `lastResort` -> stderr at WARNING only). The change
request motivated this with "dbt execution code fails silently", but after code analysis that
framing was partly misaligned:

1. The toolkit core **does not run real `dbt run`/`build`**. `core/dbt_validation.py` only runs
   *offline* `dbt deps/parse/compile` with credential-free dummy profiles. Real-run observability
   lives in the downstream **dataplatform** repo the toolkit scaffolds - explicitly **out of scope**
   here.
2. A machine-readable diagnostic contract already exists (`CompileDiagnostic` with stable `code`,
   `severity`, `rule_id`, drift-guarded by `docs/design/diagnostic-codes.md` +
   `tests/test_diagnostic_catalog.py`, surfaced via `compile --format json` per DD-133). The CR's
   proposed "diagnostic envelope for skills" would duplicate it.
3. Offline dbt validation already classifies failures (`DbtValidationError(phase, ...)`,
   `_ENVIRONMENT_BLOCK_PATTERNS`, `compile_status="environment_blocked"`).

The real, high-value gap was item (0): no central logging config + no CLI verbosity flags.

### Decision

**Scope: toolkit core + CLI only** (offline validation, compile, projections). Real dbt-run
observability in the dataplatform scaffold is tracked separately.

**Phase 1 - Structured logging foundation (the real gap).** A new subpackage
`core/observability/` provides:
- `logging_config.configure_logging(...)`: idempotent; installs console (+ optional file)
  handlers **only** at the CLI boundary on the `kairos_ontology` logger. Libraries keep
  `getLogger(__name__)` and never configure handlers. `logger.propagate = False` so third-party
  loggers (rdflib, jinja2) stay quiet by default. Handlers are stamped with a `_kairos_observability`
  marker so reconfiguration can find/remove them without touching foreign handlers (e.g.
  pytest's).
- `formatters.JsonFormatter` (NDJSON, stable field set: timestamp, level, logger, message,
  event, `kairos.operation.id`, extras, exception) and `formatters.TextFormatter` (human-readable
  single line with `[event=...]` and `[kairos.operation.id=...]` tags).
- `_redaction.RedactionFilter`: scrubs sensitive keys (password/passwd/secret/token/
  client_secret/api_key/credential/authorization) and secret substrings (tokens, bearer, ODBC
  `password=` fragments, UUID-like secrets) **before** emit. Never drops records.
- `context.OperationContext` + `contextvars.ContextVar`: per-invocation operation id (uuid4) for
  correlating all records in one command. `OPERATION_ID_ATTR = "kairos.operation.id"`.

Root Click group options in `cli/main.py`: `--verbose/-v`, `--debug`, `--log-file`,
`--log-format {text,json}`; `cli` callback calls `configure_logging(...)` once and binds the
operation context; `result_callback` resets it.

**Phase 2 - Instrument offline dbt boundaries.** `core/dbt_validation.py` (deps/parse/compile
phases) emits a small, stable, versioned event catalogue via `observability.events`:
`kairos.dbt.phase.started` / `.completed` / `.failed` / `kairos.dbt.environment_blocked`, with
attributes `kairos.operation.id`, `kairos.dbt.phase`, `duration_ms`, `kairos.retryable`. Genuine
artifact failures are **not** retryable (retrying produces identical output); only
timeout/environment-blocked outcomes are. Captured stdout/stderr is redacted before logging.
`subprocess.run` call sites in `cli/shared.py`, `cli/setup.py`, `cli/operations.py` are similarly
instrumented. **Logging never changes exit codes.**

**Phase 3 - Leverage (do not duplicate) the diagnostic contract.** `compile --format json` now
carries `operation_id` for log<->result correlation. Where offline dbt-validation failures should
be skill-consumable, they are surfaced through the existing `CompileDiagnostic` / JSON path -
**no second machine-readable envelope.**

**Phase 4 - Optional OpenTelemetry bridge (opt-in, off by default).** An `[otel]` extra in
`pyproject.toml` (opentelemetry-api/SDK + OTLP exporter), mirrored in `[dependency-groups]`. The
bridge in `observability/otel.py` activates **only** when the extra is importable **and**
`OTEL_EXPORTER_OTLP_ENDPOINT` is set. Absence of the package is a guarded-import + no-op. Export
failure is caught and never affects the CLI exit code. The handler is flushed in the CLI
`result_callback`. Uses OpenTelemetry semantic-convention attributes where standardized and
namespaces toolkit attributes as `kairos.*`.

### Rejected alternatives

- **Make OTel a hard runtime dependency.** Rejected: the toolkit is a minimal-dependency Apache-2.0
  short-lived CLI; OTel is opt-in.
- **Build a parallel "diagnostic envelope for skills".** Rejected - duplicates
  `CompileDiagnostic` / `--format json` (DD-133). Extend, don't reinvent.
- **Instrument real dbt-run observability in toolkit core.** Rejected - real dbt execution lives
  in the downstream dataplatform repo; out of scope.

### Consequences

- New subpackage `core/observability/`; new tests `tests/test_observability.py` (config idempotency,
  JSON/text formatter shape, redaction, operation-id propagation, third-party logger isolation) and
  `tests/test_observability_events.py` (dbt-validation event emission happy/failure each phase,
  retryable-classification guard, environment-blocked event, phase/operation attributes).
- `compile --format json` payload gains `operation_id`; documented in
  `docs/design/diagnostic-codes.md` ("JSON output envelope" section). `CONSUMING_COMPILE_PLAN.md`
  unchanged (consumer-oriented, not payload-oriented).
- Determinism preserved: logging/telemetry never alters compiler output bytes or artifact paths;
  `tests/scenarios/test_scenario_v5.py` and determinism tests still pass.
- SPDX/Apache-2.0 headers on every new .py file. 100-char ruff lines.
- Future: real-run dbt observability in the dataplatform scaffold is a separate change.

---

## DD-152: Reference Models Resolve From a Shared, Versioned Machine-Level Cache (Supersedes DD-036's Location)

**Status:** Superseded by DD-158 (2026-08-15). Never implemented.
**Date:** 2026-08-14
**Affects:** `cli/shared.py` (`_fetch_reference_models`, refmodels discovery), `core/catalog_utils.py`
(`CatalogResolver`), `core/archetype_loader.py` (`resolve_refmodels_root`, version drift),
`core/ontology_loader.py` (`stable_root`), hub scaffolding (`claude-settings.json`, `.gitignore`),
hub CI workflows, DD-036, DD-047
**Implementation:** None — proposal for review. Nothing is implemented until this entry is Accepted.

### Context

A hub vendors **17.5 MB / 560 files** of reference models into `ontology-reference-models/`, **409 of
them raw ontology serialisations** (297 `.rdf` + 112 `.ttl`), all committed to git, and `init` fetches
them by default (#290). DD-036 chose this deliberately over submodules and accepted "hub repo size
slightly increases" as the cost. At one client hub the cost is no longer slight, and it is paid three
times over: permanently in every hub's git history, once per client as a pinned duplicate of bytes
nobody edits, and once per agent workspace — raw ontology sitting inside the tree the agent reads.

That third cost is why the DD-103 agent boundary has to exist as a **deny-list** at all. The
concurrent DD-103 amendment extends those globs to `.rdf`/`.owl` and re-anchors them to the project
root, which closes the holes that were open — but a deny-list is a guardrail, not a sandbox: `Bash`,
`cat` and `git show` still reach the files, and the rules only bind agents that honour that settings
file. The boundary is a policy over files that are present. Absence is stronger than policy.

Nothing about the vendored *content* is wrong. What is wrong is the *location*.

### Decision

**Reference models are fetched into a shared, versioned, per-user location outside every repository**
— `%LOCALAPPDATA%\kairos\rm\<version>\` on Windows, the XDG equivalent
(`${XDG_CACHE_HOME:-~/.cache}/kairos/rm/<version>/`) elsewhere. One copy per version per machine,
shared by every hub on it. The hub does not gitignore the models; it simply does not contain them.

**The short prefix is a requirement, not an aesthetic.** The longest path inside the tree is **144
characters** relative to the inner reference-models root (170 including the
`ontology-reference-models/` prefix; the upstream FIBO `fibo/BE/GovernmentEntities/…` paths are the
binding constraint). Against `MAX_PATH` that leaves 115 characters of prefix budget. Vendored in a
realistic user-profile hub the total is **235** — it fits, which is why nobody has hit this.
`.venv\Lib\site-packages\kairos_ontology_referencemodels\ontology-reference-models\…` totals **291**,
exceeding `MAX_PATH` by **31**; a global Python or `uv tool` install totals 286/287. A
`%LOCALAPPDATA%\kairos\rm\<version>\` prefix sits well under. **These figures are arithmetic, not
observed failures** — the machine they were measured on has `LongPathsEnabled=1` and therefore cannot
reproduce the fault. Any location this decision picks must carry the short-prefix constraint
explicitly, because the constraint is invisible to the developers most likely to change it.

**Fetching reuses `_fetch_reference_models` (`cli/shared.py:1724-1847`) as-is.** #290's work is
preserved, not replaced: the sparse shallow clone, the assemble-off-to-the-side-then-swap that keeps a
partial Windows `copytree` from leaving a tree that "looks valid", the clone-root `VERSION` copied in
beside the subtree, and `FETCH_PROVENANCE.json`. Only the destination changes.

**Resolution is an additive catalog overlay.** `CatalogResolver.__init__`
(`core/catalog_utils.py:138-142`) gains `extra_catalogs`, with the default resolved **inside
`__init__`** rather than threaded through `load_ontology`. This is the load-bearing choice in the
whole proposal. There are **8 `CatalogResolver` construction sites** (`cli/shared.py:1392`,
`core/analyse_sources.py:859`, `core/archetype_topology.py:159`, `core/catalog_test.py:41`,
`core/inventory.py:609`, `core/ontology_loader.py:241`, `core/propose_alignment.py:462`,
`core/reference_modules.py:587`) and roughly **14 independent catalog-discovery sites** across
`cli/` and `core/` that locate `catalog-v001.xml` by their own means (five in `cli/inspection.py`
alone). A threaded parameter would reach a small minority, and the majority would degrade **silently**
— a `<nextCatalog>` that does not exist is a `warning`-level diagnostic
(`catalog_utils.py:210-216`), not an error, so the failure mode of a missed site is a hub that quietly
resolves less of its closure. Defaulting in the constructor is the only variant where forgetting a
call site is inert rather than harmful. The `catalog_path is not None` gate at
`core/ontology_loader.py:241` must be fixed in the same change, and note that
`core/design_landscape.py:403-408` *raises* on a missing reference-models directory where everything
else warns.

**The overlay must be additive-only, and this is a correctness constraint, not a style preference.**
`stable_root` derives from `Path(catalog_path).resolve().parent`
(`core/ontology_loader.py:233-239`) and feeds `source_identity` → `_closure_hash` → the DD-047
inventory envelope. If the overlay can displace or reorder the hub catalog's own resolutions, closure
hashes become machine-dependent and every inventory in every hub churns on the next run. Additive-only
means: the hub catalog is still the root, its entries still win, and the overlay only supplies
resolutions the hub catalog does not already provide.

**Precedence extends `resolve_refmodels_root`'s existing chain** (`core/archetype_loader.py:139-184`)
rather than replacing it: explicit `--refmodels-root`, then `KAIROS_REFMODELS_ROOT`, then the existing
sibling/hub-relative folder scan, then the cache. A hub that still has
`ontology-reference-models/` on disk keeps resolving from it and is unaffected. Migration is therefore
opt-in per hub, and DD-036's layout stays valid — it stops being the *default*, it does not become
wrong.

If resolution is ever moved into an installed package, use `importlib.resources.files()`, which
returns a real `pathlib.Path` for both wheel and editable installs, and **assert
`isinstance(root, Path)` so a zip-import regression fails loudly**. Never call `as_file()` on a
directory traversable: its default behaviour recursively replicates the tree into a temp directory
deleted on context exit — a 17.5 MB extraction per invocation. House convention for packaged data is
`__file__`-relative (`core/design_validation.py:284-286`, `core/binding_archetypes.py:40-43`).

### Rejected alternatives

- **Ship reference models as a Python wheel resolved via `importlib.resources`.** Rejected on
  distribution, and the path budget is only the second reason. **There is no package index.** The
  toolkit itself installs from a GitHub-Release-asset direct URL
  (`scaffold/pyproject.toml.template:7`, `.github/workflows/release.yml:105-109`), so a second
  distribution has exactly two options: pin it *inside* the toolkit wheel — which makes every
  reference-models release require a toolkit release, destroying the only reason to separate them — or
  add a second hub-side URL pin, which reproduces the multi-pin divergence #297 was filed to remove
  (five strings for one version, kept in agreement by nothing). "`update-refmodels` becomes
  `pip install -U`" is simply not on offer. Separately, `site-packages` is the *worst* location on path
  length: **291 characters, over `MAX_PATH` by 31**, some 56 characters worse than vendoring.
- **Bake an absolute cache path into the committed `catalog-v001.xml`.** The catalog is a committed,
  shared, user-editable artifact; an absolute machine path makes it non-portable across every developer
  and CI runner, and because `stable_root` is the catalog's parent directory it would also make
  `source_identity` machine-specific. Rejected.
- **Generate the catalog at run time.** Turns a committed contract artifact into a build output.
  `catalog-v001.xml` is referenced by name from ~14 discovery sites and both scaffold templates, is the
  one `.xml` the DD-103 boundary deliberately lets an agent read, and is intentionally hand-editable
  under DD-024's hash-tolerant resolution. Generation would also silently discard whatever a hub had
  added to it. Rejected.
- **Symlink or junction the hub path into the cache.** Windows symlink creation needs Developer Mode
  or elevation; junctions are directory-only and unknown to git, so git either tracks a placeholder or
  walks through and stages the 560 files this decision exists to remove. It also buys nothing on path
  length, since resolution still traverses the hub-side prefix. Rejected.
- **`KAIROS_REFMODELS_ROOT` only.** This is the status quo, not a decision — the variable already
  exists and is already second in `resolve_refmodels_root`'s precedence. As the *primary* mechanism it
  requires every user, shell, IDE, CI job and agent session to set it correctly, manages no fetching or
  versioning, and when unset degrades through a `warning`-level missing-`nextCatalog` path rather than
  failing. It remains essential as the air-gap escape hatch; it is not a distribution strategy.

### Consequences

- **This is the first machine-level state the toolkit has ever owned.** There is currently no
  `Path.home()`, `%APPDATA%` or `platformdirs` use anywhere in `src/` — the toolkit reads and writes
  only inside the repo it was pointed at. That property ends here, and with it come failure modes the
  codebase has no precedent for: profile redirection and roaming profiles in managed corporate estates,
  per-user caches on shared build agents, and read-only or quota-limited profile directories.
- **Cache lifecycle becomes the toolkit's problem.** Nothing deletes a `<version>` directory, so
  versions accumulate at 17.5 MB each. Two hubs can fetch the same version concurrently — the existing
  build-off-to-the-side-then-swap makes a partial tree unlikely but does not make the swap atomic
  against a concurrent reader. Invalidation, a `--prune`/GC story, and a documented "delete this
  directory" recovery step are in scope for the implementation, not optional follow-ups.
- **Every hub's CI must populate the cache.** Today the models arrive with the checkout and nothing
  needs to know they exist. After this, every workflow that runs `compile`, `validate`,
  `check-inventory`, `design-landscape` or `discovery-conformance` needs a fetch step and a cache key.
  This is the largest migration cost and it lands in client repositories, not in this one.
- **Offline and air-gapped use regresses.** A clone is currently self-sufficient. Afterwards, a cold
  machine with no network cannot resolve the closure at all. `KAIROS_REFMODELS_ROOT` plus a documented
  pre-seed procedure (copy a known-good `<version>` directory into place) are therefore mandatory
  deliverables, not documentation nice-to-haves.
- **Historical reproducibility weakens, and this is the direct counterweight to DD-036's rationale.**
  DD-036 valued "files are version-controlled in the hub repo — easy to diff/track changes". Under
  DD-152 a hub no longer records the bytes it was authored against; `FETCH_PROVENANCE.json` moves into
  the cache along with the models. A committed pin in the hub is the replacement, and the DD-047
  envelope stamp below is where it becomes verifiable.
- **The DD-103 boundary becomes structural for migrated hubs but the deny-list cannot be deleted.**
  The `ontology-reference-models/**` globs in `scaffold/claude-settings.json` become vestigial once a
  hub has no such directory, and remain necessary for every hub that still does. They stay, inert, for
  as long as both layouts are supported — a permanent piece of dead-looking configuration that a future
  reader will be tempted to remove. The `model/ontologies/**` and `model/shapes/**` globs are
  untouched: hub-authored ontology never leaves the repo, so the deny-list remains the only mechanism
  there.
- **Path budget improves rather than merely holding.** The tree moves from 235 characters to a prefix
  well inside budget, which also removes the latent `copytree` hazard `_fetch_reference_models`
  currently documents in its own docstring.
- **The acceptance test is byte-equality, not "it works".** Closure hashes and DD-047 inventory
  filenames must be identical before and after the move on the same hub; a `compile --check` and
  `validate` must complete with **zero `missing_import` warnings** and no `ontology-reference-models/`
  in the hub. Silent partial resolution is the failure this proposal must be tested against, because it
  is the failure the warning-level catalog diagnostics make easy.

### Open questions

These are genuinely unresolved. This entry should not move to Accepted until both have answers.

1. **What is `<version>` in the cache path — which string is authoritative?** `VERSION` is **15
   files**, not one: the repository root plus 14 per-module and per-pack files under
   `ontology-reference-models/` (`blueprints/{archetypes,ontology,patterns}`,
   `accelerator-packs/{financial-services,logistics}`, and nine `derived-ontologies/*`). Only the root
   one is a candidate for substitution by a distribution version; the 14 are read by `_module_version`
   (`core/archetype_loader.py:411-456`) to check `compatible_with.ontology_versions` pins and must keep
   shipping verbatim. Meanwhile `repo_tag_range` (`core/archetype_loader.py:459-495`) is a **git tag**
   range whose schema the reference-models repo owns, compared via `packaging` against whatever
   `_refmodels_version` reads — which is why `_fetch_reference_models` copies the clone-root `VERSION`
   in beside the subtree at all. So the git tag (`v1.16.0`), the root `VERSION` (`1.16.0`) and any
   future distribution version are three strings kept in agreement by nothing, and PEP 440
   normalisation diverges from tag form for non-final releases. The straightforward candidate is the
   **resolved git ref actually fetched**, since that is what `_fetch_reference_models` accepts and what
   `FETCH_PROVENANCE.json` records — but naming it here without settling the relationship to
   `repo_tag_range` would just move the ambiguity into a directory name.
2. **Aggregate third-party attribution is not reaching hubs today, and the cache inherits that.**
   FIBO (MIT, © 2020 Enterprise Data Management Council) and IATA ONE Record (MIT, © 2025 IATA-Cargo)
   each carry a `LICENSE` inside their `current/` directory, and those files *are* vendored. An
   aggregate `NOTICE` naming both, with paths, copyrights and the Apache-2.0/MIT compatibility
   statement, exists at the **upstream reference-models repository root** — but
   `_fetch_reference_models` copies only the `ontology-reference-models/` subtree plus the clone-root
   `VERSION`, so neither the root `LICENSE` nor the root `NOTICE` has ever reached a hub. Moving to a
   cache does not create this gap and does not fix it; it carries it to a new location while removing
   the per-file `LICENSE` copies from the repo a downstream consumer would clone. Recorded as an
   observation for review, not as legal advice: whoever owns redistribution terms should decide whether
   the fetch should also copy the root `LICENSE`/`NOTICE`.

---

## DD-153: Command Outcome and Exit-Code Contract

**Status:** Accepted
**Date:** 2026-08-14
**Affects:** every CLI command that reports partial success; `core/command_outcome.py`,
`generate-inventory`, `check-inventory`, `import-flatfile`, `propose-alignment`, `scaffold-system`
**Implementation:** `src/kairos_ontology/core/command_outcome.py`, `cli/inspection.py`
(`generate_inventory_cmd`, `check_inventory_cmd`), `core/inventory.py` (`InventoryCheckReport`)

### Context

Partial-failure policy was decided per command, so two commands facing the same question gave opposite
answers, and there were **76 hand-rolled `raise SystemExit(...)` sites** across `cli/` with no documented
rule about which code to use. Thirteen already used exit 2 for "cannot locate or parse the inputs"; fifteen
comparable sites used 1. Nothing recorded which was correct.

The concrete failure that forced this (#405): `generate-inventory` printed
`✅ Generated 78 inventory file(s)` and exited **0** while three sources failed to build and a fourth was
skipped by a filename collision — the collision even printing `❌` in a command that then reported success.
`written` was the only counter the command kept, so the summary line had no denominator to divide by. In an
unattended run the exit code is the entire signal, and it did not distinguish "78 generated cleanly" from
"78 generated, 4 lost, and the next command will refuse to proceed".

#408 proposed the invariant `exit == 0 ⟺ failed == []`, naming `import-flatfile` as the reference semantics.
Those two are incompatible: `import-flatfile` deliberately exits **0** on partial failure and 1 only on total
failure. A per-command `failure_policy` flag was considered and rejected — it does not resolve the ambiguity,
it relocates it to whoever sets the flag, and it mis-classifies `import-flatfile`, which is legitimately both.

### Decision

Blocking-ness is **intrinsic to the outcome, not a property of the command**:

```
is_blocking =
      no artifact produced for any requested target     # total failure
   or an explicitly-named target failed                 # a directly-named input always fails fast
   or (strict and advisory_findings)                    # the escalation axis
```

This generalises a shape the codebase already used — `blocking = report.is_blocking or (strict and
report.unverifiable)`. `CommandOutcome` carries `succeeded` / `skipped` / `failed` plus per-target
`attempted` / `produced` / `failed` counts, and exposes named `is_blocking` and `has_warnings` properties so
no CLI re-derives the rule inline. A target's `total_failure` requires **both** attempts and failures, so an
empty or wholly-skipped target is never mistaken for a broken one.

Exit codes:

- **0** — every attempted target produced its artifact. `skipped` never affects the code.
- **0 + a `⚠` line** — partial failure where output was still written. The summary always carries the
  denominator (`78 generated, 3 failed, 1 skipped`).
- **1** — the command did not do what was asked: total failure, an explicitly-named target failed, or an
  escalation gate (`--strict`, `--fail-on`) was crossed.
- **2** — the inputs to attempt the work could not be located or parsed.

Two invariants, both testable, and the second was being violated:

- `exit != 0` ⟹ at least one `❌`/`⛔` line was printed.
- a `❌` line was printed ⟹ `exit != 0`.

### Rejected alternatives

- **Per-command `failure_policy ∈ {blocking, advisory}`.** Mis-classifies `import-flatfile`, which is both,
  and turns an unclassified failure into a configuration question.
- **Make every partial failure blocking.** Would render `generate-inventory` unconvergeable: it enumerates the
  vendored reference-models tree, which a hub author cannot repair, so a single unparseable upstream TTL would
  block every hub resolving that version. Ownership is the test — fail for what the author can fix.
- **A machine-readable failure manifest** written by the generator and read by the checker. Solves the
  remediation-text problem but adds an artifact and a staleness question; the `unbuildable` classification
  (DD-047 amendment) achieves the same result inside the existing report.

### Consequences

- `generate-inventory` now exits 1 when it produced nothing from a non-empty source set, or on a DD-054
  collision, and prints a denominator summary. A single unbuildable vendored source stays advisory.
- `import-flatfile`'s documented behaviour is unchanged — partial reads still exit 0 — and it now expresses
  that through the shared rule rather than a local convention.
- Migrating the remaining hand-rolled `SystemExit` sites is deliberately incremental. The behaviour-changing
  subset is the ~15 input-resolution sites that should move from 1 to 2; the rest is a mechanical swap and can
  follow. Until then the contract is documented but not uniformly enforced, which is an honest description of
  the state rather than a claim of completion.
- Any new command reporting more than one outcome should return a `CommandOutcome` rather than hand-rolling an
  exit, so the invariants above hold by construction.

---

## DD-154: Content-addressed inventory writes; unchanged counts as produced

**Status:** Accepted
**Date:** 2026-08-15
**Affects:** `write_inventory` and every caller — `generate-inventory`, `init` step 9b
**Implementation:** `src/kairos_ontology/core/inventory.py` (`write_inventory`),
`cli/inspection.py` (`generate_inventory_cmd`), `cli/setup.py` (init step 9b)

### Context

`init --domain` regenerated all 79 reference-model inventories on every run (#419). The envelope is a pure
function of the source TTLs — except `generated_at`, which `resolve_generated_at()` defaults to
`datetime.now()` — so every registration produced a 78-file diff in which *only* the timestamp line changed.
Two consequences: the prescribed `guard-scope --check-since` gate hard-failed on every registration (the
documented 3-glob footprint could never hold), and reviewers faced churn diffs carrying zero information.
`write_inventory` was the single write path and never looked at the existing file.

### Decision

`write_inventory` is content-addressed: it dumps the new envelope to text (same YAML kwargs as before),
reads the existing file text-mode when present, and compares the two after (a) newline normalisation —
a CRLF checkout on Windows (`core.autocrlf`) must compare equal to the LF text `yaml.dump` produces —
and (b) removing the single column-0 `generated_at:` line from both sides (anchored at line start; nested
keys are always indented, so no data line can be swallowed). Equal → no write, no mtime touch, return
`False`; different, missing, or **any** read/decode failure → write and return `True`. A compare failure
must never cause a skip.

Under DD-153, an unchanged file **counts as produced**: the artifact exists and is current, only the write
was elided. `generate-inventory` keeps unchanged files in the produced set (exit-code semantics untouched),
prints `⏭ {stem}: up to date` per file, and its summary separates the counters:
`{writes} generated, {unchanged} unchanged, {failed} failed, {skipped} skipped` — "generated" counts actual
writes only. `init` step 9b prints its existing "Generated N reference-model inventory file(s)" only when
N > 0 actual writes occurred, and an "already up to date" line otherwise.

Expected one-time full rewrites remain by design: after a toolkit upgrade that bumps `INVENTORY_VERSION`
(or otherwise changes envelope content), and after the #414 `generated_from` provenance migration, the next
run legitimately rewrites every inventory once. Run `generate-inventory` once after upgrading, before the
next registration, so that rewrite lands outside a registration diff.

### Rejected alternatives

- **Hash-only compare (`source_sha256`/`closure_hash`).** A toolkit version bump or a provenance-path change
  (`generated_from`, `INVENTORY_VERSION`) alters the envelope without moving `closure_hash` — the stale
  envelope would be skipped forever. Whole-content-minus-timestamp is the only compare that cannot go stale.
- **Report unchanged files as skipped (a `REASON_UNCHANGED` decline).** Any skip entry flips
  `CommandOutcome.has_warnings`, so every idempotent rerun would print `⚠` — a warning for the healthiest
  possible state. Unchanged is a produced artifact, not a declined one.
- **Timestamp pinning (`KAIROS_GENERATED_AT`/`SOURCE_DATE_EPOCH` in the workflow).** Pushes the fix onto
  every caller's environment, and a pinned timestamp makes `generated_at` a lie rather than making the write
  idempotent.

### Consequences

- Re-running `init --domain` or `generate-inventory` over unchanged sources produces a zero-file diff; the
  documented 3-glob `guard-scope` footprint for domain registration becomes true.
- `generated_at` in a committed inventory now means "when the content last changed", not "when the command
  last ran".
- mtimes of unchanged inventories no longer advance; nothing in the toolkit uses mtime freshness (DD-047
  chose content hashes), so this is observable only to external tooling.

---

## DD-155: Managed Import Completeness is mode-independent and gates registration

**Status:** Accepted
**Date:** 2026-08-15
**Affects:** `run_validation` (all modes), `init --domain` registration, kairos-design-domain skill
**Implementation:** `src/kairos_ontology/core/validator.py` (managed-import preflight),
`cli/validation.py` (`--syntax` help), `cli/setup.py` (`_registration_import_gate`, init `--degraded`),
`.github/skills/kairos-design-domain/SKILL.md` + scaffold copy

### Context

Issue #426: a domain missing a blueprint-required managed `owl:imports` sailed through four green gates and
was registered anyway — silently unactivated. Two structural causes: (1) the validator's Managed Import
Completeness check was gated on `if do_shacl or do_consistency:`, so Gate 5's inner-loop
`validate --syntax` never ran it — an accidental mode split (the check is static rdflib parsing, no
pyshacl), while the sibling `_master.ttl` import-sync check (#393) is deliberately unconditional; and
(2) `init --domain` — the only registration path — performed no import check at all before writing the
catalog entry and syncing `_master.ttl`.

### Decision

Three coordinated parts:

1. **Validator (mode-independent check).** The managed-import preflight runs in every mode, including
   `--syntax`, mirroring the unconditional `_master.ttl` check's precedent. The only remaining gate is
   *resolvability*: when reference models cannot be resolved (no ref-models dir, or no accelerator module
   config — every case where `build_reference_module_context` returns `None`), the parse pre-pass, the
   section header, and the per-file loop are all skipped, so a run on a no-refmodels hub produces
   byte-identical output to before. `--degraded` semantics are unchanged and now also apply to `--syntax`
   runs. **Knowingly accepted:** catalog/module infrastructure errors (e.g. `module_unresolved`) now fail
   `--syntax` on misconfigured refmodels-present hubs.

2. **Registration gate.** `init --domain` refuses to register a **pre-existing** domain TTL whose Managed
   Import Completeness diagnostics contain hard errors, or degradable `missing_managed_import` errors
   without the new `--degraded` flag — exiting 1 *before* the catalog write and the `_master.ttl` sync, so
   a refused run changes neither. Rules that bound the gate:
   - **Pre-existing files only.** A TTL `init` itself just scaffolded (fresh, or overwritten via `--force`)
     is never gated — the starter template has no `owl:imports`, so gating it would refuse init's own
     output on every refmodels-present hub. The fresh path gets an advisory pointing at
     `validate --all --domain <domain>`.
   - **Resolvability short-circuit.** No refmodels dir (or it fails `_looks_like_refmodels_root`), or no
     module config → no gate. An *ambiguous* accelerator warns, skips the gate, and points at
     `validate --all --accelerator <pack>`. Toolkit-owned infrastructure exceptions (context build crash,
     unreadable TTL) warn and proceed — they must never block a user's registration.
   - **Lower bound, not a replacement.** The gate builds a scoped single-domain module context, which is a
     LOWER BOUND versus `validate --all`'s full context: the scoped check can pass where `--all` fails,
     never the reverse of practical concern. The skill's pre-registration `validate --all --domain
     <domain>` run therefore remains necessary, not belt-and-braces.
   - **Fleet mode (DD-088).** The gate blocks identically in fleet mode; an explicit `--degraded` is the
     only bypass, and fleet invocations must record that bypass.
   - Accepted wart: `kairos.yaml`'s `default_domain` is written before the gate, so a refused run can still
     have set it.

3. **Skill.** Gate 5 documents that `validate --syntax` now also reports Managed Import Completeness when
   reference models are present (`missing_managed_import` blocking, degradable only via `--degraded`), and
   step 9 inserts a full-coverage `uv run kairos-ontology validate --all --domain <domain>` run before the
   registration command. Both skill copies stay byte-identical.

### Open sibling dependency

`Cnext-eu/kairos-ontology-referencemodels#64`: the logistics blueprint assigns the `equipment` domain both
`mmt/equipment` and `dcsa/equipment` with no precedence. The hard gate makes such dual-assigned domains
require BOTH overlapping imports — on existing hubs this surfaces as one required import edit per
dual-assigned domain on the first post-upgrade registration (the dogfooding hub's `equipment` domain hits
this immediately). Tracked there; not a toolkit defect.

### Rejected alternatives

- **Skill-text-only fix.** Prose doesn't gate: the transcript that motivated #426 followed the skill and
  still registered an unactivated domain. Only a deterministic check closes the gap.
- **Keeping the check SHACL-gated.** The mode split was accidental, not designed — no DD ever specified it,
  the check needs no pyshacl, and the in-file precedent (the deliberately unconditional `_master.ttl`
  check, validator.py's "Deliberately unconditional" comment) already establishes that structural import
  checks are mode-independent.
- **Reordering the refmodels fetch before registration** so a fresh `init` could always gate. The fetch is
  deliberately offline-safe and network-touching; moving it ahead of registration couples registering a
  domain to network availability and does not help the actual failure mode (pre-existing authored domains
  on hubs that already have reference models).

### Consequences

- Gate 5's inner-loop `validate --syntax` now catches a missing managed import at authoring time, between
  edits — the cost is `build_reference_module_context` loading the activated modules' closures once per
  run on refmodels-present hubs (scoped to requested domains, not all modules).
- `init --domain` on an import-incomplete pre-existing domain exits 1 with the diagnostics and leaves the
  catalog and `_master.ttl` untouched; `--degraded` registers with warnings.
- No-refmodels hubs (including every `--syntax` test fixture) see byte-identical validator output.

---

## DD-156: Profiling evidence semantics: row_count, rows_sampled, distinctScope

**Status:** Accepted
**Date:** 2026-08-15
**Affects:** `import-flatfile`, `extract-schema`, `import-source`, vocabulary enrichment; schema YAML v1.2; `kairos-bronze` vocabulary
**Implementation:** `src/kairos_ontology/core/import_flatfile.py`, `core/extract_schema.py`, `core/import_source.py` (`normalize_profiling_evidence`, `_distinct_scope`, `_sync_managed_profiling_predicates`), `core/enrich_vocabulary.py`, `scaffold/kairos-bronze.ttl`

### Context

`row_count` meant two different things depending on which importer produced it (#422). The
warehouse path (`extract-schema`) recorded full-table `COUNT(*)` and full-table
`COUNT(DISTINCT)` — true population facts. The flatfile path (`import-flatfile`) recorded
the number of rows read into a capped profiling window (default 1,000) under the **same
field name**, with `distinct_count` counted within that window. Every downstream consumer
that thresholds on `row_count` or trusts `distinctCount` (enum suggestion, FK cardinality
matching, and — via #424 — `suggest-shapes` `sh:in` enums) therefore treated window-local
observations as population truth. The dogfooding hub shipped provably wrong `sh:in` enums
derived from 5-row samples. As DD-089 already put it for a sibling artifact: **source
samples are not equivalent to full production data** — the fields must say which one they
carry.

### Decision

One meaning per field, from schema YAML **v1.2** onward:

| Field (YAML) | Predicate (RDF) | Meaning |
|---|---|---|
| `row_count` | `kairos-bronze:rowCount` | TRUE table cardinality, always. **Omitted when unknown** — never a window size, never a defaulted `0`. |
| `rows_sampled` | `kairos-bronze:rowsSampled` | Rows read into the profiling window. Always present on flatfile-read tables; absent on warehouse extraction (profiling there is full-table). |
| — | `kairos-bronze:distinctScope` | `"table"` or `"sample"`: whether distinct/sample evidence covers the full relation. RDF-only, derived at emission. |

Producer rules:

- **CSV/XLSX**: cap-hit is detected structurally — the read loop's `break` fires only when a
  row *beyond* the cap exists, so natural exhaustion (even at exactly `max_rows` rows) is a
  full read with a true count. Full read → `row_count = rows_sampled`. Capped →
  `row_count` omitted, `rows_sampled = max_rows`. openpyxl "ghost" rows (formatting-only
  trailing rows) can make a boundary-sized sheet look capped; the cost is a conservative
  `row_count` omission, never a false count.
- **Parquet**: `row_count` from `ParquetFile.metadata.num_rows` — free, true, and covering
  all row groups (this also fixed a latent undercount where only the first batch of a
  multi-row-group file was reported). `rows_sampled` = the single batch actually read.
- **Warehouse (`extract-schema`)**: unchanged semantics (already true cardinality); writes
  v1.2 and no `rows_sampled`.

**Scope derivation (H2 guard):** `distinctScope = "table"` iff `row_count` is known AND
(`rows_sampled` is absent OR `rows_sampled == row_count`); `"sample"` otherwise; when BOTH
fields are absent the predicate is **omitted** — zero evidence must never be asserted as
`"table"`. Absence therefore reads as legacy/unknown, which consumers must treat as
untrusted (#424 consumes exactly this contract).

**Legacy normalization (H3 allowlist):** v1.0/1.1 YAML is reinterpreted at a single choke
point (`normalize_profiling_evidence`, after parse, before enrichment). Trust is decided by
platform **allowlist** — only the values `extract-schema` actually emits
(`fabric-warehouse`, `fabric-lakehouse`, `databricks`, `snowflake`, `postgres`) keep
`row_count`; `flatfile`, `unknown`, or a missing platform mean the legacy `row_count` was a
window size and it becomes `rows_sampled`. Unknown provenance is never promoted to truth.

**Merge-managed predicates (H1):** `rowCount`/`rowsSampled`/`distinctScope` are
introspection-owned and replaced on merge (`merge_with_existing`), like
`dataType`/`nullable`/`sampleValues`. Without this, re-running `import-source` over an
existing monolithic TTL would keep the legacy window-sized `rowCount` forever while the
per-table files carried fresh v1.2 semantics — two contradicting claims in one combined
graph, and the "regenerate to migrate" advisory would be false.

### Accepted advisory losses on capped flatfiles (H4)

- **Enum suggestions**: `detect_enums` now requires exhaustive evidence (`row_count` known
  and window covering it) before the existing min-rows/threshold/ratio gates run. Capped
  flatfile tables produce no `suggestedEnum` — a windowed distinct count proves value
  concentration in the window, not that the enumeration is complete.
- **FK cardinality matching**: `infer_foreign_keys` treats an unknown `row_count` as 0,
  which disables cardinality-based (medium-confidence) FK matching for capped flatfile
  tables. Accepted: the signal is advisory-only, and matching against a window size would
  manufacture false positives. Name-based (high-confidence) matching is unaffected.

Both losses restore honesty rather than remove capability: the suggestions they suppress
were exactly the ones the old semantics fabricated.

### Consequences

- Schema YAML v1.2 joins `SUPPORTED_VERSIONS`; flatfile manifests write `version: "1.2"`.
- Migration is regeneration: re-running `import-flatfile` + `import-source` updates the
  managed predicates in place (H1). Untouched legacy TTLs keep their old `rowCount` but
  carry no `distinctScope`, so v1.2-aware consumers treat them as untrusted.
- `column-coverage-audit` display renders an unknown denominator as `distinct=N/?`.
- DD-050 and DD-039 amended; DD-076's "distinctCount is the reliability signal" is
  falsified for windowed evidence and is addressed by #424 (suggest-shapes reads
  `distinctScope` — see DD-076's 2026-08-15 amendment).

---

## DD-157: Domain ownership surfacing and demand-evidence routing

**Status:** Accepted
**Date:** 2026-08-15
**Affects:** `domain-coverage`, `kairos-ontology next`, `validate` (warning path), kairos-design-domain skill
**Implementation:** `src/kairos_ontology/core/domain_coverage.py` (`--explain`/`--owns` cores),
`core/next_actions.py` + `core/hub_inspection.py` (`triage-concept-mapping` observation/action),
`core/evidence_loaders.py` (`scan_concept_mapping_worksheets`, shared with `core/design_landscape.py`),
`core/reference_modules.py` (`surplus_managed_import` warning), `cli/inspection.py`,
`.github/skills/kairos-design-domain/SKILL.md` + scaffold copy

### Context

Two dogfooding findings with the same shape — **the toolkit knows, the design loop never asks**:

- **#418 (near-miss):** an author modeled transport-order concepts in the `consignment` domain. The
  blueprint's `data-domains.yaml` states per domain what it `owns` and `does_not_own`, and
  `analyse-sources` already loads that text — but only into an LLM prompt no design author ever sees.
  Nothing in the prescribed kairos-design-domain loop surfaces or checks ownership; a misplaced class
  passes every gate. Post-DD-155 the *missing*-import case is caught; the undetected residue is the
  **surplus** import (the author adds the other domain's module import, satisfying completeness while
  crossing an ownership boundary).
- **#421:** `import-tmdl` generated Engineering Packs and concept-mapping worksheets for a real hub's BI
  models; all **24 of 24** worksheet tables still had an empty `reference_model_match`. Two deterministic
  consumers already exist — `design-landscape` (advisory `bi_weight` + unfilled count) and
  `draft-model-report` (reads `domain`/`reference_model_match`/`action`) — but no skill text and no `next`
  action routes anyone to the artifacts, and the design skill's inputs mislabeled them as "optional
  TMDL/PBIP … supplied by the user" when the toolkit itself writes them to `integration/discovery/bi/`.

Principle from the adversarial round: **routing first, machinery second, no new write obligations for the
design skill.**

### Decision

1. **Routing text (skill, both copies).** Authoritative input #5 names `integration/discovery/bi/` as
   toolkit-written BI demand evidence, required reading when present; Gate 2 makes the conditional concrete
   (read the whole model on a first pass — the worksheet `domain` field is typically unfilled); step 4
   cites the concept-mapping worksheet + Engineering Pack as the source of the evidence matrix's
   "Downstream demand" column and names the two deterministic consumers. The skill is explicitly told
   **never to fill** the worksheet. DD-147's rule is reaffirmed: BI evidence is demand, never business
   authority; the "Treating TMDL or Gold demand as business authority" anti-pattern stays.
2. **`next` advisory (`triage-concept-mapping`).** A hub-level observation (total worksheet tables /
   unfilled `reference_model_match`) computed by ONE shared helper,
   `evidence_loaders.scan_concept_mapping_worksheets` — which rglobs both `integration/discovery/bi/` and
   the legacy `integration/sources/` location — consumed by both `design-landscape` (its gap message is
   unchanged) and `gather_hub_input_snapshot`, so the two counts can never diverge. The derived action is
   routed to **kairos-design-source** (it owns the import-tmdl lifecycle; kairos-design-domain is forbidden
   from filling the worksheet), status `human_decision_required`, advisory-only, exit 0 (DD-137). Proposal
   `SCHEMA_VERSION` 3→4.
3. **`domain-coverage --explain <domain>`.** Prints the domain's name, OWNS / DOES NOT OWN boundaries, and
   its blueprint module imports — the data `build_domain_coverage_report` already loaded and discarded. No
   accelerator blueprint → clean informational notice; unknown domain → the valid id list. Always exit 0
   (the command's existing contract, also required by the executable-skill test's no-refmodels fixture).
   domain-coverage `SCHEMA_VERSION` 1→2 (the CLI JSON envelope gains optional `explain`/`owns` payloads).
4. **`domain-coverage --owns <ClassName>`.** Reverse ownership lookup with **no closure parsing**: the
   materialized `referencemodels-unpacked/*-inventory.yaml` classes carry `provenance.source_identity`
   (the asserting module's ontology IRI) → matched to a managed profile via
   `load_accelerator_module_config` (both `ontology_iri` and `catalog_uri`, hash-namespace legacy forms
   normalized) → owning domain **list** via the blueprint activations (ownership can be plural).
   Case-insensitive on the class name; specified outputs: inventories missing → "run generate-inventory
   first"; class in no managed module, module assigned to no domain, and same-name-in-multiple-modules all
   say so explicitly. (Deliberately NOT `belongs_to_domains`: it exists only on the parse-all-closures slow
   path — the DD-044 inventory fast path returns early without it.)
5. **Gate-3 ownership step (skill).** A confirmation **step, not a gate** — `owns`/`does_not_own` is free
   text no validator can enforce: before authoring, run `--explain` (and `--owns` for the primary entity)
   and, if another domain owns the concept, stop and switch domains rather than authoring here.
6. **Surplus-import warning (deterministic safety net).** Inside
   `validate_external_term_imports`: **surplus = authored direct `owl:imports` ∩ managed-module IRIs −
   plan requirement IRIs** (a module required in any form — activation, authored term use, accepted
   transitive — is additionally excluded by requirement module id, so an alias-form import of a required
   module can't false-positive). Managedness is matched against `context.config.profiles`, NOT
   `context.modules` — a scoped (init-gate) context may not have the module resolved. The
   `surplus_managed_import` diagnostic names the module and the domain(s) the blueprint assigns it to (or
   "no domain"). Warning severity: it flows through the validator's existing warning path with **zero
   validator edits**, and the DD-155 registration gate inherits it non-blockingly. It structurally cannot
   fire on required imports, cross-module term-use imports (those ARE requirements), `_master.ttl`
   (excluded upstream by `_is_domain_ontology`), or init-added imports (activation set ⊆ requirements).

### Rejected alternatives

- **Fill the worksheet during design (kairos-design-domain).** Violates the skill's
  persist-only-the-accepted-patch charter and guard-scope footprint; per-model worksheet vs per-domain
  slice granularity mismatch; and the worksheet's free-text `domain` field is validated against nothing —
  `draft-model-report`'s `_normalise_domain` slugs it as-is, so filled-during-design values would
  manufacture phantom report domains (a live mini-#418). If wanted later: a separate triage pass under
  kairos-design-source with `domain` validated against canonical ids.
- **Subclass-parent-walk ownership heuristic** (flag a local class whose reference parent lives in a module
  the domain doesn't activate). False-positives on designed-for cross-module reuse: the DD-070 pool,
  pattern-library `mode_bindings`, and `STUB (deferred-relationship)` targets. The surplus-import warning
  is sharper and purely set-algebraic.
- **Per-domain "BI demand mapped n/m" column on domain-coverage.** Chicken-and-egg: attributing worksheet
  rows to a domain needs the very `domain` field that is unfilled; a hub-level count in `next` carries the
  same signal without inventing attribution.

### Consequences

- The design loop now sees ownership at the moment it matters (Gate 3) and gets a deterministic backstop
  (`surplus_managed_import`) for the one case DD-155 cannot catch; both are advisory/warning-level —
  nothing new blocks.
- `kairos-ontology next` surfaces untriaged BI demand and routes it to the skill that owns the lifecycle;
  consumers of the proposal JSON must accept `schema_version` 4 and the new `bi_concept_mappings` input.
<!--
~ SPDX-License-Identifier: Apache-2.0
~ Copyright 2026 Cnext.eu
-->

---

## DD-158: Reference Models Resolve From an Installed Python Package (Supersedes DD-152, Amends DD-036)

**Status:** Accepted
**Date:** 2026-08-15
**Affects:** `cli/shared.py` (refmodels discovery, fetch, provenance), `core/catalog_utils.py`
(`CatalogResolver`), `core/archetype_loader.py` (`resolve_refmodels_root`, version drift),
`core/ontology_loader.py` (`stable_root`, `_relative_identity`), hub scaffolding
(`pyproject.toml.template`, `catalog-v001.xml.template`, `claude-settings.json`),
`.github/workflows/ci.yml`, DD-036, DD-152, DD-047, DD-103

### Context

DD-152 (Proposed, never implemented) argued for a shared, versioned, per-machine cache and
**explicitly rejected** a pip/package approach. This decision supersedes DD-152 and takes the
package approach DD-152 rejected, addressing each of its concerns.

The upstream `kairos-ontology-referencemodels` repository is restructured into a distributable
Python data package. The `ontology-reference-models/` directory moves inside the package tree
(`kairos_ontology_referencemodels/ontology-reference-models/`), and the release workflow
builds and publishes a wheel (`kairos_ontology_referencemodels-<version>-py3-none-any.whl`)
alongside the existing `tar.gz`.

The toolkit resolves reference models from the installed package at runtime, falling back to
`KAIROS_REFMODELS_ROOT` (env var) and `--refmodels-root` (CLI flag) as air-gap escape hatches.
The old sparse-clone fetch mechanism (`_fetch_reference_models`), the folder-scan fallback
(`_resolve_ref_models_dir`), and the `FETCH_PROVENANCE.json` provenance file are **removed**.
No backward compatibility is provided — this is a clean break for new hubs.

### DD-152's rejection reasons and how this decision addresses them

| DD-152 concern | DD-158 response |
|---|---|
| **No package index.** The toolkit uses GitHub-Release-asset direct URLs, not PyPI; a second distribution has no index. | The referencemodels package uses the same distribution pattern: a GitHub Release wheel with a direct-URL pin in the hub's `pyproject.toml`. No PyPI is needed. |
| **Multi-pin divergence.** A second hub-side URL pin reproduces the multi-pin divergence #297 was filed to remove. | A single pin in `pyproject.toml [project.dependencies]` for `kairos-ontology-referencemodels`, managed by `update-refmodels` (uv pip install --upgrade + pin rewrite + uv lock). The toolkit itself is already a single pin; this adds exactly one more, following the same pattern. |
| **`site-packages` path = 291 chars, exceeds MAX_PATH by 31.** | Windows long-path support (`LongPathsEnabled=1`) is standard since 2024. The `pyproject.toml` documents this as a requirement. Package data is kept flat (`ontology-reference-models/` directly under the package directory — no redundant nesting). `importlib.resources.files()` returns a real `Path` for wheel installs. |
| **Bake absolute path into catalog.** Non-portable. | Not needed. The scaffold hub catalog template removes the `<nextCatalog>` entry. The toolkit overlays the package catalog at runtime via `CatalogResolver.with_reference_models()`, which is equivalent to the old `<nextCatalog>` chain but resolved at import time, not baked in. |
| **Coupling refmodels releases to toolkit releases.** | The two packages are independently versioned and independently released. A hub pins each separately. No build-time cycle: the toolkit's dev-dependency pins the referencemodels wheel from a published release; the referencemodels dev-extras pin the toolkit wheel from a published release. Local development uses `KAIROS_REFMODELS_ROOT` / `KAIROS_TOOLKIT_SRC` env vars or `[tool.uv.sources]` path overrides. |

### Decision

**Reference models resolve from the installed `kairos-ontology-referencemodels` Python package.**

Resolution precedence (`resolve_refmodels_root` in `core/archetype_loader.py`):
1. Installed package — `from kairos_ontology_referencemodels import refmodels_root`.
2. Explicit `--refmodels-root` CLI flag (air-gap escape hatch).
3. `KAIROS_REFMODELS_ROOT` env var (air-gap escape hatch).
4. ~~Folder-scan fallback~~ — **removed**.

The package's `refmodels_root()` returns `Path(importlib.resources.files("kairos_ontology_referencemodels") / "ontology-reference-models")`, a real `Path` for wheel installs.

**Catalog overlay:** `CatalogResolver.with_reference_models(catalog_path)` is a factory
classmethod that overlays the package's `catalog-v001.xml` as an extra catalog, equivalent to
the old `<nextCatalog>` chain but resolved at runtime. The hub catalog template no longer
contains a `<nextCatalog>` entry. All 8 `CatalogResolver()` construction sites are updated to
use `with_reference_models()`.

**Closure hash stability:** `_relative_identity` in `core/ontology_loader.py` derives
machine-independent relative paths from the package root: `ontology-reference-models/blueprints/...`.
`stable_root` is the actual installed package path (not a virtual `kairos://` URI). Closure
hashes are identical across machines as long as the package's internal directory structure is
stable (which it is — it's a wheel).

**Scaffolding:**
- `pyproject.toml.template` adds `kairos-ontology-referencemodels @ https://github.com/Cnext-eu/kairos-ontology-referencemodels/releases/download/{refmodels_ref}/kairos_ontology_referencemodels-{refmodels_version}-py3-none-any.whl`.
- `catalog-v001.xml.template` removes the `<nextCatalog>` entry.
- `claude-settings.json` removes all 12 `ontology-reference-models/**` deny-list globs (6 Read + 6 Grep) — the DD-103 boundary becomes structural: the files are absent from the repo.
- `_resolve_scaffold_refmodels_pin()` resolves the latest referencemodels release tag via `gh api`.

**`update-refmodels` command:** replaced with `uv pip install --upgrade kairos-ontology-referencemodels` + pin rewrite in `pyproject.toml` + `uv lock`.

**Provenance:** `_read_refmodels_provenance()` uses `importlib.metadata.version("kairos-ontology-referencemodels")` instead of reading a `FETCH_PROVENANCE.json` file.

**Version drift:** `_refmodels_version()` in `archetype_loader.py` uses `importlib.metadata.version()` first, falling back to reading the `VERSION` file (for `KAIROS_REFMODELS_ROOT` workflows). Per-module `VERSION` files are inside the package and still read via `refmodels_root()` — no change needed.

### Rejected alternatives (carried forward from DD-152, plus new ones)

- **Machine-level shared cache (DD-152).** Rejected — introduces the first machine-level state
  the toolkit has ever owned, with cache lifecycle, GC, concurrent-fetch, profile-redirection, and
  offline-regression problems. A package is a well-understood mechanism with `uv`/`pip` handling
  all of that.
- **Keep vendoring (DD-036).** Rejected — 17.5 MB / 560 files per hub, 409 raw ontology serialisations
  with agent-read deny-list policy rather than structural absence.
- **`KAIROS_REFMODELS_ROOT` only.** Not a distribution strategy; remains as the air-gap escape hatch.

### Consequences

- **New hubs get a clean tree.** No `ontology-reference-models/` directory, no 560 files, no
  per-hub duplicate of 17.5 MB. Reference models arrive via `uv sync` as a Python package dependency.
- **The DD-103 boundary is structural, not policy.** The `ontology-reference-models/**` deny-list
  globs are removed from the scaffold template because the files are simply absent. This is the
  strongest form of the boundary.
- **`update-refmodels` becomes `uv pip install --upgrade` + pin rewrite + `uv lock`.** No sparse
  clone, no `FETCH_PROVENANCE.json`. The pin in `pyproject.toml` is the version record; `uv lock`
  is the lockfile.
- **Offline/air-gapped:** `KAIROS_REFMODELS_ROOT` + `--refmodels-root` are preserved. Pre-seed by
  installing the wheel from a local file: `uv pip install ./kairos_ontology_referencemodels-*.whl`.
- **Issue #428** (grain_collisions registry re-keying, skill wording, coverage step) is split into
  a separate PR — three independent changes that don't depend on the package migration.
- **Contract-manifest.yaml catalog surface** (uri + rewriteURI entries) is preserved verbatim
  inside the package. Only the resolution path changes (filesystem folder → installed package).
  The `test_every_rewrite_prefix_is_a_real_directory` test still passes because the directory
  structure inside the package is identical to the repo-root layout.
- **The `_KNOWN_CLAUDE_SETTINGS_HASHES` in `shared.py` includes the new claude-settings.json hash**
  (without refmodel deny entries) so the `update` command recognizes the new generation. Both old
  and new hashes are present so `update` works on hubs of either generation.
- **Sequencing:** Phase 1 (referencemodels wheel publish, branch `feature/data-package-wheel`)
  must be merged to main and a wheel-publishing release cut before the toolkit can pin to a real
  wheel URL. Until then, the toolkit CI uses a `[tool.uv.sources]` git override pointing at the
  Phase 1 branch. This is temporary and replaced with a wheel-URL pin once the first wheel is
  published.

---


## DD-160: Source-affinity domain coverage and relationship proposal

**Status:** Accepted
**Date:** 2026-08-15
**Affects:** `domain-coverage`, `audit-column-coverage`, `kairos-ontology next`, `compile --check`,
`propose-relationships` (new), kairos-design-domain + kairos-design-mapping skills
**Implementation:** `core/domain_coverage.py` (`load_source_affinity`,
`load_source_affinity_tables`, `_classify`), `core/propose_relationships.py` (new),
`core/column_coverage_audit.py`, `core/compiler/kernel.py`
(`_unrealized_relationship_diagnostics`), `core/next_actions.py` +
`core/hub_inspection.py`, `cli/inspection.py`, `cli/sources.py`

### Context

Five issues from one dogfooding run (#491, #493, #494, #496, #498) turned out to share a single
root cause: **the toolkit already held the evidence, and never joined it up.**

- `analyse-sources` assigns every discovered source table a data domain and persists it in
  `integration/sources/_analysis/*-affinity.yaml`. Nothing ever compared that against the
  authored ontologies and bindings, so a domain holding real source data with nothing bound was
  invisible to every command. The hand-written Stage-4 report claimed two domains had "no
  eligible source tables found"; the affinity files said 2 and 4 tables respectively.
- The accelerator blueprint's `data-domains.yaml` declares `cross_domain_relationships` — 24 for
  the logistics pack — each naming an exact `property_uri` with its domain/range class URIs. It
  was consumed **only** by the legacy v2 report template (`report_projector.py`), never by the v5
  binding path. The hub shipped 27 bindings with `relationships: []`.
- `analyse_sources` blanks `domain` when the LLM assignment fails, and every consumer skipped
  empty-domain rows, so those tables appeared in **no artifact at all** (#492/#500's "12 entirely
  untracked tables").
- `UnboundTableFinding` carried no row count, so the autopilot's own "unbound tables over 1000
  rows" reporting rule was literally unevaluable.

### Decision

1. **`domain-coverage` joins source affinity against ontologies and bindings.** Each row gains
   `source_tables`, `source_tables_secondary` and a derived `status`: `bound`, `deferred`
   (modeled, source data, nothing bound — the "relax this domain" signal), `not-modeled` (source
   data, no ontology — the "add this domain" signal), or `no-eligible-sources` (genuinely empty,
   and the only status that justifies silence). Absent affinity reports yield `None`, never `0`:
   an unrun analysis must never read as "no source data exists". `SCHEMA_VERSION` 2 to 3.
2. **Unassigned source tables are surfaced, not dropped.** `domain-coverage` reports them as
   `unassigned_source_tables`, and `load_affinity_reports` now logs the count it skips. That
   loader still skips them for *alignment* — alignment picks candidate classes from a domain, and
   there is none — but the skip is no longer silent.
3. **`propose-relationships` (new, advisory, exit 0).** The object property is read from the
   blueprint bridge or from a hub `owl:ObjectProperty` (via the DD-103 canonical loader, `rdfs`
   profile, so inherited relationships count), never guessed. Join columns are matched by exact
   normalized name equality against the parent's `identity.sourceKey`. Cross-domain parents get a
   draft DD-138 `externalReference`. Everything non-derivable is an explicit sentinel.
   Endpoint matches are labelled `uri` or `local-name`, because a hub routinely authors its own
   class in its own namespace and a URI-only match discards nearly every declared bridge.
4. **`relationship.unrealized-technical-field` (warning).** Emitted when a binding carries
   `technicalFields` with `purpose: relationship` and no `relationships:` entry. Warning, not
   error: the FK really is materialized and staging carriers ahead of an unbound parent is
   legitimate. Emitted *outside* the blocking path, and the `_binding_safety_diagnostics` call
   site now blocks only on ERROR severity so a future non-error diagnostic there cannot silently
   block a binding.
5. **`audit-column-coverage` gains DD-156 row evidence, `--format json`, and cross-domain
   candidates.** An unknown true count renders `?` and a capped window `N+ (sampled)`, never a
   plain number. Cross-domain candidates come from the affinity pass's own `secondary_domains`.
6. **Routed through `kairos-ontology next`** (`model-data-driven-domain` to
   kairos-design-domain, `bind-deferred-domain` to kairos-design-mapping), so an interactive
   client-hub user gets the signal without the autopilot. Proposal `SCHEMA_VERSION` 4 to 5.

### Rejected alternatives

- **Name-matching leftover columns to other domains' properties** (the first attempt at #489's
  detector). `scaffold_binding`'s measured candidate ladder matches **zero** columns on its
  exact-equality rung against a real 3,087-column corpus, so this reports nothing while looking
  authoritative. The affinity pass's `secondary_domains` already states the same thing with
  evidence — 56 of 79 tables carry one in the dogfooding hub.
- **A `blocked` status derived from counting a domain's own `owl:DatatypeProperty`.** Answering
  "are this domain's classes bindable?" honestly needs the DD-103 semantic index per domain,
  which an always-exit-0 advisory table must not pull in; counting only local declarations
  would over-flag any domain whose properties are inherited. `plan-sources` already warns about a
  zero-datatype target class at the moment an author actually picks one (#484).
- **Persisting a deferred-source manifest** (#492). v5 is stateless by construction (DD-133); the
  v4 Claim Registry was deliberately deleted. Recompute via `domain-coverage` /
  `audit-column-coverage`; the *rationale* for a deferral belongs in the hub Decision Log (DD-141).

### Consequences

- The design loop now measures source coverage at Gate 1 instead of discovering it during
  binding, and `analyse-sources` must be run before `domain-coverage` can say anything about
  sources (it says so explicitly rather than reporting zeros).
- Consumers of the `next` proposal JSON must accept `schema_version` 5; `domain-coverage`
  consumers must accept 3.
- `compile --check` gains its second non-error diagnostic ever (after
  `safety.prefix-ambiguous`). Any freshly `scaffold-binding`-generated binding raises it, which is
  correct: the scaffolder writes the carrier and expects a human follow-up.

---

## DD-161: Multiple bindings per source relation; multi-target bindings rejected

**Status:** Accepted
**Date:** 2026-08-15
**Affects:** DD-133 EntityBinding authoring guidance, kairos-design-mapping skill
**Implementation:** `.github/skills/kairos-design-mapping/SKILL.md` section 6a (+ scaffold copy);
no code change — the capability already exists

### Context

#489 reported that "one source table can only map to one canonical domain", concluding that
columns outside the chosen domain are silently lost, and proposed multi-target bindings.

The premise is false. Nothing constrains a source relation to one binding:
`entity-binding.schema.json` places no uniqueness constraint on `source.relation`, and
`quality.py`'s `safety.artifact-collision` keys on binding **name** and artifact **path** only.
`compile <domain>` selects bindings by `metadata.domain`, so two bindings over one relation in
two domains are in different compile scopes and cannot collide. The real gap was that nothing
told the author this — not the schema, not the skill, not any diagnostic.

### Decision

Multi-domain source coverage is expressed as **multiple bindings over one source relation**, one
per canonical entity, each with its own grain, identity, load policy and quality. This is
documented with a worked example (`Qargo.orders` to booking at order grain, to party at customer
grain) in kairos-design-mapping section 6a, including the two constraints that make it safe:
differing grain per target, and the fact that two bindings for the same class in the *same* domain
require a `conformance:` block or fail `conformance.group-required`.

**Multi-target bindings are rejected.** Because each target needs its own grain/identity/load, a
multi-target document would have to nest N complete binding bodies — identical in content to N
documents, while breaking the DD-133 section 3 invariant ("One binding document authors **one**
canonical entity from **one** source relation", restated normatively at section 3d) and requiring
changes to `target.class` (string to array), four `by_target` maps in `kernel.py`/`quality.py`,
conformance regrouping, and per-target artifact paths and provenance. Large blast radius, no new
capability.

Requiring a dbt split model instead is also rejected as the default: that is for genuine
relational logic (aggregation, joins, grain change), not for separating entities that are already
separable by grain.

### Consequences

- #489 closes as a documentation gap, not a schema limitation.
- `audit-column-coverage` names bound tables whose affinity assigned them a domain nothing binds
  them to (DD-160), so the missing second binding is prompted rather than discovered late.
- This decision exists so the multi-target proposal is not re-raised without new evidence.

---

## DD-162: Hub-side registration of source-discovered concepts

**Status:** Accepted

**Date:** 2026-08-15

**Affects:** `src/kairos_ontology/core/registered_concepts.py` (new),
`src/kairos_ontology/core/conformance_artifact.py`,
`src/kairos_ontology/core/design_landscape.py`,
`src/kairos_ontology/core/hub_inspection.py`,
`src/kairos_ontology/core/next_actions.py`, `src/kairos_ontology/cli/sources.py`,
`kairos-design-source` skill

**Implementation:** `register-concept`

### Context

Issue #505 reported three mechanisms that could stop an ontology domain being modeled. Two
turned out not to exist as described:

- The archetype tier `not_applicable` (Layer A) is **not in the published tier enum at all** —
  `VALID_TIERS = ("required", "recommended", "optional")`. Ref-models #82 was closed for exactly
  that reason. Layer A is moot.
- The `not-applicable` *outcome* (Layer C) is real and is handled by issue #507: source-evidence
  aware judgments, `core/conformance_evidence.py`.

The third (Layer B) is real and had no answer. **A business concept that exists in the source
data but has no entry in the archetype catalog is invisible to the entire system.** Discovery
only ever iterates the catalog, so such a concept cannot be judged, cannot carry a
`likely_domains` tag, never reaches `design-landscape`, and never becomes an authored domain.
On the CLdN hub roughly ten BI-relevant concepts sat in that hole: planning zones, tariff
scales, empty-unit lifecycle, distance/toll matrix, order source attribution.

DD-160 surfaced the *domain*-level version of this gap (`unassigned_source_tables`, and the
`not-modeled`/`deferred` statuses). It has no concept-level counterpart, and no way to record
that a specific concept belongs.

### Decision

Add hub-side concept registration, answering the four questions #505 left open:

1. **Human confirmation is required.** A registration records `decided_by`; an `ai`/`autopilot`
   registration with `needs_confirmation: true` or no `confidence` is an open question and
   blocks `compile`/`validate` through the existing `check_discovery_gate`, exactly like an
   unresolved archetype judgment (DD-148). Adding a concept the blueprint deliberately omitted
   is a strictly *larger* authority than judging one it included, so it cannot be gated more
   weakly.
2. **Persisted in its own artifact**, `integration/discovery/registered-concepts.yaml`, with its
   own `schema_version`, and mirrored by `discovery-conformance build` into a **sibling**
   `registered_concepts` list in the conformance artifact. Deliberately *not* merged into
   `core_concepts`: `validate_artifact`'s coverage/identity checks (#308) require every
   `core_concepts` entry to be a real concept of the resolved archetype's catalog, and
   `concept_set_hash` staleness would fire on every registration. **Registering a concept must
   not make the archetype look wrong.** A URI present in both is an error.
3. **The archetype schema is not extended.** Registration is hub-side only; the reference-models
   repo is untouched. The archetype catalog stays a stable shared contract across every hub that
   uses it, and adding a concept to one hub never requires a cross-repo release. A URI already in
   the catalog is *rejected* for registration — it belongs in `core_concepts` with a real
   discovery judgment, and registering it would route it around the coverage checks.
4. **Counted separately, never folded into the archetype total**, so archetype-conformance
   percentages stay comparable across hubs. Registered concepts are excluded from the artifact's
   `scorecard` for the same reason #507 kept `by_evidence` out of it: `validate_artifact`
   recomputes that scorecard and compares it for equality against the stored one.

Registered concepts always carry tier `optional`: the source data argued them into scope, no
blueprint recommended them, and any other tier would misrepresent an obligation nobody made.
`--source-evidence` and `--rationale` are both mandatory — registration is a claim about source
data, and an unevidenced or unexplained claim is a guess the next reader cannot check.

`design_landscape` synthesizes a class record for each registered concept. This is required, not
cosmetic: the report's join skips any URI the activated accelerator modules do not declare, and
a registered concept is outside those modules by construction — without it, the concept would be
silently absent from the very backlog it exists to appear in.

### Rationale

The alternatives each fail on one of the four questions. Extending the archetype schema makes
one hub's business concept everyone's contract change. Writing registrations into `core_concepts`
makes the archetype's own coverage and staleness checks fail on correct hubs. Skipping human
confirmation grants AI a larger authority for inventing a concept than DD-148 grants it for
judging one. Folding registrations into the scorecard makes conformance percentages
incomparable across hubs, which is the number the scorecard exists to provide.

### Consequences

- A concept outside the archetype catalog can be recorded, gated, surfaced in
  `design-landscape`, and routed by `kairos-ontology next` (`model-registered-concept`).
- Registration records that a concept *belongs* and names its evidence. It does not model or
  bind it: authoring the class stays a `kairos-design-domain` decision.
- The conformance artifact gains an optional `registered_concepts` key. Absent in every existing
  artifact, and absence is indistinguishable from empty, so no artifact on disk is invalidated.
- `register-concept` is gated to `kairos-design-source`, not `kairos-design-discovery`: the
  registration is proposed from `analyse-sources`' own unassigned-table output.

---

## DD-163: Hub-wide ontology integrity is enforced, not advised

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `validate`, kairos-design-domain Gate 3, kairos-design-mapping
**Implementation:** `core/ontology_integrity.py`, wired into `core/validator.py:run_validation`

### Context

Every ontology check the toolkit had was single-file by construction.
`validate_naming_conventions` parses one `.ttl` with no import resolution — deliberately, and
its docstring says so — and `validate_managed_imports` compares one domain's declared imports
against the blueprint. Neither can observe a relationship *between* two domain files.

A 21-domain autopilot run exposed the consequence. Of 132 locally declared classes, 34 were
re-mints of the same eight concepts across domains: `Consignment` and `Booking` in eight domains
each, `Document` and `Company` in seven, `Contact` and `Comment` in four. Each domain has its own
namespace, so these are unrelated OWL entities that merely share a name, with no
`owl:equivalentClass` between them. `validate` passed the hub cleanly. The defect surfaced two
stages later as a dbt parse failure — the projector derives a model filename from the class local
name, so `party#Company` and `mdm#Company` both emitted `company.sql`.

Nine of those files stated the violation in their own headers. `party.ttl` lists under
`Deliberate exclusions`: *"Party bookings: owned by the booking domain"*, then declares
`:Booking`. The accelerator blueprint agrees — `party.does_not_own` reads *"Contracts, bookings,
invoices, operational events, or terminal moves."* That prose was already a contract field
(`analyse_sources` feeds it to the source-affinity classifier, so its wording is behavioural),
but nothing read it after classification. kairos-design-domain Gate 3 conceded the point in
writing: *"the blueprint's owns/does_not_own boundaries are free text no validator can enforce."*

The affinity analysis was not the cause. Every leaked concept had been assigned to exactly one
domain, and the correct one — `Booking` to booking, `Comment` to claims. The evidence entering
design was clean; the design stage did not honour it.

### Decision

Add a hub-wide integrity pass to `validate`, blocking by default and degradable with
`--degraded`. Three checks are errors:

- `integrity.class-redeclared-across-domains` — purely mechanical, no interpretation, and
  already a build failure downstream;
- `integrity.class-violates-declared-exclusion` — the file's own header contradicts the file;
- `integrity.class-outside-blueprint-boundary` — the blueprint's `does_not_own` names the concept.

Four more are advisory: reference-model shadowing (class and property), unused `owl:imports`,
and collapsed address value objects.

**Precision is chosen over recall.** A false positive on a blocking check teaches an operator to
pass `--degraded`, which would cost more than the check earns. So each blocking check reads
either a machine-readable fact or the hub's own written-down intent. Notably, a bullet naming
*this* domain as owner ("Contact details: owned by the party domain") is a clarification, not an
exclusion, and must not flag `:Contact`; and the domain's own name inside a subject phrase
("Party bookings") must flag `Booking` without flagging `Party`. Both are regression-tested.

Fuzzy inference — "does this class feel like it belongs here" — is deliberately absent. Anchoring
ratios are reported as scores rather than enforced, because a hub legitimately declares local
classes the reference model does not carry.

### Alternatives rejected

| Alternative | Why not |
|---|---|
| Ship as warnings first | `kairos-flow-autopilot` states "warnings are acceptable but must be explained". A warning would have been explained and ignored in exactly the run that produced this. |
| Put the rule in the skill | Skills are prose an agent may skip under context pressure, and this rule was *already* in prose — in the exemplar, in Gate 3, and in nine file headers — and was violated anyway. |
| Enforce via SHACL | Cross-file identity comparison across namespaces is not what SHACL shapes are for, and the hub's shapes are hand-authored governance, not toolkit-owned. |
| Reuse `load_ontology()` | It merges the import closure, erasing the locally-declared vs imported distinction every check depends on. Registered in both TTL-boundary tests with that reasoning. |

### Consequences

Existing non-conforming hubs fail `validate` until fixed or run with `--degraded`. That is the
intent: the CLdN hub moves from passing to 63 blocking errors, all of which were already real.


## DD-164: Every source table needs a recorded disposition

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `validate`, kairos-design-domain Gate 1, kairos-design-mapping
**Implementation:** `core/source_disposition.py`, `source-disposition` CLI, wired into
`core/validator.py:run_validation`

### Context

A blueprint deliberately scopes which domains exist (DD-149/DD-150), so a hub will always hold
source tables no blueprint domain claims. `domain-coverage` already reports this — `not-modeled`,
`deferred`, unassigned tables — but reports it advisorily and always exits 0, so nothing obliges
anyone to answer.

Unanswered, the question resolves itself two ways, both unrecorded. The table is dropped ("no
canonical entity"), or it is force-fitted by minting a local class in whatever domain was in
scope. A real run did both to the same table: `comments` (3,149 rows) was skipped in `claims` as
having no canonical home, while a local `Comment` class appeared in commercial, customs, mdm and
roro, and a `hasCommentCategory` property was hung off a leaked `Document` class in party. The
run's transparency report then asserted *"All unbound tables are metadata, schema-lookup, or
workflow tables with no canonical entity target"* — while `qargo.stops` (72,633 rows),
`qargo.shipments` (32,491) and `qargo.resource_allocations` (30,492) sat unbound and unmentioned.
The hand-built `.dap-dbt` project models all three as first-class entities, so they are plainly
business data.

`register-concept` (DD-162) already existed as the sanctioned route for "our source data argued
this concept in". It was referenced by one skill, once, and the run produced
`registered_concepts: []`.

### Decision

Make the outcome an artifact. Every source table above `DEFAULT_ROW_THRESHOLD` (100) rows must be
either bound by an EntityBinding or carry an explicit disposition in
`integration/sources/_analysis/table-dispositions.yaml`. An unbound, undisposed table fails
`validate`; smaller ones warn.

The disposition set is closed: `bound`, `registered-extension`, `deferred`, `not-business-data`,
`blueprint-gap`. The last three require a written rationale, because a reviewer cannot otherwise
distinguish a considered skip from an overlooked table.

This does not force data into the ontology. `not-business-data` remains a good answer — it simply
has to be an answer, attributed and reasoned, rather than the absence of one. `blueprint-gap`
exists so a genuine accelerator shortfall is filed upstream instead of absorbed hub-side, and the
undecided-table remediation names `register-concept` explicitly so the sanctioned path is the
visible one.

### Alternatives rejected

| Alternative | Why not |
|---|---|
| Add a `--strict` flag to `domain-coverage` | Deferred once already (issue #393). An opt-in flag is not run by the pipeline that needs it, and the gap is in `validate`, which stage exits already call. |
| A hub-local extension domain | Solves where a concept lives, not whether anyone decided. Still available later as a disposition value. |
| One record per table | The ledger's value is that a reviewer sees every skipped table in one place and can judge the shape of what the hub declined to model. |
| Threshold on row count alone | A table with no recorded `rowCount` is reported as unknown and still requires a decision: not knowing its size is not evidence that it is empty. |

### Consequences

The CLdN hub reports 56% decision coverage — 42 bound, 0 disposed, 33 undecided of 75 — and 22
blocking errors. Closing them is a human pass over tables that were, until now, invisible.


## DD-165: Anchoring is suggested deterministically, never invented

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** kairos-design-domain step 3 (inspect selected industry references)
**Implementation:** `core/class_anchoring.py`, `suggest-anchor` CLI

### Context

DD-163 made an unanchored local class visible. Visibility does not change what gets
authored: the run that prompted it anchored 5 of 132 classes (3.8%) and 0 of 473
properties, while declaring 57 `owl:imports` and referencing terms from 4 of them. The
reference models were installed, imported, and then ignored. A hand-built hub over the
same sources reached 87% class anchoring and 18 `rdfs:subPropertyOf` links, so the gap is
effort, not feasibility.

The effort is mundane and entirely mechanical: find which of ~80 materialized inventories
covers the domain's imports, then read it for a plausible match. Declaring a local class
is always cheaper. Warning about the result afterwards does not change that arithmetic.

### Decision

`suggest-anchor <domain>` reads the inventories for the modules the domain already
imports, ranks candidates for each unanchored term by name evidence, and prints the exact
`rdfs:subClassOf` / `rdfs:subPropertyOf` line. It never writes.

Three constraints make the output trustworthy rather than merely plentiful:

**Silence beats a plausible wrong answer.** An early scoring pass rewarded a shared head
noun and produced `companyBillingPostalCode -> companyCode` and
`companyLegalName -> contactName`. Acting on either writes a false subsumption into the
canonical model, and both look considered. Nothing below an exact, case, plural, or label
match now scores at all.

**Turtle is emitted only for a confident match.** Weaker matches ("X is a qualified form
of Y") are shown as candidates with the paste-ready line withheld, because name evidence
cannot separate a right specialisation from a sibling.

**Ranking uses the archetype, and warnings do not reorder it.** Eight classes in the party
modules end in "Party" and score identically; the archetype breaks the tie, marking
`mmt/party#TransportParty` *required* and `NotifyParty` *optional*. Separately, a first
version sorted pattern-library grain collisions last — which buried `TransportParty`, a
flagged collision *and* the archetype's required party identity, beneath two deprecated
role overlays. The caution is now an annotation on the ranked answer, never a demotion.

### Alternatives rejected

| Alternative | Why not |
|---|---|
| Auto-apply the top anchor | Subsumption is a modelling assertion. `qualified-role-assignment` exists because subclassing the wrong party parent is a known, costly error. |
| Embedding/LLM similarity | A score no one can explain makes the author's judgement harder, and this must stay deterministic and offline like every other design-stage check. |
| Enforce an anchoring ratio | A hub legitimately declares classes the reference model does not carry. Ratios stay reported by DD-163, unenforced. |
| Suggest from all inventories | An anchor into an unimported module produces a dangling reference the managed-import check then rejects. Scoped to declared imports. |

### Consequences

Advisory and exit-0 always. On the CLdN hub it finds confident anchors for 3 of party's
40 unanchored terms, 6 of financial's 120, and 4 of booking's 64 — modest, and every one
is an exact name match against a module the domain already imports, i.e. reuse that was
sitting there unused.


## DD-166: Sample values are evidence, and are gated before they leave the hub

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `analyse-sources`, `propose-alignment`, `import-flatfile`, `import-source`
**Implementation:** `core/analyse_sources.py`, `core/import_flatfile.py`, `core/import_source.py`,
`core/propose_alignment.py`, `cli/sources.py`

### Context

`analyse-sources` sends sample values from every column to a third-party LLM. The module
contained no privacy check: redaction happened earlier, at import and via
`source-privacy`, and the send step relied on that ordering. Ordering is not a control.

Separately, capture was five values per column, and the alignment step showed three. That
is too few to tell a governed code list from free text, which is the judgement alignment
exists to make.

### Decision

`analyse-sources` runs the privacy scan and refuses on any finding, reporting paths and
kinds only, never the offending value.

Capture rises to twenty **distinct** values. Three separate caps had to move, each of which
made the previous fix a no-op: four hardcoded five-value slices in `import_source` that took
the first five rather than five distinct; a single `DEFAULT_SAMPLE_SIZE` in `import_flatfile`
governing both column values and whole sample rows; and finally the real one — column values
were stripped from the schema YAML on write, with the TTL deriving its values from the five
sample rows instead.

That last point is the substantive change. Stripping the values *was* the privacy control:
they had never been sanitized. They now pass through the same `redact_sample_rows` detector
as rows — reused rather than reimplemented, each value becoming a one-cell row — and are
published. Redaction collapses distinct values to identical tokens, so they are deduped
again: a PII column contributes one masked token, not twenty copies.

Row samples stay at five and stay out of the schema YAML. A row correlates every column of
one real record; a column value does not. Conflating the two under one constant is what hid
the distinction.

Affinity keeps three values (`MAX_AFFINITY_SAMPLES`): it classifies a table into a domain and
needs a type hint, not a distribution. Alignment gets twenty. The asymmetry is asserted in a
test so it cannot drift.

### Consequences

On 75 real tables, 34% of 3,410 columns now carry more than the old cap and 604 hold the full
twenty, with `source-privacy` clean across 227 artifacts. Note for reviewers: legal entity
names (`companies.name`) are correctly *not* PII and are now sent twenty at a time. That is
commercial confidentiality, not GDPR, and is a separate control if the business wants one.

## DD-167: Conformance judgment is offloaded, retrieval-grounded, and code-gated

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `discovery-conformance`, kairos-design-discovery
**Implementation:** `core/conformance_judge.py`, `discovery-conformance judge`

### Context

`discovery-conformance` could scaffold a judgments file and validate a finished one, but
nothing filled it in. For `unit-load-carrier` that is 174 concepts, so the orchestrating
agent judged them inline. The hub's own issue log recorded this as an open enhancement —
the pass belongs on the configured provider, not in the orchestrator's context.

The risk is specific. A wrong `conforms` silently certifies a concept the hub never models:
a real run scored the party domain "6 conforms / 0 deviates" while its ontology contained
none of the three classes it certified, and recorded *"the same companies carry customer,
subcontractor and consignee roles"* as proof a role-assignment entity existed — which is the
evidence that one is **needed**, not that one exists.

### Decision

`discovery-conformance judge` offloads the pass, batched (~15 calls for 174 concepts), under
a third AI role (`judgment`). It is retrieval-grounded: the model never recalls concepts or
emits URIs, receiving the archetype catalog plus collected evidence and choosing from a
closed outcome set.

Enforcement is in code, not in the prompt, because a prompt asks the thing being checked to
check itself. Four guards run over every response:

1. An unrecognised outcome becomes `partial`, never coerced to the nearest valid one.
2. `conforms` with no source evidence is downgraded.
3. `conforms` on **domain-level evidence only** is downgraded. Alignment evidence and an
   affinity `likely_entity` match name the concept; "16 tables in the party domain" does not.
   Without this guard the first live run reproduced the original error exactly.
4. A concept the pattern library flags (grain collision, anti-pattern exemption) **escalates**
   rather than downgrades. A grain collision governs how a concept is modelled, not whether
   the business has it; forcing `mmt:TransportParty` to `partial` would be wrong, but
   certifying it unreviewed is worse.

Evidence placement is derived from the blueprint: a concept's URI names its module and
`data-domains.yaml` maps modules to domains, breaking the circularity where evidence needed
the `likely_domains` that the judgment was meant to produce. Downstream BI demand is passed
as a distinct, labelled signal — it can corroborate, never certify.

Every judgment is `decided_by: ai`, so DD-148's gate still requires human resolution, and the
command cannot satisfy DD-149's archetype confirmation as a side effect.

### Consequences

On the live hub: `TransportPartyRoleAssignment` moved from conforms 0.91 to partial 0.58
flagged, `TransportPartyRoleCode` from 0.86 to 0.56, `TransportParty` from 0.95 to 0.61. The
ten surviving `conforms` are precisely the concepts a source table is identified as. 147 of
174 need human confirmation — high, and honest: most of this archetype is genuinely unproven
before mapping has run.


## DD-168: Alignment coverage is reported with a reason code per unmapped column

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `propose-alignment`, kairos-design-discovery
**Implementation:** `core/alignment_report.py`, `propose-alignment alignment-report`

### Context

Alignment finished with no statement of what it had *not* done. On the live corpus it
mapped 494 of 1,994 columns; the other 1,096 simply vanished from view. "75 tables aligned"
reads as completion. The first version of the report was worse than silence: it printed
"0 gaps" because it looked for `example_values` on entries that never carry that key, so
the no-evidence branch always fired and every gap was filtered away as noise.

### Decision

Every source column not bound to a reference property is reported with one code from a
closed set: `no-reference-property`, `low-confidence-suggestion`, `no-sample-evidence`,
`vendor-slot`, `operational`. Evidence is read from the source vocabulary, not from the
proposal. A column whose evidence cannot be established counts as a **gap**, never as
noise — the fallback must be the direction that gets a human to look.

### Consequences

`GAP_REASONS` names the two codes that mean the domain model is short of a property, which
is the subset that blocks (DD-169). Grouping by column name collapsed 1,096 gap columns to
609 distinct names, of which 258 recur across tables and cover 745 columns — the recurring
names are the tractable work.

## DD-169: The alignment gap is a hard stop before entity binding

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `compile`, entity binding, kairos-design-domain
**Implementation:** `core/alignment_report.py` (`undecided_gap_columns`, `GAP_RESOLUTIONS`)

### Context

Entity binding is the last point at which an omission is cheap. After it, an unmapped
column with real business signal is not merely missing — the binding asserts a shape that
says the model is complete, and every downstream projection inherits that claim.

### Decision

Gap columns carrying real signal and no recorded decision block the workflow before entity
binding. Not a warning: a stop. Clearing one is an explicit recorded resolution from
`GAP_RESOLUTIONS`, so "we looked at it and it does not belong" is a durable, auditable
answer rather than an absence.

### Consequences

The gate is deliberately upstream of the expensive stage. A gap found here costs a
decision; the same gap found after binding costs a re-model.

## DD-170: A model-proposed hub-local property is validated, not trusted

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `propose-alignment`
**Implementation:** `core/propose_alignment.py` (`normalize_local_proposal`, `flag_risky_proposals`)

### Context

When no reference property fits, the aligner may propose a hub-local one. Left unchecked
the model returns IRI-shaped names, ranges that are classes, and role-flavoured properties
(`isShipper`, `customerFlag`) that are the `subclass-identity-by-role` anti-pattern wearing
a property's clothes.

### Decision

Local proposals pass `normalize_local_proposal`, which rejects IRI-shaped `name`, `range`
and `on_class`, and `flag_risky_proposals`, which flags role-shaped names for review. A
rejected proposal degrades to a gap column (DD-168) rather than entering the registry.

### Consequences

The two checks are coded, not prompt instructions — a prompt can be talked out of a rule,
a normalizer cannot.

## DD-171: The business glossary is a preflight input to alignment

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `propose-alignment`, discovery preflight
**Implementation:** `core/propose_alignment.py` (`load_glossary_terms`)

### Context

The glossary was treated as documentation. It is evidence: it is where the organisation
already wrote down what its own terms mean, and the pattern-library cautions need it on
every run, not on the runs where someone remembered to pass it.

### Decision

Alignment loads glossary terms as part of discovery preflight, unconditionally.

### Consequences

Glossary absence is now visible at preflight rather than silently producing a
vocabulary-blind alignment.

## DD-172: Namespace constants are pinned by test, after `domainIncludes` never matched

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** every projection and reader touching schema.org terms
**Implementation:** `core/projections/shared.py`, `tests/test_namespace_constants.py`

### Context

`SCHEMA = Namespace("http://schema.org/")`. Every reference model in the pack binds
`https://schema.org/`. The constant had therefore **never matched a single triple** in the
project's life, so the REUSABLE domainless-property pattern — `schema:domainIncludes` —
was invisible to every consumer. `TradeParty` presented 9 properties instead of 13, and
the four it hid were `hasAddress`, `hasBillingAddress`, `hasShippingAddress`, `hasContact`.
The live symptom was the aligner replying that *no address property is listed on
TradeParty* while `hasBillingAddress` to `Address` sat in the list it was reading.

A second instance of the same class of defect: object properties rendered identically to
datatype ones, so `hasBillingAddress (Address)` looked like a string property named
Address.

### Decision

Match both spellings (`DOMAIN_INCLUDES_PREDICATES`), mark object properties explicitly in
the prompt, and pin every namespace constant with a test that asserts the constant matches
what the shipped reference models actually bind.

### Consequences

A silently-never-matching constant produces no error, no warning and a plausible answer —
it can only be caught by asserting against real data. The guard was verified by
reintroducing the bug: it fails 2 of 3. The other 13 namespace constants were audited and
are correct.

## DD-173: Reference models resolve live; there is no inventory

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** all reference-model consumers
**Implementation:** `core/class_anchoring.py` (`read_reference_terms`), `core/ontology_loader.py`

### Context

A materialized inventory sat between the resolver and its consumers, kept honest by a
freshness gate. DD-172 showed what that costs: when the resolver was fixed, every cached
inventory kept the old wrong answer, and the fast path *preferred* the cache — so the hubs
that had an inventory were exactly the hubs that stayed broken. The freshness gate could
not see this, because the snapshot was perfectly fresh with respect to a stale resolver.

### Decision

Delete the inventory. `read_reference_terms` resolves live from the catalog through the
canonical loader (DD-103) on every call. `generate-inventory`, `check-inventory` and the
freshness gate are removed with no compatibility shim.

### Consequences

Nothing can drift from the resolver, because nothing is stored. Module selection excludes
the hub's own `model/ontologies` by resolved path — an earlier hostname filter also
excluded every other vendor and all test fixtures.

## DD-174: LLM pipeline stages are seeded, and capability degradation is centralised

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `propose-alignment`, `analyse-sources`, `discovery-conformance judge`
**Implementation:** `core/ai_provider.py` (`resolve_ai_seed`, `create_chat_completion`), `tests/test_ai_determinism_guard.py`

### Context

The LLM stages are analysis, not authorship: the same evidence should yield the same
proposal on Tuesday as on Monday, or a re-run silently rewrites a model a human already
reviewed. Measured on one domain, three identical runs mapped 21, 26 and 25 columns.

Three defects underlay this, all invisible to review:

1. `temperature=0.1` had never taken effect on the reasoning tier. Those models reject the
   parameter outright; the provider wrapper caught the rejection and retried without it.
   The setting read as variance control and was a no-op.
2. The affinity and judgment stages called `chat.completions.create` directly, bypassing
   that wrapper. They worked only because they happened to point at a model tolerating
   `temperature`; repointing either at a reasoning model was a hard 400.
3. The discovery round-trip was paid once per source table, not once per model.

Measured on this provider: `temperature` and `top_p` rejected on the reasoning tier,
`seed` accepted on every model, and with a seed 3/3 completions byte-identical against
3/3 different without.

### Decision

Every pipeline completion passes `seed=resolve_ai_seed(role)`, resolving
`KAIROS_AI_{ROLE}_SEED` then `KAIROS_AI_SEED` then `DEFAULT_AI_SEED`, where `off` disables
seeding so run-to-run variation can still be measured deliberately and a non-integer value
raises rather than silently unseeding. Every stage routes through `create_chat_completion`,
which now remembers a per-model parameter rejection for the process.

### Consequences

Seeding is best-effort by construction: it removes sampling noise, not the effect of a
changed prompt, model or provider backend. This provider returns no `system_fingerprint`,
so a backend change is undetectable from the response — which is why the seed is recorded
next to the model in artifact provenance rather than assumed. A source-level guard fails
any new stage that forgets either the seed or the wrapper.

## DD-175: The prompt is reproducible, because a seed cannot stabilise a moving question

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `propose-alignment`, `analyse-sources`, every reference-model consumer
**Implementation:** `core/ontology_loader.py` (`stable_value`), `core/semantic_index.py`, `core/analyse_sources.py`, `core/ontology_ops.py`, `core/propose_alignment.py` (`_sorted_terms`)

### Context

Seeding every LLM stage (DD-174) moved party-domain stability from 62% to 77%, not to
100%. The residual was ours, not the provider's: the prompt was different on every run.

Two independent causes, both invisible in review because both look like ordinary code:

`Graph.value()` returns an *arbitrary* object when a term carries more than one. It takes
whatever graph iteration yields first, and that order differs between processes.
Reference-model classes routinely carry several `rdfs:comment` triples — a local
definition plus one pulled in through the import closure — so the same class described
itself differently each run. Measured on the live catalog: 46 of 2,706 resolved terms
changed their comment between two consecutive runs. `ontology_ops._first_literal` was the
same defect wearing a different name; there is no "first" when iteration order is
undefined.

Separately, `parse_source_vocabulary` collected a table's columns into a `set` of
`URIRef` and iterated it. `URIRef` hashes as a string, so iteration order is randomised
per process. All five party-domain table prompts differed between two processes, and 70
of 352 prompt lines differed for `companies` alone.

### Decision

`stable_value` lands in `ontology_loader` — the DD-103 canonical loader — and is used by
`semantic_index`, `analyse_sources` and `ontology_ops`, so every consumer stabilises from
one definition. It prefers an `en` literal, then breaks ties lexically. This is a
tie-break, not a merge: where several definitions genuinely apply, one is chosen, always
the same one.

Reference-model classes and properties are ordered by `_sorted_terms` on `(name, uri)`,
keeping own and inherited properties in separate groups because the prompt relies on that
distinction. Source tables and columns are sorted by URI; the bronze vocabulary records no
column ordinal, so that is the available deterministic order.

Restriction reads (`owl:onProperty`, `owl:onClass`) keep `Graph.value`: those are
functional by OWL semantics, so an arbitrary pick is the only pick.

### Consequences

`read_reference_terms` now hashes identically across four consecutive processes (2,706
terms), and all five party table prompts hash identically across three. Stability rose to
80%.

The remaining gap is provider-side and not ours to close: on the real 23 KB alignment
prompt a fixed seed yields three distinct completions from both `gpt-5.5` and
`gpt-5.6-terra`, where the same seed on a short prompt is byte-identical. That is what
motivated DD-177. A stable prompt is still the precondition — it is what makes a stable
answer mean anything.

## DD-176: Reasoning effort is a per-role knob, defaulted from the shape of the work

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `propose-alignment`, `analyse-sources`, `discovery-conformance judge`
**Implementation:** `core/ai_provider.py` (`resolve_reasoning_effort`, `DEFAULT_REASONING_EFFORT`)

### Context

The reasoning-tier models accept a `reasoning_effort` parameter, and the pipeline's three
LLM stages do genuinely different work. Affinity is a one-of-N pick over a short candidate
list, made once per source table — the highest-volume call and the one least helped by
extended reasoning. Alignment and judgment are closed-vocabulary reasoning over a large
candidate set, where a wrong answer is silently wrong.

### Decision

`resolve_reasoning_effort` resolves exactly like the seed (DD-174):
`KAIROS_AI_{ROLE}_REASONING_EFFORT`, then `KAIROS_AI_REASONING_EFFORT`, then a per-role
default of `low` for affinity and `medium` for alignment and judgment. `off` sends no
`reasoning_effort` at all. An unrecognised tier raises rather than being passed through,
so a typo fails at the first call instead of silently reverting to the model's default.

`create_chat_completion` drops `None`-valued kwargs, so a disabled knob is absent from the
request rather than sent as null.

### Consequences

These are defaults, not findings. Effort trades latency against recall, and recall is the
weak axis here — roughly a quarter of source columns map. They should be changed from
measurement, not intuition.

One measurement already argues against reaching for the cheap tier: `gpt-5.6-terra` at
`low` scored 63% stability and 21.7 columns mapped on the party domain, against 80% and 23
for `gpt-5.5` at its default. Speed was the only axis on which the cheaper configuration
won.

## DD-177: The alignment answer is shape-constrained, so a column cannot be skipped

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `propose-alignment`
**Implementation:** `core/propose_alignment.py` (`build_alignment_response_schema`, `normalize_schema_response`), `core/ai_provider.py` (`param_fallbacks`)

### Context

Alignment asked for `{"type": "json_object"}`, which guarantees parseable JSON
and nothing else. Under it the model may simply leave a column out of its answer,
and measurement showed that is exactly what it did — inconsistently.

Three identical runs of the party domain mapped 24, 22 and 23 columns with **zero**
disagreement about what the shared columns meant. The instability was never in the
model's judgement; it was in which columns the model bothered to answer for.

The earlier variance work took stability from 62% to 80% — a fixed seed (DD-174),
then a reproducible prompt (DD-175) — but could not close it. Seeding turns out not
to survive a real prompt: on the 23 KB alignment prompt, one seed produced three
distinct completions from both `gpt-5.5` and `gpt-5.6-terra`, where the same seed on
a short prompt is byte-identical. Provider-side determinism is simply not on offer at
this size, so the remaining lever is the shape of the answer.

### Decision

`column_alignments` is a JSON-schema **object keyed by source column name**, with every
key in `required` and `additionalProperties` false — not an array. Omitting a column
then violates the schema, so the model must return a verdict for each one; a
duplicated or invented column name is impossible for the same reason. `null` remains
a legal `ref_property`, because forcing a *verdict* must not become forcing a
*mapping* — that would be a worse failure than silence.

`ref_property` and `ref_class` are enum-constrained to terms drawn from the same
inventory the prompt renders, so the enum and the prose cannot disagree and a
hallucinated property is unrepresentable rather than caught afterwards (DD-170).

Provider limits, measured by bisection against the live endpoint: at most 1,000 enum
values *in total across one schema*, and `$defs`/`$ref` is required because inlining
the verdict per column exceeds a separate total-size limit at realistic widths. "In
total" is the trap — the class enum is emitted twice and every nullable enum carries
its own `null` — so the property enum takes what remains of a shared budget rather
than a fixed cap. An enum that does not fit is dropped and reported in the returned
notes, never silently.

`create_chat_completion` gains `param_fallbacks`: a model rejecting the strict schema
falls back to plain JSON mode instead of losing the constraint entirely.

### Consequences

Party-domain stability rose from 62-80% to **82-100%** across repeated three-run trials
(100%, 96%, 82% — the byte-identical trial was a favourable draw, not the expected
outcome). Recall improved at the same time, from a drifting 22-24 columns to 24-26.
Forcing a verdict per column recovers the ones the model used to drop.

This is the fix the seed could not be, but it is not determinism. Reruns of the same
configuration still differ, so a re-run may still change a model a human has reviewed;
what the schema removes is the *silent* form of that drift, where a column disappeared
from the answer entirely rather than being answered "no match". The seed and the stable
prompt remain necessary, because a stable question is what makes a stable answer
meaningful.

One confound worth recording: runs whose `--analysis` directory already contained a
previous run's output scored 82%, against 96% from pristine inputs. Prior output appears
to influence the next run, which is a separate thread to pull.

The response shape changes only how the answer is obtained. `normalize_schema_response`
converts the object back to the historical list of per-column dicts, so every consumer
downstream is untouched, and a list response — the JSON-mode fallback path — passes
through unchanged.

## DD-178: An AI-generated artifact states its own provenance and review status

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `propose-alignment`, `alignment-report`, any future model-authored artifact
**Implementation:** `core/_provenance.py` (`ai_attribution`, `ai_attribution_note`, `provenance_comment(ai_generated=...)`)

### Context

An ontology reads as authoritative — that is what one is for. So does a coverage
report with precise percentages in it. Neither carried any trace of the fact that a
language model proposed its content, or of which model, so a reader six months later
had no way to tell a machine proposal from a human decision, and no way to know what
would have to be re-run to reproduce it.

The run log has this information and nobody keeps run logs.

### Decision

Any artifact whose content a model proposed carries the model on its face. For Turtle
and YAML that is a `#`-comment block extending the existing DD-072 provenance header;
for Markdown reports it is a one-line note placed *above* the figures it qualifies.

`ai_attribution` records what a re-run would need — model, pipeline role, seed,
reasoning effort — omitting anything not set, so an artifact generated without a seed
does not claim one. The disclaimer names the artifact as a proposal for human review
and points at the decision log for recording acceptance.

The wording is about provenance and review status, not liability. The reader needs to
know which statements were machine-proposed and that a human has not necessarily
confirmed them; that is a claim the toolkit can actually stand behind.

### Consequences

Because seeding is best-effort at this prompt size (DD-177), the recorded settings are
an audit trail of what was *asked for*, not a promise the artifact can be reproduced
byte for byte. Recording them is still what makes a later divergence diagnosable
rather than mysterious.

Comment headers are inert in both formats — `rdflib` and `yaml.safe_load` ignore them
— and the header is idempotent, so regenerating never stacks. Deterministic generators
(`init`, `build-glossary`, `import-source`) are untouched and must never claim AI
assistance they did not use; a test pins that.

## DD-179: Alignment sees the table's role structure, and the mapping is checked as a set

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `propose-alignment`
**Implementation:** `core/propose_alignment.py` (`group_columns_by_role`, `format_role_structure`, `flag_role_collisions`)

### Context

The prompt presented source columns as a flat list, one line each, and asked for a
property per column. The reference-model side was already graph-shaped — DD-172 renders
`hasShipper (Organization) [OBJECT PROPERTY]` — but the source side was not, so the
strongest signal a flat table carries was left on the floor.

A flat table hides its relationships in its naming. `shipper_code`, `shipper_name`,
`consignee_code`, `consignee_name` is not four unrelated columns: it is two references
to the same kind of entity, in two different roles. That is exactly what distinguishes
`hasShipper` from `hasConsignee`, two object properties with the same range that no
amount of per-column name similarity can separate. Presented flat, the model had to
rediscover the structure on every call, and nothing prevented it mapping both roles
onto one property — a mistake that is individually defensible for each column and only
visible when the set is examined together.

### Decision

The prompt gains an `APPARENT ROLE STRUCTURE` block listing columns grouped by shared
leading token, with the rule that two different groups must not map to the same object
property. Separately, `flag_role_collisions` checks the finished mapping as a set and
records a `role-collision` flag on the table when two distinct roles do land on one
property.

Grouping is deliberately conservative, because a false group asserts a relationship the
data does not have. A group needs a shared leading token, at least two members, no more
than half the table (beyond that it is the table's *subject*, not a related entity),
no structural token like `is`/`created`/`total`, and at least one member that actually
identifies or names something (`code`, `name`, `id`, `key`, `ref`, …).

That last condition came from the corpus, not from theory: a prefix-only rule produced
`ActualDate`/`ActualTimeFrom` and `KmLoadingTotal`/`KmUnloadingTotal`, which share a
prefix for reasons unrelated to entity identity. With it, 98 of 150 source tables carry
a role structure, and they are the right ones — `origin(16)`/`destination(16)` on the
orders table, `pickup(8)`/`delivery(8)` on stops.

The guard flags and never blocks. Two roles legitimately share a property when the
reference model is deliberately coarser than the source, and that is a design decision
for a human, not an error to reject automatically.

### Consequences

Measured on the party domain, three parallel runs: recall rose from 24-25 columns to a
steady **28** (+15%), with stability at 93% — inside the 82-100% band established in
DD-177, and traded for materially more coverage on the axis that was weakest.

The guard immediately earned itself, firing identically on all three runs: the `company`
and `reference` roles both mapped to `partyIdentifier`. That is precisely the failure
this decision exists to surface — plausible per column, wrong as a set.

One honest cost: a single column mapped to different properties across runs, where
earlier configurations had shown zero such conflicts. More columns attempted means more
opportunity to disagree.

A table with no role group renders no block, so its prompt is byte-identical to before,
and `consistency_flags` is emitted only when a rule fires.

Declared relationships from Power BI semantic models (`import-tmdl` already parses 17 of
them across this hub's two models) remain unused. They are real relational evidence, but
the BI table names are the semantic model's, not the source tables' — wiring them in
needs a name-resolution step that this decision does not attempt.

## DD-180: An unanchored table is reported, gated, and told where its class lives

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `propose-alignment`, `alignment-report`, `compile`
**Implementation:** `core/alignment_report.py` (`UnanchoredTable`, `find_anchor_candidates`, `domain_imports`, `undecided_unanchored_tables`), `cli/compile.py`

### Context

Alignment anchors a table before mapping its columns: step 1 decides which reference
class the table *is*, step 2 maps each column to a property of that class. The anchor
is the frame. Without one, step 2 draws from the whole property pool with nothing to
constrain the choice.

Nothing reported when step 1 failed. The alignment file for an unanchored table looks
like any other, and every downstream consumer reads it as an ordinary result.

Testing a second domain is what exposed it. On `consignment`, run-to-run stability was
48% against `party`'s 93%, and the cause was not the model, the prompt or the settings
— all three had just been measured and improved. Split by anchor status it was
unambiguous:

| table | anchor | mapped per run | stability |
|---|---|---|---|
| `consignments` | Consignment | 26, 26, 24 | 67% |
| `shipments` | Shipment | 5, 3, 4 | 60% |
| `stops` | **none** | 26, 13, 8 | **30%** |
| `stops_table` | **none** | 23, 11, 16 | **44%** |

Both unanchored tables returned `unmatched` — the model was shown every class the
domain imports and declined to force-fit, which is the anchor contract working. It was
also right: the class those tables need is `TransportCall`, which exists in
`dcsa/transport-call#` and is imported by **`route-schedule`**, not `consignment`. 237
columns had no reachable home because of where a module was imported, not because of
anything a language model did.

An A/B on the same 122-column table ruled out the obvious alternative explanation: the
strict schema (DD-177) maps *more* under identical conditions (24/22 vs 16/11), varies
less, and uses half the output tokens. Width was not the problem either.

### Decision

`build_alignment_report` collects every table whose `ref_class` is empty or whose
status is `unmatched`/`rejected`, and for each one searches the *full* reference
vocabulary — not merely what the domain imports — for classes matching the table's name
and candidate entity, reporting which domain already imports each module.

That is the difference between "the model could not anchor `stops`" and "`TransportCall`
exists in `dcsa/transport-call#`, which `route-schedule` imports and `consignment` does
not". The first is an observation; the second is the fix.

Candidates rank by: a module some other domain imports first (a boundary mismatch is
both the likelier diagnosis and the cheaper fix, where an orphan module is usually
vocabulary coincidence), then token overlap, then fewest surplus tokens so
`TransportCall` outranks `BargeTransportCall`. Matching is blunt on purpose — the output
is a pointer for a human, not an automatic re-anchor, so a false suggestion costs a
moment's reading while a missed one costs a silent blind spot.

`compile` gates on it, before the DD-169 column gate: an unanchored table is the larger
omission, and listing a hundred homeless columns underneath one describes the symptom
while hiding the cause. Cleared by a table-grain disposition (DD-164), like any other
scope decision.

### Consequences

On the live hub this found **9 unanchored tables covering 306 columns**, across six
domains — only two of which were known. Every one names a candidate class and the
domain that already imports it, so each is a boundary decision rather than an
investigation: `compliance/resource_calendar_events` wants `events#` (imported by
`events`), `equipment/equipmentcode_fix` wants `onerecord/cargo#` (imported by
`booking`).

This is the mirror image of the defect that started this work. `Booking` appeared in
`party` where it did not belong; here `TransportCall` is absent from `consignment`
where it is needed. Same root cause — a mismatch between where affinity puts tables and
where the blueprint puts classes — and until now only the first direction was
detectable.

The wider lesson is about method, and is recorded here because it cost real time: every
conclusion in DD-174 through DD-179 was drawn from one domain of five narrow tables, and
the first different domain overturned the headline number. Single-domain measurement
sets a hypothesis; it does not settle one.

## DD-181: A declared cross-domain bridge makes a class anchorable, by default

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `propose-alignment`, `scaffold-domain`
**Implementation:** `core/analyse_sources.py` (`load_cross_domain_bridges`, `bridge_anchor_classes`), `core/propose_alignment.py` (`resolve_bridge_anchor_classes`, `_bridge_tag`)

### Context

A source table often holds rows of an entity its domain *references* rather than
*owns*. `stops` sits under `consignment`, but each row is a transport call — a
concept `route-schedule` owns. Offered only its home classes, the model has nothing
truthful to pick and correctly declines to anchor.

That is how 306 columns across nine tables ended up unanchored (DD-180), and the
only routes forward were both bad: import a module the domain has no business owning
(recreating the boundary erosion that DD-163 exists to catch, and that produced
`Booking` in `party` in the first place), or move the table to a domain that fits the
class but not the grain.

The blueprint already had the right mechanism and nothing read it for this purpose.
`cross_domain_relationships` declares exactly this — `source_domain` may reference
`range_class_uri`, owned by `target_domain`, through a named `property_uri` — and the
logistics pack ships 24 of them. The existing cross-module machinery is opt-in behind
`--cross-module --accelerator` and widens the *property* pool, not the anchor pool, so
a hub could declare a bridge and alignment would still not offer the class.

Reference-models v1.28.1 confirmed this is not a vocabulary problem: it added 663
resolved properties and **zero** classes, leaving all nine tables unanchored.

### Decision

Classes reachable through a bridge declared *from* a domain join that domain's anchor
candidate pool, tagged with the domain that owns them. Ownership does not move — the
tag is what lets the boundary check (DD-163) distinguish an authorised reference from
a redeclaration, and it tells the model in as many words that anchoring to the class
is allowed while minting a local copy is not.

**On by default, with no flag.** A bridge in the blueprint *is* the authorisation;
requiring a CLI flag to honour it would mean the default run ignores governance the
hub already expressed. Bridges load whenever a reference-models directory is present,
independently of `--cross-module`, and a test pins that ordering so the two cannot be
re-coupled by accident.

`load_cross_domain_bridges` returns bridges verbatim rather than filtering on
populated fields, because the scaffold header needs only `property_uri` while the
anchor pool needs `range_class_uri`. `cli/setup.py` now delegates to it, so a scaffold
header and an anchor pool cannot disagree about what the blueprint authorises.

### Consequences

On the live hub, `consignment`'s anchor pool goes from 25 to 33 classes —
`Invoice`, `TransportEvent`, `ServiceLoop`, `CustomsDeclaration` and four more, each
marked with its owner.

This supplies the mechanism, not the cure. **None of DD-180's nine tables is fixed by
the bridges that exist today**: no bridge declares `TransportCall`, and `compliance`
declares none at all. What changes is the shape of the remedy — a one-line blueprint
declaration that the toolkit then honours everywhere, instead of nine hand-added
imports that erode boundaries and trip DD-163. Landing the 306 columns needs, at
minimum, `consignment → route-schedule : TransportCall` (237 columns) and
`compliance → events : Event` (25).

A bridge is directional by construction: `booking → consignment` does not let
`consignment` anchor to `booking`'s classes.

## DD-182: Per-table vocabulary is a projection of the aggregate, not a second derivation

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `import-source`, source catalog, every downstream stage
**Implementation:** `core/import_source.py` (`split_vocabulary_by_table`)

### Context

`import-source` writes each table's Bronze vocabulary twice: into the source's
aggregate `<system>.vocabulary.ttl` and into `vocabulary/<table>.vocabulary.ttl`.
Both were derived independently from the parsed source schema, and they were
maintained by *different* update paths — the aggregate by an in-place merge that
syncs a fixed list of managed predicates, the per-table files by wholesale
regeneration.

Any enrichment added to the generator but not to the merge's sync list therefore
landed in one and never the other. `formatHint` did exactly that. On the live hub,
38 columns carried it in their per-table file and not in the aggregate.

The consequence was out of all proportion to the cause. The source catalog reads
both files, found the same `SourceTable` IRI with two different signatures, and
reported 75 conflicts — one per table. It could not decide which definition was
authoritative, so it refused to load, and `analyse-sources` aborted. Affinity,
alignment and everything after them were blocked by a missing format annotation.

### Decision

The per-table files are produced by `split_vocabulary_by_table`, which projects
each `bronze:SourceTable` and its columns out of the finished aggregate graph. They
are a view of the aggregate, not a parallel derivation from the schema.

Whatever the aggregate says about a table is, verbatim, what its per-table file
says — so divergence is impossible by construction rather than policed by a sync
list that must be remembered. The split carries no allow-list of its own; it copies
every triple on the table and its columns, which is what keeps a future enrichment
from reintroducing the same defect.

### Consequences

Adding `formatHint` to the merge's sync list would have unblocked the hub in one
line and left the class of bug intact — the next predicate added to one path and
not the other would repeat it. This closes the class.

The existing hub was already divergent, so the fix needed a re-import of all four
sources through the corrected path. Afterwards the catalog loads 75 tables with 0
conflicts.

The guard that caught this stays exactly as strict: a test tampers with a per-table
file and confirms the catalog still reports the conflict. The problem was never that
the guard was wrong — it was that two writers were allowed to disagree.

## DD-183: Affinity resolves the hub's accelerator instead of scanning the whole tree

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `analyse-sources`
**Implementation:** `cli/sources.py`

### Context

Affinity classifies each source table into a data domain. Given an accelerator it
uses the blueprint's governed domains; given none it falls back to globbing every
TTL under the reference-models tree and treating each directory group as a
candidate domain.

That fallback was never sound, and reference-models v1.28/1.29 made it obvious by
adding 80 TTL files. A run without `--accelerator` reported:

    📊 Resolved 274 domain(s) (12501 classes, 29089 properties)
       • Partnerships Ontology …  • ACTUS Challenge Examples Ontology …
       • 1.2.0 …  • current …  • deferred-relationship …

FIBO, ACTUS, the pattern library and version strings, offered as domains alongside
`party` and `financial`. 75 tables were classified against those 274 candidates,
and 8 of the 19 resulting domains — `shipment-journey`, `track-and-trace`,
`transport-order`, `revenue-yield`, `cost-accounting`, `vessel-registry`,
`container-operations`, `carbon` — are reference-model *module* names that no
blueprint domain owns.

What makes this dangerous is that the output looks entirely normal. The affinity
file has the same shape either way, and nothing downstream can tell a governed
domain from a scanned directory name. The same run with `--accelerator logistics`
produced 22 domains and assignments closely tracking the previous baseline
(financial 17→16, booking 11→7, consignment 4→5).

The hub already declares `[tool.kairos].accelerator = "logistics"` — the same
setting DD-181 reads for cross-domain bridges. Affinity simply never consulted it.

### Decision

When `--accelerator` is absent, `analyse-sources` resolves the hub's declared
accelerator through `resolve_hub_accelerator` (DD-125) — the shared path `validate`,
`project` and DD-181 already use — with any `--domains` filter as a hint. Inference
only fills a gap; an explicit flag is never overridden, and the output states which
of the two applied.

If nothing resolves, the fallback still runs but says plainly, on stderr, that
classification is against every ontology in the tree rather than the blueprint's
governed domains, and names both remedies.

### Consequences

This is the second defect of the same shape in one session: DD-181's bridge loader
also silently took the alphabetically-first accelerator pack when none was
resolved. Both produced plausible output from the wrong vocabulary. The pattern
worth naming is that a *default* which quietly widens scope is more dangerous than
one that fails — a failure gets investigated, a wrong-but-shaped-right answer gets
consumed.

The remaining exposure is that the fallback still exists. It is retained because a
hub with no accelerator is a legitimate configuration, but it is now loud rather
than silent.

## DD-184: LLM calls are traced to Langfuse, opt-in, with source values masked

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `propose-alignment`, `analyse-sources`, `discovery-conformance judge`
**Implementation:** `core/tracing.py`, `core/ai_provider.py` (`_openai_class`, `create_chat_completion`)

### Context

Three pipeline stages call a model, and the only durable record was a progress
line plus, on failure, a sanitized error. Diagnosing a questionable mapping meant
re-running the stage under a purpose-written instrumentation script — which is
exactly what it took to discover that `companies` was prompted twice, that its
first shortlist omitted `TradeParty`, and that the retry tripled the token cost.
That should not have required a bespoke harness.

### Decision

Tracing uses Langfuse's OpenAI drop-in wrapper rather than hand-rolled spans, so
model name, token usage and the `generation` observation type are captured
without the call sites knowing tracing exists. `_openai_class()` returns the
instrumented client when tracing is live and the plain one otherwise; nothing in
`create_chat_completion` branches on it beyond attaching `name`/`metadata`, which
only the wrapper accepts.

Calls are grouped by a per-invocation **session id** rather than a parent span.
Alignment fans out across threads, where a context-manager span does not reliably
parent concurrent work, and sessions are the SDK's documented mechanism for
grouping logically-connected traces.

Three properties are non-negotiable and each is pinned by test:

1. **Off unless configured.** All of `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`
   and `LANGFUSE_HOST` must be set. There is deliberately no default host, so a
   hub cannot ship traces anywhere by accident.
2. **Source values masked by default.** Alignment prompts carry real sample data
   from client tables. It already passes the `source-privacy` gate, but "not
   personal" is not "safe to send to a third party". The mask strips the
   `| samples: …` block and keeps column names, types, the reference classes
   offered, the instructions and the model's full response — nearly all the
   diagnostic value at none of the egress. `KAIROS_LANGFUSE_SEND_SAMPLES=1` opts
   in, which is reasonable for a self-hosted collector and a deliberate act
   either way.
3. **Never fails a run.** A missing package, an unreachable collector or a broken
   constructor logs at info level and continues untraced. Observability that can
   break a pipeline is worse than none.

An autouse fixture clears the Langfuse variables and the memoised client around
every test: tracing activates purely from the environment, so a developer with
real credentials in their shell would otherwise export fixture data to a live
project simply by running pytest.

### Consequences

Metadata carries what the earlier bespoke harness had to reconstruct — role,
table, source-column count, candidate-class count, resolved anchor override,
likely entity, and any dropped schema enum — plus the seed and reasoning effort
already recorded for provenance (DD-178). Filtering "every alignment call on a
table where the schema enum was dropped" becomes a query rather than a re-run.

`flush_tracing()` is called before `_propose_alignments` returns. These are
short-lived CLI processes; without it the buffered events are lost at exit and
the run appears never to have happened.

What this does **not** yet cover: the affinity and judgment stages get the traced
client for free through `get_ai_client`, but do not pass `trace_name`/
`trace_metadata`, so their calls arrive with default names and no role tag.

## DD-185: Tables are anchored globally, in one call, before per-table alignment

**Status:** Accepted
**Date:** 2026-08-17
**Affects:** `anchor-tables` (new), `propose-alignment`, `analyse-sources`
**Implementation:** `core/anchor_tables.py`, `cli/sources.py` (`anchor-tables`), `core/propose_alignment.py` (consumption)

### Context

The per-table pipeline decided a table's anchor from inside one domain's view:
affinity guessed the domain, a lexical shortlist picked twelve candidate classes,
the model chose among them. Measured failures: the shortlist ranked `TradeParty`
#24 for a table of companies (`Address` won on column overlap 44:20), ~40% of
tables needed a second 70KB full-inventory call, a plausible-but-wrong shortlist
anchor passed both retry thresholds silently, and affinity itself moved tables
between runs (`stops`: consignment → events on consecutive runs).

Anchoring is a grain question — *what is one row?* — and it wants the widest view
with the least detail. Brute force is arithmetically impossible (2,035 column
verdicts ≈ 163k output tokens in one response; the full property-detailed model is
~250k tokens per table). But every table's column names against a one-line-per-class
catalog fits in one ~35k-token call.

Tested on the live corpus before building: 6/6 on human-reviewed anchors (with
ownership marks; 5/6 without), honest nulls on metadata junk tables, zero invented
class names, and — against the hand-crafted cldn2 hub's nine bindings — 9/9 exact
grain-column matches as a secondary output. Sample values were tested and cost
accuracy here (5/6) and ~7k tokens: they stay in stage-2 mapping, where they are
proven, and out of anchoring.

### Decision

`anchor-tables` runs one global call (chunked above 150 tables): all tables'
column names × the full class catalog, each class marked with its owning blueprint
domain, plus the three anchoring-relevant pattern rules (role flags → neutral
party class; code-list tables; grain-of-one-row). Output is `table-anchors.yaml`:
anchor, alternate, confidence, derived domain, grain columns, natural key and load
hint per table, with DD-178 AI provenance. Every table is a required key in the
strict response schema (the DD-177 shape), so a table cannot be skipped; class
names are free strings — 1,275 candidates exceed the 1,000-value enum budget — and
are validated afterwards, invented names nulled with the evidence kept.

The domain is derived, not guessed: candidates are the domains owning any copy of
the anchor plus the domains bridging to it (DD-181), with affinity kept as a
tie-break *within* candidates. Bridge-awareness keeps a table in the bridging
domain instead of moving it to the owner — a move would trade an anchor gap for a
grain error. An anchor no domain can reach keeps its affinity domain and is
flagged `unowned`: the extension worklist, surfaced up front.

`propose-alignment` consumes the anchors through the existing uri-anchor-contract
override, with three guards: a human-confirmed alias always outranks the model's
anchor; nothing below `ANCHOR_CONFIDENCE_FLOOR` (0.6) is applied; and an anchor
outside the domain's pool (home + bridges) is reported, never silently applied.
Applied anchors are recorded as status `anchored` — never `confirmed`, which
means a human decided. The anchor and its status join the per-table cache key.

Column-level dispositions (DD-164) now feed the prompt: a column recorded as
`not-business-data` — including a system-wide `(system, "", column)` entry — is
excluded from the outline, so a SaaS tenant discriminator cannot become a grain or
key member. On the live run the model had keyed every qargo table on `tenant_id`
before the exclusion; zero after.

### Consequences

Live pilot on the hub: 72/75 tables anchored in one 54-second call, all five
session-confirmed anchors correct, six unowned-class flags, zero invented names.
Party alignment with anchors: three overrides applied, one refused as
outside-pool, one refused below the floor (0.18 — the honest `unmatched` beat a
bad pin), no full-inventory retries.

Two defects were found live and fixed: duplicate class names across modules
(ownership derived from an arbitrary copy put `consignments` in `commercial`; the
index now keeps every copy and aggregates), and the affinity reader using a field
name that does not exist (`primary_domain` vs `domain`).

Not yet done, in honest order: alignment still *groups* tables by affinity's
domains, so an anchor pointing outside that grouping is reported rather than
moving the table — regrouping by derived domain is the follow-up that makes
affinity fully derived. The binding-draft generator (assemble EntityBinding
skeletons from anchors + alignment) and the Langfuse golden-set evaluation are
deferred; the latter because the cldn2 golden set contains genuine modelling
disagreements (`shipments`: Shipment vs TransportMovement) that need human labels
before they can score anything.

## DD-186: The gap gate is drafted, grouped by domain-scoped family, and still decided by a human

**Status:** Accepted
**Date:** 2026-08-17
**Affects:** `draft-gap-decisions` (new), `source-disposition`, `alignment-report`, kairos-design-source
**Implementation:** `core/gap_decisions.py`, `cli/sources.py`, `core/source_disposition.py`

### Context

The DD-169 gate is correct and expensive: on the live hub 1,286 source columns
carry real signal with no canonical home, and none may reach entity binding
undecided. Reviewing 1,286 rows is not review, it is attrition — and attrition is
how a gate stops being read and starts being bypassed.

Three observations make it tractable:

1. Two reason codes were never judgment calls. `operational` (audit/system
   columns) and `vendor-slot` (`Column1`, `Field3`) are already classified
   deterministically by `classify_unmapped` before a human sees them.
2. The remainder collapses by name: the same `OrderNo` in nineteen tables is one
   decision, not nineteen.
3. It collapses again by family: `pickup_location_city`, `pickup_location_country`
   and eighteen siblings are one concept. Measured: 58 families covered 434 of 596
   undecided names.

### Decision

`draft-gap-decisions --auto` records the rule-decidable dispositions and nothing
else. `draft-gap-decisions` drafts everything remaining into `gap-decisions.yaml`
— one entry per family or single name, with occurrence counts, tables, types and
a proposed disposition where a rule applies — for a human to fill in and apply
with `--apply`, which fans one decision out to every column it covers.

**A family is a decision unit, so two constraints follow.** It cannot cross a
domain boundary: a disposition is domain-scoped, and the same column name can be
a modelled fact in one domain and a genuine gap in another. And a shared prefix is
not a shared concept — `is_approved`, `is_external_resource` and
`is_delivery_stop` share a token and are three unrelated booleans, the DD-179 trap
one level up. Structural and temporal prefixes are excluded, and a member must be
a *qualified* form of the token rather than the bare entity.

**`--suggest` adds one model call over the families**, filling `reasoning` and
`proposed_disposition` and flagging families whose members do not belong together.
The split of labour is deliberate: forming families is deterministic (free,
instant, reproducible, and already solved), while naming the concept a family
represents is judgement. The model never fills `decision`.

Nothing writes `blueprint-gap`, `deferred` or `registered-extension` on its own.
`blueprint-gap` in particular asserts *a reference-model defect to file upstream*
— it is not the neutral default, and the prompt says so; on the live corpus the
model proposed it zero times, choosing `deferred` (45) and `registered-extension`
(18) instead.

### Consequences

On the live hub: 224 columns auto-dispositioned, and the remaining 1,286 reduced
to **526 decisions** (63 families + 463 single names) — a 59% reduction, with the
63 families carrying a drafted concept description apiece ("*a supplier/vendor
billing-party snapshot with legal, tax, address and blocking/status
information*").

Building this surfaced a **pre-existing data-loss bug** in `record_disposition`:
its replace filter matched `(system, table)` and ignored the column, so every
column-grain write deleted the table's previously recorded columns. A run
recording 224 dispositions kept 37. The writer now matches the same
`(system, table, column)` grain `load_dispositions` already keyed on. This is the
argument for keeping the drafting deterministic in miniature — a silent
deterministic loss was recoverable by re-running; 596 plausible model judgments
would not have been.

The `--suggest` schema keys on `domain::family` because domain-scoping made the
bare token non-unique — caught by a provider 400 on the first live run.

## DD-187: Domain design runs as a fleet, and every refusal is recorded in the file it belongs to

**Status:** Accepted
**Date:** 2026-08-17
**Affects:** kairos-design-domain, kairos-flow autopilot leg 2, `validate` integrity warnings
**Evidence:** cldn-v5b hub, 13 domains authored in one parallel pass

### Context

Leg 2 turns alignment evidence into domain ontologies. On the live hub that is 22
domains, ~1,900 alignment proposals and an import closure of several thousand
reference terms. Authored serially by one context it is slow and, worse,
inconsistent: the standard applied to domain 1 has drifted by domain 13.

DD-088 already establishes design fleet mode — decisions AI-approved rather than
user-confirmed, with mandatory stop conditions. Leg 2 is the first use of it at
full width.

### Decision

**One agent per domain, one shared authoring contract, run in parallel.** The
contract fixes the order of work: resolve the import closure *before* writing,
read the anchors and alignment, author, refuse, validate, report. Every agent
gets the same two finished exemplars (`party`, `consignment`) as the house style,
not a prose description of it.

**Refusals are a first-class deliverable, written into the TTL itself.** Each
domain file ends with a numbered block naming every alignment proposal not
modelled and why. This is the load-bearing part of the decision. A refusal kept
in a report is detached from the model within one release; a refusal in the file
is read by the next person to open it, and survives the toolkit that produced it.
On the live hub this is 142 numbered refusals across 15 files — a larger artefact
than the 40 classes and 109 properties they accompany, and a more useful one.

**Refusing is the default when evidence and closure disagree.** Five refusal
classes are mandatory: out-of-closure parent terms, role-as-flag and
role-as-subclass, collisions (two source columns onto one reference property),
sub-0.60 confidence, and anchor/property disagreement. An empty domain is a
correct outcome — `customs` and `terminal-operations` are empty by decision, with
the reasoning recorded.

**`integrity.managed-import-unused` is reclassified as a sourcing signal, not
authoring debt.** A domain that imports a blueprint-mandated module and
references nothing from it is reporting that the blueprint's scope outran the
evidence. The warning must not be silenced by minting a term no source column
reaches. Every agent in the live run independently refused to game it.

### Consequences

Thirteen domains in one pass: 40 classes, 109 properties, all validating, with
**zero** out-of-closure parent terms, zero source-system names in `rdfs:comment`,
and no PII modelled while the GDPR hold stands. Consistency held across agents
because the contract, not the agent, carried the standard.

The unused-import count is now a readable backlog. Ten domains carry 42 such
warnings, and they concentrate exactly where sourcing is thin:
`terminal-operations` owns ~40 classes with zero source tables; `commercial`'s
entire contract-and-pricing scope has no evidence while its one table is a
packaging ledger; `equipment` owns reefers, chassis and swap bodies and is
sourced by a single spreadsheet export. This is the most valuable output of the
leg, and it is only legible because nothing was invented to hide it.

Running wide also made the toolkit's own defects visible by repetition rather
than by inspection — a per-class property enum gap in DD-177, alignment not
searching value-object subclasses, alignment files going stale against newer
imports, and several bad anchors. One agent finding these reads as noise;
several finding them independently reads as a defect list. See the hub's
`_analysis/leg2-findings.md`.

## DD-188: Ontology semantics live in the reference models, never in the toolkit

**Status:** Accepted
**Date:** 2026-08-17
**Affects:** every toolkit module that inspects a column name, a class name or a
property name — `propose_alignment`, `anchor_tables`, `class_anchoring`,
`gap_decisions`, `source_disposition`
**Supersedes in practice:** the hardcoded vocabularies listed under Consequences

### Context

The toolkit is a domain-agnostic engine. The reference models carry the domain
knowledge, and they are versioned, reviewed and shipped per accelerator pack —
`logistics` and `financial-services` today.

That separation has been leaking. `propose_alignment.py` alone hardcodes:

- **postal-address semantics** across seven constants (`_ADDRESS_PART_TOKENS`,
  `_ADDRESS_QUALIFIER_TOKENS`, `_ADDRESS_WEAK_TOKENS`, `_ADDRESS_CONTEXT_TOKENS`,
  `_ADDRESS_SUBDIVISION_TOKENS`, `_ADDRESS_PROPERTY_TOKENS`,
  `_ADDRESS_PART_TOKEN_KINDS`), including which tokens are "too weak" to be an
  address part without a qualifier;
- **finance semantics** (`_FINANCIAL_COLUMN_TOKENS`);
- **maritime semantics** — `_LOCATION_ROLE_PREFIXES = ("hasplaceof", "hasportof", "has")`.
  `hasportof` is DCSA vocabulary compiled into the engine.

The address vocabulary is also, specifically, *e-commerce* vocabulary: it knows
`billing`, `shipping`, `mailing`, `home`, `work` and `delivery`, but not
`pickup`, `origin` or `destination`. On the live logistics hub that asymmetry
alone was the whole defect — `delivery_location_city` clustered and
`pickup_location_city` did not, so one table's address detection covered 5 of 40
columns.

The obvious repair was to add the missing freight tokens. That is the wrong
repair: it compiles one industry's vocabulary deeper into a product that also
ships a financial-services pack, and it would have been the ninth such constant.

### Decision

**The toolkit must not encode ontology-level semantics — class names, property
names, or the token vocabularies that recognise them — unless a human explicitly
confirms that instance.** Structure is the toolkit's; meaning is the reference
models'.

The line: a rule that would still be true if the customer were a bank belongs in
the toolkit. A rule that names a concept — an address part, a port call, a
charge — does not.

The mechanism already exists and is already used. `core/pattern_loader.py` reads
`blueprints/patterns/<id>/pattern.yaml` from the reference models, and
`validator.py`, `conformance_judge.py`, `compiler/kernel.py` and `cli/sources.py`
consume it. Five patterns are externalised this way today: `temporal-quartet`,
`governed-code-list`, `qualified-role-assignment`, `deferred-relationship`,
`multimodal-order-leg`. Alignment is the stage that bypasses it and transcribes
the library into Python instead — its own comments admit as much
(*"Anchoring-relevant rules from the pattern library. Deliberately the small…"*,
*"Reference classes the pattern library marks as grain collisions"*).

New semantic knowledge therefore lands as pattern data, loaded per accelerator
pack. Not as a constant.

**The confirmed exception.** Some vocabulary is genuinely structural rather than
semantic — audit-column names, vendor placeholders, identifier shapes. Those may
stay, but each needs a comment saying why it is structural and not a concept, so
the next reader can tell a considered exception from an accreted one.

### Consequences

The following are now recorded as debt to be externalised, not extended: the
seven `_ADDRESS_*` vocabularies, `_FINANCIAL_COLUMN_TOKENS`, and `hasportof` in
`_LOCATION_ROLE_PREFIXES`. Adding a token to any of them is a decision that needs
this DD cited against it.

The immediate work this blocks and reshapes: the cross-domain projection detector
(toolkit issue on the alignment stage, reference-models issue for an
`entity-projection` pattern schema). The detection *logic* — cluster columns by
role prefix, require complementary part kinds, resolve the target class in the
domain's closure, emit an advisory candidate — is generic and stays. The
vocabulary that tells it what an address part is moves to the pack, so logistics
ships freight roles and financial-services ships its own.

The cost is a schema negotiation across two repos before code, rather than a
one-line frozenset edit. That is the point: a one-line edit is exactly how eight
of these arrived.


## DD-189: Sources are profiled deterministically before any model call

**Status:** Accepted
**Date:** 2026-08-19
**Affects:** `profile-sources` (new), `anchor-tables` (consumption), `kairos.yaml` (`data_maturity`)
**Implementation:** `core/profile_sources.py`, `cli/sources.py` (`profile-sources`), `core/anchor_tables.py` (outline annotation)

### Context

Anchoring and grain decisions leaned on column names and declared types — the
weakest evidence class. Measured on the qargo corpus (signal-first validation,
2026-08-19, experiment branch `experiment/signal-first-two-pass`): with
deterministic profile tags in the anchoring outline the model reproduced the
hand-confirmed grain on 9/9 golden tables; without them it keyed **every**
table on the SaaS tenant discriminator (0/9) — the same live DD-185 failure
that previously required a hand-maintained disposition-ledger exclusion.
Separately, 204 always-empty columns (~12% of the estate) and 178 constant
columns were feeding model context as pure name-bait, and two tables with no
sample evidence participated in semantic analysis indistinguishably from
populated ones.

### Decision

A new deterministic, LLM-free stage profiles raw `.import/` extracts
(Parquet/CSV) per system and writes `integration/sources/<system>/
<system>.profile.yaml`: per-column null/empty ratio (blank strings count),
cardinality (`unique` / `const` / `low-card(n)`), value shape (`id-like`,
`code-like`, `date-like`, `measure-like`, `free-text`, `json`), sampled
cross-table inclusion (`fk?->table.col` against proven-unique columns), and
table tags (`empty-table`, `versioned?`, `code-list?`). **Statistics only —
no data value is ever written**, which also means profile signal may reach a
model even where raw values must not.

Every artifact records its evidence **basis** (`import-extract(full)` now; a
later dataplatform re-profile writes `platform` and diffs as a release
verification gate — two-phase per the signal-first proposal §4.4).

`anchor-tables` consumes the profile automatically when present: outline
columns gain `[tag,…]` annotations plus a legend, and always-empty columns are
omitted from model context — **only** when the profile was computed under a
declared `data_maturity: production` (`kairos.yaml`, overridable per run).
Under `test`/unspecified maturity every tag is advisory and nothing is
excluded: absence of data in a test extract is not evidence of absence of
meaning. Exclusions are never silent — the artifact carries the counts and
consumers echo them. The annotated outline feeds the prompt only; anchor
resolution (`column_property_overlap`, copy choice) keeps raw column names so
tag text cannot pollute word matching.

### Consequences

Grain quality stops depending on a manually maintained tenant-discriminator
exclusion: `const`/`low-card` detection finds that column class from the data.
The `fk?` inclusion tags are new deterministic join evidence available to
relationship proposal (a tier-2 matcher where name equality fails — measured:
`goods.consignment_id ⊆ consignments.consignment_id` was known to profiling
while the name matcher returned `<CONFIRM_JOIN_COLUMN>`). Systems without a
profile are untouched — the stage is additive, not a new gate. Unsupported
extract types are listed as `not_profiled`, never silently skipped.

Full validation evidence: `experiments/signal-first/README.md` runs 1–9 on
the experiment branch (ablation, kernel-compile verification, convergence).


## DD-190: The anchors artifact is a reviewable design sheet with sticky human decisions

**Status:** Accepted
**Date:** 2026-08-19
**Affects:** `anchor-tables` (prompt, schema, artifact v2), `propose-alignment` (anchor application)
**Implementation:** `core/anchor_tables.py`, `core/propose_alignment.py` (`resolve_global_anchor`)

### Context

The global anchor call (DD-185) already decides the whole design skeleton's
hardest question — what each table IS — but returned only the anchor half.
Relationships, embedded secondary entities, and extension flags were
re-derived later, stage by stage, from partial views. And nothing an operator
decided survived a re-run: every `anchor-tables` invocation re-litigated
every table, so a human correction lasted exactly one pipeline pass.
Validated on the signal-first experiment corpus (runs 1–9): the same global
call also returns relationships at 0.95 recall against hand-authored FK sets,
id-keyed secondary entities, and 6/6 correct extension-candidate flags on
catalog-gap tables — and a sticky-status sheet converged to the human-ruled
answer on every contested table with collateral movement confined to
known-unstable rows.

### Decision

`table-anchors.yaml` (schema_version 2) grows into the **design sheet**:

1. **Three new per-table model outputs**, each validated deterministically
   after the call — the model proposes, the estate/catalog decide what is
   representable: `relationships` (`to_table` must exist in the estate and
   differ from the table itself; `local_column` must be a real column),
   `secondary_entities` (class must resolve in the catalog; grain must
   DIFFER from the primary grain — a same-grain cluster is properties of the
   primary, dropped and counted), and `flags` (closed set:
   `unowned-anchor`, `extension-candidate`, `code-list`, `no-data-evidence`,
   `versioned`). Every drop is counted and echoed, never silent.
2. **Sticky review statuses.** Entries carry `status` (`proposed` machine;
   `confirmed`/`edited` human — both pin; `rejected` re-anchors) and a
   `schema_hash` of the sorted raw column names. A pinned entry with an
   unchanged hash is preserved verbatim and **excluded from the model call**
   (true delta mode — re-runs cost only the unpinned tables). A pinned entry
   whose hash changed releases its pin to `stale-confirmed`: the fresh
   proposal is recorded, the human's values are kept under `previous` (or as
   the entry itself when the re-proposal is unanchored), and the row
   re-enters review. Stickiness is bounded by evidence identity — never by
   table name alone.
3. **A human decision is not a model score.** `propose-alignment` applies a
   `confirmed`/`edited` sheet anchor without the DD-185 confidence floor
   (`resolve_global_anchor`, status `sheet-confirmed`). An out-of-pool anchor
   is still never applied, human-confirmed or not: alignment has no
   properties to offer for a class outside the domain pool, and forcing it
   would produce exactly the plausible-empty mapping DD-159 exists to
   prevent.

### Consequences

One call now yields the full design skeleton — anchor, grain, identity,
relationships, secondary entities, flags — and review effort concentrates
where it belongs: an operator confirms rows once, and re-runs stop asking.
`fk?` profile evidence (DD-189) feeds the relationship output directly.
Secondary entities give binding generation its multi-entity worklist without
a separate discovery pass. The `previous` block on `stale-confirmed` entries
means a human decision can be superseded by schema drift but never silently
lost. Consumers of the v1 artifact are unaffected: all new fields are
additive, and entries without `status` behave exactly as before.


## DD-191: First-draft bindings are generated from the design sheet and validated before they exist

**Status:** Accepted
**Date:** 2026-08-19
**Affects:** `generate-bindings` (new)
**Implementation:** `core/generate_bindings.py`, `cli/sources.py` (`generate-bindings`)

### Context

DD-185 deferred "the binding-draft generator", and the gap shaped the whole
authoring economy: every binding was a hand-authoring session even when the
design sheet (DD-190), the alignment output, and the source profile (DD-189)
already contained every fact the draft needs. Validated on the signal-first
corpus: drafts assembled deterministically from those three artifacts passed
`compile --check` clean on four domains — after exactly two rules were
learned from kernel diagnostics (object properties must not be scalar
fields; property URIs must resolve in the anchor copy's own module).

### Decision

`generate-bindings` assembles one first-draft EntityBinding per anchored,
non-`rejected` sheet row that has a `propose-alignment` result — **zero model
calls**:

- `target.class` = the sheet's `anchor_uri` directly (reuse-first, DD-144;
  no local class is authored here);
- `fields:` from the alignment's scalar property mappings, resolved ONLY in
  the anchor copy's module inventory — an unresolvable property is a
  reported gap, never a cross-module guess; duplicate property claims keep
  the highest-confidence column and report the rest;
- object-property mappings and sheet-relationship columns become
  `technicalFields purpose: relationship` FK carriers (the DD-139 interim
  pattern `propose-relationships` upgrades as parents get bound);
- sheet grain/natural-key columns are materialized `purpose: identity`,
  typed from the profile (or the alignment's SQL type, normalized to the
  closed canonical enum);
- `quality:` tests only where the profile measured them (`unique`/
  `not-null` on the grain);
- every draft is validated through the compiler's own `load_entity_binding`
  **before** writing — an invalid draft is reported and never lands on disk;
- an existing binding is never overwritten without `--force`; review is the
  git diff, per the scaffold-binding convention.

Secondary entities from the sheet are echoed as a worklist (separate
bindings at their own grain), never auto-generated. Everything generation
cannot decide is on the report: unresolved properties, dropped duplicate
claims, skipped tables.

### Consequences

The mechanical majority of bindings becomes generate → review-diff → confirm,
and hand-authoring (kairos-design-mapping) concentrates on what genuinely
needs judgment: merges, survivorship, grain changes, conformance groups.
`scaffold-binding` remains the single-table archetype path; this is the
sheet-driven batch path. The generated draft is deliberately conservative —
`full-refresh`, FK carriers instead of authored joins — so nothing a human
did not confirm ever reaches execution semantics silently.


## DD-192: Human design rulings are durable, transferable, and outrank model judgment

**Status:** Accepted
**Date:** 2026-08-19
**Affects:** `anchor-tables` (prompt + provenance), `integration/discovery/design-rulings.yaml` (new authored input)
**Implementation:** `core/design_rulings.py`, `core/anchor_tables.py`

### Context

The measured blind spot no detector closes: a well-fitting wrong sibling.
`shipments` anchored to `Shipment` maps enough properties to pass every
absolute check while the defensible answers sit one sibling over — three
hand-crafted artifacts gave three different answers. Only a human resolves
this, and before this DD the resolution lived in one conversation: the next
re-run, the next table with the same shape, and the next hub all re-litigated
it. DD-190's `confirmed` status pins one *table*; the ambiguity is a *rule*.

### Decision

`integration/discovery/design-rulings.yaml` is a third authored evidence
input, peer to business discovery and source vocabularies. One entry per
resolution: `kind` (`disambiguation` | `rejection` | `preference`), a `scope`
with `class_pair` and an **`applies_when` condition in data terms**, the
`ruling` target, `rationale`, and `decided_by`.

`anchor-tables` renders the applicable rulings into the global prompt as
accumulated human authority ("these OUTRANK your own reading of the catalog;
apply each ruling wherever its condition matches, and never re-litigate it")
and records `rulings_applied` in the artifact for provenance. Validated live:
the ruled table converged to the ruled answer at 0.91–0.95 with the rejected
candidate kept as alternate, and collateral movement confined to
already-unstable rows — the ruling applies **by condition, not by table
name**, which is what makes it transferable to future tables and hubs.

Three boundaries keep this from becoming a shadow ontology:

1. **Always human-decided.** An entry whose `decided_by` is not `user` is
   inert and reported — a model may propose a ruling, an unconfirmed
   proposal feeds nothing.
2. **A ruling never introduces a class.** A `disambiguation`/`preference`
   whose target the catalog cannot resolve is skipped and reported (it would
   steer the model toward a name post-validation must null). `rejection`
   rulings name a class to avoid and need no resolution.
3. **A ruling never maps columns.** Column-level decisions stay in
   alignment/bindings.

An absent file is a silent no-op. Skipped entries are echoed with reasons,
never dropped silently.

### Consequences

Contested-space resolutions are decided once and never re-litigated — per
table, per run, and (via the condition) per future hub. A disambiguation
ruling that recurs across hubs is a measured candidate for the shared
reference-models pattern library (the #262 harvesting route): the blind spot
becomes the mechanism by which the blueprint itself learns, with recorded,
evidenced rulings instead of anecdote. The `applies_when` conditions are
prose interpreted by the model, not predicates evaluated by code — which is
why `rulings_applied` provenance and the skipped-with-reason echo exist, and
why pattern-library promotion stays a human review, never automatic.


## DD-193: The profiling class catalog is scoped to the resolved accelerator

**Status:** Accepted
**Date:** 2026-08-19
**Affects:** `read_reference_terms` (new `module_scope` parameter), `build_class_catalog`
**Implementation:** `core/class_anchoring.py`, `core/anchor_tables.py`
**Issue:** #558

### Context

`read_reference_terms` seeded the anchoring class catalog from every module
URI the whole installed `kairos-ontology-referencemodels` package maps in the
catalog — not the modules the active accelerator pack actually declares. On a
logistics profiling run this put ~400 FIBO classes (`Contract`,
`LegalEntity`, `Organization`, …) in front of the model as `UNOWNED` anchor
candidates, alongside OMG Commons/LCC and every other vendor's models,
regardless of whether any logistics domain has ever imported them. Beyond
prompt bloat, the anchoring prompt's own fallback rule ("pick an UNOWNED
class only when no owned class fits") means a genuinely unrelated vendor
class could win a table that should have been flagged for review instead.

### Decision

`read_reference_terms` gains an optional `module_scope` parameter: when
given, only modules in the scope seed the walk. Each seed's own
`owl:imports` closure still resolves in full through the canonical loader
(unchanged) — scoping narrows *which modules seed the walk*, not how far one
seed's closure reaches, so a foundation module reached only via import from
an accelerator-declared module stays visible. `None` (the default) keeps
today's unrestricted behaviour; every existing caller (`alignment_report`,
`domain_coverage`, `ontology_integrity`, DD-165's local-class suggestion) is
unaffected.

`build_class_catalog` is the one caller that opts in: when an accelerator
resolves, the seed set is exactly the union of that accelerator's own
declared domain imports (`load_data_domains`'s `uris`) — the same set the
function already computes for ownership marks. A module the accelerator
never reaches, directly or transitively, is excluded from the catalog
outright rather than merely marked `UNOWNED`. An accelerator name that fails
to resolve (`load_data_domains` returns nothing) keeps the unrestricted
legacy behaviour rather than silently emptying the catalog — a scoping bug
must never look like "the accelerator has zero classes."

### Consequences

A module reachable only via a *different* accelerator's own domain (FIBO for
a future `financial-services` pack) is now invisible to a logistics
profiling run, which is the fix working as intended. The corollary the issue
also names: a module reachable **only** by explicit import from within the
accelerator's own package (IATA `onerecord.iata.org/ns/code-lists`, not
today transitively imported by the accelerator's declared `.../ns/cargo`
module) becomes invisible too, until that package adds the import — a data
change in the separate `kairos-ontology-referencemodels` repository, out of
this repository's scope, tracked on #558. Until it lands, code-list classes
like `ChargeCode`/`CurrencyCode` will not appear as anchor candidates for
logistics hubs; this is the honest state (a real accelerator gap, surfaced),
not a regression the scoping fix should paper over.

Also out of scope here, and left to the issue for a follow-up decision: a
`kairos.yaml` field making the accelerator a hub-level declared setting
rather than resolved from `pyproject.toml`/CLI/inference. That is a new
config-surface question, not a scoping bug, and wants its own decision.

## DD-194: Temporal columns are excluded from profiling key-set candidacy

**Status:** Accepted
**Date:** 2026-08-19
**Affects:** `core/profile_sources.py` (`profile_table`)
**Found on:** frachtv5 (real CargoWise extracts) — the first hub run of `profile-sources` against a corpus DD-189 was never built or tested against.

### Context

A unique, timezone-aware timestamp column crashed `profile-sources` outright:
`arr.drop_null().to_pylist()` on a tz-aware Arrow timestamp needs a tz
database, which a bare Windows Python install does not ship (`ArrowInvalid:
The zoneinfo module or pytz package must be installed`) unless the `tzdata`
package happens to be present. The column had qualified for key-set
construction only because it was tagged `unique` — the same path any
identifier column takes.

### Decision

`profile_table` excludes temporal-typed columns from key-set construction
outright (`not pa.types.is_temporal(arr.type)`), not merely by handling the
conversion error. Two independent reasons, either sufficient alone:
containment-matching a timestamp value against another table's timestamp
column is never a meaningful join signal the way an identifier's is, and the
crash is real on a platform without a tz database regardless. The column
still gets its `unique`/`date-like` tags (unaffected) — only key-set
candidacy is excluded.

### Consequences

`profile-sources` no longer depends on the host having a timezone database
for hubs whose sources carry timezone-aware timestamps (CargoWise does).
No behavioural change for identifier columns — the fix narrows an
over-broad candidacy check, not the join-evidence mechanism itself.

---

## DD-195: The scaffold offers every extra the toolkit ships, including langfuse

**Status:** Accepted
**Date:** 2026-08-19
**Affects:** `scaffold/pyproject.toml.template`
**Issue:** #563

### Context

DD-184 added the toolkit's own `langfuse` extra (`langfuse>=4.14.0,<5.0.0`),
which `core/tracing.py` depends on directly. The scaffold template that
generates a client hub's own `pyproject.toml` (`new-repo`/`init`) was never
updated to pass it through — a hub carrying real Langfuse credentials in
`.env` had no way to `uv sync --extra langfuse` at all, and tracing would
silently no-op (its own "off unless configured" path masks a missing
dependency identically to a deliberately-disabled one). Found on a real
client hub (frachtv5, 2026-08-19).

### Decision

Add `langfuse = ["kairos-ontology-toolkit[langfuse]"]` to the scaffold
template, in the same bare-requirement shape as every sibling extra
(`azure`, `foundry`, `flatfile`, `parquet`, `otel` — no repeated wheel URL,
per issue #297).

### Consequences

A freshly scaffolded hub can install Langfuse tracing support the same way
it installs any other extra. `tests/test_packaging_extras.py` and
`tests/test_scaffold_toolkit_pin.py`'s `USER_FACING_EXTRAS` widened to
match — which also exercises, for free, the existing guard that the
toolkit's own `pyproject.toml` actually ships every scaffolded extra.

---

## DD-196: Archived reference-model snapshots are excluded from resolution unconditionally

**Status:** Accepted
**Date:** 2026-08-19
**Affects:** `analyse_sources.resolve_reference_models` (and every caller, incl. `coverage_report.run_coverage_report`)
**Issue:** #566 (supersedes kairos-ontology-referencemodels#108, closed as not a referencemodels defect)

### Context

`coverage-report` produced a resolver warning listing 53 property-domain
assertions across 14 modules that "could not be attached to any class" —
filed initially against the reference-models repo (#108) under the
assumption the live `.ttl` files were missing `owl:imports`. That
assumption was wrong: every one of the 53 traces to a file under
`derived-ontologies/<vendor>/archive/<old-version>/...`, never `current/`.
The live files already declare the correct imports (added by
referencemodels commit `a449ab2`, v1.32.0); the archived snapshots
legitimately predate that fix, by that repo's own documented
archive-before-fix convention. Because an archived file shares its live
module's permanent IRI, `_warn_unattached_property_domains`'s bucketing by
module lumped the resolved, historical defect onto the live module's label.

`resolve_reference_models` already accepted an `exclude_patterns` parameter
for exactly this class of exclusion, but no default existed and
`run_coverage_report` never supplied one — so the coverage-report path
walked `archive/**` unconditionally. The reference-models repo's own
equivalent structural check (`scripts/validate_structure.py` check 10)
already skips any path with an `archive` segment, unconditionally, for the
identical reason — this toolkit's resolver was the one place that hadn't
caught up.

### Decision

`resolve_reference_models` now excludes any TTL whose path (relative to
the resolution root) contains an `archive` segment, unconditionally —
before caller-supplied `exclude_patterns` even run, and with no way to opt
back in. Matched on a literal path segment (`"archive" in
path.relative_to(root).parts`), not a glob, so it is robust regardless of
vendor folder layout.

### Consequences

Every caller of `resolve_reference_models` (`coverage_report.py` and any
future caller) is fixed at once, not just the one call site that surfaced
the bug. An archived TTL can never again masquerade as evidence of a live
defect. `kairos-ontology-referencemodels#108` closes as not a defect in
that repo.

---

## DD-197: --max-workers gets a hub-level default, in the same place accelerator and channel already live

**Status:** Accepted
**Date:** 2026-08-19
**Affects:** `cli/shared.py` (`_read_hub_max_workers`), `cli/sources.py` (`analyse-sources`, `propose-alignment`)
**Issue:** #562 (Problem 1)

### Context

`analyse-sources` and `propose-alignment` both expose `--max-workers`,
bounding the per-table LLM call thread pool. Fine as a one-off flag, but a
hub had no way to set its own default once — every invocation needed the
flag retyped, unlike `accelerator` and `channel`, which already live in
`[tool.kairos]` in the hub's `pyproject.toml` with an explicit-flag >
hub-config > default precedence.

### Decision

New `_read_hub_max_workers(hub_root)` reads `[tool.kairos].max_workers`
with the same dual-candidate lookup `resolve_hub_accelerator_detailed`
(DD-125) already uses (`hub_root/pyproject.toml` then
`hub_root.parent/pyproject.toml`). Both CLI options change their default
from a hardcoded `16` to `None`, resolved as: explicit `--max-workers` >
`[tool.kairos].max_workers` > `_CLI_DEFAULT_MAX_WORKERS` (16, unchanged).
A present but invalid value (non-integer, boolean, zero, or negative) is a
configuration error and raises — unlike an absent key, a wrong one must
not look like "not set".

### Consequences

A hub can now set its own concurrency default once. Honest, pre-existing
gap this does not fix, named rather than hidden: `core/_concurrency.py`'s
own `DEFAULT_MAX_WORKERS = 8` (the library default for direct callers
bypassing the CLI) has always been unreachable for CLI users, since both
commands already hardcoded `16` before this change — that split stays as
it was; this DD only adds a config-level override on top of the existing
CLI default.

---

## DD-198: AI preflight surfaces a missing SDK as a missing dependency, with a uv-native fix, not as network unreachability

**Status:** Accepted
**Date:** 2026-08-20
**Affects:** `_create_foundry_client`, `_resolve_azure` (`core/ai_provider.py`); `_probe_client`, `preflight_ai_provider`, `AIRolePreflight.is_blocking` (`core/ai_preflight.py`); `check_ai_config_cmd` (`cli/inspection.py`)
**Implementation:** `core/ai_provider.py`, `core/ai_preflight.py`, `cli/inspection.py`, `scaffold/.env.example`
**Issue:** #553

### Context

Two separate problems compounded on hubs missing an optional AI-provider
SDK. First, the remediation text at all three `NotConfigured` raise sites
(Foundry's missing `azure-ai-projects` package, ×2, and Azure's missing
`azure-identity` package) told the operator to `pip install
kairos-ontology-toolkit[foundry/azure]` — the wrong tool for a project this
toolkit itself scaffolds and manages with `uv`. Second, and worse,
`ai_preflight.py`'s `_probe_client` caught that same `NotConfigured`
exception under a generic `except Exception` and rewrapped it as
`Unreachable`, so `check-ai-config` reported a missing SDK as
`STATUS_UNREACHABLE` with a "verify network connectivity" remediation —
actively misleading, since no network call was ever attempted, and burying
the real install hint inside the wrapped error's text instead of surfacing
it as the reported remediation.

### Decision

`core/ai_provider.py` gains a module-local `_extra_install_hint(extra: str)
-> str` returning `f"uv sync --extra {extra}"`, used at all three
`NotConfigured` raise sites in place of the `pip install` text.
`scaffold/.env.example` (and its committed root-repo copy) get the same
uv-native wording in their Azure/Foundry install comments, so a scaffolded
hub's own reference file matches what the CLI itself now says.

`_probe_client` lets `NotConfigured` propagate unchanged instead of
catching it as a generic `Exception`. `preflight_ai_provider` gains a new
`except NotConfigured` branch, ordered before the existing `except
Unreachable`, that reports a new `STATUS_MISSING_DEPENDENCY` status with
`remediation` set directly from the exception's own message — the same
uv-native hint the exception already carries, not a second copy of it.
`STATUS_MISSING_DEPENDENCY` is added to `AIRolePreflight.is_blocking`
alongside the existing blocking statuses, and to `cli/inspection.py`'s
`_STATUS_ICONS` table so `check-ai-config`'s text and JSON output both
render it distinctly from `not_configured`/`unreachable`.

Scope is deliberately limited to the three AI-provider call sites. The
`[flatfile]`/`[parquet]` extras' own `pip install` remediation text
(`field_mapping_report.py`, `import_flatfile.py`) is a different subsystem
with no reported bug and is left untouched, rather than pulled in as
unrelated scope creep.

### Consequences

`check-ai-config --probe` against a hub with the AI provider configured
but the matching SDK not installed now reports `missing_dependency` with
the exact `uv sync --extra ...` command to run, and no longer suggests
checking network connectivity for what is actually a local dependency gap.
No command (`init`, `new-repo`, `update --upgrade`) auto-installs the
matching extra during hub setup — that stretch goal from the issue's own
wording stays a "consider," not implemented here.

---

## DD-199: Per-PR CI only gates on the PR's own diff; global-state checks move to a schedule

**Status:** Accepted
**Date:** 2026-08-20
**Affects:** `.github/workflows/ci.yml`, `.github/workflows/dependency-audit.yml`, new `.github/workflows/refmodels-pin.yml`

### Context

Four sibling PRs (#567–#570), all forked from the same `main` commit, sat
open at the same time. While they were open, `kairos-ontology-referencemodels`
published v1.35.2. The `refmodels-pin` job in `ci.yml` ran on every PR and
checks the release feed against the pin at run time, not the PR's own
diff — so all four PRs failed the identical check simultaneously, for a
reason none of their authors could have prevented by changing their PR, and
each needed a follow-up commit before it could merge. A per-PR gate that
fails on external state a contributor cannot control by editing their PR is
a false signal: it looks like "your PR broke something" when nothing in the
PR caused it.

`Analyze (actions)`/`Analyze (python)` (CodeQL, via the repo's code-scanning
default setup) is the slowest job on every PR and, like `refmodels-pin`,
tests the whole codebase rather than the diff — appropriate for a periodic
sweep, not for gating merge on every change.

### Decision

Per-PR CI (`ci.yml`'s `test` job, `check-version`) stays as the only
required gate — both are fast and both are actually about the PR's own
diff. Everything that tests state independent of the diff moves off the
per-PR path:

- `refmodels-pin` is removed from `ci.yml` entirely and reimplemented as a
  new scheduled workflow (`refmodels-pin.yml`, daily): on drift, it updates
  the pin, re-locks, runs the full suite against the new bundle, and opens
  a `chore/refmodels-pin-<version>` PR automatically — the busywork of
  bumping the pin no longer falls on whichever PR happens to be open when
  upstream ships a release.
- `pip-audit` (`dependency-audit.yml`) stays on every PR for visibility
  (a newly disclosed CVE is worth seeing) but is non-blocking there
  (`continue-on-error` when `github.event_name == 'pull_request'`); it
  stays blocking on push-to-main and its existing weekly schedule, so a
  real vulnerability is still enforced before it reaches a release.
- CodeQL's per-PR analysis is a repo-level code-scanning **default setup**
  setting (Settings → Code security → Code scanning), not a workflow file
  in this repo, and changing it requires repo-admin access this change did
  not have — left as a follow-up for whoever holds that access: switch the
  default setup's trigger from every-PR to its existing weekly schedule (or
  to an advanced-setup workflow scoped to `schedule` + release tags).

### Consequences

A PR's CI status now reflects only things that PR actually did. Reference-
models pin drift is caught and fixed automatically, same-day, without
touching whatever unrelated PRs happen to be open — it will never again
require four simultaneous rebase-and-bump commits for one upstream release.
A real dependency CVE is visible on every PR (not silently hidden) but
no longer blocks an unrelated PR's merge; it still blocks `main` and the
weekly audit. CodeQL's per-PR gating is unchanged until someone with repo
admin access applies the follow-up above.

---

## DD-200: `update --upgrade` also upgrades reference models, resolved the same way scaffolding is

**Status:** Accepted
**Date:** 2026-08-20
**Affects:** `_resolve_refmodels_tag` (new, `cli/shared.py`), `_upgrade_refmodels` (new, `cli/operations.py`), `update_refmodels` (`update-refmodels` command), `update --upgrade`
**Issue:** #551

### Context

`update-refmodels` (no `--version`) ran `uv pip install --upgrade
kairos-ontology-referencemodels` and reported whatever
`importlib.metadata.version()` returned afterward as the new pin. Reference
models ship only as a GitHub Release wheel (DD-158), never to a package
index — there is no `kairos-ontology-referencemodels` for `uv pip install
--upgrade` to find there, so the install silently did nothing while the
command still printed success. This is exactly how a real hub's pin sat
thirteen minor versions behind (#541): the command that exists to fix pin
drift could not actually move the pin forward at all.

A second, independent bug in the same command: with an explicit
`--version`, the tag was written into the pin/wheel URL verbatim, without
the `v`-prefix normalization `_resolve_scaffold_refmodels_pin` already
applies (`1.33.1` and `v1.33.1` name the same release, but only the latter
is a valid tag/URL segment) — an unprefixed `--version` produced a 404 pin.

A third gap, this time in `update --upgrade`: it only ever rewrote the
toolkit pin. Reference models drifted independently, with nothing in this
command's own path to catch it — the same pin-drift class as #541, just
without even a broken command to run against it.

### Decision

New `_resolve_refmodels_tag(version_tag)` in `cli/shared.py` resolves the
tag an upgrade should install: with no `version_tag`, the latest published
**stable** release via the same draft-filtering, version-ordered resolver
(`_list_published_release_tags` / `_latest_stable_tag`) every other caller
already uses — a fourth caller of one policy, not a second reimplementation
(the mistake #542 was). With an explicit `version_tag`, normalizes a bare
version to the `v`-prefixed form. Unlike the scaffold-time resolver, there
is **no fallback to a hardcoded tag** when the release list can't be
fetched: scaffolding with no evidence still needs something to pin, but an
upgrade is protecting an existing, working pin — refusing (`None`) is
correct, not silently reusing a stale hardcoded tag.

`update_refmodels`'s whole body is extracted into `_upgrade_refmodels(version_tag) -> str`
in `operations.py`, reusable by both the standalone command and `update
--upgrade`. It always installs the exact wheel URL for the resolved tag —
the pip-index path is gone entirely, so `importlib.metadata.version()` can
no longer diverge from what was actually resolved, and the pin written to
`pyproject.toml` is always the normalized tag.

`update --upgrade` gains a new step, right after the toolkit pin is
upgraded: if the hub's `pyproject.toml` declares a
`kairos-ontology-referencemodels` dependency at all (a dataplatform repo
never does, and is skipped), it calls `_upgrade_refmodels(None)`. A failure
there is caught and reported by name — "Toolkit upgraded to X, but
reference models upgrade failed: ...; run `kairos-ontology
update-refmodels` to retry" — and exits 1, rather than leaving the hub on a
new toolkit with a silently stale reference-models pin. This is
deliberately **not** wrapped in the existing `_dependency_files_transaction`
helper: the toolkit half of `--upgrade` was never transactional either, so
this matches existing behavior rather than inventing an uneven new
guarantee for only one half of the command.

### Consequences

`update-refmodels` (with or without `--version`) now always installs the
exact release it reports installing, and a bare `--version` no longer
produces a 404 pin. `update --upgrade` on a hub that pins reference models
upgrades both in one run; a refmodels-side failure is named and non-zero,
never silent. A hub whose `pyproject.toml` has no refmodels dependency
(dataplatform repos) is entirely unaffected — the new step is a no-op for
them, not a new failure mode.

---

## DD-201: A cross-domain class-name collision is resolved by richness, and the resolution travels downstream as a URI

**Status:** Accepted
**Date:** 2026-08-20
**Affects:** `choose_class_copy`, `ALLOWED_SHEET_FLAGS`/`PROPERTY_LESS_ANCHOR_FLAG`, `run_anchor_tables` (`core/anchor_tables.py`); `_process_table`, `TableAlignment.likely_entity_uri` (`core/propose_alignment.py`); `_resolve_alignment_class` (`core/design_landscape.py`)
**Issue:** #564

### Context

`choose_class_copy` hard-partitioned candidate copies of a colliding class
name into tiers — same-domain-owned, then any-domain-owned, then all —
*before* any richness scoring ran. When a name collided across copies owned
by two DIFFERENT domains (a bare IATA `Person` owned only by `party`, a
richer BSP `Person` owned only by `financial`), the hard filter discarded
the richer copy the moment the *other* domain happened to own it — the
domain a table's own catalog-read-order landed on decided the outcome,
never richness. This is the same "read order decides" defect class #519
already fixed one level up (which copy a *single* domain's own duplicate
resolves to); #564 is the sibling case one level further out.

Separately: the newer DD-185/190 global-anchor path already disambiguates
a table's class via `choose_class_copy` and records the resolved
`anchor_uri` in `table-anchors.yaml` — but `propose_alignment.py` never
carried that URI forward into `TableAlignment.likely_entity_uri`, even
though both of `likely_entity_uri`'s existing consumers
(`design_landscape._resolve_alignment_class`, `conformance_evidence.py`)
already prefer it over the bare `ref_class` local name when present. The
uri-anchor-contract's own "confirmed" path populated it; the global-anchor
path silently didn't, so a URI the toolkit had already resolved never
reached the consumers built to use it — producing exactly the "ambiguous
local name, skipped" gaps `design_landscape` reported on real data (12
tables on one hub run).

### Decision

`choose_class_copy` keeps only one tier — owned by *any* domain, over
unowned — ahead of scoring. Same-domain ownership moves from a hard
pre-filter into the last key of the ranking tuple, after column-property
overlap and property count: richness now always gets to compete, and
same-domain ownership only breaks a genuine tie. A deterministic (never
model-proposed) `property-less-anchor` sheet flag is added to a table's
`table-anchors.yaml` entry whenever its resolved anchor has zero
properties — the same condition that already produced a console-only
warning, now surviving into the reviewable artifact.

`_process_table` threads the global-anchor path's resolved `anchor_uri`
through its returned dict (`global_anchor_uri`) whenever that path applied
an override; the table-assembly step populates `likely_entity_uri` from it
when the uri-anchor-contract path didn't already set one. `design_landscape.py`
additionally gains a defensive fallback for hubs whose `*-alignment.yaml`
predates this fix (no `likely_entity_uri` recorded at all): when a
`ref_class` local name is ambiguous, it reads `table-anchors.yaml` directly
and uses that table's own `anchor_uri` — but *only* when the sheet's
`anchor` name matches the alignment's `ref_class` exactly, so a stale or
mismatched sheet entry can never silently substitute a different class
than the one the alignment artifact itself names.

### Consequences

A name collision across two different domains' modules is now resolved the
same way a same-domain collision already was: by richness first, ownership
only as a tie-break. Every future consumer of `likely_entity_uri` benefits
from the global-anchor path's disambiguation, not just the older
uri-anchor-contract path. `design_landscape` can now resolve some
previously-ambiguous `ref_class` entries even against an already-generated,
stale alignment artifact — narrowing, though not eliminating, the
"ambiguous local name, skipped" gap class; a table whose sheet anchor name
doesn't match its alignment's `ref_class` still correctly reports the gap
rather than guessing.
