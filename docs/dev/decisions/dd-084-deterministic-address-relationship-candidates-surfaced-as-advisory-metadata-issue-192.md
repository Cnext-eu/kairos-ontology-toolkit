# DD-084: Deterministic address relationship candidates surfaced as advisory metadata (issue #192)

> **Superseded in part by DD-188 (2026-08-17).** The detector described here survives, but its vocabulary no longer lives in the toolkit: the address part
> kinds, role qualifiers and weak/context rules now come from the accelerator pack's `client-hub-blueprint/entity-projections.yaml`, and the six
> `_ADDRESS_*` constants have been deleted. The candidate shape below is also out of date — it is now `type: entity_projection_candidate` with
> `projection_id`, `part_kinds`, and a resolved `target_class_uri` / `target_resolved` (the Phase A2 deferral noted below is closed). See DD-188.

**Status:** Accepted
**Date:** 2026-06-20
**Affects:** `src/kairos_ontology/propose_alignment.py`,
`src/kairos_ontology/claim_registry.py`,
`src/kairos_ontology/migrate_claims.py`, `kairos-design-domain` skill
**Implementation:** issue #192 Phase A1 (A2 target-URI naming + Phase B
satellite/child-entity detection deferred)

### Context

During initial domain design a source table that spreads an address across several
scalar columns (`billing_street` / `billing_city` / `billing_postal_code`) was
silently force-fit into unrelated scalar properties. DD-069 already detects
address-part columns and emits a **prose** `review_reason` ("…model an address
relationship / shared Address concept"), but it only *flags* — nothing
machine-readable is produced, so the relationship is easy to miss and there is no
gate that blocks TTL generation until a human decides.

Issue #192 proposed promoting these into relationship claims, defaulting
cross-module LLM widening on for accelerator domains, and adding satellite/child
detection from name suffixes. Auditing the code and the governing methodology
(`evidence-led-accelerator-first-modeling-approach`) showed several of those levers
drift from the methodology: the accelerator must not become an automatic generator
(lines 72/222/1252), LLM output stays candidate-only until approval (1139),
relationships come from **source-confirmed** silver FKs (525), and DD-070 guarantees
the default (non-`--cross-module`) output is byte-identical with a cache signature
that encodes the cross-module params. Also, `relationship` is already a valid claim
`type`, but a `Claim` only carries one URI (`class_uri` / `property_uri` via
`identifying_uri()`) — it has no source/target/cardinality/source-columns fields, so
it cannot yet faithfully encode a 1:n relationship.

### Decision

Ship the smallest evidence-led slice (**Phase A1**): a deterministic, always-on,
**additive** detector that promotes the existing address-part signal into a
machine-readable **advisory candidate**, plus a mandatory skill gate. No LLM, no
cross-module widening, no new claim type, no registry migration.

- **Detector** (`_detect_address_relationship_candidates`): groups address-part
  columns by **role** (the qualifier prefix, e.g. `billing` / `shipping`), requires
  **≥2 distinct complementary part kinds** per role, and emits one candidate per
  qualifying role. Reuses the DD-069 `_detect_address_part` gate (so
  `country_of_origin` and `billing_email` stay excluded) and exact-token matching to
  avoid false positives (e.g. "ethnicity" ≠ city).
- **Candidate shape:** `{type: address_relationship_candidate, source_table, role,
  suggested_relationship (hasAddress / has{Role}Address), target_concept: "Address",
  source_columns, address_parts, requires_human_confirmation: true, rationale}`.
  It carries **no resolvable target URI** — naming a concrete `→ Address` (Phase A2)
  needs the shared/accelerator pack loaded and is deferred.
- **Additive, advisory:** candidates are emitted *in addition to* the scalar column
  dispositions (deleting those would lose columns from silver/gold + coverage). They
  ride along as a registry-level `relationship_candidates` list — **not** as governed
  `relationship` claims — so we don't prematurely encode under-specified relationship
  semantics. `alignment_to_registry` ignores them for claim generation;
  `merge_preserving_decisions` regenerates them deterministically each run while
  preserving human claim decisions.
- **Enforcement is the skill gate, not an LLM default.** A new MANDATORY
  *Checkpoint 3c — Relationship & Satellite-Entity Review* in `kairos-design-domain`
  blocks TTL generation until every candidate has an explicit model / relate / defer
  decision. Issue #192's cross-module default-on is **rejected** (it would break the
  DD-070 byte-identical contract, enlarge the LLM pool/cost, and drift toward
  accelerator-as-generator); `--cross-module` stays an opt-in deep pass invokable
  from the gate.

### Consequences

- The address-relationship gap is now surfaced as reproducible, reviewable metadata
  and gated before TTL generation, without LLM cost or DD-070 breakage.
- The relationship-claim schema gap is documented but untouched: governed
  `relationship` claims (with source/target/cardinality/columns) and FK-driven
  satellite detection remain future work (Phase A2 / Phase B) once the schema
  semantics settle.
- New deterministic surface area: `relationship_candidates` on `TableAlignment`,
  `alignment_to_dict`, and `ClaimRegistry` (round-tripped through `to_dict` /
  `from_dict` and the migrate path). Covered by `tests/test_relationship_candidates.py`
  and `tests/scenarios/test_scenario_relationship_candidates.py`.
