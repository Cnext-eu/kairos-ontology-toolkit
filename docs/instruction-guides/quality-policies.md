# Quality & Policy Reference — Kairos v5

This guide explains **every check the Kairos compiler performs on a Silver/Gold model**: the
non-suppressible safety kernel, the six Silver policies (identity, multi-source, incremental, hash,
temporal, data quality), the Gold policies (tables, measures, calendar, security), and the
cross-cutting adapter-capability and deviation governance.

It is grounded in the compiler source:

| Concern | Module |
|---|---|
| Safety kernel | `core/compiler/quality.py` |
| Policy catalogue & enums | `core/projections/dbt/policy_specs.py` |
| Normalization / validation | `core/projections/dbt/policy_normalize.py` |
| Executable dbt rendering | `core/projections/dbt/quality_renderers.py` |

## Contents

1. [Design principles](#1-design-principles)
2. [Layer 0 — Safety kernel (structural, non-suppressible)](#2-layer-0--safety-kernel)
3. [Silver policies](#3-silver-policies)
   - [3.1 Identity (DD-108)](#31-identity--dd-108)
   - [3.2 Multi-source (DD-108)](#32-multi-source--dd-108)
   - [3.3 Incremental (DD-109)](#33-incremental--dd-109)
   - [3.4 Canonical hash (DD-109)](#34-canonical-hash--dd-109)
   - [3.5 Temporal FK (DD-109)](#35-temporal-fk--dd-109)
   - [3.6 Data quality (DD-115)](#36-data-quality--dd-115)
4. [Gold policies](#4-gold-policies)
   - [4.1 Gold tables (DD-112)](#41-gold-tables--dd-112)
   - [4.2 Measures (DD-113)](#42-measures--dd-113)
   - [4.3 Calendar (DD-113)](#43-calendar--dd-113)
   - [4.4 Security RLS/OLS (DD-113)](#44-security-rlsols--dd-113)
5. [Which checks become dbt tests](#5-which-checks-become-dbt-tests)
6. [Cross-cutting governance](#6-cross-cutting-governance)
   - [6.1 Adapter capability evidence (DD-111)](#61-adapter-capability-evidence--dd-111)
   - [6.2 Approved deviations (DD-114)](#62-approved-deviations--dd-114)
7. [How policies wire together](#7-how-policies-wire-together)
8. [Authoring & verifying](#8-authoring--verifying)

---

## 1. Design principles

Five principles apply to **all** policies below:

- **Authored, not auto-defaulted.** Every policy is built from authored RDF facts. There is no
  implicit "not-null on every column" or silent capability grant. A check exists only if authored.
- **Fail-closed.** Missing, ambiguous, or contradictory input raises a `PolicyNormalizationError`
  and stops the compile — it is never silently dropped or defaulted to a permissive value.
- **Deterministic & immutable.** Specs are frozen dataclasses carrying `PolicyProvenance`. Rules
  carry a stable SHA-256 hash, so identical facts always compile to an identical plan.
- **Governed authority only.** Executable checks must reference toolkit-owned tests/macros;
  arbitrary SQL is not accepted as quality or capability authority.
- **Emit ≠ operate.** The compiler emits executable contracts. Execution, monitoring, alerting, and
  trend storage remain downstream — passing compilation does not replace running the tests.

Design-decision numbering used throughout: **DD-108** identity/multi-source, **DD-109**
incremental/hash/temporal, **DD-111** adapter capability, **DD-112** Gold tables, **DD-113**
Gold semantics (measures/calendar/security), **DD-114** deviations, **DD-115** data quality.

---

## 2. Layer 0 — Safety kernel

`core/compiler/quality.py` runs a small, **closed, non-suppressible** catalogue that decides whether
executable SQL may be emitted **at all**. It is structural — it does not inspect data content; it
validates that the resolved binding is coherent. All other policies assume the kernel passed.

| Rule code | Fires when |
|---|---|
| `safety.grain-missing` | binding has no materialized grain columns |
| `safety.identity-incomplete` | binding has no source identity key |
| `safety.identity-role-collision` | identity roles collide |
| `safety.source-unresolved` / `.column-unresolved` | source relation / column cannot be resolved |
| `safety.class-unresolved` / `.property-unresolved` | canonical class / property cannot be resolved |
| `safety.type-incompatible` | source/target types are incompatible |
| `safety.expression-unsafe` | an expression is not statically safe |
| `safety.relationship-endpoint` | a relationship target is not in compile scope, its property does not resolve, or the property's declared `rdfs:domain`/`rdfs:range` does not cover the authored endpoints (a `target:` that is the declared range **or a subclass of it** is accepted; a superclass is not) |
| `safety.incremental-identity-incomplete` | incremental identity is incomplete |
| `safety.adapter-unsupported` | the adapter cannot support a required construct |
| `safety.artifact-collision` | duplicate binding name, or two entities own one artifact |

These codes are **stable and cannot be suppressed** by any authored policy.

---

## 3. Silver policies

Each Silver policy is authored as RDF facts and normalized into an immutable effective spec.

### 3.1 Identity — DD-108

`_normalize_identities` establishes *how each canonical entity's key is formed* and wires in the
other Silver policies. It is the hub of the policy graph.

**Required authored fields** (each missing raises its own error): `identityStrategy`,
`businessGrain`, `keyScope`, `entityInstanceIriPolicy`, `lineagePolicy`, `changeDetectionStrategy`.

**Identity strategy and its constraints (`IdentityStrategy`):**

| Strategy | Requires | `keyScope` must be | Notes |
|---|---|---|---|
| `business-key` | ≥1 `naturalKey` | (any) | authoritative business identity |
| `source-scoped-immutable-key` | — | `source-table` / `source-table-array-element` | physical source key |
| `deterministic-integration-key` | `naturalKey` components | `domain` / `enterprise` | **requires** a multi-source policy with *approved exactly-equivalent* branches |
| `externally-mastered-identifier` | `naturalKey` id columns | `enterprise` | routed to MDM |
| `surrogate-only` | **forbids** `naturalKey`; **requires** `reconciliationLimitation` | `source-table*` | join key only; asserts no domain identity |

**Other validations:**

- **Source identities**: refs must be unique, each known (bound by an EntityBinding or a dbt
  ContractIdentity), and must enumerate *exactly* the actual prepared contributors — no missing and
  no extra (`identity.source-contributor-mismatch`).
- **Contract identity**: contract-output identity that is not verified against passing uniqueness +
  non-null evidence tied to the contract content hash raises a blocking `identity.contract-unverified`
  issue. SCD1/SCD2 contract identity requires canonical CDC output bindings (operation,
  source-update, business-effective, ingestion) → `identity.contract-cdc-incomplete`.
- **Natural keys**: components unique and explicitly ordered; camelCase → snake_case normalized.
- **Change detection** (`ChangeDetectionStrategy`: `compare-columns` | `canonical-hash` | `none`):
  `canonical-hash` requires a declared `HashPolicy` ref; any other strategy forbids one.
- **Driving source**: a single contributor is auto `only-source`; multiple contributors require an
  explicit `drivingSource` chosen from the declared source identities.
- **IRI policy** (`EntityIriMode`): `emit` | `omit`.

**Cross-references validated:** `multiSourcePolicy` (required iff >1 source), `hashPolicy`,
`incrementalPolicy` — each must exist and be mutually consistent.

Produces `EntityIdentitySpec` (source / business / integration / mastered / surrogate / IRI /
driving-source / change-detection / lineage sub-policies, incl. timestamp semantics below).

**Timestamp semantics** (`_timestamp_semantics`): derives four canonical audit columns —
`_loaded_at` (always supplied by one injected run clock), `_ingested_at`, `_source_updated_at`,
`_source_effective_at` — per source, each marked `supplied` or `NOT_SUPPLIED`. No timestamp is
silently substituted for another.

### 3.2 Multi-source — DD-108

`_normalize_multi_source` governs entities fed by several source branches. The relationship and
precedence are tightly coupled — a mismatch is rejected.

| `branchRelationship` | required `sourcePrecedence` | conflict/collision restriction |
|---|---|---|
| `disjoint` | `not-applicable-disjoint` | — |
| `overlapping` | `none-without-approved-exact-equivalence` | retains branch identity |
| `exactly-equivalent` | `declared-order:<sources>` (unique, non-empty) | **cannot** `retain-branch-values` / `retain-source-scoped-identities` |

Additional authored fields: **`conflict`** (`ConflictAction`: `block`/`quarantine`/`retain-branch-values`),
**`collision`** (`CollisionAction`: `block`/`quarantine`/`retain-source-scoped-identities`),
**`deletion`** (`BranchDeleteAction`), **`lateArrival`** (`BranchLateArrivalAction`),
**`normalization`** text, and **`reconciliationTests`** (row-level rule refs; approved only when
exactly-equivalent). Produces `MultiSourcePolicySpec` including `ExactEquivalenceSpec(approved=…)`.

### 3.3 Incremental — DD-109

`_normalize_incremental` is the single load-execution authority per Silver model (one policy per
resource; duplicates rejected).

- **`totalOrder`** tie-breakers — required, non-empty, unique/ordered (`incomplete-order` /
  `duplicate-order-term`).
- **Runtime field distinctness** — `cdcOperation`, `sourceUpdatedAt`, `sourceEffectiveAt`,
  `ingestedAt` must all be distinct columns (`ambiguous-runtime-fields`).
- **`lookbackWindow`** — `positive-int (hours|days)`.
- **Delete semantics** — `hardDelete` and `softDelete` (`DeleteAction`:
  tombstone/ignore/quarantine/block/apply-operation).
- **`lateArrival`** (`LateArrivalAction`), **`correction`** (`CorrectionAction`:
  replace-by-total-order / revise-valid-time / append-correction / quarantine / block), **`replay`**
  (idempotent-merge / full-rebuild / block), **`backfill`** (full-rebuild-approved /
  range-replay-approved / block), **`schemaChange`** (`SchemaEvolutionAction`: fail /
  append-compatible).

Supported CDC operations are fixed by policy v1: insert, update, delete, soft-delete, snapshot.
Produces `IncrementalPolicySpec` with `CdcOrderingSpec` and `SchemaEvolutionSpec`.

### 3.4 Canonical hash — DD-109

`_normalize_hashes` defines the change-detection hash contract (one per resource; duplicates
rejected). Everything is pinned to contract **v1**:

- **`algorithm`** must equal `SHA-256`.
- **`version`** must equal `1`.
- **`inputs`** must be an ordered RDF list, unique (`unordered-inputs` / `duplicate-input`).
- **`nullRepresentation`** must be `typed-length-delimited-null`.
- `encoding` fixed to `ordered-typed-length-delimited`.

Produces `CanonicalHashPolicySpec`.

### 3.5 Temporal FK — DD-109

`_normalize_temporal` governs temporal foreign-key resolution per property.

- **`mode`** (`TemporalMode`): `current` | `as-of` | `none`.
- **`as-of` mode is strict** — requires `as_of_column`, `interval`, `time_zone`, `precision`
  together (any of these on a non-`as-of` mode → `contradictory-details`), and further:
  - interval must be `closed-open` `[from, to)`,
  - time zone must be `UTC`,
  - precision must be `microsecond`.
- **`cardinality`** (`LookupCardinality`: `zero-or-one` | `exactly-one`).
- **`missingAction` / `ambiguousAction` / `lateParentAction`** (`ParentAction`); ambiguous must be
  `fail` / `quarantine` / `retry`.
- **`changeDetection`** participation flag is mandatory (`change-detection-missing`).

Produces `TemporalRelationshipSpec`.

### 3.6 Data quality — DD-115

`_normalize_dq` (+ `_normalize_dq_expression` / `_normalize_dq_tolerance`) authors row- and
aggregate-level content checks. **This is where "null checks" live.**

**Authoring surface — class-attached (active on the v5 `compile` path).** A DQ rule is authored as a
`kairos-ext:DataQualityRule` individual in the domain ontology and attached to a canonical
`owl:Class` via `kairos-ext:dataQualityRule`. The v5 compiler collects these individuals while the
ontology graph is still loaded (`resolve_scope`), threads them graph-free through the plan, and emits
their artifacts on `--emit` and surfaces them per entity on `--explain` (`dq-rule:` lines). A rule
attached to more than one governing class is rejected.

**Attachment vs `dqScope`.** The class the rule is *attached to* is its **governing entity** — it
selects which Silver model the rule runs against. `dqScope` names the target *within* that entity:
for an entity-level rule `dqScope` is the governing class itself; for a property/relationship-level
rule the attachment picks the entity and `dqScope` names the property/relationship. The governing
class disambiguates scopes that would otherwise resolve to multiple entities (`dq.scope-owner-conflict`
when the attachment and scope disagree).

**The nine governed check kinds (`DqCheckKind`):**

| Check kind | Purpose | Required parameters | Row-level predicate (failure detection) |
|---|---|---|---|
| `contract-shape` | Required columns present & populated — **the null check** | `required` | `col is null` OR-ed across every required column |
| `range` | Numeric/value bounds | `column`, `minimum`/`maximum` | `col < minimum` or `col > maximum` |
| `distribution` | Value in an allowed set | `column`, `allowed` | `col is null or col not in (allowed…)` |
| `referential-coverage` | FK exists in a parent model | `column`, `parent_model`, `parent_column` | `col is null or not exists (…parent…)` |
| `cross-field` | Relation between two columns | `left`, `operator`, `right` | null-aware `eq/ne/lt/lte/gt/gte` |
| `duplicate-rate` | Uniqueness over key columns | `columns` | aggregate macro |
| `freshness` | Recency of a timestamp | `column`, `unit` (`hours`/`days`) | aggregate macro |
| `volume` | Row-count expectation | `metric` (= `row-count`) | aggregate macro |
| `reconciliation` | Match another model on a metric | `compare_model`, `metric` (+opt. `column`, `compare_column`) | aggregate macro |

**How a null check works:** there is *no* standalone `not_null`. A required-column null test is a
**`contract-shape`** rule listing the columns; it renders as `source."a" is null or source."b" is
null …` and is fail-closed (tolerance forced to 0). `distribution` and `referential-coverage` *also*
treat null as failure.

**Every rule must supply** (else compile error): unique `rule_id`+`version`; `check_kind`; the exact
required parameters; a toolkit-owned test ref `kairos.dq.<check-kind>.v1` (arbitrary SQL rejected →
`dq.unsupported-test-reference`); `tolerance`, `action`, `category`, `scope`, `severity`,
`owner_role`, `evidence`; and a deterministic `rule_hash`.

**Tolerance is derived from the check kind:**

| Check kind | Tolerance kind | Constraint |
|---|---|---|
| `contract-shape` | count | **fail-closed → must be `0`** |
| `volume` | count | integer; metric = `row-count` |
| `freshness` | duration | unit ∈ {hours, days} |
| `duplicate-rate` / `range` / `distribution` / `referential-coverage` / `cross-field` | ratio | `0 ≤ x ≤ 1` |
| `reconciliation` | absolute-difference | `x ≥ 0` |

**Severity / action / effect:** `severity` ∈ info/warning/error/critical; `category` ∈
contract/source/business/operational; `action` drives routing:

| Action | dbt test severity | Row routing |
|---|---|---|
| `block` | `error` | source rows **not** released |
| `warn` | `warn` | rows released; failure reported only |
| `quarantine` | `warn` | failing rows → explicit quarantine relation (immutable lineage); passing rows → accepted view; release requires passing recheck |

**Compiler emits per rule:** a persistent result table in the `quality` schema (calling
`kairos_dq_<kind>(...)`), a singular dbt test, an accepted view (passing rows), a quarantine relation
(rejects with full source lineage), and a portable JSON-Schema runtime contract.

#### Authoring guidance — `reconciliation` and row-count checks

`reconciliation` (and any row-count comparison) is **grain-sensitive**. A row-count reconciliation
is only meaningful when the two relations share a grain; comparing a re-grained/deduped model
against a raw upstream relation produces legitimate-but-false failures. Apply it deliberately, not
across the board:

- **DQ rules are authored-only** — there is no auto-applied `reconciliation`. Every rule is already
  an explicit per-binding decision, so "blanket-applying" is never the default.
- **The dividing line is grain alignment, not "raw relation vs contracted dbt model."** In v5, grain
  changes live in the dbt model and a binding maps *one relation/model at its grain* to one entity.
  Therefore:
  - reconciling a Silver entity against its **immediate source** (the exact `source.dbtModel` or
    relation the binding reads) is safe — including contracted `dbtModel` sources, because counts
    align there by definition;
  - the false-failure risk appears only when reconciling against a **raw upstream** that sits behind
    a re-graining/deduplicating model.
- **Pick the right check for the intent:**
  - cross-model equivalence at equal grain → `reconciliation` (tolerance is absolute-difference, so a
    delta can be allowed);
  - absolute row-count expectations → `volume` (metric `row-count`);
  - uniqueness / dedup / survivorship → `duplicate-rate`, not a row-count reconciliation.

**Rule of thumb:** author `reconciliation` wherever a genuine equal-grain compare target exists
(raw *or* the immediate contracted model), and omit it where no equal-grain counterpart exists.

---

## 4. Gold policies

Gold policies shape the downstream BI/semantic layer and consume the Silver CompilePlan.

### 4.1 Gold tables — DD-112

`_normalize_gold_table` validates one dimensional table. The **role determines which fields are
allowed** — declaring another role's fields is rejected.

| `role` (`GoldTableRole`) | Requires | Forbids |
|---|---|---|
| `fact` | `factGrain`, `factType`, `dimensionVersionBinding`; optional `correction`, `lateArrival` | bridge/dimension-only policy |
| `dimension` | `dimensionExposure`, `dimensionVersionBinding` | fact/bridge grain/type/version policy |
| `bridge` | `bridgeGrain`, exactly **two distinct** `bridgeEndpoint`s, two `bridgeEndpointBinding`s, `bridgeCardinality`, `bridgeAllocationSemantics`; optional `bridgeWeightColumn` | fact/dimension-only policy |

Every table requires `goldSourceModel` + `goldSourceVersion`. Table name defaults deterministically
to `<fact|dim|bridge>_<snake_case(local-name)>`. Produces `GoldTablePolicySpec`.

The product wrapper (`_normalize_gold`) additionally checks: a `goldProductProfile` + explicit
`goldSchema` are present when Gold resources exist; every measure is linked from the product
(`gold.unlinked-measure`); and calendar/security refs each resolve to exactly one resource.

### 4.2 Measures — DD-113

`_normalize_measures` validates semantic measures with a dependency graph.

- **Dependency cycle** detection across `measureDependencies` → `measure.dependency-cycle`.
- Unique `measure_id`; all `measureDependencies` must resolve (`unknown-dependency`).
- **Lifecycle gating** (`MeasureLifecycle`: `intent` | `provisional` | `validated` | `approved`):
  - non-`intent` requires an `expression` **and** ≥1 dependency, plus `measureDataType`,
    `measureFormatString`, `measureFolder`.
  - `validated`/`approved` additionally require tests **and** validation evidence.
  - `approved` additionally requires an owner role.
- `measureDataType` ∈ {string, boolean, int64, decimal, double, datetime, currency, percentage}.

Produces `MeasureSpec`.

### 4.3 Calendar — DD-113

`_normalize_calendar` validates the date-dimension profile:

- `startDate` ≤ `endDate`, both ISO `YYYY-MM-DD` (`invalid-date` / `invalid-range`).
- `fiscalYearStartMonth` an integer 1–12.
- `calendarApprovalStatus` ∈ {draft, approved}.
- Plus `weekPattern`, `locale`, `holidaySource`, `timeZone`, `periodClosure`, and
  `rolePlayingDates`. Produces `CalendarProfileSpec`.

### 4.4 Security RLS/OLS — DD-113

`_normalize_security` validates row-/object-level security:

- **`failClosed` must be true** (`security.not-fail-closed`) — a permissive security policy is
  rejected outright.
- Positive **and** negative test evidence is required (`security.test-evidence-missing`).
- Plus `entitlementSource`, `identityMapping`, `rolePolicies`, `filterDirection`, `bindings`.
  Produces `SecurityPolicySpec`.

---

## 5. Which checks become dbt tests

Not every policy emits a dbt test — some only shape SQL, metadata, or lineage. The table below maps
each policy to the **dbt tests actually rendered** into the schema YAML / model files. Two kinds are
emitted: **generic column tests** (`not_null`, `unique`) and **custom/singular tests** (toolkit
macros run as data tests).

| Policy | dbt test(s) emitted | Where |
|---|---|---|
| **Identity (DD-108)** | `unique` on integration-identity, surrogate-join-key, and entity-IRI columns; `unique` on the single grain column. Under SCD2 these become `unique` with `config.where: <current_flag> = 1` | `shape.py` column tests |
| **Nullability (from identity/binding)** | `not_null` on every column whose committed nullability is `false` | `shape.py` column tests |
| **Incremental (DD-109)** | model-level data tests `kairos_runtime_total_order`, `kairos_runtime_replay_idempotent`, `kairos_runtime_cdc_contract`, `kairos_runtime_delete_policy`; plus `kairos_runtime_one_current` and `kairos_runtime_half_open_intervals` under SCD2 | `shape.py` `data_tests` |
| **Temporal FK (DD-109)** | one `kairos_temporal_fk_cardinality` data test per relationship (mode, cardinality, missing/ambiguous action) | `shape.py` `data_tests` |
| **Data quality (DD-115)** | one **singular dbt test** per DQ rule over the rule's result relation (`severity=error` for `block`, else `warn`; tagged `kairos-dq` + category) | `quality_renderers.py` `render_dq_test` |
| **Gold tables (DD-112)** | `not_null` on non-nullable columns; `unique` on the primary key | `gold_render.py` |
| **Gold calendar (DD-113)** | `not_null` + `unique` on `date_key` and `full_date` of the generated `dim_date` (only when the calendar is approved) | `gold_render.py` |
| **Measures (DD-113)** | governed `validationTests` references (required for `validated`/`approved` lifecycle) carried as test evidence | `_normalize_measures` |
| **Security RLS/OLS (DD-113)** | governed `positiveTests` + `negativeTests` references (evidence required) | `_normalize_security` |
| **Multi-source (DD-108)** | `reconciliationTests` references (row-level, approved only for exactly-equivalent) carried in model metadata | `shape.py` metadata |

Policies that emit **no** dbt test (they only shape SQL, hashing, or lineage): **canonical hash**
(DD-109), **change-detection strategy**, **IRI policy**, and the **timestamp-semantics** lineage
columns. The **safety kernel** (Layer 0) is not a dbt test either — it is a compile-time gate.

> `not_null` is therefore emitted **two ways**: as a generic dbt test on non-nullable columns
> (above), and — for explicitly required columns — as a DD-115 `contract-shape` rule with its own
> result relation and singular test. The former guards declared column nullability; the latter is a
> governed, tolerance-0 quality contract with quarantine/block routing.

---

## 6. Cross-cutting governance

### 6.1 Adapter capability evidence — DD-111

`_validate_adapter_evidence` records, per `(adapter, version, scope, capability)`, an
`AdapterEvidenceStatus` (`supported` | `deviation-required` | `unsupported`):

- Conflicting statuses for the same key → `adapter-evidence.contradictory-status`.
- `supported` without successful compile evidence → non-blocking `adapter-evidence.compile-missing`.
- Any non-`supported` status raises an issue so strict release cannot treat it as supported.

The `AdapterCapability` catalogue covers constructs such as canonical types/hash, incremental
SCD1/SCD2, JSON scalar/array-child, merge-upsert, delete semantics, window functions, total
ordering, temporal lookups, schema evolution, conformance union/deduplicate, contracted dbt source,
constraints, quarantine, dbt tests, RLS/OLS, and TMDL.

### 6.2 Approved deviations — DD-114

`_normalize_deviations` is how anything **unsupported** is allowed only with explicit governed
approval:

- `approvalStatus` must be `approved`; anything else raises `deviation.not-approved`.
- `reviewDate`/`expiryDate` are ISO dates and `expiry` must not precede `review`
  (`invalid-date` / `expiry-before-review`).
- Optional `adapterName` must be a known adapter. Plus `policyReference`, `scope`, `rationale`,
  `ownerRole`, `evidence`. Produces `ApprovedDeviationSpec`.

---

## 7. How policies wire together

**Identity is the hub.** It references, and validates the existence and mutual consistency of:

```
EntityIdentity ──▶ MultiSourcePolicy   (required iff >1 source; forbidden if 1)
             ├──▶ HashPolicy          (required iff change detection = canonical-hash)
             └──▶ IncrementalPolicy    (load-execution authority)
Temporal FK  ──▶ (per property; feeds change-detection participation)
DataQuality  ──▶ (independent per-rule; routes rows via quarantine/accepted)
Gold product ──▶ GoldTables + Measures + Calendar + Security  (consume Silver plan)
AdapterEvidence / Deviations  ── gate what constructs may be emitted per adapter
```

All specs are frozen and carry provenance; combined with rule hashes this makes the whole compile
deterministic and reproducible.

---

## 8. Authoring & verifying

Author Silver policies inside a closed `EntityBinding` (skill `kairos-design-mapping`); author Gold
policies via `kairos-design-gold`. Then iterate:

```bash
uv run kairos-ontology compile <domain> --check --format json
uv run kairos-ontology compile <domain> --explain --format json
uv run kairos-ontology compile <domain> --emit
```

- `--check` surfaces the diagnostics in this guide (`safety.*`, `identity.*`, `multi-source.*`,
  `incremental.*`, `hash.*`, `temporal-fk.*`, `dq.*`, `gold.*`, `measure.*`, `calendar.*`,
  `security.*`, `adapter-evidence.*`, `deviation.*`).
- `--explain` shows each effective policy value with its provenance and (for DQ) its rule hash.
- `--emit` writes the executable dbt artifacts.

### Where to see what policy and DQ tests are applied

| I want to see… | Use |
|---|---|
| Per-binding policy + every focused DQ check and the dbt test it emits | `compile <domain> --explain --format json` → each `entity.quality[]` (`kind`, `columns`, `emittedTest`) and `entity.emittedTests` (singular test files); the text output prints a `dq:` line per check |
| A human-readable per-binding review of the above | skill **`kairos-execute-report`** |
| Hub-wide inventory of authored inputs, current diagnostics, and next action | skill **`kairos-diagnose-status`** |
| The complete set of emitted tests (generic `not_null`/`unique` + `kairos_runtime_*` + singular DQ tests) | the emitted artifacts themselves (`--emit`): `schema.yml` and `tests/<domain>/*.sql` |

`--explain` is the single source of truth: `kairos-execute-report` renders it, and the two report
skills have non-overlapping scopes (per-binding explanation vs hub-wide status).

See also: `docs/design/dd-106-medallion-engineering-policy-v1.md` for the medallion policy context,
and `docs/instruction-guides/data-engineer-methodology-guide.md` for the authoring workflow.
