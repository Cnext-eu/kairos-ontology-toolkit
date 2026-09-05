# DD-055: Business Discovery Materializes Reference-Model Breadth & Links Glossary to Ref-Model IRIs

**Status:** Accepted
**Date:** 2026-06-13
**Affects:** `kairos-design-discovery` skill (+ scaffold copy), `kairos-design-domain`
skill (step 2a note)
**Implementation:** `.github/skills/kairos-design-discovery/SKILL.md` (Phase 1a,
Phase 1 breadth, Phase 2 IRI resolution, Phase 4 rerun), mirrored to
`src/kairos_ontology/scaffold/skills/`

### Context

Business discovery (DD-048) is meant to be a **company-wide** first step, but its
glossary linking was scoped to the hub: Phase 2 confirmed a term's IRI only against
`model/ontologies/`. Early in a hub only the *first* domain is modeled, so terms
belonging to later domains could not be linked — they all fell into "flagged for
domain modeling". Discovery had no view of the **full** domain model, so the user's
business understanding and terminology capture were implicitly narrowed to the first
domain, risking lost information when subsequent domains were modeled. Materialized
reference-model inventories (DD-044/DD-054) already provide a complete, read-only map
of every available class/property but discovery did not use them.

### Decision

1. **Materialize first (read-only).** Add **Phase 1a** to discovery: run
   `generate-inventory` over `ontology-reference-models/` so discovery has the full
   reference-model breadth as `referencemodels-unpacked/*.yaml` before research. Read-only —
   no hub-graph import, no `.ttl` edits (discovery Gate 4 intact).
2. **Breadth over depth.** Phase 1 research is explicitly company-wide — cover the
   whole offering/operating model and capture out-of-scope-for-now terms.
3. **Three-tier IRI resolution.** Phase 2 resolves a term's IRI in priority order:
   hub IRI (`model/ontologies/`) → existing **reference-model** IRI (from Phase 1a
   inventories) → flag as truly novel. Linking to an existing ref-model IRI is now
   allowed and preferred; only inventing IRIs remains forbidden.
4. **Idempotent reruns.** Add **Phase 4**: on rerun, re-materialize, re-link flagged
   terms to hub IRIs once their domain is modeled, and append new terms. Handoff
   tells the user to revisit discovery on each new domain.

### Rationale

The reference-model inventories are the canonical full-breadth view, and they are
already read-only and sha-verifiable — using them for glossary linking costs nothing
extra and resolves links immediately rather than deferring everything to "flagged".
Keeping it skill-content only (no `generate-inventory` change) is the smallest change
that closes the gap. Importing all reference models into the hub graph was rejected:
it would violate discovery's read-only Gate 4 and bloat the hub with unclaimed classes.

### Consequences

- Discovery now depends on `generate-inventory` having run; the skill invokes it
  (and instructs `update-referencemodels.ps1` if the reference models are absent).
- Supersedes the hub-only linking constraint of DD-048; builds on DD-044/DD-054.
- Glossary entries may carry `rdfs:seeAlso` to a ref-model IRI; these are reconciled
  to hub IRIs on later reruns as domains are modeled — nothing is lost across domains.
- `kairos-design-domain` step 2a notes that glossary terms may point at ref-model
  IRIs and that reconciliation happens on the next discovery rerun (not in the domain
  skill).
