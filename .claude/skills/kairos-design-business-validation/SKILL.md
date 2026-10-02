---
name: kairos-design-business-validation
description: >
  Interactive v5 workflow for producing a per-domain logical data model document
  (Word .docx, PDF preview) that a business representative and a data architect
  review and sign off. Facts come deterministically from the ontology, Silver
  contracts, bindings and ledgers; the agent drafts only the plain-language
  narrative, which a human confirms before rendering. Use for "business
  validation document", "sign-off pack", "validate the <domain> model with the
  business", "model confirmation document". NOT for changing the ontology,
  bindings or dbt, and NOT release or deployment evidence.
---

# Business Validation Document

Produce one document per domain that lets someone from the business confirm,
line by line, that the canonical model matches how the business works. The
reader knows the business but not modelling, so every fact is restated in
plain language, every relationship is readable in both directions, and every
row has Yes / No / Comment boxes to fill in.

The document is a **validation artefact** (DD-254). A signed document is
evidence for a design decision, never for a release, compile or deployment.
Feedback returns through **kairos-design-domain** (and a Decision Log entry),
never by editing the generated document or the facts.

## Design fleet mode (DD-088)

Default is interactive. Ask the user to confirm scope, core entities, figure
grouping, every narrative block (definitions, "why" panels, glossary meanings,
gaps, decisions) and the output path before rendering.

If the user explicitly requests design fleet mode for this invocation:

- announce that AI will make checkpoint decisions;
- apply every evidence, privacy and verification gate below;
- set `document.ai_drafted: true` in the narrative, so the title page reads
  **AI-drafted, not user-confirmed**;
- record rationale, confidence and evidence references for each AI-approved
  narrative block;
- stop for low confidence, missing definitions, terminology conflicts,
  PII/proprietary risk, or a fact the narrative would contradict.

The override applies only to this skill invocation and is never inherited.

## Authoritative inputs

`business-doc --facts` reads all of these for you; the narrative may never add
a fact they do not carry. Use the inspection commands to understand a fact,
never a `.ttl` read as text (DD-103).

| Input | Read through | Provides |
|---|---|---|
| Ontology import closure | `show-class-inventory --domain <d>`, `list-class-properties <IRI> --domain <d>`, `explain-term <IRI> --domain <d>` | classes, labels, comments, properties with origin, ranges, functional properties, cardinality restrictions, inverses, deprecation, owning domain |
| Silver contract | `model/contracts/<d>.contract.yaml` | column type, `requirement`, business key, relationships |
| Compile plan | `compile <d> --explain --format json` | entities, sources, grain, relationship shapes |
| Bindings | `integration/bindings/*.binding.yaml` with `metadata.domain: <d>` | source systems per entity (named, never sampled) |
| Source ledgers | `integration/sources/_analysis/src-*.table-dispositions.yaml` | `deferred` and `blueprint-gap` entries become candidate gaps |
| Decisions | `decisions/` (records with `domain: <d>`) | decided rules the "why" panels may cite; open questions |
| Glossary | `businessdiscovery/`, `integration/discovery/` | the business's own terms; previous sign-off packs and review remarks |

**PII.** The document never contains sample values, names, identifiers or free
text from any source, even redacted ones. Examples in the narrative are
synthetic and labelled as such.

## Document layout

The layout is fixed so successive domains and versions read the same way. A4
portrait for text; every diagram on its own **landscape** page.

1. **Title block** — "`<Domain>` domain / Logical data model for business
   validation", document version, date, model version (`owl:versionInfo`),
   the facts hash, and "AI-drafted" when produced in fleet mode.
2. **How to use this document**, then a **"What changed since version N"**
   panel when a previous version exists.
3. **§1 Terms used in this document** — *Term | Meaning in this document |
   Owned by*. Every business term used anywhere in the document appears here;
   use the business's word (e.g. "customer", never "client") and no undefined
   metaphors.
4. **§2 The `<domain>` domain and its neighbours** — Figure 1 (this domain in
   the centre, each neighbour domain with what it is master of), the table
   *Domain | Master of | How it is related | Yes | No | Comment*, an optional
   "Why it works this way" panel and the check "Do these domains and
   relationships match how the business works?". Neighbours are **master of
   their data — they link to this domain, they do not copy into it**.
5. **§3 Logical data model** — the line-end legend, one landscape page per
   figure (3.1, 3.2, …), then a *Relationships in Figure N* table per figure
   (*# | Read in one direction | Read in the other direction | Yes | No |
   Comment*, R1…Rn as numbered in the facts) and the box "Anything missing
   from the logical data model?". Three or four thematic figures beat one
   dense one.
6. **§4…§n one section per core entity** — definition and check, "why" panel,
   **Identification** (only the `(PK)` technical id and the `(BK)` business
   key), "Numbers of other objects, still held on the `<entity>`", field tables
   grouped by theme (*Field | Meaning | Data type & format | Code list | Yes |
   No | Comment*), and "Anything missing from the `<entity>`?".
7. **Gaps and open decisions** — G1…Gn and D1…Dn.
8. **Confirmation** — Business representative and Data architect, plus a
   "General comments" box.
9. **Appendix A** — one row per remark on the previous version and how this
   version answers it (only when one was reviewed).

### Conventions the generator applies

- **Relationships, not attributes.** A link to another object is drawn and
  listed as a relationship with its role name, never as a field. A link to a
  code list is a field with its *Code list* column filled.
- **Cardinality comes from OWL.** Functional or max 1 → zero or one; min 1 →
  one or more / exactly one; otherwise zero or more. When Silver joins
  many-to-one but OWL still allows many, the facts carry a warning: raise it
  with the user and fix it in the ontology through **kairos-design-domain**;
  never reword the cardinality in the narrative.
- **Line ends:** the mark at an entity's end says how many of *that* entity
  belong to one at the other end.
- **External entities** (owned by another domain) are grey with the owning
  domain in italics. **Gaps** are dashed red boxes, drawn only where the
  narrative names them.
- **Code lists** are recognised by `kairos-ext:isReferenceData`,
  `kairos-mdm:referenceList` or a `skos:Concept` parent, and shown by their
  dedicated class name.
- **Deprecated** properties and technical columns other than the PK are left
  out.

## Workflow

1. **Scope.** Resolve the hub from `kairos.yaml`, the domain, the core
   entities (default: the classes bound in the domain; override with
   `--entity`), the target document version, and any previous version or review
   remarks (a reviewed `.docx`/`.pdf` with comments, a meeting transcript).
   Confirm with the user.
2. **Facts.**

   ```powershell
   $env:KAIROS_SKILL_CONTEXT = "1"
   uv run kairos-ontology business-doc <domain> --facts --format json
   ```

   This writes `ontology-hub-publish/business/<domain>/business-doc.facts.json`.
   Read the facts from that file; never hand-assemble or edit them. Report
   every entry under `warnings` to the user.
3. **Draft the narrative.** Write `business-doc.narrative.yaml` beside the
   facts. Every block cites its evidence (`rdfs:comment`, decision ID, review
   remark, disposition entry) in an `evidence:` list. Read terminology from the
   glossary and previous packs first. Use the facts' CURIEs (or full IRIs) as
   keys.

   ```yaml
   document: {version: 3, date: 2026-10-01, previous_version: 2}
   # optional: company: <name for the footer>, ai_drafted: true
   how_to_use: [<bullet>, ...]            # optional; a default is used
   what_changed: [<bullet>, ...]
   glossary:
     - {term: Customer, meaning: <plain text>, owned_by: Party, evidence: [<ref>]}
   domain_view:
     rows: {party: <how it is related>}   # keys: neighbour_domains in the facts
     why: [<bullet>, ...]
   figures:
     - id: "3.1"
       title: House, master and transport leg
       entities: [<CURIE>, ...]           # core and external entities
       intro: <text>
       gaps: [{id: G1, near: <CURIE>}]    # optional dashed gap boxes
   relationships:                         # every R-id in the facts
     R1: {one: <sentence>, other: <sentence>}
   entities:                              # every core entity
     <CURIE>:
       heading: House consignment (the shipment)
       definition: <text>
       why: [<bullet>, ...]
       business_key: <what the BK identifies and its uniqueness scope>
       field_groups:
         - {title: Classification, properties: [<CURIE>, ...]}
       field_meanings: {<CURIE>: <business wording>}
       held_references: {<CURIE>: <which object this number points to>}
       omitted: [{property: <CURIE>, reason: <why it is not shown>}]
   omitted: [{item: R7, reason: <why>}]   # a relationship or entity left out
   gaps:
     - {id: G1, concept: Means of transport, today: <text>, evidence: [<ref>]}
   decisions:
     - {id: D1, question: <text>, current: <text>, evidence: [<ref>]}
   review_remarks:
     - {id: 1, remark: <text>, answer: <text>}
   ```

   Each relationship sentence states its cardinality from the facts
   (`from_card` = how many *from* per one *to*, `to_card` = how many *to* per
   one *from*) and, where it helps, when the optional case occurs ("…zero or
   one master consignment. It has none when it is not consolidated.").
4. **Gate: confirmation.** Present the narrative block by block. In
   interactive mode, explicit approval is required for each definition and
   "why" panel; silence is not approval. Re-check that no block contradicts a
   fact (a "why" panel that says "always one" for a zero-or-one relationship is
   a blocking error).
5. **Render.**

   ```powershell
   uv run kairos-ontology business-doc <domain> --render `
     --narrative <path>/business-doc.narrative.yaml --format json
   ```

   The command rebuilds the facts and refuses a narrative that names an ID the
   facts do not carry, or leaves a core entity, relationship or non-deprecated
   field unplaced without an `omitted:` reason. Fix the narrative and re-run;
   never weaken it by omitting a fact the business should see. It writes
   `<domain>-validation-v<N>.docx`, the figure SVGs and, when LibreOffice or
   Word is available, a PDF preview. Rendering needs the `business-doc` extra
   (`uv sync --extra business-doc`) and a headless Chrome, Chromium or Edge for
   the diagrams (`KAIROS_CHROME` points at one); without a browser the figure
   pages hold a placeholder and the command warns.
6. **Verify.** Open the PDF preview (or the `.docx`) and look at every page:
   figures readable, no overlapping labels, no table overflowing the page.
   Confirm every cardinality, type and code list in the document matches the
   facts file, and that every term used is in §1.
7. **Hand off.** Report the file path, document version, model version and
   facts hash. When the signed document comes back, take each No and each
   comment to **kairos-design-domain** (or **kairos-design-mapping** for a
   source issue) and record material outcomes with `kairos-ontology decision
   new`. Never edit the facts or the generated document to absorb feedback.

## Known pitfalls

- **Overlapping labels and lines** in dense figures: split into thematic
  figures instead of cramming one.
- **Generic code-list links** (`ReferenceCode`) read as ambiguous to the
  business; the ontology should link to the dedicated code class.
- **Undefined words** ("contract", "journey", "envelope") are the most common
  review remark; the glossary check in step 6 exists for that.
- **Identification creep:** list only the PK and BK; everything else is a
  field or a relationship.
- **Write access.** A hub's `.claude/settings.json` may deny agent writes to
  `ontology-hub-publish/**`. The CLI writes there; if the narrative cannot be
  written beside the facts, keep it elsewhere in the hub and pass its path.

## Related skills

- **kairos-design-domain** — changes the model when the business says No.
- **kairos-design-discovery** — the confirmed terms the glossary builds on.
- **kairos-design-architecture** — the ubiquitous language and bounded contexts.
- **kairos-design-mapping** — source-side remarks.
