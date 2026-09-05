# DD-220: A proposal never re-renders an authored relationship, and a child's own identity is not a foreign key

**Status:** Accepted
**Date:** 2026-09-05
**Affects:** `propose-relationships`, its machine-readable `SCHEMA_VERSION` (1 → 2), and the
tier-1 join rule DD-160 §3 states verbatim
**Issue:** #722
**Implementation:** `core/propose_relationships.py` (`_class_token`, `BoundEntity`,
`_match_join`, `build_relationship_proposals`), `cli/inspection.py`

### Context

On a real hub — 33 bindings, 14 domains, toolkit v5.15.0rc16 — `propose-relationships`
reported 13 proposals, 8 with resolved join columns. None were actionable, and applying them
as rendered would have caused damage. Three defects, all verifiable in the code as it stood.

**The command could not see what the binding already said.** `index_bindings` recorded only
`relationship_count=len(data.get("relationships") or [])`; it never captured the authored
`(property, target)` pairs, and `build_relationship_proposals` never compared against them.
Five of the eight resolved proposals were verbatim re-renders of entries already present in
the target binding. The header simultaneously reported "Bindings with zero relationships: 29"
of 33 — the command knew those four bindings had relationships and re-proposed them anyway.

**Re-rendering one overwrote deliberate policy.** `to_yaml` hard-codes `cardinality`, `mode`,
`missingParent` and `ambiguousParent`. The hub's authored `identificationCodeType` entry
carries `missingParent: null` under a comment naming the five code types (CID, IPA, DUN, GEM,
CAD) its reference catalog does not cover, so an uncatalogued number is retained rather than
failing the load. The proposal for that same relationship rendered `missingParent: error`. An
author following the documented workflow — "Paste the rendered YAML into the child binding" —
converts a tolerant lookup into a hard failure for exactly the rows the comment protects. A
proposal cannot know the policy, which is the reason it must not render one for a relationship
that already exists.

**The tier-1 rule matched the child's own primary key.** `index_bindings` seeded its candidate
list with `list(source_key)`, so the child's own `identity.sourceKey` columns were the *first*
tried against the parent's. Where a hub uses one uniform surrogate identity name, that yields
`source_record_id = source_record_id` — a row joined to itself across two relations. The three
remaining resolved proposals were all this shape. Worse, it ignored `parent_invoice_source_id`,
the real foreign key, which the author had already declared as a `technicalFields` entry with
`purpose: relationship`: the command parsed `purpose` out of the YAML and discarded it before
the matcher ran. It therefore picked the wrong column precisely in the cases DD-139's
`relationship.unrealized-technical-field` warning points at this command to fix.

### Decision

**A `(property, target)` pair the child binding already authors is not proposed.** The pair is
recorded on the report as `already_authored`, counted in the text header and listed in JSON.
Skipping rather than re-rendering with the policy fields stripped is what makes the safety
structural: there is no entry to paste, so nothing can overwrite the author's policy. The
comparison uses `_class_token` — local name, prefix-stripped, case-folded — because a
relationship `target:` may be a full URI, a `prefix:Local` qname, or a bare local name, and the
canonical example authors the qname form; raw string equality would miss the match and
re-propose the entry anyway.

**Join keys are matched in three tiers.** Tier 0 (new): a column the author declared
`purpose: relationship`, matched against the parent's `identity.sourceKey` by the same name
equality as tier 1. Tier 1: exact normalized name equality over the child's other authored
columns, **excluding any column that constitutes the child's entire identity**. Tier 2
(DD-189, unchanged): measured value containment. When a join is unresolved, any declared
`purpose: relationship` carrier is surfaced as a `join_candidates` hint — never as a value.

Tier 0's purpose is not better matching; it is exemption from the tier-1 exclusion. Tier 1 is
our inference and must yield to the structural argument below; a declaration is the author
saying "this column is a foreign key" and must not.

`SCHEMA_VERSION` goes 1 → 2.

### Consequences

This **amends DD-160 §3**, which states the rule as "exact normalized name equality against
the parent's `identity.sourceKey`" with no exclusion — the sentence that produced the
self-joins. DD-160 is not superseded; the rest of it stands.

The exclusion is deliberately narrower than #722 proposes. "Exclude the child's
`identity.sourceKey` columns" outright would kill the line-item child whose grain is
`[order_id, line_no]`, where `order_id` genuinely *is* the foreign key — a shape the toolkit
itself scaffolds. Excluding only a column that is the child's *whole* identity is the case
that can be argued structurally: the child then has the same grain as the parent under the
same name, which is the same-entity shape `build_relationship_proposals` already refuses
(#334), not a many-to-one FK.

The one shape this costs is a genuine identifying relationship — a 1:1 extension or subtype
table keyed by its parent's key — which is name-indistinguishable from the bogus self-join and
now falls to `<CONFIRM_JOIN_COLUMN>`. Three mitigations, in order: declare the column
`purpose: relationship` and tier 0 resolves it; let tier 2 resolve it from the measured
profile; or accept the sentinel, which is the contract this command already advertises — a
compile-visible placeholder beats a plausible-looking guess.

Rejected, and why:

- **Matching a `purpose: relationship` carrier positionally** — pairing the sole carrier with
  the sole parent key rather than by name. A child routinely carries several carriers aimed at
  different parents (`parent_invoice_source_id`, `parent_subject_id`), so this is a coin flip
  that emits a *confidently* wrong join. Strictly worse than the bug it replaces, which at
  least looks absurd on the page.
- **Re-rendering authored entries with the policy fields stripped and an `[ALREADY AUTHORED]`
  marker**, as #722 offers as an alternative. It leaves a pasteable block on the screen and
  relies on the reader honouring a label; skipping removes the failure mode instead of
  labelling it.
- **Counting suppressed pairs without listing them.** `_class_token` is deliberately tolerant
  of namespace — the same tolerance `_endpoints` already takes — so two same-local-name
  properties in different namespaces compare equal. Because a match now *suppresses* a
  proposal, that tolerance can hide real work, and the JSON `already_authored` list is what
  keeps it reviewable.
- **Normalizing tokens with `_normalize`** (which strips every non-alphanumeric). `hasParty`
  and `has_party` are different property local names; collapsing them would manufacture false
  suppressions. Case-folding only.

Left open, and filed separately: a container→contained object property (`containsInvoiceLine`,
`includesPortCall`) runs parent→child in the ontology while the foreign key lives on the
contained side. After this change those degrade to honest sentinels rather than wrong joins,
but the command still cannot propose the correct reverse entry. The v5 `cardinality` enum is
`["many-to-one", "one-to-one"]` with no `one-to-many`, so such an edge is not
*mis-cardinalitied* on the container side — it is unauthorable there, and the only correct
authoring is the inverse property on the FK side. Where no `owl:inverseOf` is asserted there is
no property URI to propose and the command would have to invent one, which DD-160 §3 forbids.
That is a design question, not a bug, and it did not belong in this change.
