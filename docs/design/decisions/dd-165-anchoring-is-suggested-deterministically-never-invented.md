# DD-165: Anchoring is suggested deterministically, never invented

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** kairos-design-domain step 3 (inspect selected industry references)
**Implementation:** `core/class_anchoring.py`, `suggest-anchor` CLI

### Context

DD-163 made an unanchored local class visible. Visibility does not change what gets
authored: the run that prompted it anchored 5 of 132 classes (3.8%) and 0 of 473
properties, while declaring 57 `owl:imports` and referencing terms from 4 of them. The
reference models were installed, imported, and then ignored. A hand-built hub over the
same sources reached 87% class anchoring and 18 `rdfs:subPropertyOf` links, so the gap is
effort, not feasibility.

The effort is mundane and entirely mechanical: find which of ~80 materialized inventories
covers the domain's imports, then read it for a plausible match. Declaring a local class
is always cheaper. Warning about the result afterwards does not change that arithmetic.

### Decision

`suggest-anchor <domain>` reads the inventories for the modules the domain already
imports, ranks candidates for each unanchored term by name evidence, and prints the exact
`rdfs:subClassOf` / `rdfs:subPropertyOf` line. It never writes.

Three constraints make the output trustworthy rather than merely plentiful:

**Silence beats a plausible wrong answer.** An early scoring pass rewarded a shared head
noun and produced `companyBillingPostalCode -> companyCode` and
`companyLegalName -> contactName`. Acting on either writes a false subsumption into the
canonical model, and both look considered. Nothing below an exact, case, plural, or label
match now scores at all.

**Turtle is emitted only for a confident match.** Weaker matches ("X is a qualified form
of Y") are shown as candidates with the paste-ready line withheld, because name evidence
cannot separate a right specialisation from a sibling.

**Ranking uses the archetype, and warnings do not reorder it.** Eight classes in the party
modules end in "Party" and score identically; the archetype breaks the tie, marking
`mmt/party#TransportParty` *required* and `NotifyParty` *optional*. Separately, a first
version sorted pattern-library grain collisions last — which buried `TransportParty`, a
flagged collision *and* the archetype's required party identity, beneath two deprecated
role overlays. The caution is now an annotation on the ranked answer, never a demotion.

### Alternatives rejected

| Alternative | Why not |
|---|---|
| Auto-apply the top anchor | Subsumption is a modelling assertion. `qualified-role-assignment` exists because subclassing the wrong party parent is a known, costly error. |
| Embedding/LLM similarity | A score no one can explain makes the author's judgement harder, and this must stay deterministic and offline like every other design-stage check. |
| Enforce an anchoring ratio | A hub legitimately declares classes the reference model does not carry. Ratios stay reported by DD-163, unenforced. |
| Suggest from all inventories | An anchor into an unimported module produces a dangling reference the managed-import check then rejects. Scoped to declared imports. |

### Consequences

Advisory and exit-0 always. On the CLdN hub it finds confident anchors for 3 of party's
40 unanchored terms, 6 of financial's 120, and 4 of booking's 64 — modest, and every one
is an exact name match against a module the domain already imports, i.e. reuse that was
sitting there unused.
