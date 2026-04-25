---
name: kairos-projection-generation
description: >
  Knowledge about generating downstream artifacts from ontologies.
  Covers all 7 projection targets and when to use each.
---

# Projection Generation Skill

You help users generate and understand projection artifacts.

## Before you start

0. **Quick toolkit version check** — run `python -m kairos_ontology update --check` once
   at the start of the session.  If it reports outdated files, run
   `python -m kairos_ontology update` and commit the refresh before doing any other work.
   See the kairos-toolkit-update skill for full upgrade steps.

## Available targets

| Target | Output | Use case |
|--------|--------|----------|
| **dbt** | SQL models + schema.yml | Data warehouse modeling |
| **neo4j** | Cypher schema scripts | Graph database setup |
| **azure-search** | Index + synonym map JSON | Azure AI Search configuration |
| **a2ui** | Message schema JSON | UI generation / form scaffolding |
| **prompt** | Compact + detailed context JSON | LLM prompt context injection |
| **silver** | DDL + ALTER + Mermaid ERD | MS Fabric / Delta Lake silver layer |
| **powerbi** | Star schema DDL + TMDL + DAX + ERD | Power BI / MS Fabric gold layer |
| **report** | HTML mapping reports | Business analyst mapping coverage review |

## When to use each target

- **dbt**: When the ontology drives a data warehouse using dbt Core. Generates a complete dbt project with staging models (from source systems via SKOS mappings), silver entity models, schema YAML with SHACL-derived tests, and project config. Requires source vocabulary files (`*.vocabulary.ttl`) in `integration/sources/{system-name}/` for source system descriptions and `model/mappings/{system-name}/*.ttl` for SKOS column mappings to domain ontology properties. The dbt projector scans `integration/sources/` recursively for `*.ttl` files with the `kairos-bronze:` namespace. See the **kairos-medallion-projection** skill.
- **neo4j**: When building a knowledge graph. Generates `CREATE CONSTRAINT` statements and relationship patterns.
- **azure-search**: When building a search index. Maps ontology properties to Azure Search field types with filters and facets.
- **a2ui**: When generating UI forms. Creates JSON schemas that describe the data structure for automatic UI rendering.
- **prompt**: When using the ontology as LLM context. Generates a compact version (entity→fields map) and a detailed version (with types, descriptions, relationships).
- **silver**: When building the silver layer of a medallion data platform (e.g. MS Fabric warehouse). Generates T-SQL DDL (`CREATE TABLE`), FK/UNIQUE constraints (`ALTER TABLE`), and a Mermaid ERD. Requires a `*-silver-ext.ttl` annotation file in `model/extensions/`. See the **kairos-medallion-silver** skill.

## CLI commands

```bash
# Generate all projections for all domains
python -m kairos_ontology project

# Generate a single target
python -m kairos_ontology project --target prompt

# Generate silver layer (requires *-silver-ext.ttl in model/extensions/)
python -m kairos_ontology project --target silver

# Available targets: dbt, neo4j, azure-search, a2ui, prompt, silver, powerbi
```

## Output structure

Output is generated into `ontology-hub/output/<target>/`:

```
ontology-hub/output/
├── medallion/
│   ├── dbt/customer/models/silver/
│   │   ├── customer.sql
│   │   └── schema_customer.yml
│   ├── silver/customer/
│   │   ├── customer-ddl.sql               # CREATE TABLE (T-SQL / MS Fabric)
│   │   ├── customer-alter.sql             # ALTER TABLE (UNIQUE + FK constraints)
│   │   ├── customer-erd.mmd               # Mermaid erDiagram
│   │   └── customer-erd.svg               # SVG render (requires Mermaid CLI)
│   └── powerbi/customer/
│       ├── customer-gold-ddl.sql          # Star schema CREATE TABLEs
│       ├── customer-gold-alter.sql        # FK constraint documentation
│       ├── customer-gold-erd.mmd          # Star schema Mermaid ERD
│       ├── customer-gold-erd.svg          # SVG render (requires Mermaid CLI)
│       └── semantic-model/                # TMDL + DAX measures
├── neo4j/
│   └── customer-schema.cypher
├── azure-search/customer/indexes/
│   └── customer-index.json
├── a2ui/customer/schemas/
│   └── customer-message-schema.json
└── prompt/
    ├── customer-context.json              # compact
    └── customer-context-detailed.json     # verbose
```

## Property type mapping

| OWL/XSD Type | dbt | neo4j | Azure Search | a2ui | silver (T-SQL) |
|---|---|---|---|---|---|
| `xsd:string` | VARCHAR | String | Edm.String | string | NVARCHAR(MAX) |
| `xsd:integer` | INTEGER | Integer | Edm.Int64 | integer | BIGINT |
| `xsd:decimal` | DECIMAL | Float | Edm.Double | number | DECIMAL(18,4) |
| `xsd:boolean` | BOOLEAN | Boolean | Edm.Boolean | boolean | BIT |
| `xsd:dateTime` | TIMESTAMP | DateTime | Edm.DateTimeOffset | date-time | DATETIME2 |
| `xsd:date` | DATE | Date | Edm.DateTimeOffset | date | DATE |

## Tips

- Generate `prompt` projection first to quickly verify the ontology structure is correct.
- Use `dbt` projection when you want to see the full property extraction including SHACL tests.
- Run all targets at once to catch issues specific to certain mappings.
- For `silver`: run the **kairos-medallion-silver** skill first to set up `kairos-ext:` annotations in `model/extensions/` before projecting.
