# Kairos Ontology Toolkit — User Guide

> **What it is:** A command-line toolkit that turns OWL/Turtle ontologies into
> production-ready data platform artifacts — DDL scripts, dbt models, graph
> schemas, search indexes, UI schemas, and LLM context — while keeping
> everything traceable back to the source ontology.

---

## Table of Contents

1. [Why Use This Toolkit](#1-why-use-this-toolkit)
2. [Key Concepts](#2-key-concepts)
3. [Getting Started](#3-getting-started)
4. [Creating an Ontology Hub](#4-creating-an-ontology-hub)
5. [Writing Ontologies](#5-writing-ontologies)
6. [Validating Ontologies](#6-validating-ontologies)
7. [Generating Projections](#7-generating-projections)
8. [Silver Layer Projection](#8-silver-layer-projection)
9. [Projection Traceability](#9-projection-traceability)
10. [Keeping Your Hub Up to Date](#10-keeping-your-hub-up-to-date)
11. [Multi-Domain Architecture](#11-multi-domain-architecture)
12. [Workflow Summary](#12-workflow-summary)
13. [Troubleshooting](#13-troubleshooting)

---

## 1. Why Use This Toolkit

Most data platforms suffer from a **model–code gap**: the conceptual data model
lives in a wiki or diagram tool, while the DDL, dbt models, and search indexes
are maintained by hand. Over time they drift apart.

The Kairos Ontology Toolkit closes this gap:

```
   OWL/Turtle Ontology          ┌─ DDL + ERD  (Silver layer)
   (single source of truth)  ──►├─ dbt models
                                ├─ Neo4j Cypher
                                ├─ Azure Search indexes
                                ├─ A2UI JSON schemas
                                └─ LLM prompt context
```

**You should use this toolkit when you want to:**

- Define your data model **once** and generate all downstream artifacts
- Keep every generated artifact **traceable** to its source ontology IRI and
  version
- Support **multiple data domains** (customer, order, party, …) that can be
  owned, versioned, and deployed independently
- Validate your model with **SHACL shapes** before pushing changes
- Work in a **Git-based workflow** with feature branches and pull requests

---

## 2. Key Concepts

### Ontology

An OWL/Turtle (`.ttl`) file that describes a data domain: its classes,
properties, relationships, and metadata. This is the **single source of truth**
for your data model.

### Ontology Hub

A Git repository containing one or more domain ontologies, SHACL validation
shapes, reference models, and generated output. Created by
`python -m kairos_ontology new-repo`.

### Projection

The process of transforming an ontology into a target-specific artifact (DDL,
dbt model, etc.). Each ontology can produce artifacts for multiple targets.

### Silver Layer

A specific projection target that generates **data warehouse DDL** (CREATE
TABLE / ALTER TABLE), **Mermaid ERD diagrams**, and **SVG exports**. Designed
for Snowflake-style analytics databases with SCD Type 1/2, surrogate keys,
audit envelopes, and GDPR satellite tables.

### Projection Manifest

A `projection-manifest.json` file generated alongside your artifacts. It
records which ontology IRI and version produced each output file — enabling
controlled upgrades in both directions.

---

## 3. Getting Started

### Prerequisites

- **Python 3.12+**
- **Git**
- **GitHub CLI** (`gh`) — for repository creation and pull requests
- **Node.js** (optional) — for Mermaid SVG rendering

### Install the Toolkit

```bash
pip install git+https://github.com/Cnext-eu/kairos-ontology-toolkit.git
```

Verify installation:

```bash
python -m kairos_ontology --version
```

> **Always use `python -m kairos_ontology`** to invoke the CLI. This works
> regardless of whether the `Scripts/` directory is on your PATH.

---

## 4. Creating an Ontology Hub

An ontology hub is a Git repository that holds your domain ontologies and their
generated projections. Create one with a single command:

```bash
python -m kairos_ontology new-repo \
  --name "my-company-ontology-hub" \
  --desc "Ontology hub for My Company" \
  --company-domain "mycompany.com"
```

This scaffolds the following structure:

```
my-company-ontology-hub/
├── .github/
│   ├── copilot-instructions.md     # AI assistant context
│   └── skills/                     # Copilot skills for modelling workflows
├── ontology-hub/
│   ├── ontologies/                 # Your domain ontologies (.ttl)
│   │   └── _master.ttl             # Imports all domains
│   ├── shapes/                     # SHACL validation shapes
│   ├── output/                     # Generated projections
│   ├── application-models/         # ERD diagrams for web display
│   ├── kairos-ext.ttl              # Extension vocabulary (DO NOT EDIT)
│   ├── silver-ext.ttl.template     # Template for silver annotations
│   └── package.json                # Mermaid CLI dependency
├── ontology-reference-models/      # External ontologies (FIBO, etc.)
├── README.md
└── .gitignore
```

After creation, `cd` into the repo and install the Mermaid CLI for SVG export:

```bash
cd my-company-ontology-hub
npm install
```

---

## 5. Writing Ontologies

### Minimum Requirements

Every ontology **must** declare:

```turtle
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix ex:   <https://mycompany.com/ontology/customer#> .

# 1. Ontology declaration (required)
<https://mycompany.com/ontology/customer> a owl:Ontology ;
    rdfs:label "Customer Domain"@en ;
    owl:versionInfo "1.0.0" .

# 2. Classes with label + comment (required)
ex:Customer a owl:Class ;
    rdfs:label "Customer"@en ;
    rdfs:comment "A person or organisation that purchases products."@en .

# 3. Properties with domain, range, and label (required)
ex:customerName a owl:DatatypeProperty ;
    rdfs:domain ex:Customer ;
    rdfs:range xsd:string ;
    rdfs:label "customer name"@en .
```

### Naming Conventions

| Element        | Convention  | Example              |
|----------------|-------------|----------------------|
| Classes        | PascalCase  | `ex:IndividualClient`|
| Properties     | camelCase   | `ex:dateOfBirth`     |
| Namespace URIs | HTTPS + `#` | `https://company.com/ontology/customer#` |

### Importing External Ontologies

Use `owl:imports` to reference shared or external models:

```turtle
<https://mycompany.com/ontology/customer> a owl:Ontology ;
    owl:imports <https://mycompany.com/ontology/party> ;
    owl:imports <https://spec.edmcouncil.org/fibo/ontology/FND/Parties/Parties/> .
```

The toolkit automatically resolves imports via the XML catalog in
`ontology-reference-models/catalog-v001.xml`.

---

## 6. Validating Ontologies

Always validate before generating projections or merging a PR.

```bash
# Full validation (syntax + SHACL + consistency)
python -m kairos_ontology validate --all

# Syntax check only
python -m kairos_ontology validate --syntax

# SHACL shapes only
python -m kairos_ontology validate --shacl
```

### What Gets Validated

| Level         | What it checks                                      |
|---------------|-----------------------------------------------------|
| **Syntax**    | Valid Turtle/RDF — parseable by rdflib               |
| **SHACL**     | Constraints from `shapes/*.shacl.ttl` (cardinality, value types, patterns) |
| **Consistency**| SPARQL-based checks (orphan properties, missing labels) |

---

## 7. Generating Projections

```bash
# All targets at once
python -m kairos_ontology project --target all

# Single target
python -m kairos_ontology project --target silver
python -m kairos_ontology project --target dbt
python -m kairos_ontology project --target neo4j
python -m kairos_ontology project --target azure-search
python -m kairos_ontology project --target a2ui
python -m kairos_ontology project --target prompt
```

### Available Targets

| Target           | What it generates                                    | Use case                        |
|------------------|------------------------------------------------------|---------------------------------|
| **silver**       | DDL, ALTER SQL, Mermaid ERD, SVG, master ERD         | Data warehouse (Snowflake/Databricks) |
| **dbt**          | SQL models + YAML schema                             | dbt transformation layer        |
| **neo4j**        | Cypher schema (constraints, relationship types)      | Graph database                  |
| **azure-search** | JSON index definitions                               | Azure AI Search                 |
| **a2ui**         | JSON Schema for message payloads                     | UI generation                   |
| **prompt**       | Compact + detailed JSON context                      | LLM/AI assistant context        |

### Output Structure

```
ontology-hub/output/
├── silver/
│   ├── customer/
│   │   ├── customer-ddl.sql          # CREATE TABLE statements
│   │   ├── customer-alter.sql        # ALTER TABLE (FK constraints)
│   │   ├── customer-erd.mmd          # Mermaid ERD source
│   │   └── customer-erd.svg          # Rendered SVG diagram
│   ├── master-erd.mmd                # Cross-domain ERD (all domains)
│   └── master-erd.svg
├── dbt/
│   └── customer/models/silver/
│       ├── customer.sql
│       └── schema_customer.yml
├── neo4j/
│   └── customer-schema.cypher
├── prompt/
│   ├── customer-context.json
│   └── customer-context-detailed.json
├── customer-projection-manifest.json  # Provenance manifest
└── order-projection-manifest.json
```

---

## 8. Silver Layer Projection

The silver target is the most feature-rich projection. It generates
production-ready DDL for analytics databases.

### Annotating Your Ontology for Silver

Create a `<domain>-silver-ext.ttl` file alongside your ontology:

```turtle
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
@prefix ex:         <https://mycompany.com/ontology/customer#> .

# Schema-level settings (on the owl:Ontology)
<https://mycompany.com/ontology/customer>
    kairos-ext:silverSchema "silver_customer" ;
    kairos-ext:surrogateKeyStrategy "hash" ;
    kairos-ext:namingConvention "camel-to-snake" ;
    kairos-ext:auditEnvelope "_load_date TIMESTAMP_NTZ, _source_system NVARCHAR(100), is_current BOOLEAN" .

# Per-class settings
ex:Customer
    kairos-ext:scdType "2" ;
    kairos-ext:partitionBy "_load_date" ;
    kairos-ext:clusterBy "is_current" .

# Inheritance with discriminator (subtypes folded into parent table)
ex:Client
    kairos-ext:inheritanceStrategy "discriminator" ;
    kairos-ext:discriminatorColumn "client_type" .

# Reference data (SCD Type 1, ref_ prefix)
ex:Country
    kairos-ext:isReferenceData "true"^^xsd:boolean ;
    kairos-ext:scdType "1" .

# GDPR satellite table
ex:CustomerPII
    kairos-ext:gdprSatelliteOf ex:Customer ;
    kairos-ext:scdType "2" .
```

### Silver Projection Rules (R1–R16)

| Rule | What it does |
|------|--------------|
| R1   | Schema name from `kairos-ext:silverSchema` or `silver_{domain}` |
| R2   | Surrogate key strategy: `hash` (BINARY(20)) or `uuid` (NVARCHAR(36)) |
| R3   | Audit envelope columns appended to every table |
| R4   | Naming convention: `camel-to-snake` or `as-is` |
| R5   | SQL type mapping from XSD types |
| R6   | Inheritance: `class-per-table` or `discriminator` strategy |
| R7   | GDPR satellite tables with PK/FK back to parent |
| R8   | Reference data tables with `ref_` prefix, SCD Type 1 |
| R9   | Audit envelope parsing with custom columns |
| R10  | IRI lineage column (`{table}_iri`) on every table |
| R11  | NOT NULL from SHACL `sh:minCount 1` or `kairos-ext:nullable "false"` |
| R12  | FK constraints via ALTER TABLE script |
| R13  | Junction tables for many-to-many relationships |
| R14  | Mermaid ERD generation with relationship labels |
| R15  | Projection extension merging (`*-silver-ext.ttl`) |
| R16  | Empty subtype suppression under discriminator strategy |

---

## 9. Projection Traceability

Every projection output includes **provenance metadata** linking it back to the
source ontology:

### In-File Headers

```sql
-- Silver layer DDL: silver_customer
-- Domain: customer
-- Ontology IRI: https://mycompany.com/ontology/customer
-- Ontology version: 1.2.0
-- Toolkit version: 1.9.0
-- Generated at: 2026-04-21T00:18:00Z
```

### Projection Manifest

Each domain gets a `<domain>-projection-manifest.json`:

```json
{
  "domain": "customer",
  "ontology_iri": "https://mycompany.com/ontology/customer",
  "ontology_version": "1.2.0",
  "ontology_label": "Customer Domain",
  "namespace": "https://mycompany.com/ontology/customer#",
  "toolkit_version": "1.9.0",
  "generated_at": "2026-04-21T00:18:00Z",
  "targets": {
    "silver": ["customer/customer-ddl.sql", "customer/customer-alter.sql", "customer/customer-erd.mmd"],
    "dbt": ["customer/models/silver/customer.sql", "customer/models/silver/schema_customer.yml"]
  }
}
```

### Why This Matters

- **Forward upgrade**: ontology version changed → compare with manifest → know
  which artifacts to regenerate
- **Backward lookup**: found a DDL file → check header or manifest → know
  exactly which ontology version produced it
- **Drift detection**: CI can compare `owl:versionInfo` vs manifest
  `ontology_version` to flag stale projections

---

## 10. Keeping Your Hub Up to Date

When a new toolkit version is released, update your hub:

```bash
# 1. Update the toolkit
pip install --upgrade git+https://github.com/Cnext-eu/kairos-ontology-toolkit.git

# 2. Refresh managed files (skills, copilot-instructions, kairos-ext.ttl)
python -m kairos_ontology update

# 3. Regenerate projections
python -m kairos_ontology project --target all

# 4. Commit
git add . && git commit -m "chore: update toolkit to v1.9.0 and regenerate projections"
```

The `update` command compares the version marker in managed files and only
overwrites files that are behind the installed toolkit version.

---

## 11. Multi-Domain Architecture

Each `.ttl` file in `ontologies/` represents an independent data domain.
Domains can:

- Be **owned by different teams**
- Be **versioned independently** (each has its own `owl:versionInfo`)
- Be **deployed independently** (e.g. `dbt run --models customer.*`)
- **Import from each other** via `owl:imports`

### Cross-Domain References

When a property references a class in another domain (e.g. `client:representsParty`
pointing to `party:Party`), the silver projector generates a cross-schema FK:

```sql
-- In silver_client.client table:
party_sk BINARY(20)   -- FK → silver_party.party(party_sk)
```

The FK is tracked in ALTER SQL and ERD but the constraint is logical (not
enforced within a single schema's DDL) since the tables live in different schemas.

### Master ERD

After projecting, a `master-erd.mmd` is generated that merges all per-domain
ERDs into one cross-domain diagram — showing all tables and relationships across
all your domains.

---

## 12. Workflow Summary

```
┌─────────────────────────────────────────────────────────────┐
│  1. CREATE HUB                                              │
│     python -m kairos_ontology new-repo --name my-hub        │
│                                                             │
│  2. MODEL                                                   │
│     Write / edit .ttl ontology files in ontologies/         │
│     Add silver annotations in *-silver-ext.ttl              │
│                                                             │
│  3. VALIDATE                                                │
│     python -m kairos_ontology validate --all                │
│                                                             │
│  4. PROJECT                                                 │
│     python -m kairos_ontology project --target all          │
│                                                             │
│  5. REVIEW & MERGE                                          │
│     git add . && git commit                                 │
│     gh pr create --base main                                │
│                                                             │
│  6. DEPLOY                                                  │
│     Use generated DDL / dbt / Cypher in your data platform  │
└─────────────────────────────────────────────────────────────┘
```

### Quick Reference — CLI Commands

| Command | Description |
|---------|-------------|
| `python -m kairos_ontology new-repo` | Create a new ontology hub repository |
| `python -m kairos_ontology init` | Initialize a domain ontology in an existing hub |
| `python -m kairos_ontology validate --all` | Validate all ontologies |
| `python -m kairos_ontology project --target all` | Generate all projections |
| `python -m kairos_ontology project --target silver` | Generate silver layer only |
| `python -m kairos_ontology update` | Refresh managed toolkit files |
| `python -m kairos_ontology catalog-test` | Test XML catalog resolution |

---

## 13. Troubleshooting

### No Files Generated

1. Check that your ontology has an `owl:Ontology` declaration
2. Ensure class URIs match the ontology namespace
3. Verify classes have at least one `owl:DatatypeProperty`

### Mermaid ERD Syntax Errors

- Types with commas (e.g. `DECIMAL(18,4)`) are automatically sanitized to
  `DECIMAL_18_4` in ERD output
- If you see parse errors, regenerate with the latest toolkit version

### Missing FK Columns

- Ensure object properties have `rdfs:domain` and `rdfs:range`
- For many-to-one FKs, either add `kairos-ext:silverColumnName` on the property
  or make it an `owl:FunctionalProperty`

### SVG Export Not Working

```bash
# Install Mermaid CLI in your hub
npm install

# Check it's available
npx mmdc --version
```

### Windows Path Issues

Always use `python -m kairos_ontology` (not `kairos-ontology.exe` directly).
The toolkit sanitizes filenames to be Windows-compatible.

---

*Generated for kairos-ontology-toolkit v1.9.0*
