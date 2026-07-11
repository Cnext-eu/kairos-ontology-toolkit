# MDM Hub Design v2

_Revised architecture proposal. Supersedes `mdmhubdesign.md`. Rewritten to simplify
the component topology, tighten the ontology/runtime boundary, close governance gaps
(privacy, data quality, consumer entitlement, evidence feedback), and record the crucial
decisions as explicit architecture decisions._

> **What changed from v1 (summary):**
> - MDM **policy authoring** is not a new toolkit. It is a new **extension vocabulary**
>   (`*-mdm-ext.ttl`) plus an **8th projection target** (`mdm-profile`) inside the existing
>   `kairos-ontology-toolkit`, authored through a `kairos-design-mdm` skill — consistent
>   with `kairos-design-silver` / `kairos-design-gold`.
> - MDM **runtime** software (API, services, stewardship UI, DB migrations, deploy modules)
>   is a single product, `kairos-mdm-runtime`, that starts as a module and is split into its
>   own repo **only when its release cadence genuinely diverges**.
> - Three design-time UIs collapse to **two surfaces**: one design portal (Ontology
>   Navigator, with an MDM authoring module) and one operational Stewardship UI.
> - **One** identifier-normalization implementation, embedded into both batch and runtime —
>   not two implementations reconciled by tests.
> - Probabilistic matching config is a **versioned runtime artifact referenced by** the
>   profile, not authored in Turtle.
> - New governance coverage: privacy-vs-immutability reconciliation, operationalized data
>   quality, consumer entitlement, and an evidence-feedback artifact.
> - New epics: **CONSUME**, **AUDIT**, **INTEGRATE**, and non-functional stories.

---

## 1. Purpose and non-goals

This document defines how Master Data Management (MDM) is added to the Kairos ecosystem
**without** turning the ontology hub into an operational application or the analytical
Warehouse into an OLTP system.

**In scope:** analytical MDM for reporting (Phase 1); operational mastering and
reference-data governance (Phase 2); the ontology-hub / runtime / dataplatform boundary;
durable identity, golden-record and reference-data state; governance workflows; privacy;
data quality; APIs, events, security, audit, operations and analytical publication.

**Out of scope / deliberate non-goals:** mandating a UI vendor, frontend stack or
entity-resolution product; owning KYC/onboarding, credit or sanctions business processes;
introducing a general-purpose Operational Data Store.

---

## 2. Component topology (simplified)

Two products, one hub, one runtime, one deployment — **not** four products.

```mermaid
flowchart TB
    subgraph products["Reusable Kairos products"]
        ot["kairos-ontology-toolkit<br/>validation + projections<br/>(dbt, silver, gold, powerbi,<br/>report, ... , <b>mdm-profile</b>)"]
        rt["kairos-mdm-runtime<br/>API, services, stewardship UI,<br/>DB migrations, deploy modules,<br/>normalization library"]
    end

    subgraph design["Customer design time"]
        oh["Ontology hub<br/>semantics, mappings, SHACL,<br/><b>*-mdm-ext.ttl</b> extensions"]
        contract["Contract + MDM profile release<br/>schemas, constraints, IRIs, policy"]
        nav["Ontology Navigator<br/>(+ MDM authoring module)"]
    end

    subgraph runtime["Customer dataplatform runtime"]
        deploy["Deployment<br/>pinned versions, bindings, infra"]
        ingest["Ingestion / bronze"]
        api["MDM API + services"]
        ui["Stewardship UI"]
        db[("MDM operational DB<br/>golden records, crosswalks,<br/>reference values, cases, audit")]
        wh[("Fabric Warehouse<br/>read-only analytical replica")]
    end

    sources["Source systems"] --> ingest
    ot --> oh
    nav <--> oh
    oh --> contract
    rt --> deploy
    contract --> deploy
    deploy --> api & ui & db
    ingest --> api
    ui --> api
    api <--> db
    api -->|approved publication| wh
    api -->|approved sync-back (Phase 2)| sources
```

- **`kairos-ontology-toolkit`** produces the semantic contract **and** the MDM profile via
  the new `mdm-profile` projection target. Design authoring uses the `kairos-design-mdm`
  skill and an MDM module inside the existing Ontology Navigator.
- **`kairos-mdm-runtime`** is the reusable runtime software and ships the single
  normalization library used by both batch and runtime.
- **Ontology hub** is the customer design source of truth for both semantics and declarative
  MDM policy. Its release contains the contract and the projected, immutable MDM profile.
- **Dataplatform** pins one ontology-hub release + one runtime release, adds technical
  bindings, and operates one MDM instance. Deployment does not couple MDM to Fabric, dbt or
  a specific operational database.

> There is **no** `<client>-mdm-hub` repository by default, and MDM policy authoring adds
> **no** new toolkit — only an extension vocabulary and a projection target. See ADR-1/ADR-2.

---

## 3. Terminology

| Term | Meaning |
|---|---|
| Master data | Governed business entities (Party, Location, Vessel) |
| Reference data | Controlled code lists (UN/LOCODE, currency, Incoterms) |
| Source of Entry (SoE) | Application where a user first enters/changes data |
| System of Record (SoR) | Authoritative source for a defined entity or attribute |
| Enterprise ID | Durable MDM identifier for one real-world entity (`MDM_PARTY_ID`) |
| Crosswalk | Versioned links between an enterprise ID and source records |
| Golden record | Approved current representation of a mastered entity, with provenance |
| Registry MDM | Identity linking without operational authoring or write-back |
| Coexistence MDM | Hub and sources share controlled authoring; requires sync-back |
| Centralized MDM | Hub is sole authoring authority for selected data |
| MDM profile | Immutable, runtime-neutral policy projected from `*-mdm-ext.ttl` |
| MDM extension | RDF file (`model/extensions/<domain>-mdm-ext.ttl`) declaring MDM policy |
| Stewardship case | Governed work item requiring investigation, decision or approval |
| Published replica | Read-only MDM data copied into the Warehouse for analytics |
| Evidence pack | Runtime quality metrics linked back to the policies they should tune |

SoR is decided at **attribute level** where responsibility differs (legal name from a
registry; local display name in a TMS).

---

## 4. Scope by phase

### 4.1 Phase 1 — analytical MDM (reporting only)

- consolidate in-scope Party records across selected sources;
- allocate and persist `MDM_PARTY_ID`; maintain the source crosswalk;
- expose only minimal reporting attributes;
- route missing/conflicting identifiers to a stewardship queue;
- publish crosswalk + reporting dimension into the Warehouse;
- corrections happen in the source; **no** operational write-back.

Phase 1 does **not** create full golden records, change operational SoR ownership, manage
Party Groups, or become an onboarding/KYC application. Its stewardship queue uses a **limited
Phase-1 case path** (a minimal case API/UI for missing/conflicting-identifier decisions),
**not** the full operational MDM API/event surface, which arrives in Phase 2 (§19). Even in
Phase 1, case actions go through that limited API — never direct DB edits.

The identity registry lives in a protected `mdm_registry` Warehouse schema, **not owned by
dbt**: one serialized idempotent identity-allocation pipeline is the only writer; registry
and crosswalk tables are append-only except explicit lifecycle transitions; dbt has
read-only view access and no DDL; full refresh cannot touch `mdm_registry`; merge/crosswalk
history is retained in backup/recovery.

Before concurrent operational authoring begins, the registry migrates **without reminting
IDs** into the Phase-2 operational SQL store. If Phase 2 is already funded, deploy that SQL
store early to avoid the migration (see ADR-9).

### 4.2 Phase 2 — operational MDM

Adds: full golden records; governed create/edit/deactivate/merge/split/unmerge;
attribute-level survivorship and ownership; **entity relationships and hierarchies**
(e.g. Party Groups, parent/subsidiary); reference-data authoring/versioning/publication;
maker/checker approval; operational APIs and events; controlled sync-back where a source
supports it; reconciliation, retry and compensation; data-quality scorecards and SLAs.

Phase 2 is adopted **independently per domain**. Party may use coexistence MDM while an
externally governed reference list stays registry/publish-only.

---

## 5. Architecture

### 5.1 The ontology/runtime boundary

The core ontology answers **what governed concepts mean**. MDM extensions answer **how they
are mastered and governed**. Both are stable, reviewable design intent, so both live in the
ontology hub as `*-mdm-ext.ttl` files, projected by the `mdm-profile` target into an
**immutable** profile release.

The profile references ontology IRIs and configures:

- mastered domains and MDM style per domain;
- attribute-level authoritative sources and ownership;
- **deterministic** matching rules and thresholds, plus an **immutable, content-addressed
  reference** to the probabilistic-matching artifact (see ADR-5) — the profile does not encode
  probabilistic weights in Turtle, and the referenced digest is traced in every match record;
- survivorship precedence, recency, completeness and exception rules;
- automatic-action boundaries and conditions requiring stewardship;
- case routing, SLA, escalation and maker/checker policy;
- governance scopes and **abstract** roles (environment identity mapping kept separate);
- reference-data ownership, release, effective-date and deprecation policy;
- **data-quality rules and scorecard thresholds** (see §11);
- enabled UI capabilities and policy-driven forms (not arbitrary business data).

The extension is reviewed by data governance; the generated profile is immutable; the
runtime records which hub and profile version made each decision.

The dataplatform owns **only technical bindings** — endpoints, secrets, scaling, Entra
group→abstract-role maps, notification channels, connectors, environment rollout. Bindings
may **not** redefine authority, survivorship, matching or approval policy.

| Ontology-hub MDM extension | Dataplatform binding | MDM runtime state |
|---|---|---|
| Mastered/reference classification | DB and service endpoints | Enterprise IDs, crosswalks |
| Match attributes, rules, thresholds | Secrets, managed identities | Candidates, scores, explanations |
| Attribute authority + survivorship | Entra groups → abstract roles | Golden values, provenance |
| Auto-action + maker/checker bounds | Workflow engine, notifications | Cases, assignments, decisions |
| Abstract SLA + escalation policy | Connector endpoints, retries | Timers, retries, escalations |
| Reference ownership/release policy | Scaling, environment rollout | Values, mappings, releases |
| DQ rules + scorecard thresholds | Alert routing, dashboards | Quality scores, breaches |

Production evidence never mutates policy directly. It flows through a reviewed change:

```text
edit *-mdm-ext.ttl -> validate -> review/approve -> project profile -> deploy -> observe
                                                                          |
                                        next reviewed hub change  <-------+  (via evidence pack)
```

### 5.2 Runtime data path

```text
Source ingestion
  -> source-aligned bronze (unchanged history)
  -> canonical normalization (single shared library)
  -> identity resolution + candidate matching
  -> governance decision
  -> durable crosswalk + golden/reference state
  -> versioned API + events (outbox)
  -> analytical Warehouse replica (read-only)
```

Bronze preserves source granularity and is **not** the golden record. Silver provides
canonical analytical representations. The MDM store holds governed operational state. Gold
stays optimized for BI.

### 5.3 Single normalization contract (changed from v1)

Identity resolution and analytical transformation **must** normalize identifiers (VAT,
KBO/BCE, LEI, EORI) identically. v1 proposed two implementations reconciled by conformance
examples; v2 mandates **one source of normalization rules** with an enforced conformance
gate on every realization of it:

- `kairos-mdm-runtime` owns **one source of normalization rules**;
- that single source is realized as **one executable library where the engine allows a shared
  callable/UDF, or generated from the single source** where dbt/Fabric SQL cannot invoke the
  library directly — codegen keeps one rule source but two build outputs, so it does not by
  itself eliminate drift;
- **byte-for-byte conformance examples are the enforced regression gate** on every realization
  (library and any generated variant), which is what actually removes the drift class;
- dbt batch never reimplements an independent set of rules.

The concrete execution model (shared UDF vs codegen), its supported engines, packaging,
version pinning and failure semantics is decided at implementation time; whichever is chosen,
the conformance gate is mandatory. MDM does not consume a gold table. See ADR-4.

---

## 6. Repository responsibilities

### 6.1 Ontology hub (`kairos-ontology-toolkit` consumer)

Owns: domain classes/properties/relationships; master-vs-reference distinction; identifier
semantics and issuer/country context; SHACL constraints; source vocabularies and mappings;
stable intent (mastered entity, match-capable identifier, ownership hint); `*-mdm-ext.ttl`
policy for authority/matching/survivorship/workflow/reference/DQ; the normalization
**contract** + conformance examples; versioned contracts and the projected MDM profile;
compatibility checks and test examples.

The **contract + profile package** is a projection deliverable alongside the dbt and Power BI
packages, pinned by the dataplatform under `contracts/mdm/`.

`kairos-ontology-toolkit` owns the MDM extension **vocabulary**, its SHACL, and the
`mdm-profile` **projector**. Authoring uses the `kairos-design-mdm` skill and the MDM module
of the Ontology Navigator.

Does **not** own: enterprise-ID values or source links; golden/reference values; cases and
decisions; concrete assignees or notification endpoints; product-specific UI layouts;
infrastructure, secrets, SSO, runtime RBAC assignments; connectors, retries, sync-back;
operational audit or monitoring. Provider names and product-specific config never become
ontology annotations. The projector may emit an **abstract** role/permission contract
referencing IRIs; a runtime adapter (configured by the dataplatform) resolves it to a
concrete identity platform.

### 6.2 MDM runtime (`kairos-mdm-runtime`)

Owns reusable, customer-neutral runtime code: versioned MDM API + events; identity
resolution, mastering and survivorship services; reference-data authoring/release/mapping
services; governance cases, workflow, maker/checker and audit; the default stewardship web
app and its extension points; the **single normalization library**; baseline operational
schema and forward migrations; deploy modules/adapters for supported SQL and hosting
platforms; MDM-profile consumption + runtime compatibility checks; conformance/migration
test harnesses.

Publishes versioned containers/packages, UI artifacts, migration bundles and deploy modules.
May consume the product-neutral contract, but does not depend on any customer's ontology hub.

Does **not** own: a customer's live DB, IDs, values or audit history; customer authority /
survivorship / approval decisions; customer infra, secrets, identity assignments or support;
source credentials or customer connectors; analytical models in a customer Warehouse.

> **Repo-split rule (ADR-2):** `kairos-mdm-runtime` MAY start life as a package/module inside
> the toolkit workspace. It is promoted to its own repository **only when** it needs an
> independent release train (different cadence, different consumers, or different release
> authority). Do not pay the pinning/compat-matrix cost before there is a second consumer.

### 6.3 Dataplatform repo

Owns: consumption of pinned ontology-hub contract + runtime releases; deployment of the
projected MDM profile; operational DB infrastructure + executed migration history; technical
bindings and permitted extensions; deployment of API, services and Stewardship UI; source
ingestion + sync-back connectors; Warehouse publication models; Entra integration + runtime
role assignments; secrets, observability, backup, restore, DR, incident response; production
tuning and support. Ontology projections still run **only** in the ontology hub.

### 6.4 Data-governance organisation

Owns business accountability technology cannot assign: data-domain ownership; authoritative-
source decisions; DQ policy and thresholds; approval of MDM extensions and profile promotion;
steward/approver assignments; merge/split policy; retention and privacy policy; approval of
destructive changes; periodic review of rules and access; **consumer entitlement approval**
(§14.1).

### 6.5 Source applications

Remain the SoE unless a domain moves to centralized MDM; expose stable keys and change
events/extracts; accept approved changes only through supported integration contracts; return
acknowledgements/rejections; preserve local fields outside MDM ownership.

### 6.6 Reference-data ownership

| Concern | Owner |
|---|---|
| Meaning of a reference concept + relationships | Ontology hub |
| Structural constraints, identifier semantics, intent | Ontology hub |
| Reusable authoring/approval/versioning/publication capability | MDM runtime |
| Actual values, labels, mappings, dates, releases, approvals | MDM operational DB |
| Customer authority/ownership/release policy | `*-mdm-ext.ttl` + profile |
| External-authority provenance + license/attribution | MDM operational DB + `NOTICE` |
| Approved analytical copy | Fabric Warehouse |

External standards may seed a list, but once values need effective dating, approval,
deprecation, mappings or reconciliation, the governed record lives in the MDM DB — the
ontology hub is **not** a transactional reference-data store. Where a source list carries
license/attribution terms, they are tracked with the release and surfaced in `NOTICE`.

---

## 7. Repository layout

`kairos-mdm-runtime` (conceptual):

```text
kairos-mdm-runtime/
|-- services/           # API, identity, mastering, reference, workflow
|-- normalization/      # single shared identifier library (batch + runtime)
|-- apps/stewardship/   # operational stewardship web UI
|-- database/migrations/# versioned baseline operational schema
|-- deploy/{azure,portable}/
|-- contracts/          # ontology-contract reader + compatibility logic
`-- tests/              # product, migration, conformance
```

The customer dataplatform composes released artifacts without forking implementation source:

```text
dataplatform/
|-- packages.yml                 # pinned ontology-hub dbt package
|-- contracts/mdm/               # pinned contract + profile release
|-- deploy/mdm/                  # pinned runtime artifacts/modules
|-- config/mdm/{bindings,environments,ui}/
|-- dbt/models/mdm_publish/      # analytical replica/read models
|-- infra/mdm/                   # SQL DB, identity, network, secrets
|-- migrations/mdm-extensions/   # reviewed customer migrations via runtime extension points
|-- integration/{inbound,outbound}/
`-- .github/workflows/
    |-- deploy-mdm-infra.yml
    |-- migrate-mdm.yml
    |-- deploy-mdm-services.yml
    `-- publish-mdm-warehouse.yml
```

> **Migration-override rule (changed from v1):** customer migrations use
> `kairos-mdm-runtime`-declared **extension points** (`migrations/mdm-extensions/`), whose
> compatibility validation the runtime supplies — not a free-form overrides folder, so
> live-schema divergence cannot silently accumulate. See ADR-8.

### 7.1 Deployment and upgrade lifecycle

1. Data governance approves the `*-mdm-ext.ttl` extensions.
2. The ontology hub projects and releases a versioned contract + MDM profile.
3. `kairos-mdm-runtime` releases tested containers, the stewardship UI, migrations and deploy
   modules.
4. The dataplatform pins both releases and supplies bindings, infra settings and connectors.
5. The dataplatform provisions the live operational DB from a runtime module; all data in it
   belongs to the customer runtime.
6. The pipeline applies reviewed migrations and records execution; customer migrations are
   declared extension overlays only.
7. The dataplatform deploys profile, API, services and UI as independently versioned
   components, then publishes approved state to the Warehouse.
8. Hub and runtime upgrades are tested independently before either pin advances. **No upgrade
   may regenerate enterprise IDs or governed state.**

---

## 8. Runtime components and non-overlapping functions

| Component | Sole responsibility | Not responsible for |
|---|---|---|
| Ingestion/bronze | Preserve source records + arrival metadata | Golden-record decisions |
| Normalization | Canonicalize/validate identifiers (one library) | Linking or survivorship |
| Identity resolution | Find candidate duplicates, propose links | Approving ambiguous decisions |
| Mastering service | Apply approved links/merges/survivorship + relationships | UI workflow or BI modeling |
| Reference-data service | Govern lists, values, mappings, releases | Master-entity matching |
| Workflow service | Cases, assignment, approval, SLA, escalation | Deciding match algorithms |
| DQ service | Evaluate DQ rules, produce scorecards + evidence packs | Deciding survivorship |
| MDM operational store | Durable approved state + history | Analytical star schemas |
| MDM API/events | Stable consumer contracts | Exposing physical tables |
| Stewardship UI | Human interaction via APIs | Direct database ownership |
| Publication adapter | Write approved versions to outbox/landing | Write into analytical models |
| dbt/gold | Analytical dimensions and facts | Allocate enterprise identity |

This separation prevents a UI, dbt model or matching engine from silently becoming the
authoritative MDM system.

---

## 9. Logical data model

Physical schema may vary; the runtime must support these logical records.

### 9.1 Master-data records

| Record | Required content |
|---|---|
| Enterprise entity | Durable enterprise ID, entity type, lifecycle state, version |
| Source-record link | Source system, source entity type, source key, valid period, status |
| Identifier | Type, issuer/country, normalized value, validation status, valid period |
| Golden attribute | Value, provenance, effective period, decision, rule + profile version |
| **Entity relationship** | Relationship type, from/to enterprise ID, valid period, decision provenance |
| Match candidate | Candidate entities, score, rule/profile version, explanation |
| Merge lineage | Survivor, predecessor, reason, decision, effective period |
| Stewardship decision | Actor, role, action, reason, before/after, profile version, timestamp |
| Publication event | Entity version, event ID, consumers, delivery state |

Enterprise IDs are append-only and never reused. Source links are temporally versioned. A
merge tombstones the loser and points it to the survivor. Split/unmerge retain provenance and
never rewrite history. **Entity relationships** (hierarchies, householding, Party Groups) are
first-class, temporally versioned records — added in v2 (ADR-6).

### 9.2 Reference-data records

| Record | Required content |
|---|---|
| Reference list | Stable list ID, owner, authority, lifecycle, version policy, **license/attribution** |
| Reference value | Code, labels, effective dates, status, provenance |
| Source mapping | External/source code → governed code, valid period |
| Replacement relation | Deprecated code, replacement code, transition date |
| Release | Version, approval, publication date, compatibility class |
| Consumer delivery | Consumer, release, delivery/ack state |
| Consumer entitlement | Consumer ID, approver, granted domains/attribute scope, effective period, delivery endpoints, status |

Values are deprecated, not deleted, after publication.

### 9.3 Cases, audit and access log

Master and reference workflows share one governance-case capability: case type + affected
entity/list; severity/priority/risk; assignee/role/scope; status/SLA/escalation; evidence +
comments; proposed + approved actions; immutable decision history.

**Access-decision log (added in v2, ADR-7):** every controlled action and every denied
attempt records actor, abstract role, **role-binding version**, scope, decision (allow/deny),
reason, **requested and returned field sets, masking rule + result**, and profile version.
A separate **identity-binding change history** records role-assignment/mapping changes with
effective periods. Together these satisfy field-level masking audit (ACCESS-05) and effective-
access / denied-action / role-change recertification (ACCESS-06); the access-decision log
alone cannot prove role-change history, which is why binding-change history is distinct.

### 9.4 Privacy records (added in v2)

| Record | Required content |
|---|---|
| Subject-rights request | Subject reference, request type (access/rectify/erase/restrict), status, legal basis |
| Redaction/erasure action | Target attribute/entity, method (redact / crypto-shred / purge), decision, retained non-identifying lineage keys, erasure-ledger entry |

See §12 for how erasure reconciles with append-only immutability.

---

## 10. Governance flows

### 10.1 New client creation

```text
Create request -> search-before-create -> normalize + validate -> candidate matching
  -> auto-link | stewardship case | proposed creation -> maker/checker approval
  -> enterprise ID allocation -> source crosswalk -> approved publication -> reconciliation
```

Exact, policy-safe matches may auto-link only when no conflicting authoritative identifier
exists. Probable matches open a case with side-by-side values, provenance, confidence and
rule explanation. No-match becomes a proposed entity; a distinct approver activates it where
four-eyes is required. The identity service allocates the enterprise ID **once**, creates the
source link, and the outbox publishes to consumers + Warehouse; ack/reconcile closes the
request. MDM supplies governed identity/party data to onboarding/KYC but does not own that
business process.

### 10.2 Conflicting attributes

```text
Source change -> preserve raw + provenance -> normalize + resolve identity
  -> detect conflict -> evaluate authority/survivorship -> auto-resolve | case
  -> steward decision + approval -> new golden version -> publish/sync/reconcile
```

Deterministic low-risk rules may auto-resolve (recording rule version + evidence). Ambiguous,
high-risk or authoritative-source conflicts open a case with values, provenance, timestamps,
validation, downstream impact and proposed action. High-impact attributes require a separate
approver. A **new golden version** is created; history is never overwritten. Sync-back (if
present) consumes the published event; consumer/source acks are reconciled.

### 10.3 Duplicate merge

Identity resolution proposes a duplicate cluster with evidence; a steward reviews
identifiers, links, relationships and impact; conflicting authoritative identifiers block
auto-merge; approval selects the surviving ID and attribute-level survivors; the loser is
tombstoned and linked to the survivor; crosswalk history stays queryable; a merge event
carries both IDs, effective time and golden version; unmerge remains possible via a new
governed decision and never erases history.

### 10.4 Missing or invalid identifier

Validation opens a case rather than inventing an identifier. Phase 1: the assignee corrects
the value in the SoE; the corrected record returns via ingestion and closes the case after
match. Phase 2: policy may permit a clearly-marked, stewarded provisional entity excluded
from selected downstream processes.

### 10.5 Reference-data governance

```text
Proposal | authority import -> structural + semantic validation -> mapping + impact analysis
  -> steward review -> maker/checker approval -> scheduled versioned release
  -> API/event publication -> consumer acknowledgement -> monitoring -> deprecation
```

Releases classify compatibility as **additive** (backward compatible), **deprecating** (old
value valid during transition) or **breaking** (meaning/key change requiring consumer
migration). Emergency changes follow an expedited but audited path. External-authority
imports record license/attribution.

---

## 11. Data quality (operationalized — new in v2)

DQ is not just monitoring; it is governed policy with a feedback loop.

- **DQ rules are authored in `*-mdm-ext.ttl`** against the six DAMA dimensions — accuracy,
  completeness, consistency, timeliness, uniqueness, validity — and projected into the
  profile with scorecard thresholds.
- The **DQ service** evaluates rules over golden/reference state and produces **scorecards**.
- A breached threshold can **generate a stewardship case** (not just an alert).
- Match precision/recall, conflict rate and SLA breach metrics are gathered into an
  **evidence pack** (§13) linked to the specific policies that should be tuned — this
  realizes DESIGN-09 with a concrete artifact rather than a diagram.

| Quality concern | Owner |
|---|---|
| File/schema ingestion validity | Dataplatform ingestion |
| Source-to-domain mapping validity | Ontology contract + dataplatform impl |
| Identifier format/semantic constraints | Shared contract, enforced by runtime |
| Match precision/recall, conflict rate | Mastering + DQ service + governance |
| Golden-record completeness/freshness | DQ service |
| BI model tests | dbt/gold |
| Source correction | Source owner via stewardship case |

---

## 12. Privacy vs. immutability (new in v2)

Append-only lineage ("IDs never reused, history never erased") **conflicts** with the GDPR
right to erasure. v2 reconciles them, but does **not** claim lineage is automatically
non-personal:

- **Structural records are retained only after field-level classification.** Enterprise IDs,
  crosswalk topology and merge lineage are retained where they are non-identifying, but source
  keys, actor identities and decision `before/after` payloads **can** be personal data and are
  classified per field with a legal basis and retention; identifying lineage fields are erased
  or irreversibly anonymized when required, leaving only a non-identifying decision shell.
- **Personal attribute values are erasable by crypto-shredding or redaction:** the golden
  attribute value is destroyed (per-subject/value key destruction) or overwritten while the
  versioned record shell, non-identifying decision provenance and profile version remain,
  preserving auditability of *that a decision occurred* without retaining erased content.
- Payload-free audit records are preferred where the audited fact needs no personal content.
- A **subject-rights request** (§9.4) is itself a governed, audited case with a legal basis.
- Field-level classification drives masking at rest and in the UI; erasure is a distinct,
  approved action, not a delete.
- **Erasure must reach every copy.** Bronze source-aligned history, outbox payloads, dbt
  history models, Warehouse replicas and exports are covered by an **erasure ledger**:
  publication carries redaction/erasure events, replicas acknowledge them, and backup
  expiration or restore-time reapplication of the ledger prevents an old backup from
  resurrecting erased values. Where crypto-shredding is unavailable, physical
  purge/compaction rules apply.

This keeps audit integrity (the *shape* and non-identifying *decisions* of history) while
satisfying erasure of personal *content* across all copies. See ADR-10.

---

## 13. Evidence feedback (new in v2)

The runtime → hub tuning loop needs a real artifact, not just an arrow:

- the DQ/mastering services emit a versioned **evidence pack**: match precision/recall,
  ambiguous-candidate rate, false-merge corrections, conflict rate, SLA breaches — each tagged
  with the **profile version**, **rule version** and affected **policy IRIs**;
- the `kairos-design-mdm` skill / Ontology Navigator MDM module consumes an evidence pack to
  propose a reviewed `*-mdm-ext.ttl` change (e.g. adjust a threshold or survivorship rule);
- observed scores and records stay runtime data and are **never** copied into the ontology;
- the change follows the normal validate → review → project → deploy path.

This makes DESIGN-09 implementable and keeps production tuning out of direct policy mutation.

---

## 14. API, events and consumer entitlement

Consumers never touch raw tables or a generic DB API. The MDM service exposes versioned
domain contracts: resolve source key → enterprise ID; search entities; submit create/change
request; retrieve approved current/historical versions; retrieve reference releases; inspect
request/publication status. Commands require an idempotency key; responses expose stable
domain fields, not physical schema.

Events use an **outbox** and include: event ID + schema version; aggregate ID + version;
event type + effective time; causation/correlation IDs; origin system; semantic-contract,
MDM-profile and decision/rule versions where relevant; payload or stable retrieval link.
Consumers must handle duplicate delivery.

### 14.1 Consumer entitlement (new in v2)

Consuming golden records is a governed privilege: each operational/analytical consumer is
**registered and entitlement-approved** by data governance (§6.4), scoped to specific domains
and attribute sets, and reconciled against delivery. This closes the gap where anyone with
event access could implicitly consume mastered data.

### 14.2 Sync-back status

Sync-back is a **Phase-2 conceptual contract, not an implemented design**. A dedicated
integration architecture must define target acknowledgement, rejection reasons, idempotency,
retry, dead-letter, replay, compensation, field-ownership conflicts and legal accountability.
`originSystem` alone is not sufficient loop prevention. Coexistence MDM is not truly achieved
until sync-back lands (ADR-3).

---

## 15. Security, RBAC and persistence

Reuse Entra groups and governance roles where appropriate, but MDM permissions are
**independent** from Warehouse grants.

| Role | Typical permissions |
|---|---|
| Requester | Submit create/change requests, view status |
| Data steward | Investigate cases, propose decisions within scope |
| Data owner/approver | Approve high-impact/policy-controlled decisions |
| MDM system writer | Apply approved service commands; no interactive login |
| Integration publisher | Publish approved versions; cannot alter golden state |
| Operational reader | Read approved domain API views (entitlement-scoped) |
| Analytical publisher | Read approved publication views for replication |
| Auditor | Read decisions/provenance/audit + access log; no modification |
| Platform operator | Operate infrastructure without business approval authority |

Controls: least privilege + deny-by-default; global/local + domain scope; field-level
restrictions for sensitive attributes; maker/checker separation; service vs human identities;
encryption in transit and at rest; secrets in the platform store; access review and role
recertification; immutable audit + access-decision log export with retention; privacy
classification, masking and erasure procedures (§12). Warehouse RLS may mirror approved
business scopes but is generated and enforced separately from operational write permissions.

**Persistence** changes only through reviewed, forward migrations: additive changes automated
after compatibility checks; explicit restartable observable backfills; destructive changes
need data-owner + platform approval; enterprise IDs/crosswalks/decisions/audit/published
reference values are never dropped or regenerated; drift detected before deploy; ordering
separates schema/backfill/service/publication; rollback normally means a forward corrective
migration; backups taken and restore tested. The runtime owns schema + migration **code**;
the dataplatform owns provisioning, execution, credentials, backups and all live **data**.

---

## 16. Warehouse publication

Only approved MDM state is published.

```text
MDM transaction -> transactional outbox -> dataplatform ingestion
  -> append-only MDM bronze events -> idempotent dbt current/history models
  -> gold dimensions + semantic models
```

The outbox + aggregate version prevent commit/publish divergence. Ingestion is at-least-once;
dbt deduplicates by event ID and applies aggregate versions in order. `mdm_publish/` models
are dataplatform-owned and consume the product-neutral MDM event contract. In Phase 1 the
protected registry already lives in the Warehouse; dbt reads its views but cannot modify its
tables. Erasure events (§12) propagate so replicas cannot resurrect erased values.

Recommended analytical schemas: `mdm_current.{party, party_crosswalk, reference_value}`;
`mdm_history.{party_version, crosswalk_version, reference_release}`;
`mdm_quality.{case_metrics, publication_reconciliation, dq_scorecard}`.

Historical facts remain resolvable to the enterprise ID + crosswalk version valid when
loaded; current-state rollups may follow merge lineage to the surviving ID. These are
separate analytical views.

---

## 17. UI strategy (two surfaces, not three)

v1 proposed three design/operational UIs. v2 uses **two surfaces**:

1. **Design portal — Ontology Navigator with an MDM authoring module.** Explores the
   ontology, mappings, constraints and semantic impact, and — via the MDM module (backed by
   the `kairos-design-mdm` skill) — authors and validates `*-mdm-ext.ttl` policy in business
   terms, writing RDF through toolkit operations (never concatenating Turtle) and producing a
   reviewed PR. It must not silently modify active production policy. Design-time only.
2. **Stewardship UI — the operational surface** shipped by `kairos-mdm-runtime`, deployed by
   the dataplatform against the versioned API. Independently deployable; not embedded in the
   DB, dbt project or Warehouse.

Stewardship UI minimum capabilities: search-before-create; side-by-side comparison with
provenance; match explanation + confidence; create/change/merge/split/unmerge proposals;
relationship/hierarchy editing; reference-list editing + release prep; assignment/SLA/
escalation; maker/checker; impact preview; audit + decision history; accessibility +
localization.

Candidate stewardship implementations: the default runtime web app (e.g. React + Refine/
react-admin); a customer replacement (Power Apps over the versioned API); an internal-tool
platform (Appsmith); a data platform (Directus, subject to license/fit review). **No
candidate may bypass the domain API** to become the de facto owner of MDM state; direct DB
admin interfaces are limited to platform operations.

The two surfaces reuse a shared design system, auth shell and graph components, may appear as
modules in one Kairos portal, and deep-link (class/constraint ↔ affected profile policy ↔
operational evidence ↔ semantic definition + lineage). All create/approve/merge/reference
actions still go through the MDM API. See ADR-1.

---

## 18. Epics and baseline user stories

Epics establish a product-level backlog per principal role. Feature refinement adds
domain-specific acceptance criteria, security constraints and measurable outcomes.

### 18.1 MDM-DESIGN — Define mastered concepts and policy (MDM designer, design portal)

| ID | User story |
|---|---|
| DESIGN-01 | Designate ontology classes as master- or reference-data so MDM scope is explicit and machine-readable. |
| DESIGN-02 | Identify enterprise identifiers, match attributes and normalization rules so the runtime resolves records consistently. |
| DESIGN-03 | Define attribute-level authority and survivorship so golden values follow approved business rules. |
| DESIGN-04 | Define auto-action boundaries, maker/checker and abstract workflow so ambiguous/high-risk decisions require governance. |
| DESIGN-05 | Define reference-data ownership, release and deprecation so lists follow a consistent lifecycle. |
| DESIGN-06 | Define DQ rules and scorecard thresholds so quality is governed policy, not ad-hoc monitoring. |
| DESIGN-07 | Validate MDM extensions and see semantic + runtime impact before a PR so invalid/breaking policy never reaches production. |
| DESIGN-08 | Have approved extensions projected into an immutable profile so every runtime decision traces to reviewed design. |
| DESIGN-09 | Consume a runtime **evidence pack** to propose a reviewed threshold/survivorship change so tuning stays governed. |

### 18.2 MDM-DEPLOY — Deploy and operate an instance (dataplatform engineer)

| ID | User story |
|---|---|
| DEPLOY-01 | Pin compatible ontology-hub and runtime releases so deployments are reproducible and independently upgradeable. |
| DEPLOY-02 | Provision the supported operational DB from runtime modules so durable state is isolated from dbt schemas. |
| DEPLOY-03 | Apply reviewed forward migrations with drift checks + restartable backfills preserving IDs/crosswalks/audit. |
| DEPLOY-04 | Configure technical bindings (identities, endpoints, secrets, connectors, notifications) without duplicating policy. |
| DEPLOY-05 | Deploy profile, API, services and Stewardship UI as versioned components promoted and rolled forward safely. |
| DEPLOY-06 | Publish and reconcile approved MDM events with the Warehouse so analytics receive trusted current + historical data. |
| DEPLOY-07 | Monitor health, audit, backlog, backup and restore so the instance meets its operational objectives. |

### 18.3 MDM-STEWARD — Govern master and reference data (data steward / SoE user)

| ID | User story |
|---|---|
| STEWARD-01 | Search before creating master data so an existing entity is reused instead of duplicated. |
| STEWARD-02 | Submit a proposed record when no credible match exists so creation follows validation + approval. |
| STEWARD-03 | Compare candidates with identifiers, provenance, confidence and rule explanations for evidence-based decisions. |
| STEWARD-04 | Review conflicting values and proposed survivorship to accept/reject/override with a recorded reason. |
| STEWARD-05 | Propose merge/split/unmerge and **maintain entity relationships/hierarchies** with impact visibility, without erasing history. |
| STEWARD-06 | Create/maintain reference values, source mappings, effective dates and deprecations for approved releases. |
| STEWARD-07 | Have cases assigned, prioritized and escalated by policy so exceptions resolve within SLAs. |
| STEWARD-08 | See publication + source acknowledgements so failed corrections/sync-back stay actionable. |

### 18.4 MDM-ACCESS — Govern steward access (MDM administrator)

| ID | User story |
|---|---|
| ACCESS-01 | Define abstract steward/approver/requester/auditor/operator permissions reusable across environments. |
| ACCESS-02 | Scope permissions by domain, geography, organisation and action. |
| ACCESS-03 | Define maker/checker and separation-of-duty so an action can't be requested and approved by one person. |
| ACCESS-04 | Map approved identity groups to abstract roles per environment. |
| ACCESS-05 | Mask/restrict sensitive attributes by role, with masking recorded in the access-decision log. |
| ACCESS-06 | Review effective access, **denied actions** and role changes via the access-decision log for recertification. |
| ACCESS-07 | Have policy reviewed in the hub and identity bindings deployed via the dataplatform — no production-only RBAC source of truth. |

### 18.5 MDM-CONSUME — Consume mastered data (new in v2; operational/analytical consumer)

| ID | User story |
|---|---|
| CONSUME-01 | Register as a consumer and obtain entitlement-approved, scoped access to golden records/reference releases. |
| CONSUME-02 | Resolve a source key to an enterprise ID via a stable versioned API. |
| CONSUME-03 | Subscribe to approved events and handle duplicates/ordering via aggregate version. |
| CONSUME-04 | Reconcile the reference/profile version I consume so lagging versions are detectable. |

### 18.6 MDM-INTEGRATE — Source-system integration (new in v2; source owner)

| ID | User story |
|---|---|
| INTEGRATE-01 | Expose stable source keys and change events/extracts so ingestion resolves identity reliably. |
| INTEGRATE-02 | Receive approved sync-back changes with acknowledgement/rejection reasons. **(Gated: depends on the §14.2 sync-back integration milestone, which is not yet designed.)** |
| INTEGRATE-03 | Preserve source-local fields outside MDM ownership so mastering doesn't overwrite them. |

> **Sync-back gating:** stories whose value depends on write-back to sources — INTEGRATE-02
> and the sync-back portion of STEWARD-08 — are **not implementable** until the §14.2 sync-back
> integration architecture (acknowledgement, rejection, idempotency, retry, dead-letter,
> replay, compensation, field-ownership conflict, loop prevention) is designed and approved.
> They are backlog-visible but scheduled behind that milestone (see ADR-3). The publication/
> acknowledgement portion of STEWARD-08 does not depend on sync-back and is available in
> Phase 2.

### 18.7 MDM-AUDIT — Audit, privacy and compliance (new in v2; auditor / privacy officer)

| ID | User story |
|---|---|
| AUDIT-01 | Read immutable decision, provenance and access-decision history without modification. |
| AUDIT-02 | Raise and track subject-rights requests (access/rectify/erase/restrict) as governed cases. |
| AUDIT-03 | Have personal-attribute erasure applied by redaction/crypto-shred while retaining non-personal lineage + audit. |
| AUDIT-04 | Verify Warehouse replicas honor erasure so analytical copies can't resurrect erased values. |

### 18.8 MDM-NFR — Non-functional guarantees (new in v2; platform + governance)

| ID | User story |
|---|---|
| NFR-01 | Agree and verify API latency/availability SLOs before Phase-2 production use. |
| NFR-02 | Agree RPO/RTO and prove backup/restore and DR via a tested drill. |
| NFR-03 | Prove Phase 1 survives a dbt full refresh without changing identities. |
| NFR-04 | Enforce the single normalization library via a shared conformance regression gate. |

Main handoff:

```text
MDM designer/admin -> reviewed *-mdm-ext.ttl -> projected profile
   -> dataplatform engineer deployment -> steward/consumer/runtime decisions
   -> evidence pack -> next reviewed hub change
```

---

## 19. Functional coverage

| Capability | Phase 1 | Phase 2 | Design owner |
|---|:---:|:---:|---|
| Durable enterprise identity | Yes | Yes | MDM runtime |
| Source crosswalk + history | Yes | Yes | MDM runtime |
| Exact validated matching | Yes | Yes | Identity resolution |
| Probabilistic matching | No | Optional | Identity resolution (artifact, ADR-5) |
| Search-before-create | Limited | Yes | MDM API |
| Exception/case queue | Yes | Yes | Workflow service |
| Golden-record authoring | No | Yes | Mastering service |
| Attribute survivorship | No | Yes | Mastering service |
| Entity relationships/hierarchies | No | Yes | Mastering + workflow |
| Merge/split/unmerge | No | Yes | Mastering + workflow |
| Maker/checker approval | Manual ID decisions | Yes | Workflow service |
| Reference-list harmonization | Read/publish | Yes | Reference-data service |
| Effective dating + releases | Limited | Yes | Reference-data service |
| Source-code mappings | Yes | Yes | Reference-data service |
| Consumer impact + entitlement | Limited | Yes | Reference-data service + governance |
| Data-quality scorecards | Limited | Yes | DQ service |
| Privacy / subject-rights | Basic | Yes | Runtime + governance |
| Operational API/events | No | Yes | MDM API |
| Source sync-back | No | Optional | Integration |
| Warehouse publication | Yes | Yes | Dataplatform/dbt |
| RBAC + immutable audit + access log | Yes | Yes | Platform + governance |
| KYC/onboarding process | External | External | Business application |
| BI semantic modeling | Yes | Yes | Gold/Power BI |

---

## 20. Delivery sequence

**Phase 1:** confirm Party scope, sources and reporting attributes; approve the identity +
crosswalk contract; define country-aware identifier normalization + conformance examples;
apply the protected `mdm_registry` schema and deny dbt write/DDL; deploy the serialized
idempotent identity-allocation pipeline; add exact-match + missing/conflicting policy to
`*-mdm-ext.ttl`; publish read-only crosswalk views + reporting dimension; prove dbt full
refresh cannot alter IDs (NFR-03); measure match quality before expanding.

**Phase-2 readiness gate** — do not start operational MDM until all are agreed: mastered
domains + style per domain; attribute-level ownership + authoritative sources; an approved
initial profile valid against the contract; governance roles + staffed stewardship model;
the operational store; API/event SLOs; merge/split/unmerge policy; sync-back ownership +
failure handling; privacy/retention/audit policy; RPO/RTO/backup/DR/support ownership.

**Phase 2:** release contract + approved initial profile; deploy the operational store and
migrate Phase-1 identities without reminting; pin + deploy a `kairos-mdm-runtime` release
(profile, API, schema, outbox, workflow); add golden attributes one domain slice at a time;
deploy + configure the Stewardship UI against the API; add entity relationships; add
reference-data releases + consumer reconciliation; add sync-back only after read-only
publication is stable; add probabilistic matching only when measured cases justify it.

---

## 21. Acceptance criteria

Ready for implementation when: repository + runtime ownership is approved; contract/profile
and runtime versions pin independently; every durable asset has one owner; no generated
process can recreate enterprise IDs or stewarded state; Phase 1 survives a dbt full refresh;
normalization runs through **one** library gated by shared conformance; every decision
records actor/reason/evidence/before-after + active contract/profile versions; profile
changes are validated, approved, immutable after release, and promoted via deployment (not
direct mutation); APIs/events hide physical tables and version independently; Warehouse
consumers are read-only and entitlement-scoped; reference releases support impact/approval/
effective-dates/deprecation; merge/split history keeps facts resolvable; RBAC enforces domain
scope + maker/checker; the access-decision log supports recertification; privacy erasure works
without breaking audit lineage; publication + sync-back have reconciliation + failure
handling; backup/restore + operational ownership proven; the Stewardship UI can be replaced
without migrating MDM state.

---

## 22. Architecture decisions (rationale)

The crucial, load-bearing decisions. Each states the decision, why, and what it rejects.

### ADR-1 — MDM policy is an ontology extension + projection target, not a new toolkit
**Decision:** MDM policy authoring reuses the existing extension pattern
(`model/extensions/<domain>-mdm-ext.ttl`) and a new `mdm-profile` projection target in
`kairos-ontology-toolkit`, authored via the `kairos-design-mdm` skill and an MDM module of
the Ontology Navigator.
**Why:** authority/matching/survivorship/reference policy is stable, reviewable design intent
— exactly what silver/gold extensions already are. Adding an 8th projection target and a
vocabulary is far cheaper than a second design product, and it inherits validation, review
and versioning for free.
**Rejects:** a standalone "MDM Navigator" application and a separate policy pipeline; three
distinct design/operational UIs (collapsed to two surfaces, §17).

### ADR-2 — One runtime product, split repo only on cadence divergence
**Decision:** all MDM runtime software lives in a single `kairos-mdm-runtime` product, which
may start as a module in the toolkit workspace and is promoted to its own repository **only
when** it needs an independent release train.
**Why:** premature repo-splitting imposes a pinning/compatibility-matrix tax before a second
consumer exists.
**Rejects:** day-one four-repo topology; per-service repos.

### ADR-3 — No `<client>-mdm-hub` repo; sync-back gates "coexistence"
**Decision:** the dataplatform is the default deployment boundary; a customer MDM repo is
justified only by a different owner, regulatory boundary or release authority. Coexistence MDM
is not considered achieved until sync-back is designed and deployed.
**Why:** avoids a fourth customer repo; prevents overstating maturity when write-back is
absent.
**Rejects:** default per-client MDM hub; calling registry+golden-read "coexistence".

### ADR-4 — Single source of normalization rules
**Decision:** one source of normalization rules in `kairos-mdm-runtime`, realized as a shared
callable/UDF where the engine allows and generated from that single source where dbt/Fabric
SQL cannot invoke it; the hub owns the contract + conformance examples used as a **byte-for-
byte regression gate** on every realization.
**Why:** two independently authored implementations drift on identifier edge cases (VAT/LEI/
EORI). A single rule source plus a mandatory conformance gate removes the drift class; codegen
alone does not, which is why the gate — not the packaging choice — is the load-bearing part.
**Rejects:** v1's parallel dbt + runtime implementations; claiming a shared source removes
drift without a conformance gate.

### ADR-5 — Deterministic policy in Turtle; probabilistic model as an owned, versioned artifact
**Decision:** the profile encodes match-capable attributes + deterministic rules/thresholds
in RDF and **references, by immutable content-addressed version, a separately versioned
probabilistic-matching artifact** for weights/features/blocking keys. The artifact is owned
and released by `kairos-mdm-runtime`, approved through the same governance path as profile
changes, and its digest is recorded in the profile and in every affected match
candidate/decision/event/evidence record.
**Why:** probabilistic models don't model cleanly as ontology annotations; forcing them into
Turtle produces an awkward config format. But a *mutable* referenced artifact would bypass
ADR-12's reviewed loop, so it must be immutable, versioned and traced like any other policy.
**Rejects:** authoring probabilistic weights in `*-mdm-ext.ttl`; a mutable or untraced
artifact reference.

### ADR-6 — Entity relationships/hierarchies are first-class
**Decision:** the logical model includes temporally versioned entity-relationship records
(hierarchies, householding, Party Groups) as governed, provenance-bearing state.
**Why:** most Phase-2 programs need relationship mastering; omitting it from the model forces
ungoverned workarounds later.
**Rejects:** treating relationships as an out-of-model afterthought.

### ADR-7 — Access-decision log is durable state
**Decision:** every controlled action and denied attempt is logged with actor, abstract role,
scope, allow/deny, reason and profile version.
**Why:** ACCESS-05/06 (masking audit, denied-action review, recertification) are unimplement-
able without it.
**Rejects:** relying on inferred access from role config alone.

### ADR-8 — Customer migrations via runtime-declared extension points
**Decision:** customer-specific migrations use `kairos-mdm-runtime`-declared extension points
(`migrations/mdm-extensions/`), with compatibility validation supplied by the runtime, not a
free-form overrides folder.
**Why:** free-form overrides invite silent live-schema divergence from the product baseline;
the runtime owns schema + migration code (§6.2), so it must own the extension contract too.
**Rejects:** v1's `mdm-overrides/` free folder; toolkit-owned migration extension points.

### ADR-9 — Deploy the operational SQL store early when Phase 2 is committed
**Decision:** if Phase 2 is funded, deploy the operational SQL store at Phase 1 rather than
building the Warehouse `mdm_registry` and migrating later; otherwise keep the protected
registry-in-Warehouse and migrate without reminting.
**Why:** the migration has real cost; commitment level is the deciding criterion.
**Rejects:** unconditionally building the Warehouse registry first.

### ADR-10 — Erasure by redaction/crypto-shred across all copies, retaining only non-identifying lineage
**Decision:** GDPR erasure destroys/overwrites personal attribute **values** and any
identifying lineage fields (per field-level classification), while retaining non-identifying
enterprise IDs, crosswalk topology, merge lineage and decision shells; an **erasure ledger**
propagates to bronze, outbox, dbt history, Warehouse replicas, exports and backups (via
expiration or restore-time reapplication).
**Why:** reconciles "history never erased" (audit integrity) with the right to erasure
(content removal). Lineage is **not** assumed non-personal — that assumption would itself
breach GDPR; classification decides what is retained.
**Rejects:** hard-deleting records (breaks audit); refusing erasure (breaks GDPR); assuming
IDs/crosswalks/before-after are automatically non-personal; erasing only the primary copy.

### ADR-11 — Durable state is never regenerable; generated artifacts are replaceable
**Decision (retained from v1, restated as the keystone):** enterprise IDs, crosswalks,
stewardship decisions, merge history, audit, access log and reference values are never
recreated by projection; the hub generates only semantic contracts + the MDM profile; the
runtime provides software + baseline migrations; neither creates, resets or owns live data.
**Why:** this is the invariant every other decision protects; violating it silently corrupts
identity and audit.
**Rejects:** dbt or any generated pipeline owning identity/golden state.

### ADR-12 — Policy changes only through the reviewed hub loop
**Decision:** runtime observations flow back as an **evidence pack**; policy changes only via
`edit → validate → review → project → deploy`. Production tuning never mutates the profile
directly.
**Why:** keeps governance auditable and prevents production-only policy drift.
**Rejects:** hot-editing thresholds/survivorship in the running system.

---

_This design keeps Kairos shift-left: semantics and MDM policy are model-driven and
projected; reusable runtime code is productized once in `kairos-mdm-runtime`; durable business
state and operational responsibility remain in the dataplatform where they can be secured,
migrated, monitored and governed._
