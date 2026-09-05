# DD-167: Conformance judgment is offloaded, retrieval-grounded, and code-gated

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `discovery-conformance`, kairos-design-discovery
**Implementation:** `core/conformance_judge.py`, `discovery-conformance judge`

### Context

`discovery-conformance` could scaffold a judgments file and validate a finished one, but
nothing filled it in. For `unit-load-carrier` that is 174 concepts, so the orchestrating
agent judged them inline. The hub's own issue log recorded this as an open enhancement —
the pass belongs on the configured provider, not in the orchestrator's context.

The risk is specific. A wrong `conforms` silently certifies a concept the hub never models:
a real run scored the party domain "6 conforms / 0 deviates" while its ontology contained
none of the three classes it certified, and recorded *"the same companies carry customer,
subcontractor and consignee roles"* as proof a role-assignment entity existed — which is the
evidence that one is **needed**, not that one exists.

### Decision

`discovery-conformance judge` offloads the pass, batched (~15 calls for 174 concepts), under
a third AI role (`judgment`). It is retrieval-grounded: the model never recalls concepts or
emits URIs, receiving the archetype catalog plus collected evidence and choosing from a
closed outcome set.

Enforcement is in code, not in the prompt, because a prompt asks the thing being checked to
check itself. Four guards run over every response:

1. An unrecognised outcome becomes `partial`, never coerced to the nearest valid one.
2. `conforms` with no source evidence is downgraded.
3. `conforms` on **domain-level evidence only** is downgraded. Alignment evidence and an
   affinity `likely_entity` match name the concept; "16 tables in the party domain" does not.
   Without this guard the first live run reproduced the original error exactly.
4. A concept the pattern library flags (grain collision, anti-pattern exemption) **escalates**
   rather than downgrades. A grain collision governs how a concept is modelled, not whether
   the business has it; forcing `mmt:TransportParty` to `partial` would be wrong, but
   certifying it unreviewed is worse.

Evidence placement is derived from the blueprint: a concept's URI names its module and
`data-domains.yaml` maps modules to domains, breaking the circularity where evidence needed
the `likely_domains` that the judgment was meant to produce. Downstream BI demand is passed
as a distinct, labelled signal — it can corroborate, never certify.

Every judgment is `decided_by: ai`, so DD-148's gate still requires human resolution, and the
command cannot satisfy DD-149's archetype confirmation as a side effect.

### Consequences

On the live hub: `TransportPartyRoleAssignment` moved from conforms 0.91 to partial 0.58
flagged, `TransportPartyRoleCode` from 0.86 to 0.56, `TransportParty` from 0.95 to 0.61. The
ten surviving `conforms` are precisely the concepts a source table is identified as. 147 of
174 need human confirmation — high, and honest: most of this archetype is genuinely unproven
before mapping has run.
