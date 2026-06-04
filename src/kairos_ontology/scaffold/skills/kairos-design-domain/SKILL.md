---
name: kairos-design-domain
description: >
  Expert skill for designing and editing OWL ontology classes, properties, and
  relationships in TTL files. Use when the user wants to create, modify, or
  extend domain ontologies — NOT for repo setup, scaffolding, or infrastructure.
  Includes business alignment checkpoints, reference-model workflow, source/TMDL
  analysis, and session persistence.
---
<!-- kairos-ontology-toolkit:managed v2.35.0 -->

# Ontology Modeling Skill

You are an expert in OWL 2 ontology modeling using Turtle (TTL) syntax. This
skill combines core modeling knowledge with an interactive configurator workflow
that ensures naming decisions and design choices are validated with stakeholders
before generating TTL files.

---

## Hard Gates (BLOCKING — must not be bypassed)

These rules are **non-negotiable enforcement constraints**. Violating any of
them means the modeling process has failed, regardless of output quality.

### Gate 1: Session file prerequisite

> **You MUST create a `.sessions-design/modeling-{domain}-*.md` file BEFORE
> writing any domain `.ttl` file.**

If no session file exists for the domain being modeled, you are NOT permitted
to create or modify its `.ttl` file. Create the session file first, even if
it's initially sparse.

### Gate 2: No TTL without confirmed naming

> **You MUST NOT write a class definition to a `.ttl` file until the user has
> explicitly confirmed the class name via Checkpoint 1 (Naming Alignment).**

This means: propose names → wait for user response → only then write TTL.
Generating "draft" TTL files without checkpoint confirmation is a violation.

### Gate 3: One domain per turn

> **Never model more than 1 domain per user turn.**

If the user requests multiple domains (e.g., "create all 21 domains"), you MUST:
1. Acknowledge the request
2. Propose a priority sequence
3. Start with the first domain using full checkpoints
4. Only proceed to the next domain after the current one is confirmed

Bulk-generating multiple domain files in a single response is **always a
violation**, even if the user says "just do it all."

### Gate 4: Quick-edit scope limit

Quick-edit mode (skipping checkpoints) applies ONLY when ALL of these are true:
- The domain `.ttl` file **already exists** with confirmed classes
- The change involves **≤ 3 properties** being added/modified
- **No new classes** are being introduced
- **No structural changes** (inheritance, imports, domain boundaries)

If any condition is false, use the full checkpoint workflow.

### Gate 5: Explicit user confirmation required

> **Every design decision requires an explicit user response before proceeding.**

You must NOT:
- Assume silence means approval
- Batch multiple unconfirmed decisions into one TTL generation
- Generate TTL "for review" without prior checkpoint confirmation
- Proceed with "reasonable defaults" without asking

### Gate 6: Source-grounded proposals (data-first)

> **You MUST NOT propose class or property names until you have read the
> relevant bronze vocabulary files AND TMDL table definitions (when present).**

Before proposing ANY classes or properties, you MUST:
1. Scan `integration/sources/` for bronze vocabulary `.ttl` files relevant to
   this domain
2. Extract actual table names and column names from those files
3. Check `integration/sources/powerbi/` for TMDL files (engineering packs or
   raw `.tmdl`). **If TMDL files exist, you MUST read them — this is not optional.**

> **Sub-rule 6a:** If `integration/sources/powerbi/` contains TMDL files,
> you MUST read them in Step 0c.3. The Source Evidence Table MUST include
> 🟡 TMDL rows. Skipping TMDL when files exist is a Gate 6 violation.
4. Build a **Source Evidence Table** (see Step 0c below)

Every proposed property MUST cite its evidence source:
- A specific source column name (e.g., `gooddetails2.MAFINR`)
- A TMDL column (e.g., `f_LoadDelivery.TransportMediumTypeDescr`)
- An explicit user statement ("we track X")
- A reference model property (inherited)

Properties based solely on "general domain knowledge" MUST be:
- Clearly labelled as `[INFERRED — no source evidence]`
- Presented in a separate tier BELOW source-evidenced properties
- Never mixed into the main proposal as if they were facts

**Rationale:** Client data is the ground truth for what properties exist and
matter. LLM knowledge can suggest useful additions, but must never masquerade
as fact when source data is available.

### What to do when the user says "just do it" or "skip checkpoints"

If the user explicitly requests skipping governance:
1. Acknowledge their request
2. Explain what will be skipped and the risks (no audit trail, naming may not
   match business language, harder to validate later)
3. Ask: "Would you like me to proceed with minimal checkpoints (namespace +
   class names only) or full skip?"
4. If they confirm full skip, document this in the session file as a conscious
   decision with the user's rationale

---

## Decision Tree (route within this skill)

Use this quick-reference to determine which section applies:

| User's intent | Go to |
|---|---|
| "Add a property" / "fix a label" / minor tweak (≤ 3 props, no new classes) | [Quick-edit mode](#quick-edit-mode) |
| "Model a new domain" / "create classes for X" | [Before you start](#before-you-start-full-modeling-workflow) → full workflow |
| "Use FIBO / DCSA / reference model" | [Reference-model-first workflow](#reference-model-first-workflow) |
| "Here's a TMDL / PBIP file" | [TMDL Analysis](#tmdl-analysis-legacy-bi-input) (then return to modeling) |
| "Align with industry standard" | [Standard model alignment](#standard-model-alignment) |
| "What annotations do I need?" | **Delegate:** invoke `kairos-design-silver` or `kairos-design-gold` skill |
| "Generate dbt / silver DDL / projection" | **Delegate:** invoke `kairos-execute-project` skill |
| "Validate my ontology" | **Delegate:** invoke `kairos-execute-validate` skill |
| "Map source columns to domain" | **Delegate:** invoke `kairos-design-mapping` skill |

> **Default path:** For any new modeling work, always start at
> [Before you start](#before-you-start-full-modeling-workflow) and follow
> Step 0 → Step 0b → Step 0c (Source Evidence Table) → Checkpoints.

---

## Session Management

### On start — Check for existing session

At the beginning of every modeling session, look for saved configuration files:

```
ontology-hub/.sessions-design/
  └── modeling-{domain}-{YYYY-MM-DD}.md    # Saved session state
```

**Ask the user:**

> "I found a saved modeling session for `{domain}` from `{date}`.
> Would you like to:
> 1. **Continue** from that session (pick up where we left off)
> 2. **Start fresh** (new session, previous one archived)
> 3. **Review** the saved session first"

If no session exists, start fresh and create one immediately.

### Session file format

Save progress to `ontology-hub/.sessions-design/modeling-{domain}-{YYYY-MM-DD}.md`:

```markdown
# Modeling Session: {Domain Name}

**Started:** {datetime}
**Last updated:** {datetime}
**Status:** IN_PROGRESS | PAUSED | COMPLETED

## Domain Scope

| Decision | Choice | Confirmed? |
|----------|--------|-----------|
| Domain name | {value} | ✅/❓ |
| Namespace | {value} | ✅/❓ |
| Reference model imports | {list} | ✅/❓ |
| Subclass vs extend strategy | {choice} | ✅/❓ |
| TMDL consulted | yes / no / not-available | ✅ |

## Classes Confirmed

| # | Class Name | Business Term | Subclass of | Status |
|---|-----------|---------------|-------------|--------|
| 1 | {OWL name} | {what users call it} | {parent or none} | ✅ Confirmed / ❓ Open |

## Properties Confirmed

| # | Property | Domain | Range | Business Term | Status |
|---|----------|--------|-------|---------------|--------|
| 1 | {name} | {class} | {type} | {what users call it} | ✅/❓ |

## Open Questions

- [ ] {question 1}
- [ ] {question 2}

## Source Evidence Table

| # | Source Column | Source Table | System | Data Type | Candidate Property | Candidate Class | Evidence |
|---|---|---|---|---|---|---|---|
| 1 | {column} | {table} | {system} | {type} | {property} | {class} | 🟢/🟡/🔵 |

_Built from actual bronze vocabulary files and TMDL definitions (Gate 6)._
_Every proposed property must trace back to a row in this table or be marked [INFERRED]._

## Design Decisions Log

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 1 | {question} | {choice made} | {why} |

## Source Alignment Warnings

| # | Issue | TMDL/Source says | Ref model says | Decision | Status |
|---|-------|-----------------|----------------|----------|--------|
| 1 | {description} | {what TMDL or source shows} | {what ref model defines} | {follow ref model / create local class / discuss} | ⚠️ Discuss / ✅ Resolved |

_This section captures disagreements between legacy BI (TMDL), source system data,_
_and the reference model. Reference model has priority unless explicitly overridden._
```

### Saving and pausing

- **Auto-save** the session file after each confirmed decision
- Mark resolved Open Questions as `[x]` with the decision outcome
- When the user says "pause", "stop", "save", or "continue later":
  1. Update the session file with current state
  2. List remaining open questions
  3. Confirm: "Session saved. You have N open questions remaining."

### Quick-edit mode

When the user is making **minor changes** to an existing ontology (adding a
property, fixing a label, adjusting a range), skip session management and
business checkpoints. Just apply the modeling patterns directly.

**Scope limit (see Gate 4):** Quick-edit ONLY applies when:
- The domain `.ttl` already exists with confirmed classes
- ≤ 3 properties are being added/modified
- No new classes are introduced
- No structural changes (inheritance, imports, domain boundaries)

Indicators of quick-edit mode:
- "Add a property X to class Y"
- "Change the range of X from string to integer"
- "Fix the label on class Z"
- "Add rdfs:comment to these properties"

For anything involving **new classes, renaming, structural changes, or new
domains**, use the full configurator workflow with checkpoints. See Gate 2
and Gate 3 — these are non-negotiable.

---

## Before you start (full modeling workflow)

> ⚠️ **Reminder:** Gates 1–6 above are BLOCKING. Before creating any `.ttl` file,
> verify you have: (1) a session file, (2) confirmed class names, (3) only one
> domain in scope for this turn, (4) source evidence table built.

0. **Quick toolkit version check** — run `python -m kairos_ontology update --check` once
   at the start of the session.  If it reports outdated files, run
   `python -m kairos_ontology update` and commit the refresh before doing any other work.
   See the kairos-toolkit-ops skill for full upgrade steps.
1. **Create a feature branch** — never work directly on `main`.  Use the
   SC-feature-branch skill (e.g., `ontology/add-order-domain`).
2. **Read the hub README** — open `ontology-hub/README.md` and note the company
   name, company domain, namespace base, and the domain model overview table.
   All new ontologies MUST use the namespace pattern documented there.
3. **Ask: Are we starting from a reference model?** — this is the FIRST question
   to ask the user before any modeling work.  See the
   [Reference-model-first workflow](#reference-model-first-workflow) section
   below.  If the user answers yes, follow that workflow before proceeding.
4. **Check the domain model overview** — before creating a new `.ttl` file,
   verify that a row for the intended domain exists in the overview table.
   If it doesn't, add the domain to the table first and get agreement from the
   user.  This avoids fragmented, overlapping ontology files.
5. **Check the master ontology** — after creating a new domain file, add an
   `owl:imports` line for it in `ontology-hub/model/ontologies/_master.ttl`.
6. **Check for standard model alignment** — if the user mentions basing the
   domain on an industry standard (e.g. FIBO, DCSA, GS1, PROV-O, schema.org),
   follow the steps in the [Standard model alignment](#standard-model-alignment)
   section below before designing any classes or properties.

---

## Reference-model-first workflow

The recommended approach for new modeling projects is to **start from reference
models** rather than inventing entities from scratch.  Reference models are
curated, industry-aligned OWL ontologies bundled into **accelerator packs** —
sector-specific collections of ontologies (e.g., Financial Services, Supply
Chain, Healthcare) that provide a proven starting point.

> **Two alignment strategies:** The default strategy is **Reference Model Inspired**
> — model locally with selective pattern adoption and a SKOS alignment file. If the
> user's domain uses a Kairos-managed reference model (small, projection-ready, ships
> defaults), they can override to **Reference Model Enforced** which uses `owl:imports`.
> See [Standard model alignment](#standard-model-alignment) for details.

### Step 0 — Ask the user

At the **very start** of any modeling session, ask:

> "Are we starting from a reference model / accelerator pack?  If so, have you
> already imported the reference models into this hub by running
> `update-referencemodels.ps1`?"

- If the user has **not yet imported** reference models, instruct them to run:
  ```powershell
  .\update-referencemodels.ps1          # from ontology-hub root
  # or specify a version tag:
  .\update-referencemodels.ps1 -Ref v1.2.1
  ```
  This fetches the `ontology-reference-models/` folder from the central repo
  (`Cnext-eu/kairos-ontology-referencemodels`) via a sparse shallow clone.
  The user must run this **before** any modeling work begins.

- If the user says **no reference model** is needed, skip to the standard
  modeling workflow (class design, property design, etc.).

### Step 0a — Source Domain Analysis (MANDATORY prerequisite)

> **BLOCKING GATE:** Before proceeding to modeling, verify that source systems
> have been pre-analysed against reference model domains.

Check for the analysis output:

```bash
ls integration/sources/_analysis/
```

- If `_analysis/` exists with `*-affinity.yaml` files → proceed.  Read the
  domain contribution reports to understand which reference domains each source contributes to.
- If `_analysis/` is **missing** → instruct the user to run:
  ```bash
  kairos-ontology analyse-sources \
    --accelerator logistics \
    --sources integration/sources \
    --ref-models ontology-reference-models \
    --output integration/sources/_analysis
  ```
  With `--accelerator <name>` the analysis classifies each source table toward the
  accelerator's **data domains** (party, commercial, booking, ...) — each carrying its
  model URIs — instead of raw reference-model groupings. Without `--accelerator` it
  falls back to grouping reference-model TTLs. Requires AI provider env vars (see
  `.env.example`).

**Why this matters:**
- The contribution report tells you WHICH data domains are relevant (with their URIs)
- It classifies source tables by domain affinity and identifies likely entities
- It scopes context: only load tables with ≥30% domain_relevance to the target domain
- Without it, the modeler tends to create too many custom classes instead of
  reusing proven reference model concepts

**Using the domain contributions report during modeling:**

When loading source evidence for a domain, read the relevant `{system}-affinity.yaml`:

```yaml
# Example: adminpulse-affinity.yaml shows 82% confidence to the "commercial" data domain
domain_contributions:
  - domain: commercial
    group: party-commercial
    domain_uris:
      - https://www.kairosflow.ai/ont/bsp/commercial#
    ref_source: party-commercial
    confidence: 0.82
    contributing_tables:
      - table: tblContracts
        domain_relevance: 0.85
        rationale: "Contains contract numbers, trade terms, and validity dates"
        likely_entity: SalesContract
        indicative_columns: [ContractNo, TradeTerms, ValidFrom]
      - table: tblPricing
        domain_relevance: 0.71
        rationale: "Pricing conditions tied to commercial agreements"
        likely_entity: PricingCondition
        indicative_columns: [RateCode, Amount, Currency]
```

The `domain` is the data-domain id and `domain_uris` tells you which reference-model
module(s) to `owl:imports` for that domain (e.g. `bsp/commercial`). Use the
pre-classified tables as the **starting point** for your Source Evidence Table
(Step 0c). The `likely_entity` tells you which class each table feeds, and
`indicative_columns` highlights the most relevant columns to consider.

### Step 0b — Inventory available inputs (Source Systems & TMDL)

Before selecting reference models or designing classes, inventory all available
input signals that can inform the modeling process.

**Check for source system documentation:**

```bash
ls ontology-hub/integration/sources/
```

**Check for existing TMDL (Power BI semantic model) files:**

```bash
ls ontology-hub/integration/sources/powerbi/
# or ask: "Do you have existing Power BI TMDL files to use as input?"
```

**TMDL file placement convention:**

```
integration/
  sources/
    powerbi/                              ← TMDL input (one or more semantic models)
      {model-name}.SemanticModel/
        definition/
          model.tmdl                      ← Main model definition
          tables/*.tmdl                   ← Table/measure definitions
          relationships/*.tmdl            ← Relationship definitions
      README.md                           ← Brief description, known issues
    {source-system}/                      ← Source system docs (DDL, API specs)
      sql-ddl/
      api-specs/
      samples/
```

> **💡 Tip:** Use `kairos-ontology import-tmdl <path-to-pbip-or-folder>` to
> automatically extract and inventory TMDL content. It generates an Engineering
> Pack (markdown) and a Concept Mapping template (YAML) that this skill can
> use directly during modeling.

**Present the input matrix:**

> "Here are the available inputs for this modeling session:
>
> | Input | Location | Trust Level | What it provides |
> |-------|----------|-------------|-----------------|
> | Reference model | `ontology-reference-models/` | 🟢 Highest — structural authority | Class hierarchies, standard properties |
> | Source system DDL | `integration/sources/{system}/` | 🟡 High — reality check | Actual cardinalities, data types, columns |
> | TMDL (Power BI) | `integration/sources/powerbi/` | 🟠 Medium — legacy/advisory | Business measures, BI naming, hierarchies |
> | Business knowledge | (from user) | 🟢 High — domain authority | Naming, scope, intent |
>
> **Trust hierarchy (ENFORCED — see Step 0d):**
> Source system columns > TMDL columns > Reference model structure > Domain knowledge
>
> Source system data is the ground truth for what properties exist.
> TMDL files are treated as **legacy input** — they may contain inconsistencies,
> denormalized structures, or patterns that don't follow best practices.
> We use them to inform decisions but never override the reference model.
> General domain knowledge (LLM suggestions) is lowest priority and must always
> be labelled `[INFERRED]` when source data is available."

**Rules for using inputs during modeling:**

| Situation | Action |
|-----------|--------|
| TMDL table matches a reference model class | ✅ Confirms the class is needed; use ref model structure |
| TMDL table has no reference model equivalent | ⚠️ Flag as potential gap — candidate for local class |
| TMDL relationship contradicts reference model | ⚠️ Log as warning; follow reference model; discuss with user |
| Source DDL has M:N where ref model says 1:N | ⚠️ Flag cardinality mismatch; may need junction table |
| TMDL measure references a concept | 🔵 Informs gold-layer design later; note for gold-ext |
| TMDL dimension exists but ref model has no class | ⚠️ Candidate for subclass or new local class |

### Step 0c — Build Source Evidence Table (MANDATORY — Gate 6)

**This step is BLOCKING.** You must complete it before proposing any classes
or properties in Checkpoint 1. The Source Evidence Table drives all proposals.

**Step 0c.1 — Identify relevant source systems:**

Determine which bronze vocabulary files relate to the domain being modeled.
If `_analysis/` contains `*-affinity.yaml` files, use them to scope:

```bash
# Check for affinity reports
ls ontology-hub/_analysis/*-affinity.yaml

# Each report lists contributing_tables per domain with domain_relevance scores.
# Only load tables with domain_relevance ≥ 0.3 for the target domain.
# The likely_entity field tells you which class each table feeds.
```

If no affinity reports exist, use naming heuristics and the user's input to
identify relevant systems:

```bash
# List all bronze vocabulary files
find ontology-hub/integration/sources/ -name "*.vocabulary.ttl"
```

**Step 0c.2 — Extract source table and column inventory:**

For each relevant source system, extract the complete column list:

```bash
# List all tables in a source system
grep "a kairos-bronze:SourceTable" integration/sources/{system}/*.ttl

# Extract all column names for relevant tables
grep "kairos-bronze:columnName" integration/sources/{system}/*.ttl
```

For bronze vocabulary files, extract:
- All `kairos-bronze:SourceTable` resources → candidate class sources
- All `kairos-bronze:SourceColumn` resources → candidate property sources
- All `kairos-bronze:dataType` values → informs `xsd:` range selection

**Step 0c.3 — Read TMDL definitions (MANDATORY when TMDL exists):**

**Check:** Does `integration/sources/powerbi/` contain TMDL files or engineering
packs? If YES → this step is BLOCKING. If NO → document "No TMDL available" in
the session file and skip to Step 0c.4.

For each relevant TMDL table:
- Read the `.tmdl` file to extract column names, data types, and relationships
- Note dimension tables (potential class candidates)
- Note fact tables (potential event/transaction class candidates)
- Note relationship definitions (potential object property candidates)
- Note measures (for gold-layer annotations later — do NOT model measures as
  ontology properties)

**Step 0c.4 — Produce the Source Evidence Table:**

Build this table BEFORE proposing any classes or properties:

> "**Source Evidence Table** (extracted from client data):
>
> | # | Source Column | Source Table | System | Data Type | Candidate Property | Candidate Class | Evidence Strength |
> |---|---|---|---|---|---|---|---|
> | 1 | `MAFINR` | `gooddetails2` | RoRoNet | nvarchar(50) | `mafiNumber` | MafiTrailer | 🟢 Direct |
> | 2 | `LICENSEPLATE` | `equips` | RoRoNet | nvarchar(50) | `licensePlate` | (shared) | 🟢 Direct |
> | 3 | `EQUIPMENTCODE` | `gooddetails2` | RoRoNet | nvarchar(50) | _(discriminator)_ | _(subclass selector)_ | 🟢 Direct |
> | 4 | `TransportMediumTypeDescr` | `d_UnitTypes` | TMDL | string | _(discriminator)_ | _(confirms subclasses)_ | 🟡 TMDL |
> | … | … | … | … | … | … | … | … |
>
> **Evidence strength legend:**
> - 🟢 Direct — column exists in source system bronze vocabulary
> - 🟡 TMDL — column exists in Power BI semantic model
> - 🟠 Cross-validated — appears in both source AND TMDL
> - ⚪ Inherited — property comes from reference model
> - 🔵 Inferred — suggested by domain knowledge, no source evidence"

**Step 0c.5 — Detect subclass candidates from source data:**

Scan the Source Evidence Table for **discriminator patterns** — columns that
indicate type classification and suggest subclasses:

Look for:
- Columns with names containing `TYPE`, `CODE`, `KIND`, `CATEGORY`, `CLASS`
- TMDL dimension tables that classify a fact table (e.g., `d_UnitTypes` →
  `f_LoadDelivery`)
- Source reference/code tables with few distinct values
- Foreign keys to small lookup tables

Present discriminator findings:

> "**Subclass candidates from source data:**
>
> | # | Discriminator Column | Source | Links to | Distinct Values / Description | Subclass candidate? |
> |---|---|---|---|---|---|
> | 1 | `EQUIPMENTCODE` | RoRoNet.gooddetails2 | `equipmentcodes` table | Equipment type codes | ✅ Yes — suggests typed subclasses |
> | 2 | `TransportMediumTypeDescr` | TMDL.d_UnitTypes | Fact tables | Unit type descriptions | ✅ Confirms #1 |
> | 3 | `FULLEMPTYIND` | RoRoNet.gooddetails2 | — | Boolean flag | ❌ No — state, not type |
>
> Based on discriminator analysis, the source data supports these subclasses: …"

**Rules for the Source Evidence Table:**
- It MUST be built from actual file reads, not from memory or assumption
- Every row must cite the exact file and column name
- The table drives Checkpoint 1 (class proposals) and Checkpoint 3b (property proposals)
- If no source systems are available for this domain, document that explicitly
  and note that all proposals will be `[INFERRED]`
- **Completeness check (Gate 6a):** If TMDL files exist in
  `integration/sources/powerbi/`, the table MUST contain at least one row with
  🟡 TMDL evidence. A table with only 🟢 rows when TMDL is available means
  Step 0c.3 was skipped — go back and read the TMDL files.

### Step 0d — Trust-Priority Rule (ENFORCED)

When proposing classes or properties, sources are consulted and weighted in
this strict priority order:

| Priority | Source | What it provides | Label |
|---|---|---|---|
| 1 (highest) | **Bronze vocabulary columns** | What data actually exists in source systems | 🟢 Direct |
| 2 | **TMDL columns/relationships** | What the BI team already uses | 🟡 TMDL |
| 3 | **Reference model properties** | Structural authority (inherited props) | ⚪ Inherited |
| 4 (lowest) | **General domain knowledge** | LLM suggestions, industry norms | 🔵 Inferred |

**Enforcement rules:**

- A property is proposed WITHOUT an evidence label only if it appears at
  priority 1 or 2 (source or TMDL evidence).
- Reference model properties (priority 3) are always listed because they're
  inherited — but clearly marked as `⚪ Inherited`.
- Everything else (priority 4) gets the `🔵 [INFERRED]` tag and is presented
  in a separate section.
- When source data contradicts LLM assumptions, **source data wins**.
- When TMDL contradicts source data, **source data wins** (TMDL may be
  denormalized or outdated).
- When source data contradicts the reference model **structure**, the reference
  model wins for hierarchy but source data wins for cardinality and existence
  of columns.

**Impact on Checkpoints:**

- **Checkpoint 1 (Naming):** Class proposals must cite discriminator evidence
  from Step 0c.5
- **Checkpoint 2 (Subclass Justification):** Subclass proposals must cite
  discriminator columns or TMDL dimension tables as evidence
- **Checkpoint 3b (Property Design):** Properties are proposed in two tiers
  (see updated Checkpoint 3b below)

### Step 1 — Select the accelerator pack

Once reference models are imported, explore the available accelerator packs:

```bash
ls ontology-reference-models/accelerator-packs/
```

Each pack bundles ontologies for a business sector.  Ask the user:

> "Which accelerator pack / sector is closest to your business?  We will use
> this as a starting point and later trim what is not relevant."

### Step 1b — Review the blueprint and data-domains registry

Each accelerator pack includes a **client-hub-blueprint/** folder with:

- `BLUEPRINT.md` — recommended folder structure, import guidance, medallion
  architecture relationship, domain priority order, and "extend vs import"
  decision table.
- `data-domains.yaml` — structured registry of every domain with:
  - `owns` / `does_not_own` boundaries (used by Checkpoint 4)
  - exact `owl:imports` URIs for each domain
  - aligned reference model modules and standards

**Read both files** before starting any domain modeling:

```bash
cat ontology-reference-models/accelerator-packs/{pack}/client-hub-blueprint/BLUEPRINT.md
cat ontology-reference-models/accelerator-packs/{pack}/client-hub-blueprint/data-domains.yaml
```

Use the blueprint's **recommended sequence** (e.g., for logistics:
Party → MDM → Commercial → Booking → Consignment → ...) to guide which
domain to model first.

Use `data-domains.yaml` entries to:
- Pre-populate the correct `owl:imports` URIs for each domain TTL file
- Answer Checkpoint 4 ("does this class belong to this domain?") using the
  `owns` / `does_not_own` fields
- Identify which reference model modules provide parent classes for subclassing

### Step 2 — Map business data domains to reference ontologies

Before creating any files, build a **domain mapping table** together with the
user.  The goal is to create a complete map of all relevant data domains for the
business and align each one to a corresponding ontology from the reference
models.

| Business Data Domain | Reference Ontology | Status |
|---|---|---|
| Customer management | `ref:party.ttl` | ✅ Direct match |
| Invoicing | `ref:billing.ttl` | ✅ Direct match |
| Fleet management | — | ⚠️ No reference; model later |

**Rules for the mapping:**

1. **Avoid overlaps** — each business domain maps to exactly one reference
   ontology.  If two reference ontologies cover overlapping territory, choose
   one and note the exclusion.
2. **Do not invent new entities yet** — at this stage, stick strictly to what
   the reference models provide.  Custom entities come later, after the
   reference baseline is established.
3. **Flag gaps** — if a business domain has no matching reference ontology, mark
   it for later custom modeling.  Do not attempt to fill gaps with invented
   classes at this point.

### Step 2b — Overlap Resolution (MANDATORY when using multiple reference models)

When an accelerator pack imports from multiple reference model modules, the
**same concept** (class) may exist in more than one module. Before proceeding to
domain modeling, you MUST detect and resolve these overlaps.

**Step 2b.1 — Detect overlaps:**

Scan the imported reference models for classes that represent the same real-world
concept but appear in different modules. Present an overlap table:

> "I found the following concept overlaps across your imported reference models:
>
> | # | Concept | Candidate A | Candidate B | Recommended source |
> |---|---------|------------|------------|-------------------|
> | 1 | Shipment Event | BSP/Commercial | DCSA/Events | DCSA/Events |
> | 2 | Dimension (measurement) | BSP/Reference | MMT/Cargo | MMT/Cargo |
> | 3 | Weight | BSP/Reference | MMT/Cargo | MMT/Cargo |
> | 4 | Tariff Classification | BSP/Compliance | WCO/Customs | WCO/Customs |
> | … | … | … | … | … |
>
> Each concept must have exactly **one canonical source**. Do you agree with
> my recommendations, or would you like to override any?"

**Step 2b.2 — Apply resolution principles:**

Use these default principles to determine the recommended source. The user may
override with client-specific priorities:

| Principle | Application |
|-----------|-------------|
| **Authority first** | Use the most authoritative standard for the concept (IMO for vessels, WCO for customs, DCSA for shipping docs) |
| **Domain-centric** | Prefer the reference model closest to the client's core business (e.g., transport operator → prefer operational models over generic) |
| **Domain ownership** | Each class is "owned" by one reference module; others may reference it via imports |
| **No duplication** | Never subclass the same concept from two different parents — pick one canonical source |
| **Equivalence later** | Add `owl:equivalentClass` links between overlapping URIs only if cross-model querying is needed later |

**Step 2b.3 — Document in data-domains.yaml:**

Record overlap resolutions in the client hub blueprint's `data-domains.yaml`
under a new `overlaps` field per domain:

```yaml
domains:
  cargo:
    owns: [CargoItem, CargoLine, Dimension, Weight]
    does_not_own: [Vessel, Port, Container]
    imports:
      - https://referencemodels.kairos.cnext.eu/mmt/cargo
    overlaps:
      - class: Dimension
        candidates: [BSP/Reference, MMT/Cargo]
        resolved_to: MMT/Cargo
        rationale: "Physical dimensions relate to cargo handling in transport"
      - class: Weight
        candidates: [BSP/Reference, MMT/Cargo]
        resolved_to: MMT/Cargo
        rationale: "Weight is cargo-operational context"

  events:
    owns: [ShipmentEvent, MilestoneEvent]
    imports:
      - https://referencemodels.kairos.cnext.eu/dcsa/events
    overlaps:
      - class: ShipmentEvent
        candidates: [BSP/Commercial, DCSA/Events]
        resolved_to: DCSA/Events
        rationale: "DCSA event model is authoritative for shipping milestones"
```

**Rules:**
- Every overlap MUST be resolved before any domain modeling begins.
- Resolutions are recorded with a rationale so future modelers understand WHY.
- If the user cannot decide, flag it as `resolved_to: TBD` and revisit in Step 3
  (validate with business).
- During domain modeling (Step 5+), if a class is referenced that has an overlap
  resolution, always import from the `resolved_to` module.

### Step 3 — Validate with the business

Before proceeding to implementation, **suggest that the user validates the
domain mapping with business stakeholders**:

> "Before we start building, I recommend reviewing this domain mapping table
> with your business stakeholders.  This ensures we've selected the right data
> domain models and avoids rework later.  Do you want to finalize this mapping
> first, or proceed with what we have?"

This is a critical governance step — getting business sign-off on which
reference domains are in scope prevents scope creep and misalignment.

### Step 4 — Import via OWL catalog (Reference Model Enforced ONLY)

When incorporating **Kairos reference model** ontologies into the hub, **use
`owl:imports` via the catalog** — never copy or recreate the reference model
TTL files inside the hub.

> **Important:** This applies only to the **Reference Model Enforced** strategy
> (Kairos-managed reference models: small, < 50 classes, include `-defaults.ttl`).
> For large **external standards** (FIBO, DCSA, GS1, schema.org), use the default
> [Reference Model Inspired](#reference-model-inspired-default-strategy) strategy below.

The reference models ship with a `catalog-v001.xml` that maps logical URIs to
local file paths.  Your domain ontology imports the reference model by URI:

```turtle
@prefix : <https://contoso.com/ont/customer#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .

<https://contoso.com/ont/customer> a owl:Ontology ;
    rdfs:label "Customer Domain"@en ;
    owl:versionInfo "1.0.0" ;
    owl:imports <https://referencemodels.kairos.cnext.eu/party> .
```

**Rules (Reference Model Enforced — Kairos reference models):**

- ✅ **DO** use `owl:imports` referencing the catalog URI for Kairos reference
  ontologies (BSP, MMT, and other accelerator pack models).
- ✅ **DO** extend reference classes via `rdfs:subClassOf` when specialization
  is needed.
- ❌ **DO NOT** copy reference model `.ttl` files into `model/ontologies/`.
- ❌ **DO NOT** re-create reference model classes or properties in your domain
  files — reference them, don't duplicate them.
- ❌ **DO NOT** add new entities that aren't in the reference model until the
  reference baseline is validated and the user explicitly requests additions.
- ❌ **DO NOT** use `owl:imports` for large external standards (FIBO, DCSA, GS1,
  PROV-O, schema.org) — they are not projection-optimized and cause slow loading,
  unresolvable transitive imports, and whitelisting complexity. Use the Reference
  Model Inspired strategy instead.

### Step 5 — Trim and specialize

After the reference baseline is imported and validated:

1. **Remove what's not needed** — if a reference ontology contains classes that
   are out of scope, do NOT import them.  Import only the reference ontologies
   that match your domain mapping table.
2. **Specialize where needed** — extend reference classes with domain-specific
   subclasses or additional properties.
3. **Fill gaps** — for business domains with no reference model match (flagged
   in Step 2), now create custom ontology files following the standard modeling
   patterns below.
4. **Claim imported classes for projection (DD-021)** — by default, imported
   classes are NOT projected to silver or gold. To include them, add
   `kairos-ext:silverInclude true` / `kairos-ext:goldInclude true` per class
   in the appropriate extension file, or use `kairos-ext:silverIncludeImports true` /
   `kairos-ext:goldIncludeImports true` on the ontology URI to bulk-claim all
   first-level imported classes.

> **Principle:** Start broad with the accelerator pack, validate with the
> business, then narrow down.  It is easier to remove what you don't need than
> to discover missing domains later.

---

## TMDL Analysis (Legacy BI Input)

When existing TMDL files are available in `integration/sources/powerbi/`, analyze
them **before** domain modeling to extract business-validated concepts. TMDL is
treated as **legacy advisory input** — it informs decisions but the reference model
has structural priority.

### Step 1 — Read TMDL structure

Read the TMDL files and extract:

| TMDL artifact | What to extract | Modeling relevance |
|---|---|---|
| **Tables** (fact + dimension) | Table names, columns, data types | Class candidates and properties |
| **Relationships** | FK directions, cardinality | Object property candidates |
| **Measures (DAX)** | Measure name, expression, format | Gold-layer annotations (note for later) |
| **Hierarchies** | Drill paths (e.g., Year → Quarter → Month) | SubClassOf or part-of patterns |
| **Display folders** | Logical groupings | Domain boundary hints |
| **Column descriptions** | Business definitions | `rdfs:comment` candidates |

### Step 2 — Produce concept mapping table

Map each TMDL entity to its reference model equivalent:

> "Based on the TMDL files, here is the concept mapping:
>
> | # | TMDL Entity | Type | Reference Model Match | Action |
> |---|---|---|---|---|
> | 1 | `dim_Customer` | Dimension | `ref:TradeParty` | ✅ Use ref model; subclass if needed |
> | 2 | `dim_FreightCustomer` | Dimension | `ref:TradeParty` | 🔶 Specialize — create subclass |
> | 3 | `fact_Shipment` | Fact | `ref:Consignment` | ✅ Use ref model |
> | 4 | `dim_Route` | Dimension | _(no match)_ | 🆕 New local class needed |
> | 5 | `fact_Revenue` | Fact | _(no match)_ | 🆕 New local class needed |
> | 6 | `dim_Date` | Dimension | _(utility)_ | ⏭️ Skip — handled by gold layer |
>
> **Actions:**
> - ✅ = reference model covers this; use as-is
> - 🔶 = reference model has a parent class; create a subclass specialization
> - 🆕 = no reference model equivalent; create a new local class
> - ⏭️ = BI utility (date dim, bridge table); not an ontology class"

### Step 3 — Flag inconsistencies

When TMDL patterns disagree with the reference model, **always flag as a warning**
and **always follow the reference model**:

> "⚠️ **TMDL inconsistencies detected** (reference model takes priority):
>
> | # | Issue | TMDL pattern | Reference model pattern | Impact |
> |---|---|---|---|---|
> | 1 | Shipper cardinality | `dim_Shipper` joined M:N to `fact_Shipment` | `ref:hasShipper` is functional (1:N) | Follow ref model; review source data |
> | 2 | Flattened address | `dim_Customer.City`, `.Country` as columns | `ref:hasAddress → ref:Address` | Follow ref model (structured); flag for BI simplification later |
> | 3 | Missing relationship | No FK between `dim_Carrier` and `fact_Booking` | `ref:Booking hasCarrier ref:Carrier` | Ref model is correct; TMDL likely has a gap |
>
> These are logged in the session file as items to discuss with stakeholders."

**Rules for TMDL inconsistency handling:**

- ❌ Never restructure the ontology to match TMDL denormalization patterns
- ✅ Log every inconsistency in the session file "Source Alignment Warnings" section
- ✅ If the TMDL reveals a genuine **missing concept** in the ref model, that IS
  a valid input — create a local class
- ✅ TMDL measure expressions can be carried forward as `kairos-ext:measureExpression`
  in gold-ext.ttl — note them for later, don't let them drive ontology structure

### Step 4 — Tag classes for specialization

Based on the TMDL analysis, tag reference model classes that need subclassing:

> "The TMDL analysis suggests these **specializations** of reference model classes:
>
> | Reference class | TMDL evidence | Proposed subclass | Justification |
> |---|---|---|---|
> | `ref:TradeParty` | Has separate `dim_FreightCustomer`, `dim_ContractCustomer` | `:FreightCustomer`, `:ContractCustomer` | Different BI grain, different natural key |
> | `ref:Location` | Has `dim_Port`, `dim_Warehouse` | `:Port`, `:Warehouse` | Different properties, different lifecycle |
>
> Do you agree these warrant subclasses, or should some use the parent class directly?"

This feeds directly into [Checkpoint 2: Subclass Justification](#checkpoint-2-subclass-justification-mandatory-when-extending-reference-model).

---

## Source System Analysis (Reality Check)

When source system documentation is available in `integration/sources/`, analyze
it to confirm cardinalities, discover real data shapes, and identify attributes
not covered by the reference model.

### Step 1 — Read source system schemas

For each source system in `integration/sources/{system}/`, read:

| Material | What to extract | Priority |
|---|---|---|
| SQL DDL (CREATE TABLE) | Table structure, PKs, FKs, constraints | ⭐ Best — exact schema |
| API specs (OpenAPI/Swagger) | Endpoint resources, relationships, types | ⭐ Good — typed |
| Sample data (CSV/JSON) | Actual values, NULLability, patterns | 🔶 Useful — infer patterns |

### Step 2 — Map source entities to reference model

> "Source system `{system}` analysis:
>
> | # | Source Entity | Reference Model Match | Cardinality Match? | Extra Columns |
> |---|---|---|---|---|
> | 1 | `tbl_Customers` | `ref:TradeParty` | ✅ 1:1 | `credit_limit`, `payment_terms` |
> | 2 | `tbl_Shipments` | `ref:Consignment` | ✅ 1:1 | `internal_ref`, `priority_code` |
> | 3 | `tbl_ShipmentItems` | `ref:ConsignmentItem` | ⚠️ Source has M:N via junction | `damage_code` |
> | 4 | `tbl_Routes` | _(no match)_ | — | Full table is a gap |
>
> **Cardinality mismatches** require discussion — they may indicate:
> - The ref model is too restrictive (raise as feedback to ref model maintainers)
> - The source has denormalized data (common — model the semantic truth, not the source shape)
> - A junction table is needed (`kairos-ext:junctionTableName`)"

### Step 3 — Identify candidate properties

Extra columns in source systems that have no reference model equivalent are
candidates for new properties:

> "These source columns are not represented in the reference model:
>
> | # | Source column | Source table | Candidate property | Candidate domain |
> |---|---|---|---|---|
> | 1 | `credit_limit` | `tbl_Customers` | `:creditLimit` | `:Customer` (subclass of ref:TradeParty) |
> | 2 | `priority_code` | `tbl_Shipments` | `:priorityCode` | ref:Consignment or local subclass |
> | 3 | `damage_code` | `tbl_ShipmentItems` | `:damageCode` | ref:ConsignmentItem or local subclass |
>
> Should I add these as properties on the reference model class directly (if you
> control it) or on a local subclass?"

### Step 4 — Cross-validate with TMDL

If both TMDL and source system data are available, cross-validate:

> "Cross-validation: source system vs TMDL:
>
> | Concept | Source system | TMDL | Aligned? |
> |---|---|---|---|
> | Customer types | Single `tbl_Customers` table | Split into `dim_FreightCustomer`, `dim_ContractCustomer` | ⚠️ TMDL has more specialization |
> | Routes | `tbl_Routes` exists | `dim_Route` exists | ✅ Both agree — new class needed |
> | Carrier-Booking | FK exists in source | No relationship in TMDL | ⚠️ TMDL has gap |
>
> Where source and TMDL agree on a gap, this strongly confirms a new class is needed."

---

## Standard model alignment

When a user wants to model a domain based on — or aligned with — an industry
standard ontology (FIBO, DCSA, GS1, PROV-O, schema.org, etc.):

### Step 1 — Confirm which standard

Ask the user to confirm:
- The exact standard or vocabulary (name + version/edition if relevant).
- Whether the standard is available as a **Kairos reference model** (Enforced-eligible)
  or is an **external standard** (Inspired — the default).

### Step 2 — Determine the strategy

| Strategy | When to use | Approach |
|----------|-------------|----------|
| **Reference Model Inspired** (default) | All external standards AND any reference model where you want selective adoption. This is the default — use unless overridden. | Model locally + selective pattern adoption + SKOS alignment file |
| **Reference Model Enforced** (override) | Kairos-managed reference models in `ontology-reference-models/`. Small (< 50 classes), projection-optimized, ships `-defaults.ttl`. | `owl:imports` + `rdfs:subClassOf` + DD-021 whitelist + DD-023 defaults |

> **Default rule:** Always start with **Reference Model Inspired** unless the user
> explicitly requests Enforced and the reference model meets all eligibility criteria.

**Enforced eligibility** (ALL must be true):
- Found in `ontology-reference-models/accelerator-packs/`
- Has a catalog entry mapping its URI to a local `.ttl` file
- Typically < 50 classes, focused on a specific domain
- Ships `*-silver-defaults.ttl` (DD-023 compatible)
- No transitive imports pulling in unrequested concepts
- Examples: BSP-Party, BSP-Billing, MMT modules

**Inspired indicators** (anything not meeting Enforced criteria):
- Large (100+ classes) or depends on large transitive imports
- Externally maintained — versioned independently of your hub
- Not projection-optimized (no `kairos-ext:` annotations, no `-defaults.ttl`)
- Examples: FIBO, DCSA, GS1, PROV-O, schema.org

> **Rule of thumb:** If importing the standard would add > 50 classes to the
> merged graph that you'll never project, use Reference Model Inspired (the default).

### Step 3 — Alignment patterns

#### Reference Model Enforced: Extend a Kairos reference class

```turtle
@prefix ref-party: <https://referencemodels.kairos.cnext.eu/party#> .

<https://contoso.com/ont/customer> a owl:Ontology ;
    owl:imports <https://referencemodels.kairos.cnext.eu/party> .

:PremiumCustomer rdfs:subClassOf ref-party:Customer ;
    rdfs:label "Premium Customer"@en ;
    rdfs:comment "A high-value customer — extends the reference model."@en .
```

#### Reference Model Inspired (default strategy)

**Do NOT import the external standard.** Instead:

1. Model your classes locally (self-contained, projection-ready) and add
   `rdfs:seeAlso` pointing to the reference model class URI for traceability:
   ```turtle
   :LegalEntity a owl:Class ;
       rdfs:subClassOf :Party ;
       rdfs:label "Legal Entity"@en ;
       rdfs:comment "A legal entity / company."@en ;
       rdfs:seeAlso <https://spec.edmcouncil.org/fibo/ontology/BE/LegalEntities/LegalPersons/LegalPerson> .
   ```

2. Selectively adopt patterns from the reference model when they create a
   **structurally different silver schema** (new table or new FK relationship).
   Always include `rdfs:seeAlso` linking back to the source pattern:
   ```turtle
   :Identifier a owl:Class ;
       rdfs:label "Identifier"@en ;
       rdfs:comment "Multi-identifier support — separate silver table."@en ;
       rdfs:seeAlso <https://spec.edmcouncil.org/fibo/ontology/FND/Arrangements/Identifiers/Identifier> .
   ```

**Why `rdfs:seeAlso`:**
- Part of core RDFS — no extra imports needed
- Non-committal — no logical entailments (unlike `owl:equivalentClass`)
- Machine-readable — tooling can resolve the URI to check reference model alignment
- Loaded with the domain ontology — visible during silver/gold design sessions

**Silver structural difference criterion (DD-032):** Only adopt a reference model
pattern as a local class when it produces a structurally different silver output
(new table or new FK relationship). If a pattern merely renames or reclassifies
without changing the silver schema, do not create a local class for it.

#### Reuse a standard property by reference (documentation-only)

```turtle
:carrierSCAC a owl:DatatypeProperty ;
    rdfs:domain :Carrier ;
    rdfs:range xsd:string ;
    rdfs:label "Carrier SCAC"@en ;
    rdfs:comment "Standard Carrier Alpha Code as defined by DCSA."@en ;
    rdfs:seeAlso <https://dcsa.org/standards/> .
```

### Known standards and their recommended strategy

| Standard | Domain | Strategy | Rationale |
|----------|--------|----------|-----------|
| BSP-Party | Party / customer | Enforced | Kairos-managed, small, has defaults |
| BSP-Billing | Invoicing | Enforced | Kairos-managed, small, has defaults |
| MMT | Maritime / logistics | Enforced | Kairos-managed, small, has defaults |
| FIBO | Financial / legal entities | **Inspired** | Large (1000+ classes), deep transitive imports |
| DCSA | Shipping / container logistics | **Inspired** | Large, externally maintained |
| GS1 | Supply chain / product IDs | **Inspired** | Large, externally maintained |
| PROV-O | Data provenance | **Inspired** | W3C standard, small but no projection value |
| schema.org | General-purpose web semantics | **Inspired** | Very broad vocabulary |
| Dublin Core (DC) | Metadata | Enforced or Inspired | Small enough to import safely if needed |

> **Rule:** Never hardcode a downloaded copy of a standard model inside the hub
> repo.  For Enforced, reference it via the catalog. For Inspired, model locally
> and add `rdfs:seeAlso` on each inspired class.

---

## Business Alignment Checkpoints

These checkpoints are **mandatory** when modeling new domains or creating new
classes. They ensure business alignment before any TTL is generated. Skip them
only in [Quick-edit mode](#quick-edit-mode).

### Checkpoint 1: Naming Alignment (MANDATORY before creating any class)

**Prerequisite:** Step 0c (Source Evidence Table) must be complete before
reaching this checkpoint. Class proposals must be grounded in source evidence.

For every new class, **explicitly cite the source evidence and ask**:

> "I'm proposing the OWL class name `:{ProposedName}`.
>
> **Source evidence for this class:**
> - Discriminator: `{column}` in `{table}` ({system}) — values suggest this type
> - TMDL confirmation: `{tmdl_table}` dimension exists (if applicable)
> - Reference model parent: `{ref:ParentClass}`
>
> **Business context check:**
> - What do your users/business call this? (e.g., 'cargo line', 'shipment item', 'goods entry')
> - Will this name be clear on a Power BI dashboard or report?
> - Does any source system already use a term for this?
>
> **Reference model context:**
> - The reference model calls this `{refmodel:ClassName}` — our class will extend it via `rdfs:subClassOf`.
> - **Full inheritance chain:** `:{ProposedName}` → `{ref:Parent}` → `{ref:Grandparent}` → …
> - **ALL inherited properties (resolve the full chain):**
>   | Property | Defined on | Type | Semantic meaning |
>   |----------|-----------|------|-----------------|
>   | `{ref:prop1}` | `{ref:Parent}` | `xsd:string` | {what it represents} |
>   | `{ref:prop2}` | `{ref:Grandparent}` | `xsd:dateTime` | {what it represents} |
>   | … | … | … | … |
>
> Proposed name: `:{ProposedName}` — would you like to keep this or rename?"

If a class has **no source evidence** (no discriminator column, no TMDL
dimension, no source table), it must be explicitly marked:

> "⚠️ `:{ProposedName}` — **[INFERRED]** — No source evidence found for this
> class. It is suggested based on domain knowledge / reference model structure.
> Do you confirm this class exists in your business?"

**Naming decision table** (present for each class):

| Consideration | Guideline |
|---|---|
| **Matches business language?** | Use the term people say in meetings |
| **Distinct from reference model parent?** | Only subclass if there's real semantic difference |
| **Clear in BI/reports?** | Would a business user understand `dim_{snake_case_name}`? |
| **Consistent across domains?** | Same pattern as other domain classes |

**Multi-source naming context** (when source/TMDL inputs are available):

> | Source | Name for this concept | Notes |
> |--------|----------------------|-------|
> | Reference model | `ref:{ClassName}` | Canonical structural name |
> | TMDL | `dim_{tmdl_name}` / `fact_{tmdl_name}` | Legacy BI name — may differ |
> | Source system | `tbl_{source_name}` | Technical source name |
> | Business term | _{what stakeholders say}_ | From user |
> | **Proposed** | `:{ProposedName}` | Aligned with reference model |
>
> If TMDL/source names differ significantly from the reference model, note this
> in the session file — it may indicate a naming gap or a specialization need.

**TMDL cross-reference** (MANDATORY when TMDL inputs exist — Gate 6a):

After proposing all classes for the domain, present a summary cross-reference:

> "**TMDL cross-reference for this domain:**
>
> | Proposed class | Matching TMDL table | Notes |
> |---|---|---|
> | `:FreightCustomer` | `dim_FreightCustomer` | Direct match — confirms class |
> | `:Route` | `dim_Route` | Confirms new local class |
> | `:BookingEvent` | _(none)_ | New concept not in legacy BI |
>
> Classes with no TMDL match are fine — they may be new concepts or ref model
> structures not yet in the BI layer."

If TMDL files exist but this table is missing, it's a Gate 6 violation.

### Checkpoint 2: Subclass Justification (MANDATORY when extending reference model)

Before creating any `rdfs:subClassOf` relationship, validate:

> "You want `:{YourClass} rdfs:subClassOf {ref:ParentClass}`.
>
> **Subclass vs. direct use — which applies?**
>
> | Create subclass when... | Use parent class directly when... |
> |---|---|
> | You need a discriminator in silver | It's the same concept, just with more properties |
> | Multiple variants exist (e.g., AirCargo, SeaCargo) | Only one kind in practice |
> | Different lifecycle or natural key | Same lifecycle as parent |
> | Business has a distinct name for it | Just adding fields to the standard class |
>
> **Does `:{YourClass}` pass at least one 'create subclass' criterion?**"

If the user cannot justify the subclass, suggest:
```turtle
# Instead of subclassing, extend the parent directly:
:myNewProperty rdfs:domain ref:ParentClass ;
    rdfs:range xsd:string .
```

**TMDL/Source evidence for subclassing** (when available):

When TMDL or source system data suggests specialization, present the evidence:

> "**Evidence from available inputs:**
>
> | Input | What it shows | Supports subclass? |
> |-------|--------------|-------------------|
> | TMDL | Separate `dim_FreightCustomer` table with extra columns | ✅ Yes — distinct grain |
> | Source | Single `tbl_Customers` with `customer_type` discriminator column | ✅ Yes — discriminator exists |
> | Reference model | `ref:TradeParty` as general parent | ✅ Yes — designed for specialization |
>
> ⚠️ **Caution:** TMDL having separate tables does NOT automatically justify a
> subclass. The TMDL may be denormalized for performance. Always validate
> against the 'create subclass' criteria above."

### Checkpoint 3: Property Design — Flat vs. Structured

When a property could be modeled as either flat columns or a structured object:

> "The reference model uses a **structured** pattern:
> ```
> CargoItem → hasWeight → Weight (weightValue + weightUnit)
> ```
>
> For your use case, I can model this as:
>
> | Option | Pattern | Silver result | Pros | Cons |
> |---|---|---|---|---|
> | A: Flat | `grossWeightKg : xsd:decimal` | Single column, unit in name | Simple, no joins | Loses unit flexibility |
> | B: Structured | `hasWeight → Weight` | Extra table or inlined | Flexible, multi-unit | More complex |
> | C: Hybrid | Flat + `originalWeightUnit` | Two columns | Audit trail + simple | Slight redundancy |
>
> Which approach fits your business needs?"

### Checkpoint 3b: Property Reuse Check (MANDATORY before defining properties)

Before defining **any** new datatype or object property on a class that extends
a reference model class, you MUST resolve the full inheritance chain and present
all available inherited properties. This check also applies to **named
individuals** (enumerations) and **sub-property relationships**.

**IMPORTANT: Two-tier property presentation (Gate 6 enforcement)**

When presenting new property proposals, you MUST separate them into two tiers:

> **Tier 1 — Source-evidenced properties** (from Source Evidence Table):
>
> | # | Proposed Property | Source Column | Source Table | System | Data Type | Confidence |
> |---|---|---|---|---|---|---|
> | 1 | `mafiNumber` | `MAFINR` | `gooddetails2` | RoRoNet | nvarchar(50) → xsd:string | 🟢 Direct |
> | 2 | `licensePlate` | `LICENSEPLATE` | `equips` | RoRoNet | nvarchar(50) → xsd:string | 🟢 Direct |
> | 3 | `verifiedGrossMass` | `VGM` | `gooddetails2` | RoRoNet | decimal → xsd:decimal | 🟢 Direct |
>
> **Tier 2 — Inferred properties** (domain knowledge, no source evidence):
>
> | # | Proposed Property | Reasoning | Confidence |
> |---|---|---|---|
> | 1 | `isAccompanied` | Standard RoRo concept; not found in source columns | 🔵 Inferred |
> | 2 | `requiresSpecialPermit` | Common for oversized cargo; no source column found | 🔵 Inferred |
>
> ⚠️ **Tier 2 properties** may already exist under different names in the
> source, or may not be relevant to this client. Discuss before including.

**Rules for tiered presentation:**
- Tier 1 is always presented FIRST and forms the default proposal
- Tier 2 is presented SECOND and clearly separated
- The user must explicitly opt-in to Tier 2 properties
- If a Tier 2 property is confirmed by the user, record their statement as the
  evidence source in the session file
- Never mix Tier 1 and Tier 2 properties in a single undifferentiated list

**Step 1 — Resolve the inheritance chain:**

Programmatically (or by reading the imported ontology files) build the full
parent chain:

```
:{YourClass} → ref:Parent → ref:Grandparent → owl:Thing
```

**Step 2 — List all inherited properties:**

> "Before defining properties for `:{YourClass}`, here are ALL properties
> already available via inheritance:
>
> | # | Property | Defined on | Range | Semantic meaning |
> |---|----------|-----------|-------|-----------------|
> | 1 | `ref:partyName` | `ref:TradeParty` | `xsd:string` | Legal or trading name of the party |
> | 2 | `ref:partyIdentifier` | `ref:TradeParty` | `xsd:string` | Business identifier (e.g., KVK, DUNS) |
> | 3 | `ref:contactEmail` | `ref:Party` | `xsd:string` | Primary contact email address |
> | … | … | … | … | … |

**Step 2b — List all named individuals (enumerations) from imports:**

If the reference model defines named individuals (e.g., status values,
type codes), list them before allowing new enum creation:

> "The reference model already defines these named individuals relevant to
> `:{YourClass}`:
>
> | # | Individual | Class | Semantic meaning |
> |---|-----------|-------|-----------------|
> | 1 | `ref:StatusActive` | `ref:PartyStatus` | Party is active and tradeable |
> | 2 | `ref:StatusInactive` | `ref:PartyStatus` | Party is suspended |
> | … | … | … | … |
>
> Do any of your proposed status/type values duplicate these?"

**Step 3 — Gate new property creation:**

> "You proposed these new properties: `{list}`.
>
> **Reuse check:**
>
> | Proposed property | Equivalent inherited property? | Recommendation |
> |---|---|---|
> | `customerName` | ✅ `ref:partyName` already covers this | **REUSE** — do not create |
> | `customerTier` | ❌ No equivalent exists | **CREATE** — genuinely new |
> | `contactPhone` | ✅ `ref:contactPhone` already exists | **REUSE** — do not create |
>
> I recommend reusing the inherited properties where marked. Do you agree,
> or do you need a separate property with different semantics?"

**Step 3b — Check for sub-property relationships:**

When a new property is genuinely needed but *narrows* an existing inherited
property, use `rdfs:subPropertyOf` instead of creating an unrelated property:

> "Your proposed property `customerLegalName` is a specialization of the
> inherited `ref:partyName`. Should I model it as:
>
> | Option | Pattern | Implication |
> |---|---|---|
> | A: Sub-property | `customerLegalName rdfs:subPropertyOf ref:partyName` | Inherits domain/range semantics; reasoners link them |
> | B: Independent | `customerLegalName` (standalone) | No link to `partyName`; may cause confusion |
>
> **Recommendation:** Use sub-property (Option A) when the new property
> represents a *narrower meaning* of the parent property."

**Rules:**
- If an inherited property covers the same semantic meaning, default to REUSE.
- Only create a new property if the user explicitly confirms it has **different
  semantics** from all inherited properties (e.g., different cardinality,
  different business context, or more specific meaning).
- If a new property *narrows* an inherited one, use `rdfs:subPropertyOf`.
- If named individuals already exist for a concept, reuse them rather than
  creating domain-specific duplicates.
- Document the reuse decision in the session file under "Design Decisions."

### Checkpoint 4: Domain Boundary Verification

Before modeling any class, verify it belongs to this domain by checking the
`data-domains.yaml` entry for the current domain (found in the accelerator pack's
`client-hub-blueprint/` folder):

> "Before I add `:{ClassName}` to `{domain}.ttl`:
> - ✅ This domain **owns**: _{`owns` field from data-domains.yaml}_
> - 🚫 This domain **does not own**: _{`does_not_own` field from data-domains.yaml}_
>
> Does `:{ClassName}` fall within the `owns` scope?"

### Checkpoint 5: Inheritance Impact Review

After every 3-5 classes are confirmed, pause and show:

> "**Inheritance summary so far:**
>
> ```
> ref:ParentA
>   └── your:ChildA (inherits: prop1, prop2, prop3)
>       └── adds: newProp1, newProp2
>
> ref:ParentB
>   └── your:ChildB (inherits: propX, propY)
>       └── adds: newPropZ
> ```
>
> **Silver projection preview:**
> These will become tables: `silver_{domain}.{table1}`, `silver_{domain}.{table2}`
>
> **Inheritance note:** If a parent class is NOT projected separately, its
> properties are automatically inherited by child tables. If the parent IS
> projected, S3 flattening merges the child into the parent table.
>
> Does this structure make sense from a data warehouse perspective?"

**Source/TMDL cross-check** (when available):

After showing the inheritance summary, cross-reference with source/TMDL inputs:

> "**Cross-check against available inputs:**
>
> | Your class | Source system | TMDL | Alignment |
> |---|---|---|---|
> | `:FreightCustomer` | `tbl_Customers` (filtered by type) | `dim_FreightCustomer` | ✅ All agree |
> | `:Route` | `tbl_Routes` | `dim_Route` | ✅ All agree (new local class) |
> | `:Booking` | `tbl_Bookings` | — (not in TMDL) | ⚠️ TMDL gap — class is still valid per ref model |
>
> **Cardinality notes from source:**
> - `tbl_Bookings` → `tbl_Customers`: FK exists (1:N confirmed)
> - `tbl_Shipments` → `tbl_Routes`: FK exists but nullable (optional relationship)
>
> Any cardinality surprises to discuss?"

---

## Class design

- Every class is declared as `owl:Class` with `rdfs:label` and `rdfs:comment`.
- Use inheritance (`rdfs:subClassOf`) for IS-A relationships.
- Prefer flat hierarchies (max 3 levels deep) for business ontologies.
- Abstract base classes are useful for shared properties (e.g., `AuditableEntity`).

## Property design

- **Datatype properties** (`owl:DatatypeProperty`): link a class to a literal value.
  Common ranges: `xsd:string`, `xsd:integer`, `xsd:decimal`, `xsd:boolean`, `xsd:dateTime`, `xsd:date`.
- **Object properties** (`owl:ObjectProperty`): link two classes.
  Always specify `rdfs:domain` and `rdfs:range`.
- Use `rdfs:label` for human-friendly names and `rdfs:comment` for descriptions.

## Naming conventions

- **Classes**: PascalCase — `Customer`, `SalesOrder`, `VIPCustomer`.
- **Properties**: camelCase — `customerName`, `orderDate`, `belongsToCustomer`.
- **Namespaces**: Use HTTPS URIs matching the hub's namespace base —
  `https://<company-domain>/ont/<domain>#` (e.g., `https://contoso.com/ont/customer#`).

## Common patterns

### Enumeration (fixed set of values)
```turtle
:OrderStatus a owl:Class ;
    rdfs:label "Order Status" ;
    rdfs:comment "Possible states of an order" .
:statusPending a :OrderStatus .
:statusConfirmed a :OrderStatus .
:statusShipped a :OrderStatus .
```

### Composition (HAS-A relationship)
```turtle
:hasLineItem a owl:ObjectProperty ;
    rdfs:domain :Order ;
    rdfs:range :LineItem ;
    rdfs:label "has line item" .
```

### Metadata properties
```turtle
:createdAt a owl:DatatypeProperty ;
    rdfs:domain :AuditableEntity ;
    rdfs:range xsd:dateTime ;
    rdfs:label "Created At" .
:modifiedAt a owl:DatatypeProperty ;
    rdfs:domain :AuditableEntity ;
    rdfs:range xsd:dateTime ;
    rdfs:label "Modified At" .
```

## Ontology declaration

Every .ttl file MUST start with an ontology declaration:
```turtle
@prefix : <https://contoso.com/ont/domain#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<https://contoso.com/ont/domain> a owl:Ontology ;
    rdfs:label "Domain Ontology"@en ;
    rdfs:comment "Description of this domain"@en ;
    owl:versionInfo "1.0.0" .
```

---

## Extension annotations reference

> **Full reference:** The complete annotation tables for `kairos-ext:` (silver and
> gold) and `kairos-map:` (mapping) annotations are maintained in the
> **kairos-design-silver** and **kairos-design-gold** skills.
> Invoke those skills when you need the detailed annotation reference.

**Key principle:** Domain ontology files (`.ttl`) define the *what* (classes,
properties, relationships). Extension files define the *how* (projection behavior).
Never mix `kairos-ext:` annotations into domain ontology files.

### File layout

```
model/
  ontologies/
    client.ttl              ← pure domain model (no kairos-ext: annotations)
  extensions/
    client-silver-ext.ttl   ← silver layer projection annotations
    client-gold-ext.ttl     ← gold layer projection annotations
  mappings/
    adminpulse-to-client.ttl ← source-to-domain SKOS mappings + kairos-map: annotations
```

### Quick annotation checklist (for modeling awareness)

When finishing a domain model, remind the user that extension files will need:

| Layer | What to annotate | Key annotations |
|-------|-----------------|-----------------|
| Silver | SCD type, natural keys, FK relationships | `scdType`, `naturalKey`, `silverForeignKey` |
| Gold | Fact vs dimension, measures, hierarchies | `goldTableType`, `measureExpression`, `hierarchyName` |
| Mapping | Source-to-domain column transforms | `transform`, `mappingType`, `filterCondition` |

### Design rules for extensions

1. **Separate concerns**: domain ontology defines the *what*; extension files define the *how*.
2. **One extension file per layer per domain**: `client-silver-ext.ttl`,
   `client-gold-ext.ttl`. Never mix silver and gold annotations in one file.
3. **Re-import the domain namespace**: extension files must `@prefix` and reference
   the same domain namespace as the ontology they extend.
4. **Validate after editing**: run `kairos-ontology validate` to ensure the
   extension file parses correctly.
5. **Test the projection**: run `kairos-ontology project --target silver` (or `dbt`,
   `gold`) and inspect the generated output to verify annotations took effect.

---

## Completion: Final Configuration Report

When the user confirms all classes and properties for a domain, generate a final
report. Save to `ontology-hub/.sessions-design/modeling-{domain}-FINAL-{YYYY-MM-DD}.md`:

```markdown
# Modeling Configuration Report: {Domain Name}

**Completed:** {datetime}
**Domain file:** `model/ontologies/{domain}/{domain}.ttl`
**Ontology version:** 1.0.0

## Summary

| Metric | Count |
|--------|-------|
| Classes defined | N |
| Properties defined | N |
| Reference model imports | N |
| Subclass relationships | N |
| Design decisions made | N |

## Naming Map (Business ↔ Technical)

| Business Term | OWL Class/Property | Reference Parent | Silver Table/Column |
|---|---|---|---|
| {what users say} | :{TechnicalName} | ref:{Parent} | silver_{domain}.{table} |

## Inheritance Tree

{full tree showing all classes and their parents}

## Design Decisions Audit Trail

| # | Decision | Choice | Rationale | Stakeholder |
|---|----------|--------|-----------|-------------|
| 1 | {question} | {choice} | {reason} | {who confirmed} |

## Open Items for Follow-up

- {any deferred decisions}
- {any items that need silver extension work}

## Next Steps

- [ ] Create silver extension (`model/extensions/{domain}-silver-ext.ttl`)
- [ ] Create source mappings — invoke **kairos-design-mapping** skill to interactively
  map source columns to domain properties (`model/mappings/{source}-to-{domain}.ttl`)
- [ ] Run `python -m kairos_ontology validate`
- [ ] Run `python -m kairos_ontology project --target silver`
```

---

## Anti-patterns to avoid

- Do NOT create classes without labels or comments.
- Do NOT use `xsd:string` for everything — use appropriate types.
- Do NOT create circular subclass hierarchies.
- Do NOT mix domains in a single .ttl file — one domain per file.
- Do NOT use `http://` in namespace URIs — always use `https://`.
- Do NOT forget to add new domains to `_master.ttl` and the hub README table.
- Do NOT put projection annotations directly in the domain ontology `.ttl` —
  use separate extension files.

### Anti-patterns this skill's checkpoints prevent

| Problem | How prevented |
|---|---|
| Naming mismatch (CargoLine vs GoodsItem vs CargoItem) | Checkpoint 1 forces explicit naming discussion |
| Unnecessary subclassing | Checkpoint 2 requires justification |
| Flat vs structured confusion | Checkpoint 3 shows trade-offs explicitly |
| Redundant property (e.g., `customerName` when `partyName` is inherited) | Checkpoint 3b forces property reuse check before defining new properties |
| **Invented properties from LLM knowledge** | **Gate 6 + Tier system requires source evidence before proposals** |
| **Subclasses without discriminator evidence** | **Step 0c.5 requires discriminator column citation** |
| Same concept imported from two reference models | Step 2b overlap resolution picks one canonical source |
| Modeling concepts outside domain boundary | Checkpoint 4 verifies ownership |
| Silver layer surprises | Checkpoint 5 previews projection impact |
| Lost context between sessions | Session files persist all decisions |
| No audit trail for design choices | Final report captures everything |

---

## Related skills

| When you need | Invoke |
|---|---|
| Silver/gold extension annotations (full reference tables) | **kairos-design-silver** / **kairos-design-gold** |
| Source-to-domain column mapping | **kairos-design-mapping** |
| Run projections (dbt, silver DDL, Power BI) | **kairos-execute-project** |
| Validate ontology syntax + SHACL | **kairos-execute-validate** |
| Create bronze vocabulary from source docs | **kairos-design-source** |
| Hub status / what's missing | **kairos-diagnose-status** |
