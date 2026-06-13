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
   `ontology-hub/model/glossary/{company}-glossary.ttl` (SKOS overlay — the domain
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
| Raw artifacts (notes, decks, PPT/PDF) | **`.imports/businessdiscovery/`** at the **repo root** | User drops these in; read them first |
| Public web research | web search / fetch | Mark findings `[INFERRED — public web]` until confirmed |
| Hub README | `ontology-hub/README.md` | Company name + domain context |
| User statements | conversation | Highest-confidence input |

> **Location note:** `.imports/` lives at the **repository root** (alongside
> `ontology-reference-models/`), NOT under `ontology-hub/`. It is created
> automatically by `kairos-ontology init` / `new-repo`.

---

## Phased Workflow

### Phase 0 — Session check

1. Look for an existing `ontology-hub/.sessions-design/businessdiscovery-*.md`.
2. If found, ask the user:
   > "I found a business-discovery session from `{date}`. **Continue**, **start
   > fresh**, or **review** it first?"
3. If none exists, create one immediately (Gate 1), even if sparse.

### Phase 1 — Company research

1. **Read the artifacts** in `.imports/businessdiscovery/` (repo root). Summarise
   each briefly.
2. **Read** `ontology-hub/README.md` for the company name and stated context.
3. **Research** the company on the public web (only if the user agrees). Capture:
   - What the company does (core activity, sector)
   - Business model (how they make money)
   - Offerings / products / services
   - Key operational processes and the entities involved
   - Sector specifics (e.g. freight forwarder vs carrier vs 3PL)
4. Present a **Company Context Proposal** and ask the user to confirm/correct each
   point. Tag every web-sourced claim `[INFERRED — public web]` (Gate 2).
5. Save confirmed context to the session file.

### Phase 2 — Terminology capture (the glossary)

1. From the artifacts, research, and conversation, list the company's
   **alternative/business names** — especially terms that differ from the standard
   industry meaning.
2. For each term, propose a glossary entry:

| Business term (altLabel) | Canonical / domain term (prefLabel) | Linked domain IRI | Note (if meaning differs) |
|---|---|---|---|
| `House Bill`, `HBL` | Transport Document | `…#TransportDocument` | Broader than strict industry meaning |
| `Leg` | Shipment Movement | `…#ShipmentMovement` | One origin→destination segment |

3. Wait for user confirmation on **each** entry (Gate 3). Confirm the linked domain
   IRI exists (read `model/ontologies/`); if the domain class/property does not yet
   exist, record the term and flag it for **kairos-design-domain** rather than
   inventing an IRI.
4. Write confirmed entries to `ontology-hub/model/glossary/{company}-glossary.ttl`
   using `rdflib` patterns (never modify the domain `.ttl` — Gate 4):

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

   Start from `model/glossary/glossary-template.ttl` (installed by the scaffold).

### Phase 3 — Persist & handoff

1. Update the session file: confirmed context, glossary entries, open questions,
   and any terms flagged for domain modeling.
2. Hand off:
   > "Business discovery is captured.
   > - Company context → `.sessions-design/businessdiscovery-{date}.md`
   > - Glossary → `model/glossary/{company}-glossary.ttl`
   >
   > Next: design the bronze vocabulary with **kairos-design-source**, then model
   > the domain with **kairos-design-domain** (it will read this context). The
   > **kairos-design-mapping** skill will use the glossary's alternative names to
   > match source columns to domain properties."

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

## Glossary Entries (→ model/glossary/{company}-glossary.ttl)

| # | Business term(s) | Canonical term | Linked domain IRI | Meaning note | Status |
|---|------------------|----------------|-------------------|--------------|--------|
| 1 | {altLabel(s)} | {prefLabel} | {IRI or "needs domain class"} | {note} | ✅/❓ |

## Terms flagged for domain modeling

- [ ] {term} — no domain class/property yet → invoke kairos-design-domain

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
- Do NOT invent a domain IRI for a `rdfs:seeAlso` link; if the class/property does
  not exist, flag it for kairos-design-domain.
- Do NOT write glossary TTL by string concatenation — use `rdflib`.
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
