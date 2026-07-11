# MDM User Stories

Product backlog for the Kairos MDM capability, organized by principal role. Migrated
from `docs/design/mdmhubdesignv2.md` §18.

**Ownership legend** — each epic is tagged with where its stories are *implemented*:

- 🟦 **Design-time (this repo, `kairos-ontology-toolkit`)** — expressed as `*-mdm-ext.ttl`
  policy, the `mdm-profile` projection, validation, and the `kairos-design-mdm` skill.
- 🟧 **Runtime (`kairos-mdm-runtime`)** — matching, stewardship UI, operational DB, APIs,
  events, RBAC enforcement, privacy operations.
- 🟩 **Dataplatform (consumer dbt repo)** — deployment binding, warehouse publication.

Design-time and runtime meet at one artifact: the **immutable, content-addressed MDM
profile** (`output/mdm/{domain}-mdm-profile.json`, MDM-DD-003). Design-time authors it;
runtime and dataplatform consume the pinned digest.

---

## MDM-DESIGN — Define mastered concepts and policy 🟦 *(design-time, this repo)*

Role: MDM designer / data governance. Delivered via `kairos-design-mdm` +
`project --target mdm-profile`.

| ID | User story |
|---|---|
| DESIGN-01 | Designate ontology classes as master- or reference-data so MDM scope is explicit and machine-readable. |
| DESIGN-02 | Identify enterprise identifiers, match attributes and normalization rules so the runtime resolves records consistently. |
| DESIGN-03 | Define attribute-level authority and survivorship so golden values follow approved business rules. |
| DESIGN-04 | Define auto-action boundaries, maker/checker and abstract workflow so ambiguous/high-risk decisions require governance. |
| DESIGN-05 | Define reference-data ownership, release and deprecation so lists follow a consistent lifecycle. |
| DESIGN-06 | Define DQ rules and scorecard thresholds so quality is governed policy, not ad-hoc monitoring. |
| DESIGN-07 | Validate MDM extensions (`mdm-validate`) and see semantic + runtime impact before a PR so invalid/breaking policy never reaches production. |
| DESIGN-08 | Have approved extensions projected into an immutable profile so every runtime decision traces to reviewed design. |
| DESIGN-09 | Consume a runtime **evidence pack** to propose a reviewed threshold/survivorship change so tuning stays governed. |

> DESIGN-01..08 are implemented here today. DESIGN-09 closes the loop: the **evidence
> pack is produced by runtime** (🟧) and *consumed* here to author the next reviewed change.

---

## MDM-DEPLOY — Deploy and operate an instance 🟧🟩 *(runtime + dataplatform)*

Role: dataplatform engineer. **Out of scope for this repo** except that DEPLOY-01 pins the
design-time profile digest.

| ID | User story |
|---|---|
| DEPLOY-01 | Pin compatible ontology-hub and runtime releases so deployments are reproducible and independently upgradeable. |
| DEPLOY-02 | Provision the supported operational DB from runtime modules so durable state is isolated from dbt schemas. |
| DEPLOY-03 | Apply reviewed forward migrations with drift checks + restartable backfills preserving IDs/crosswalks/audit. |
| DEPLOY-04 | Configure technical bindings (identities, endpoints, secrets, connectors, notifications) without duplicating policy. |
| DEPLOY-05 | Deploy profile, API, services and Stewardship UI as versioned components promoted and rolled forward safely. |
| DEPLOY-06 | Publish and reconcile approved MDM events with the Warehouse so analytics receive trusted current + historical data. |
| DEPLOY-07 | Monitor health, audit, backlog, backup and restore so the instance meets its operational objectives. |

---

## MDM-STEWARD — Govern master and reference data 🟧 *(runtime)*

Role: data steward / system-of-engagement user. Implemented by the runtime Stewardship UI
and services; the **policy** the steward operates within (survivorship, workflow, auto-action
bounds) is authored design-time (DESIGN-03/04).

| ID | User story |
|---|---|
| STEWARD-01 | Search before creating master data so an existing entity is reused instead of duplicated. |
| STEWARD-02 | Submit a proposed record when no credible match exists so creation follows validation + approval. |
| STEWARD-03 | Compare candidates with identifiers, provenance, confidence and rule explanations for evidence-based decisions. |
| STEWARD-04 | Review conflicting values and proposed survivorship to accept/reject/override with a recorded reason. |
| STEWARD-05 | Propose merge/split/unmerge and maintain entity relationships/hierarchies with impact visibility, without erasing history. |
| STEWARD-06 | Create/maintain reference values, source mappings, effective dates and deprecations for approved releases. |
| STEWARD-07 | Have cases assigned, prioritized and escalated by policy so exceptions resolve within SLAs. |
| STEWARD-08 | See publication + source acknowledgements so failed corrections/sync-back stay actionable. |

---

## MDM-ACCESS — Govern steward access 🟦🟧 *(policy design-time, enforcement runtime)*

Role: MDM administrator. Abstract role/permission **policy** is design-time governance
(reviewed in the hub); **enforcement + identity binding** is runtime/dataplatform (ACCESS-07).

| ID | User story |
|---|---|
| ACCESS-01 | Define abstract steward/approver/requester/auditor/operator permissions reusable across environments. |
| ACCESS-02 | Scope permissions by domain, geography, organisation and action. |
| ACCESS-03 | Define maker/checker and separation-of-duty so an action can't be requested and approved by one person. |
| ACCESS-04 | Map approved identity groups to abstract roles per environment. |
| ACCESS-05 | Mask/restrict sensitive attributes by role, with masking recorded in the access-decision log. |
| ACCESS-06 | Review effective access, denied actions and role changes via the access-decision log for recertification. |
| ACCESS-07 | Have policy reviewed in the hub and identity bindings deployed via the dataplatform — no production-only RBAC source of truth. |

---

## MDM-CONSUME — Consume mastered data 🟧 *(runtime)*

Role: operational/analytical consumer.

| ID | User story |
|---|---|
| CONSUME-01 | Register as a consumer and obtain entitlement-approved, scoped access to golden records/reference releases. |
| CONSUME-02 | Resolve a source key to an enterprise ID via a stable versioned API. |
| CONSUME-03 | Subscribe to approved events and handle duplicates/ordering via aggregate version. |
| CONSUME-04 | Reconcile the reference/profile version I consume so lagging versions are detectable. |

---

## MDM-INTEGRATE — Source-system integration 🟧 *(runtime; partially gated)*

Role: source owner.

| ID | User story |
|---|---|
| INTEGRATE-01 | Expose stable source keys and change events/extracts so ingestion resolves identity reliably. |
| INTEGRATE-02 | Receive approved sync-back changes with acknowledgement/rejection reasons. **(Gated — see below.)** |
| INTEGRATE-03 | Preserve source-local fields outside MDM ownership so mastering doesn't overwrite them. |

> **Sync-back gating:** stories whose value depends on write-back to sources — INTEGRATE-02
> and the sync-back portion of STEWARD-08 — are **not implementable** until the v2 §14.2
> sync-back integration architecture (acknowledgement, rejection, idempotency, retry,
> dead-letter, replay, compensation, field-ownership conflict, loop prevention) is designed
> and approved. They are backlog-visible but scheduled behind that milestone (ADR-3). The
> publication/acknowledgement portion of STEWARD-08 does not depend on sync-back.

---

## MDM-AUDIT — Audit, privacy and compliance 🟧 *(runtime)*

Role: auditor / privacy officer.

| ID | User story |
|---|---|
| AUDIT-01 | Read immutable decision, provenance and access-decision history without modification. |
| AUDIT-02 | Raise and track subject-rights requests (access/rectify/erase/restrict) as governed cases. |
| AUDIT-03 | Have personal-attribute erasure applied by redaction/crypto-shred while retaining non-personal lineage + audit. |
| AUDIT-04 | Verify Warehouse replicas honor erasure so analytical copies can't resurrect erased values. |

---

## MDM-NFR — Non-functional guarantees 🟧🟩 *(runtime + platform)*

Role: platform + governance.

| ID | User story |
|---|---|
| NFR-01 | Agree and verify API latency/availability SLOs before Phase-2 production use. |
| NFR-02 | Agree RPO/RTO and prove backup/restore and DR via a tested drill. |
| NFR-03 | Prove Phase 1 survives a dbt full refresh without changing identities. |
| NFR-04 | Enforce the single normalization library via a shared conformance regression gate. |

---

## Handoff

```text
MDM designer/admin -> reviewed *-mdm-ext.ttl -> projected immutable profile (this repo)
   -> dataplatform engineer deployment -> steward/consumer/runtime decisions (runtime)
   -> evidence pack -> next reviewed hub change (back to this repo)
```
