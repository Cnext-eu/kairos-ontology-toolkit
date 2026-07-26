# Optimizing Projection Readiness

**Status:** Draft for toolkit design review  
**Date:** 2026-07-26  
**Case study:** Party to Fabric dbt/Silver projection  
**Toolkit:** `4.7.0rc5`

## 1. Executive conclusion

The dbt projection gate is **not generally too strict**. Most DD-106, DD-108, and
DD-109 checks protect important runtime invariants: reproducible source identity,
explicit type conversion, complete CDC ordering, deterministic FK resolution, and
non-invented business keys. Weakening those checks would move failures into generated
SQL or, worse, allow plausible but incorrect Silver data.

The poor experience came from four different problems being exposed through one
fail-fast projection loop:

1. **Design completion was declared too early.** Several cross-artifact requirements
   were known or derivable during source, mapping, transformation, and Silver design,
   but those phases validated their own files rather than the complete bound contract.
2. **Readiness checks are fragmented.** `validate`, `check-claims`,
   `check-transformation-readiness`, contract synchronization, preparation SHACL, and
   projection normalization each cover a different slice. No command evaluates the
   complete live projection input before generation.
3. **Projection normalization is fail-fast.** It raises on the first invalid policy,
   so each retry reveals only the next dependency. This creates the repeated
   design-edit-project loop even when multiple findings already coexist.
4. **There is one genuine toolkit model gap.** A governed dbt-contract virtual source is
   marked `contracted-virtual`, but preparation normalization indexes only `physical`
   tables. DD-108 then accepts source identities only from normalized preparation
   `RecordKeyPolicy` or `ArrayChildContract` resources. A keyless raw source whose
   identity is legitimately formed by a contracted transformation therefore has no
   truthful representation in `4.7.0rc5`.

The recommended response is:

- keep runtime projection fail-closed;
- move relevant checks to the earliest authoritative design phase;
- add one **live, non-writing projection-readiness simulation** that binds and
  normalizes the complete scoped input, accumulates independent findings, and emits a
  dependency-ordered remediation plan; and
- fix the contracted-virtual identity model rather than inventing a raw source PK.

## 2. What happened in the Party projection

The session uncovered blockers in roughly this order:

| Finding | Correct owner | Should have been found before projection? | Classification |
|---|---|---:|---|
| Ontology/import/catalog closure ambiguity | Domain/validation | Yes | Validation scoping/configuration |
| Claim-to-extension layout/sync drift | Domain/Silver | Yes | Design output validation |
| Missing immutable source key on `qargo.companies` | Source | Yes | Missing source readiness check |
| Missing Contact/Address relationship mappings | Mapping | Yes | Missing cross-artifact mapping check |
| TradeParty lacked a mapped semantic key for child FK resolution | Silver + mapping | Yes | Missing FK resolvability check |
| Missing preparation policy for mapped physical source | Source | Yes | Missing prep-coverage check |
| Incompatible mapped physical types lacked explicit casts | Source + mapping | Yes | Missing source-to-target type check |
| Runtime tie-breakers did not match prepared outputs | Silver | Yes | Missing runtime-to-prep check |
| `sourceIdentity` referenced a virtual table rather than an accepted identity resource | Silver/transformation | Yes | Missing identity-reference check |
| Raw Contact has no valid PK, while virtual prep is rejected | Toolkit architecture | No valid config exists | Product defect/design gap |

This table shows why the experience felt excessively strict even though most individual
rules are sound: projection was acting as the first integration test of artifacts that
had already passed isolated phase checks.

## 3. Evidence from the current implementation

### 3.1 Projection uses the correct complete contract

`normalize_contract()` binds policy, mappings, source systems, contracts, Silver
candidates, and FK facts before rendering. This is the right authority for final
projection readiness:

- `.venv/Lib/site-packages/kairos_ontology/core/projections/dbt/normalize.py:102-123`

The problem is not that projection checks too much. The problem is that this complete
binding is not available as a first-class, non-writing design validation.

### 3.2 Normalization is structurally fail-fast

`normalize_medallion_policy()` runs subsystems sequentially:

1. preparation;
2. multi-source;
3. incremental runtime;
4. hashes;
5. temporal relationships;
6. data quality;
7. identities;
8. deviations and adapter evidence;
9. Gold policy.

See:

- `policy_normalize.py:5317-5407`

Although the function creates an `issues` list, many authored-policy failures are raised
as `PolicyNormalizationError`. Preparation alone contains many immediate raises for
duplicate/missing policy, unknown tables, unsafe identifiers, casts, CDC, JSON, and
record-key mismatches:

- `policy_normalize.py:1060-1510`

Consequently, later independent checks never execute after the first exception.

Later physical-planning stages already demonstrate the desired pattern:
`_quality_physical_plans()`, `_runtime_physical_plan()`, and
`_silver_physical_plan()` accumulate blocker collections, while render raises from those
collections. Extending structured accumulation into policy normalization is therefore an
alignment with existing architecture, not a new validation philosophy. A wrapper that
only catches and records the first `PolicyNormalizationError` would not solve the
one-blocker-at-a-time problem.

### 3.3 `check-release` does not solve live projection readiness

`check-release` already aggregates Claim Registry, source coverage, extension sync,
aspirational binding, and previously persisted validation/project status. It explicitly
does **not** rerun validation or projection:

- `cli/main.py:4093-4107`

That is appropriate for lifecycle/CI status, but it cannot identify a new
`prep.missing-required-cast`, invalid runtime tie-breaker, or unresolved source identity
before projection has attempted normalization.

Therefore:

- retain `check-release` as the lifecycle/release report;
- add a separate live projection-readiness evaluator;
- let strict release evaluation consume the latest readiness report as evidence.

## 4. The contracted-virtual source blocker

### 4.1 Why the current configuration is impossible

During bind, synchronized dbt-contract vocabularies are recognized and their tables are
marked:

```text
relation_kind = "contracted-virtual"
```

See:

- `bind.py:617-629`

Preparation normalization intentionally builds its table index from only:

```python
if table.relation_kind != "physical":
    continue
```

See:

- `policy_normalize.py:1068-1073`

Therefore a preparation policy whose `sourceTable` is the contracted Contact virtual
table fails with `prep.unknown-source-table`.

At the same time, identity normalization builds accepted `sourceIdentity` references
only from normalized physical preparation record keys and array-child contracts:

- `policy_normalize.py:2424-2455`
- `policy_normalize.py:2511-2521`

The two rules together mean:

1. a contracted virtual table cannot own a preparation `RecordKeyPolicy`; and
2. its contract grain key cannot be used directly as DD-108 source identity.

For `qargo.contacts`, declaring a raw PK is not a truthful workaround. Profiling found:

- 3,149 raw rows;
- only 3,146 distinct complete rows;
- nullable participation in the complete-row candidate;
- no stable source contact identifier.

The contracted model legitimately forms a unique, non-null content identity at its
approved grain and removes exact duplicate business rows. The toolkit currently has no
identity authority representing that boundary.

### 4.2 Is the gate too strict here?

The requirement for governed source identity is correct. The accepted authority model is
too narrow.

The toolkit should not:

- pretend all raw columns form a source PK;
- treat a nullable or non-unique tuple as immutable identity;
- use row content silently as a raw source key;
- disable DD-108 for all contracted models; or
- accept an arbitrary virtual table IRI without contract evidence.

### 4.3 Recommended design

Add a first-class **contracted transformation identity authority**.

The synchronized contract already provides relevant evidence:

- stable virtual source IRI;
- approved target class;
- explicit grain sentence;
- physical `grain_key`;
- key `unique` and `not_null` tests with recorded passing evidence;
- approved decisions and evidence;
- governed `replaces_sources`;
- adapter support; and
- implementing model/test references.

Represent that evidence as a typed identity resource generated by
`sync-dbt-contracts`, for example:

```text
kairos-dbt:ContractIdentity
```

with:

- contract/model reference;
- virtual table;
- ordered grain-key columns;
- scope (`source-table` or a more precise `contract-output`);
- required uniqueness/non-null tests;
- a machine-verifiable passing test/profile result tied to the contract content hash;
- source-replacement lineage;
- canonical CDC field bindings where SCD1/SCD2 is required; and
- decision approval/evidence status.

DD-108 `sourceIdentity` should accept:

1. physical preparation `RecordKeyPolicy`;
2. preparation `ArrayChildContract`; or
3. validated contracted-transformation identity.

The contract identity is not automatically an enterprise/business identity. It remains
source-scoped unless the Silver policy separately establishes exact equivalence or an
externally mastered identifier.

A declared dbt test is not sufficient evidence that the key is valid. The identity
authority must reference a passing full-data profile or dbt test result. If only the test
declaration exists, readiness must fail with a distinct diagnostic such as
`identity.contract-unverified`. Changing the contract grain, key columns, SQL, or tests
invalidates the evidence and requires re-verification.

### 4.4 Alternative designs

| Option | Assessment |
|---|---|
| Include `contracted-virtual` in `_normalize_prep` | Technically small, but conflates physical source preparation with a governed transformation output and may generate an incorrect second staging layer |
| Treat contract `grain_key` as accepted identity without a typed resource | Better than inventing a PK, but loses explicit provenance and validation requirements |
| Require ingestion to inject file/batch/row ordinal for every keyless raw source | Valid when such metadata exists, but it does not represent stable Contact identity and was not present here |
| Disable source identity enforcement for contracts | Unsafe; weakens lineage and replay guarantees |

The typed contract identity is the cleanest authority boundary.

## 5. Checks to move earlier

The same invariant should be checked twice:

- **design gate:** early, scoped, actionable, and grouped by owning phase;
- **projection gate:** final, exact, and fail-closed.

This is deliberate defense in depth, not duplicate bureaucracy.

### 5.1 Source design completion gate

Before a source/preparation phase is marked complete for a scoped domain:

- every directly mapped physical table has exactly one preparation policy;
- every physical source used directly as a source-scoped identity has a declared,
  non-empty source PK;
- profile evidence confirms candidate key nullness/distinctness when samples are
  available;
- mapped source/target physical types are compatible or have explicit conversions;
- incremental columns have complete CDC normalization;
- required normalized fields exist and use valid types;
- JSON columns have explicit scalar/array contracts;
- schema-change and error behavior are explicit; and
- keyless physical tables are classified as:
  - ingestion-identity supplied,
  - transformed-contract identity required, or
  - blocked.

This is more useful than preparation SHACL alone. SHACL proves graph shape, not that
record-key components equal the bound source PK or that mapped types require casts.

### 5.2 Mapping design completion gate

Before mapping is marked complete:

- every source and target IRI resolves;
- table mappings resolve to materialized target classes;
- every named mapping is structurally valid;
- object-property mappings used for FKs have the necessary source columns;
- FK source component count matches the target semantic key;
- required/identity target properties have mappings;
- governed replacement has one authority path and no direct/replacement conflict;
- virtual vocabularies match current contracts; and
- mapping expressions are type-compatible after preparation.

This would have caught both missing `company_id` relationship mappings before
projection.

### 5.3 Contracted dbt transformation completion gate

Before a contracted model is marked complete:

- contract vocabulary is synchronized;
- target class and `silverSourceRef` agree;
- grain key is declared, non-null, unique, and test-backed;
- grain-key evidence is passing, current for the contract content hash, and not only a
  declared test;
- the contract declares whether identity is raw-preserved or transformation-formed;
- governed replacement lineage is complete;
- required canonical CDC fields are present when linked Silver entities use SCD1/SCD2;
- implementing SQL references allowed `source()`/`ref()` nodes;
- every decision names an implementing model and verifying test; and
- both mapping and Silver readiness are evaluated using the live bound contract.

The present `check-transformation-readiness` returning “no candidate inventory” is not
evidence that existing contracted models are projection-ready. Existing contracts need a
separate readiness path even when no imported candidate inventory exists.

### 5.4 Silver design completion gate

Before Silver design is marked complete:

- each materialized class has a complete DD-108 identity policy;
- each `sourceIdentity` resolves to an accepted governed identity resource;
- every SCD class links one complete DD-109 runtime;
- runtime merge/order/timestamp fields exist in the effective prepared or contracted
  source relation;
- source record identity and semantic natural key are kept distinct;
- every materialized FK resolves against a mapped target semantic key;
- FK temporal/cardinality/failure/change-detection policy is complete;
- managed claim/import/include surfaces are synchronized; and
- the full class-to-source binding can normalize without rendering.

The Party Silver log said design was complete while also deferring end-to-end FK
verification and assuming `_source_record_key` would avoid a target natural key. Those
are projection-contract questions and should block Silver completion for a projection-
ready status.

## 6. Bulk live projection-readiness simulation

### 6.1 Proposed command

Prefer a dedicated command rather than weakening or overloading projection:

```powershell
kairos-ontology check-projection `
  --ontology model\ontologies\party.ttl `
  --target dbt `
  --platform fabric `
  --accelerator logistics `
  --catalog catalog-v001.xml `
  --format json `
  --plan
```

Possible alias:

```powershell
kairos-ontology project --check ...
```

`check-projection` is clearer because it promises no artifact generation.

### 6.2 Required behavior

The command must:

1. use the exact projection discovery, closure, bind, and normalize code paths;
2. never render or write generated projection artifacts;
3. never modify source, mapping, ontology, extension, contract, or phase-log files;
4. check contract synchronization without rewriting;
5. collect all independent diagnostics instead of stopping at the first;
6. suppress cascades when a prerequisite is invalid;
7. emit text and stable JSON reports;
8. group findings by owning skill and affected resource;
9. order remediation by dependencies; and
10. exit non-zero when blocking findings exist.

### 6.3 Evaluation stages

| Stage | Examples |
|---|---|
| Scope and closure | catalog resolution, imports, accelerator/profile |
| Governance | claims, extension sync, ownership, MDM warnings |
| Contract integrity | contract parse, sync drift, decisions/tests, adapter support |
| Source binding | source/table/column resolution, direct vs replacement authority |
| Preparation | policy coverage, keys, casts, CDC, JSON, identifiers |
| Mapping | IRI resolution, expression types, required/FK bindings |
| Identity | accepted authority, key scope, semantic key, reconciliation limits |
| Runtime | merge identity, timestamps, ordering, replay/delete/backfill |
| Foreign keys | target key resolution, cardinality, temporal policy, failure actions |
| Adapter feasibility | canonical-to-physical type support, macro/resource collisions |
| Artifact plan | files that would be generated, omitted, or skipped |

### 6.4 Diagnostic accumulation

Do not implement accumulation by repeatedly running projection and suppressing
exceptions. Refactor normalization around one shared diagnostic collector:

```text
Diagnostic
  code
  rule_id
  severity
  blocking
  stage
  owner_skill
  resource_uri
  predicate_uri
  message
  evidence[]
  depends_on[]
  remediation
```

Use one normalization implementation with two collector behaviors:

- `FAIL_FAST`: emit the diagnostic and immediately re-raise it;
- `COLLECT`: emit the same diagnostic and mark the affected result unavailable.

Every current `raise PolicyNormalizationError(...)` must go through this same collector;
a separate simulation implementation is prohibited. This makes projection parity
structural rather than dependent on two implementations staying synchronized.

Each evaluation stage declares its upstream prerequisites explicitly. Each subsystem
returns either a valid/partial spec or an unavailable result plus diagnostics. A
downstream stage with an unavailable prerequisite is mechanically marked
`not_evaluated` with the prerequisite diagnostic IDs, rather than relying on ad hoc
per-check suppression.

Example:

- missing preparation policy blocks effective prepared columns;
- runtime field validation becomes `not_evaluated: preparation unavailable`;
- unrelated contract synchronization and Address FK checks still run.

This yields a complete useful report without hundreds of cascade errors.

### 6.5 Dependency-ordered remediation plan

Raw diagnostics should be transformed into a plan:

```text
1. Source design
   - Establish companies source PK.
   - Author companies preparation policy.
   - Add three required type conversions.

2. Contracted transformation
   - Establish Contact contract identity authority.
   - Confirm canonical CDC fields and tests.

3. Mapping
   - Map Contact.company_id and Address.company_id relationships.
   - Map companies.company_id to TradeParty.partyIdentifier.

4. Silver
   - Bind sourceIdentity resources.
   - Align runtime total-order fields.
   - Confirm FK target key resolution.

5. Projection
   - Generate Fabric dbt/Silver bundle.

6. Validation
   - Run validate-dbt and audit-silver-samples.
```

The plan should deduplicate findings that share one root cause. For example, one missing
TradeParty semantic key can cause both Contact and Address FK failures; it should be one
Silver task with two impacted relationships.

## 7. Fleet-mode remediation

A useful Plan B is a **bounded projection-readiness campaign**, not unrestricted
lifecycle autopilot.

### 7.1 Recommended workflow

```text
check-projection --plan
        |
        v
review one complete remediation plan
        |
        v
execute approved deterministic batches by owning skill
        |
        v
check-projection again
        |
        v
project only when readiness is green
```

### 7.2 What may be fleet-approved

After explicit user authorization for the campaign:

- synchronize generated contract vocabularies;
- add mechanically required named mapping resources after semantic mappings are already
  approved;
- add provably lossless widening casts whose source/target semantics are unchanged;
- align references to already-approved resource IRIs;
- generate scaffolds/templates;
- update phase logs and readiness evidence; and
- rerun deterministic checks.

### 7.3 What must still stop for a decision

- inventing or changing business identity;
- declaring a source PK without evidence;
- selecting SCD1 versus SCD2;
- changing grain, deduplication, survivorship, or source replacement;
- lossy/narrowing casts or conversions that depend on locale, precision, timezone, or a
  parse format;
- choosing FK missing/late-parent behavior;
- asserting cross-source equivalence;
- PII/security policy;
- destructive regeneration; and
- low-confidence or contradictory mappings.

This preserves governance while reducing the user experience from many one-question
loops to one reviewed plan plus a small number of genuinely semantic checkpoints.

### 7.4 Skill architecture implication

Current fleet authorization is skill-invocation scoped and expires at handoff. A
cross-phase readiness campaign therefore needs either:

1. a new orchestrating skill that owns the campaign and records delegated decisions; or
2. explicit per-phase batch approvals generated from the same immutable plan.

The second option is safer for the first release. It preserves current authority
boundaries while still avoiding rediscovery.

## 8. Recommended product changes

### P0 - Fix the impossible identity boundary

1. Add contracted-transformation identity as an accepted DD-108 authority.
2. Generate the identity resource through `sync-dbt-contracts`.
3. Require current passing grain-key uniqueness/non-null evidence, not only declared
   tests.
4. Carry canonical CDC field bindings for SCD-linked outputs.
5. Add a regression scenario for a keyless raw source whose contract forms the output
   identity.

### P0 - Add live `check-projection`

1. Reuse exact bind/normalize inputs.
2. Add diagnostic collection mode.
3. Emit JSON and dependency-ordered Markdown/text plans.
4. Guarantee no projection artifact writes.
5. Support domain, target, adapter, accelerator, and catalog scoping.

### P1 - Strengthen phase completion gates

1. Source: bound prep/key/type/CDC readiness.
2. Mapping: full IRI, type, FK, replacement, and contract-sync readiness.
3. Transformation: existing-contract readiness even without candidate inventory.
4. Silver: bound identity/runtime/FK normalization without render.
5. Flow/status: distinguish `design-valid` from `projection-ready`.

### P1 - Consolidate validation UX

Provide one command or skill action that runs, in one invocation:

- ontology syntax/SHACL/closure;
- claims and extension sync;
- contract synchronization check;
- transformation readiness;
- preparation/mapping/Silver bound normalization;
- adapter feasibility; and
- release-lifecycle facts.

The result should still show the individual authorities and rule IDs; consolidation
must not merge their semantics into a vague pass/fail.

### P2 - Improve authoring assistance

- `propose-preparation` from source profiles and mappings;
- `validate-mapping`;
- `propose-silver-ext`;
- contracted-transformation scaffolding from a surviving vocabulary;
- phase-log deliverable integrity checks; and
- scoped closure/module loading.

These items reduce missing configuration before readiness simulation is needed.

## 9. State model improvement

Use separate statuses:

| Status | Meaning |
|---|---|
| `authored` | Required files exist |
| `design-valid` | Owning artifact syntax and local rules pass |
| `bound-valid` | Cross-artifact source/mapping/contract/Silver binding passes |
| `projection-ready` | Live check-projection has zero blockers for target/adapter |
| `generated` | Projection artifacts were written |
| `compile-valid` | dbt parse/manifest/compile passed |
| `runtime-valid` | Warehouse-backed tests passed |
| `release-eligible` | Strict governance/release gate passed |

The Party Silver phase was `design-valid`, but not `bound-valid` or
`projection-ready`. Calling it simply “done” hid that distinction.

## 10. Acceptance criteria

### 10.1 Party scenario

From the state before the first projection attempt, one `check-projection` run must
report at least:

- companies source-key/preparation gap;
- required mapped type conversions;
- Contact and Address FK relationship mapping gaps;
- TradeParty semantic target-key gap;
- runtime/preparation field mismatches;
- invalid Contact source identity;
- claims/extension sync state;
- contract synchronization state; and
- the contracted-virtual identity architecture blocker.

It must produce one ordered plan and write no dbt/Silver artifacts.

### 10.2 Multiple-error behavior

A fixture with:

- missing prep policy on source A;
- invalid cast on source B;
- unresolved mapping target on source C; and
- incomplete runtime on entity D

must report all four independent roots in one run.

### 10.3 Cascade suppression

If source A has no preparation policy, the report must not emit a dozen runtime errors
for fields that could not be derived. It should mark those checks `not_evaluated` and
reference the prep blocker.

### 10.4 Projection parity

When `check-projection` is green, immediate projection with identical scope/options must
not discover a new deterministic bind/normalize blocker. Rendering, filesystem, and dbt
compile failures remain possible and must be classified separately.

### 10.5 Contract identity

A keyless raw source plus an approved contracted model with:

- stable virtual IRI;
- unique/non-null grain key;
- current passing profile/test evidence tied to the contract content;
- approved decisions;
- governed replacement;
- canonical CDC outputs; and
- verifying tests

must normalize as a source-scoped identity without declaring a false raw PK.

A contract with only declared, unexecuted key tests must instead report
`identity.contract-unverified`.

### 10.6 No simulation-only blockers

For identical scope and options, `check-projection` must not report a deterministic
blocker that projection would not encounter. This protects against users learning to
bypass a noisy readiness command.

### 10.7 Shared normalization path

Tests must prove that fail-fast projection and collection-mode readiness emit the same
first deterministic diagnostic for every fixture. Both modes must invoke the same
normalizer and diagnostic sites.

### 10.8 Existing contracted-model readiness

An existing synchronized contract must be evaluated for projection readiness even when
the advanced-transformation candidate inventory is empty. “No candidates” must not be
reported as evidence that existing contracts are ready.

## 11. Recommended decision

Adopt the following:

1. **Do not relax DD-106/DD-108/DD-109 projection invariants.**
2. **Fix contracted-virtual identity authority as a P0 defect.**
3. **Add `check-projection` with collection mode as the primary UX improvement.**
4. **Make source, mapping, transformation, and Silver completion gates call scoped
   subsets of the same live evaluator.**
5. **Add an orchestrated, plan-driven remediation workflow with bounded fleet approval.**
6. **Reserve actual projection for a green readiness report.**

This changes the workflow from:

```text
design one item -> project -> fail -> return to design -> repeat
```

to:

```text
design -> simulate complete projection -> approve one remediation plan
       -> remediate in dependency order -> simulate green -> project once
```

The result preserves correctness while substantially reducing fine-grained workflow
churn.
