---
name: kairos-help
description: >
  Comprehensive guide to the Kairos Ontology Toolkit — design philosophy,
  hub structure, projections, CLI commands, and best practices.
  Invoke whenever a user asks "how does Kairos work?" or needs orientation.
---

# Kairos Ontology Toolkit — Help & Reference

You are a Kairos ontology assistant. Use this skill when users need orientation,
ask how the toolkit works, want to understand design choices, or need guidance
on best practices.

## 1  Design Philosophy

### 1.1  Ontology-Driven Architecture

Everything starts from the **domain ontology** (OWL/Turtle `.ttl` files).
All downstream artifacts — database schemas, dbt models, search indexes,
semantic models, documentation — are **generated (projected)** from the
ontology. The ontology is the single source of truth.

### 1.2  Shift-Left Principle

> **Never edit generated output. Always change the model and regenerate.**

When a projection output doesn't match requirements, the fix belongs in the
ontology or its annotations — never in the generated files. This is the
"shift-left" principle: push decisions as far upstream as possible.

**Examples:**

| Desired outcome | ❌ Wrong approach | ✅ Right approach |
|---|---|---|
| A field must be required / NOT NULL | Add a `not_null` dbt test manually | Add `sh:minCount 1` in the SHACL shape → dbt test is generated automatically |
| A column needs a specific SQL type | Edit the generated DDL | Add `kairos-ext:sqlType "DECIMAL(18,4)"` on the property in an extension file |
| A table should be a fact table | Rename the generated model | Add `kairos-ext:goldTableType "fact"` on the class in the gold extension |
| A measure needs YTD calculation | Write DAX in the TMDL output | Add `kairos-ext:generateTimeIntelligence true` on the ontology |
| A field should be hidden from some users | Edit the RLS role manually | Add `kairos-ext:olsRestricted true` on the property |

### 1.3  Separation of Concerns

The toolkit enforces clean boundaries:

| Layer | Owns | Does NOT own |
|---|---|---|
| **Domain ontology** | Classes, properties, relationships, business vocabulary | Physical storage, BI measures, integration logic |
| **Extension files** (`*-ext.ttl`) | Physical annotations (SQL types, table types, gold schema) | Business semantics |
| **SHACL shapes** | Validation constraints (required fields, value ranges, patterns) | Downstream schema |
| **Bronze vocabulary** | Source system field descriptions | Domain meaning |
| **Mappings** | Source-to-domain column alignment (SKOS + kairos-map:) | Transform implementation |
| **Projections** | Generated artifacts (dbt, DDL, TMDL, indexes) | — (read-only output) |

### 1.4  dbt vs Semantic Model Split

For the medallion gold layer, follow this rule:

- **dbt = data logic** — cleansing, joins, conformed dimensions, fact tables, surrogate keys, incremental loads, data quality tests, documentation, lineage
- **Semantic model = business metrics** — DAX measures, relationships, hierarchies, RLS/OLS, perspectives, calculation groups, business-friendly names
- **Reports = visuals only** — consume semantic model measures; no business logic in reports

The toolkit enforces this: properties with `kairos-ext:measureExpression` are
**skipped** in dbt SQL and rendered **only** in TMDL/DAX.

## 2  Hub Folder Structure

A Kairos ontology hub repository follows this layout:

```
ontology-hub/
├── model/                          # Domain knowledge (ontologies + shapes)
│   ├── ontologies/                 # OWL/Turtle domain ontologies
│   │   ├── _master.ttl             # Imports all domains
│   │   ├── sales.ttl               # Example domain
│   │   └── hr.ttl
│   ├── shapes/                     # SHACL validation shapes
│   │   ├── sales-shapes.ttl
│   │   └── hr-shapes.ttl
│   ├── extensions/                 # Physical / BI annotations
│   │   ├── sales-silver-ext.ttl    # Silver-layer annotations (R1–R16)
│   │   ├── sales-gold-ext.ttl      # Gold-layer annotations (G1–G8)
│   │   └── hr-silver-ext.ttl
│   └── mappings/                   # Source-to-domain mappings (SKOS + kairos-map:)
│       └── sales-erp-mapping.ttl
├── integration/                    # Source system documentation
│   └── sources/                    # API specs, SQL DDL, sample data
│       └── erp/
│           ├── README.md
│           └── schema.sql
├── output/                         # Generated artifacts (DO NOT EDIT)
│   ├── medallion/                  # Medallion architecture outputs
│   │   ├── dbt/                    # dbt Core project (silver + gold)
│   │   │   ├── models/
│   │   │   ├── analyses/
│   │   │   └── docs/
│   │   └── gold/                   # Power BI semantic model (TMDL)
│   │       └── {Domain}.SemanticModel/
│   │           └── definition/
│   │               ├── model.tmdl
│   │               ├── tables/
│   │               ├── relationships/
│   │               ├── roles/
│   │               ├── perspectives/
│   │               └── calculationGroups/
│   ├── neo4j/                      # Cypher constraints + import scripts
│   ├── azure-search/               # Azure AI Search index definitions
│   ├── a2ui/                       # A2UI navigation model
│   └── prompt/                     # LLM-optimised ontology descriptions
├── .github/
│   ├── skills/                     # Copilot skills for this hub
│   └── copilot-instructions.md
├── package.json                    # Hub metadata
└── README.md                       # Domain catalog
```

### Key rules

- **`model/`** is the source of truth. All changes start here.
- **`output/`** is generated. Never edit files here — regenerate with `kairos-ontology project`.
- **`integration/`** holds source system reference docs used by the bronze vocabulary skill.
- **`_master.ttl`** must import every domain ontology.

## 3  Available Projections

The toolkit supports 8 projection targets:

| Target | Command flag | What it generates | When to use |
|---|---|---|---|
| `dbt` | `--target dbt` | dbt Core project (silver → gold SQL models, schema YAML, docs) | Data warehouse / lakehouse pipeline |
| `silver` | `--target silver` | Spark SQL DDL, Mermaid ERD, ALTER TABLE FK scripts for MS Fabric Warehouse | Silver-layer physical schema |
| `powerbi` | `--target powerbi` | Power BI TMDL semantic model (tables, measures, relationships, RLS, perspectives) | BI semantic layer |
| `neo4j` | `--target neo4j` | Cypher constraints, indexes, and import scripts | Graph database |
| `azure-search` | `--target azure-search` | Azure AI Search index definitions (JSON) | Search / RAG scenarios |
| `a2ui` | `--target a2ui` | A2UI navigation model | UI integration |
| `prompt` | `--target prompt` | LLM-optimised ontology descriptions | AI / copilot context |
| `report` | `--target report` | HTML mapping report with data flow diagrams and coverage dashboards | Documentation / governance |
| `all` | `--target all` | All of the above | Full regeneration |

## 4  CLI Commands

```bash
# Validate syntax + SHACL shapes
kairos-ontology validate [--ontologies PATH] [--shapes PATH]

# Generate projections
kairos-ontology project [--ontologies PATH] [--shapes PATH] [--target TARGET]

# Initialise a new hub from scaffold
kairos-ontology init [--name NAME]

# Create a new hub repository
kairos-ontology new-repo [--name NAME]

# Update managed files to installed toolkit version
kairos-ontology update

# Upgrade toolkit to channel's latest version (stable/preview)
kairos-ontology update --upgrade

# Preview what update would change
kairos-ontology update --check

# Migrate flat layout → grouped layout
kairos-ontology migrate

# Run catalog tests
kairos-ontology catalog-test
```

Default paths:
- `--ontologies` → `ontology-hub/model/ontologies`
- `--shapes` → `ontology-hub/model/shapes`

## 5  Annotation Namespaces

| Prefix | Namespace | Purpose |
|---|---|---|
| `kairos-ext:` | `https://kairos.cnext.eu/ext#` | Physical annotations (SQL types, gold table types, BI features) |
| `kairos-bronze:` | `https://kairos.cnext.eu/bronze#` | Source system vocabulary |
| `kairos-map:` | `https://kairos.cnext.eu/map#` | Source-to-domain column mappings |

### Common `kairos-ext:` annotations

| Annotation | Level | Effect |
|---|---|---|
| `goldTableType` | Class | `"fact"`, `"dimension"`, `"bridge"` — controls gold table naming and SCD behaviour |
| `goldSchema` | Class | Target schema for the gold table |
| `measureExpression` | Property | DAX expression → rendered in TMDL only, skipped in dbt |
| `sqlType` | Property | Override SQL column type |
| `generateDateDimension` | Ontology | `true` → auto-generates `dim_date` with Calendar hierarchy |
| `generateTimeIntelligence` | Ontology | `true` → generates YTD/QTD/MTD/PY/YoY% calculation group |
| `perspective` | Class | Name of the perspective this table belongs to |
| `incrementalColumn` | Class | Column for incremental loads (dbt `is_incremental()` filter) |
| `olsRestricted` | Property | `true` → column is restricted via Object-Level Security |

## 6  Common Workflows

### Adding a new domain

1. Create `model/ontologies/new-domain.ttl` (OWL classes + properties)
2. Add `owl:imports` in `_master.ttl`
3. Create `model/shapes/new-domain-shapes.ttl` (SHACL constraints)
4. Run `kairos-ontology validate` → fix any issues
5. Run `kairos-ontology project --target all` → generates all outputs
6. Commit model + output together

### Changing a projection output

1. **Identify what needs to change** in the output
2. **Trace back** to the ontology class/property or annotation
3. **Modify the model** (ontology, shape, or extension file)
4. **Regenerate**: `kairos-ontology project --target <target>`
5. **Verify** the output matches expectations
6. Commit

### Adding silver/gold annotations

1. Create `model/extensions/{domain}-silver-ext.ttl` or `{domain}-gold-ext.ttl`
2. Use the appropriate namespace (`kairos-ext:`) to annotate classes/properties
3. Regenerate: `kairos-ontology project --target dbt` (or `powerbi`)

## 7  Ontology Modelling Best Practices

| Practice | Guideline |
|---|---|
| **Naming** | PascalCase for classes (`SalesOrder`), camelCase for properties (`orderDate`) |
| **Labels** | Every `owl:Class` must have `rdfs:label` and `rdfs:comment` |
| **Properties** | Every property must have `rdfs:domain`, `rdfs:range`, and `rdfs:label` |
| **Ontology header** | Must declare `owl:Ontology` with `rdfs:label` and `owl:versionInfo` |
| **Namespaces** | Use HTTP/HTTPS URIs with `#` or `/` separator |
| **SHACL for constraints** | Required fields → `sh:minCount 1`; patterns → `sh:pattern`; value ranges → `sh:minInclusive` / `sh:maxInclusive` |
| **Extension files for physical** | SQL types, table types, BI annotations go in `*-ext.ttl`, not in the domain ontology |

## 8  Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Validation fails with "No owl:Ontology" | Missing ontology header | Add `<uri> a owl:Ontology ; rdfs:label "..." ; owl:versionInfo "1.0" .` |
| dbt model missing a column | Property lacks `rdfs:domain` | Add `rdfs:domain` pointing to the class |
| Gold table named wrong | Missing `kairos-ext:goldTableType` | Add annotation in extension file |
| TMDL measure not generated | Missing `kairos-ext:measureExpression` | Add DAX expression annotation |
| SHACL validation passes but dbt test fails | Shape constraint mismatch | Align SHACL `sh:minCount` with expected NOT NULL behaviour |

## 9  Keeping This Skill Up to Date

This skill must be updated whenever **new core functionality** is added to the
toolkit — new projections, new annotations, new CLI commands, or new design
patterns. The PR checklist in `SC-merge-pr` includes a reminder to verify this.

---

*This skill is auto-distributed to hub repositories via the scaffold system.
Changes here are mirrored to `src/kairos_ontology/scaffold/skills/kairos-help/`.*
