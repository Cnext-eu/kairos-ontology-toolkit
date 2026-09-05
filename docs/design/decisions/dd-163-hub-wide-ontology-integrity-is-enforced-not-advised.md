# DD-163: Hub-wide ontology integrity is enforced, not advised

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `validate`, kairos-design-domain Gate 3, kairos-design-mapping
**Implementation:** `core/ontology_integrity.py`, wired into `core/validator.py:run_validation`

### Context

Every ontology check the toolkit had was single-file by construction.
`validate_naming_conventions` parses one `.ttl` with no import resolution — deliberately, and
its docstring says so — and `validate_managed_imports` compares one domain's declared imports
against the blueprint. Neither can observe a relationship *between* two domain files.

A 21-domain autopilot run exposed the consequence. Of 132 locally declared classes, 34 were
re-mints of the same eight concepts across domains: `Consignment` and `Booking` in eight domains
each, `Document` and `Company` in seven, `Contact` and `Comment` in four. Each domain has its own
namespace, so these are unrelated OWL entities that merely share a name, with no
`owl:equivalentClass` between them. `validate` passed the hub cleanly. The defect surfaced two
stages later as a dbt parse failure — the projector derives a model filename from the class local
name, so `party#Company` and `mdm#Company` both emitted `company.sql`.

Nine of those files stated the violation in their own headers. `party.ttl` lists under
`Deliberate exclusions`: *"Party bookings: owned by the booking domain"*, then declares
`:Booking`. The accelerator blueprint agrees — `party.does_not_own` reads *"Contracts, bookings,
invoices, operational events, or terminal moves."* That prose was already a contract field
(`analyse_sources` feeds it to the source-affinity classifier, so its wording is behavioural),
but nothing read it after classification. kairos-design-domain Gate 3 conceded the point in
writing: *"the blueprint's owns/does_not_own boundaries are free text no validator can enforce."*

The affinity analysis was not the cause. Every leaked concept had been assigned to exactly one
domain, and the correct one — `Booking` to booking, `Comment` to claims. The evidence entering
design was clean; the design stage did not honour it.

### Decision

Add a hub-wide integrity pass to `validate`, blocking by default and degradable with
`--degraded`. Three checks are errors:

- `integrity.class-redeclared-across-domains` — purely mechanical, no interpretation, and
  already a build failure downstream;
- `integrity.class-violates-declared-exclusion` — the file's own header contradicts the file;
- `integrity.class-outside-blueprint-boundary` — the blueprint's `does_not_own` names the concept.

Four more are advisory: reference-model shadowing (class and property), unused `owl:imports`,
and collapsed address value objects.

**Precision is chosen over recall.** A false positive on a blocking check teaches an operator to
pass `--degraded`, which would cost more than the check earns. So each blocking check reads
either a machine-readable fact or the hub's own written-down intent. Notably, a bullet naming
*this* domain as owner ("Contact details: owned by the party domain") is a clarification, not an
exclusion, and must not flag `:Contact`; and the domain's own name inside a subject phrase
("Party bookings") must flag `Booking` without flagging `Party`. Both are regression-tested.

Fuzzy inference — "does this class feel like it belongs here" — is deliberately absent. Anchoring
ratios are reported as scores rather than enforced, because a hub legitimately declares local
classes the reference model does not carry.

### Alternatives rejected

| Alternative | Why not |
|---|---|
| Ship as warnings first | `kairos-flow-autopilot` states "warnings are acceptable but must be explained". A warning would have been explained and ignored in exactly the run that produced this. |
| Put the rule in the skill | Skills are prose an agent may skip under context pressure, and this rule was *already* in prose — in the exemplar, in Gate 3, and in nine file headers — and was violated anyway. |
| Enforce via SHACL | Cross-file identity comparison across namespaces is not what SHACL shapes are for, and the hub's shapes are hand-authored governance, not toolkit-owned. |
| Reuse `load_ontology()` | It merges the import closure, erasing the locally-declared vs imported distinction every check depends on. Registered in both TTL-boundary tests with that reasoning. |

### Consequences

Existing non-conforming hubs fail `validate` until fixed or run with `--degraded`. That is the
intent: the CLdN hub moves from passing to 63 blocking errors, all of which were already real.
