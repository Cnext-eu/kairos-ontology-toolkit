---
name: kairos-design-gold
description: >
  Expert guide for designing gold-layer extension annotations (fact/dimension
  types, DAX measures, hierarchies, RLS) and understanding Power BI projection
  output. Targets DirectLake on Microsoft Fabric Warehouse.
---

# Kairos Medallion Gold Skill

## Lifecycle state (DD-080)

> The **kairos-flow** skill is the lifecycle orchestrator and the **only** writer of
> `ontology-hub/.kairos-state/status.md`. This skill plugs into that shared state; it
> does not maintain the global status file.

**On start (pre-flight):** read `ontology-hub/.kairos-state/` — the `status.md`
continuation region and this phase's log(s) at `phases/gold/<model>.md` — to resume open
questions. Ignore `_archive/`. (`kairos-ontology status` gives the objective view.)

**On pause or finish:** append a *State update proposal* to `phases/gold/<model>.md` with
OKF frontmatter (`type: kairos-phase-log`, `phase: gold`, `instance: <model>`, `status:`,
`last_updated:`). Record decisions made and an **Open questions** list as the resume
anchor. Do **not** edit `status.md` directly — kairos-flow folds your proposal in.


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
