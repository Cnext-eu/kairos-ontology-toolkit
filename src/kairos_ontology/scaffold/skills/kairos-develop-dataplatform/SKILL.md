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

### ⚠️ MANDATORY: Always use `extract-schema` CLI for extraction

> **NEVER use manual SQL queries or dbt macros (`print_query`, `extract_source_schema`)
> to extract column metadata or sample values.** These are insufficient — they miss
> samples, distinct counts, JSON detection, and row counts.
>
> The **only** tool for schema extraction is:
> ```bash
> kairos-ontology extract-schema \
>   --profiles-dir .dbt --profile <profile> \
>   --schema <schema_name> \
>   --output extracted/<system_name> \
>   --sample-size 5
> ```
>
> The `print_query` macro is ONLY for interactive schema/table discovery (listing
> available schemas). It must NEVER be used for column or sample extraction.

### Overview

Source introspection produces a **schema YAML file** that serves two purposes:

1. **Dataplatform** — updates `models/_sources.yml` so dbt knows which tables exist
2. **Ontology Hub** — feeds `kairos-ontology import-source` to generate bronze
   vocabulary TTL for source-to-domain mappings

```
┌─────────────────────┐    extract-schema CLI        ┌─────────────────────┐
│ Live Warehouse      │ ─────────────────────────►   │ extracted/<sys>/     │
│ (Fabric/Databricks) │                              │   _manifest.yaml    │
└─────────────────────┘                              │   tblClient.yaml    │
                                                     │   tblInvoice.yaml   │
                                                     └──────────┬──────────┘
                                                    ┌────────────┼────────────┐
                                                    ▼                         ▼
                                         models/_sources.yml      kairos-ontology import-source
                                         (dataplatform dbt)       (ontology-hub vocabulary)
```

### Decision Gate

Before starting, determine the right path:

| User knows the schema name? | Action |
|-----------------------------|--------|
| **Yes** (e.g., "introspect bronze schema") | → Skip to **Step 1** (extract-schema) |
| **No** (e.g., "what's in the warehouse?") | → Start at **Step 0** (discover schemas, then extract) |

### Prerequisites

1. **`.dbt/profiles.yml`** must exist with valid credentials.
2. **Connection must work** — run `dbt debug --profiles-dir .dbt` if unsure.

---

### Step 0 — Interactive Schema Discovery (only if schema unknown)

Use `print_query` to help the user **select** which schemas to introspect.
This step produces schema name(s) as input for Step 1 — nothing more.

**0a. List available schemas:**

```bash
dbt run-operation print_query \
  --args '{sql: "SELECT DISTINCT table_schema FROM INFORMATION_SCHEMA.TABLES WHERE table_type = '\''BASE TABLE'\'' ORDER BY table_schema"}' \
  --profiles-dir .dbt
```

Present the list and let the user **select which schemas** to include.
Skip system schemas (`sys`, `INFORMATION_SCHEMA`, `dbo` if empty) by default.

**0b. (Optional) Preview tables in selected schemas:**

```bash
dbt run-operation print_query \
  --args '{sql: "SELECT table_schema, table_name FROM INFORMATION_SCHEMA.TABLES WHERE table_schema IN ('\''raw_adminpulse'\'') ORDER BY table_name"}' \
  --profiles-dir .dbt
```

This is informational only. The user may want to see what's there before extracting.

**→ Once schemas are selected, proceed to Step 1.**

---

### Step 1 — Run `extract-schema` CLI (with samples)

This is the **primary extraction step**. Run it for each selected schema:

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

---

### Step 2 — Update `_sources.yml` (automatic)

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

---

### Step 3 — Generate bronze_expanded staging models (for JSON)

If JSON columns are detected in the extracted YAML, generate dbt models that flatten them:

```bash
kairos-ontology generate-staging \
  --from extracted/<system_name>/ \
  --output models/staging
```

Generated model patterns:
- **Flat JSON** → `view` with `JSON_VALUE` column extractions
- **Array of objects** → `table` with `CROSS APPLY OPENJSON` (child table)
- **Nested objects** → flattened with dotted key naming

---

### Step 4 — Export to ontology hub (vocabulary use)

> ⚠️ **IMPORTANT: Run this step from the ontology-hub repo, NOT the dataplatform.**
> The `import-source` command writes output relative to CWD. If you run it from
> the dataplatform repo, vocabulary files will be created in the wrong location.
> The CLI will warn you if it detects this situation.

**Option A (recommended) — cd into the hub repo:**

```bash
cd ../your-ontology-hub/
kairos-ontology import-source \
  --from ../your-dataplatform/extracted/<system_name>/ \
  --system <system_name>
```

**Option B — explicit output path:**

```bash
# From the dataplatform repo:
kairos-ontology import-source \
  --from extracted/<system_name>/ \
  --system <system_name> \
  --output ../your-ontology-hub/integration/sources/<system_name>
```

This generates/updates in the hub:
- `integration/sources/<system_name>/<system_name>.vocabulary.ttl` — semantic metadata
- `integration/sources/<system_name>/*.samples.yaml` — row-level sample data
  (automatically copied from the extracted directory for ontology modeler reference)

v1.1 YAML with JSON structures generates:
- Expanded properties for flat JSON keys
- Linked classes for nested objects and array-of-objects
- Sample values in `rdfs:comment` annotations

The vocabulary is then used for source-to-domain SKOS mappings. The `.samples.yaml`
files provide row-level context when the `kairos-design-source` skill presents table
structure to the ontology modeler.

---

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
