# Kairos for Data Engineers — A Methodology Guide

> **Audience:** Data engineers who need to build data warehouses, lakehouses,
> or BI platforms using the Kairos ontology-driven approach.
>
> This guide explains *what* to do and *why*, not how to install tools.

---

## 1. The Big Idea: Model First, Generate Everything

Traditional data engineering works bottom-up: you look at source systems, design
tables, write ETL, then hope the BI layer makes sense. This leads to:

- Naming inconsistencies across layers
- Business logic buried in SQL
- Schema changes that ripple unpredictably
- Documentation that's always out of date

**Kairos flips this.** You start with a formal domain model (an ontology), and
the toolkit *generates* your warehouse schemas, dbt models, BI semantic models,
and documentation from that single source of truth.

```text
                    ┌─────────────────┐
                    │  Domain Ontology │  ← You design this
                    │    (OWL/Turtle)  │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
        Silver DDL      dbt Models    Power BI TMDL
        + FK scripts    (bronze→gold)  (star schema)
```

**Why this matters for you as a data engineer:**
- Change a property in the ontology → regenerate → all layers update consistently
- Business definitions live in one place (not scattered across 47 dbt YAML files)
- Traceability from BI column → silver table → ontology class → business concept

---

## 2. Core Concepts (Without the Academic Jargon)

You don't need a PhD in knowledge representation. Here's what matters:

### OWL — Your Domain Model

OWL (Web Ontology Language) is how we formally describe the business domain.
Think of it as an **entity-relationship model on steroids**:

| Traditional ER | OWL Equivalent | What it means |
|---|---|---|
| Entity | `owl:Class` | A business concept (Customer, Order, Asset) |
| Attribute | `owl:DatatypeProperty` | A fact about a thing (name, amount, date) |
| Relationship | `owl:ObjectProperty` | A link between things (Order → Customer) |
| Inheritance | `rdfs:subClassOf` | Specialisation (PremiumCustomer is a Customer) |
| Cardinality | `owl:Restriction` | "Every Order has exactly 1 Customer" |

**Key difference from ER diagrams:** OWL models are *formal* — machines can reason
over them, validate them, and generate code from them. Your ER diagram in Visio
can't do that.

The files are written in **Turtle (.ttl)** syntax — a compact, human-readable
text format. Example:

```turtle
:Order a owl:Class ;
    rdfs:label "Order" ;
    rdfs:comment "A customer purchase transaction" .

:orderDate a owl:DatatypeProperty ;
    rdfs:domain :Order ;
    rdfs:range xsd:date ;
    rdfs:label "order date" .

:placedBy a owl:ObjectProperty ;
    rdfs:domain :Order ;
    rdfs:range :Customer ;
    rdfs:label "placed by" .
```

### SKOS — Mapping Source Systems to the Ontology

SKOS (Simple Knowledge Organisation System) is how we connect *source system
columns* to *ontology concepts*. It's the bridge between messy reality and
clean models.

| SKOS Relationship | When to use |
|---|---|
| `skos:exactMatch` | Source column maps 1:1 to an ontology property |
| `skos:closeMatch` | Close but not identical (needs transformation) |
| `skos:broadMatch` | Source is more specific than the ontology property |
| `skos:narrowMatch` | Source is more general than the ontology property |

**Why you care:** These mappings drive the dbt model generation. A `skos:exactMatch`
becomes a direct column reference; a `skos:closeMatch` gets flagged for a transform
expression.

### SHACL — Validation Rules (Quality Gates)

SHACL (Shapes Constraint Language) defines rules that your ontology must follow.
Think of it as **unit tests for your data model**:

```turtle
:OrderShape a sh:NodeShape ;
    sh:targetClass :Order ;
    sh:property [
        sh:path :orderDate ;
        sh:datatype xsd:date ;
        sh:minCount 1 ;     # every Order MUST have an orderDate
    ] .
```

**Why you care:** Before generating any DDL or dbt code, the toolkit validates
the ontology against SHACL shapes. If someone adds a class without a label or
a property without a range, validation fails — catching errors *before* they
reach your warehouse.

---

## 3. The Methodology: Where to Start

### The Sequence Matters

```text
Step 1: Create the domain ontology
        ↓
Step 2: Create silver extensions (FK annotations, schema config)
        ↓
Step 3: Generate silver layer (DDL + dbt)
        ↓
Step 4: Create gold extensions (star schema annotations)
        ↓
Step 5: Generate gold layer (Power BI TMDL + DDL)
        ↓
Step 6: Create source mappings (SKOS)
        ↓
Step 7: Generate dbt bronze-to-silver models
        ↓
Step 8: Set up dataplatform runtime repo and consume generated dbt package
```

**Why this order?**

- You can't annotate what doesn't exist (extensions need the ontology first)
- Silver is the normalised truth layer — gold is derived from it
- Source mappings connect reality to the model — they need both sides to exist
- Each step validates against the previous, catching errors early

---

## 4. Step 1 — Creating the Domain Ontology

### Inputs You Gather

Before designing classes, collect these inputs:

| Input | Where it lives | What it tells you |
|---|---|---|
| **Reference models** (accelerator pack) | `ontology-reference-models/` | Industry-standard class hierarchies — your starting point |
| **Source system metadata** | `integration/sources/{system}/` | DDL, API specs, sample data — what actually exists |
| **TMDL / Power BI models** | `integration/sources/powerbi/` | Existing BI concepts, measures, relationships — legacy business validation |

### The Trust Hierarchy

When these inputs disagree (and they will), follow this priority:

```text
🟢 Reference model structure    — Highest (industry best practice)
🟡 Source system reality         — High (what actually exists)
🟠 TMDL / existing BI           — Medium (legacy, may have shortcuts)
```

**Example:** Your TMDL has a denormalised `FactSalesWithCustomer` table. The
reference model separates `Order` and `Customer`. Follow the reference model
(normalised), but note the TMDL pattern — it tells you what the business
actually uses and may inform your gold star-schema design later.

### Using the Reference Model (Accelerator Pack)

You rarely start from scratch. The reference models provide tested class
hierarchies for common domains:

1. **Browse available modules** — find the closest match for your business domain
2. **Import via `owl:imports`** — your ontology pulls in reference classes
3. **Specialise where needed** — create subclasses for business-specific concepts
4. **Add local classes** — for things unique to your organisation

```turtle
@prefix ref: <https://kairos.cnext.eu/ref/logistics#> .

:ExpressShipment rdfs:subClassOf ref:Shipment ;
    rdfs:label "Express Shipment" ;
    rdfs:comment "A shipment with guaranteed next-day delivery" .
```

### Using Source System Metadata

Source DDL reveals what data *actually* exists — cardinalities, data types,
columns that aren't in any reference model:

- A source table with 50 columns might map to 3 ontology classes
- Nullable columns suggest optional properties (cardinality 0..1)
- Foreign keys confirm relationships between concepts

### Using TMDL (Legacy BI) as Input

Run `kairos-ontology import-tmdl` to automatically extract an engineering pack
from existing Power BI models:

```bash
kairos-ontology import-tmdl path/to/Model.SemanticModel --output integration/sources/powerbi/
```

This generates:
- **Engineering Pack** — inventory of tables, columns, measures, relationships
- **Concept Mapping YAML** — template to map TMDL tables to ontology classes

⚠️ **TMDL is advisory, not authoritative.** Existing BI models often contain:
- Denormalised tables (star schema shortcuts)
- Inconsistent naming
- Technical columns that aren't business concepts
- Measures that belong in gold, not in the domain model

Use TMDL to *validate* your ontology ("does it cover what the business actually reports on?")
— not to *drive* it.

---

## 5. Step 2 — Silver Extensions (Why They're Needed)

The domain ontology describes *what* exists in the business. But to generate a
physical warehouse schema, the toolkit needs additional information:

| Question | Extension annotation | Example |
|---|---|---|
| What's the schema name? | `kairos-ext:silverSchema` | `silver_logistics` |
| Which properties become FK columns? | `kairos-ext:silverForeignKey` | Links between tables |
| What's the surrogate key column? | `kairos-ext:silverSurrogateKey` | `SK_Order` |
| Should this class be excluded? | `kairos-ext:silverExclude` | Skip abstract classes |

### Why separate from the ontology?

The domain ontology is **platform-agnostic** — it describes the business, not the
warehouse. Silver extensions add **physical implementation decisions** that would
pollute the pure domain model:

```text
Domain ontology (pure business):     "An Order is placed by a Customer"
Silver extension (physical):          "The silver_orders table has FK_Customer
                                       referencing silver_customers.SK_Customer"
```

This separation means you can:
- Regenerate for a different warehouse technology without touching the ontology
- Share ontologies across teams that use different physical implementations
- Keep the business model readable by non-engineers

### The FK Annotation Pattern

When your ontology imports reference models, object properties (relationships)
won't automatically generate FK columns — you need to explicitly declare them:

```turtle
:placedBy kairos-ext:silverForeignKey true ;
    kairos-ext:silverForeignKeyOn :Customer .
```

This tells the generator: "In the silver layer, the Order table should have a
foreign key column pointing to the Customer table."

---

## 6. Step 3 — Generating the Silver Layer

Once you have:
- ✅ Domain ontology with classes and properties
- ✅ Silver extension with FK and schema annotations

Run the projection:

```bash
kairos-ontology project --target silver
kairos-ontology project --target dbt
```

This generates:
- **DDL scripts** — `CREATE TABLE` statements for your warehouse
- **ALTER scripts** — FK constraint documentation
- **ERD diagram** — Mermaid entity-relationship diagram
- **dbt models** — SQL models that read from bronze and write to silver

### What you get in the dbt project

```text
output/medallion/dbt/
  models/
    silver/
      {domain}/
        silver_{class}.sql          ← One model per ontology class
        _schema.yml                 ← Column docs + tests
    gold/
      {domain}/
        dim_{class}.sql / fact_{class}.sql
  analyses/
    {domain}/
      silver_ddl.sql               ← Full DDL for reference
```

---

## 7. Steps 4–5 — Gold Layer (Star Schema for BI)

Gold extensions annotate your ontology for **Power BI / star schema** generation:

| Annotation | Purpose |
|---|---|
| `kairos-ext:goldTableType` | Force fact/dimension/bridge classification |
| `kairos-ext:goldSchema` | Schema name for gold layer |
| `kairos-ext:measureExpression` | DAX measure definitions |
| `kairos-ext:generateTimeIntelligence` | Auto-generate date dimension |

The gold projector produces:
- Star-schema DDL (dim_/fact_ tables with SCD Type 2 on dimensions)
- TMDL semantic model (ready to deploy to Power BI)
- DAX measures
- RLS roles (from GDPR annotations)

---

## 8. Steps 6–7 — Source Mappings and Bronze-to-Silver dbt

Source mappings use SKOS to connect source system columns to ontology properties:

```turtle
source:customer_name skos:exactMatch :customerName .
source:cust_email    skos:closeMatch :emailAddress .
```

These mappings drive the generated dbt SQL — telling each silver model exactly
which source columns to select and how to transform them.

---

## 9. Step 8 — Set Up the Dataplatform Runtime Repo (dbt Consumer)

The ontology hub is design-time; the **dataplatform repo is your dbt runtime**.
After generating `output/medallion/dbt/`, consume it from a separate dataplatform
repository that owns profiles, source bindings, orchestration, and deployments.

Use the template/scaffold workflow for consistency:

- Set up the runtime repo via the **kairos-setup-dataplatform** skill
- Configure `packages.yml` to consume the hub dbt project by pinned revision
- Run `dbt deps` in the runtime repo to pull generated models
- Add runtime-owned models/tests/macros on top of hub-generated package models

Example package reference:

```yaml
packages:
  - git: https://github.com/your-org/your-ontology-hub.git
    revision: v1.3.0
    subdirectory: output/medallion/dbt
```

Runtime split:

| Ontology hub (design-time) | Dataplatform repo (runtime) |
|---|---|
| OWL model, extensions, mappings | dbt profile, `_sources.yml`, CI/CD |
| Generate dbt package artifacts | Consume package via `dbt deps` |
| Publish versioned releases | Pin/upgrade package revisions |

---

## 10. Why the Sequence Matters — A Summary

| If you skip... | What breaks |
|---|---|
| Ontology first | Nothing to annotate, nothing to generate |
| Reference models | You reinvent the wheel; inconsistent naming |
| Silver extensions before generating | Missing FKs, wrong schema names, incomplete tables |
| Silver before gold | Gold references silver tables that don't exist |
| Source mappings before dbt | dbt models don't know which columns to select |
| Dataplatform runtime setup | No governed runtime to consume and operationalize dbt output |

**The ontology is the keystone.** Everything downstream is derived from it.
If the ontology is wrong, *everything* generated from it will be wrong — but
at least it will be *consistently* wrong and fixable in one place.

---

## 11. Quick Reference: What Lives Where

```text
ontology-hub/
├── model/
│   ├── ontologies/          ← Your domain models (.ttl)
│   ├── extensions/          ← Silver + gold annotations
│   └── shapes/              ← SHACL validation rules
├── integration/
│   ├── sources/             ← Source system docs + TMDL
│   └── mappings/            ← SKOS source-to-ontology mappings
└── output/                  ← Generated (never edit manually!)
    └── medallion/
        ├── dbt/             ← dbt project
        └── gold/            ← Power BI TMDL + DDL

dataplatform/
├── dbt_project.yml          ← Runtime dbt project
├── packages.yml             ← Pins ontology-hub dbt package revision
├── models/                  ← Runtime-owned models/extensions
└── _sources.yml             ← Physical source bindings
```

---

## 12. Getting Started Checklist

- [ ] Collect your inputs (reference models, source DDL, existing TMDL)
- [ ] Run `kairos-ontology import-tmdl` on any existing Power BI models
- [ ] Design the domain ontology (use the modeling skill with Copilot)
- [ ] Validate: `kairos-ontology validate`
- [ ] Create silver extensions (FK annotations, schema name)
- [ ] Generate silver: `kairos-ontology project --target silver`
- [ ] Create gold extensions (star schema annotations, measures)
- [ ] Generate gold: `kairos-ontology project --target powerbi`
- [ ] Create source mappings (SKOS)
- [ ] Generate dbt: `kairos-ontology project --target dbt`
- [ ] Set up dataplatform runtime repo (use `kairos-setup-dataplatform`)
- [ ] Add/pin ontology hub package in `packages.yml` and run `dbt deps`
- [ ] Review generated artifacts, iterate on ontology if needed

---

> **Remember:** The ontology is a living document. As you discover new source
> systems, business requirements change, or BI needs evolve — update the ontology,
> regenerate, and everything stays in sync. That's the power of model-driven
> data engineering.
