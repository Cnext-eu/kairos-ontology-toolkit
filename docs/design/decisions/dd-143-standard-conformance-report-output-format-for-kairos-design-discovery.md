# DD-143: Standard Conformance-Report Output Format for `kairos-design-discovery`

**Status:** Accepted
**Date:** 2026-08-01
**Affects:** `kairos-design-discovery` skill (both copies), archetype conformance report authoring
**Implementation:** `.github/skills/kairos-design-discovery/SKILL.md` (Output format section),
`src/kairos_ontology/scaffold/skills/kairos-design-discovery/SKILL.md` (scaffold copy)

### Context

DD-090 introduced **Phase 2.5 — Core Concepts Conformance**, which persists a machine
`integration/discovery/core-concepts-conformance.yaml` artifact plus an OKF prose section.
The skill, however, never defined an **output format** for the human-readable conformance
report: the reference-model repo owns the interview *questions*
(`accelerator-packs/<domain>/discovery/<archetype>.md`) but not the report *shape*, so every
conformance report was authored ad-hoc. A client-hub run (`shipping-carrier` archetype)
demonstrated that a scannable, visual report (badges, Mermaid diagrams, an at-a-glance
dashboard) materially improved stakeholder review — but that visual structure had to be
hand-created each time and was not reproducible across hubs or archetypes. Because the skill
is toolkit-managed, hubs cannot bake this in locally without failing the managed-files check;
the fix must live in the toolkit.

### Decision

Give `kairos-design-discovery` a **standard conformance-report output format** documented in
its `SKILL.md`. When Phase 2.5 emits a conformance report, the report MUST render the
template structure below (each element renders natively on GitHub, no extra tooling):

1. **Outcome-code legend with badge emojis** — exactly one emoji per outcome, drawn from the
   contract's `outcome-codes.yaml` enum (loaded, never hardcoded):
   - ✅ `conforms` · 🟩 `conforms-with-rename` · 🟨 `partial` · 🟥 `deviates` ·
     ⬜ `not-applicable` · ❓ `open` · 🏗️ `in-scope-modelling-gap` · ⏸️ `on-hold`.
   - Any outcome code added to the contract later gets an emoji assigned in the skill before
     it is used in a report; unknown codes render as ⚠️ so a report never silently drops a
     concept.
2. **"📊 At a glance" dashboard** near the top of the report:
   - a **text coverage bar** (conforms + conforms-with-rename share of total concepts);
   - a **Mermaid `pie`** of core concepts by outcome;
   - a **Mermaid `flowchart`** of the client's canonical spine (the confirmed topology edges);
   - a **Mermaid `flowchart` "scope map"** grouping concepts into In-scope / To-build /
     Out-of-scope / On-hold;
   - a compact **section status matrix** table (section → outcome badge).
3. **Per-section heading badges** — every section heading leads with its outcome emoji for
   scanability, matching the legend.
4. **Interview log** section with date-stamped SME answers, recording rationale, confidence,
   and references per concept as required by fleet mode (DD-088) and the dual-persistence
   contract (DD-090).

**Mermaid label guidance (included in the template):** node labels containing special
characters (`&`, `/`, `→`) MUST be quoted as `["..."]` to avoid Mermaid parser errors — this
was a real failure during the reference run.

The report is a human-authored Markdown artifact that accompanies the machine
`core-concepts-conformance.yaml`; it never replaces the YAML as the execution authority, and
the YAML remains the single machine authority consumed by later lifecycle stages.

### Rationale

A fixed, GitHub-native report shape makes conformance outcomes scannable and comparable across
archetypes and hubs without per-run hand-crafting. Emoji badges plus Mermaid diagrams give a
stakeholder-readable at-a-glance view that the raw YAML cannot, while the YAML stays the
machine authority. Documenting the format in the managed skill (rather than the
reference-model repo) keeps report *shape* in the toolkit and interview *content* in
reference-models, matching the existing ownership split from DD-090.

### Consequences

- Every Phase 2.5 conformance report includes the badge legend, an at-a-glance dashboard with
  at least one Mermaid diagram, per-section badges, and an interview log — with no
  hand-editing.
- The scaffold copy and `.github/skills/...` mirror MUST stay byte-identical; scaffold-sync
  and managed-files tests guard this.
- The report is documentation only; it does not change the conformance artifact schema, the
  outcome enum, claim derivation, or the domain gate.
- New outcome codes in the contract require a skill update (emoji assignment) before use in a
  report; the ⚠️ fallback prevents silent concept loss in the interim.
