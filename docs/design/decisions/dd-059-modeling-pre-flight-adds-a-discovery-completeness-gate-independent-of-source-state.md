# DD-059: Modeling Pre-Flight Adds a Discovery-Completeness Gate (Independent of Source State)

**Status:** Accepted
**Date:** 2026-06-13
**Affects:** `kairos-design-domain` skill (pre-flight + Step 2a)
**Implementation:** `.github/skills/kairos-design-domain/SKILL.md` (+ scaffold copy)

### Context

The canonical lifecycle is `discovery → source → domain → …` (kairos-help §2), so
business discovery should precede modeling. But `kairos-design-domain` only hard-gated on
**sources**, not discovery: the discovery offer lived **only** in the no-sources branch
(P2a, where it hands off to `kairos-design-source` and offers discovery). When sources
were already imported, the skill landed in the sources-exist path (P2b/P2c) — which ran
only the source checks and never surfaced discovery. The sole other touchpoint was Step 2a
("read business-discovery context *if present*"), passive context rather than a gate. As a
result, on a hub with imported sources but no `businessdiscovery/` artifacts, nothing ever
prompted discovery, and modeling proceeded without the company model + glossary.

### Decision

Add a **Discovery-Completeness Checkpoint (P1b)** to the modeling pre-flight, symmetric to
the P2c Source-Completeness Checkpoint and **independent of source state** so it fires in
**every** branch (P2a and the sources-exist branches):

1. Detect discovery artifacts — `businessdiscovery/*.ttl` and
   `.sessions-design/businessdiscovery-*.md`.
2. If absent, prompt to run **kairos-design-discovery** first (recommended, not a hard
   block — Gate 6 remains authoritative). The user's decline is recorded in the session
   file.
3. Upgrade Step 2a from "read if present" to an explicit gate that assumes P1b has already
   fired and **must** read discovery artifacts when present.

The Continue/Review extension pre-flight note now also runs P1b alongside P2c.

### Rationale

Discovery is the documented lifecycle start but was only enforced in the empty-sources
branch — an asymmetry that let real hubs skip it. Making the gate independent of source
state (a hub can have sources without ever running discovery) closes the gap. It stays a
recommendation rather than a hard block because discovery improves naming alignment but is
not the authoritative evidence source (that is Gate 6 / source data).

### Consequences

- "Start modeling" now surfaces discovery even when sources are already imported.
- Discovery and source completeness are checked symmetrically (P1b + P2c), once per
  session start.
- No CLI/code change — `kairos-design-discovery` already exists; this is a skill-flow
  correction. Pairs with DD-055 (discovery materialization) and DD-058 (source-analysis
  gate).
- **Amended by DD-148**: the "recommendation, not a hard block" framing above is
  superseded once a hub has started modeling (or discovery ran under fleet mode with
  unresolved items) — `kairos-ontology compile`/`validate` now hard-fail in those cases.
