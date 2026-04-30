# Data Platform & dbt Architecture

## Overview

This document describes the layer separation between the **data platform**
(landing zone + bronze) and the **dbt transformation pipeline** (silver + gold)
that is generated from the ontology hub.

```
┌──────────────────────────────────────────────────────────────┐
│  LANDING ZONE (data platform — outside dbt)                  │
│                                                              │
│  Raw data (CSV, JSON, API exports, flat files)               │
│       ↓  ingestion tools (ADF, Fabric pipelines, etc.)       │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│  BRONZE (data platform — outside dbt)                        │
│                                                              │
│  Tabular representation of raw system data                   │
│  1:1 with source tables, no transforms                       │
│  Examples: adminpulse.api.Relation, harmoney.platform.Entity │
└──────────────────────────────┬───────────────────────────────┘
                               │  dbt {{ source() }} references
                               ▼
┌──────────────────────────────────────────────────────────────┐
│  SILVER — canonical domain (models/silver/{domain}/)         │
│  dbt starts here                                             │
│  Ontology-driven: SKOS mappings + silver-ext schema          │
└──────────────────────────────┬───────────────────────────────┘
                               │  {{ ref('...') }}
                               ▼
┌──────────────────────────────────────────────────────────────┐
│  GOLD — dimensional / star-schema (models/gold/{domain}/)    │
│  Fact/dimension tables for Power BI consumption              │
└──────────────────────────────────────────────────────────────┘
```

---

## Layer Details

### Landing Zone (data platform — outside dbt)

| Aspect | Detail |
|--------|--------|
| **Owner** | Data platform team (ADF / Fabric pipelines / other tools) |
| **Purpose** | Ingest raw data (files, APIs) and deliver into bronze |
| **Input** | Raw files: CSV, JSON, API exports, flat files |
| **Output** | Raw data loaded into bronze tables |

The landing zone handles **ingestion only** — getting raw data from source
systems into the platform. This is managed entirely by platform tools.

---

### Bronze (data platform — outside dbt)

| Aspect | Detail |
|--------|--------|
| **Owner** | Data platform team (ADF / Fabric pipelines / other tools) |
| **Purpose** | Tabular representation of raw system data |
| **Format** | Delta/Parquet tables in lakehouse / warehouse |
| **Naming** | `{source_system}.{schema}.{TableName}` |
| **Content** | 1:1 with source system tables, no business transforms |

Bronze tables are the **tabular output of the landing zone pipeline**. They
mirror the source system structure exactly. No renaming, no casting, no
business logic — just raw data in tabular format.

**Bronze is NOT managed by dbt.** It is produced by platform ingestion tools.

#### Single Source of Truth

The **`*.vocabulary.ttl`** file in the ontology hub is the authoritative
definition of bronze table structure (tables, columns, data types, keys).

The dbt `_sources.yml` files are **minimal references only** — they declare
the database, schema, and table names so dbt can generate `{{ source() }}`
references. They do **not** duplicate column-level documentation or tests
that already exist in the vocabulary TTL.

| Artifact | Role | Column-level detail? |
|----------|------|---------------------|
| `integration/sources/{sys}/*.vocabulary.ttl` | **Authoritative** — full column definitions, types, keys | ✅ Yes |
| `models/silver/_sources.yml` | **Minimal dbt reference** — table names + connection only | ❌ No |

> **Rule**: If you need to know what columns a bronze table has, look at
> the vocabulary TTL — not the dbt sources YAML.

---

### Silver (dbt starts here — ontology-driven)

| Aspect | Detail |
|--------|--------|
| **Folder** | `models/silver/{domain}/` |
| **Materialization** | `table` |
| **Schema** | `silver_{domain}` |
| **Naming** | `{entity}.sql` (matches ontology class name in snake_case) |
| **Purpose** | Map bronze source tables → canonical domain entities |

Silver is the **first dbt layer**. It reads directly from bronze tables via
`{{ source() }}` and applies the **ontology SKOS mappings** to transform
source-system data into canonical domain entities.

Silver models handle:
- Column renaming (source camelCase → snake_case)
- Type casting
- Combining multiple bronze sources into domain entities
- Surrogate key generation

Each silver table has:
- `{entity}_sk` — Surrogate key (hash or sequence)
- `{entity}_iri` — Ontology IRI for graph interop
- Domain properties matching the silver DDL

> **Ontology hub artifacts**:
> - Mappings: `model/mappings/{source}/{source}-to-{domain}.ttl`
> - Schema: `model/extensions/{domain}-silver-ext.ttl`
> - DDL: `output/medallion/silver/{domain}-silver.sql`
> - ERD: `output/medallion/silver/{domain}-silver-erd.md`

**Examples:**
```
models/silver/party/party.sql
models/silver/party/legal_entity.sql
models/silver/party/natural_person.sql
```

---

### Gold (dbt — dimensional)

| Aspect | Detail |
|--------|--------|
| **Folder** | `models/gold/{domain}/` |
| **Materialization** | `table` |
| **Schema** | `gold_{domain}` |
| **Naming** | `dim_{entity}.sql`, `fact_{entity}.sql` |
| **Purpose** | Star-schema tables optimized for Power BI / DirectLake |

> **Ontology hub artifacts**:
> - Schema: `model/extensions/{domain}-gold-ext.ttl`
> - DDL: `output/medallion/gold/`

---

## How Ontology Artifacts Map to Each Layer

| Ontology Hub Artifact | Layer |
|-----------------------|-------|
| `integration/sources/{sys}/*.vocabulary.ttl` | Documents **Bronze** structure (for mapping purposes) |
| `model/mappings/{sys}/{sys}-to-{domain}.ttl` | Drives **Silver** mapping logic |
| `model/extensions/{domain}-silver-ext.ttl` | Defines **Silver** schema |
| `model/extensions/{domain}-gold-ext.ttl` | Defines **Gold** schema |
| `model/ontologies/{domain}.ttl` | Domain semantics (silver + gold) |

---

## Naming Conventions Summary

| Layer | Pattern | Example |
|-------|---------|---------|
| Bronze (platform) | `{source}.{schema}.{Table}` | `adminpulse.api.Relation` |
| Silver (dbt) | `{entity}` in `silver/{domain}/` | `silver/party/party.sql` |
| Gold (dbt) | `dim_{entity}` / `fact_{entity}` | `gold/service/dim_party.sql` |

---

## Materialization Rules

| Layer | Default | Rationale |
|-------|---------|-----------|
| Bronze | N/A (platform-managed) | Not a dbt layer |
| Silver | `table` | Canonical entities, queried by downstream |
| Gold | `table` | BI consumption, DirectLake requires tables |

---

## Where Does the Ontology Conversion Start?

**The ontology/dbt conversion boundary is between Bronze and Silver.**

- **Bronze** is source-system-centric — it uses the vocabulary and structure
  of the source system. It is managed by the data platform, not dbt.
- **Silver onwards** is domain-centric — it uses the vocabulary, structure,
  and semantics defined in the ontology. This is where dbt begins.

```
Data Platform (outside dbt)     │  dbt (ontology-driven)
                                │
Landing Zone                    │
  Raw files → Bronze tables     │
                                │
Source World                    │  Domain World
(source vocabulary)             │  (ontology vocabulary)
                                │
adminpulse.api.Relation    ────►│────► silver/party/party.sql
harmoney.platform.Entity   ────►│────► silver/party/legal_entity.sql
                                │
```

---

## What Is NOT in Scope for dbt / Ontology Hub

| Concern | Handled By |
|---------|-----------|
| File ingestion (CSV → table) | Landing zone (ADF, Fabric pipelines) |
| Raw → tabular conversion | Landing zone / Bronze (platform tools) |
| Schema drift detection | Data platform tooling |
| Raw file validation | Data platform tooling |
| Data quality at source | Data platform tooling |

