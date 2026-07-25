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
   Source vocab + prep policy ─┐
   Typed mappings             ├─► Governed domain + extension contracts
   OWL/Turtle domain model   ─┘      ├─ Silver dbt / DDL / parity
                                      ├─ Profile-driven Gold / Power BI
                                      ├─ Neo4j / Azure Search / A2UI
                                      └─ Reports and prompt context
```

**You should use this toolkit when you want to:**

- Govern source preparation, mappings, domain semantics, and target policy before generation
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
`kairos-ontology new-repo`.

### Projection

The process of transforming an ontology into a target-specific artifact (DDL,
dbt model, etc.). Each ontology can produce artifacts for multiple targets.

### Silver Layer

A shared logical authority rendered as **dbt SQL/schema YAML**, adapter-specific
**data warehouse DDL**, constraint/index metadata, quality links, parity manifests,
and **Mermaid ERD diagrams**. SCD1/SCD2 behavior requires complete runtime policy;
identity and physical keys are explicit rather than inferred.

---

## 3. Getting Started

### Prerequisites

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** — Python package and environment manager
- **Git**
- **GitHub CLI** (`gh`) — for repository creation and pull requests
- **Node.js** (optional) — for Mermaid SVG rendering

### Install the Toolkit

Hub repos manage the toolkit automatically via `uv sync`. After cloning a hub repo:

```bash
cd my-ontology-hub
.\setup-env.ps1          # Windows (PowerShell)
./setup-env.sh           # Linux / macOS
```

Or directly:

```bash
uv sync
```

This creates a `.venv` and installs the pinned toolkit version from `pyproject.toml`.

Run toolkit commands:

```bash
uv run kairos-ontology --version
uv run kairos-ontology validate
```

### Updating the Toolkit

Hub repos include a `[tool.kairos]` section in `pyproject.toml` that controls
which toolkit version is installed:

```toml
[tool.kairos]
channel = "stable"    # "stable" (default), "preview", or an explicit tag like "v2.16.0"
```

| Channel | Resolves to | Use case |
|---------|-------------|----------|
| `stable` | Latest GA release (e.g. `v2.17.0`) | Production hubs |
| `preview` | Latest pre-release (e.g. `v2.18.0-rc.1`) | Testing new features |
| `v2.16.0` | Explicit pinned version | Locked environments |

To upgrade the toolkit and refresh managed files:

```bash
# Upgrade to the channel's latest version
uv run kairos-ontology update --upgrade

# Refresh skill files and copilot-instructions
uv run kairos-ontology update
```

> **Testing a pre-release:** Set `channel = "preview"` in `pyproject.toml`, run
> `update --upgrade`, validate your projections, then switch back to `"stable"`.

---

## 4. Creating an Ontology Hub

An ontology hub is a Git repository that holds your domain ontologies and their
generated projections. Create one with a single command:

```bash
kairos-ontology new-repo \
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
kairos-ontology validate --all

# Syntax check only
kairos-ontology validate --syntax

# SHACL shapes only
kairos-ontology validate --shacl
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
kairos-ontology project --target all

# Single target
kairos-ontology project --target silver
kairos-ontology project --target dbt
kairos-ontology project --target neo4j
kairos-ontology project --target azure-search
kairos-ontology project --target a2ui
kairos-ontology project --target prompt
```

### Available Targets

| Target           | What it generates                                    | Use case                        |
|------------------|------------------------------------------------------|---------------------------------|
| **silver**       | Evidence-bound SQL/YAML + adapter DDL, metadata, ERD, parity manifest | Silver physical review |
| **dbt**          | Complete dbt project plus the same Silver physical/parity bundle | dbt transformation layer |
| **neo4j**        | Cypher schema (constraints, relationship types)      | Graph database                  |
| **azure-search** | JSON index definitions                               | Azure AI Search                 |
| **a2ui**         | JSON Schema for message payloads                     | UI generation                   |
| **prompt**       | Compact + detailed JSON context                      | LLM/AI assistant context        |
| **mdm-profile**  | Immutable, content-addressed MDM policy profile (JSON + review MD) | Master Data Management (opt-in; requires `{domain}-mdm-ext.ttl`; consumed by `kairos-mdm-runtime`) |

### Output Structure

```
ontology-hub/output/
├── medallion/dbt/
│   ├── models/silver/customer/       # authoritative dbt SQL + schema YAML
│   ├── analyses/customer/
│   │   └── customer-ddl.sql          # adapter physical DDL
│   ├── metadata/
│   │   ├── customer-silver-constraints.json
│   │   └── customer-silver-parity.json
│   └── docs/diagrams/
│       ├── customer/customer-erd.mmd
│       └── master-erd.mmd
├── medallion/powerbi/
│   └── customer/
│       ├── dbt/                       # profile-owned dimensional dbt
│       ├── Customer.SemanticModel/    # governed TMDL
│       ├── customer-gold-ddl.sql
│       ├── customer-gold-erd.mmd
│       └── customer-gold-product.json
├── neo4j/
│   └── customer-schema.cypher
├── prompt/
│   ├── customer-context.json
│   └── customer-context-detailed.json
└── reports/
```

---

## 8. Silver Layer Projection

The `silver` target is a thin facade over the same DD-110 pipeline as `dbt`:
`bind → normalize → shape → materialize → render`. It cannot generate an
ontology-only plausible schema. Imported source vocabulary, preparation policy,
validated mappings, identity/runtime policy, and bound model evidence are required.

One immutable `SilverModelSpec` drives dbt SQL, schema YAML, Fabric or Databricks DDL,
constraint/index metadata, quality/quarantine links, and ERD. The field-level parity
manifest hashes every representation; strict release blocks missing or drifted parity.

### Annotating Your Ontology for Silver

Create a `<domain>-silver-ext.ttl` file alongside your ontology:

```turtle
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
@prefix ex:         <https://mycompany.com/ontology/customer#> .

# Schema-level settings (on the owl:Ontology)
<https://mycompany.com/ontology/customer>
    kairos-ext:silverSchema "silver_customer" ;
    kairos-ext:namingConvention "camel-to-snake" .

# Per-class policy also references governed identity and DD-109 runtime resources.
ex:Customer
    kairos-ext:scdType "2" .

# Inheritance — S3 always flattens in silver; annotation preserved for Gold
ex:Client
    kairos-ext:inheritanceStrategy "discriminator" ;
    kairos-ext:discriminatorColumn "client_type" .

# Reference data (SCD Type 1; inlining is a Gold decision, never Silver)
ex:Country
    kairos-ext:isReferenceData "true"^^xsd:boolean ;
    kairos-ext:scdType "1" .

# Sensitive columns remain ordinary governed columns. Classification, access policy,
# and any decomposition must be explicit in the approved model and security contract.
```

### Physical and runtime contract

- Canonical types are normalized once and explicitly mapped by the Fabric or
  Databricks adapter profile.
- `_source_record_key` is the source/table-scoped record identity; there is no legacy
  alias.
- Entity IRI and integration identity columns are emitted only when the normalized
  identity strategy requires them.
- `_row_hash`, when selected, is canonical SHA-256 v1 lowercase hexadecimal text.
- SCD2 keeps `_business_valid_from/to` separate from `_system_from/to`; current and
  delete semantics use the governed current flag and `_is_deleted`.
- Temporal FKs explicitly state `current`, `as-of`, or `none`, cardinality, and
  missing/ambiguous/late-parent behavior.
- Constraints and index recommendations have deterministic adapter-bounded names.
  Metadata with `enforced: false` or `applied: false` is not an enforcement claim.
- Column order is exactly `SilverModelSpec.columns` in SQL, YAML, DDL, and metadata;
  no renderer may independently reorder or infer fields.

---

## 9. Gold Product Profiles

Gold projects consumption-oriented data products. Every Gold product names a registered
profile; the only v1 implementation is `dimensional-powerbi-v1`. Gold is not globally
defined as star schema, so future product shapes can be added without changing this
profile's dimensional guarantees.

The dimensional profile is fail-closed:

- only explicitly authored `fact`, `dimension`, and `bridge` tables are included;
- every table binds an exact actual Silver model and version;
- facts declare grain, transaction/snapshot type, version binding, and complete
  incremental/correction/late-arrival policy;
- dimensions declare current/history/dual exposure and source-version behavior;
- bridges declare grain, endpoints, endpoint columns, cardinality, and allocation;
- measures are first-class resources and never remove their base columns;
- calendars must be explicitly bounded and approved before any date/time-intelligence
  output is generated; and
- RLS/OLS requires a complete deny-by-default entitlement contract with positive and
  negative test evidence. Perspectives are navigation only.

The `powerbi` target runs the same Silver authority pipeline first and requires passing
Silver parity. It then emits dimensional dbt, Fabric or Databricks DDL, Power BI TMDL,
DAX, Mermaid ERD, and a governed product report. Fabric uses DirectLake. Databricks
downstream-Power-BI output is generated only under approved scoped deviations.

Strict release also requires approved measure state and evidence, approved calendar
state when present, complete security when present, matching adapter/TMDL compile
evidence, and deterministic artifact completeness. Projection never claims deployment,
runtime security enforcement, or data validation from syntax alone.

---

## 10. Projection Traceability

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

### Why This Matters

- **Forward upgrade**: ontology version changed → regenerate projections
- **Backward lookup**: found a DDL file → check the SQL header comment to know
  exactly which ontology version produced it
- **Drift detection**: CI can compare `owl:versionInfo` vs generated file headers
  to flag stale projections

---

## 11. Keeping Your Hub Up to Date

When a new toolkit version is released, update your hub:

```bash
# 1. Update the toolkit (uses .whl from GitHub Releases)
kairos-ontology update --upgrade

# 2. Refresh managed files (skills, copilot-instructions, kairos-ext.ttl)
kairos-ontology update

# 3. Regenerate projections
kairos-ontology project --target all

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
party_sk STRING   -- FK → silver_party.party(party_sk)
```

The FK is tracked in `*-silver-constraints.json` and ERD. Its metadata states the
adapter capability/deviation and `enforced` value explicitly; generated DDL never
claims enforcement that the adapter does not provide.

### Master ERD

After projecting, a `master-erd.mmd` is generated that merges all per-domain
ERDs into one cross-domain diagram — showing all tables and relationships across
all your domains.

---

## 12. Workflow Summary

```
┌─────────────────────────────────────────────────────────────┐
│  1. CREATE HUB                                              │
│     kairos-ontology new-repo --name my-hub        │
│                                                             │
│  2. MODEL                                                   │
│     Write / edit .ttl ontology files in ontologies/         │
│     Add silver annotations in *-silver-ext.ttl              │
│                                                             │
│  3. VALIDATE                                                │
│     kairos-ontology validate --all                │
│                                                             │
│  4. PROJECT                                                 │
│     kairos-ontology project --target all          │
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

> **Prefix all commands with `uv run`** (e.g., `uv run kairos-ontology validate --all`)

| Command | Description |
|---------|-------------|
| `kairos-ontology new-repo` | Create a new ontology hub repository |
| `kairos-ontology init` | Initialize a domain ontology in an existing hub |
| `kairos-ontology validate --all` | Validate all ontologies |
| `kairos-ontology project --target all` | Generate all projections |
| `kairos-ontology project --target silver` | Generate silver layer only |
| `kairos-ontology update` | Refresh managed toolkit files |
| `kairos-ontology catalog-test` | Test XML catalog resolution |

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

Always use `uv run kairos-ontology` to invoke the CLI. This uses the repo's
isolated `.venv` without needing manual activation.
The toolkit sanitizes filenames to be Windows-compatible.

---

*Generated for kairos-ontology-toolkit v1.9.0*
