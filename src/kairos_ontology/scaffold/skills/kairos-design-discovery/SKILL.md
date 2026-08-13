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

Archetype selection (Gate A below) is never fleet-eligible: always confirmed by the human, even
under an active fleet-mode override for this invocation. It scopes the entire downstream
reference-model import closure, so getting it wrong is effectively irreversible once modeling
begins (DD-149).

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

### Gate A: Archetype confirmation (DD-149)

Before step 1 below, run `kairos-ontology discovery-conformance list-archetypes --format json`
to get the candidate archetype ids + labels, present the full list to the human, and STOP —
require an explicit human reply naming the archetype id, recorded in the interview log. Never
auto-select or AI-approve this choice, even in fleet mode. Only proceed to step 2 (`load
--archetype <id>`) once the human has confirmed. Record `archetype.confirmed_by: "human"` in the
artifact (step 4) — `kairos-ontology compile`/`validate` and `discovery-conformance validate`
reject artifacts missing this.

### Use the toolkit CLI — never hand-transcribe or hand-script

The `kairos-ontology discovery-conformance` command group is the deterministic tool for this
phase. Use it; do not re-derive its output by reading archetype YAML/markdown files by eye or by
writing a one-off Python generator script. Set `KAIROS_SKILL_CONTEXT=1` for these calls.

1. `kairos-ontology discovery-conformance list-archetypes --format json` — discover valid
   archetype ids and load the **authoritative outcome-codes enum** from the contract. Never
   assume or hardcode which codes exist; the enum in the reference-models checkout is the only
   source of truth and it may contain fewer or different codes than any cached example.
2. `kairos-ontology discovery-conformance load --archetype <id> --format json` — the
   authoritative source for `core_concepts` (uri/label/tier) and derived relationship
   `topology` (edges with cardinality). Files can be long or truncated in an editor; the CLI
   payload is complete and hashed (`catalog_hash`, `concept_set_hash`) — treat it as ground
   truth over any manual read of the archetype file. Review `warnings` (version drift, missing
   discovery doc) before proceeding.
3. Author **only** the per-concept business judgment as data: `outcome` (one of the loaded
   codes), `rename_to` or `deviation_reason` where applicable, `confidence`, `rationale`,
   `references`, `needs_confirmation`, `decided_by` (`"user"` or `"ai"` — mark every
   AI-approved choice `"ai"`; never mark an AI choice `"user"`), and optional `likely_domains`
   (a list of lowercase domain-id strings the concept informs — a concept may inform more than
   one domain; omit or leave empty for a **cross-cutting** concept, which stays in scope for
   every domain). This is the actual discovery analysis and cannot be automated — everything
   else (the concept list, tiers, topology) comes from step 2.
4. Write the step-3 judgments as a plain YAML (or JSON) file — `mode: "interactive"` or
   `mode: "fleet"` to match this session (DD-088), a `core_concepts` list with one outcome dict
   per concept from step 2 (`uri`, `outcome`, `tier`, `confidence`, `rationale`, `references`,
   `needs_confirmation`, `decided_by`, `likely_domains` (optional, defaults to cross-cutting),
   plus `rename_to`/`deviation_reason` where applicable), and optional
   `topology_confirmations`/`cardinality_answers`. Then run:

   `kairos-ontology discovery-conformance build --archetype <id> --judgments-file <path>`

   This assembles the full envelope (`schema_version`, `archetype` block with
   `confirmed_by: "human"` per Gate A above, `scorecard`, hashes, etc.), writes it to
   `integration/discovery/core-concepts-conformance.yaml`, and — by default — immediately
   validates it, in one step. Hand-rolling the envelope yourself, or calling
   `kairos_ontology.core.conformance_artifact.build_artifact()`/`write_artifact()` directly, is
   exactly the "one-off script" the opening section of this phase forbids; write the judgments
   file and let `build` assemble and persist the artifact instead.
5. `build` already runs the same checks as `discovery-conformance validate` and fails loudly
   (non-zero exit, printed errors) on any problem — treat that failure the same way you would a
   separate `validate` failure: fix the judgments file (or the archetype/discovery data) and
   rerun `build`, never present an unvalidated artifact as final. A separate
   `kairos-ontology discovery-conformance validate --file integration/discovery/core-concepts-conformance.yaml`
   call is only needed after running `build --no-validate` (e.g. to inspect an intentionally
   incomplete draft) or after hand-editing the written YAML afterward. In any mode — `mode: fleet`
   or `mode: interactive` alike — validation also fails while any concept is `decided_by: "ai"`
   and has an unresolved judgment (`needs_confirmation: true`, or no recorded `confidence`);
   resolve those with the human (or pass `--allow-unresolved` only for a diagnostic dry run, never
   for the final artifact) before presenting the report as done. `mode` records the session type
   for provenance only — it is never a way to bypass this check.

### Outcome-code legend (badge emojis)

Build this legend from the `outcome_codes` returned in step 1 above — do not hardcode a fixed
list here, because the contract can add or remove codes over time. As of the current contract
version there are five codes:

- ✅ `conforms` — concept matches the reference model as-is.
- 🟩 `conforms-with-rename` — concept matches under a different local name (record `rename_to`).
- 🟨 `partial` — concept is partially present; note the gap in the interview log.
- 🟥 `deviates` — concept is present but diverges (record `deviation_reason`).
- ⬜ `not-applicable` — concept does not apply to this business.

If the loaded enum contains a code not covered above (e.g. a future addition), assign it a
sensible new emoji in the report rather than forcing it into `partial`/`deviates`; if you cannot
render it meaningfully, use ⚠️ so the concept is never silently dropped. Never invent a code
(e.g. `open`, `on-hold`) that isn't present in the loaded enum — map genuinely unresolved
concepts to the closest loaded code (typically `partial`) with `needs_confirmation: true` and a
note in the interview log instead.

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
