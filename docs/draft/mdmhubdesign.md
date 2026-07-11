# MDM Hub Design

_Draft architecture proposal - based on `mdmhub.md`, the MDM deep-dive, and the
governance walkthrough._

> **Design status:** this document supersedes the repository placement, platform and
> responsibility proposals in `mdmhub.md` where they conflict. In particular, the default
> is no separate `<client>-mdm-hub` repo and no Directus-specific projection. The existing
> dataplatform repo owns the MDM runtime.

## 1. Purpose

This document defines a consistent architecture for adding Master Data Management
(MDM) to the Kairos ecosystem without turning the ontology hub into an operational
application or turning the analytical Warehouse into an OLTP system.

The design covers:

- analytical MDM for reporting in Phase 1;
- operational mastering and reference-data governance in Phase 2;
- the boundary between the ontology hub and dataplatform repositories;
- durable identity, golden-record and reference-data state;
- governance workflows for new records, conflicts, merges and reference-data changes;
- APIs, events, security, audit, operations and analytical publication.

It deliberately does not select a stewardship UI or entity-resolution product. Those
are replaceable runtime choices owned by the dataplatform.

## 2. Decisions

1. **The ontology hub is the semantic contract producer.** It defines mastered concepts,
   identifiers, validation constraints, source mappings and stable governance intent.
2. **The dataplatform repo is the runtime owner.** It deploys the MDM database, migration
   pipeline, services, workflows, integrations, stewardship UI and monitoring.
3. **The Fabric Warehouse is the analytical serving layer, not the Phase-2 golden-record
   store.** It receives a read-only published replica of approved MDM data.
4. **Phase-2 golden records require an operational SQL store.** Fabric SQL Database,
   Azure SQL or PostgreSQL are candidates. Fabric Warehouse is not the default OLTP store.
5. **MDM state is durable and non-regenerable.** Enterprise IDs, crosswalk links,
   stewardship decisions, merge history, audit records and reference-data values are
   never recreated by projection.
6. **Generated artifacts are replaceable; runtime data is not.** The ontology hub may
   generate contracts and migration proposals, but it never creates, resets or owns live
   MDM data.
7. **The stewardship UI is replaceable.** React/Refine, Power Apps, Appsmith, Directus or
   another client may consume the same versioned MDM API. No UI product is part of the
   core architecture.
8. **Phase 1 and Phase 2 use different MDM styles.**
   - Phase 1: registry/consolidation MDM for analytical identity.
   - Phase 2: coexistence or centralized operational MDM, chosen per mastered domain.
9. **The design does not introduce a general-purpose Operational Data Store (ODS).**
   Bronze remains the source-aligned history. The MDM operational store contains only
   governed identity, golden-record, reference-data and workflow state.
10. **The existing dataplatform repo is the default deployment boundary.** A separate MDM
    repo is justified only if a different owner, regulatory boundary or release authority
    requires it.

## 3. Terminology

| Term | Meaning in this design |
|---|---|
| **Master data** | Governed business entities such as Party, Location or Vessel |
| **Reference data** | Controlled code lists such as UN/LOCODE, currency or Incoterms |
| **Source of Entry (SoE)** | The application where a user first enters or changes data |
| **System of Record (SoR)** | The authoritative source for a defined entity or attribute |
| **Enterprise ID** | Durable MDM identifier for one real-world entity, such as `MDM_PARTY_ID` |
| **Crosswalk** | Versioned links between an enterprise ID and source-system records |
| **Golden record** | Approved current representation of a mastered entity, with provenance |
| **Registry MDM** | Identity linking without operational authoring or source write-back |
| **Coexistence MDM** | Hub and source applications share controlled authoring responsibilities |
| **Centralized MDM** | Hub is the sole authoring authority for selected data |
| **Stewardship case** | Governed work item requiring investigation, decision or approval |
| **Published replica** | Read-only MDM data copied into the Warehouse for analytics |

An SoR decision must be explicit at **attribute level** where responsibility differs.
For example, the legal name may be authoritative from a company registry while a local
display name remains authoritative in a TMS.

## 4. Scope by phase

### 4.1 Phase 1 - analytical MDM

Phase 1 supports reporting only:

- consolidate in-scope Party records across selected source systems;
- allocate and persist `MDM_PARTY_ID`;
- maintain the source-record crosswalk;
- expose only the minimal reporting attributes;
- route missing or conflicting identifiers to a stewardship queue;
- publish the crosswalk and reporting dimension into the Warehouse;
- require corrections to be made in the source system;
- perform no operational write-back from MDM.

Phase 1 does **not** create a full golden record, change operational SoR ownership,
manage Party Groups, or become an onboarding/KYC application.

The Phase-1 identity registry is implemented in a protected `mdm_registry` Warehouse
schema. It is **not owned by dbt**:

- one serialized identity-allocation pipeline is the only writer;
- the pipeline generates an enterprise ID once and performs an idempotent merge keyed by
  identifier type, issuer/country and normalized identifier;
- registry and crosswalk tables are append-only apart from explicit lifecycle/status
  transitions;
- dbt identities have read access through published views and no DDL or write permission
  on `mdm_registry`;
- full refresh is limited to rebuildable silver/gold schemas and cannot address the
  registry schema;
- merge and crosswalk history is retained and included in backup/recovery procedures.

This is appropriate only for Phase 1's serialized batch workload. Before concurrent
operational authoring begins, the registry is migrated without reminting IDs into the
Phase-2 operational SQL store. If Phase 2 is already funded, that SQL store may be
deployed earlier to avoid the migration.

### 4.2 Phase 2 - operational MDM

Phase 2 adds:

- full golden records for selected mastered domains;
- governed create, edit, deactivate, merge, split and unmerge operations;
- attribute-level survivorship and ownership;
- reference-data authoring, versioning and publication;
- maker/checker approval;
- operational APIs and events;
- controlled sync-back where a source supports it;
- reconciliation, retry and compensation;
- data-quality scorecards and stewardship SLAs.

Phase 2 is adopted independently per domain. Party may use coexistence MDM while an
externally governed reference list remains registry/publish-only.

## 5. Architecture

```text
                         DESIGN TIME

  +---------------------------+       released contracts
  | Ontology hub              |-------------------------------+
  |                           |                               |
  | domain ontology           |                               v
  | SHACL constraints         |                 +---------------------------+
  | source vocabularies       |                 | Dataplatform repo         |
  | source-domain mappings    |                 |                           |
  | stable MDM annotations    |                 | consumes pinned release   |
  +---------------------------+                 | owns infra and deployment |
                                                +-------------+-------------+
                                                              |
                         RUNTIME                              |
                                                              v
  +------------------+      +------------------+     +----------------------+
  | Source systems   |----->| Ingestion/bronze |---->| MDM runtime          |
  | TMS, CRM, ERP    |      | source-aligned   |     |                      |
  +------------------+      +------------------+     | identity resolution  |
          ^                                           | golden/reference DB  |
          | approved sync-back                        | workflow and audit   |
          +-------------------------------------------| versioned API/events |
                                                      +----+-------------+---+
                                                           |             |
                                              stewardship  |             | approved publication
                                                           v             v
                                                    +-----------+  +------------------+
                                                    | UI client |  | Fabric Warehouse |
                                                    | replaceable|  | read-only replica|
                                                    +-----------+  +------------------+
```

### 5.1 Runtime data path

```text
Source ingestion
  -> source-aligned bronze
  -> canonical normalization
  -> identity resolution and candidate matching
  -> governance decision
  -> durable crosswalk and golden/reference state
  -> versioned API and events
  -> analytical Warehouse replica
```

Bronze preserves source granularity. It is not the golden record. Silver provides
canonical analytical representations. The MDM store holds governed operational state.
Gold remains optimized for BI.

### 5.2 Normalization boundary

Identity resolution and analytical transformation must use equivalent normalization
semantics for identifiers such as VAT, KBO/BCE, LEI and EORI.

The ontology hub defines the normalization and validation **contract**. The dataplatform
implements it:

- in dbt for batch analytical processing; and
- in the operational ingestion service when Phase 2 requires low-latency processing.

Both implementations must pass the same conformance examples. MDM does not consume a
gold table and does not duplicate an independently invented set of cleansing rules.

## 6. Repository responsibilities

### 6.1 Ontology hub

The ontology hub owns:

- domain classes, properties and relationships;
- the distinction between master and reference concepts;
- identifier semantics and issuer/country context;
- SHACL validation constraints;
- source vocabularies and source-to-domain mappings;
- stable intent such as mastered entity, match-capable identifier and ownership hint;
- versioned MDM contracts generated from the model;
- contract compatibility checks and test examples.

The released MDM contract is a third ontology-hub deliverable alongside the dbt package
and Power BI package. It contains product-neutral schemas, validation rules,
normalization examples, role/scope semantics and API/event schemas. The dataplatform pins
an immutable contract release under `contracts/mdm/`.

The ontology hub does **not** own:

- enterprise ID values or source links;
- golden-record or reference-data values;
- stewardship cases and decisions;
- workflow routing, SLA or escalation configuration;
- UI layouts tied to a particular product;
- infrastructure, secrets, SSO or runtime RBAC assignments;
- matching thresholds tuned from production data;
- source connectors, retries or sync-back;
- operational audit logs or runtime monitoring.

Provider names, endpoints, workflow steps and product-specific configuration must not
become ontology annotations. Runtime configuration may reference ontology IRIs.

The projector may emit an abstract role and permission contract referencing ontology
IRIs. A dataplatform adapter translates that contract for the selected UI and identity
platform. The projector must not emit Directus, Power Apps or other product-specific
configuration.

### 6.2 Dataplatform repo

The dataplatform repo owns:

- consumption of a pinned ontology-hub contract release;
- operational database infrastructure and migrations;
- identity-allocation and mastering services;
- reference-data services;
- case workflow and approval orchestration;
- a versioned domain API and event contracts;
- the selected stewardship UI adapter;
- source ingestion and sync-back connectors;
- Warehouse publication models;
- Entra integration and runtime role assignments;
- secrets, observability, backup, restore, DR and incident response;
- production tuning and operational support.

Projections still run only in the ontology hub. The dataplatform consumes released
artifacts and never requires the Kairos toolkit at runtime.

### 6.3 Data-governance organisation

Technology cannot assign business accountability. The governance organisation owns:

- data-domain ownership;
- authoritative-source decisions;
- data-quality policy and thresholds;
- steward and approver assignments;
- merge/split policy;
- retention and privacy policy;
- approval of destructive schema or policy changes;
- periodic review of rules and access.

### 6.4 Source applications

Source applications:

- remain the SoE unless a domain explicitly moves to centralized MDM;
- expose stable source keys and change events or extracts;
- accept approved changes only through supported integration contracts;
- return acknowledgements or rejection reasons;
- preserve local fields that are outside MDM ownership.

## 7. Dataplatform repository layout

The MDM runtime can be added to the existing dataplatform repo without mixing its
deployment lifecycle with dbt:

```text
dataplatform/
|-- packages.yml                    # pinned ontology-hub dbt package
|-- contracts/
|   `-- mdm/                        # pinned released MDM contract
|-- dbt/
|   `-- models/
|       `-- mdm_publish/            # analytical replica/read models
|-- infra/
|   `-- mdm/                        # SQL DB, identity, network, secrets
|-- migrations/
|   `-- mdm/                        # reviewed forward migrations
|-- services/
|   |-- mdm-api/                    # stable domain API
|   |-- mastering/                  # match, link, merge, survivorship
|   `-- reference-data/             # author and publish code lists
|-- apps/
|   `-- stewardship/                # replaceable UI implementation
|-- integration/
|   |-- inbound/                    # source change handling
|   `-- outbound/                   # events and controlled sync-back
`-- .github/workflows/
    |-- deploy-mdm-infra.yml
    |-- migrate-mdm.yml
    |-- deploy-mdm-services.yml
    `-- publish-mdm-warehouse.yml
```

This existing dataplatform repository is the default because the same platform team owns
analytics, integration and MDM operations. MDM still has independent pipelines,
approvals, database credentials, release gates and rollback procedures. A separate repo
is an exception requiring a different owner, regulatory boundary or release authority;
it is not the default scaffold.

## 8. Runtime components and non-overlapping functions

| Component | Sole responsibility | Explicitly not responsible for |
|---|---|---|
| Ingestion/bronze | Preserve source records and arrival metadata | Golden-record decisions |
| Normalization | Canonicalize and validate identifiers/values | Linking or survivorship |
| Identity resolution | Find candidate duplicates and propose links | Approving ambiguous decisions |
| Mastering service | Apply approved links, merges and survivorship | UI workflow or BI modeling |
| Reference-data service | Govern lists, values, mappings and releases | Master-entity matching |
| Workflow service | Cases, assignment, approval, SLA and escalation | Deciding match algorithms |
| MDM operational store | Durable approved state and history | Analytical star schemas |
| MDM API/events | Stable consumer contracts | Exposing physical tables |
| Stewardship UI | Human interaction through APIs | Direct database ownership |
| Publication adapter | Write approved versions to the outbox/landing contract | Write directly into analytical models |
| dbt/gold | Analytical dimensions and facts | Allocate enterprise identity |

This separation prevents a UI product, dbt model or matching engine from silently
becoming the authoritative MDM system.

## 9. Logical data model

The physical schema may vary, but the runtime must support these logical records.

### 9.1 Master-data records

| Record | Required content |
|---|---|
| Enterprise entity | Durable enterprise ID, entity type, lifecycle state, version |
| Source-record link | Source system, source entity type, source key, valid period, link status |
| Identifier | Type, issuer/country, normalized value, validation status, valid period |
| Golden attribute | Value, source provenance, effective period, decision/rule version |
| Match candidate | Candidate entities, score, rule version, explanation |
| Merge lineage | Survivor, predecessor, reason, decision and effective period |
| Stewardship decision | Actor, role, action, reason, before/after values, timestamp |
| Publication event | Entity version, event ID, consumers and delivery state |

Enterprise IDs are append-only and never reused. Source links are temporally versioned.
A merge tombstones the losing identity and points it to the survivor. Split and unmerge
retain provenance and never rewrite history.

### 9.2 Reference-data records

| Record | Required content |
|---|---|
| Reference list | Stable list ID, owner, authority, lifecycle and version policy |
| Reference value | Code, labels, effective dates, status and provenance |
| Source mapping | External/source code to governed code, valid period |
| Replacement relation | Deprecated code, replacement code and transition date |
| Release | Version, approval, publication date and compatibility classification |
| Consumer delivery | Consumer, release, delivery/acknowledgement state |

Reference values are deprecated rather than deleted after publication.

### 9.3 Cases and audit

Both master and reference workflows use a shared governance-case capability:

- case type and affected entity/list;
- severity, priority and risk;
- assignee, role and governance scope;
- status, SLA and escalation;
- evidence and comments;
- proposed and approved actions;
- immutable decision history.

The shared case mechanism avoids duplicating workflow infrastructure while preserving
domain-specific decision rules.

## 10. Master-data governance flows

### 10.1 New client creation

```text
Create request
  -> search before create
  -> normalize and validate identifiers
  -> candidate matching
  -> automatic link, stewardship case or proposed creation
  -> maker/checker approval
  -> enterprise ID allocation
  -> source crosswalk
  -> approved publication
  -> reconciliation
```

1. An onboarding process or source application submits a proposed client with a stable
   request ID.
2. The MDM API performs search-before-create across identifiers, names and addresses.
3. Registration identifiers are normalized and validated in issuer/country context.
4. The identity resolver returns:
   - an exact, policy-safe match;
   - probable candidates requiring review; or
   - no credible candidate.
5. Exact matches may be linked automatically only when policy permits and no conflicting
   authoritative identifier exists.
6. Probable matches create a stewardship case with side-by-side values, provenance,
   confidence and rule explanation.
7. A no-match request becomes a proposed enterprise entity. An approver distinct from the
   maker activates it where risk policy requires four-eyes approval.
8. The identity service allocates the enterprise ID once and creates the source link.
9. The outbox publishes the approved version to operational consumers and the Warehouse.
10. Delivery acknowledgement and reconciliation close the request.

MDM supplies governed identity and party data to onboarding/KYC. It does not own the
end-to-end onboarding, credit, sanctions or KYC business process.

### 10.2 Conflicting client attributes

```text
Source change
  -> preserve raw value and provenance
  -> normalize and resolve identity
  -> detect attribute conflict
  -> evaluate authority/survivorship
  -> auto-resolve or create case
  -> steward decision and approval
  -> new golden-record version
  -> publish, sync and reconcile
```

1. A source change is retained unchanged in bronze.
2. The source record resolves through the crosswalk to an enterprise entity.
3. The mastering service compares the incoming attribute with the current golden value.
4. Attribute-level authority and survivorship rules are evaluated.
5. A deterministic low-risk rule may resolve the value automatically. Every automatic
   decision records the rule version and evidence.
6. Ambiguous, high-risk or authoritative-source conflicts create a stewardship case.
7. The steward sees values, provenance, timestamps, validation results, downstream impact
   and the proposed action.
8. The steward accepts, rejects or overrides the proposal and supplies a reason.
9. A separate approver is required for high-impact attributes or policy exceptions.
10. The system creates a new golden-record version; it does not overwrite history.
11. An event publishes the approved version. A future sync-back integration may consume
    it after the dedicated integration design is approved.
12. Consumer and source acknowledgements are reconciled. Rejections remain visible cases.

### 10.3 Duplicate merge

1. Identity resolution proposes a duplicate cluster and explains the evidence.
2. A steward reviews identifiers, source links, relationships and downstream impact.
3. Conflicting authoritative identifiers block automatic merge.
4. Approval selects the surviving enterprise ID and attribute-level survivors.
5. The losing ID is tombstoned and linked to the survivor.
6. Crosswalk history remains queryable for historical facts.
7. A merge event includes both IDs, effective time and golden-record version.
8. Unmerge remains possible through a new governed decision; history is never erased.

### 10.4 Missing or invalid identifier

1. Validation creates a case rather than inventing or guessing an identifier.
2. In Phase 1, the assigned user corrects the value in the SoE.
3. The corrected record returns through normal ingestion and closes the case after match.
4. In Phase 2, the governance policy may permit a stewarded provisional entity, clearly
   marked and excluded from selected downstream processes.

## 11. Reference-data governance flow

```text
Proposal or authority import
  -> structural and semantic validation
  -> mapping and impact analysis
  -> steward review
  -> maker/checker approval
  -> scheduled versioned release
  -> API/event publication
  -> consumer acknowledgement
  -> monitoring and eventual deprecation
```

1. A steward proposes a value or imports a release from the external authority.
2. Validation checks code uniqueness, required labels, formats, dates and authority.
3. Impact analysis identifies affected source mappings, master records, integrations,
   reports and consumers.
4. The steward supplies mappings from source-local codes to the governed code.
5. An independent owner approves the change and its effective date.
6. The service creates an immutable release version and schedules publication.
7. APIs and events publish the release; the Warehouse receives the analytical copy.
8. Registered consumers acknowledge delivery. Reconciliation identifies lagging versions.
9. Obsolete values are deprecated with replacement guidance and a transition period.
10. Emergency changes follow an expedited but still audited approval path.

Reference-data releases classify compatibility:

- **additive** - new value, normally backward compatible;
- **deprecating** - old value remains valid during transition;
- **breaking** - meaning or key changes and requires explicit consumer migration.

## 12. Workflow states

### 12.1 Governance case

```text
open -> triaged -> assigned -> proposed -> awaiting_approval
     -> approved -> applied -> published -> reconciled -> closed
```

Alternative terminal states are `rejected`, `cancelled` and `superseded`. Failed
application or publication returns the case to an actionable state; it is not reported
as successfully closed.

### 12.2 Master entity

```text
proposed -> active -> deactivated
                   -> merged
```

Split and unmerge are governed actions that create new versions and lineage. They do not
delete prior states.

### 12.3 Reference value

```text
draft -> approved -> scheduled -> active -> deprecated -> retired
```

`retired` means unavailable for new use but still resolvable historically.

## 13. Security and RBAC

Existing Entra groups and governance roles should be reused where appropriate, but MDM
permissions must be independent from Warehouse grants.

| Role | Typical permissions |
|---|---|
| Requester | Submit create/change requests and view their status |
| Data steward | Investigate cases and propose decisions within assigned scope |
| Data owner/approver | Approve high-impact or policy-controlled decisions |
| MDM system writer | Apply approved service commands; no interactive login |
| Integration publisher | Publish approved versions; cannot alter golden state |
| Operational reader | Read approved domain API views |
| Analytical publisher | Read approved publication views for Warehouse replication |
| Auditor | Read decisions, provenance and audit history; no modification |
| Platform operator | Operate infrastructure without business approval authority |

Required controls:

- least privilege and deny-by-default;
- global/local and domain-specific scope;
- field-level restrictions for sensitive attributes;
- maker/checker separation for controlled actions;
- service identities separated from human identities;
- encryption in transit and at rest;
- secrets in the platform secret store;
- access review and role recertification;
- immutable audit export with defined retention;
- privacy classification, masking and deletion/restriction procedures.

Warehouse RLS may mirror approved business scopes for analytics, but it is generated and
enforced separately from operational write permissions.

## 14. API and event contracts

Consumers never use raw operational tables or a generic database API.

The MDM service exposes versioned domain contracts such as:

- resolve source key to enterprise ID;
- search for existing entities;
- submit a create/change request;
- retrieve approved current and historical versions;
- retrieve reference-list releases;
- inspect request or publication status.

Commands require an idempotency key. Responses expose stable domain fields rather than
physical schema details.

Events use an outbox and include:

- event ID and schema version;
- aggregate ID and aggregate version;
- event type and effective time;
- causation and correlation IDs;
- origin system;
- decision/rule version where relevant;
- payload or a stable retrieval link.

Consumers must handle duplicate delivery.

Sync-back remains a **Phase-2 conceptual contract, not an implemented design**. A
dedicated integration architecture must define target acknowledgement, rejection
reasons, idempotency, retry policy, dead-letter handling, replay, compensation,
field-ownership conflicts and legal accountability. `originSystem` alone is not
sufficient loop prevention.

## 15. Persistence and migrations

The operational store is changed only through reviewed, forward migrations.

Migration policy:

- create/additive changes are automated after compatibility checks;
- backfills are explicit, restartable and observable;
- destructive changes require data-owner and platform approval;
- enterprise IDs, crosswalks, decisions, audit and published reference values are never
  dropped or regenerated;
- schema drift is detected before deployment;
- deployment ordering separates schema, backfill, service and publication changes;
- rollback normally means a forward corrective migration;
- production data is backed up and restore is tested.

The ontology hub may generate a migration **proposal** from a contract change. The
dataplatform owns review, adaptation and execution because it owns live state.

## 16. Warehouse publication

Only approved MDM state is published to the Warehouse.

In Phase 2, the publication mechanism is:

```text
MDM transaction
  -> transactional outbox
  -> dataplatform ingestion
  -> append-only MDM bronze events
  -> idempotent dbt current/history models
  -> gold dimensions and semantic models
```

The outbox and aggregate version prevent a database commit from being separated from
its publication intent. Ingestion is at-least-once; dbt models deduplicate by event ID
and apply aggregate versions in order. The `mdm_publish/` models are custom
dataplatform-owned models that consume the product-neutral MDM event contract.

In Phase 1 the protected registry already resides in the Warehouse. dbt reads its
published views but cannot modify its tables.

Recommended analytical schemas:

```text
mdm_current.party
mdm_current.party_crosswalk
mdm_current.reference_value
mdm_history.party_version
mdm_history.crosswalk_version
mdm_history.reference_release
mdm_quality.case_metrics
mdm_quality.publication_reconciliation
```

Publication is incremental and keyed by aggregate version or event sequence. dbt may
transform the published replica into dimensions, but it does not allocate enterprise IDs
or alter operational history.

Historical facts remain resolvable to the enterprise ID and crosswalk version valid when
the fact was loaded. Current-state rollups may follow merge lineage to the surviving ID.
These are separate analytical views.

## 17. Data quality and observability

Responsibilities are deliberately separated:

| Quality concern | Owner |
|---|---|
| File/schema ingestion validity | Dataplatform ingestion |
| Source-to-domain mapping validity | Ontology hub contract and dataplatform implementation |
| Identifier format and semantic constraints | Shared contract, enforced by MDM runtime |
| Match precision/recall and conflict rate | Mastering service and data governance |
| Golden-record completeness/freshness | MDM runtime |
| BI model tests | dbt/gold |
| Source correction | Source owner through a stewardship case |

Operational monitoring includes:

- ingestion lag and failed records;
- match rates, ambiguous candidates and false-merge corrections;
- open cases, SLA breaches and escalations;
- API availability and latency;
- event backlog, retries and dead letters;
- sync-back acceptance/rejection;
- Warehouse publication lag and reconciliation;
- database capacity, backup and restore status;
- rule, contract and consumer versions in use.

Service-level objectives, RPO and RTO must be agreed before Phase 2 production use.

## 18. UI strategy

The stewardship UI is a client of the MDM API and workflow service.

Minimum capabilities:

- search-before-create;
- side-by-side comparison with provenance;
- match explanation and confidence;
- create, change, merge, split and unmerge proposals;
- reference-list editing and release preparation;
- assignment, SLA and escalation;
- maker/checker approval;
- impact preview;
- audit and decision history;
- accessibility and localization.

Candidate implementation approaches include:

- custom React using Refine or react-admin;
- Power Apps over the versioned API;
- an internal-tool platform such as Appsmith;
- a data platform such as Directus, subject to license and fit review.

No candidate may bypass the domain API to become the de facto owner of MDM state.
Direct database administration interfaces are limited to platform operations.

## 19. Functional coverage

| Capability | Phase 1 | Phase 2 | Design owner |
|---|:---:|:---:|---|
| Durable enterprise identity | Yes | Yes | MDM runtime |
| Source crosswalk and history | Yes | Yes | MDM runtime |
| Exact validated matching | Yes | Yes | Identity resolution |
| Probabilistic matching | No | Optional | Identity resolution |
| Search-before-create | Limited | Yes | MDM API |
| Exception/case queue | Yes | Yes | Workflow service |
| Golden-record authoring | No | Yes | Mastering service |
| Attribute survivorship | No | Yes | Mastering service |
| Merge/split/unmerge | No | Yes | Mastering + workflow |
| Maker/checker approval | For manual ID decisions | Yes | Workflow service |
| Reference-list harmonization | Read/publish | Yes | Reference-data service |
| Effective dating and releases | Limited | Yes | Reference-data service |
| Source-code mappings | Yes | Yes | Reference-data service |
| Consumer impact analysis | Limited | Yes | Reference-data service |
| Operational API/events | No | Yes | MDM API |
| Source sync-back | No | Optional | Integration |
| Warehouse publication | Yes | Yes | Dataplatform/dbt |
| RBAC and immutable audit | Yes | Yes | Platform + governance |
| KYC/onboarding process | External | External | Business application |
| BI semantic modeling | Yes | Yes | Gold/Power BI |

## 20. Delivery sequence

### 20.1 Phase 1

1. Confirm Party scope, source systems and reporting attributes.
2. Approve the enterprise identity and crosswalk history contract.
3. Define country-aware identifier normalization and conformance examples.
4. Create the protected `mdm_registry` Warehouse schema and deny dbt write/DDL access.
5. Implement the serialized, idempotent identity-allocation pipeline.
6. Implement exact-match policy and missing/conflicting-identifier cases.
7. Publish read-only crosswalk views and the reporting dimension.
8. Prove that dbt full refresh cannot alter IDs or crosswalk history.
9. Measure match quality and operational effort before expanding scope.

### 20.2 Phase-2 readiness gate

Do not begin operational MDM until all are agreed:

- mastered domains and MDM style per domain;
- attribute-level ownership and authoritative sources;
- governance roles and staffed stewardship operating model;
- golden-record operational store;
- API and event service levels;
- merge, split and unmerge policy;
- sync-back ownership and failure handling;
- privacy, retention and audit policy;
- RPO, RTO, backup, DR and support ownership.

### 20.3 Phase 2

1. Deploy the operational store and migrate Phase-1 identities without reminting.
2. Introduce the versioned MDM API, outbox and workflow service.
3. Add golden attributes one domain slice at a time.
4. Add the stewardship UI against the API.
5. Add reference-data releases and consumer reconciliation.
6. Add source sync-back only after read-only publication is stable.
7. Add probabilistic matching only when measured cases justify it.

## 21. Acceptance criteria

The architecture is ready for implementation when:

- repository and runtime ownership is approved;
- every durable asset has one owner;
- no generated process can recreate enterprise IDs or stewarded state;
- Phase 1 can survive a dbt full refresh without changing identities;
- the normalization contract has shared conformance examples;
- every governance decision records actor, reason, evidence and before/after state;
- APIs and events hide physical tables and are independently versioned;
- Warehouse consumers are read-only;
- reference releases support impact, approval, effective dates and deprecation;
- merge/split history keeps historical facts resolvable;
- RBAC enforces domain scope and maker/checker separation;
- publication and sync-back have reconciliation and failure handling;
- backup/restore and operational ownership are proven;
- the selected UI can be replaced without migrating MDM state.

## 22. Remaining decisions

1. Is Phase 2 committed strongly enough to deploy the operational identity store early,
   instead of migrating the protected Phase-1 Warehouse registry later?
2. Which operational SQL platform best fits the selected Fabric environment?
3. Which domains besides Party and which reference lists are in scope?
4. Which attributes become authoritative in MDM, and which remain local to each SoE?
5. Which actions require maker/checker approval?
6. What latency, availability, RPO and RTO are required?
7. Which UI approach should be prototyped against the stable API?
8. Which source systems can support safe, acknowledged and reversible sync-back?

---

This design keeps Kairos shift-left: semantics and contracts are model-driven, while
durable business state and operational responsibility remain in the dataplatform where
they can be secured, migrated, monitored and governed.
