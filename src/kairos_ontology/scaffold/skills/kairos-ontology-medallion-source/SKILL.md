---
name: kairos-ontology-medallion-source
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

1. **Create SKOS mappings** in `model/mappings/{system-name}/` to link source columns to domain ontology properties
2. **Run the medallion projection** to generate dbt silver models:
   ```bash
   python -m kairos_ontology project --target dbt
   ```

See the **kairos-ontology-medallion-silver** skill for the full bronze-to-silver pipeline.

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
