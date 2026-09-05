# DD-058: Modeling Pre-Flight Gates on Source Analysis; Unpack Reference Models Before `analyse-sources`

**Status:** Accepted
**Date:** 2026-06-13
**Affects:** `kairos-design-domain` skill (pre-flight branches), `kairos-design-source`
skill (Phase 4)
**Implementation:** `.github/skills/kairos-design-domain/SKILL.md`,
`.github/skills/kairos-design-source/SKILL.md` (+ scaffold copies)

### Context

Two adjacent workflow gaps were observed in a client hub:

1. **Modeling started without source analysis.** "Start modeling" routed straight into
   `kairos-design-domain` and proceeded toward the Source Evidence Table even though
   `integration/sources/_analysis/` contained no affinity reports. The skill's pre-flight
   only distinguished *no sources* (P2a → hand off to import) from *sources exist* (P2b →
   completeness checkpoint); it had **no branch for "sources imported but not analysed"**,
   so the data-first analysis (a Gate 6 prerequisite) was silently skipped and Step 0c.1
   fell back to naming heuristics.
2. **Reference-model unpacking happened too late.** `generate-inventory` (the deterministic,
   AI-free materialization of `referencemodels-unpacked/*-inventory.yaml`) was only a *tip*
   before `analyse-sources` and was otherwise enforced as the DD-047 gate at modeling Step
   0c.1b — i.e. mid-modeling. Because it is cheap and AI-free, there was no reason to defer
   it, and deferring it risked failing the DD-047 gate after the long AI analysis had run.

### Decision

1. **Add a modeling pre-flight branch (P2b) that gates on source analysis.** In
   `kairos-design-domain`, the pre-flight now has three branches: **P2a** (no sources →
   hand off to import), **P2b** (sources imported but `_analysis/*-affinity.yaml` missing →
   **auto-hand off to `kairos-design-source` Phase 4** to run the analysis before any class
   design), and **P2c** (sources imported *and* analysed → the existing mandatory
   Source-Completeness Checkpoint, formerly P2b).
2. **Unpack reference models first in source Phase 4.** `kairos-design-source` Phase 4a now
   makes `generate-inventory` (+ `check-inventory`) a **required up-front step** run
   **before** `analyse-sources`, rather than an optional tip. The documented order is
   `generate-inventory` (quick, AI-free) → `analyse-sources` (the long AI run). The
   `kairos-design-domain` Step 0a `_analysis/`-missing handoff was updated to the same
   order.

### Rationale

Domain modeling is data-first: classes/properties must be grounded in analysed source
evidence (Gate 6). A skill that proceeds without affinity reports produces invented
classes, defeating the reference-model-first design. Unpacking the reference models is
deterministic and AI-free, so doing it up front costs nothing and removes a mid-modeling
failure mode (the DD-047 inventory gate) — it is strictly better to unpack before the
expensive analysis.

### Consequences

- "Start modeling" on a hub with imported-but-unanalysed sources now auto-routes through
  `analyse-sources` first instead of silently skipping it.
- The reference-model inventory is materialized before `analyse-sources`, so the later
  Step 0c.1b / DD-047 gate is already green.
- Pre-flight branch labels shifted: the Source-Completeness Checkpoint is now **P2c**
  (was P2b); cross-references in the skill were updated accordingly.
- No CLI/code change — `generate-inventory`, `check-inventory`, and `analyse-sources`
  already exist (DD-044/DD-047/DD-054); this is a skill-flow correction.
