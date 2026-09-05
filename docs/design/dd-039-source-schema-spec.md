# Source Schema YAML Specification (v1.0)

This document defines the intermediate YAML format used to exchange bronze table
metadata between the **dataplatform repo** (where schema extraction runs against
live tables) and the **ontology hub** (where vocabulary TTL is maintained).

## Overview

```
Dataplatform Repo                      Ontology Hub
┌─────────────────┐     YAML file      ┌──────────────────────┐
│ dbt/Python      │ ──────────────────▶ │ kairos-ontology      │
│ extract schema  │                     │ import-source        │
│ from bronze     │                     │ → vocabulary.ttl     │
└─────────────────┘                     └──────────────────────┘
```

## Schema Definition

```yaml
# Required fields
version: "1.0"                          # Schema version (must be "1.0")
system: "adminpulse"                    # Source system identifier
                                        # Must match hub convention: integration/sources/{system}/

# Optional metadata
platform: "fabric-lakehouse"            # Platform identifier (see Platform Types below)
environment: "production"               # dbt target name or environment label
extracted_at: "2026-06-01T19:00:00Z"    # ISO 8601 timestamp of extraction

# Optional connection info (used by dataplatform for _sources.yml, NOT sent to hub vocab)
connection:
  database: "bronze_lakehouse"          # Physical database name
  schema: "raw_adminpulse"              # Physical schema name

# Required: table definitions
tables:
  - name: "tblClient"                   # Physical table name (case-sensitive)
    incremental_column: "ModifiedDate"  # Optional: column used for incremental loading
    columns:
      - name: "ClientId"                # Physical column name (case-sensitive)
        data_type: "int"                # Canonical data type (see Type Mapping below)
        nullable: false                 # Whether NULL is allowed (default: true)
        is_primary_key: true            # Whether this column is part of the PK (default: false)
      - name: "ClientName"
        data_type: "string"
        nullable: true
      - name: "MetadataJson"
        data_type: "string"
        content_type: "json-object"     # Optional: "json-object" or "json-array"
        nullable: true
```

## Field Reference

### Root Level

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `version` | ✅ | string | Schema version. Must be `"1.0"`. |
| `system` | ✅ | string | Source system identifier. Maps to `integration/sources/{system}/`. |
| `platform` | ❌ | string | Platform type (see below). |
| `environment` | ❌ | string | Environment name (e.g., `dev`, `staging`, `production`). |
| `extracted_at` | ❌ | string | ISO 8601 timestamp of when the schema was extracted. |
| `connection` | ❌ | object | Physical connection info for dataplatform use. |
| `tables` | ✅ | list | List of table definitions. |

### Connection Object

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `database` | ❌ | string | Physical database name in the lakehouse/warehouse. |
| `schema` | ❌ | string | Physical schema name. |

### Table Object

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `name` | ✅ | string | Physical table name (case-sensitive). |
| `columns` | ✅ | list | List of column definitions (must not be empty). |
| `incremental_column` | ❌ | string | Column name used for incremental/SCD loading. |

### Column Object

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `name` | ✅ | string | Physical column name (case-sensitive). |
| `data_type` | ✅ | string | Canonical data type (see Type Mapping). |
| `nullable` | ❌ | boolean | Whether NULL is allowed. Default: `true`. |
| `is_primary_key` | ❌ | boolean | Part of primary key. Default: `false`. |
| `content_type` | ❌ | string | `"json-object"` or `"json-array"` for JSON-in-string columns. |

## Platform Types

These describe the **source system being introspected**, which is a superset of the
platforms the compiler can emit for: `snowflake` and `postgres` are readable sources, not
compile targets. The two vocabularies overlap by name and agree where they overlap; the
compile-target set is owned by `core/adapters.py` (DD-215).

| Platform ID | Description | dbt Adapter |
|-------------|-------------|-------------|
| `fabric-lakehouse` | Microsoft Fabric Lakehouse (Spark/Delta) | `dbt-fabric` |
| `fabric-warehouse` | Microsoft Fabric Warehouse (T-SQL) | `dbt-fabric` |
| `databricks` | Databricks (Unity Catalog) | `dbt-databricks` |
| `snowflake` | Snowflake | `dbt-snowflake` |
| `postgres` | PostgreSQL | `dbt-postgres` |
| `unknown` | Unspecified platform | — |

## Canonical Type Mapping

The YAML uses canonical type names. The extraction script normalizes platform-specific
types to these canonical forms:

| Canonical Type | Fabric Lakehouse | Fabric Warehouse | Databricks | Snowflake |
|----------------|-----------------|------------------|------------|-----------|
| `int` | `INT`, `INTEGER` | `int`, `bigint` | `INT`, `BIGINT` | `NUMBER(38,0)` |
| `string` | `STRING` | `varchar`, `nvarchar` | `STRING` | `VARCHAR` |
| `decimal` | `DECIMAL(p,s)` | `decimal(p,s)`, `numeric` | `DECIMAL(p,s)` | `NUMBER(p,s)` |
| `boolean` | `BOOLEAN` | `bit` | `BOOLEAN` | `BOOLEAN` |
| `date` | `DATE` | `date` | `DATE` | `DATE` |
| `datetime` | `TIMESTAMP` | `datetime2` | `TIMESTAMP` | `TIMESTAMP_NTZ` |
| `binary` | `BINARY` | `varbinary` | `BINARY` | `BINARY` |
| `float` | `FLOAT`, `DOUBLE` | `float`, `real` | `FLOAT`, `DOUBLE` | `FLOAT` |

> **Note:** Precision/scale suffixes (e.g., `decimal(18,2)`) are preserved as-is.
> The canonical type is the base name for matching purposes.

## Versioning Strategy

The `version` field enables forward-compatible schema evolution:

- **v1.0** (current): Base schema with tables, columns, types, PK, nullable, content_type
- Future versions may add: constraints, indexes, partitioning info, relationships
- Consumers SHOULD ignore unknown fields (forward compatibility)
- Breaking changes require a new major version

## Example: Complete File

```yaml
version: "1.0"
system: "adminpulse"
platform: "fabric-lakehouse"
environment: "production"
extracted_at: "2026-06-01T19:00:00Z"
connection:
  database: "bronze_lakehouse"
  schema: "raw_adminpulse"

tables:
  - name: "tblClient"
    incremental_column: "ModifiedDate"
    columns:
      - name: "ClientId"
        data_type: "int"
        nullable: false
        is_primary_key: true
      - name: "ClientName"
        data_type: "string"
        nullable: true
      - name: "ClientTypeId"
        data_type: "int"
        nullable: true
      - name: "Email"
        data_type: "string"
        nullable: true
      - name: "IsActive"
        data_type: "boolean"
        nullable: false
      - name: "MetadataJson"
        data_type: "string"
        content_type: "json-object"
        nullable: true
      - name: "CreatedDate"
        data_type: "datetime"
        nullable: false
      - name: "ModifiedDate"
        data_type: "datetime"
        nullable: false

  - name: "tblClientType"
    columns:
      - name: "ClientTypeId"
        data_type: "int"
        nullable: false
        is_primary_key: true
      - name: "TypeName"
        data_type: "string"
        nullable: false
      - name: "Description"
        data_type: "string"
        nullable: true

  - name: "tblInvoice"
    incremental_column: "ModifiedDate"
    columns:
      - name: "InvoiceId"
        data_type: "int"
        nullable: false
        is_primary_key: true
      - name: "ClientId"
        data_type: "int"
        nullable: false
      - name: "Amount"
        data_type: "decimal(18,2)"
        nullable: false
      - name: "InvoiceDate"
        data_type: "date"
        nullable: false
      - name: "Status"
        data_type: "string"
        nullable: true
      - name: "ModifiedDate"
        data_type: "datetime"
        nullable: false
```

## Related Documents

- [DD-038: Bronze Source Introspection & Layered dbt Architecture](dd-038-bronze-introspection-architecture.md)
- [DD-015: Vocabulary TTL as Bronze Contract](decisions/dd-015-vocabulary-ttl-as-bronze-contract.md)
