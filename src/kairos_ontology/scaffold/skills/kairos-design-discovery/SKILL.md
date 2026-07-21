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

## Design fleet mode (DD-088)

Default is interactive: ask the user to confirm company facts, inferred business
terms, and glossary entries. At the start of each invocation, this skill offers a
skill-scoped fleet override after explaining its implications. If the user selects
fleet mode, make high-confidence checkpoint decisions with AI judgment, but mark
them as **AI-approved** rather than user-confirmed. Record rationale, confidence,
and source evidence in `phases/discovery.md`; stop for low-confidence company
facts, conflicting evidence, proprietary/PII risk, or terms that could materially
affect later domain/mapping design.

Any fleet override applies only to this skill invocation. It expires when the
skill ends or pauses and is never inherited by another skill or a later resume.

## Lifecycle state (DD-080)

> The **kairos-flow** skill is the lifecycle orchestrator and the **only** writer of
> `ontology-hub/.kairos-state/status.md`. This skill plugs into that shared state; it
> does not maintain the global status file.

**On start (pre-flight):** read `ontology-hub/.kairos-state/` — the `status.md`
continuation region and this phase's log at `phases/discovery.md` — to resume any open
questions. Ignore `_archive/`. (`kairos-ontology status` gives the objective view.)

**On pause or finish:** append a *State update proposal* to `phases/discovery.md` with
OKF frontmatter (`type: kairos-phase-log`, `phase: discovery`, `instance: company`,
`status:`, `last_updated:`). Record decisions made and an **Open questions** list as the
resume anchor. Do **not** edit `status.md` directly — kairos-flow folds your proposal in.


You guide the user through **business discovery** — the first phase of the design
lifecycle. The goal is to build shared, written context about the company *before*
any source or domain modeling, and to capture the company's own vocabulary so that
later mapping is accurate.

This skill produces two things:

1. A **company-context summary** in the OKF phase log
   `ontology-hub/.kairos-state/phases/discovery.md`.
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

> **You MUST create a `ontology-hub/.kairos-state/phases/discovery.md`
> file BEFORE writing any glossary TTL.**

### Gate 2: No falsely confirmed facts

> **You MUST NOT record a company fact (what they do, business model, offering) as
> confirmed until the user has approved it.**

Information gathered from public web research is **inferred** until the user
confirms it. Mark such items `[INFERRED — public web]` and present them for review.
In an authorized fleet invocation, high-confidence facts may instead be recorded
as **AI-approved**, with rationale, confidence, and evidence. Never label an
AI-approved or inferred claim as user-confirmed or present it as an established
stakeholder fact.

### Gate 3: No glossary term without approval

> **You MUST NOT write a `skos:Concept` (or any `skos:altLabel`) to the glossary
> until the term and its domain link are user-confirmed in interactive mode or
> explicitly AI-approved with rationale, confidence, and evidence in an authorized
> fleet invocation.**

### Gate 4: Never modify the domain ontology

> **This skill captures alternative names as a SKOS overlay only. You MUST NOT add
> `skos:altLabel`, synonyms, or business terms to any domain `.ttl` file.**

Link a glossary concept to the domain by **IRI reference only** (`rdfs:seeAlso` /
`skos:relatedMatch`). If the user wants to change the domain model itself, hand off
to the **kairos-design-domain** skill.

### Gate 5: No autopilot without a current skill override

Interactive mode is the default: present proposals, wait for the user, and proceed
step by step. Fleet behavior is allowed only after the user grants the override
for this invocation in Phase 0. Never reuse an override from stored state or a
previous conversation.

---

## Inputs

| Source | Location | Notes |
|--------|----------|-------|
| Raw artifacts (notes, decks, PPT/PDF, screenshots, diagrams, scanned docs, image files) | **`.import/businessdiscovery/`** at the **repo root** | User drops these in; read them first, including text embedded in images |
| **Per-document extractions** | **`ontology-hub/businessdiscovery/_extractions/*.extraction.yaml`** | **One file per processed document — provenance + `source_sha256` for incremental reruns (DD-060)** |
| Public web research | web search / fetch | Mark findings `[INFERRED — public web]` until confirmed |
| Hub README | `ontology-hub/README.md` | Company name + domain context |
| **Reference-model inventories** | **`ontology-hub/referencemodels-unpacked/*.yaml`** | **Materialized in Phase 1a — read-only view of the *full* domain breadth used to link glossary terms** |
| **Business archetypes (contract v0.2)** | **`<refmodels-root>/blueprints/archetypes/<id>.yaml`** (+ `_schema/outcome-codes.yaml`, `accelerator-packs/*/discovery/<id>.md`) | **Machine catalog of core concepts + tiers per archetype; drives Phase 2.5. Root resolved via `--refmodels-root` → `KAIROS_REFMODELS_ROOT` → fallback** |
| User statements | conversation | Highest-confidence input |

> **Location note:** `.import/` lives at the **repository root** (alongside
> `ontology-reference-models/`), NOT under `ontology-hub/`. It is created
> automatically by `kairos-ontology init` / `new-repo`.

---

## Phased Workflow

### Phase 0 — Session check

1. Look for an existing `ontology-hub/.kairos-state/phases/discovery.md`.
2. If found, ask the user:
   > "I found a business-discovery session from `{date}`. **Continue**, **start
   > fresh**, or **review** it first?"
3. If none exists, create one immediately (Gate 1), even if sparse.
4. **Choose the mode for this invocation.** After the continue/start-fresh/review
   decision, explain the implications and ask with the interactive question tool:

   > **Interactive:** You approve company facts, glossary links, and conformance
   > decisions step by step.
   >
   > **Design fleet:** AI may approve high-confidence decisions and records each as
   > AI-approved with rationale, confidence, and evidence. The same phases and gates
   > still apply. Discovery stops for ambiguity, conflicting evidence, sensitive
   > data, or materially consequential choices.

   Offer exactly:
   - **Interactive (Recommended)**
   - **Design fleet**

   Record the selected mode in `phases/discovery.md`. This is an invocation record,
   not reusable consent: ask again after any pause/resume and never pass the mode to
   another skill. If fleet is selected, announce that it is active before Phase 1a.

> **Starting fresh — archive, don't overwrite (DD-071).** When the user chooses to
> start a new session instead of resuming, first move any existing
> `ontology-hub/.kairos-state/phases/discovery.md` log into
> `ontology-hub/.kairos-state/_archive/` (create it if missing; use a
> collision-safe filename). Never delete a previous log. Then create the new
> phase log.

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
   Inspect **all evidence in the artifact**, not only selectable text:
   - standalone images (`.png`, `.jpg`, screenshots);
   - scanned PDFs and OCR-visible text;
   - embedded images in PDF/PPT/deck exports;
   - diagrams, process flows, org charts, swimlanes, tables, captions, legends, and
     screenshots.

   Pull visible labels, OCR text, diagram entities, system/application names,
   process steps, roles, product names, and business terms from visual content. If a
   visual/OCR finding is uncertain, mark it as low confidence and keep it
   **inferred** until the user confirms it (Gate 2 / Gate 3). Do not copy raw
   screenshots or sensitive image content into the extraction YAML; summarize only.

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
       source_locator: page 3 diagram        # optional: page/slide/image locator
       evidence_type: diagram                # optional: text | image | ocr | diagram | screenshot
       linked_iri: null                      # optional; resolved in Phase 2
       link_relation: seeAlso                # optional; seeAlso (default) | relatedMatch
   visual_evidence:                          # optional; summarize, never embed raw images
     - locator: page 3 / slide 7 / screenshot.png
       visual_type: process_diagram          # process_diagram | org_chart | screenshot | table | scanned_text | other
       extracted_text:
         - HBL
         - Customer Portal
       observed_entities:
         - Transport Document
         - Shipment
       notes: Diagram appears to show how house bills flow through the portal.
       confidence: medium                    # high | medium | low
   notes: ...
   status: processed                         # processed | partial | skipped
   ```
   > **Worked example (generic strategy):** for a terminology-extraction pass, pull the
   > full text and visual content from each document and keep only
   > **company-specific** terms — internal system/app names, proprietary identifiers,
   > route/vessel codes, diagram labels, screenshot labels, and industry terms the
   > company uses with a *different* meaning — and filter out generic industry jargon
   > (`company_specific: false`). A `Domain`/category column in the source (if
   > present) helps bucket terms. The schema is generic: adapt `strategy`,
   > `extracted_terms`, and `visual_evidence` to whatever the discovery focus is.
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
5. Present a **Company Context Proposal**. In interactive mode, ask the user to
   confirm/correct each point. In fleet mode, AI-approve only high-confidence
   points and stop on the Gate 2 conditions. Tag every unresolved web-sourced claim
   `[INFERRED — public web]`.
6. Save user-confirmed or explicitly AI-approved context to the session file —
   **including** terms and areas that are out of scope for the current domain but
   will matter for later ones.

### Phase 2 — Terminology capture (the glossary)

1. From the artifacts, research, and conversation, list the company's
   **alternative/business names** — especially terms that differ from the standard
   industry meaning.
2. For each term, propose a glossary entry:

| Business term (altLabel) | Canonical / domain term (prefLabel) | Linked domain IRI | Note (if meaning differs) |
|---|---|---|---|
| `House Bill`, `HBL` | Transport Document | `…#TransportDocument` | Broader than strict industry meaning |
| `Leg` | Shipment Movement | `…#ShipmentMovement` | One origin→destination segment |

3. In interactive mode, wait for user confirmation on **each** entry. In fleet
   mode, approve only high-confidence entries and record the required decision
   evidence; stop on Gate 3 uncertainty. **Resolve the linked IRI against the full
   domain breadth**, in this order:
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

### Phase 2.5 — Core Concepts Conformance (archetype contract v0.2)

> **What this phase answers:** *Which industry-standard concepts MUST exist for this
> kind of business, and does the company actually conform to them?* This is the gap
> that otherwise surfaces mid-modeling as ad-hoc reference-model debates and
> undocumented deviations. It runs **after** the business model + glossary are
> captured (Phase 2) and **before** handoff (Phase 3), producing a machine artifact
> that **kairos-design-domain** consumes when selecting reference models.

> **Contract source.** Reference-models **v1.11.0+** ships the *archetype + discovery
> contract (v0.2)*: a machine catalog per archetype
> (`blueprints/archetypes/<id>.yaml`: ref-model modules + core concepts + tiers), a
> shared outcome enum (`blueprints/archetypes/_schema/outcome-codes.yaml`), and SME
> interview prose (`accelerator-packs/<pack>/discovery/<id>.md`, paired by filename
> stem). The toolkit loads, validates, derives topology, and persists; this skill
> drives the interview.

> **Mode (DD-088).** Interactive by default — present each concept's proposed
> outcome and **wait for user confirmation**. In an authorized design-fleet
> invocation, the AI may approve high-confidence outcomes from the glossary and
> business model, recording each as AI-approved with rationale, confidence, and
> evidence. Ambiguous outcomes remain inferred and require user input.

> **Single archetype per session.** Pick exactly one archetype. A company spanning two
> archetypes runs a second discovery session (contract composability rule).

**Outcome codes** (loaded from the ref-models `outcome-codes.yaml` — codes are
authoritative there, the prose lives here):

| Code | Meaning |
|------|---------|
| `conforms` | The concept exists in the business exactly as the standard defines it. |
| `conforms-with-rename` | The concept exists but the business calls it something else (capture the alt-label in the glossary). |
| `partial` | The concept partly applies — some attributes/relationships are missing or differ. |
| `deviates` | The business does something materially different from the standard (capture the deviation reason). |
| `not-applicable` | The concept does not apply to this business at all (capture why). |

**Steps:**

0. **Locate the reference-models root.** Resolution precedence: explicit
   `--refmodels-root` → `KAIROS_REFMODELS_ROOT` env var → the existing
   `_resolve_ref_models_dir()` fallback chain. The root is normalized (accepts the
   repo root *or* its `ontology-reference-models/` child) and validated by presence of
   `catalog-v001.xml` + `blueprints/archetypes/`. If it can't be found, stop with an
   actionable message (set the env var or unpack the reference models).

1. **Pick a single archetype.** List the available archetypes and let the user choose
   the one that matches the business:

   ```bash
   kairos-ontology discovery-conformance list-archetypes
   ```

2. **Load the archetype + auto-derive topology.** This emits the catalog (modules +
   core concepts + tiers), the derived relationship topology (domain/range edges +
   declared cardinality), and the paired discovery-doc path as **clean JSON/YAML on
   stdout** (all progress/diagnostics go to stderr):

   ```bash
   kairos-ontology discovery-conformance load --archetype <id> --format json
   ```

   - **Counts are dynamic** — read the concept/module counts from the loaded archetype;
    never hardcode them (e.g. `shipping-carrier` currently has 186 concepts / 27
    modules).
   - A **version-drift warning** may appear if the archetype's `compatible_with`
    range doesn't match the resolved ref-models `VERSION` or per-module
    `owl:versionInfo`. It's a warning, not a blocker.
   - If a core-concept URI can't be resolved in the modules, it's **warned and
    skipped** — continue with the rest.

3. **Run the conformance interview — keep it light.** Drive it from the discovery-doc
   prose, grouped by business area, **tier-gated**:
   - **`required` concepts first** — confirm an outcome code for each.
   - **`recommended` / `optional`** — batch or skip; don't belabor them.
   - **Topology is a yes/no checklist**, not open questions — the standard relationships
    are auto-derived; just confirm each holds. Concepts with `minCardinality >= 1`
    are already ontology-declared mandatory — don't re-ask; only genuinely-undeclared
    1-vs-many cardinality gets a fresh question.

4. **Structural / lifecycle questions.** Ask the small number of genuinely-undeclared
   questions the discovery doc flags (lifecycle states, the undeclared cardinalities
   from step 3).

5. **Coverage scorecard.** Summarize counts per outcome and per tier (conforms /
   rename / partial / deviates / N-A), so the user sees how well the business fits the
   archetype before handoff.

6. **Persist (dual persistence — DD-080).**
   - **Machine artifact** → `integration/discovery/core-concepts-conformance.yaml`
    (validated, hashed for stale-detection, carries the resolved `ref_model_modules`
    so design-domain can pre-seed imports). Write/validate via:

    ```bash
    kairos-ontology discovery-conformance validate --file \
      integration/discovery/core-concepts-conformance.yaml
    ```

   - **OKF phase log** → append a **Core Concepts Conformance** section to
    `.kairos-state/phases/discovery.md` recording the chosen archetype, the outcome
    decisions, deviations/renames, and any **open questions** (resume anchor). Do not
    write `status.md` — kairos-flow folds the deterministic status in.

> **Handoff effect.** `kairos-design-domain` reads
> `integration/discovery/core-concepts-conformance.yaml` during reference-model
> selection: it pre-seeds the imports from the persisted `ref_model_modules`,
> pre-justifies known deviations/renames, and surfaces `not-applicable` exclusions.
> Consumption remains **warn-only** (missing or stale artifact warns, never blocks).

#### Downstream: conformance feeds *proposed-only* claims (DD-090 → DD-095)

A committed, valid conformance artifact is also a **deterministic evidence stream**
for `derive-claims` (run later in **kairos-design-source**). This is the seam where
the lifecycle turns curated conformance outcomes into candidate claims **without any
AI and without any approval authority**:

- **AI-free, deterministic derivation.** `derive-claims` maps each conformance
  outcome to a candidate class claim by a fixed policy — `conforms` → `claim`,
  `conforms-with-rename` → `claim` (carrying the alt-label), `partial` →
  `specialize`, `deviates` → `gap`, `not-applicable` → **no proposal**. Required,
  recommended, and optional tiers are **all** eligible; only `not-applicable` is
  dropped. This mapping is machinery, not a design decision — it never runs an LLM.
- **`status: proposed` only — never materialization.** Every derived claim starts
  as `status: proposed`. Conformance authorizes **nothing** to be built: the Claim
  Registry stays the single approval/materialization authority (DD-094), and
  `check-claims` remains the only approval gate. A conformance outcome — even a
  user-confirmed `conforms` — does **not** approve the derived claim.
- **Two distinct decision layers — do not conflate.** The conformance *outcome
  code* here is a **design decision** (user-confirmed by default, or **AI-approved**
  with rationale/confidence/evidence in an authorized fleet invocation). The
  downstream *derived claim* is **AI-free proposal generation** from that
  outcome — it is neither user-confirmed nor AI-approved until a human curates and
  approves it during the source/claims phase.

So when you record outcomes here, you are seeding proposals a human still has to
approve — you are not pre-approving anything for the physical model.

### Phase 3 — Persist & handoff

1. Update the session file: confirmed context, glossary entries, open questions,
   and any terms flagged for domain modeling.
2. Hand off:
   > "Business discovery is captured.
   > - Company context → `.kairos-state/phases/discovery.md`
   > - Glossary → `businessdiscovery/{company}-glossary.ttl`
   > - Core-concepts conformance → `integration/discovery/core-concepts-conformance.yaml`
   > - Per-document provenance → `businessdiscovery/_extractions/*.extraction.yaml`
   >   (run `kairos-ontology discovery-status` any time to see what's new/changed)
   >
   > Next: design the bronze vocabulary with **kairos-design-source**, then model
   > the domain with **kairos-design-domain** (it will read this context). The
   > **kairos-design-mapping** skill will use the glossary's alternative names to
   > match source columns to domain properties.
   >
   > The conformance outcomes you just recorded also become **proposed-only** class
   > claims when **kairos-design-source** runs `derive-claims` (deterministic,
   > AI-free) — a human still curates and approves them via `check-claims`. Nothing
   > here authorizes materialization.
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

Save to `ontology-hub/.kairos-state/phases/discovery.md`:

```markdown
# Business Discovery: {Company Name}

**Started:** {datetime}
**Last updated:** {datetime}
**Status:** IN_PROGRESS | PAUSED | COMPLETED
**Invocation mode:** INTERACTIVE | DESIGN_FLEET

## Company Context

| Aspect | Summary | Source | Confirmed? |
|--------|---------|--------|-----------|
| Core activity | {what they do} | artifact / web / user | ✅/❓ |
| Sector | {e.g. freight forwarding} | … | ✅/❓ |
| Business model | {how they earn} | … | ✅/❓ |
| Offerings | {products/services} | … | ✅/❓ |
| Key processes | {process → entities} | … | ✅/❓ |

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
