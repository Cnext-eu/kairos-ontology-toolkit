# DD-127: Domain-Ownership Handoffs and Generalized, Stable-Cluster Relationship Candidates

> **Superseded in part by DD-188 (2026-08-17).** The detector described here survives, but its vocabulary no longer lives in the toolkit: the address part
> kinds, role qualifiers and weak/context rules now come from the accelerator pack's `client-hub-blueprint/entity-projections.yaml`, and the six
> `_ADDRESS_*` constants have been deleted. The candidate shape below is also out of date — it is now `type: entity_projection_candidate` with
> `projection_id`, `part_kinds`, and a resolved `target_class_uri` / `target_resolved` (the Phase A2 deferral noted below is closed). See DD-188.

**Status:** Accepted
**Date:** 2026-08-09
**Affects:** `core/claim_registry.py`, `core/migrate_claims.py`,
`core/propose_alignment.py`, `core/draft_model_report.py`
**Implementation:** `DomainHandoff`, `ClaimRegistry.domain_handoffs`,
`_merge_relationship_candidates`, `_RELATIONSHIP_CANDIDATE_DETECTOR_KEYS`,
`_object_relationship_downgrade_reason`, `_is_technical_actor_column`,
`_looks_like_identifier_column`, `_location_role_token` /
`_has_typed_role_evidence`, `_relationship_cluster_id`,
`_cluster_object_property_candidates`

### Context

A design-session review of `propose-alignment` output (`docs/draft/bookingsession.md`,
findings #7–#9) identified three related quality gaps. First, a column whose match
resolved to a sibling/shared reference-model module outside the current domain
(DD-070's `ref_module` tag) was still turned into an ordinary in-domain property
claim by `migrate_claims.alignment_to_registry` — the accelerator's `owns` /
`does_not_own` boundary (`data-domains.yaml`) was enforced only *after* the fact,
downstream, by `claim_coverage.py`'s governance gate, never *before* claim
emission. Second, issue #192's relationship-candidate detector only ever clustered
address-part columns; every other object-property downgrade (F3) emitted one
relationship candidate per column, so several columns evidencing the same
relationship on the same table fragmented into separate, unmergeable candidates,
and a re-run of the detector fully replaced `relationship_candidates` with no
concept of a stable identity a human decision could be recorded against. Third,
the F3 object-property downgrade only ever checked whether a *target class*
resolved — a `created_by_*`/`updated_by_*` technical-actor column, a plain
descriptive scalar with no identifier evidence, or a specialized location
property (e.g. `hasPlaceOfDischarge`) picked without the column itself naming
that role could all still resolve into a governed-looking object-property mapping
or relationship candidate with no generic safeguard against the false positive.

### Decision

`migrate_claims.alignment_to_registry` now checks each column's `ref_module`
(DD-070) **before** building a property claim: a truthy `ref_module` routes the
column into a `DomainHandoff` (new, versioned — `DOMAIN_HANDOFF_SCHEMA_VERSION =
1` — dataclass carrying `ref_class`, `ref_property`, `owning_domains`,
`ref_module`/`ref_module_uri`, and the source `evidence_sources`) instead of a
claim, and `continue`s the loop — the source evidence is never lost, but it can
never be mis-attributed to a domain that does not own it. `ClaimRegistry` gained
an additive `domain_handoffs: list[DomainHandoff]` field (omitted from
serialization when empty, so a pre-feature registry round-trips byte-identical);
`merge_preserving_decisions` always takes `domain_handoffs` from the new run
(derived evidence, not a curated decision, same rule as `generation_outcomes`).
`draft_model_report.py` surfaces `registry.domain_handoffs` as a new
`cross_domain_handoffs` report key, kept separate from `relationship_questions`
so cross-domain recommendations are never conflated with in-domain claim
candidates.

Every relationship-candidate dict (address clusters and, newly, object-property
clusters) now carries a `cluster_id` — a stable SHA-256-derived id computed ONLY
from `(domain, source_table, role/suggested_relationship, target_concept,
cardinality)`, never from which columns currently contribute. A new
`_cluster_object_property_candidates` groups the previously one-per-column F3
candidates by that same stable key, merging `source_columns` (so one cluster
carries all contributing columns) and regenerating the rationale when more than
one column contributes; `_detect_address_relationship_candidates` gained a
backward-compatible optional `domain` keyword to qualify its own `cluster_id` the
same way. On the registry side, `merge_preserving_decisions` now merges
`relationship_candidates` by `cluster_id` via `_merge_relationship_candidates`:
fields owned by the detector (`_RELATIONSHIP_CANDIDATE_DETECTOR_KEYS` —
membership, rationale, cardinality, ...) always refresh from the new run so a
re-run *reports* membership changes, while any additional key a human curator
attached directly to an existing cluster (anything outside that set) survives
the refresh untouched; a candidate without a `cluster_id` (pre-feature output)
passes through unmerged.

A new, deliberately generic (no accelerator/DCSA-specific vocabulary added)
`_object_relationship_downgrade_reason` dispatcher runs before an F3
object-property column is accepted as a resolved mapping: (1) a
technical/audit-actor column (`_is_technical_actor_column` — `created_by_*` /
`updated_by_*` / `approved_by_*` and analogous "&lt;verb&gt;by" shapes) always
downgrades to passthrough evidence and, uniquely, **never** produces a
relationship candidate (audit evidence is not an in-domain relationship); (2) a
specialized location property (one of the existing, pre-dating
`_OBJECT_PROPERTY_NAME_HINTS`, e.g. `hasPlaceOfReceipt`) requires the column's
own name to carry the property's derived role token (`_location_role_token`
strips a `hasPlaceOf`/`hasPortOf`/`has` prefix, e.g. → `receipt`) via
`_has_typed_role_evidence`, else downgrades with reason
`missing_typed_role_evidence`; the two fully-generic `hasLocation`/`hasAddress`
properties are exempt (no specific role to require evidence for); (3) every
other (non-location) object property requires `_looks_like_identifier_column`
evidence (tokenized name — `id`/`code`/`reference`/`key`/... — or data-type
shape — `int`/`uuid`/...) before being trusted as an entity reference, else
downgrades with reason `missing_identifier_evidence`; (4) only after all of the
above passes is the pre-existing F3 `target_resolved` check applied
(`unresolved_target`), preserving byte-identical behavior for every previously
passing case. `_build_object_property_passthrough` /
`_build_object_property_candidate` gained an optional keyword-only `reason`
parameter (default `"unresolved_target"`) that only changes the rationale text
for a non-default reason, so every existing direct-call test keeps its exact
default rationale.

Finally, `uri-anchor-contract`'s existing "no LLM call / no columns" invariant
for an `"unresolved"` table anchor is now also applied to relationship-cluster
detection: `rel_candidates` computation is skipped entirely
(`is_unresolved_anchor`) so an unresolved table emits neither claims (already
true) nor relationship clusters — a name-based address-part cluster naming an
unresolved class could otherwise smuggle a guess back in through the
relationship-candidate side channel.

### Rationale

Enforcing the ownership boundary at emission time (inside `alignment_to_registry`)
rather than only downstream (the existing post-hoc `claim_coverage.py` gate)
means a domain's registry can never even transiently contain a claim it has no
right to approve — the downstream gate remains as defense-in-depth, not the only
line of defense. A content-addressed `cluster_id` (never derived from column
membership) is the only way to let a re-run *refresh* which columns belong to a
cluster while a human decision recorded against that cluster survives — mirroring
the existing claim-`id`-keyed decision-preservation contract
(`HUMAN_CURATED_FIELDS`) at the relationship-candidate granularity. The
audit-actor / identifier-evidence / typed-role-evidence checks were kept
deliberately generic and ordered so each is scoped to exactly the case it targets
(verified against `tests/scenarios/test_scenario_object_property_target.py`'s
existing `PlaceOfReceipt → hasPlaceOfReceipt` regression case, which continues to
resolve normally because the column name itself supplies the "receipt" role
token) — no new accelerator-specific (DCSA/logistics/Booking) name or heuristic
was introduced; the pre-existing `_OBJECT_PROPERTY_NAME_HINTS` list is reused
unchanged.

### Consequences

- `core/claim_registry.py`: new `DomainHandoff` dataclass +
  `DOMAIN_HANDOFF_SCHEMA_VERSION`; `ClaimRegistry.domain_handoffs` field (additive,
  omitted when empty); `_RELATIONSHIP_CANDIDATE_DETECTOR_KEYS` +
  `_merge_relationship_candidates`; `merge_preserving_decisions` merges
  `relationship_candidates` by `cluster_id` and always carries `domain_handoffs`
  forward from the new run; `validate_registry` gained a warning-level check for
  a handoff naming its own registry's domain as an owner.
- `core/migrate_claims.py`: `alignment_to_registry` routes `ref_module`-tagged
  columns into `DomainHandoff` records instead of property claims.
- `core/propose_alignment.py`: new generic safeguards
  (`_is_technical_actor_column`, `_looks_like_identifier_column`,
  `_location_role_token` / `_has_typed_role_evidence` /
  `_is_location_object_property`, `_object_relationship_downgrade_reason`);
  `_relationship_cluster_id` + `cluster_id`/`cardinality` on address candidates;
  `_cluster_object_property_candidates`; `_detect_address_relationship_candidates`
  gained a backward-compatible `domain` keyword; relationship-cluster detection is
  now skipped for an `"unresolved"` table anchor.
- `core/draft_model_report.py`: new `cross_domain_handoffs` report key per domain,
  kept separate from `relationship_questions`.
- New/updated tests: `tests/test_claim_registry.py` (`TestDomainHandoff`,
  `TestRelationshipCandidateClusterMerge`), `tests/test_migrate_claims.py`
  (`TestDomainHandoffMigration`), `tests/test_propose_alignment.py`
  (`TestTechnicalActorSafeguard`, `TestIdentifierEvidenceSafeguard`,
  `TestTypedLocationEvidenceSafeguard`, `TestRelationshipClusterId`,
  `TestClusterObjectPropertyCandidates`), `tests/test_draft_model_report.py`,
  and new scenario coverage
  (`tests/scenarios/test_scenario_cross_module.py::TestCrossModuleOwnershipHandoff`,
  `tests/scenarios/test_scenario_unresolved_relationship_clusters.py`).
