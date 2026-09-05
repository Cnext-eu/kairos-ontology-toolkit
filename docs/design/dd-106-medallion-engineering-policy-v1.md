# Medallion Engineering Policy v1

**Status:** Accepted normative design baseline; DD-106–DD-115 runtime implemented  
**Version:** 1.0  
**Frozen:** 2026-07-25  
**Applies to:** Fresh Kairos ontology hubs only  
**Platforms:** Microsoft Fabric and Azure Databricks  
**Decisions:** DD-106 through DD-115

This document is the frozen normative baseline for the Medallion projector redesign.
It resolves the data-engineering review captured in
[`../draft/Kairos-Ontology 4.7- Medaillon projector - dataengineeringrules - FEEDBACK.md`](../draft/Kairos-Ontology%204.7-%20Medaillon%20projector%20-%20dataengineeringrules%20-%20FEEDBACK.md).

The typed projector implements this policy through immutable phase contracts,
adapter-specific rendering, executable DQ artifacts, and fail-closed strict release.
The accepted decisions remain authority over implementation and generated output.

## 1. Authority and evidence

Authority is ordered:

1. accepted design decisions and versioned policy profiles;
2. governed ontologies, claims, mappings, extensions, prep policies, and contracts;
3. approved, scope-limited deviations;
4. implementation capability evidence; and
5. generated artifacts.

Implementation never overrides policy. Every effective value reports its authored,
inherited, defaulted, or deviated source. Unsupported or partial behavior fails or is an
approved deviation; it never silently degrades.

Policy evidence, generated capability evidence, and observed runtime results are
separate. The toolkit may generate executable checks and import their result contract,
but it does not operate monitoring, alerting, or trend storage.

## 2. Layer responsibilities

| Layer / surface | Owns | Must not own |
|---|---|---|
| Raw Bronze | Replayable source values, raw schema, source PK/CDC/ingestion evidence | Cleanup, semantic conformance, cross-source identity |
| Prep/staging | Source-specific names, types, sentinels, scalar JSON, array-child extraction, normalized CDC inputs, source-record key | Joins, aggregation, business classification, survivorship, cross-source equivalence |
| Mapping | Source-column to domain-property alignment and constrained typed scalar expressions | Arbitrary SQL, joins, windows, aggregation, grain changes |
| Contracted dbt | Governed relational and grain-forming transformation | Final Silver SK/IRI/SCD/FK policy, hidden semantic authority |
| Silver | Entity grain, exact deterministic conformance, identity strategy, SK/IRI, history, relationships, reusable quality | Report-specific metrics and dimensional roles, probabilistic mastering |
| MDM runtime | Probabilistic matching, enterprise identity, merge/split, survivorship | Raw technical normalization |
| Gold profile | Consumption-oriented product shape and semantic-model behavior | Source cleanup or ungoverned identity |

## 3. Bronze and prep

1. Bronze is immutable input for replay and audit.
2. Every mapped table has
   `integration/preparation/{source}-prep.ttl`.
3. Every mapped table declares `prepMode`:
   - `passthrough`; or
   - `normalize`.
4. Absence of prep policy is blocking.
5. `passthrough` is allowed only when validation finds no:
   - authored prep operation;
   - unsafe/reserved identifier;
   - incompatible source/target type;
   - sentinel policy;
   - JSON shape;
   - derived CDC/watermark field; or
   - other known normalization risk.
6. Any normalization or derived CDC field requires a physical
   `stg_{source}__{table}` model.
7. Prep may:
   - rename physical identifiers;
   - trim and perform lossless textual normalization;
   - parse and cast with explicit error behavior;
   - normalize evidenced sentinel/null values;
   - normalize CDC operation/timestamp/sequence fields;
   - emit `_source_record_key` from source/table scope and declared source PK;
   - flatten scalar JSON; and
   - create keyed child relations for arrays.
8. Prep must not:
   - join independent source relations;
   - aggregate;
   - apply business classification;
   - perform semantic matching or survivorship;
   - assert cross-source equivalence; or
   - silently change parent grain.
9. Scalar JSON preserves parent row grain. Arrays use an explicit child grain, parent
   key, element key/index, and null/empty behavior.
10. Raw JSON payload or a replayable raw reference is retained.
11. Polymorphic, recursive, unstable, or unsupported JSON fails/quarantines or routes
    to contracted dbt.

## 4. Mapping and contracted transformations

Normal mapping expressions are typed, deterministic, column-bounded expressions or
approved namespaced macros. They resolve identifiers, output type, null behavior, and
adapter support before rendering.

Normal mappings reject:

- arbitrary SQL, comments, and statement separators;
- subqueries and joins;
- windows and aggregation;
- nondeterministic functions;
- unsafe literals or unknown macros;
- hidden filtering/row loss without an explicit typed predicate policy; and
- undeclared grain changes.

Technical source cleanup belongs in prep. Relational, grain-forming, complex fallback,
deduplication, and contribution-building logic belongs in a contracted dbt model.

Advanced transformations follow:

1. profile representative source evidence;
2. approve grain, identity, target, dependencies, and output contract;
3. implement SQL and tests against fixtures or a working development flow;
4. validate on each declared adapter;
5. synchronize the proven virtual-source contract;
6. map virtual columns; and
7. bind the generated Silver wrapper.

Working SQL is not semantic authority. The approved contract is the acceptance boundary.

## 5. Identity and lineage

Every materialized entity declares:

- business grain;
- identity strategy;
- key scope;
- source identity;
- change-detection strategy; and
- lineage policy.

Identity strategies are:

- business key;
- source-scoped immutable key;
- deterministic integration key;
- externally mastered identifier; or
- surrogate-only with an explicit reconciliation limitation.

Rules:

1. `_source_record_key` is globally unique by source/table/record scope and does not
   establish business equivalence.
2. Silver emits a shared integration/surrogate key only after exact deterministic
   equivalence is approved.
3. A surrogate key is a physical join key, not business identity or an incremental
   prerequisite.
4. Source identity never silently falls back to a business SK.
5. Schema-level `skos:exactMatch` does not establish row-level entity equivalence.
6. Ontology document/term IRIs, optional entity-instance IRI, source-record identity,
   and physical SK are separate.
7. `_loaded_at`, `_ingested_at`, `_source_updated_at`, and `_source_effective_at` are
   distinct.
8. Contracted transformations expose each contributing source-record fact; the
   normalized Silver contract owns the canonical contribution-lineage relation and the
   generated Silver wrapper emits it.

**Implementation status (DD-108):** complete. Immutable identity, lineage, timestamp,
multi-source and MDM-routing specifications now govern Silver SQL/schema authority,
release metadata and Gold inputs. Strategy contradictions and missing mapped identity
evidence fail closed; no compatibility alias or inferred natural key is emitted.

## 6. Multi-source conformance and MDM

Every multi-source entity declares:

- branches are disjoint, overlapping, or exactly equivalent;
- code, unit, currency, and time-zone normalization;
- source precedence and attribute conflict behavior;
- natural/integration key collision behavior;
- deletion and late-arrival behavior; and
- reconciliation tests by branch and union.

Typed `UNION ALL` is schema alignment, not proof of semantic conformance.

Silver may resolve reviewed exact deterministic equivalence. Probabilistic/fuzzy
matching, persistent enterprise IDs, merge/split, and survivorship belong exclusively
to MDM runtime and its policy vocabulary.

## 7. Incremental, CDC, SCD, hashing, and FKs

Every incremental entity declares:

- unique/merge identity;
- CDC operation;
- source update/effective timestamp;
- ingestion timestamp;
- complete total-order tie-breaker;
- lookback;
- hard/soft delete behavior;
- late arrival and correction behavior;
- replay and backfill behavior; and
- schema-change behavior.

SCD2 declares either:

- `business-valid`; or
- `load-history`.

Projection/run time must not be described as business-valid time. One injected run clock
drives load metadata.

Hashing uses versioned, ordered, typed, length-delimited canonical serialization with an
explicit null representation and SHA-256. Adapters must produce equivalent logical hash
inputs.

Temporal relationships declare:

- current or as-of mode;
- interval boundary semantics;
- normalized time zone/precision;
- expected zero-or-one or exactly-one cardinality;
- missing parent policy;
- ambiguous parent policy; and
- late-parent restatement policy.

Multiple parent matches are never resolved by silently selecting one.

## 8. Typed projection and output parity

Projection remains:

`bind → normalize → shape → materialize → render`

The phase contract is:

- **bind** reads RDF and authoring inputs and emits immutable facts;
- **normalize** is the sole effective-policy classification phase;
- **shape** emits logical typed specifications and no rendered content;
- **materialize** selects physical plans through adapter capabilities; and
- **render** consumes physical plans only.

No phase handoff contains mutable containers, `rdflib.Graph`, Jinja environments, or
rendered artifacts.

`SilverModelSpec` is the single logical source for:

- dbt SQL;
- schema YAML;
- Silver DDL;
- ERD;
- Gold registry;
- generated quality tests; and
- projection/release reports.

DDL-only operational behavior is forbidden. Platform constraints that are documentation
only are labeled non-enforced. Reference inlining is a Gold product optimization, not
Silver behavior.

The same materialization plan maps canonical types to Fabric or Databricks physical
types and emits:

- `analyses/{domain}/{domain}-ddl.sql`;
- `metadata/{domain}-silver-constraints.json`;
- `docs/diagrams/{domain}/{domain}-erd.mmd`; and
- `metadata/{domain}-silver-parity.json`.

The parity manifest maps every logical specification field to the dbt SQL, schema YAML,
DDL, constraint metadata, and ERD representations with deterministic SHA-256 hashes.
Strict release rejects a missing, blocking, or hash-drifted parity manifest.

## 9. Adapter capabilities

Fabric and Databricks have versioned capability records for:

- semantic-to-physical types and lossiness;
- identifiers and collation;
- timestamp zone/precision;
- canonical hashes;
- JSON;
- merge/incremental/SCD behavior;
- constraints;
- partitioning/clustering; and
- dbt test support.

Unknown adapters and unsupported combinations fail. No default branch treats every
non-Fabric adapter as Databricks. Physical layout is deployment-profile policy based on
observed workload, not ontology truth.

“Supported/applied” requires successful compile evidence on every required adapter.
`environment_blocked` is not strict-pass evidence.

## 10. Gold product profiles

Gold is a consumption-oriented product layer. Every product declares a named, versioned
profile.

The only profile in v1 is `dimensional-powerbi-v1`. It includes:

- dimensional dbt models;
- facts, dimensions, bridges, and relationships;
- hierarchies and governed measures;
- governed date/calendar and calculation groups;
- RLS/OLS scaffolds and perspectives;
- DirectLake TMDL; and
- a deployment-readiness manifest.

It excludes other product types, visuals, entitlement provisioning, and runtime identity
administration.

Within this profile:

1. every table explicitly declares `fact`, `dimension`, or `bridge`;
2. FK counts never infer table role;
3. zero-dimension facts are valid;
4. facts declare grain and type: transaction, periodic snapshot, or accumulating
   snapshot;
5. correction, late-arrival, dimension-version binding, and incremental policy are
   explicit; and
6. dimensions declare current-only, history-only, or dual exposure.

## 11. Measures, calendars, and security

Measures are first-class semantic resources with:

- stable identifier and business definition;
- declared column/measure dependencies;
- lifecycle state (`intent`, `provisional`, `validated`, `approved`);
- format/folder/owner role; and
- validation tests.

Measures never remove required base columns. Missing or cyclic DAX dependencies block
release.

Production time intelligence requires an approved calendar profile defining date range,
fiscal/week pattern, locale, holidays, time zone, period closure, and role-playing
dates.

RLS/OLS output requires a complete projection-time fail-closed security contract:
entitlement source, identity mapping, role policy, filter direction, bindings, and
positive/negative test definitions. Perspectives are not security.

TMDL must parse/compile and DirectLake bindings/types must validate. Deployment and
runtime enforcement remain downstream evidence.

## 12. Data quality

Every DQ rule declares:

- stable ID and version;
- category (`contract`, `source`, `business`, `operational`);
- scope;
- severity and tolerance;
- action (`warn`, `quarantine`, `block`);
- abstract owner role;
- evidence; and
- executable test reference.

Supported checks include contract shape, freshness, volume, duplicate rate, range,
distribution, reconciliation, referential coverage, and cross-field rules.

Prefer toolkit-owned namespaced dbt tests/macros. External packages require approved
package policy, compatible licensing, and adapter evidence.

Runtime results use a portable versioned schema with run/snapshot/adapter identity, rule
ID/version/hash, status, measured value, threshold, affected/quarantined counts,
reconciliation values, and evidence URI. Runtime observations are immutable imported
evidence, not generated claims.

The v1 executable surface uses toolkit-owned references
`kairos.dq.<check-kind>.v1` and a closed `key=value;...` parameter grammar.
It never accepts raw SQL. Each rule emits a persistent result relation and singular
dbt test. Row-level quarantine additionally emits `{model}__dq_input`, a filtered
normal model, and `{model}__dq_quarantine`; aggregate-only checks cannot request
quarantine. The portable JSON schema is
`contracts/dq-runtime-result-contract.schema.json`.

## 13. Release and reporting

Fresh hubs contain `model/governance/release-baseline.yaml`.

Strict release blocks:

- missing or stale baseline/evidence;
- unknown validation/projection status;
- missing prep policy;
- unexpected skip, unbinding, or required-entity change;
- design stub;
- contract, mapping, or adapter regression;
- unsupported required capability;
- blocking DQ/security/profile rule;
- warning/error prohibited by the release profile; and
- missing required adapter compile evidence.

Intentional exclusions are explicit policy. Baseline changes require approval and
deterministic diff.

Reports separate:

- normative policy;
- effective configuration and provenance;
- implementation capability;
- approved deviations;
- generated artifacts/checks; and
- observed runtime evidence.

Ordinary projection emits `release-manifest.json` and `release-report.json` in
`review-only` mode with `release_ready: false`. `project --strict` is the only
projection path that may set the boolean true. It requires an approved, unexpired
baseline and matching supported compile evidence for every required
adapter/version/capability/scope. Registry claims alone never satisfy that check.

Required released-product metadata includes abstract owner/steward roles, data
classification, compatibility status, freshness SLA expectation, adapter evidence, and
known limitations. SLA is an expectation, not runtime-health proof.

## 14. Breaking scope

This policy intentionally provides:

- no compatibility aliases;
- no old/new dual generation path;
- no migration command for existing hubs;
- no support for old scaffold annotations or layouts; and
- no byte-compatibility guarantee for old generated artifacts.

Vocabulary, shapes, scaffold templates, scenario extensions, skills, reports, and
downstream contracts change atomically. Existing customer hubs are outside scope; newly
scaffolded hubs are the only supported configuration.

## 15. Implementation acceptance gate

The policy is implemented only when:

1. representative Silver and Gold scenarios use typed phase specs with no rendered
   content before render;
2. prep pass-through and normalization fail closed;
3. source identity, integration identity, and MDM ownership are distinct;
4. CDC/SCD replay, delete, late-arrival, correction, hash, and temporal-FK tests pass;
5. Silver dbt/DDL/schema/report parity is proven from one spec;
6. Fabric and Databricks compile required scenarios with equivalent semantic contracts;
7. explicit Gold roles, measures, calendars, and security gates pass;
8. versioned status/validation/projection/release/DQ reports pass schema tests;
9. strict release detects baseline regression and refuses stubs/unknown evidence; and
10. scaffold, skill, scenario, lint, deterministic, and full test suites pass.
