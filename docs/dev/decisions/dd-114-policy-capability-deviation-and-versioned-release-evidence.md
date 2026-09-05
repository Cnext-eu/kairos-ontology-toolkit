# DD-114: Policy, Capability, Deviation, and Versioned Release Evidence

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
