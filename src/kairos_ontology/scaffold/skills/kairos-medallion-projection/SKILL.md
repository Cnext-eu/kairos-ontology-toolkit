---
name: kairos-medallion-projection
description: >
  Expert guide for generating dbt Core staging and silver models as part of the
  medallion architecture. Covers the full bronze-to-silver pipeline using bronze
  vocabulary, SKOS mappings, and SHACL-derived dbt tests.
---

# Kairos Medallion Projection Skill

You are helping the user generate a **dbt Core project** that transforms bronze
(source system) data into silver (domain-conformed) tables. The transformation
is driven by:

- **Domain ontology** — OWL classes and properties defining the silver target schema
- **Bronze vocabulary** — `kairos-bronze:` descriptions of source system tables/columns
- **SKOS mappings** — semantic + technical column mappings between bronze and silver
- **SHACL shapes** — data quality constraints converted to dbt tests

## Prerequisites / Dependencies

Before running this projection, ensure the following artifacts exist in the hub:

- **Bronze vocabulary** must exist in `bronze/` — one `.ttl` file per source system
  describing tables and columns using the `kairos-bronze:` vocabulary. Use the
  `kairos-medallion-staging` skill to create these from source system documentation
  found in `sources/`.
- **Silver canonical schema** should exist — domain ontologies with silver projection
  annotations (`kairos-ext:` / `kairos-silver:` properties). Use the
  `kairos-medallion-silver` skill to design and generate the silver layer schema.
- **SKOS mappings** must exist in `mappings/` — one `.ttl` file per source-to-domain
  combination (e.g. `adminpulse-to-party.ttl`) linking bronze columns to silver
  domain properties using SKOS match predicates and `kairos-map:` transforms.

## Architecture

```
Bronze (source systems)          Silver (domain model)
┌───────────────────┐            ┌──────────────────┐
│ adminpulse.ttl    │──SKOS───→  │ party.ttl        │
│ erp-navision.ttl  │  mappings  │ client.ttl       │
└───────────────────┘            └──────────────────┘
        ↓                                ↓
  dbt sources.yml              dbt silver models
  dbt staging models           dbt schema + tests
```

**dbt layer mapping:**

| Medallion | dbt Layer | Materialization | What |
|-----------|-----------|----------------|------|
| Bronze | `sources` + `staging/` | views | Raw tables, rename + cast |
| Silver | `silver/` | tables | Domain entities, business logic |

---

## Phase 1 — Describe the bronze source system

### 1a — Create the bronze vocabulary file

In the hub's `bronze/` directory, create a TTL file per source system:

```bash
ls ontology-hub/bronze/
# If empty, copy the template:
cp "$(python -m kairos_ontology _scaffold_path)/ontology-hub/bronze/source-system.ttl.template" \
   ontology-hub/bronze/{system-name}.ttl
```

### 1b — Fill in source tables and columns

Use the `kairos-bronze:` vocabulary:

```turtle
@prefix bronze-ap: <https://your-company.com/bronze/adminpulse#> .
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .

bronze-ap:AdminPulse a kairos-bronze:SourceSystem ;
    rdfs:label "AdminPulse" ;
    kairos-bronze:connectionType "jdbc" ;
    kairos-bronze:database "AdminPulse_Prod" ;
    kairos-bronze:schema "dbo" .

bronze-ap:tblClient a kairos-bronze:SourceTable ;
    kairos-bronze:sourceSystem bronze-ap:AdminPulse ;
    kairos-bronze:tableName "tblClient" ;
    kairos-bronze:primaryKeyColumns "ClientID" ;
    kairos-bronze:incrementalColumn "ModifiedDate" .

bronze-ap:tblClient_ClientID a kairos-bronze:SourceColumn ;
    kairos-bronze:sourceTable bronze-ap:tblClient ;
    kairos-bronze:columnName "ClientID" ;
    kairos-bronze:dataType "int" ;
    kairos-bronze:nullable "false"^^xsd:boolean ;
    kairos-bronze:isPrimaryKey "true"^^xsd:boolean .
```

### Source table properties

| Property | Required | Description |
|----------|----------|-------------|
| `kairos-bronze:sourceSystem` | ✅ | Link to SourceSystem |
| `kairos-bronze:tableName` | ✅ | Physical table name |
| `kairos-bronze:primaryKeyColumns` | Recommended | Space-separated PK columns |
| `kairos-bronze:incrementalColumn` | Optional | Column for incremental extraction |
| `kairos-bronze:tableType` | Optional | `table`, `view`, `synonym`, `external` |

### Source column properties

| Property | Required | Description |
|----------|----------|-------------|
| `kairos-bronze:sourceTable` | ✅ | Link to SourceTable |
| `kairos-bronze:columnName` | ✅ | Physical column name |
| `kairos-bronze:dataType` | ✅ | Source data type (e.g. `int`, `nvarchar(255)`) |
| `kairos-bronze:nullable` | Recommended | Boolean |
| `kairos-bronze:isPrimaryKey` | Optional | Boolean |

---

## Phase 2 — Create SKOS mappings

### 2a — Create mapping file

In `mappings/`, create `{source}-to-{domain}.ttl`:

```turtle
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
@prefix bronze-ap: <https://your-company.com/bronze/adminpulse#> .
@prefix party: <https://your-company.com/ont/party#> .

# Table-level: which source table feeds which silver entity
bronze-ap:tblClient skos:exactMatch party:Client ;
    kairos-map:mappingType "direct" .

# Column-level: 1:1 with cast
bronze-ap:tblClient_ClientID skos:exactMatch party:clientId ;
    kairos-map:transform "CAST(source.ClientID AS STRING)" .

# Column-level: needs cleaning
bronze-ap:tblClient_Name skos:closeMatch party:clientName ;
    kairos-map:transform "TRIM(source.Name)" .

# Computed from multiple source columns
bronze-ap:tblClient_Address skos:narrowMatch party:addressLine1 ;
    kairos-map:transform "CONCAT(source.Street, ' ', source.Nr)" ;
    kairos-map:sourceColumns "Street Nr" .
```

### 2b — SKOS match semantics

| SKOS Property | Meaning for column mapping |
|---------------|---------------------------|
| `skos:exactMatch` | 1:1, same semantics |
| `skos:closeMatch` | 1:1 but needs transformation |
| `skos:narrowMatch` | Source is more specific → silver is broader |
| `skos:broadMatch` | Source is broader → filter/split required |
| `skos:relatedMatch` | Indirect — business logic / lookup needed |

### 2c — kairos-map: properties

| Property | Level | Description |
|----------|-------|-------------|
| `kairos-map:mappingType` | Table | `direct`, `split`, `merge`, `pivot`, `lookup` |
| `kairos-map:transform` | Column | SQL expression (`source.` prefix for columns) |
| `kairos-map:sourceColumns` | Column | Space-separated list of source columns used |
| `kairos-map:defaultValue` | Column | Default when source is NULL |
| `kairos-map:filterCondition` | Table | SQL WHERE fragment |
| `kairos-map:deduplicationKey` | Table | Columns for ROW_NUMBER() dedup |
| `kairos-map:deduplicationOrder` | Table | ORDER BY for dedup |

---

## Phase 3 — Run the projection

```bash
# Generate dbt project for all domains
python -m kairos_ontology project --target dbt

# Generate for a specific ontology
python -m kairos_ontology project --ontology ontology-hub/ontologies/client.ttl --target dbt
```

### Output structure

```
output/dbt/
  models/
    staging/{source}/
      _{source}__sources.yml         # dbt source definitions
      stg_{source}__{table}.sql      # Staging models (views)
    silver/{domain}/
      _{domain}__models.yml          # Schema + SHACL tests
      {entity}.sql                   # Silver entity models (tables)
  dbt_project.yml
  packages.yml                       # dbt_utils, dbt_expectations
```

---

## Phase 4 — Review and validate

### Check staging models

- Each source table should have a `stg_` model
- Staging models should only rename + cast (no joins, no aggregations)
- Materialized as views

### Check silver models

- Each domain class should have a silver entity model
- Column names must match the silver projector DDL output
- FK relationships preserved as model references

### Check dbt tests

- `not_null` from SHACL `sh:minCount 1`
- `unique` from SHACL `sh:maxCount 1`
- `accepted_values` from SHACL `sh:in`
- Regex patterns from SHACL `sh:pattern`
- Length constraints from SHACL `sh:minLength` / `sh:maxLength`

### Run dbt locally

```bash
cd output/dbt
dbt deps       # Install packages
dbt compile    # Validate SQL
dbt run        # Execute models (requires warehouse connection)
dbt test       # Run SHACL-derived tests
```

---

## Hub directory structure

```
ontology-hub/
  ontologies/
    party.ttl                      # Silver domain ontology
    party-silver-ext.ttl           # Silver projection annotations
  bronze/
    adminpulse.ttl                 # Bronze: source system schema
    erp-navision.ttl               # Bronze: another source
  mappings/
    adminpulse-to-party.ttl        # SKOS: AdminPulse → Party
    adminpulse-to-client.ttl       # SKOS: AdminPulse → Client
  shapes/
    client.shacl.ttl               # SHACL → dbt tests
  output/
    dbt/                           # Generated dbt project
    silver/                        # Generated silver DDL
```
