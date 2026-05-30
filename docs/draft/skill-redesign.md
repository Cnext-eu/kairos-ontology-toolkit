# Skill Redesign Plan

> **Status:** Draft (v2 — revised after critical review)  
> **Date:** 2026-05-30  
> **Related:** DD-032, Skills Audit (PR #82)

## Executive Summary

The Kairos Ontology Toolkit ships 19 Copilot skills. An audit identified the
modeling skill (72.6 KB / 1645 lines) as problematically large — not because of
an arbitrary KB threshold, but because **observed failure modes** correlate with
instruction distance from the top of the file:

- Hard gates in mid-document (lines 800+) are sometimes skipped
- Session persistence rules (line ~300) are forgotten when alignment rules (line ~900) dominate
- The 7 distinct responsibilities create ambiguity about which section applies

This plan proposes a **reorganize-first, split-second** approach: improve
instruction salience within the modeling skill before considering extraction.

---

## 1. Problem Statement

### 1.1 The Modeling Skill Has Instruction Salience Issues

The skill is **72.6 KB / 1645 lines** with 7 responsibilities distributed
throughout. The problem is not raw size per se — it's that critical invariants
(hard gates, session management, naming confirmation) are buried in the middle
of the document where LLMs demonstrably lose attention ("Lost in the Middle"
phenomenon, Liu et al. 2023).

**Observed failure patterns:**

| Failure | Root cause | Location in skill |
|---------|-----------|-------------------|
| TTL generated without naming confirmation | Gate buried at line ~450 | Mid-document |
| Session file not created | Persistence rules at line ~300 | Early-mid |
| TMDL evidence ignored | Source analysis at line ~1100 | Late document |
| Alignment strategy not asked | Reference model section at line ~900 | Mid-late |
| Annotations table consulted for non-silver work | Extension table at line ~1400 | End |

**The 7 responsibilities:**

| # | Responsibility | Lines | Extraction risk |
|---|----------------|-------|-----------------|
| 1 | Interactive modeling workflow (gates, checkpoints) | ~400 | ❌ Core — must stay |
| 2 | Session management (persistence, file formats) | ~150 | ❌ Core — must stay |
| 3 | Reference-model-first workflow | ~120 | ⚠️ Coupled to gates |
| 4 | Standard model alignment (Inspired/Enforced) | ~180 | ⚠️ Coupled to gates |
| 5 | TMDL analysis (legacy BI input) | ~80 | ❌ Mandatory Gate 6 — must stay |
| 6 | Source system analysis (reality check) | ~100 | ❌ Core evidence — must stay |
| 7 | Extension annotations reference table | ~150 | ✅ Already in silver skill |

### 1.2 Structural Inconsistencies (minor)

| Gap | Impact |
|-----|--------|
| Inconsistent footers | Users don't discover related skills |
| Missing "Before you start" in some workflow skills | Pre-flight checks skipped |
| Broken cross-reference in SC-merge-pr | Trust erosion |

### 1.3 Broken Cross-References

`SC-merge-pr` references `kairos-help` (non-existent) instead of
`kairos-ontology-help`.

---

## 2. Design Principles

1. **Gates stay together** — All hard gates and invariants must live in ONE skill.
   Never split orchestration from enforcement.
2. **Salience over size** — Reorganize for attention (critical rules first) before
   splitting for size.
3. **Reference material is extractable** — Catalogs, examples, and lookup tables
   can be appendices without breaking workflow integrity.
4. **No peer workflows** — A split must produce a parent + appendix, never two
   competing orchestrators that share session state.
5. **Prove improvement** — Any restructure must demonstrate better gate compliance
   via behavioral prompt testing, not just smaller file size.

---

## 3. Proposed Approach

### Phase A: Reorganize (Recommended First Step)

Restructure the modeling skill **without splitting** to maximize instruction salience:

```
kairos-ontology-modeling (reorganized, same ~1500 lines after removing duplication)
│
├── § NON-NEGOTIABLE GATES (moved to top, ~60 lines)
│   ├── Gate checklist (numbered, explicit)
│   ├── "NEVER generate TTL without confirmed naming"
│   ├── "ALWAYS create session file first"
│   └── "ALWAYS consult TMDL/source evidence when available"
│
├── § DECISION TREE (new, ~30 lines)
│   ├── "If user says 'quick edit' → quick-edit mode"
│   ├── "If user mentions reference model → §5 alignment"
│   ├── "If TMDL/PBIP files present → §4 source analysis first"
│   └── "If multiple domains → STOP, one at a time"
│
├── § SESSION MANAGEMENT (~150 lines)
│
├── § SOURCE & TMDL ANALYSIS (~180 lines)
│   └── Mandatory for all modeling — not just alignment
│
├── § REFERENCE MODEL ALIGNMENT (~300 lines)
│   ├── Inspired vs Enforced strategies
│   ├── Standard model catalog (compact)
│   └── SKOS alignment file instructions
│
├── § CLASS & PROPERTY DESIGN (~400 lines)
│   ├── Naming conventions
│   ├── Property proposal tiers (Tier 1/2 — source vs inferred)
│   └── Subclass justification rules
│
├── § EXAMPLES & REFERENCE (moved to end, ~200 lines)
│   └── "For full annotations table, see kairos-ontology-medallion-silver"
│
└── § RELATED SKILLS (new, ~10 lines)
```

**Key changes:**
- **Gates at the top** — Non-negotiable rules appear in the first 100 lines
- **Decision tree** — Explicit routing within the skill (avoids "which section applies?")
- **Annotations table removed** — Already duplicated in silver skill; replaced with pointer
- **Examples moved to end** — Reference material where attention is lowest anyway
- **TMDL stays** — It's mandatory for Gate 6, not alignment-specific

**Expected result:** ~1500 lines / ~65 KB (modest reduction) but significantly
improved gate compliance due to attention-optimal ordering.

### Phase B: Extract Reference Appendix (If Phase A insufficient)

Only after Phase A is deployed and behavioral testing shows continued gate failures,
extract a **read-only reference appendix** (not a peer workflow):

```
kairos-ontology-modeling              (orchestrator, ~1100 lines, ~50 KB)
├── All gates, all workflows, all session management
├── Source/TMDL analysis (mandatory)
├── Alignment strategy selection (Inspired/Enforced choice)
└── Pointer: "For reference model catalogs and SKOS examples,
    see kairos-ontology-modeling-reference"

kairos-ontology-modeling-reference    (NEW appendix, ~300 lines, ~12 KB)
├── Standard model catalog (FIBO, DCSA, GS1, etc.)
├── SKOS alignment file examples
├── Inspired pattern catalog (Identifier, PartyInRole, etc.)
└── Enforced eligibility checklist
```

**Critical constraint:** The appendix is **reference-only**. It does NOT:
- Own any gates or checkpoints
- Make class/property decisions
- Write session files
- Have its own workflow

The modeling skill remains the **sole orchestrator**. It consults the appendix
for catalog lookups, then returns to its own decision flow.

**Why not a peer skill?**
- Alignment decisions depend on confirmed class names (Gate 3)
- SKOS alignment files reference local classes (must be decided first)
- Session state must be written by one owner to avoid conflicts
- Users say "model this with FIBO" — they expect ONE skill to handle it

### Phase C: Structural Consistency (Separate PR)

Light-touch standardization without over-engineering:

**For workflow skills** (modeling, mapping, silver, gold, source, projection):
- Add `## Related skills` section (2-3 pointers)

**For procedural skills** (SC-merge-pr, SC-feature-branch, SC-document):
- Add `## Error handling` table (they already do real work that can fail)

**NOT adding** (rejected after review):
- ❌ Version metadata in frontmatter — duplicates managed-file stamps
- ❌ Mandatory changelog — skills deploy with toolkit version, not independently
- ❌ "Before you start" everywhere — only where pre-flight checks are meaningful

---

## 4. Rejected Alternatives

### 4.1 Option: Full Peer Skill Split (Original Plan v1)

Extract alignment into `kairos-ontology-modeling-alignment` as a peer workflow.

**Rejected because:**
- Alignment is tightly coupled to modeling gates (session state, naming, source evidence)
- Users won't know to invoke a separate alignment skill — they say "model this with FIBO"
- Creates ping-pong problem: modeling → alignment → back to modeling for TTL generation
- Two skills sharing `.sessions-modeling/` state is a divergence risk
- Routing table can't reliably distinguish "model with alignment" from "just model"

### 4.2 Option: Merge Medallion Skills (source + silver + gold)

Combine the three pipeline phases into one skill.

**Rejected because:**
- Silver skill is already 33.6 KB; merged would be ~52 KB (worse than current modeling)
- Different personas (bronze=data engineer, silver=architect, gold=BI developer)
- Users often do one phase at a time, not all three

### 4.3 Option: Conditional Loading / On-Demand Appendix

Only load alignment sections when user mentions reference models.

**Rejected because:**
- Copilot skill files are loaded in full — no conditional loading mechanism exists today
- Would require tool infrastructure changes beyond this project's scope

---

## 5. Implementation Plan

### Phase 1: Quick Fixes (PR #82 — current branch)

| Task | Effort | Impact |
|------|--------|--------|
| Fix `kairos-help` → `kairos-ontology-help` in SC-merge-pr | 5 min | 🐛 Correctness |

### Phase 2: Reorganize Modeling Skill (separate PR)

| Task | Effort | Impact |
|------|--------|--------|
| Move non-negotiable gates to top of skill | 1 hr | 🎯 Salience |
| Add decision tree section (~30 lines) | 30 min | 🧭 Routing clarity |
| Remove annotations table (replace with pointer) | 15 min | 📉 -150 lines |
| Move examples/reference to end of document | 1 hr | 🎯 Salience |
| Consolidate duplicated content | 30 min | 📉 Size reduction |
| Update scaffold copy | 15 min | 🔄 Sync |
| **Behavioral testing** (see §6) | 2 hr | ✅ Validation |

**Target:** Same ~1500 lines but gates in first 100 lines + decision tree.
Modest size reduction (~65 KB) from deduplication + annotations removal.

### Phase 3: Extract Reference Appendix (only if Phase 2 insufficient)

| Task | Effort | Impact |
|------|--------|--------|
| Create `kairos-ontology-modeling-reference` appendix skill | 1 hr | 📚 Separation |
| Move standard model catalog + SKOS examples | 1 hr | 📉 -300 lines |
| Add "consult appendix" pointers in modeling skill | 30 min | 🔗 Delegation |
| Define handoff contract (what's passed, what's returned) | 1 hr | 🤝 Interface |
| Update routing table (appendix is NOT user-facing) | 15 min | 🧭 Routing |
| Update scaffold copies | 15 min | 🔄 Sync |
| **Behavioral testing** (see §6) | 2 hr | ✅ Validation |

**Gate:** Phase 3 only proceeds if Phase 2 behavioral tests show continued
gate failures attributable to document length.

### Phase 4: Structural Consistency (separate PR)

| Task | Effort | Impact |
|------|--------|--------|
| Add `## Related skills` to workflow skills (6 skills) | 1 hr | 🔗 Discoverability |
| Add `## Error handling` to procedural skills (3 skills) | 30 min | 🛡️ Robustness |

### Phase 5: Governance (process, no PR)

- **Size gate:** Skills exceeding 50 KB require a salience review
- **Sync gate:** `.github/skills/` must always match `scaffold/skills/`
- **Behavioral gate:** Structural changes require prompt-based regression testing

---

## 6. Behavioral Testing Protocol

**Critical:** Restructuring must be validated by behavioral outcomes, not file
metrics. Before and after any reorganization, run these test prompts:

### Test Suite

| # | Prompt | Expected behavior | Gate tested |
|---|--------|-------------------|-------------|
| 1 | "Create a Customer class for me" | Asks for naming confirmation before TTL | Gate 3 |
| 2 | "Just generate the TTL, skip the questions" | Refuses; explains mandatory gates | Gate 1 |
| 3 | "Model an order domain, here's the TMDL: [file]" | Analyzes TMDL before proposing classes | Gate 6 |
| 4 | "Create a logistics ontology inspired by DCSA" | Asks Inspired vs Enforced, proceeds with Inspired | Alignment |
| 5 | "Model client, invoice, and payment domains" | Stops; says one domain at a time | Multi-domain |
| 6 | "Add a phone property to Person" (quick edit) | Uses quick-edit mode without full workflow | Quick-edit |
| 7 | "Import FIBO directly" | Explains Enforced eligibility criteria, likely refuses | Enforced gate |
| 8 | "What silver annotations should I use?" | Points to silver skill, doesn't recite full table | Delegation |

### Scoring

Each prompt is scored pass/fail. **Phase 2 success criteria:** ≥ 7/8 pass.
If < 6/8 pass after reorganization, proceed to Phase 3 (appendix extraction).

### Baseline

Run the same 8 prompts against the CURRENT skill before any changes to establish
a baseline score. This proves whether reorganization actually helped.

---

## 7. Success Criteria

| Metric | Current | Phase 2 Target | Phase 3 Target |
|--------|---------|----------------|----------------|
| Behavioral test score | TBD (baseline) | ≥ 7/8 | 8/8 |
| Gates in first 100 lines | 0 | All 5 gates | All 5 gates |
| Decision tree present | No | Yes | Yes |
| Annotations table duplicated | Yes (modeling + silver) | No (silver only) | No |
| Broken cross-references | 1 | 0 | 0 |
| Skills with Related Skills section | ~5/19 | ~5/19 | 11/19 |

---

## 8. Routing Considerations

### The modeling skill stays as sole entry point for all modeling

Users will say any of these — ALL route to `kairos-ontology-modeling`:

- "Model this domain"
- "Create classes for logistics"
- "Model with FIBO inspiration"
- "Align to DCSA reference model"
- "Here's a TMDL, model from it"

The internal decision tree handles sub-routing. No external routing changes needed
for Phase 2. Phase 3's appendix skill is **not user-facing** — it's consulted
internally by the modeling skill.

### Routing conflict matrix (modeling-adjacent skills)

| User says | Routes to | NOT to |
|-----------|-----------|--------|
| "Model / design / create classes" | modeling | mapping, silver |
| "Map source columns to domain" | mapping | modeling |
| "Add silver annotations" | medallion-silver | modeling |
| "Generate dbt / run projection" | projection | modeling |
| "Validate my ontology" | validation | modeling |

---

## 9. Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-05-30 | Reorganize-first, split-second | Salience improvement is lower-risk than extraction; proves hypothesis before committing to new skill |
| 2026-05-30 | TMDL stays in modeling skill | Mandatory Gate 6 — not alignment-specific |
| 2026-05-30 | No peer workflow skills | Gates must live in one orchestrator; shared state is a divergence risk |
| 2026-05-30 | Appendix (Phase 3) is read-only reference | Avoids competing orchestrators; modeling stays sole decision-maker |
| 2026-05-30 | No version metadata in frontmatter | Managed-file stamps already track this; duplicating creates drift |
| 2026-05-30 | Keep all 19 skills separate | Distinct intents, individually sized (except modeling), routing table works |
| 2026-05-30 | Behavioral testing required | File metrics don't prove instruction-following improvement |
| 2026-05-30 | Phase 3 is gated on Phase 2 results | Don't add complexity unless reorganization alone is insufficient |
