---
name: kairos-design-source
description: >
  Expert guide for creating bronze vocabulary descriptions from source system
  reference documentation. Reads API specs, SQL DDL, sample data from the
  sources/ folder and generates kairos-bronze: TTL files alongside the source docs.
---

# Kairos Medallion Staging Skill

You are helping the user create a **bronze vocabulary description** for a source
system. The bronze vocabulary uses the `kairos-bronze:` namespace to describe
tables, columns, and data types from the source system — enabling downstream
dbt silver model generation.

## Prerequisites

- Source system reference docs should be placed in `ontology-hub/integration/sources/{system-name}/`
- The `kairos-bronze:` vocabulary is defined in the toolkit (`kairos-bronze.ttl`)

## Alternative input: CSV/Excel flat files

If source documentation is available as flat files (CSV exports, Excel workbooks),
use `import-flatfile` instead of manually creating the vocabulary:

```bash
kairos-ontology import-flatfile --from exports/my-data.csv --system my-source
kairos-ontology import-flatfile --from exports/workbook.xlsx --system my-source
kairos-ontology import-flatfile --from exports/ --system my-source  # directory of files
```

This auto-generates `_manifest.yaml`, per-table YAML, and `.samples.yaml` files —
then run `import-source --from integration/sources/{system}/` to produce the TTL.

## Architecture

```
integration/sources/{system}/
┌──────────────────────┐
│ sql-ddl/             │
│ api-specs/           │  AI skill generates
│ samples/             │──────────────────→  {system}.vocabulary.ttl
│ README.md            │                     (in same folder)
└──────────────────────┘
```

---

## Phase 1 — Verify source documentation

### 1a — Check for source system folder

```bash
ls ontology-hub/integration/sources/
```

If the system folder doesn't exist yet, create it:

```bash
mkdir -p ontology-hub/integration/sources/{system-name}
cp ontology-hub/integration/sources/source-system-template/README.md \
   ontology-hub/integration/sources/{system-name}/README.md
```

### 1b — Inventory reference materials

Check what documentation is available in the source folder:

| Material | Location | Priority |
|----------|----------|----------|
| SQL DDL (CREATE TABLE) | `sql-ddl/*.sql` | ⭐ Best — exact schema |
| API specs (OpenAPI/Swagger) | `api-specs/*.yaml` or `*.json` | ⭐ Good — typed endpoints |
| Sample data (CSV/JSON) | `samples/*` | 🔶 Useful — infer types |
| Database documentation | `docs/*` | 🔶 Context — business meaning |
| Notes / observations | `README.md`, `notes.md` | 📝 Context |

### 1c — Review the source system README

Read `ontology-hub/integration/sources/{system-name}/README.md` for:
- System name and version
- Connection type (jdbc, odbc, api, file, lakehouse)
- Database and schema names
- Owner and contact info
- Any known quirks or limitations

---

## Phase 2 — Extract schema information

### 2a — From SQL DDL

If `sql-ddl/` contains CREATE TABLE statements, extract:
- Table names, column names, data types
- Primary keys, foreign keys
- Nullable constraints
- Default values

### 2b — From API specs

If `api-specs/` contains OpenAPI/Swagger files, extract:
- Resource/endpoint names → map to tables
- Request/response properties → map to columns
- Property types → map to data types
- Required properties → map to NOT NULL

### 2c — From sample data

If `samples/` contains CSV or JSON files, infer:
- Column names from headers / keys
- Data types from values (inspect patterns)
- Nullable from presence of empty values

### 2d — From enriched schema YAML (preferred)

If the vocabulary was generated via `import-source --enrich` from an `extract-schema`
output, the TTL already contains rich inference annotations. **Check these first** before
manual documentation — they are machine-derived but highly informative:

| Annotation | What it tells you | Design action |
|---|---|---|
| `kairos-bronze:suggestedEnum true` | Low-cardinality column (≤25 distinct values) | Propose as `skos:ConceptScheme` with values as concepts |
| `kairos-bronze:enumValues "A | B | C"` | The actual distinct values observed | Use as concept labels in the scheme |
| `kairos-bronze:formatHint "email"` | Samples match a known format pattern | Suggest `xsd:string` with format constraint; propose dedicated property name |
| `kairos-bronze:formatHint "date"` | Date-like values stored as string | Suggest `xsd:date` or `xsd:dateTime` range in domain model |
| `kairos-bronze:formatHint "uuid"` | UUID identifiers | Likely a natural key or foreign key reference |
| `kairos-bronze:suggestedForeignKey <uri>` | Column likely references another table | Propose as `owl:ObjectProperty` linking to the target entity |
| `kairos-bronze:fkConfidence "high"` | Name-based match (strong signal) | High confidence — present as default recommendation |
| `kairos-bronze:fkConfidence "medium"` | Cardinality-based match (weaker signal) | Present as suggestion, ask user to confirm |
| `kairos-bronze:rowCount N` | Table size | Prioritize high-volume tables for modeling |
| `kairos-bronze:sampleValues "val1 | val2 | val3"` | Actual data samples | Show in prompts for user to validate semantics |
| `rdfs:comment "Examples: ..."` | Concrete value examples | Use to write meaningful property descriptions |

**Workflow when enrichment annotations exist:**

1. List all tables sorted by `rowCount` (high → low) for prioritization
2. For each table, highlight:
   - Columns with `suggestedEnum` → ask user: "Should this be a code list?"
   - Columns with `suggestedForeignKey` → ask user: "Does this reference [target]?"
   - Columns with `formatHint` → propose appropriate `xsd:` type
3. Use `sampleValues` in all interactive prompts so user can validate without
   querying the database
4. After user confirms/rejects each suggestion, generate the enriched vocabulary

---

## Phase 3 — Generate the bronze vocabulary TTL

### 3a — Create the output file

Create `ontology-hub/integration/sources/{system-name}/{system-name}.vocabulary.ttl`:

```bash
# Create from scratch in the source system folder following the kairos-bronze: vocabulary.
touch ontology-hub/integration/sources/{system-name}/{system-name}.vocabulary.ttl
```

The bronze vocabulary file lives alongside the source system documentation it describes.

### 3b — Fill in the source system

```turtle
@prefix bronze-{prefix}: <https://{company-domain}/bronze/{system-name}#> .
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .

bronze-{prefix}:{SystemName} a kairos-bronze:SourceSystem ;
    rdfs:label "{System Display Name}" ;
    kairos-bronze:connectionType "{jdbc|odbc|api|file|lakehouse}" ;
    kairos-bronze:database "{DatabaseName}" ;
    kairos-bronze:schema "{SchemaName}" .
```

### 3c — Add tables

For each table/resource extracted in Phase 2:

```turtle
bronze-{prefix}:{tableName} a kairos-bronze:SourceTable ;
    rdfs:label "{tableName}" ;
    kairos-bronze:sourceSystem bronze-{prefix}:{SystemName} ;
    kairos-bronze:tableName "{tableName}" ;
    kairos-bronze:primaryKeyColumns "{PK1} {PK2}" ;
    kairos-bronze:incrementalColumn "{ModifiedDate}" .
```

### 3d — Add columns

For each column/property:

```turtle
bronze-{prefix}:{tableName}_{columnName} a kairos-bronze:SourceColumn ;
    kairos-bronze:sourceTable bronze-{prefix}:{tableName} ;
    kairos-bronze:columnName "{columnName}" ;
    kairos-bronze:dataType "{dataType}" ;
    kairos-bronze:nullable "{true|false}"^^xsd:boolean ;
    kairos-bronze:isPrimaryKey "{true|false}"^^xsd:boolean .
```

### Data type mapping reference

| Source (SQL Server) | Source (API/JSON) | kairos-bronze:dataType |
|--------------------|--------------------|----------------------|
| `int` | `integer` | `"int"` |
| `bigint` | `integer (int64)` | `"bigint"` |
| `nvarchar(N)` | `string` | `"nvarchar(N)"` |
| `varchar(N)` | `string` | `"varchar(N)"` |
| `datetime2` | `date-time` | `"datetime2"` |
| `date` | `date` | `"date"` |
| `bit` | `boolean` | `"bit"` |
| `decimal(P,S)` | `number` | `"decimal(P,S)"` |
| `uniqueidentifier` | `string (uuid)` | `"uniqueidentifier"` |

---

## Phase 4 — Validate the output

### 4a — Syntax check

```bash
python -m kairos_ontology validate
```

### 4b — Completeness check

Verify:
- [ ] Every table from the source has a `kairos-bronze:SourceTable` entry
- [ ] Every column has a `kairos-bronze:SourceColumn` entry
- [ ] All primary key columns are marked with `kairos-bronze:isPrimaryKey "true"`
- [ ] Data types are filled in for all columns
- [ ] The source system README in `integration/sources/` is up to date

---

## Phase 5 — Next steps

After the bronze vocabulary is complete:

1. **Create SKOS mappings** — invoke the **kairos-design-mapping** skill to interactively
   map source columns to domain ontology properties in `model/mappings/`
2. **Design silver annotations** — invoke the **kairos-design-silver** skill
   to create extension annotations for the silver layer
3. **Generate output** — invoke the **kairos-execute-project** skill to produce
   dbt models, silver DDL, and ERDs

See the **kairos-design-silver** skill for annotation design guidance.

---

## Source system folder structure reference

```
ontology-hub/integration/sources/{system-name}/
  README.md                        # System description, owner, connection details
  {system-name}.vocabulary.ttl         # Source vocabulary (kairos-bronze: TTL)
  sql-ddl/                         # CREATE TABLE exports from the source database
  api-specs/                       # OpenAPI / Swagger specification files
  samples/                         # Sample data files (CSV, JSON, XML)
  docs/                            # Additional documentation (ERD, data dictionary)
  notes.md                         # Free-form observations and notes
```

---

## Session Management

> **MANDATORY:** Every source design session MUST produce a session file that
> captures what was documented, what gaps remain, and design decisions.

### On start — Check for existing session

```
ontology-hub/.sessions-design/
  └── source-{system-name}-{YYYY-MM-DD}.md
```

If a previous session exists, ask the user whether to continue or start fresh.

### Session file format

Save to `ontology-hub/.sessions-design/source-{system-name}-{YYYY-MM-DD}.md`:

```markdown
# Source Design Session: {system-name}

**Started:** {ISO-8601}
**Last updated:** {ISO-8601}
**Status:** Complete | In Progress
**Toolkit version:** {version}

## Tables Documented

| # | Table | Columns | Data Types Verified | Notes |
|---|---|---|---|---|
| 1 | {table_name} | {count} | ✅/❌ | {any notes} |

## Deferred / TODO

| # | Table/Column | Item | Reason | Resolve via |
|---|---|---|---|---|
| 1 | {name} | {what is missing} | {why deferred} | kairos-design-source |

## Design Decisions

| # | Question | Decision | Rationale |
|---|---|---|---|
| 1 | {question} | {choice made} | {why} |

## Source Evidence Gaps

| # | Gap | Impact | Resolution |
|---|---|---|---|
| 1 | {what documentation is missing} | {which mappings/projections are blocked} | {how to resolve} |
```

### Saving rules

- **Auto-save** after each table vocabulary is confirmed
- Record tables that could not be fully documented with reasons
- On pause/completion, list remaining gaps and their downstream impact

---

## Related skills

| When you need | Invoke |
|---|---|
| **Analyse sources against reference models (next step!)** | CLI: `kairos-ontology analyse-sources` |
| Design/modify domain ontology classes and properties | **kairos-design-domain** |
| Design silver layer (DDL, SCD, FK annotations) | **kairos-design-silver** |
| Design gold layer (Power BI star schema, measures) | **kairos-design-gold** |
| Map source columns to domain properties | **kairos-design-mapping** |
| Run projections after source vocab is complete | **kairos-execute-project** |

## Next Step — Pre-Model Analysis

After all source vocabularies have been created, run the **analyse-sources** command
to understand which reference model domains each source contributes to:

```bash
kairos-ontology analyse-sources \
  --sources integration/sources \
  --ref-models ontology-reference-models \
  --output integration/sources/_analysis
```

This produces `{system}-affinity.yaml` files with `domain_contributions` — a ranked
list of reference model domains each source feeds, with per-table contribution scores
and column-level match suggestions. The **kairos-design-domain** skill uses this
output as a mandatory prerequisite (Step 0a) to scope which tables to model per domain.
