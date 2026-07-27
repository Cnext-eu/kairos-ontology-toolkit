# Historical: Kairos 4.7 Medallion Projector Rules

> **Frozen v4.7 record.** Claims, authored preparation/Silver policy,
> lifecycle/readiness/release evidence, and their commands were retired by the v5 DD-133
> clean break. The rules below are preserved for provenance and are not active v5 guidance.
> Use the [v5 data-engineer methodology](data-engineer-methodology-guide.md).

**Status:** Consolidated toolkit rules
**Version:** 1.0
**Date:** 2026-07-25
**Scope:** Fresh Kairos ontology hubs
**Target platforms:** Microsoft Fabric and Azure Databricks

## 1. Authority and evidence

1. Authority is ordered as follows:
   1. accepted design decisions and versioned policy profiles;
   2. governed ontologies, claims, mappings, extensions, preparation policies, and
      contracts;
   3. approved, scope-limited deviations;
   4. implementation capability evidence; and
   5. generated artifacts.
2. Implementation must never override policy.
3. Every effective configuration value must identify whether it is authored, inherited,
   defaulted, or deviated.
4. Unsupported or partial behavior must fail or be recorded as an approved deviation. It
   must never silently degrade.
5. Normative policy, generated capability evidence, and observed runtime results must
   remain separate.
6. The toolkit may generate executable checks and import their result contracts. Operating
   monitoring, alerting, and trend storage remains a platform responsibility.

## 2. Layer responsibilities

| Layer | Owns | Must not own |
|---|---|---|
| Raw Bronze | Replayable source values, raw schema, source PK, CDC, and ingestion evidence | Cleanup, semantic conformance, cross-source identity |
| Preparation/staging | Source-specific names, types, sentinels, JSON expansion, normalized CDC inputs, and source-record keys | Independent-source joins, aggregation, business classification, survivorship, cross-source equivalence |
| Mapping | Source-column to domain-property alignment and constrained typed scalar expressions | Arbitrary SQL, joins, windows, aggregation, or grain changes |
| Contracted dbt | Governed relational and grain-forming transformations | Final Silver surrogate keys, IRIs, SCD, FK policy, or hidden semantic authority |
| Silver | Entity grain, deterministic conformance, identity, history, relationships, and reusable quality | Report-specific metrics, dimensional roles, or probabilistic mastering |
| MDM runtime | Probabilistic matching, enterprise identity, merge/split, and survivorship | Raw technical normalization |
| Gold | Consumption-oriented product shape and semantic-model behavior | Source cleanup or ungoverned identity |

## 3. Bronze and preparation

1. Raw Bronze must remain immutable and replayable.
2. Every mapped source table must have an
   `integration/preparation/{source}-prep.ttl` policy.
3. Every mapped table must explicitly declare `prepMode` as either `passthrough` or
   `normalize`.
4. Missing preparation policy is blocking.
5. `passthrough` is valid only when validation finds no:
   - authored preparation operation;
   - unsafe or reserved identifier;
   - incompatible source and target type;
   - sentinel-value policy;
   - JSON shape;
   - derived CDC or watermark field; or
   - other known normalization risk.
6. Any normalization or derived CDC field requires a physical
   `stg_{source}__{table}` model.
7. Preparation may:
   - rename physical identifiers;
   - trim and perform lossless textual normalization;
   - parse and cast values with explicit error behavior;
   - normalize evidenced sentinel and null values;
   - normalize CDC operation, timestamp, and sequence fields;
   - emit `_source_record_key` from source, table, and declared source-PK scope;
   - flatten scalar JSON; and
   - create keyed child relations for arrays.
8. Preparation must not:
   - join independent source relations;
   - aggregate;
   - apply business classifications;
   - perform semantic matching or survivorship;
   - assert cross-source equivalence; or
   - silently change parent grain.
9. Scalar JSON expansion must preserve parent row grain.
10. JSON arrays must use an explicit child grain, parent key, element key or index, and
    declared null and empty behavior.
11. The raw JSON payload or a replayable raw reference must be retained.
12. Polymorphic, recursive, unstable, or unsupported JSON must fail, quarantine, or route
    to a contracted dbt transformation.

## 4. Mapping rules

1. Normal mappings may use only typed, deterministic, column-bounded expressions or
   approved namespaced macros.
2. Every expression must resolve its identifiers, output type, null behavior, and adapter
   support before rendering.
3. Normal mappings must reject:
   - arbitrary SQL, comments, and statement separators;
   - subqueries and joins;
   - windows and aggregation;
   - nondeterministic functions;
   - unsafe literals and unknown macros;
   - hidden filtering or row loss without an explicit typed predicate policy; and
   - undeclared grain changes.
4. Technical source cleanup belongs in preparation.
5. Relational logic, grain-forming logic, complex fallback, deduplication, and
   contribution-building logic belong in a contracted dbt transformation.

## 5. Contracted dbt transformations

1. Advanced transformations must follow this sequence:
   1. profile representative source evidence;
   2. approve grain, identity, target, dependencies, and output contract;
   3. implement SQL and tests against fixtures or a working development flow;
   4. validate on every declared adapter;
   5. synchronize the proven virtual-source contract;
   6. map the virtual columns; and
   7. bind the generated Silver wrapper.
2. The approved contract is the acceptance boundary. Working SQL is not semantic
   authority.
3. Contracted transformations are required for:
   - multi-table joins;
   - window functions;
   - ranking and deterministic deduplication;
   - aggregation and grain changes;
   - structurally different multi-source branches;
   - complex fallback rules;
   - complex or grain-changing JSON expansion;
   - conditional business derivations; and
   - association or bridge formation.
4. A contracted model must declare exact output columns, types, nullability, grain,
   physical keys, semantic target, stable virtual-source IRI, materialization,
   dependencies, supported adapters, and tests.
5. Contracted SQL must use `source()` and `ref()` rather than hard-coded physical
   relations.
6. A contracted model must not generate final Silver:
   - surrogate keys;
   - ontology-aligned entity-instance IRIs;
   - resolved FK surrogate keys;
   - SCD2 validity columns; or
   - `_row_hash`.
7. A model may replace a Bronze source only when the claim, contract, synchronized virtual
   vocabulary, mappings, replacement assertion, and `silverSourceRef` all agree.
8. Contract changes require re-synchronization and may require mapping and Silver-policy
   review.

## 6. Grain, identity, and lineage

1. Every materialized entity must declare:
   - business grain;
   - identity strategy;
   - key scope;
   - source identity;
   - change-detection strategy; and
   - lineage policy.
2. Supported identity strategies are:
   - governed business key;
   - source-scoped immutable key;
   - deterministic integration key;
   - externally mastered identifier; or
   - surrogate-only identity with an explicit reconciliation limitation.
3. `_source_record_key` must be globally unique by source, table, and record scope.
4. `_source_record_key` must not be treated as proof of business equivalence.
5. Silver may emit a shared integration or surrogate key only after exact deterministic
   equivalence is approved.
6. A surrogate key is a physical join key. It is not business identity and is not an
   incremental-loading prerequisite.
7. Source identity must never silently fall back to a business surrogate key.
8. Schema-level `skos:exactMatch` does not prove row-level entity equivalence.
9. Ontology term IRIs, optional entity-instance IRIs, source-record identity, and physical
   surrogate keys are separate concepts.
10. `_loaded_at`, `_ingested_at`, `_source_updated_at`, and `_source_effective_at` have
    distinct meanings and must not be substituted for one another.
11. Contracted transformations must expose every contributing source-record fact.
12. The normalized Silver contract owns the canonical contribution-lineage relation.

## 7. Multi-source conformance and MDM

1. Every multi-source entity must declare whether source branches are:
   - disjoint;
   - overlapping; or
   - exactly equivalent.
2. Every multi-source entity must also declare:
   - code, unit, currency, and time-zone normalization;
   - source precedence and attribute-conflict behavior;
   - natural or integration-key collision behavior;
   - deletion and late-arrival behavior; and
   - reconciliation tests by branch and union.
3. Typed `UNION ALL` provides schema alignment only. It is not proof of semantic
   conformance.
4. Silver may resolve reviewed, exact, deterministic equivalence.
5. Probabilistic or fuzzy matching, persistent enterprise IDs, merge/split, and
   survivorship belong exclusively to MDM runtime.

## 8. Incremental loading, CDC, and SCD

1. Every incremental entity must declare:
   - unique or merge identity;
   - CDC operation;
   - source update and effective timestamps;
   - ingestion timestamp;
   - a complete total-order tie-breaker;
   - lookback behavior;
   - hard-delete and soft-delete behavior;
   - late-arrival and correction behavior;
   - replay and backfill behavior; and
   - schema-change behavior.
2. SCD2 history must be classified as either `business-valid` or `load-history`.
3. Projection or run time must never be represented as business-valid time.
4. One injected run clock must drive load metadata for a projection run.
5. SCD2 validity intervals must be deterministic, non-overlapping, and ordered.
6. Replay and reruns must be idempotent.
7. Delete, late-arrival, correction, and same-timestamp behavior must have executable test
   coverage.

## 9. Canonical hashing

1. Change-detection hashing must use a versioned canonical serialization contract.
2. The contract must define:
   - ordered participating columns;
   - type-aware serialization;
   - unambiguous null representation;
   - length-delimited field boundaries;
   - normalized decimal, timestamp, Boolean, and Unicode representation;
   - excluded volatile technical fields;
   - SHA-256 as the hash algorithm; and
   - output encoding.
3. Every supported adapter must produce equivalent logical hash inputs.
4. A changed hash contract is a migration and backfill event.

## 10. Relationships and temporal foreign keys

1. Every relationship must declare:
   - current, as-of, or non-temporal lookup mode;
   - interval-boundary semantics;
   - normalized time zone and precision;
   - expected zero-or-one or exactly-one cardinality;
   - missing-parent behavior;
   - ambiguous-parent behavior; and
   - late-parent restatement behavior.
2. Missing parents must follow an explicit fail, quarantine, retry, or governed unknown-key
   policy.
3. Multiple parent matches must never be resolved by silently selecting one.
4. Parent SCD2 intervals must be checked for overlap and duplicate current rows.
5. As-of relationships require compatible business-effective time.
6. The projection and runtime reports must surface unresolved and ambiguous relationship
   counts.

## 11. Typed projection and output parity

1. Projection must follow:

   `bind → normalize → shape → materialize → render`

2. Phase responsibilities are:
   - **bind** reads RDF and authoring inputs and emits immutable facts;
   - **normalize** is the only effective-policy classification phase;
   - **shape** emits logical typed specifications without rendered content;
   - **materialize** selects physical plans through adapter capabilities; and
   - **render** consumes physical plans only.
3. Phase handoffs must not contain mutable containers, `rdflib.Graph`, Jinja
   environments, or rendered artifacts.
4. `SilverModelSpec` must be the single logical source for:
   - dbt SQL;
   - schema YAML;
   - Silver DDL;
   - ERD;
   - Gold registry;
   - generated quality tests; and
   - projection and release reports.
5. DDL-only operational behavior is forbidden.
6. Documentation-only platform constraints must be labeled non-enforced.
7. Reference inlining is a Gold product optimization, not Silver behavior.
8. The parity manifest must map every logical specification field to its dbt SQL, schema
   YAML, DDL, constraint metadata, and ERD representation.
9. Parity artifacts must use deterministic SHA-256 hashes.
10. Strict release must reject missing, blocking, or hash-drifted parity evidence.
11. Artifact determinism and runtime-data determinism are separate guarantees and must be
    reported separately.

## 12. Adapter portability

1. Fabric and Databricks must have versioned capability records covering:
   - semantic-to-physical types and lossiness;
   - identifiers and collation;
   - timestamp zone and precision;
   - canonical hashes;
   - JSON;
   - merge, incremental, and SCD behavior;
   - constraints;
   - partitioning and clustering; and
   - dbt test support.
2. Unknown adapters and unsupported combinations must fail.
3. No generic fallback may treat every non-Fabric adapter as Databricks.
4. Physical layout is deployment-profile policy based on observed workload, not ontology
   truth.
5. A capability is supported only when required scenarios compile successfully on every
   declared adapter.
6. `environment_blocked` is not passing strict-release evidence.

## 13. Gold product profiles

1. Gold is a consumption-oriented data-product layer.
2. Every Gold product must declare a named, versioned profile.
3. The v1 profile is `dimensional-powerbi-v1`.
4. The profile may emit dimensional dbt models, facts, dimensions, bridges,
   relationships, hierarchies, governed measures, calendars, calculation groups,
   security scaffolds, perspectives, DirectLake TMDL, and deployment-readiness evidence.
5. The profile does not own visuals, entitlement provisioning, deployment, or runtime
   identity administration.
6. Every dimensional table must explicitly declare `fact`, `dimension`, or `bridge`.
7. FK counts must never infer table role.
8. Zero-dimension facts are valid.
9. Facts must declare:
   - grain;
   - transaction, periodic-snapshot, or accumulating-snapshot type;
   - correction policy;
   - late-arrival policy;
   - dimension-version binding; and
   - complete incremental policy.
10. Dimensions must declare current-only, history-only, or dual exposure.
11. Bridges must declare grain, endpoints, key bindings, cardinality, optional weight, and
    allocation semantics.
12. Gold must bind to actual passing Silver models and emitted columns. It must not invent
    references or select unavailable fields.

## 14. Measures and calendars

1. Measures are first-class semantic resources rather than annotations that replace
   physical properties.
2. Every measure must declare:
   - stable identifier;
   - business definition;
   - column and measure dependencies;
   - lifecycle state: `intent`, `provisional`, `validated`, or `approved`;
   - result type;
   - format and display folder;
   - abstract owner role; and
   - validation tests and evidence.
3. An `intent` measure may omit DAX.
4. `provisional`, `validated`, and `approved` measures require an expression and explicit
   dependencies.
5. `validated` and `approved` measures require imported test evidence.
6. `approved` measures require an abstract owner role.
7. Measures must never remove a required base column.
8. Missing, unavailable, ambiguous, cyclic, or undeclared DAX dependencies are blocking.
9. Parseable DAX is not proof of data correctness.
10. Production time intelligence requires an approved calendar profile defining:
    - date range;
    - fiscal-year start;
    - week convention and period pattern;
    - locale and holidays;
    - time zone;
    - current and closed-period semantics; and
    - role-playing date bindings.
11. Date tables and time-intelligence calculations must not be invented without an
    approved calendar profile.

## 15. Security

1. RLS and OLS generation requires a complete fail-closed security contract containing:
   - governed entitlement source;
   - identity mapping;
   - role policy and membership bindings;
   - filter direction;
   - table and column bindings;
   - positive and negative authorization tests;
   - imported evidence; and
   - `failClosed true`.
2. Generated RLS must start deny-all.
3. Security bindings must resolve against emitted models and columns.
4. Perspectives are navigation aids and must never be represented as security boundaries.
5. TMDL must parse and compile, and DirectLake bindings and types must validate.
6. Deployment identity, entitlement provisioning, and runtime enforcement remain
   downstream responsibilities and evidence.

## 16. Data quality

1. Every data-quality rule must declare:
   - stable ID and version;
   - category: `contract`, `source`, `business`, or `operational`;
   - scope;
   - severity and tolerance;
   - action: `warn`, `quarantine`, or `block`;
   - abstract owner role;
   - evidence; and
   - executable test reference.
2. Supported checks include:
   - contract shape;
   - freshness;
   - volume and anomaly;
   - duplicate rate;
   - range and distribution;
   - source-to-target reconciliation;
   - referential coverage; and
   - cross-field rules.
3. Toolkit-owned namespaced dbt tests and macros are preferred.
4. External packages require an approved package policy, compatible license, and adapter
   evidence.
5. DQ execution must emit portable, versioned runtime-result records containing:
   - run, snapshot, and adapter identity;
   - rule ID, version, and hash;
   - status;
   - measured value and threshold;
   - affected and quarantined counts;
   - reconciliation values; and
   - evidence URI.
6. Runtime observations are immutable imported evidence, not generated compliance claims.
7. DQ references must use `kairos.dq.<check-kind>.v1` and the closed
   `key=value;...` parameter grammar.
8. DQ rules must never accept raw SQL.
9. Row-level quarantine must emit a DQ input relation, filtered normal model, and
   quarantine relation.
10. Aggregate-only checks must not request row quarantine.

## 17. Release and reporting

1. Fresh hubs must contain `model/governance/release-baseline.yaml`.
2. Strict release must block:
   - missing, expired, or stale baseline and evidence;
   - unknown validation or projection status;
   - missing preparation policy;
   - unexpected skips, unbindings, or required-entity changes;
   - design stubs;
   - contract, mapping, parity, or adapter regressions;
   - unsupported required capabilities;
   - blocking DQ, security, or product-profile rules;
   - warnings or errors prohibited by the release profile; and
   - missing required adapter compile evidence.
3. Intentional exclusions must be explicit policy.
4. Baseline changes require approval and a deterministic diff.
5. Ordinary projection must emit release artifacts in `review-only` mode with
   `release_ready: false`.
6. Only strict projection may set `release_ready: true`.
7. Strict release requires an approved, unexpired baseline and matching compile evidence
   for every required adapter, version, capability, and scope.
8. Registry claims alone never satisfy release evidence.
9. Reports must separate:
   - normative policy;
   - effective configuration and provenance;
   - implementation capability;
   - approved deviations;
   - generated artifacts and checks; and
   - observed runtime evidence.
10. Released-product metadata must include:
    - abstract owner and steward roles;
    - data classification;
    - compatibility and breaking-change status;
    - freshness SLA expectation;
    - adapter evidence;
    - known limitations; and
    - lineage and reconciliation evidence.
11. An SLA declaration is an expectation, not proof of runtime health.
12. Unmapped, skipped, unbound, stubbed, and empty-required entities must have distinct,
    machine-readable statuses.

## 18. Scope and compatibility

1. These rules apply only to newly scaffolded hubs.
2. No compatibility aliases or old/new dual-generation path are provided.
3. No migration command is provided for existing hubs.
4. Old scaffold annotations and layouts are unsupported.
5. Old generated artifacts have no byte-compatibility guarantee.
6. Vocabulary, shapes, scaffold templates, scenarios, skills, reports, and downstream
   contracts must change atomically when this policy changes.
