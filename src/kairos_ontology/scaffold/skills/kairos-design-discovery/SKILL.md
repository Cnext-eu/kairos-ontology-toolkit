---
name: kairos-design-discovery
description: Capture confirmed business context and terminology for ontology and binding design.
---

# Business Discovery

Capture business context under `integration/discovery/` before ontology and binding design.
Discovery inputs may include user statements, repository documents, and public research.

## Design fleet mode (DD-088)

Default is interactive. An explicit fleet override applies only to this skill invocation and is
never inherited. Record rationale, confidence, and references for every AI-approved choice. Stop
for ambiguity, low confidence, sensitive data, or consequential policy choices.

## Workflow

1. Read existing discovery inputs and the hub README before proposing changes.
2. Summarize the company, offerings, operating concepts, and terminology. Mark public research as
   inferred until approved; never present inference as stakeholder-confirmed fact.
3. Confirm or AI-approve each business term and ontology link before writing it.
4. Write business context as ordinary Markdown/YAML and alternative terminology as an rdflib-built
   SKOS glossary. Keep canonical class/property definitions in `model/ontologies/` unchanged.
5. Link glossary concepts to ontology IRIs with semantic references; never redefine those IRIs.
6. Parse generated Turtle and report unresolved terms for later ontology or binding review.

Discovery artifacts are authored inputs, not execution authority. Source relations live under
`integration/sources/`; canonical meaning lives in OWL; source-to-canonical execution lives only in
closed `integration/bindings/*.binding.yaml` EntityBinding documents.

## Output format — archetype conformance report (Phase 2.5, DD-090 / DD-143)

Phase 2.5 persists the machine artifact
`integration/discovery/core-concepts-conformance.yaml` plus a human-readable conformance
report. The report MUST render the structure below — every element renders natively on GitHub.
The report accompanies the YAML; it never replaces it as the execution authority, and the YAML
stays the single machine authority consumed by later lifecycle stages.

### Outcome-code legend (badge emojis)

Exactly one emoji per outcome, drawn from the contract's `outcome-codes.yaml` (loaded, never
hardcoded):

- ✅ `conforms` — concept matches the reference model as-is.
- 🟩 `conforms-with-rename` — concept matches under a different local name (record `rename_to`).
- 🟨 `partial` — concept is partially present; note the gap in the interview log.
- 🟥 `deviates` — concept is present but diverges (record `deviation_reason`).
- ⬜ `not-applicable` — concept does not apply to this business.
- ❓ `open` — SME answer still pending.
- 🏗️ `in-scope-modelling-gap` — concept is in scope but needs ontology modelling to land.
- ⏸️ `on-hold` — explicitly parked, with a recorded reason.

When a new outcome code is added to the contract, assign it an emoji here before it is used in a
report. Unknown codes render as ⚠️ so a concept is never silently dropped.

### 📊 At a glance dashboard

Place this near the top of the report:

1. **Text coverage bar** — the share of `conforms` + `conforms-with-rename` over total concepts
   (e.g. `conforms 5/8 ▶▶▶▶▶···`).
2. **Mermaid `pie`** — core concepts by outcome.
3. **Mermaid `flowchart`** — the client's canonical spine, from confirmed topology edges.
4. **Mermaid `flowchart` "scope map"** — group concepts into In-scope / To-build / Out-of-scope /
   On-hold subgraphs.
5. **Section status matrix** — a compact table mapping each report section to its outcome badge.

### Per-section heading badges

Every section heading leads with its outcome emoji for scanability, matching the legend above.

### Interview log

Date-stamped SME answers, one row per concept, recording rationale, confidence, and references
as required by fleet mode (DD-088) and the dual-persistence contract (DD-090). AI-approved
choices are marked as such, never as user-confirmed.

### Mermaid label guidance

Quote node labels containing special characters (`&`, `/`, `→`) as `["..."]` to avoid Mermaid
parser errors — this was a real failure during the reference run.
