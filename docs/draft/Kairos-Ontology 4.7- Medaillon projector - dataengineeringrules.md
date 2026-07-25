# Data Engineering Rules Embedded in the Kairos Medallion Projector

**Status:** Draft  
**Date:** 2026-07-23  
**Scope:** Bronze-to-Silver dbt projection and the surrounding Medallion design  
**Target platforms:** Microsoft Fabric and Azure Databricks

## 1. Purpose

The Kairos projector automates data-engineering decisions that would otherwise be
implemented manually in dbt models, warehouse DDL, tests, and operational conventions.
This document makes those decisions visible to data engineers.

It distinguishes four implementation states:

| State | Meaning |
|---|---|
| **Applied by dbt** | The generated dbt SQL or schema YAML implements the rule. |
| **Validated** | Projection checks the rule and fails or warns when it is unsafe. |
| **Silver DDL only** | The Silver DDL projector represents the rule, but generated dbt does not currently implement its runtime behaviour. |
| **Recognized, not rendered** | The annotation is parsed but does not currently affect generated dbt SQL. |

Generated artifacts are derivative. Ontologies, Silver extension annotations, Bronze
vocabularies, SKOS mappings, SHACL shapes, claims, and contracted transformations remain
the design authorities.

## 2. Formal Medallion design-decision constraints

The formal decision record is
[`docs/design/toolkit-design-decisions.md`](../design/toolkit-design-decisions.md). The
following decisions constrain the Medallion implementation. An **Accepted** DD is an
architectural constraint. A **Proposed, implemented** DD describes current behaviour but
still has a pending governance status in the decision log.

| DD | Status | Constraint on the Medallion implementation |
|---|---|---|
| DD-001 | Proposed, implemented | Gold defaults to class-per-table inheritance with a shared parent PK/FK; discriminator flattening is an explicit override. |
| DD-002 | Accepted | Generate platform-specific SQL for Fabric and Databricks; dbt does not abstract types, JSON functions, or all dialect differences. |
| DD-006 | Accepted | Embedded JSON is described at column level, never by a table-level physical-storage flag. |
| DD-011 | Accepted | Silver DDL, constraints, and diagrams live inside the generated dbt project tree; there is no competing Silver output root. |
| DD-014 | Accepted | Silver is the first generated dbt layer and reads Bronze directly; no mandatory generated staging layer may be reintroduced. |
| DD-015 | Accepted | Bronze vocabulary TTL is the authoritative physical source contract; dbt source YAML remains a minimal connection/reference artifact. |
| DD-018 | Accepted | Silver is entity-centric. Multi-source entities automatically use per-source normalization views plus one canonical union model. |
| DD-019 | Accepted | Silver FK columns contain resolved warehouse surrogate keys, not disguised source natural keys. |
| DD-020 | Accepted | Ontology IRIs are stable and versionless; versions use `owl:versionInfo` and repository releases. |
| DD-021 | Proposed, implemented | Imported classes are projection-whitelisted with `silverInclude`/`goldInclude` or first-level bulk include; broad imports do not imply broad materialization. |
| DD-022 | Proposed, implemented | FK direction and placement are explicitly expressible in extension TTL and normalized once for Silver DDL, dbt, and Gold. |
| DD-023 | Proposed, implemented | Reference models may provide Silver/Gold defaults, but hub extension annotations have higher precedence. |
| DD-025 | Proposed, implemented | SCD1 and SCD2 use distinct incremental strategies; SCD2 performs row-hash change detection and closes prior versions. |
| DD-026 | Accepted | Silver emits mapped columns only, honours the normalized FK contract, preserves all historical values, and retains source provenance. |
| DD-027 | Accepted | Peer Silver extensions provide cross-domain natural-key/FK context without duplicating annotations into the referencing domain. |
| DD-029 | Accepted | Gold resolves its inputs through the actual generated Silver model-and-column registry; it must not invent refs or select unavailable Silver columns. |
| DD-035 | Accepted | Silver subtype folding is opt-in through `inheritanceStrategy "discriminator"`; table-per-concrete-class is the safe default. |
| DD-039 | Accepted | JSON is detected and expanded before Silver in an optional `bronze_expanded` boundary; Silver opts into the expanded model explicitly. |
| DD-074 | Accepted | Multi-source unions use a deterministic typed superset, explicit ordered columns, typed null padding, and per-source FK resolution. |
| DD-092 | Accepted | Joins, windows, ranking, aggregation, complex JSON expansion, fallback logic, and grain changes belong in governed contracted dbt transformations, not a new RDF execution DSL. |
| DD-093 | Accepted | A contracted model may replace a Bronze source only when claims, canonical source IRIs, contract metadata, synchronized virtual vocabulary, exact mappings, and `silverSourceRef` agree. |
| DD-094 | Accepted | The Claim Registry is the single authority for what may materialize; probabilistic evidence never grants materialization authority. |
| DD-095 | Accepted | Derived claims are deterministic evidence aggregation and always remain proposed until governed approval. |
| DD-096 | Accepted | Aspirational Silver is derived, opt-in, typed, zero-row, and release-blocking until a real source binding replaces it at the same model path. |
| DD-097 | Accepted | Multi-domain projection deterministically reconciles package-level artifacts and keeps shared Gold assets domain-neutral. |
| DD-101 | Accepted | Release readiness composes existing claim, source, extension, binding, validation, and projection facts without re-deriving their rules. |
| DD-102 | Accepted | dbt projection follows immutable `bind -> normalize -> shape -> materialize -> render` phases; render cannot reread RDF or reclassify policy. |
| DD-104 | Accepted | Every bound branch has a complete natural key, timestamp-precise SCD semantics, explicit temporal FK semantics, row lineage, and platform-portable semantic contracts. |
| DD-105 | Accepted | Imported SQL is non-executable evidence until transformation readiness is governed and the DD-092/DD-093 contract path is complete. |

Superseded DD-003, DD-004, and DD-005 must not be used to justify recreating the old
mandatory staging layer. `bronze_expanded` and contracted transformations are explicit
exceptions for source-shape work that cannot safely remain in direct mappings; they are
not a general-purpose staging tier.

### 2.1 Rule hierarchy

The implementation has three related rule levels:

```text
R1-R16  common kairos-ext annotation semantics
    |-- S1-S8  Silver physical conventions
    `-- G1-G8  Gold dimensional and Power BI conventions
```

The DD log governs architecture and authority boundaries. R/S/G rules govern projection
behaviour within those boundaries. If prose in a skill or draft conflicts with an
Accepted DD or current projector implementation, the DD and implementation are
authoritative until reconciled.

## 3. Medallion design choices

### 3.1 Bronze preserves source meaning

Bronze vocabularies describe physical source systems, tables, columns, keys, types, and
enumerations without pretending that source structures are canonical business models.
Silver models consume declared Bronze sources directly through dbt `source()` calls.

Kairos deliberately removed a mandatory generated staging layer. Rename, cast, mapping,
default, filter, and straightforward transformation logic belongs in generated Silver
models. A separate intermediate model is justified only when the transformation changes
grain or requires relational logic such as joins, windows, ranking, aggregation, JSON
expansion, or complex fallback rules.

### 3.2 Silver is entity-centric and domain-conformed

Silver tables represent ontology classes rather than reports or source tables. Their
grain, natural keys, relationships, history policy, and data-quality expectations are
designed explicitly.

A Silver entity can be populated by one or more sources:

- one source produces a direct entity model;
- multiple sources produce normalized per-source views and one conformed `UNION ALL`
  entity model;
- source branches are padded to the same canonical column contract;
- each branch must provide the complete natural key.

Source-specific technical shapes are not promoted into the ontology merely because they
exist in a legacy warehouse. Stable business meaning is modeled in the ontology;
source-specific logic remains in mappings or contracted transformations.

### 3.3 Gold owns consumption semantics

Silver uses plain entity names and preserves reusable business history. It does not use
`dim_` or `fact_` prefixes. Dimensional roles, facts, dimensions, measures, report-facing
aggregations, and current-state reductions belong in Gold.

This prevents Silver from becoming coupled to one report or semantic model.

### 3.4 Grain and identity are separate concerns

Every materialized Silver entity distinguishes:

1. **Business grain** -- the real-world occurrence represented by one row.
2. **Source identity** -- source system plus immutable source-record identity.
3. **Natural key** -- business properties identifying the entity within a defined scope.
4. **Warehouse identity** -- deterministic surrogate key and ontology IRI.

The projector rejects a bound model without a natural key because an incremental model
with null warehouse keys is unsafe. Records from different systems are not considered
the same merely because display identifiers overlap; cross-source equivalence requires
an explicit mapping or governed MDM decision.

### 3.5 History is explicit

SCD policy is declared per entity:

- **SCD Type 1** keeps the current state through an incremental upsert keyed by the
  generated surrogate key.
- **SCD Type 2** stores business versions using `valid_from`, `valid_to`, `is_current`,
  and `_row_hash`.

SCD2 change detection hashes history-participating attributes rather than comparing
every column individually. Load metadata and technical identity columns are excluded.
Resolved FK values participate by default so relationship changes create history unless
the relationship is explicitly declared non-historical.

When a mapped business-effective timestamp is declared, it becomes `valid_from`.
Otherwise the projection timestamp is used. Timestamp precision is retained so multiple
changes on the same day remain distinct.

### 3.6 Relationships are semantic and temporal

OWL object properties and Silver FK annotations determine relationship direction and
cardinality. The projector can:

- place a many-to-one FK on the domain entity;
- reverse a parent-to-child relationship so the child holds the FK;
- infer a lookup through the target entity's natural key;
- resolve cross-domain references using canonical model ownership;
- join to the current version of an SCD2 parent; or
- perform an as-of join against the parent's validity interval.

An as-of relationship is rejected when the parent does not have a business-effective
validity definition. Producing a plausible but temporally incorrect join is not an
acceptable fallback.

### 3.7 Data quality is generated from semantics

SHACL and ontology metadata are projected into dbt tests instead of being maintained as
a disconnected test specification. Generated checks include:

- `not_null` for required properties and natural keys;
- current-row uniqueness for SCD2 surrogate keys and IRIs;
- ordinary uniqueness for SCD1 entities;
- accepted values for enumerated source fields;
- regex and length constraints where expressed in SHACL;
- FK relationship tests; and
- accepted values `{0, 1}` for `is_current`.

Physical warehouse constraints remain documentation where the target platform cannot
enforce them. dbt tests provide executable validation without claiming that comments are
enforced constraints.

### 3.8 Lineage and provenance are part of the contract

Generated Silver models retain:

- the ontology IRI for the entity;
- `_source_system`;
- `_source_record_id`;
- `_loaded_at`;
- source and target IRIs in dbt metadata;
- ontology and toolkit versions; and
- the reference-model closure hash and applied Silver defaults/overrides.

Lineage is not an optional observability add-on. It is part of the generated row and
model contracts.

### 3.9 Generated output is deterministic

Given the same ontology closure, extensions, sources, mappings, shapes, claims,
contracts, target platform, toolkit version, and deterministic timestamp context, the
projector is designed to emit the same managed paths and bytes.

Generated dbt files must not be hand-edited. Custom SQL belongs under the governed
contracted-transformation boundary and is then consumed as an explicit Silver source.

### 3.10 Incomplete design must not appear production-ready

Unmapped classes are skipped with an actionable warning rather than producing broken SQL.
Approved, materialization-eligible claims can optionally emit typed zero-row
aspirational views for target-first design, but those stubs remain unbound and
release-blocking.

Schema-valid, source-bound, data-valid, and release-eligible are deliberately separate
facts. A dbt model that parses successfully is not automatically safe to release.

## 4. Bronze JSON detection and unfolding

### 4.1 Why JSON is unfolded before Silver

DD-006 and DD-039 treat JSON as a physical source-column concern. Repeated
`JSON_VALUE`, `OPENJSON`, `GET_JSON_OBJECT`, or `EXPLODE` logic inside canonical Silver
entities would:

- reparse the same payload in multiple models;
- mix source-shape logic with domain conformance;
- make typed tests and lineage harder to review; and
- create avoidable warehouse execution cost.

The intended path is:

```text
Bronze raw column
    -> schema extraction and JSON classification
    -> optional bronze_expanded dbt model
    -> synchronized Bronze-compatible vocabulary/contract
    -> SKOS mapping
    -> Silver wrapper selected with silverSourceRef
```

For simple generated expansion this is the DD-039 `bronze_expanded` path. For JSON
processing combined with joins, windows, fallback rules, deduplication, aggregation, or a
grain change, DD-092 requires a contracted custom transformation.

### 4.2 Detection and classification

Rich schema extraction samples source values and records JSON metadata in schema YAML
v1.1. Fabric considers large `varchar`/`nvarchar` columns; Databricks considers string,
varchar, and binary candidates. A candidate is treated as JSON when enough sampled
values look parseable.

The extractor records:

| Classification | Meaning | Current treatment |
|---|---|---|
| `flat` | One object with scalar top-level keys | Generate typed top-level columns in a row-preserving view. |
| `nested` | Object containing nested objects or arrays | Uses the current top-level object expansion path; recursive arbitrary-depth flattening is not implemented. |
| `array_object` | Array whose elements are objects | Generate a child-grain table with one row per array element and an element index. |
| `array_primitive` | Array of scalar values | Detected and documented, but no expansion model is currently generated. |
| `polymorphic` | Mixed object/array/scalar shapes | Preserve as a string and require review; never guess a stable relational contract. |

The five-row default is a heuristic, not proof of a stable schema. Rare polymorphism may
be missed, so generated metadata remains review evidence before production use.

### 4.3 Generated Fabric expansion

The current generated expansion helper produces:

- a `bronze_expanded` **view** for flat/top-level object fields using `JSON_VALUE`;
- casts for inferred integer, decimal, and boolean values;
- a `bronze_expanded` **table** for object arrays using `CROSS APPLY OPENJSON`;
- the original source columns, expanded fields, and an array-element index; and
- a non-null JSON filter only for array expansion, where a null payload has no child row.

Parent row preservation is mandatory for object expansion: routing Silver from raw
Bronze to `bronze_expanded` must not silently drop rows with null JSON.

### 4.4 Vocabulary enrichment

Importing schema YAML enriches the Bronze vocabulary with:

- `contentType "json"` and the JSON classification;
- inferred expanded properties for object fields;
- a virtual child `SourceTable` linked with `derivedFromJson` for object arrays;
- inferred physical types and sample values; and
- review metadata for unsupported or polymorphic shapes.

The expanded vocabulary gives mappings stable source-column IRIs. It does not make
sample-derived structure a governed business model.

### 4.5 Routing into Silver

`kairos-ext:silverSourceRef` on the target class switches the generated Silver wrapper
from a raw `source()` to the reviewed expanded or contracted `ref()`. The ontology and
Silver extension still own semantic keys, IRI, FKs, SCD policy, tests, and documentation;
the expanded model owns physical JSON unpacking.

For governed contracted transformations, the model contract is synchronized into a
managed virtual-source vocabulary and mapped like any other source. A replacement of a
raw Bronze table is only valid when the complete DD-093 authority chain agrees.

### 4.6 Current limits

- JSON structure inference is sample-based, not full-column validation.
- Arbitrary recursive nested-object flattening is not implemented.
- Primitive arrays and polymorphic payloads do not get generated expansion SQL.
- The legacy expansion renderer emits Fabric/T-SQL JSON functions. Databricks extraction
  detects JSON, but equivalent generated `GET_JSON_OBJECT`/`EXPLODE(FROM_JSON(...))`
  expansion is not yet implemented by this helper.
- The generated expansion must pass dbt parse/compile before adoption. The current
  Fabric flat-object template should be treated as draft-quality until its generated SQL
  is covered by an end-to-end adapter test.
- Complex or grain-changing JSON transformations belong in DD-092 contracted dbt, where
  adapter support, grain, keys, dependencies, tests, and decision evidence are explicit.

## 5. Silver projection extension

Silver physical policy belongs in
`model/extensions/{domain}-silver-ext.ttl`, not in the domain ontology. This preserves a
clean separation between business meaning and warehouse implementation.

### 5.1 Ontology-level controls

| Annotation | Purpose |
|---|---|
| `silverSchema` | Canonical target schema, normally `silver_{domain}`. |
| `namingConvention` | Physical naming conversion, normally `camel-to-snake`. |
| `includeNaturalKeyColumn` | Despite its legacy name, controls inclusion of the `{table}_iri` ontology-lineage column. |
| `auditEnvelope` | Controls the standard generated audit/lineage envelope in Silver DDL. |
| `inlineRefThreshold` | Maximum business-column count for Silver DDL reference-data inlining. |
| `silverIncludeImports` | Explicitly bulk-claims first-level imported classes, excluding peer hub domains. |

### 5.2 Class-level controls

| Annotation | Purpose |
|---|---|
| `scdType` | Selects SCD1 overwrite or SCD2 version history. |
| `scdValidFromColumn` | Selects a mapped business-effective timestamp for SCD2 validity. |
| `naturalKey` | Declares immutable semantic key properties used for warehouse identity and FK lookup. |
| `isReferenceData` | Marks a code/reference entity and changes default history and physical treatment. |
| `gdprSatelliteOf` | Isolates sensitive 1:1 attributes behind the parent identity in Silver DDL. |
| `inheritanceStrategy` | Selects table-per-concrete-class or explicit discriminator folding. |
| `silverInclude` | Claims an imported class for Silver materialization. |
| `silverExclude` | Keeps a semantic class but prevents its own Silver table. |
| `silverSourceRef` | Routes the generated wrapper through a reviewed expanded or contracted dbt model. |
| `partitionBy` / `clusterBy` | Documents or renders physical layout choices where supported. |

Every materialized class should declare its applicable policy explicitly rather than
relying on projector defaults. In particular, SCD type, reference-data status, natural
key, source routing, and inheritance choices are reviewable design decisions.

### 5.3 Property and relationship controls

| Annotation | Purpose |
|---|---|
| `silverColumnName` | Overrides a physical column or FK name. |
| `silverDataType` | Overrides the inferred physical type. |
| `nullable` | Overrides SHACL-derived nullability. |
| `silverForeignKey` | Marks a many-to-one object property as a Silver FK. |
| `silverForeignKeyOn` | Places a parent-to-child FK on the child/range table. |
| `silverForeignKeyTemporalMode` | Requires `current` or `as-of` resolution for an SCD2 parent. |
| `silverForeignKeyAsOfColumn` | Supplies the source event/effective timestamp for an as-of lookup. |
| `silverForeignKeyChangeDetection` | Controls whether relationship changes create a new SCD2 child version. |
| `junctionTableName` | Declares the bridge table for a many-to-many relationship. |
| `conditionalOnType` | Limits an FK to selected discriminator subtypes. |

Hub-local extension values override peer/default layers. Peer Silver extensions may
supply cross-domain target natural keys, while reference-model defaults remain the
lowest authored fallback. Built-in inference is last.

## 6. Gold dimensional and semantic-model projection

Gold converts reusable Silver entities into dimensional warehouse and Power BI
artifacts. Its source is the actual generated Silver model registry, so Gold cannot
silently select ontology properties that have no materialized Silver column.

### 6.1 Facts, dimensions, and bridges

G1 classifies each projected class as follows:

1. explicit `goldTableType` wins;
2. reference data is a dimension;
3. a GDPR satellite is a secured dimension;
4. a class with at least two outgoing FK relationships is inferred as a fact; and
5. remaining classes default to dimensions.

Gold applies `fact_`, `dim_`, and `bridge_` prefixes. An explicitly declared fact
generates FK columns for all its object properties because dimensional facts are
expected to carry their dimension keys. Auto-classified facts retain normal FK
qualification safeguards.

Facts do not receive SCD columns. Dimensions can inherit SCD2 policy and expose
`valid_from`, `valid_to`, and `is_current`. Reference data becomes a shared dimension.
Aggregate-table generation (G7) is deferred.

### 6.2 Measures

A datatype property with `measureExpression` becomes a DAX measure rather than a
physical Gold column. `measureFormatString` controls its display format. Measures are
emitted into the semantic model and the generated measures artifact.

Row-level shaping, joins, and grain belong in dbt. Reusable business metrics belong in
DAX. Reports should consume semantic-model measures instead of recreating metric logic
inside visuals.

Example:

```turtle
domain:orderAmount
    kairos-ext:measureExpression "SUM([order_amount])" ;
    kairos-ext:measureFormatString "#,##0.00" .
```

### 6.3 Hierarchies, date, and time intelligence

`hierarchyName` and `hierarchyLevel` group ordered columns into Power BI drill paths.
`generateDateDimension` generates a shared `dim_date` with a `YYYYMMDD` key.
`generateTimeIntelligence` adds a calculation-group scaffold with Current, YTD, QTD,
MTD, previous-year, and year-over-year calculations.

The generated calculation group is a reusable starting contract; measure semantics and
calendar assumptions still require business review.

### 6.4 RLS, OLS, and perspectives

Gold security projection currently supports:

- **GDPR RLS:** `gdprSatelliteOf` produces a secured dimension and a generated TMDL role
  named `Restrict_{table}` with `[is_authorized] = TRUE()` as its table filter.
- **Column OLS:** `olsRestricted true` adds the column to a `RestrictedColumns` TMDL role
  with metadata permission removed.
- **Perspectives:** a space-separated `perspective` annotation groups tables into named
  TMDL perspectives for discoverability and audience-focused model views.

Generated role definitions do not assign users or groups. Identity membership,
deployment bindings, and validation of the `is_authorized` entitlement logic remain
platform operational responsibilities. RLS is security-sensitive and must be reviewed;
the generated role is not evidence that access governance is complete. The projector
does not itself add or populate the `is_authorized` entitlement column, so the Gold data
contract must supply it before this RLS scaffold is operational.

`rolePlayingAs` and `degenerateDimension` are present in the extension vocabulary/design
surface but are not currently rendered by the Gold projector. They must not be reported
as active capabilities.

### 6.5 Gold projection extension

Gold policy belongs in `model/extensions/{domain}-gold-ext.ttl`.

**Ontology-level annotations**

| Annotation | Purpose |
|---|---|
| `goldSchema` | Gold warehouse schema, normally `gold_{domain}`. |
| `goldInheritanceStrategy` | Class-per-table by default; optional discriminator flattening. |
| `generateDateDimension` | Generates the shared date dimension. |
| `generateTimeIntelligence` | Generates a TMDL calculation-group scaffold. |
| `goldIncludeImports` | Bulk-claims first-level imported classes for Gold. |

**Class-level annotations**

| Annotation | Purpose |
|---|---|
| `goldInclude` | Claims an imported class for Gold. |
| `goldExclude` | Excludes a class from Gold while leaving Silver unchanged. |
| `goldTableType` | Overrides classification with `fact`, `dimension`, or `bridge`. |
| `goldTableName` | Overrides the physical table name; the dimensional prefix is retained. |
| `goldInheritanceStrategy` | Overrides inheritance strategy for one class. |
| `perspective` | Adds the table to one or more semantic-model perspectives. |
| `incrementalColumn` | Selects incremental loading for the generated Gold dbt model. |

**Property-level annotations**

| Annotation | Purpose |
|---|---|
| `goldColumnName` | Overrides the Gold physical/semantic column name. |
| `goldDataType` | Overrides the Gold SQL type. |
| `measureExpression` | Defines a DAX measure and removes the property from physical-column generation. |
| `measureFormatString` | Defines the DAX display format. |
| `hierarchyName` / `hierarchyLevel` | Defines ordered Power BI hierarchy levels. |
| `olsRestricted` | Adds the column to generated Object-Level Security metadata. |
| `degenerateDimension` | Reserved design annotation; not currently rendered. |
| `rolePlayingAs` | Reserved design annotation; current projector code does not render role-playing dimensions. |

### 6.6 Gold outputs

The Power BI/Gold projection can emit:

- Gold DDL, relationship documentation, views, and Mermaid ERDs;
- generated Gold dbt models consuming actual Silver refs;
- `dim_`, `fact_`, and `bridge_` tables;
- DirectLake-oriented TMDL table definitions and relationships;
- DAX measures and hierarchies;
- optional date and time-intelligence artifacts;
- RLS/OLS role definitions and perspectives; and
- a deterministic cross-domain master Gold ERD.

Power BI visuals are intentionally not generated. The semantic model is the governed
consumption contract; reports remain a separate presentation concern.

## 7. Contracted advanced dbt transformations

### 7.1 Why this boundary exists

Normal SKOS mappings intentionally cover straightforward column-level conformance:
rename, cast, default, filter, and bounded SQL expressions. They are not intended to
become a second workflow engine or a general relational transformation language.

Real source systems also require logic that is inherently relational or grain-forming.
Trying to encode that logic as RDF annotations would duplicate dbt, be difficult to
test, and blur ownership between semantic design and executable data engineering.

DD-092 therefore introduces a governed advanced-transformation boundary:

```text
Bronze source(s)
    -> authored contracted dbt model
    -> managed virtual-source vocabulary
    -> SKOS mapping
    -> generated Silver wrapper
    -> Gold
```

The custom model handles complex physical transformation. The generated Silver wrapper
still applies ontology-controlled identity, IRI lineage, FK resolution, SCD policy,
tests, and documentation. Advanced SQL extends the normal projection path; it does not
replace semantic governance.

### 7.2 Supported transformation patterns

Contracted transformations support patterns that exceed safe direct mappings:

| Pattern | Typical use |
|---|---|
| Multi-table joins | Combine headers, lines, parties, status tables, or normalized source fragments. |
| Window functions | Sequence events, calculate prior/next values, or identify effective intervals. |
| Ranking and deterministic deduplication | Select one row per governed key using an explicit partition, order, and tie policy. |
| Aggregation and grain change | Produce one row per approved business occurrence rather than one row per source record. |
| Multi-source unions | Normalize structurally different branches before semantic conformance. |
| Complex fallback rules | Select values from an approved precedence chain with explicit null behaviour. |
| JSON expansion | Unpack nested or repeated structures that exceed the simple generated `bronze_expanded` path. |
| Conditional derivation | Implement evidence-backed business rules that cannot be represented by one mapping expression. |
| Association formation | Build an explicit relationship/bridge grain from multiple inputs. |
| Survivorship preparation | Produce governed candidate values or a conformed record after identity and precedence decisions. |

Supported model materializations are `table`, `view`, and supported incremental
strategies. A contract may target Fabric, Databricks, or a valid non-empty subset of the
supported adapters. SQL must either be portable across every declared adapter or use
explicit adapter dispatch.

Custom macros are supported when namespaced with the hub or domain name. The reserved
`kairos_` prefix belongs to toolkit-generated macros. External package dependencies must
come from the toolkit-approved allow-list.

### 7.3 What the custom model must not own

The contracted model emits canonical business values. It must not generate final
ontology-aligned:

- Silver surrogate keys;
- OWL IRI columns;
- resolved Silver FK surrogate keys;
- SCD2 validity columns or `_row_hash`; or
- Gold dimensional and semantic-model behaviour.

Those concerns remain in the generated wrappers and projection extensions. If the
semantic target, properties, natural key, FK direction, or SCD policy needs to change,
the change must be made through the owning ontology, mapping, or Silver design surface
rather than hidden in custom SQL.

### 7.4 Contract as the physical authority

The dbt model properties YAML is the authoritative physical contract for the custom
model. It declares:

- model name and description;
- exact output column names, types, descriptions, and nullability;
- precise row grain, stated as “one row per ...”;
- physical key columns that realize the ontology natural key;
- target ontology class;
- stable virtual-source IRI;
- materialization;
- supported adapters;
- dependencies and approved packages;
- unit and data tests;
- optional canonical Bronze table IRIs replaced by the model; and
- evidence-backed `meta.kairos.decisions`.

Contract-first design is mandatory. Grain and identity are approved before columns, and
the output contract is approved before SQL implementation. This prevents working SQL
from silently establishing the wrong business grain.

Each non-trivial rule records its statement, evidence, confidence, approval state,
implementing model, and verifying tests. Decision metadata explains the implementation;
it is never interpreted as executable configuration.

### 7.5 LLM-authored and manually authored SQL

The toolkit does not assign authority based on who typed the SQL. A contracted model may
be:

- manually authored by a data engineer;
- drafted or refactored with LLM assistance;
- generated by an LLM and reviewed by a data engineer; or
- iteratively co-authored by both.

All routes are acceptable when the result satisfies the same contract and gates:

1. every source, column, relationship, and rule has repository evidence;
2. row grain, identity, overlap, deduplication, survivorship, and null policy are explicit;
3. SQL uses `source()` and `ref()` rather than hard-coded physical relations;
4. output columns and types exactly match the contract;
5. the model supports every adapter declared by the contract;
6. unit/data tests verify the recorded decisions and grain;
7. the managed virtual vocabulary is synchronized;
8. SKOS mappings bind the virtual columns to ontology properties;
9. `silverSourceRef`, natural key, FK, and SCD policy agree with the contract; and
10. dbt parse/compile and deterministic readiness/release gates pass.

Authorship is not approval. An LLM may propose or implement logic, but it cannot silently
approve business grain, identity, mappings, survivorship, security-sensitive behaviour,
or source replacement. In normal interactive mode, AI-inferred decisions remain
`proposed` until an authorized reviewer confirms them. In an explicitly activated
fleet-mode invocation, AI decisions are recorded as `ai_approved` with rationale,
confidence, and evidence; low-confidence, destructive, security-sensitive, PII, or
proprietary-risk decisions still require human input.

Manual authorship receives no weaker or stronger treatment: handwritten SQL must pass the
same contract, evidence, mapping, adapter, and test checks. Conversely, contract-compliant
LLM-authored SQL is not rejected merely because an LLM produced it.

### 7.6 Synchronization into the semantic pipeline

The contract is synchronized into a managed virtual-source vocabulary under
`integration/sources/custom-transformations/`. That generated vocabulary must never be
hand-edited.

The integration chain is:

1. author and approve the dbt contract;
2. implement SQL, macros, unit tests, and data tests;
3. synchronize the contract into the managed vocabulary;
4. map the virtual table and columns through SKOS;
5. set `silverSourceRef` on the approved target class;
6. confirm semantic natural keys, SCD policy, and FKs in the Silver extension;
7. project separately for each required adapter; and
8. validate the assembled dbt graph and runtime data behaviour.

If contract, mapping, and ontology disagree, the workflow returns to grain/identity
design. It does not force the SQL output into an unsuitable semantic target.

### 7.7 Governed source replacement

Some transformations replace a Bronze table that is unsafe to map directly because it
has the wrong grain, duplicates, nested structures, or required relational preparation.
`meta.kairos.replaces_sources` may assert that replacement using canonical Bronze
`SourceTable` IRIs.

Replacement is accepted only when all authority surfaces agree:

- an approved source-table claim targets the same semantic class;
- the contract names that target class and canonical replaced source IRI;
- synchronization emits the replacement assertion;
- the virtual table has a table-level `skos:exactMatch` to the class;
- `silverSourceRef` selects the contracted model; and
- no competing direct mapping or second replacement path exists.

This is a governed replacement assertion, not mechanically proven SQL lineage. Joined
tables that represent other entities are dependencies, not replaced sources.

### 7.8 Testing and production-readiness

Unit tests should cover ranking, windows, fallback branches, edge cases, and regressions.
Data tests should cover key uniqueness/non-nullness, accepted values, relationships,
fan-out, and the declared grain. Fixtures must not contain raw PII, secrets, credentials,
or proprietary samples.

Toolkit validation can prove contract shape, synchronization, Jinja/SQL parseability,
dependency edges, references, adapter declarations, and compile behaviour where the
environment permits. It cannot prove live data grain or runtime correctness without a
configured warehouse. Warehouse-backed tests remain required before production
publication.

### 7.9 Current boundaries

- Arbitrary SQL is not parsed into verified row- or column-level lineage.
- A `replaces_sources` declaration is governance metadata, not lineage proof.
- Only explicit repository-contained models and contracts participate in the governed
  pipeline; imported prototype SQL remains non-executable evidence until assessed.
- Contract changes require re-synchronization and may require mapping or Silver review.
- Breaking contract changes require an explicit downstream migration independent of the
  toolkit release version.
- Complex logic must remain self-contained, collision-free, and within approved package
  and macro boundaries.

## 8. Applied data-engineering rules

| Rule | State | Manual engineering replaced | Generated or validated behaviour |
|---|---|---|---|
| Direct Bronze consumption | Applied by dbt | Source plumbing and staging boilerplate | Uses declared `source()` references or a governed contracted `ref()`. |
| Canonical physical naming | Applied by dbt | Repeated naming conversion | Applies the configured naming convention and canonical Silver schema. |
| Source-to-domain column mapping | Applied by dbt | Handwritten select lists | Projects mapped properties and applies physical aliases. |
| Type conversion | Applied by dbt | Manual casts | Converts source/XSD types to platform-aware target types. |
| Mapping transforms | Applied by dbt | Repetitive expression SQL | Renders approved `kairos-map:transform` expressions. |
| Default values | Applied by dbt | Null fallback SQL | Renders `COALESCE` from `kairos-map:defaultValue`. |
| Source filters | Applied by dbt | Entity-specific `WHERE` clauses | Applies table mapping filter conditions in source CTEs. |
| Deterministic surrogate keys | Applied by dbt | Key-generation macros and conventions | Generates warehouse keys from the declared natural-key components. |
| Natural-key completeness | Validated | Manual key coverage review | Rejects bound models without a natural key and unsafe multi-source branches with incomplete keys. |
| Ontology IRI lineage | Applied by dbt | Semantic lineage columns | Generates a stable entity IRI alongside the surrogate key. |
| Row-level source lineage | Applied by dbt | Audit-column conventions | Emits source system, immutable source-record identity, and load timestamp. |
| SCD1 loading | Applied by dbt | Merge/upsert models | Generates incremental materialization keyed by the entity surrogate key. |
| SCD2 loading | Applied by dbt | Change detection and version-closing SQL | Generates hash comparison, version sequencing, closing of current rows, and composite merge identity. |
| Sub-day source history | Applied by dbt | Custom ordering/window logic | Uses timestamp precision plus `LAG`/`LEAD` to retain multiple source versions per key. |
| Hash-based change detection | Applied by dbt | Wide row comparison | Computes `_row_hash` from history-participating attributes. |
| FK history participation | Applied by dbt | Relationship-change logic | Includes resolved FKs in `_row_hash` by default; supports explicit exclusion. |
| FK lookup inference | Applied by dbt | Natural-key lookup joins | Infers an FK join when exactly one unambiguous target-natural-key mapping exists. |
| Current SCD2 FK lookup | Applied by dbt | Safe current-parent joins | Adds `is_current = 1` to prevent child-row multiplication. |
| As-of SCD2 FK lookup | Applied by dbt | Temporal range joins | Joins source event time to the parent's `[valid_from, valid_to)` interval. |
| Temporal FK safety | Validated | Manual effective-date review | Rejects as-of lookup without a mapped parent business-validity column. |
| Cross-domain canonical ownership | Applied by dbt | Duplicate model avoidance | References the owning domain model rather than rematerializing an entity. |
| Multi-source conformance | Applied by dbt | Per-source normalization and unions | Generates one view per source, a canonical superset, typed null padding, and a parent union model. |
| SHACL tests | Applied by dbt | Hand-authored schema tests | Generates nullability, uniqueness, accepted-value, regex, and length tests. |
| FK relationship tests | Applied by dbt | Referential-integrity tests | Adds dbt `relationships` tests and `not_null` where required. |
| SCD2-aware uniqueness | Applied by dbt | Custom filtered uniqueness tests | Tests surrogate-key and IRI uniqueness only where `is_current = 1`. |
| Inheritance property handling | Applied by dbt | Repeated inherited column mapping | Inherits unprojected ancestor properties; discriminator folding occurs when configured. |
| Cross-table mapping diagnostics | Validated | Manual source-column trace review | Warns when an entity property requires a join not represented by the normal mapping path. |
| Unbound-target release gate | Validated | Manual completeness checklist | Keeps approved but unbound targets release-blocking, with optional typed design stubs. |
| Generated artifact validation | Validated | Manual Jinja/ref review | Checks generated Jinja and model references before accepting artifacts. |
| Adapter portability | Applied by dbt | Fabric/Databricks SQL forks | Uses platform-aware types and Kairos macros while preserving one semantic contract. |

## 9. Silver DDL rules related to dbt

The Silver DDL projector also encodes physical design conventions. Data engineers should
know about them even where the dbt runtime does not yet implement the same behaviour.

| Rule | State | Behaviour |
|---|---|---|
| Spark/Fabric-native types | Silver DDL only | Uses `BOOLEAN`, `TIMESTAMP`, `STRING`, and `DOUBLE`. |
| Constraint documentation | Silver DDL only | Emits PK, FK, and UNIQUE definitions as comments where Fabric cannot enforce them. |
| `_row_hash` column | Silver DDL and dbt | DDL declares storage; SCD2 dbt models calculate the hash. |
| `_deleted_at` | Silver DDL only | DDL provides the soft-delete timestamp, but generated dbt models do not currently populate it. |
| Small-reference inlining | Silver DDL only | Reference tables at or below `inlineRefThreshold` can be denormalized into the parent DDL shape. |
| GDPR satellite shape | Silver DDL only | Sensitive 1:1 satellites use the parent key and can be secured separately. |
| Canonical schema ownership | Silver DDL and dbt | Each class belongs to one owning Silver domain. |
| Plain entity names | Silver DDL and dbt | `dim_` and `fact_` prefixes are reserved for Gold. |

Inheritance flattening is not unconditional. The implemented projector folds subtypes
when the projected parent uses `inheritanceStrategy "discriminator"`; otherwise the
default table-per-concrete-class behaviour is retained.

## 10. Recognized gaps

### 10.1 Deduplication annotations

`kairos-map:deduplicationKey` and `kairos-map:deduplicationOrder` are currently parsed,
but the dbt projector does not render a `ROW_NUMBER()` or equivalent deduplication step.
They must not yet be reported as applied rules.

Deduplication that is essential to grain or identity should use a governed contracted
dbt transformation until generated support is implemented.

### 10.2 Soft-delete execution

The Silver DDL includes `_deleted_at`, but generated dbt models do not currently derive
or maintain it from source deletion signals. Source-specific delete semantics therefore
require a contracted transformation or downstream implementation.

### 10.3 Reference-data inlining parity

Small-reference inlining is represented by the Silver DDL projector. Generated dbt
entity models do not currently provide equivalent denormalized runtime behaviour.

## 11. Recommended projection report

The existing dbt projection report lists generated models, SCD type, source count,
column count, FK join count, skipped classes, and warnings. It should be extended with
an **Applied Data Engineering Rules** section.

For every entity, the report should expose:

| Field | Example |
|---|---|
| Entity and grain | `Invoice -- one issued invoice` |
| Source binding | `erp.invoice_header` |
| Natural key | `invoiceNumber` |
| Warehouse identity | `invoice_sk` generated from `invoiceNumber` |
| Materialization | `incremental, SCD2` |
| Change-detection columns | `status, amount, customer_sk` |
| Effective-time source | `invoice_effective_at` or projection timestamp |
| FK rules | `customer_sk: current lookup; participates in history` |
| Multi-source policy | `two normalized source views plus conformed union` |
| Mapping logic | transforms, defaults, filters, and contracted source reference |
| Generated tests | not-null, current-row unique, relationships, accepted values |
| Lineage | source system, source record ID, ontology/source IRIs |
| Applied design rules | stable rule identifiers with implementation evidence |
| Non-applied annotations | recognized annotations that did not affect generated SQL |
| Warnings and blockers | unresolved joins, incomplete keys, unbound claims |

The report should describe evidence, not merely claim compliance. Each rule should point
to the annotation, mapping, shape, contract, or projector convention that caused it to
be applied.

## 12. Summary for data engineers

The generated Silver package is not only a collection of select statements. It embeds a
repeatable engineering policy:

- preserve source identity and semantic lineage;
- require explicit grain and immutable natural keys;
- conform sources before combining them;
- preserve business history where it has value;
- resolve relationships with explicit temporal semantics;
- derive executable tests from the semantic model;
- isolate complex custom logic behind governed contracts;
- keep Silver reusable and move report semantics to Gold;
- generate platform-specific SQL from a portable semantic contract; and
- refuse to present incomplete or unsafe models as release-ready.

These choices are the main value of the projector: they turn recurring manual
data-engineering decisions into reviewable, deterministic, and consistently generated
contracts.
