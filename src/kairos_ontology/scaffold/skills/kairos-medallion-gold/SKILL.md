---
name: kairos-medallion-gold
description: >
  Expert guide for designing and running the gold-layer projection.
  Generates Power BI star-schema DDL, TMDL semantic model, DAX measures,
  and Mermaid ERD from OWL ontologies annotated with kairos-ext: properties.
  Targets DirectLake on Microsoft Fabric Warehouse.
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

## G8 — DirectLake Optimised Types

| Silver (S1) | Gold (G8) | Reason |
|-------------|-----------|--------|
| STRING SK (UUID) | INT SK (IDENTITY) | Better V-Order compression |
| BOOLEAN | BIT | Power BI prefers BIT |
| STRING | VARCHAR(256) | Bounded length for VertiPaq |
| DOUBLE | FLOAT | Fabric Warehouse type |

## Running the Projection

```bash
# Generate gold artifacts for all domains
python -m kairos_ontology project --target powerbi

# With explicit paths
python -m kairos_ontology project \
  --ontologies ontology-hub/model/ontologies \
  --output ontology-hub/output \
  --target powerbi
```

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

### Class-level

| Property | Type | Description |
|----------|------|-------------|
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
| **dbt** | Data logic (staging, joins, facts, dims, SCD, tests) | `models/gold/` SQL models |
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
- [ ] Annotate each class with `goldTableType` (or rely on auto-classification)
- [ ] Add `measureExpression` for DAX measures on numeric properties
- [ ] Add `hierarchyName` / `hierarchyLevel` for drill-down hierarchies
- [ ] Run `python -m kairos_ontology project --target powerbi`
- [ ] Review star schema ERD in `output/medallion/powerbi/{domain}/`
- [ ] Check SVG renders were created (requires `mmdc` — see SVG export setup)
- [ ] Import TMDL into Power BI Desktop or deploy to Fabric workspace
- [ ] Configure RLS roles in Power BI service (if GDPR dimensions exist)
