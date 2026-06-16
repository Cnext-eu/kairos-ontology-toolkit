---
name: kairos-design-gold
description: >
  Expert guide for designing gold-layer extension annotations (fact/dimension
  types, DAX measures, hierarchies, RLS) and understanding Power BI projection
  output. Targets DirectLake on Microsoft Fabric Warehouse.
---

# Kairos Medallion Gold Skill

You are an expert at generating Power BI star-schema models from OWL ontologies
using the Kairos gold-layer projection.

## Architecture Context

The Kairos projection system uses a three-layer rule architecture:

```
R1-R16: Common Annotation Rules (kairos-ext:)
    ├── S1-S8: Silver Fabric Warehouse (implemented)
    └── G1-G8: Gold Power BI / DW (implemented)
```

The silver layer produces canonical, normalised tables. The gold layer reshapes
them into a **dimensional star schema** optimised for Power BI DirectLake queries
on Microsoft Fabric Warehouse.

---

## Interaction Modes & Decision Packets (Slice 7 — thin-chat)

> **Concise mode is the default.** This skill is an *orchestrator*: the work and
> the verbose detail live in a **versioned artifact** (the gold extension file
> `model/extensions/{domain}-gold-ext.ttl`), **not** in a long chat transcript.
> Chat carries only the **decisions**. See `kairos-help` §11 (*Skill interaction
> modes & decision packets*) for the canonical definition shared by every
> `kairos-design-*` skill.

### Modes

| Mode | What it does | When to use |
|---|---|---|
| `guided` | Full step-by-step explanation at every gold design decision (the pre-Slice-7 behavior). | First-time users; teaching / onboarding. |
| `concise` **(default)** | One compact **decision packet** per decision (fact/dim classification, measure, hierarchy, RLS) — summary, options, artifact path. Methodology stated **once**, then linked. | Day-to-day gold design by someone who knows the flow. |
| `silent-artifact` | Writes annotations straight into the `*-gold-ext.ttl` with minimal chat; surfaces **only blocking decisions**. | Trusted fast iteration; review via the PR diff. |
| `review-only` | **No writes** — analyses the model and emits decision packets / findings only. | Audits, second opinions, dry runs. |

Switch modes any time (*"use guided mode"*, *"concise mode"*, …); the active
mode is recorded in the session file so it persists across turns.

### Decision-packet format

```yaml
# 🧩 Decision packet — G1: Star-schema classification (Invoice)
summary: Invoice is a fact (additive TotalAmount); Client/Date are dimensions.
requires_decision: yes        # yes → STOP and wait for the user (never auto-approve)
options:
  - A) goldTableType "fact" + measure Total Revenue = SUM(TotalAmount) (recommended)
  - B) keep as dimension (no additive measures)
artifact: model/extensions/invoice-gold-ext.ttl
mode: concise
```

Render only the packet in chat; push full reasoning to the artifact / session
file.

### Shared thin-chat rules (identical across all `kairos-design-*` skills)

1. **State methodology once per session, then link** to `kairos-help` instead of
   re-explaining the G1–G8 rules or the dbt-vs-semantic-model split.
2. **One decision packet per class / measure / hierarchy** — don't bundle
   decisions or pad packets with prose.
3. **End each phase with PR-ready diffs**, not a chat recap: list the changed
   files (`{domain}-gold-ext.ttl`) and say *"review in the GitHub PR"*.
4. **Artifacts over transcript** — rationale and rejected options go into the
   extension file / session file, never only into chat.
5. **No-autopilot preserved.** A `requires_decision: yes` packet always waits for
   an explicit user response; no mode (incl. `silent-artifact`) auto-confirms a
   blocking design decision.

> **C10 guard:** these modes are presentation rules for *this* skill's existing
> decisions — they do **not** add a new orchestration engine. The actual gold
> generation is the deterministic `project --target powerbi` command (optionally
> seeded by `tmdl-to-gold-ext`); prefer it over more prose here.

## Gold Rules G1-G8

| Rule | Name | Description |
|------|------|-------------|
| G1 | Star schema classification | Auto-classify tables as fact/dimension/bridge by relationship patterns. Override via `goldTableType`. |
| G2 | dim_/fact_/bridge_ prefixes | Gold tables use dimensional naming conventions. |
| G3 | SCD Type 2 dimensions | Dimensions with `scdType "2"` get valid_from/valid_to/is_current. Facts never get SCD columns. |
| G4 | GDPR row-level security | GDPR satellite → secured dimension + RLS role in TMDL. |
| G5 | Class-per-table inheritance | OWL subclass hierarchies projected as separate tables with shared PK/FK to parent (default). Opt into discriminator flattening via `goldInheritanceStrategy "discriminator"`. |
| G6 | Reference → shared dimension | Reference data promoted to `dim_` shared dimension. |
| G7 | Aggregate tables | (Deferred) Pre-aggregated fact tables. |
| G8 | Power BI optimised types | INT surrogate keys, BIT for booleans, VARCHAR instead of STRING. |

## G1 — Star Schema Classification

**Automatic heuristic:**
- Classes with ≥2 outgoing FK object properties → **fact**
- Classes referenced by other classes → **dimension**
- `isReferenceData = true` → always **dimension** (G6)
- `gdprSatelliteOf` set → **dimension** (G4)

**Override:** Set `kairos-ext:goldTableType` to `"fact"`, `"dimension"`, or `"bridge"`.

**Aggressive FK generation:** When `goldTableType "fact"` is set explicitly, the
projector generates FK columns for **all** object properties — not just those
marked as `owl:FunctionalProperty` or with `maxCardinality 1`. This is because
fact tables almost always need FK columns to their related dimensions. Auto-classified
facts (detected via the ≥2 FK heuristic) still use the standard cardinality filter.

## G8 — DirectLake Optimised Types

| Silver (S1) | Gold (G8) | Reason |
|-------------|-----------|--------|
| STRING SK (UUID) | INT SK (IDENTITY) | Better V-Order compression |
| BOOLEAN | BIT | Power BI prefers BIT |
| STRING | VARCHAR(256) | Bounded length for VertiPaq |
| DOUBLE | FLOAT | Fabric Warehouse type |

## Running the Projection (handoff)

Once your gold extension annotations are complete, generate the artifacts by
invoking the **kairos-execute-project** skill with target `powerbi`.

> **Design/Execute separation (DD-033):** This skill handles annotation *design*.
> The **kairos-execute-project** skill handles *generation*. If you need to
> iterate on outputs, edit the extension file here, then invoke projection again.

## Extension File

Create `{domain}-gold-ext.ttl` in `model/extensions/` to annotate classes:

```turtle
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
@prefix domain: <https://mycompany.com/ontology/customer#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .

<https://mycompany.com/ontology/customer-gold-ext>
    a owl:Ontology ;
    owl:imports <https://mycompany.com/ontology/customer> .

<https://mycompany.com/ontology/customer>
    kairos-ext:goldSchema "gold_customer" ;
    kairos-ext:generateDateDimension "true"^^xsd:boolean .

domain:Customer
    kairos-ext:goldTableType "dimension" ;
    kairos-ext:scdType "2" .

domain:Order
    kairos-ext:goldTableType "fact" ;
    kairos-ext:partitionBy "_load_date" .

domain:Country
    kairos-ext:isReferenceData "true"^^xsd:boolean ;
    kairos-ext:scdType "1" .

domain:hasOrderAmount
    kairos-ext:measureExpression "SUM([order_amount])" ;
    kairos-ext:measureFormatString "$#,##0.00" .
```

## Seeding gold from Power BI (fit-gap)

When the engagement already has an existing Power BI estate, two **advisory** CLI
commands (DD-EL-7) let you use it as *evidence, not authority* — they never approve
claims or auto-apply gold annotations.

- **`kairos-ontology tmdl-to-gold-ext SOURCE --domain {domain}`** seeds a
  **candidate** gold extension TTL (default
  `model/extensions/{domain}-gold-ext.candidate.ttl`) from existing Power BI. It emits
  `kairos-ext:measureExpression` + `measureFormatString` from PBI measures and
  `kairos-ext:hierarchyName` + `hierarchyLevel` from PBI hierarchies, with a header
  comment marking the file as a human-confirm candidate. **Review and confirm** the
  candidate here, then fold the approved annotations into your real
  `{domain}-gold-ext.ttl` — it is never applied automatically.
- **`kairos-ontology pbi-source-fit-gap SOURCE --domain {domain}`** writes an advisory
  markdown fit-gap report (default `integration/reports/{domain}-claim-fit-gap.md`)
  that reconciles existing reporting demand against approved **source-backed** claims.
  Every PBI field / measure / relationship is classified as `fit`, `gap`, `defer`,
  `reject`, or `passthrough-dependency`, and it lists *source supply without reporting
  demand*. The report **informs** which gold measures/dimensions to design; it does not
  approve them (it always exits 0 when gaps exist).

> **Power BI is evidence, not authority** (methodology §3.5, §7). The seed is
> candidate-only and the fit-gap report is advisory — source/stakeholder evidence and
> the claim-approval gate remain the basis for what lands in gold. Both commands are
> exempt from the skill soft-gate, like `import-tmdl`.

## Gold Annotation Reference

### Ontology-level

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `goldSchema` | string | `gold_{domain}` | Target schema name |
| `goldInheritanceStrategy` | string | `class-per-table` | Subclass projection strategy: `"class-per-table"` (each subclass → own table with shared PK/FK to parent) or `"discriminator"` (flatten into parent table). Can also be set per-class. |
| `generateDateDimension` | boolean | `true` | Auto-generate dim_date |
| `generateTimeIntelligence` | boolean | `false` | Generate time-intelligence calculation group (YTD/QTD/MTD/PY/YoY%) |
| `goldIncludeImports` | boolean | `false` | Bulk-claim all first-level imported classes for gold projection (DD-021) |

### Class-level

| Property | Type | Description |
|----------|------|-------------|
| `goldInclude` | boolean | Claim an imported class for gold projection (DD-021) |
| `goldTableType` | string | Override: `"fact"`, `"dimension"`, `"bridge"` |
| `goldTableName` | string | Table name override (prefix auto-added) |
| `goldExclude` | boolean | Exclude from gold projection |
| `perspective` | string | Space-separated perspective names (table subsets for role-based visibility) |
| `incrementalColumn` | string | Column for dbt incremental materialisation on gold models |

### Property-level

| Property | Type | Description |
|----------|------|-------------|
| `goldColumnName` | string | Column name override |
| `goldDataType` | string | SQL type override |
| `measureExpression` | string | DAX measure (property becomes measure, not column) |
| `measureFormatString` | string | DAX format string |
| `hierarchyName` | string | Power BI hierarchy this property belongs to |
| `hierarchyLevel` | integer | Level in hierarchy (1 = top) |
| `degenerateDimension` | boolean | Keep on fact table (no separate dim) |
| `rolePlayingAs` | string | Space-separated role names for role-playing dimension |
| `olsRestricted` | boolean | Mark column for Object-Level Security restriction |

### Working with imported classes (DD-021)

When a domain ontology uses `owl:imports` to reference external models (e.g.,
reference models), imported classes are **NOT projected** to gold by default.
Hub authors must explicitly claim them.

**Per-class claiming:**
```turtle
@prefix ref: <https://referencemodels.kairos.cnext.eu/party#> .
ref:TradeParty kairos-ext:goldInclude "true"^^xsd:boolean .
```

**Bulk claiming (all first-level imported classes):**
```turtle
<https://contoso.com/ont/customer> kairos-ext:goldIncludeImports "true"^^xsd:boolean .
```

**Rules:**
- Bulk mode (`goldIncludeImports`) claims all classes from directly imported
  ontologies (first-level `owl:imports` only).
- Peer hub domains (other domains in the same hub) are **excluded** from bulk
  claiming — they have their own extension files.
- The gold schema comes from the **hub domain name** (e.g., `gold_customer`),
  not from the reference model namespace.
- Per-class `goldInclude` overrides bulk mode for individual classes.

**Example extension file** (`customer-gold-ext.ttl`):
```turtle
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
@prefix ref: <https://referencemodels.kairos.cnext.eu/party#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

# Bulk-claim all imported reference model classes
<https://contoso.com/ont/customer>
    kairos-ext:goldSchema "gold_customer" ;
    kairos-ext:goldIncludeImports "true"^^xsd:boolean .

# Or claim individual classes
ref:TradeParty
    kairos-ext:goldInclude "true"^^xsd:boolean ;
    kairos-ext:goldTableType "dimension" .
```

## Output Artifacts

```
output/medallion/powerbi/{domain}/
├── {domain}-gold-ddl.sql                              # Star schema CREATE TABLEs
├── {domain}-gold-alter.sql                            # FK constraint documentation
├── {domain}-gold-erd.mmd                              # Star schema Mermaid ERD
├── {domain}-gold-erd.svg                              # SVG render (requires Mermaid CLI)
├── {domain}-gold-views.sql                            # SCD2 framing views (WHERE is_current)
├── {Domain}.SemanticModel/
│   └── definition/
│       ├── model.tmdl                                 # Model settings (DirectLake)
│       ├── tables/
│       │   ├── dim_{name}.tmdl                        # Dimension definitions
│       │   └── fact_{name}.tmdl                       # Fact definitions
│       ├── relationships/
│       │   └── relationships.tmdl                     # Star schema relationships
│       ├── roles/
│       │   └── rls-roles.tmdl                         # RLS + OLS roles (G4, GDPR)
│       ├── perspectives/
│       │   └── perspectives.tmdl                      # Perspective subsets (optional)
│       └── calculationGroups/
│           └── time-intelligence.tmdl                 # Time-intelligence calc group (optional)
└── measures/
    └── {domain}-measures.dax                          # DAX measures
```

### Best-practice separation

| Layer | Responsibility | Artifact |
|-------|---------------|----------|
| **dbt** | Data logic (joins, facts, dims, SCD, tests) | `models/gold/` SQL models |
| **Semantic model** | Business metrics (DAX, relationships, hierarchies, RLS/OLS) | `{Domain}.SemanticModel/` TMDL |
| **Reports** | Visuals only — consume measures from semantic model | (not generated) |

> **Rule:** Don't duplicate business rules in both dbt and DAX. Row-level
> shaping lives in dbt; reusable KPIs live in the semantic model.

**Automatically generated after all domains are projected:**
- `output/medallion/powerbi/master-gold-erd.mmd` — cross-domain master gold ERD (all star schema tables + FK relationships)
- `output/medallion/powerbi/master-gold-erd.svg` — SVG render of the master gold ERD

The master gold ERD merges every `*-gold-erd.mmd` into a single diagram with one
section per domain. It is the primary artifact to review the full gold layer star
schema at a glance.

### SVG export setup

SVG rendering requires the Mermaid CLI (`mmdc`). If not installed, `.mmd` files are
still generated but SVG export is skipped with an info message.

```bash
# Install in the hub repo (one-time)
npm install

# Or install globally
npm install -g @mermaid-js/mermaid-cli
```

Hub repos scaffolded with `kairos-ontology new-repo` already include a `package.json`
with `@mermaid-js/mermaid-cli` as a dev dependency — just run `npm install`.

## Checklist

- [ ] Create `{domain}-gold-ext.ttl` in `model/extensions/`
- [ ] Claim any imported classes with `goldInclude` or `goldIncludeImports` (DD-021)
- [ ] Annotate each class with `goldTableType` (or rely on auto-classification)
- [ ] Add `measureExpression` for DAX measures on numeric properties
- [ ] Add `hierarchyName` / `hierarchyLevel` for drill-down hierarchies
- [ ] Invoke **kairos-execute-project** with `--target powerbi`
- [ ] Review star schema ERD in `output/medallion/powerbi/{domain}/`
- [ ] Check SVG renders were created (requires `mmdc` — see SVG export setup)
- [ ] Import TMDL into Power BI Desktop or deploy to Fabric workspace
- [ ] Configure RLS roles in Power BI service (if GDPR dimensions exist)

---

## Session Management

> **MANDATORY:** Every gold design session MUST produce a session file that
> captures decisions made, items deferred, and design rationale.

### On start — Check for existing session

```
ontology-hub/.sessions-design/
  └── gold-{domain}-{YYYY-MM-DD}.md
```

If a previous session exists, ask the user whether to continue or start fresh.

> **Starting fresh — archive, don't overwrite (DD-071).** When the user chooses to
> start a new session instead of resuming, first move any existing
> `.sessions-design/gold-{domain}-*.md` log(s) for this domain into
> `ontology-hub/.sessions-design/_archive/` (create it if missing; keep the
> original filename). Never delete a previous log. Then create the new session log.

### Session file format

Save to `ontology-hub/.sessions-design/gold-{domain}-{YYYY-MM-DD}.md`:

```markdown
# Gold Design Session: {Domain}

**Started:** {ISO-8601}
**Last updated:** {ISO-8601}
**Status:** Complete | In Progress
**Toolkit version:** {version}

## Decisions Made

| Class | Gold Role | Measures | Hierarchies | RLS | Status |
|---|---|---|---|---|---|
| {ClassName} | fact/dimension/bridge | {count} | {list or —} | {yes/no} | ✅/⚠️ |

## Deferred / TODO

| # | Class | Item | Reason | Resolve via |
|---|---|---|---|---|
| 1 | {ClassName} | {what is missing} | {why deferred} | kairos-design-gold |

## Design Rationale

| # | Question | Decision | Rationale |
|---|---|---|---|
| 1 | {question} | {choice made} | {why} |
```

### Saving rules

- **Auto-save** after each class gold annotation is confirmed
- Record **every** deferred item with a reason
- On pause/completion, list remaining open items and confirm with user

---

## Related skills

| When you need | Invoke |
|---|---|
| Design/modify domain ontology classes and properties | **kairos-design-domain** |
| Design silver layer (DDL, SCD, FK annotations) | **kairos-design-silver** |
| Create bronze vocabulary from source docs | **kairos-design-source** |
| Map source columns to domain properties | **kairos-design-mapping** |
| Run projections (generate dbt/DDL/TMDL output) | **kairos-execute-project** |
