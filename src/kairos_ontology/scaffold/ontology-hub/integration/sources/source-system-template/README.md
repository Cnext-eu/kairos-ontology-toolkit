# {System Name}

> Replace `{System Name}` with the actual name of the source system and rename
> this folder to match (lowercase with hyphens, e.g. `erp-navision`).

## Overview

| Field | Value |
|-------|-------|
| **System name** | _{e.g. AdminPulse}_ |
| **Owner / contact** | _{team or person responsible}_ |
| **Version** | _{version or date of the reference docs}_ |
| **Source type** | _{API, Database, File export, …}_ |

## Connection details

| Field | Value |
|-------|-------|
| **Type** | _{REST API / SQL Server / PostgreSQL / File / …}_ |
| **Database** | _{database name, if applicable}_ |
| **Schema** | _{schema name, if applicable}_ |
| **Base URL** | _{API base URL, if applicable}_ |

> **Do not** store credentials, tokens, or connection strings here. Use a
> secrets manager or environment variables for sensitive values.

## Reference documents

List the files you have placed in this folder:

- [ ] `example-api-spec.yaml` — OpenAPI specification
- [ ] `example-ddl.sql` — SQL DDL export (`CREATE TABLE` statements)
- [ ] `example-sample.json` — Sample data / API response
- [ ] `notes.md` — Observations, caveats, data quality notes

_(Delete or add lines as needed.)_

## Notes & observations

_Record anything useful about this source system: known data quality issues,
naming quirks, fields that are always null, deprecated endpoints, etc._

-

## Generating the bronze vocabulary

Once your reference documents are in place, use the **`kairos-medallion-staging`**
Copilot skill to generate the source vocabulary TTL file:

1. Make sure this folder contains at least one reference document (API spec,
   DDL export, or sample data).
2. Invoke the `kairos-medallion-staging` skill and point it at this folder.
3. The skill will produce (or update) the source vocabulary TTL **in this
   folder** (e.g. `erp-system.vocabulary.ttl`).
4. Review the generated TTL and commit both the source docs and the vocabulary
   together.
