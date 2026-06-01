---
name: kairos-setup-dataplatform
description: >
  Guide for scaffolding and setting up a downstream dataplatform dbt repository
  that consumes ontology-hub projections. Covers scaffold generation, profile
  configuration, source binding, bronze introspection, and CI setup.
---
<!-- kairos-ontology-toolkit:managed -->

# Kairos Dataplatform Setup Skill

You help users create and configure a **dataplatform** dbt repository that consumes
ontology-generated models from an ontology-hub. The dataplatform is the downstream
consumer that connects to the actual bronze lakehouse/warehouse.

## Before you start

0. **Run from within the hub repo** — The `init-dataplatform` command must be run
   from within an ontology-hub repository so it can auto-detect the hub's repo URL,
   version, and source systems.

1. **Quick toolkit version check** — run `kairos-ontology update --check` once at
   the start. If outdated, run `kairos-ontology update` first.

## Architecture

```
ontology-hub (producer)              dataplatform (consumer)
┌────────────────────────┐           ┌────────────────────────┐
│ Vocabulary + Mappings  │           │ dbt_project.yml        │
│ → dbt projection       │           │ packages.yml ──────┐   │
│   (logical source refs)│           │ models/_sources.yml │   │
│                        │           │   (physical binding)│   │
│ output/medallion/dbt/  │ ────────► │ dbt_packages/ ◄────┘   │
│                        │           │ macros/                │
└────────────────────────┘           │   extract_source_      │
                                     │   schema.sql           │
                                     │ pyproject.toml (uv)    │
                                     └────────────────────────┘
```

**Key principle:** The hub generates transform logic (SQL with real column names);
the dataplatform provides physical source binding (database, schema, connection).

## Step 1: Scaffold the Dataplatform

From within the ontology-hub repository:

```bash
kairos-ontology init-dataplatform [NAME] [--platform fabric-lakehouse|fabric-warehouse|databricks]
```

This creates a sibling directory with:
- `dbt_project.yml` pre-configured
- `packages.yml` pinned to the hub's current version
- `models/_sources.yml` pre-populated from hub vocabulary
- `macros/extract_source_schema.sql` for bronze introspection
- `pyproject.toml` with uv + kairos-ontology-toolkit dependency
- `profiles.yml.example` with platform-specific connection template
- `README.md` with setup instructions

### Auto-detection

When run from a hub repo, the command auto-detects:
- **Hub repo URL** from git remote origin
- **Hub version** from VERSION.json
- **Source systems** from integration/sources/ directories
- **Table names** from vocabulary TTL files

## Step 2: Configure Connection Profile

Copy `profiles.yml.example` to `~/.dbt/profiles.yml` and fill in your connection:

### Microsoft Fabric Lakehouse
```yaml
your_project:
  target: dev
  outputs:
    dev:
      type: fabric
      driver: "ODBC Driver 18 for SQL Server"
      server: "your-workspace.datawarehouse.fabric.microsoft.com"
      database: "your-lakehouse-name"
      schema: "dbo"
      authentication: CLI
```

### Databricks
```yaml
your_project:
  target: dev
  outputs:
    dev:
      type: databricks
      catalog: "your-catalog"
      schema: "silver"
      host: "workspace-url.azuredatabricks.net"
      http_path: "/sql/1.0/warehouses/warehouse-id"
      token: "your-token"
```

## Step 3: Update Physical Source Bindings

Edit `models/_sources.yml` to match your actual bronze database/schema:

```yaml
version: 2
sources:
  - name: adminpulse
    database: bronze_lakehouse        # ← Your actual database
    schema: raw_adminpulse            # ← Your actual schema
    tables:
      - name: tblClient
      - name: tblInvoice
```

## Step 4: Pull Hub Models and Build

```bash
cd your-dataplatform/
uv sync                    # Install Python dependencies
dbt deps                   # Pull ontology-hub dbt package
dbt build                  # Build all models
dbt test                   # Run tests
```

## Step 5: Bronze Introspection (Optional)

To refresh the hub vocabulary from actual bronze tables:

```bash
# In the dataplatform repo:
dbt run-operation extract_source_schema --args '{source_name: "adminpulse"}'
# → Produces YAML output

# Copy YAML to the hub repo and run:
kairos-ontology import-source --from adminpulse-schema.yaml --system adminpulse
```

This updates the vocabulary TTL with new/changed/removed columns.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `init-dataplatform` can't detect hub | Run from within the hub repo root |
| `dbt deps` auth error | Ensure CI runner has access to hub repo (PAT or SSH) |
| Source not found | Check `_sources.yml` table names match hub vocabulary |
| Type mismatch errors | Run bronze introspection to refresh vocabulary |
| Missing columns in silver | Update SKOS mappings in hub for new columns |

## Related Skills

| Skill | When to use |
|-------|-------------|
| **kairos-package-dataplatform** | Understanding the hub→dataplatform consumption pattern |
| **kairos-design-mapping** | Creating/updating SKOS column mappings |
| **kairos-design-source** | Designing bronze vocabulary from scratch |
| **kairos-execute-project** | Running projections in the hub |
