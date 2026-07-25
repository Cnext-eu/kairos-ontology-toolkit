# Feedback — Data Engineering Rules Embedded in the Kairos Medallion Projector

**Status:** Feedback / open for discussion
**Date:** 2026-07-25
**Reviewer:** Data engineering colleagues (field practice: MPL, Qargo)
**Reviewed document:** [`Kairos-Ontology 4.7- Medaillon projector - dataengineeringrules.md`](./Kairos-Ontology%204.7-%20Medaillon%20projector%20-%20dataengineeringrules.md)
**Purpose:** Capture data-engineering feedback on the draft rules so the affected
design decisions (DD-014, DD-039, DD-001/G1, DD-092, §3.4, §3.8, §6.2, §7) can be
revisited by governance.

> Convention in this doc: **Draft** quotes the reviewed document; **Feedback** is the
> reviewer's position; **Affects** lists the DDs / sections that would need to change.

---

## 1. Staging / prep layer should exist (strong disagreement)

**Affects:** §1 intro, DD-014 ("no mandatory generated staging layer"), §3.2

**Draft:**
> Kairos deliberately removed a mandatory generated staging layer. Rename, cast,
> mapping, default, filter, and straightforward transformation logic belongs in
> generated Silver models. A separate intermediate model is justified only when the
> transformation changes grain or requires relational logic such as joins, windows,
> ranking, aggregation, JSON expansion, or complex fallback rules.

**Feedback (strong disagreement):**
- A staging layer (call it **unification / prep**) is a **requirement** in a modern
  multi-source data flow — not an optional intermediate model.
- The following belong in **staging/bronze**, not Silver:
  - **Basic renames / cleanups** — trimming trailing spaces, removing special
    characters that SQL dislikes, and correcting source errors and omissions.
  - **Casting to correct types**, including fixing bizarre source date assumptions
    (e.g. Microsoft Dynamics 365 Business Central (BC) date assumptions and null dates
    arriving as `1793`).
  - **Renaming reserved-word columns** — e.g. a field literally named `[No]`, which
    is a SQL keyword.
  - **Creating unique business keys across different source systems.**
  - **Expanding embedded JSON** (as seen in Qargo) — for readability and consistency
    across the future Silver layer (see §4 below).
- Doing this in staging **conserves consistency** and makes the Silver layer far more
  **readable**.
- Hard rule proposed for the staging layer:
  - The staging layer must **NEVER change grain**.
  - The goal of staging/bronze is **data consistency** only.
  - **No business logic may ever live in the staging layer.**
- Field example (**MPL**): the entire **incremental logic** is managed from the
  staging layer; dates are fixed up (null dates coming in as `1793`), reserved-word
  columns like `[No]` are renamed, and **unique business keys are created across
  different source systems** — all in staging.

**Proposed rule wording:** *"In the staging/bronze layer, data consistency is the goal.
No business logic may ever appear in staging. Staging never changes grain, but it does
normalize types, clean values, rename reserved words, build cross-source business keys,
and expand embedded JSON."*

**GPT model advice:** The feedback identifies a valid separation-of-concerns issue, but
the raw Bronze layer and a preparation layer should not be conflated. Keep ingested
Bronze data immutable for replay and audit, then introduce a generated **staging/prep
layer** for technical normalization. Define an explicit boundary: staging may perform
lossless renames, trimming, type normalization, source-system sentinel handling, JSON
expansion, technical deduplication, and incremental-watermark preparation, but may not
apply business classifications, aggregations, joins that alter meaning, or grain
changes. Cross-source business keys require special care: deterministic technical
identity may be prepared in staging, while business-defined matching and unification
belong in Silver or MDM. Rather than making every source pay for an empty layer, Kairos
could generate staging whenever normalization is declared or detected and allow a
pass-through staging model otherwise, while retaining one consistent architectural
boundary.

---

## 2. §3.4 — "Warehouse identity" is an invented, redundant concept

**Affects:** §3.4 "Grain and identity are separate concerns"

**Draft:**
> Every materialized Silver entity distinguishes: Business grain; Source identity;
> Natural key; **Warehouse identity** — deterministic surrogate key and ontology IRI.

**Feedback:**
- **"Warehouse identity" is unclear** — reviewer does not know what it is or what it
  would be used for.
- **Don't invent names that already exist.** A **Natural key** can also serve as the
  **unique primary key**; likewise the **source entity / source identity** can be a
  primary key.
- What is genuinely needed is simply a **unique primary key** (in some form) to enable
  **incremental handling** — not a new fourth identity concept layered on top.

**GPT model advice:** Rename **warehouse identity** to the established term
**surrogate key** and explain when it is needed rather than presenting it as a universal
fourth identity. Natural keys, source primary keys, and surrogate keys serve different
purposes: a natural key expresses business uniqueness, a source key identifies a record
inside one source, and a surrogate key provides a stable warehouse join key when natural
keys are composite, mutable, reused, or source-scoped. Incremental loading does not
itself require a surrogate key; it requires a reliable unique key plus a change
indicator. The ontology IRI is semantic identity and should not be bundled into the
physical primary-key definition.

---

## 3. §3.8 — Lineage/provenance contract is only partly feasible

**Affects:** §3.8 "Lineage and provenance are part of the contract"

**Draft:**
> Generated Silver models retain: the ontology IRI; `_source_system`;
> `_source_record_id`; `_loaded_at`; source/target IRIs in dbt metadata; ontology and
> toolkit versions; the reference-model closure hash and applied Silver
> defaults/overrides.

**Feedback:**
- This is **only feasible for simple entities.** For multi-source / composite entities
  you must either pick a **"base source entity"** and **omit all other contributing
  entities**, or the single-`_source_system` / `_source_record_id` contract breaks down.
- **`_loaded_at` is not very useful** in a Silver entity in practice. A **`_last_updated`
  column is far better** — and it is also **required for incremental handling**.

**GPT model advice:** Separate **operational timestamps** from **business/source
timestamps** instead of replacing one with the other. `_loaded_at` records when the
platform observed or materialized a row and remains useful for audit and replay;
`_source_updated_at` or `_last_updated` supports change detection when the source
provides a trustworthy value. For composed entities, do not pretend that one source
record explains the whole row. Retain a primary-driving-source identifier where useful,
and represent all contributing records in model-level lineage metadata or a separate
row-level lineage bridge. Make row-level multi-source provenance configurable because
its storage cost may outweigh its value for some products.

---

## 4. §4 — JSON detection/unfolding section is overcomplex

**Affects:** §4 (all subsections), DD-006, DD-039 (`bronze_expanded` boundary)

**Draft:** Section 4 defines a dedicated JSON detection/classification/expansion boundary
(`bronze_expanded`) that Silver opts into explicitly.

**Feedback (whole section is overcomplex):** it should simply be:
- **JSONs are expanded at the staging layer.**
- Assume a **stable schema** (as with every other incoming object).
- **Schema changes are handled the same way as other entities** — no special path.
- The **ontology / data platform must not be aware** that these were JSON entities —
  that is an **unneeded complication**.

**GPT model advice:** Agree that downstream Silver and ontology consumers should see
ordinary typed relations rather than JSON-specific mechanics. Keep JSON parsing and
schema-drift handling inside staging/prep, but preserve the original payload or a raw
reference for audit and reprocessing. A stable schema assumption is reasonable only
when it is enforced: generated contracts should detect incompatible shape changes and
fail or quarantine them like any other source-schema change. Scalar objects can be
flattened without changing grain; arrays and nested repeating objects create child
relations and therefore need explicit parent keys and cardinality rules rather than
silent flattening.

---

## 5. §6 — Gold produces data products, not only fact/dim warehouses

**Affects:** §6 intro "Gold dimensional and semantic-model projection"

**Draft:**
> Gold converts reusable Silver entities into dimensional warehouse and Power BI
> artifacts.

**Feedback:**
- Gold creates **data products.** A classic **fact/dimension warehouse is one
  possibility**, but **many other data products are possible.** The framing should not
  imply dimensional modeling is the only Gold output.

**GPT model advice:** Reframe Gold as the **consumption-oriented data-product layer**.
Dimensional models and Power BI semantic models remain supported projection profiles,
not the definition of Gold itself. The architecture should allow explicit product
profiles such as dimensional analytics, wide reporting tables, feature sets, API/search
projections, regulatory extracts, and domain data products, each with its own contract.
Avoid weakening current dimensional guarantees: product type should be explicit, and
each projector should validate only the rules relevant to that type.

---

## 6. §6.1 — No "magic" fact detection

**Affects:** §6.1 rule G1, DD-001

**Draft (rule G1):**
> explicit `goldTableType` wins; reference data is a dimension; a GDPR satellite is a
> secured dimension; **a class with at least two outgoing FK relationships is inferred
> as a fact;** remaining classes default to dimensions.

**Feedback:**
- The rule *"a class with ≥2 outgoing FK relationships is inferred as a fact"* is
  rejected as **"ludicrous."**
- **A fact is a fact because the designer says so.** There should be **no magic
  detection** of what a fact table is.
- Simple cases may legitimately have a **standalone fact with exactly zero
  dimensions** — don't overcomplicate this.
- Practical implication: rely on **explicit `goldTableType`** and drop the
  ≥2-FK inference heuristic.

**GPT model advice:** Make fact/dimension/bridge classification explicit for
production output. FK-count inference is not semantically reliable and may misclassify
associative entities, reference structures, or standalone events. It can remain a
non-authoritative design suggestion, clearly marked with confidence and requiring
approval, but it should never control materialization silently. Require
`goldTableType` when the selected Gold product profile is dimensional; permit facts
with zero dimensions and validate their declared grain and measures rather than their
number of relationships.

---

## 7. §6.2 — DAX measures cannot be pre-generated; they are backfilled

**Affects:** §6.2 "Measures" (`measureExpression`, `measureFormatString`)

**Draft:**
> A datatype property with `measureExpression` becomes a DAX measure ...
> Example: `kairos-ext:measureExpression "SUM([order_amount])"`.

**Feedback:**
- Writing **verbatim DAX** in the expression sounds nice but is **not realistic** — DAX
  is **far too complicated to pre-generate** without actual data and a real data model.
- In reality this will **always be backfilled**: generate the model → fill with data →
  have an LLM + the engineer develop the needed DAX → **backfill it into
  `measureExpression`.**
- Implication: treat `measureExpression` as a **backfill target**, not an up-front
  authoring field.

**GPT model advice:** Treat measure authoring as iterative, but do not assume all DAX
must be postponed. Simple additive measures can be generated or authored safely from a
confirmed grain and semantic model, while context-sensitive calculations usually
require loaded data, relationships, and validation in Power BI. Support a lifecycle
such as **declared metric intent → provisional/generated DAX → data-backed validation
→ approved expression backfill**. Store both the business definition and the final DAX;
an LLM may propose expressions, but an engineer or model owner should approve them and
tests should verify totals, filter behavior, blank handling, and time intelligence.

---

## 8. §7 — Contracted advanced dbt transformations: authoring feasibility

**Affects:** §7 (all subsections), DD-092, DD-093

**Draft:** Section 7 defines contracted advanced dbt transformations authored against the
ontology/contract.

**Feedback:**
- The **idea is nice**, but the reviewer **fails to see how authoring would work in
  reality**, because you need a **fully working data flow** to author these
  transformations in the first place.
- Implication: authoring of advanced transformations is realistically an **iterative,
  data-in-place activity**, not something specifiable purely up-front from the contract.

**GPT model advice:** Change §7 from an up-front authoring story to an **iterative
development workflow**. The contract can still be defined before production data is
available, but implementation needs source profiling, representative fixtures or a
working development flow. A practical sequence is: establish raw/staging sources,
profile data and confirm grain, author the dbt model, run it against representative
data, test its contract, then synchronize the proven output into mappings and Silver
design. The contract remains valuable as the acceptance boundary; it should not be
presented as sufficient evidence that the transformation itself is correct.

---

## Additional GPT model review of the remaining rules

The following topics were not raised in the original colleague feedback. They are
additional challenges and recommendations from the **GPT model**, based on common dbt,
Databricks, Microsoft Fabric, and Power BI engineering practices.

## 9. The rule hierarchy makes current implementation authoritative

**Affects:** §2.1, DD/R/S/G hierarchy

**GPT model challenge:** The statement that an accepted DD **and current projector
implementation** are authoritative can turn implementation limitations or defects into
policy. Code describes what exists; it should not automatically decide what is correct.
It also makes it difficult for this feedback document to challenge an implemented rule.

**GPT model advice:** Separate three authorities:
1. **Normative policy** — accepted architecture and governed contracts.
2. **Implemented capability** — what the current projector actually does.
3. **Known deviation** — where implementation differs from approved policy or best
   practice.

In a conflict, fail validation or report the deviation explicitly. Do not silently treat
current behavior as the desired standard. Every rule should have a stable identifier,
owner, status, rationale, implementation evidence, and review date.

---

## 10. Multi-source `UNION ALL` is not sufficient conformance

**Affects:** §3.2, DD-018, DD-074, Applied Rules “Multi-source conformance”

**GPT model challenge:** Typed padding and `UNION ALL` align schemas, but they do not
conform meaning or identity. Sources can overlap, disagree, use different code sets,
currencies, time zones, units, deletion semantics, and update frequencies. Requiring a
complete natural key in each branch does not resolve duplicate real-world entities or
conflicting attributes.

**GPT model advice:** Require an explicit multi-source policy per entity:
- whether branches are **disjoint**, **overlapping**, or **authoritative by attribute**;
- source precedence and survivorship rules;
- code/unit/currency/time-zone normalization;
- collision detection for natural keys;
- duplicate and conflict handling;
- deletion and late-arrival behavior; and
- reconciliation tests by source and for the union.

If equivalence needs probabilistic or governed matching, hand off to MDM rather than
implying that a union is conformance. A source discriminator should remain available
until cross-source identity is proven.

---

## 11. Mandatory immutable natural keys are too absolute

**Affects:** §3.4, §5.2 `naturalKey`, DD-104, Applied Rules “Natural-key completeness”

**GPT model challenge:** Some valid entities have no stable business natural key, or
their apparent natural key is mutable, reused, source-scoped, late-populated, or only
unique within a temporal interval. Rejecting every bound model without an “immutable
semantic key” can force engineers to invent false business identity.

**GPT model advice:** Support explicit identity strategies:
- governed business natural key;
- immutable source key plus source-system scope;
- deterministic composite integration key;
- externally mastered identifier; or
- generated surrogate with a documented reconciliation limitation.

Validate uniqueness, nullability, stability, scope, and reuse empirically. Record whether
the key is a business identifier, merge key, or warehouse join key; these are not always
the same. Incremental loading also needs a change-detection/watermark strategy, not only
a unique key.

---

## 12. SCD rules omit late-arriving data, corrections, and deletes

**Affects:** §3.5, DD-025, DD-104, Applied Rules SCD1/SCD2, §10.2

**GPT model challenge:** Using projection time as `valid_from` confuses **system/load
time** with **business-effective time**. Hash comparison and closing the current row are
not sufficient for out-of-order events, late corrections, replayed batches, hard
deletes, multiple changes with the same timestamp, or a changed natural key. The draft
also leaves soft-delete execution unimplemented while presenting the broader history
policy as repeatable.

**GPT model advice:** Define separate **valid time** and **system/load time**, even if
only one is enabled for a specific entity. Require a per-source CDC strategy covering:
operation type, event/update timestamp, ingestion timestamp, deterministic sequence or
tie-breaker, lookback window, hard/soft deletes, late-arriving changes, replay
idempotency, and full-refresh/backfill behavior. If no trustworthy business-effective
timestamp exists, describe the result as **load-history SCD2**, not business-effective
history. Add tests for exactly one current row, non-overlapping intervals,
`valid_from < valid_to`, deterministic same-time ordering, and delete handling.

---

## 13. Row hashing needs a canonical serialization contract

**Affects:** §3.5, Applied Rules “Hash-based change detection”

**GPT model challenge:** “Hash the history-participating attributes” is underspecified.
Different adapters can serialize nulls, decimals, booleans, timestamps, time zones,
Unicode, delimiters, and floating-point values differently. Naive concatenation can
also make distinct rows hash to the same input string.

**GPT model advice:** Specify one versioned canonical hash contract:
- explicit ordered columns and type-aware serialization;
- unambiguous null and field-boundary encoding;
- normalized decimal scale, timestamp zone/precision, booleans, and Unicode;
- a documented algorithm and output encoding;
- exclusion of volatile technical fields; and
- cross-adapter golden tests.

Store the hash-contract version in metadata. Treat a changed hash definition as a
backfill/migration event, not a harmless generator change.

---

## 14. Temporal FK resolution needs explicit failure behavior

**Affects:** §3.6, §5.3 temporal FK annotations, Applied Rules current/as-of FK lookup

**GPT model challenge:** `is_current = 1` prevents one common fan-out, but it does not
handle missing parents, duplicate current parents, overlapping SCD2 intervals,
late-arriving dimensions, early-arriving facts, unknown members, or a parent corrected
after child materialization. An as-of predicate can still return zero or multiple rows.

**GPT model advice:** Declare and test the relationship policy:
- lookup cardinality must be exactly zero-or-one or exactly one;
- behavior for unresolved keys: fail, quarantine, retry, or use an explicit unknown key;
- overlap and duplicate-current checks on the parent;
- late-arriving dimension restatement/backfill policy;
- whether children are re-keyed after parent corrections; and
- interval boundary semantics and time-zone normalization.

Never silently pick one match from multiple candidates. Surface unresolved and ambiguous
FK counts in the projection/runtime report.

---

## 15. Generated data quality is too narrow and lacks operational policy

**Affects:** §3.7, Applied Rules SHACL/FK tests

**GPT model challenge:** Null, uniqueness, regex, length, and relationship tests cover
contract shape, not overall data fitness. The draft does not define severity,
quarantine/reject behavior, thresholds, ownership, alerting, freshness, reconciliation,
or trend monitoring. Source enumerations are also not automatically valid domain
accepted values.

**GPT model advice:** Classify checks as **contract**, **source quality**, **business
quality**, and **operational quality**. Add freshness, volume/anomaly, source-to-target
reconciliation, duplicate rate, referential coverage, distribution/range, and
cross-field rules where applicable. Every check should define severity, tolerance,
action (warn/quarantine/block), owner, and evidence. Persist test outcomes and trends;
generation of test SQL is not the same as an operated quality process.

---

## 16. Deterministic generation does not guarantee deterministic data

**Affects:** §3.9, DD-096, DD-102

**GPT model challenge:** Byte-identical generated files are valuable, but the wording can
be read as a stronger runtime guarantee. SQL using windows, ranking, deduplication,
merges, or timestamps can remain nondeterministic when ordering is incomplete or the
warehouse evaluates concurrent changes differently.

**GPT model advice:** Distinguish:
- **artifact determinism** — identical inputs produce identical generated files; and
- **runtime determinism** — identical source snapshots produce identical rows.

Require complete tie-breakers for every window/dedup rule, deterministic clocks supplied
once per run, stable source snapshots, adapter-specific merge tests, and idempotent
reruns. The report should state which guarantee has actually been established.

---

## 17. Skipping unmapped classes can hide material data loss

**Affects:** §3.10, DD-096, Applied Rules “Unbound-target release gate”

**GPT model challenge:** An actionable warning is not always sufficient. In automated
builds, skipped or newly unbound entities can silently reduce coverage while the rest of
the package succeeds. Typed zero-row stubs can also be mistaken for valid but empty data
by downstream consumers.

**GPT model advice:** Provide strict release profiles with explicit coverage baselines
and fail on unexpected skips, binding regressions, empty required entities, or newly
unresolved mappings. Stubs should be disabled in production outputs or carry
machine-readable non-production status that downstream deployment rejects. Distinguish
“intentionally excluded,” “not yet designed,” “binding regressed,” and “source empty.”

---

## 18. Adapter portability and physical layout cannot be inferred once

**Affects:** DD-002, §5.2 `partitionBy`/`clusterBy`, Applied Rules “Adapter portability,”
§9 native types

**GPT model challenge:** A single semantic contract does not guarantee equivalent
behavior across Fabric and Databricks. Decimal overflow, string collation, case
sensitivity, timestamp zones/precision, booleans, merge semantics, constraints, JSON,
partitioning, and clustering differ. Static physical-layout annotations can also become
counterproductive as data volume and query patterns change.

**GPT model advice:** Maintain a versioned adapter capability matrix and compile/run
golden integration scenarios on every supported adapter before calling a rule “applied.”
Define portable semantic types first, then explicit adapter mappings and documented
lossiness. Treat partitioning/clustering as platform-specific operational tuning backed
by observed volume and workload, not permanent ontology truth. Unsupported behavior
must fail or be reported as unsupported—never silently degrade.

---

## 19. Removing a measured property from Gold can make its DAX impossible

**Affects:** §6.2, §6.5 `measureExpression`

**GPT model challenge:** The rule says a property with `measureExpression` becomes a DAX
measure **rather than a physical Gold column**, while the example measure is
`SUM([order_amount])`. If `order_amount` is the annotated property and is removed, the
measure has no physical column to aggregate. More generally, one base column may support
many measures, so a measure should not replace the data field by default.

**GPT model advice:** Separate **physical columns** from **semantic measures**. Keep the
base column whenever the DAX expression references it, unless the expression depends
only on other retained columns. Give measures their own stable semantic identifiers,
names, descriptions, format strings, folders, ownership, and tests. Validate every DAX
dependency against the emitted semantic model before release.

---

## 20. Gold history and dimensional behavior need more explicit choices

**Affects:** §6.1, §6.3, §6.5 `incrementalColumn`

**GPT model challenge:** “Facts do not receive SCD columns” is directionally reasonable
but incomplete. Facts may be transaction, periodic snapshot, or accumulating snapshot
facts; corrections and late-arriving dimensions still require explicit handling.
Similarly, exposing all SCD2 dimension versions to Power BI without relationship rules
can duplicate fact results. A single `incrementalColumn` annotation does not define a
safe incremental strategy.

**GPT model advice:** Require explicit fact type and grain, correction policy,
late-arrival policy, and dimension-version lookup. For SCD2 dimensions, state whether
Gold exposes current-only, full history, or both, and how facts bind to versions. Define
incremental strategy with unique key, watermark source, lookback, delete behavior,
schema-change behavior, and backfill procedure—not only a column name.

---

## 21. Generated date/time intelligence must not assume one calendar

**Affects:** §6.3, §6.5 `generateDateDimension`/`generateTimeIntelligence`

**GPT model challenge:** A `YYYYMMDD` key and generic YTD/QTD/MTD calculations do not
capture fiscal calendars, ISO weeks, 4-4-5 calendars, holidays, locale, time zones,
partial periods, or multiple role-playing dates. A scaffold that compiles can still
produce materially wrong metrics.

**GPT model advice:** Require a governed calendar profile: date range, fiscal-year
start, week convention, period pattern, locale, holidays, time zone, and current/closed
period semantics. Generate time-intelligence expressions only against approved base
measures and a marked date table. Support role-playing dates explicitly and keep the
default scaffold non-production until calendar assumptions are confirmed.

---

## 22. Generated RLS/OLS is a scaffold, not a secure design

**Affects:** §6.4

**GPT model challenge:** `[is_authorized] = TRUE()` is not a complete dynamic RLS design
and the projector does not populate the column. OLS role metadata without governed role
membership is likewise incomplete. Perspectives are usability features, not security
boundaries. “GDPR satellite” also narrows security framing to one regulation rather than
classifying sensitive data generally.

**GPT model advice:** Make generated security **fail closed** and deployment-blocking
until entitlement source, identity mapping, role membership, filter direction, test
users, and deployment binding are configured. Prefer a governed entitlement bridge and
identity-based filters over a precomputed universal boolean where row access varies by
user. Apply defense in depth at storage/warehouse and semantic layers. Add positive and
negative authorization tests, and state explicitly that perspectives never restrict
access.

---

## 23. Extension controls risk becoming configuration debt

**Affects:** §5 and §6.5 extension annotations

**GPT model challenge:** Requiring every materialized class to state every applicable
policy explicitly creates large repetitive TTL files, drift, and review fatigue.
Annotations with misleading legacy names (`includeNaturalKeyColumn` controlling an IRI)
or parsed-but-not-rendered behavior further weaken trust.

**GPT model advice:** Use named, versioned policy profiles with sensible inherited
defaults, then require explicit declarations only for identity, grain, security, history,
and deviations. Rename misleading annotations through a deprecation/migration path.
Reject unsupported annotations in strict mode rather than merely recognizing them.
Generate an effective-configuration report showing value, source layer, and override
reason for every materialized entity.

---

## 24. Mapping expressions and filters need a safety/portability contract

**Affects:** §7.1, Applied Rules transforms/defaults/source filters

**GPT model challenge:** Approved free-form SQL expressions and filters can bypass type
contracts, introduce adapter-specific behavior, change row counts or grain, and create
SQL-injection or quoting risks if values are interpolated unsafely. Calling bounded SQL
“straightforward mapping” does not define what is allowed.

**GPT model advice:** Define a constrained expression grammar or reviewed macro library
for normal mappings. Validate referenced columns, output type, null behavior,
determinism, adapter support, and whether a filter can remove rows. Parameterize literal
values safely. Any expression containing subqueries, joins, windows, aggregation,
nondeterministic functions, or grain-affecting logic should be rejected and routed to a
contracted transformation.

---

## 25. Silver DDL and dbt runtime must not describe different products

**Affects:** §9, §10.2, §10.3

**GPT model challenge:** `_deleted_at`, reference-data inlining, GDPR satellite behavior,
and some constraints exist only in DDL while dbt does not implement equivalent runtime
behavior. Consumers can therefore read the DDL as a contract that the produced data does
not satisfy. Inlining based on **business-column count** is also not a meaningful
performance or semantic criterion; row cardinality, volatility, reuse, and workload
matter more.

**GPT model advice:** Define one canonical logical contract and report a capability as
implemented only when DDL, dbt, tests, and documentation agree. Until parity exists,
mark DDL-only fields as planned/non-operational or remove them from deployable output.
Make reference inlining an explicit Gold/product optimization based on measured
cardinality and workload, not a Silver default inferred from column count.

---

## 26. The projection report needs operational and ownership evidence

**Affects:** §11

**GPT model challenge:** The proposed report explains generated design, but not whether
the product is healthy, owned, secure, fresh, or compatible with downstream consumers.
It can become a detailed build manifest rather than an operational contract.

**GPT model advice:** Add owner/steward, data classification, security status, contract
version, compatibility/breaking-change status, freshness/SLA, expected and observed
volume, last successful load, quality-test summary, quarantine counts, unresolved FK
rate, source-to-target reconciliation, lineage links, adapter validation status, and
known limitations. Separate static design evidence from runtime observations and make
the report machine-readable for release gates.

---

## Reference guidance used for the additional GPT review

- [dbt incremental models](https://docs.getdbt.com/docs/build/incremental-models)
- [dbt snapshots](https://docs.getdbt.com/docs/build/snapshots)
- [dbt model contracts](https://docs.getdbt.com/docs/mesh/govern/model-contracts)
- [Azure Databricks medallion architecture](https://learn.microsoft.com/en-us/azure/databricks/lakehouse/medallion)
- [Power BI star-schema guidance](https://learn.microsoft.com/en-us/power-bi/guidance/star-schema)
- [Power BI calculation groups](https://learn.microsoft.com/en-us/power-bi/transform-model/desktop-calculation-groups)
- [Power BI row-level security](https://learn.microsoft.com/en-us/power-bi/enterprise/service-admin-rls)
- [Power BI object-level security](https://learn.microsoft.com/en-us/power-bi/enterprise/service-security-object-level)
- [Microsoft Fabric Direct Lake overview](https://learn.microsoft.com/en-us/fabric/fundamentals/direct-lake-overview)

---

## Summary of requested changes

| # | Section / DD | Reviewer position |
|---|---|---|
| 1 | §1, DD-014 | Reinstate a mandatory **staging/prep (unification)** layer for consistency-only cleanups (renames, casts, date fixes, reserved-word fixes, cross-source keys, JSON expansion). Never changes grain, never holds business logic. |
| 2 | §3.4 | Drop invented **"Warehouse identity"**; a natural key or source identity can be the unique PK needed for incremental handling. |
| 3 | §3.8 | Lineage contract feasible only for simple entities; multi-source needs a chosen base entity. Replace `_loaded_at` with **`_last_updated`**. |
| 4 | §4, DD-039 | Radically simplify: **expand JSON in staging**, assume stable schema, hide JSON origin from ontology/platform. |
| 5 | §6 | Gold produces **data products** generally; fact/dim is only one option. |
| 6 | §6.1, DD-001 | Remove **≥2-FK "fact" inference**; facts are explicit; zero-dimension standalone facts are valid. |
| 7 | §6.2 | `measureExpression` DAX is **backfilled after data exists**, not authored up-front. |
| 8 | §7, DD-092 | Advanced-transformation **authoring requires a working data flow**; treat as iterative. |

## Summary of additional GPT model advice

| # | Section / DD | GPT model recommendation |
|---|---|---|
| 9 | §2.1 | Separate normative policy, implementation capability, and known deviations. |
| 10 | §3.2 | Add overlap, precedence, normalization, conflict, deletion, and reconciliation policy to multi-source conformance. |
| 11 | §3.4 / §5.2 | Support multiple honest identity strategies instead of requiring an invented immutable natural key. |
| 12 | §3.5 / §10.2 | Define valid vs load time and complete CDC, late-arrival, replay, correction, and delete semantics. |
| 13 | §3.5 | Specify a versioned, cross-adapter canonical row-hash serialization. |
| 14 | §3.6 | Define missing/ambiguous/late parent behavior and validate SCD2 interval integrity. |
| 15 | §3.7 | Add operational DQ dimensions, severity, tolerance, ownership, actions, and trends. |
| 16 | §3.9 | Distinguish deterministic generated artifacts from deterministic runtime data. |
| 17 | §3.10 | Use strict coverage baselines; prevent skipped entities or stubs from looking production-ready. |
| 18 | DD-002 / §5 / §9 | Maintain an adapter capability matrix and validate behavior on every claimed platform. |
| 19 | §6.2 | Keep measure input columns and validate all DAX dependencies. |
| 20 | §6.1 / §6.5 | Declare fact type, correction/history policy, dimension-version binding, and full incremental strategy. |
| 21 | §6.3 | Require an approved calendar profile before generated time intelligence is production-ready. |
| 22 | §6.4 | Treat generated RLS/OLS as fail-closed scaffolding; perspectives are not security. |
| 23 | §5 / §6.5 | Reduce annotation debt with versioned policy profiles, deprecations, and strict unsupported-annotation handling. |
| 24 | §7.1 / §8 | Constrain mapping SQL and route relational, nondeterministic, or grain-affecting logic to contracted transformations. |
| 25 | §9 / §10 | Remove deployable DDL/runtime contradictions and make inlining an evidence-based product optimization. |
| 26 | §11 | Add ownership, security, SLA, compatibility, runtime quality, reconciliation, and adapter evidence to reports. |
