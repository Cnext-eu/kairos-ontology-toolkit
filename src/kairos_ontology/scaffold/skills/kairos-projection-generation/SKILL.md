---
name: kairos-projection-generation
description: >
  Knowledge about generating downstream artifacts from ontologies.
  Covers all 5 projection targets and when to use each.
---

# Projection Generation Skill

You help users generate and understand projection artifacts.

## Available targets

| Target | Output | Use case |
|--------|--------|----------|
| **dbt** | SQL models + schema.yml | Data warehouse modeling |
| **neo4j** | Cypher schema scripts | Graph database setup |
| **azure-search** | Index + synonym map JSON | Azure AI Search configuration |
| **a2ui** | Message schema JSON | UI generation / form scaffolding |
| **prompt** | Compact + detailed context JSON | LLM prompt context injection |

## When to use each target

- **dbt**: When the ontology drives a data warehouse. Generates `silver` layer models with one SQL file per class and a schema.yml with column descriptions and tests.
- **neo4j**: When building a knowledge graph. Generates `CREATE CONSTRAINT` statements and relationship patterns.
- **azure-search**: When building a search index. Maps ontology properties to Azure Search field types with filters and facets.
- **a2ui**: When generating UI forms. Creates JSON schemas that describe the data structure for automatic UI rendering.
- **prompt**: When using the ontology as LLM context. Generates a compact version (entity→fields map) and a detailed version (with types, descriptions, relationships).

## CLI commands

```bash
# Generate all projections for all domains
kairos-ontology project

# Generate a single target
kairos-ontology project --target prompt

# Available targets: dbt, neo4j, azure-search, a2ui, prompt
```

## Output structure

Output is generated into `ontology-hub/output/<target>/`:

```
ontology-hub/output/
├── dbt/customer/models/silver/
│   ├── customer.sql
│   └── schema_customer.yml
├── neo4j/
│   └── customer-schema.cypher
├── azure-search/customer/indexes/
│   └── customer-index.json
├── a2ui/customer/schemas/
│   └── customer-message-schema.json
└── prompt/
    ├── customer-context.json          # compact
    └── customer-context-detailed.json  # verbose
```

## Property type mapping

| OWL/XSD Type | dbt | neo4j | Azure Search | a2ui |
|---|---|---|---|---|
| `xsd:string` | VARCHAR | String | Edm.String | string |
| `xsd:integer` | INTEGER | Integer | Edm.Int64 | integer |
| `xsd:decimal` | DECIMAL | Float | Edm.Double | number |
| `xsd:boolean` | BOOLEAN | Boolean | Edm.Boolean | boolean |
| `xsd:dateTime` | TIMESTAMP | DateTime | Edm.DateTimeOffset | date-time |
| `xsd:date` | DATE | Date | Edm.DateTimeOffset | date |

## Tips

- Generate `prompt` projection first to quickly verify the ontology structure is correct.
- Use `dbt` projection when you want to see the full property extraction including SHACL tests.
- Run all targets at once to catch issues specific to certain mappings.
