---
name: kairos-develop-dataplatform
description: >
  Interactive skill for dataplatform development tasks: testing dbt connections,
  introspecting live warehouse/lakehouse schemas, generating helper macros, and
  scaffolding custom models. Use when working inside a dataplatform dbt repository.
---

# Kairos Dataplatform Development Skill

You help users perform day-to-day development tasks in a **dataplatform** dbt
repository — the downstream consumer of ontology-hub projections.

## Before you start

0. **Verify you're in a dataplatform repo** — check for `dbt_project.yml` at root.
1. **Check profile configuration** — ensure `.dbt/profiles.yml` exists (or
   `~/.dbt/profiles.yml`). If not, guide the user to copy from
   `.dbt/profiles.yml.example`.
2. **Verify packages are installed** — `dbt_packages/` should exist. If not,
   run `dbt deps` first.
3. **If `dbt deps` fails because the hub package isn't published yet** — this is
   normal for new projects. Temporarily rename `packages.yml` to `packages.yml.bak`
   so you can run connection tests and schema discovery without it. Restore it once
   the hub has its first release tag.

---

## Capability 1: Connection Testing

### When to use

User says: "test my connection", "can I reach the warehouse?", "verify dbt setup"

### Steps

1. Check `.dbt/profiles.yml` (or `~/.dbt/profiles.yml`) exists and is configured.
2. Run `dbt debug --profiles-dir .dbt` to verify:
   - Profile loads correctly
   - Connection to warehouse/lakehouse succeeds
   - Required schemas exist
3. Report results clearly:
   - ✅ Connection successful — show target, database, schema
   - ❌ Connection failed — diagnose common issues (wrong server, auth, firewall)

### Common issues

| Error | Likely cause | Fix |
|-------|-------------|-----|
| Login failed | Wrong credentials | Check `profiles.yml` auth section |
| Server not found | Wrong server URL | Verify `server:` in profile |
| Database not found | Wrong database name | Check `database:` in profile |
| Permission denied | Missing grants | Contact DBA for access |
| ODBC driver missing | Driver not installed | Install ODBC Driver 18 |

---

## Capability 2: Source Introspection & Schema Extract

### When to use

User says: "introspect schema", "what tables are in bronze?", "infer columns",
"refresh source definitions", "what's in the lakehouse?", "extract schema",
"discover tables", "import sources"

### Overview

Source introspection produces a **schema YAML file** that serves two purposes:

1. **Dataplatform** — updates `models/_sources.yml` so dbt knows which tables exist
2. **Ontology Hub** — feeds `kairos-ontology import-source` to generate bronze
   vocabulary TTL for source-to-domain mappings

```
┌─────────────────────┐    extract_source_schema     ┌─────────────────────┐
│ Live Warehouse      │ ─────────────────────────►   │ extracted/<sys>.yaml │
│ (Fabric/Databricks) │                              └──────────┬──────────┘
└─────────────────────┘                                         │
                                                   ┌────────────┼────────────┐
                                                   ▼                         ▼
                                        models/_sources.yml      kairos-ontology import-source
                                        (dataplatform dbt)       (ontology-hub vocabulary)
```

### Prerequisites

1. **`.dbt/profiles.yml`** must exist with valid credentials.
2. **`models/_sources.yml`** should declare the source with at least database + schema.
   If the user doesn't have this yet, help them create it first (see Step 0 below).

### Step 0 — Discover schemas and tables (interactive selection)

If the user doesn't know what tables exist, or is connecting to a new warehouse,
guide them through an interactive discovery:

**0a. Discover available schemas:**

```sql
SELECT DISTINCT table_schema
FROM INFORMATION_SCHEMA.TABLES
WHERE table_type = 'BASE TABLE'
ORDER BY table_schema
```

Run via: `dbt run-operation print_query --args '{sql: "..."}' --profiles-dir .dbt`

Present the list and let the user **select which schemas** are relevant (some may be
system schemas like `sys`, `INFORMATION_SCHEMA`, etc. — skip those by default).

**0b. Discover tables in selected schemas:**

```sql
SELECT table_schema, table_name
FROM INFORMATION_SCHEMA.TABLES
WHERE table_type = 'BASE TABLE'
  AND table_schema IN ('<selected_schema_1>', '<selected_schema_2>')
ORDER BY table_schema, table_name
```

Present the table list grouped by schema and let the user **select which tables**
to include. Offer convenience options:
- "All tables in schema X" (common for source-system schemas like `raw_adminpulse`)
- "Filter by prefix" (e.g., all tables starting with `tbl`, `dim_`, `fct_`)
- "Select individually" (for mixed schemas)

**0c. Generate initial `_sources.yml`:**

From the user's selection, generate:

```yaml
version: 2
sources:
  - name: <system_name>        # ask user for logical name
    database: <database>
    schema: <selected_schema>
    tables:
      - name: tblClient
      - name: tblInvoice
      # ... selected tables
```

Write to `models/_sources.yml` (or append if it already exists with other sources).

### Step 1 — Declare sources in _sources.yml

Ensure `models/_sources.yml` has the source system declared with all known tables.
If tables are unknown, use a wildcard approach — list the database/schema and let
the extraction macro discover them.

### Step 2 — Run schema extraction (default: enriched with samples)

**Always use `extract-schema` CLI by default** — it provides full metadata including
sample values, row/distinct counts, and JSON structure detection. This is the standard
workflow for both dataplatform source binding and ontology hub vocabulary generation.

```bash
kairos-ontology extract-schema \
  --profiles-dir .dbt \
  --profile <profile_name> \
  --schema <schema_name> \
  --output extracted/<system_name> \
  --sample-size 5
```

Output is a per-table YAML directory:
```
extracted/<system_name>/
  _manifest.yaml         # system metadata, platform, extracted_at
  tblClient.yaml         # columns, samples, distinct_count, JSON structures
  tblInvoice.yaml
```

Each table YAML (v1.1) contains:
- Column names, data types, nullable flags, ordinal positions
- Row count + distinct count per column
- Sample values (default 5) for format detection
- JSON detection: classification (flat/nested/array_object/polymorphic)
- JSON structure: keys, types, sample values

**Fallback only** (use only when `extract-schema` is unavailable, e.g., no Python/toolkit
installed in the environment — rare for dataplatform repos):

```bash
dbt run-operation extract_source_schema \
  --args '{source_name: "<system_name>"}' \
  --profiles-dir .dbt > extracted/<system_name>-schema.yaml
```

This lightweight fallback only captures column names + data types (no samples, no JSON
detection, no row counts).

### Step 3 — Generate bronze_expanded staging models (for JSON)

If JSON columns are detected, generate dbt models that flatten them:

```bash
kairos-ontology generate-staging \
  --from extracted/<system_name>/ \
  --output models/staging
```

Generated model patterns:
- **Flat JSON** → `view` with `JSON_VALUE` column extractions
- **Array of objects** → `table` with `CROSS APPLY OPENJSON` (child table)
- **Nested objects** → flattened with dotted key naming

### Step 4 — Update _sources.yml (automatic — dataplatform only)

**Always update `_sources.yml` automatically after extraction** — this file is only
used in this dataplatform repo (dbt needs it for `{{ source() }}` resolution). The
ontology hub uses the extracted YAML files directly via `import-source`, so there is
no risk of side effects.

After extraction completes, immediately:
- Add newly discovered tables
- Add new columns to existing tables (with `data_type`)
- Flag type mismatches or removed columns (warn but don't auto-delete)

Write the updated `_sources.yml` without asking for confirmation:

```yaml
sources:
  - name: adminpulse
    database: bronze_db
    schema: raw_adminpulse
    tables:
      - name: tblClient
        columns:
          - name: ClientID
            data_type: int
            tests: [not_null, unique]
          - name: Name
            data_type: varchar
```

> **Note:** Only *removals* of tables/columns should be flagged for user review
> (they may be intentional renames). Additions and type updates are safe to apply.

### Step 5 — Export to ontology hub (vocabulary use)

Copy the extracted directory to the ontology-hub repo and run:

```bash
# In the ontology-hub repo:
kairos-ontology import-source \
  --from ../dataplatform/extracted/<system_name>/ \
  --system <system_name>
```

Or import a single YAML file:
```bash
kairos-ontology import-source \
  --from ../dataplatform/extracted/<system_name>-schema.yaml \
  --system <system_name>
```

This generates/updates the bronze vocabulary TTL at:
`integration/sources/<system_name>/<system_name>.vocabulary.ttl`

v1.1 YAML with JSON structures generates:
- Expanded properties for flat JSON keys
- Linked classes for nested objects and array-of-objects
- Sample values in `rdfs:comment` annotations

The vocabulary is then used for source-to-domain SKOS mappings.

### Schema comparison (refresh workflow)

When re-running introspection on an existing source:
- **New tables** — add to `_sources.yml` + flag for hub vocabulary update
- **New columns** — add to `_sources.yml` column definitions
- **Type changes** — warn user, update declarations
- **Removed tables/columns** — warn but don't auto-delete (may be intentional)

Present a clear diff showing what changed since last introspection.

---

## Capability 3: Custom Model Scaffolding

### When to use

User says: "create a custom model", "add a new staging model", "scaffold model
for X", "I need a custom dimension/fact"

### Steps

1. Ask what the model represents (entity, aggregation, bridge table, etc.).
2. Determine which hub-generated models it should reference (silver/gold).
3. Generate the model file in `models/custom/`:
   - Use `ref()` to reference hub-generated models
   - Follow dbt naming conventions (e.g., `stg_`, `dim_`, `fct_`, `int_`)
   - Include a YAML schema file with column descriptions and tests
4. Offer to add basic tests (not_null, unique, accepted_values).

### Model naming conventions

| Prefix | Purpose | Example |
|--------|---------|---------|
| `stg_` | Staging/light transform on top of sources | `stg_payments_enriched` |
| `int_` | Intermediate (joins, business logic) | `int_client_invoices` |
| `dim_` | Custom dimension (extends gold) | `dim_client_segments` |
| `fct_` | Custom fact (extends gold) | `fct_monthly_revenue` |
| `rpt_` | Report-specific aggregation | `rpt_top_clients_by_revenue` |

### Template

```sql
-- models/custom/{model_name}.sql
{{
  config(
    materialized='view',
    schema='gold'
  )
}}

with source as (
    select * from {{ ref('{upstream_model}') }}
),

final as (
    select
        -- columns
    from source
)

select * from final
```

---

## Helper Macros

When creating helper macros, place them in `macros/` and follow these conventions:

- One macro per file
- File name matches macro name
- Include a docstring block at the top
- Use `{{ log(...) }}` for debug output

### Available built-in macros

- **`extract_source_schema`** — introspects a dbt source and returns its schema as
  YAML output. Already included in the scaffold.
- **`print_query`** — executes arbitrary SQL and prints results to stdout. Use for
  ad-hoc schema discovery (listing schemas, tables, row counts).

### Macros you can help create

| Macro | Purpose |
|-------|---------|
| `test_connection` | Lightweight connection test (SELECT 1) |
| `compare_schemas` | Compare declared vs actual schema |
| `row_counts` | Get row counts for all tables in a source |
| `column_stats` | Basic profiling (nulls, distinct count) |

---

## Interaction guidelines

- Always check that the profile exists before running dbt commands.
- Use `--profiles-dir .dbt` when the profile is project-local.
- Show dbt output to the user — don't suppress errors.
- When introspecting, present results as tables for readability.
- For model scaffolding, show the generated code and ask for confirmation before writing.
