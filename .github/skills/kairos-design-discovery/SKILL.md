---
name: kairos-design-discovery
description: >
  Interactive first step of the design lifecycle. Explores the company this hub
  is for — what they do, their business model and offerings — and captures the
  company's alternative/business terminology as a SKOS glossary for use during
  mapping. Runs BEFORE source and domain design. NOT for modeling classes
  (kairos-design-domain) or running projections (kairos-execute-project).
---

# Business Discovery Skill

You guide the user through **business discovery** — the first phase of the design
lifecycle. The goal is to build shared, written context about the company *before*
any source or domain modeling, and to capture the company's own vocabulary so that
later mapping is accurate.

This skill produces two things:

1. A **company-context summary** in
   `ontology-hub/.sessions-design/businessdiscovery-{YYYY-MM-DD}.md`.
2. A **company business glossary** in
   `ontology-hub/businessdiscovery/{company}-glossary.ttl` (SKOS overlay — the domain
   ontology is never modified).

> **Why this matters (logistics example):** freight-forwarding and logistics
> companies frequently reuse industry terms with a *different* meaning, or have
> their own in-house names for standard concepts. Capturing these alternative
> names here lets the mapping skill correctly link source columns to domain
> properties — **without** distorting the canonical domain ontology.

> 🧹 **Start with a clean context (strongly recommended).** Because this is the
> first step of modeling, begin a **fresh Copilot session** (clear the current
> chat / run `/clear`) before you start. Discovery and modeling work best with an
> uncluttered context window — leftover noise from unrelated tasks can bias naming
> proposals and glossary matching. Advise the user to clear the session if the
> current conversation already contains substantial unrelated history.

---

## Hard Gates (BLOCKING — must not be bypassed)

### Gate 1: Session file prerequisite

> **You MUST create a `ontology-hub/.sessions-design/businessdiscovery-{YYYY-MM-DD}.md`
> file BEFORE writing any glossary TTL.**

### Gate 2: No unconfirmed facts

> **You MUST NOT record a company fact (what they do, business model, offering) as
> confirmed until the user has approved it.**

Information gathered from public web research is **inferred** until the user
confirms it. Mark such items `[INFERRED — public web]` and present them for review.
Never present inferred claims as established fact.

### Gate 3: No glossary term without confirmation

> **You MUST NOT write a `skos:Concept` (or any `skos:altLabel`) to the glossary
> until the user has explicitly confirmed the term and its link to a domain
> class/property.**

### Gate 4: Never modify the domain ontology

> **This skill captures alternative names as a SKOS overlay only. You MUST NOT add
> `skos:altLabel`, synonyms, or business terms to any domain `.ttl` file.**

Link a glossary concept to the domain by **IRI reference only** (`rdfs:seeAlso` /
`skos:relatedMatch`). If the user wants to change the domain model itself, hand off
to the **kairos-design-domain** skill.

### Gate 5: This is an interactive skill (no autopilot)

Present proposals, wait for the user, and proceed step by step. Never batch-confirm
company facts or glossary terms.

---

## Inputs

| Source | Location | Notes |
|--------|----------|-------|
| Raw artifacts (notes, decks, PPT/PDF) | **`.import/businessdiscovery/`** at the **repo root** | User drops these in; read them first |
| **Per-document extractions** | **`ontology-hub/businessdiscovery/_extractions/*.extraction.yaml`** | **One file per processed document — provenance + `source_sha256` for incremental reruns (DD-060)** |
| Public web research | web search / fetch | Mark findings `[INFERRED — public web]` until confirmed |
| Hub README | `ontology-hub/README.md` | Company name + domain context |
| **Reference-model inventories** | **`ontology-hub/referencemodels-unpacked/*.yaml`** | **Materialized in Phase 1a — read-only view of the *full* domain breadth used to link glossary terms** |
| User statements | conversation | Highest-confidence input |

> **Location note:** `.import/` lives at the **repository root** (alongside
> `ontology-reference-models/`), NOT under `ontology-hub/`. It is created
> automatically by `kairos-ontology init` / `new-repo`.

---

## Interaction Modes & Decision Packets (Slice 7 — thin-chat)

> **Concise mode is the default.** This skill is an *orchestrator*: the work and
> the verbose detail live in **versioned artifacts** (the
> `.sessions-design/businessdiscovery-{company}-*.md` session file, the
> `businessdiscovery/_extractions/*.extraction.yaml` extractions, and the
> `businessdiscovery/{company}-glossary.ttl` overlay), **not** in a long chat
> transcript. Chat carries only the **decisions**. See `kairos-help` §11
> (*Skill interaction modes & decision packets*) for the canonical definition
> shared by every `kairos-design-*` skill.

### Modes

| Mode | What it does | When to use |
|---|---|---|
| `guided` | Full step-by-step explanation at every phase (the pre-Slice-7 behavior). | First-time users; teaching / onboarding. |
| `concise` **(default)** | One compact **decision packet** per phase — summary, decision required, options, artifact path. Methodology stated **once**, then linked. | Day-to-day work by someone who knows the flow. |
| `silent-artifact` | Writes confirmed facts/terms straight into the session file + glossary with minimal chat; surfaces **only blocking decisions**. | Trusted fast iteration; review via the PR diff. |
| `review-only` | **No writes** — researches and emits decision packets / findings only. | Audits, second opinions, dry runs. |

Switch modes any time (*"use guided mode"*, *"concise mode"*, …); the active
mode is recorded in the session file so it persists across turns.

### Decision-packet format

```yaml
# 🧩 Decision packet — Phase 2: Terminology capture (glossary term)
summary: "Dossier" = a client engagement file; links to refmodel Case via relatedMatch.
requires_decision: yes        # yes → STOP and wait for the user (never auto-approve)
options:
  - A) capture as skos:Concept "Dossier" → relatedMatch Case (recommended)
  - B) treat as exactMatch of refmodel Case
artifact: businessdiscovery/acme-glossary.ttl  (+ .sessions-design/businessdiscovery-acme-*.md)
mode: concise
```

Render only the packet in chat; push full reasoning to the artifact / session
file. Web findings stay `[INFERRED — public web]` inside the packet until the
user confirms.

### Shared thin-chat rules (identical across all `kairos-design-*` skills)

1. **State methodology once per session, then link** to `kairos-help` instead of
   re-explaining the discovery workflow.
2. **One decision packet per phase / confirmation** — don't batch-confirm company
   facts or glossary terms, and don't pad packets with prose.
3. **End each phase with PR-ready diffs**, not a chat recap: list the changed
   files (session file, extractions, glossary TTL) and say *"review in the GitHub
   PR"*.
4. **Artifacts over transcript** — rationale, provenance, and rejected terms go
   into the session file / extractions, never only into chat.
5. **No-autopilot preserved.** A `requires_decision: yes` packet always waits for
   an explicit user response; no mode (incl. `silent-artifact`) auto-confirms a
   blocking decision (Gate 5).

> **C10 guard:** these modes are presentation rules for *this* skill's existing
> phases — they do **not** add a new orchestration engine. If a request needs
> real branching logic, prefer a deterministic CLI command (e.g. `build-glossary`)
> over more prose here.

---

## Phased Workflow

### Phase 0 — Session check

1. Look for an existing `ontology-hub/.sessions-design/businessdiscovery-*.md`.
2. If found, ask the user:
   > "I found a business-discovery session from `{date}`. **Continue**, **start
   > fresh**, or **review** it first?"
3. If none exists, create one immediately (Gate 1), even if sparse.

> **Starting fresh — archive, don't overwrite (DD-071).** When the user chooses to
> start a new session instead of resuming, first move any existing
> `.sessions-design/businessdiscovery-*.md` log(s) into
> `ontology-hub/.sessions-design/_archive/` (create it if missing; keep the
> original filename). Never delete a previous log. Then create the new session log.

> **Discovery is incremental and idempotent — reruns are expected.** A hub grows
> one domain at a time, but discovery is **company-wide** and runs *before* the
> first domain is modeled, so it deliberately captures terminology for domains that
> don't exist in the hub yet. When you rerun discovery (e.g. before modeling the
> next domain), treat it as a **continue**: re-materialize the inventories
> (Phase 1a), preserve previously generated glossary links as historical
> inspiration, and append newly discovered terms. Never start from scratch unless
> the user explicitly asks. See
> [Phase 4 — Rerun / incremental](#phase-4--rerun--incremental).

### Phase 1a — Materialize reference-model breadth (read-only)

> **Why:** Business understanding and glossary linking must happen against the
> **full domain model**, not just the one domain currently modeled in the hub.
> Materializing the reference models gives discovery a complete, queryable view of
> every available class/property so terminology can be linked correctly up front —
> even for domains that will only be modeled later.

1. **Check the reference models are present.** Confirm
   `ontology-reference-models/` exists at the **repo root**. If it is missing,
   instruct the user to fetch it (read-only, no hub changes):
   ```powershell
   .\update-referencemodels.ps1          # from ontology-hub root
   # or pin a version: .\update-referencemodels.ps1 -Ref v1.2.1
   ```
2. **Materialize the inventories.** Run `generate-inventory` so the *full*
   reference-model breadth (plus any already-modeled hub ontologies) is written as
   read-only YAML:
   ```bash
   kairos-ontology generate-inventory
   # writes ontology-hub/referencemodels-unpacked/*.yaml
   ```
   If `referencemodels-unpacked/*.yaml` already exists and is fresh, you may reuse it; on a
   **rerun** always regenerate so newly-modeled hub classes appear.
3. **Read the inventories** under `ontology-hub/referencemodels-unpacked/` to build an
   in-context map of available domain IRIs (classes + properties) across **all**
   reference-model domains. This map is what Phase 2 uses to link glossary terms.

> **Gate 4 still holds:** materialization is **read-only**. It only generates the
> `referencemodels-unpacked/` YAML and reads the reference models — it never imports them
> into the hub graph and never modifies any domain `.ttl`.

### Phase 1 — Company research

> **Breadth over depth — go company-wide, not first-domain-scoped.** Discovery runs
> once, up front, and is shared across **every** domain the hub will ever model.
> Cover the company's *entire* offering and operating model — all business areas,
> product lines, and processes — not just the domain you happen to be modeling next.
> Use the materialized reference-model breadth (Phase 1a) as a checklist of domains
> the company might touch. Capturing out-of-scope-for-now context here is what
> prevents losing information when later domains are modeled.

1. **Scan the artifacts incrementally.** Run the deterministic status helper to see
   which documents in `.import/businessdiscovery/` are new, changed, or already
   processed (DD-060):
   ```bash
   kairos-ontology discovery-status
   ```
   - **New** (unprocessed) and **changed** documents → process them this run.
   - **Up to date** documents → **skip** re-reading; their extraction file already
     captures what was pulled. (On a full re-review the user can ask you to reprocess.)
2. **Process each new/changed document** and write **one extraction file per document**
   to `ontology-hub/businessdiscovery/_extractions/{slug}.extraction.yaml`
   (`{slug}` = slugified source filename incl. extension, e.g. `abbreviations-pdf`).
   This records **what was extracted from which document** so provenance travels with
   the hub and later reruns stay incremental. Each file follows this schema:
   ```yaml
   version: "1.0"
   source_file: Abbreviations.pdf
   source_path: .import/businessdiscovery/Abbreviations.pdf
   source_sha256: <hash printed/verified by discovery-status>
   processed_at: 2026-01-01T00:00:00+00:00
   strategy: company-terminology-v1          # versioned extractor/strategy label
   summary: >-
     One-paragraph summary of the document and what was pulled from it.
   extracted_terms:
     - altLabel: HBL
       prefLabel: Transport Document
       definition: ...
       category: documentation               # domain / category bucket
       company_specific: true                # true = company-specific, false = generic
       linked_iri: null                      # optional; resolved in Phase 2
       link_relation: seeAlso                # optional; seeAlso (default) | relatedMatch
   notes: ...
   status: processed                         # processed | partial | skipped
   ```
   > **Worked example (generic strategy):** for a terminology-extraction pass, pull the
   > full text from each document and keep only **company-specific** terms — internal
   > system/app names, proprietary identifiers, route/vessel codes, and industry terms
   > the company uses with a *different* meaning — and filter out generic industry
   > jargon (`company_specific: false`). A `Domain`/category column in the source (if
   > present) helps bucket terms. The schema is generic: adapt `strategy` and
   > `extracted_terms` to whatever the discovery focus is.
   >
   > After writing the files, you may re-run `kairos-ontology discovery-status` to
   > confirm every processed document now shows **up to date**.
3. **Read** `ontology-hub/README.md` for the company name and stated context.
4. **Research** the company on the public web (only if the user agrees). Capture
   the **full** business, breadth-first:
   - What the company does (core activity, sector)
   - Business model (how they make money)
   - Offerings / products / services — **all** lines, not only the first domain's
   - Key operational processes and the entities involved
   - Sector specifics (e.g. freight forwarder vs carrier vs 3PL)
5. Present a **Company Context Proposal** and ask the user to confirm/correct each
   point. Tag every web-sourced claim `[INFERRED — public web]` (Gate 2).
6. Save confirmed context to the session file — **including** terms and areas that
   are out of scope for the current domain but will matter for later ones.
7. **Identify master-data / reference anchors early (MDM-first).** Before any
   domain modeling, list the company's **core master-data entities** — the
   shared, governed reference concepts that many domains hang off (e.g.
   *Customer/Party*, *Product/Item*, *Location/Site*, *Employee*, *Account*,
   *Calendar*). For each anchor capture: a working name, which business areas use
   it, the likely **owning** domain/system (system of record), and a candidate
   **reference-model IRI** resolved against the Phase 1a breadth map (hub →
   ref-model → flag, same priority as Phase 2 step 3). Record these under
   **"Master-data anchors (MDM)"** in the session file and flag each for
   **kairos-design-domain**. This front-loads the MDM/ownership decisions that
   `check-claims` later enforces (methodology §6, DD-EL-6), so reference data is
   modeled and claimed before the domains that depend on it.

### Phase 2 — Terminology capture (the glossary)

1. From the artifacts, research, and conversation, list the company's
   **alternative/business names** — especially terms that differ from the standard
   industry meaning.
2. For each term, propose a glossary entry:

| Business term (altLabel) | Canonical / domain term (prefLabel) | Linked domain IRI | Note (if meaning differs) |
|---|---|---|---|
| `House Bill`, `HBL` | Transport Document | `…#TransportDocument` | Broader than strict industry meaning |
| `Leg` | Shipment Movement | `…#ShipmentMovement` | One origin→destination segment |

3. Wait for user confirmation on **each** entry (Gate 3). **Resolve the linked IRI
   against the full domain breadth**, in this order:
   1. **Hub class/property** — read `model/ontologies/`. If a matching hub IRI
      exists, link to it (highest priority — it's already claimed by this hub).
   2. **Reference-model class/property** — otherwise look it up in the materialized
      inventories from Phase 1a (`referencemodels-unpacked/*.yaml`). If a matching
      reference-model IRI exists, **link to that ref-model IRI** (`rdfs:seeAlso` /
      `skos:relatedMatch`). Nothing is lost and the link resolves immediately, even
      though the class isn't modeled into the hub yet. Also note the term under
      **"Terms flagged for domain modeling"** so the class gets claimed when its
      domain is modeled.
   3. **Truly novel** — only when there is **no** hub *and* **no** ref-model match,
      record the term **without** an IRI and flag it for **kairos-design-domain**.
      Never invent an IRI.
4. Once entries are confirmed, **record the resolved `linked_iri`** (and, for a
   reference-model cross-reference, `link_relation: relatedMatch`) back into the
   per-document `_extractions/*.extraction.yaml` files, then **build the glossary
   deterministically** — never hand-write a one-off `rdflib` script (DD-063):

```bash
kairos-ontology build-glossary
# reads businessdiscovery/_extractions/*.extraction.yaml
# writes businessdiscovery/{company}-glossary.ttl  (SKOS overlay — domain .ttl untouched)
#   --company-specific-only   only include terms flagged company_specific
#   --company-domain / --glossary-namespace / --output   override auto-detection
```

   The command aggregates `extracted_terms` into deduplicated `skos:Concept`s
   (grouped by `linked_iri`, else `prefLabel`), collects `skos:altLabel`s, and maps
   `linked_iri` → `rdfs:seeAlso` (or `skos:relatedMatch`). Auto-detected company
   namespace is `https://{company-domain}/glossary#`. The produced TTL looks like:

   > **Glossary authority note (DD-071).** The generated glossary is inspirational
   > background only, not an authoritative ontology artifact. It is not kept in sync
   > with the domain ontology; `rdfs:seeAlso` / `skos:relatedMatch` links are
   > initial hints and are not reconciled during modeling. The generated
   > `skos:ConceptScheme` carries this disclaimer as both `rdfs:comment` and
   > `skos:editorialNote`.

```turtle
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix glossary: <https://{company}.com/glossary#> .

glossary: a skos:ConceptScheme ;
    rdfs:label "{Company} Business Glossary" .

glossary:TransportDocument a skos:Concept ;
    skos:inScheme glossary: ;
    skos:prefLabel "Transport Document"@en ;
    skos:altLabel  "House Bill"@en , "HBL"@en ;
    skos:definition "…what the business means by it…" ;
    rdfs:seeAlso <https://{company}.com/ont/logistics#TransportDocument> .
```

   `businessdiscovery/glossary-template.ttl` (installed by the scaffold) shows a
   worked example of the same shape.

### Phase 3 — Persist & handoff

1. Update the session file: confirmed context, glossary entries, open questions,
   and any terms flagged for domain modeling.
2. Hand off:
   > "Business discovery is captured.
   > - Company context → `.sessions-design/businessdiscovery-{date}.md`
   > - Glossary → `businessdiscovery/{company}-glossary.ttl`
   > - Per-document provenance → `businessdiscovery/_extractions/*.extraction.yaml`
   >   (run `kairos-ontology discovery-status` any time to see what's new/changed)
   >
   > Next: design the bronze vocabulary with **kairos-design-source**, then model
   > the domain with **kairos-design-domain** (it will read this context). The
   > **kairos-design-mapping** skill will use the glossary's alternative names to
   > match source columns to domain properties.
   >
   > 🔁 **Revisit discovery on each new domain.** When you start modeling the next
   > domain, rerun this skill in **continue** mode — it will keep prior glossary
   > links as historical inspiration and capture anything new."

### Phase 4 — Rerun / incremental

Discovery is **idempotent and incremental**. On any rerun (typically before modeling
the next domain), do **continue**, not start-fresh:

1. **Re-scan documents** — run `kairos-ontology discovery-status`. Process **only** the
   documents it flags as **new** or **changed**, writing/refreshing their
   `_extractions/{slug}.extraction.yaml`. Leave **up-to-date** documents untouched
   (their extraction already records what was pulled). This is what makes reruns cheap:
   added artifacts are detected by hash, not by re-reading everything.
2. **Re-materialize** (Phase 1a) — regenerate `referencemodels-unpacked/*.yaml` so new
   terms can still be resolved against the current breadth map.
3. **Preserve existing glossary links** — do **not** re-link previously generated
   `rdfs:seeAlso` / `skos:relatedMatch` references just because the domain model has
   evolved. They are inspirational, historical hints and may intentionally be stale.
4. **Append new terms** — capture any terminology discovered since the last run (from
   newly processed extractions), resolving IRIs with the same hub → ref-model → flag
   priority (Phase 2 step 3).
5. **Update the session file** — bump `Last updated`, keep `Status` accurate, and
   record what changed this run.

> This is what guarantees no information is lost across domains: terms are captured
> company-wide up front, while the generated glossary remains an inspirational
> snapshot rather than a domain-ontology synchronization mechanism.

---

## Session file format

Save to `ontology-hub/.sessions-design/businessdiscovery-{YYYY-MM-DD}.md`:

```markdown
# Business Discovery: {Company Name}

**Started:** {datetime}
**Last updated:** {datetime}
**Status:** IN_PROGRESS | PAUSED | COMPLETED

## Company Context

| Aspect | Summary | Source | Confirmed? |
|--------|---------|--------|-----------|
| Core activity | {what they do} | artifact / web / user | ✅/❓ |
| Sector | {e.g. freight forwarding} | … | ✅/❓ |
| Business model | {how they earn} | … | ✅/❓ |
| Offerings | {products/services} | … | ✅/❓ |
| Key processes | {process → entities} | … | ✅/❓ |

## Master-data anchors (MDM)

> Core shared reference entities identified up front (Phase 1 step 7). Each is a
> modeling prompt for kairos-design-domain and feeds the MDM/ownership checks in
> `check-claims` (methodology §6).

| Anchor | Used by (business areas) | Owning domain / system of record | Candidate IRI (hub or ref-model) | Confirmed? |
|--------|--------------------------|----------------------------------|----------------------------------|-----------|
| {e.g. Customer/Party} | {sales, invoicing, …} | {domain / system} | {IRI or "needs domain class"} | ✅/❓ |

## Glossary Entries (→ businessdiscovery/{company}-glossary.ttl)

| # | Business term(s) | Canonical term | Linked IRI (hub or ref-model) | Source of IRI | Meaning note | Status |
|---|------------------|----------------|-------------------------------|---------------|--------------|--------|
| 1 | {altLabel(s)} | {prefLabel} | {IRI or "needs domain class"} | hub / ref-model / — | {note} | ✅/❓ |

## Terms flagged for domain modeling

> Terms linked to a **reference-model** IRI (class not yet in the hub) and terms
> with **no** match. Keep these as modeling prompts; do not rewrite prior glossary
> links solely to synchronize with later domain modeling (Phase 4).

- [ ] {term} — linked to ref-model `{IRI}`, not yet a hub class → claim via kairos-design-domain
- [ ] {term} — no class/property yet (hub or ref-model) → invoke kairos-design-domain

## Open Questions

- [ ] {question}

## Artifacts reviewed

- {filename} — {one-line summary}
```

Auto-save after each confirmed decision.

---

## Anti-patterns to avoid

- Do NOT add alternative names to the domain ontology — use the glossary overlay.
- Do NOT present public-web findings as confirmed facts.
- Do NOT **invent** an IRI for a `rdfs:seeAlso` link. Linking to an IRI that
  **exists** in the hub (`model/ontologies/`) or in a materialized reference-model
  inventory (Phase 1a) is fine and preferred; only when neither exists do you flag
  the term for kairos-design-domain instead of inventing one.
- Do NOT scope discovery to the first domain — capture the company's full breadth
  (see Phase 1), including terms whose domain isn't modeled yet.
- Do NOT write glossary TTL by string concatenation **or a hand-written one-off
  `rdflib` script** — run `kairos-ontology build-glossary` (DD-063), which
  serializes deterministically from the confirmed extractions.
- Do NOT commit secrets or PII from imported artifacts.

---

## Related skills

| Need | Skill |
|------|-------|
| Model domain classes/properties (incl. terms flagged here) | **kairos-design-domain** |
| Create bronze vocabulary from source docs | **kairos-design-source** |
| Map source columns to domain (consumes this glossary) | **kairos-design-mapping** |
| Full lifecycle overview | **kairos-help** (Fresh Hub Lifecycle) |

---

*This skill is auto-distributed to hub repositories via the scaffold system.
Changes here are mirrored to `src/kairos_ontology/scaffold/skills/kairos-design-discovery/`.*
