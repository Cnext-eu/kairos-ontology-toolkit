# Advisory: Medallion Output Structure — dbt Best-Practice Alignment

## Problem Statement

The current `output/medallion/` layout has two directories describing silver-layer
tables, causing confusion about which is authoritative:

```
medallion/
├── dbt/
│   └── models/
│       ├── staging/{source}/      ← Bronze → renamed/cast views (OK)
│       └── silver/{domain}/       ← Domain entity transforms — BUT only stubs (2 cols!)
└── silver/                        ← Full physical DDL (30 cols), ALTER, ERD — BUT outside dbt
```

**Core issues:**
1. Two "silver" folders describe the same target tables
2. The dbt silver models are **stubs** (e.g. `party.sql` selects 2 NULL columns
   vs 30 columns in the DDL)
3. ERDs and DDL live outside the dbt project, disconnected from model documentation
4. No clear single source of truth for the silver schema

## dbt Best Practices (from dbt docs & community)

| Practice | Standard | Current State |
|----------|----------|---------------|
| **dbt owns table creation** | Models define schema; no external DDL | ❌ Separate DDL files |
| **Schema YAML co-located with models** | `_{domain}__models.yml` next to `.sql` | ⚠️ Exists but incomplete |
| **`analyses/` for reference SQL** | Non-DAG SQL (one-off queries, reference DDL) | ❌ Not used |
| **`docs/` for supplemental docs** | ERDs, diagrams, markdown linked from YAML | ❌ ERDs in separate tree |
| **Staging = light transforms** | Rename, cast, no joins — `stg_{source}__{table}` | ✅ Correct |
| **Silver = domain-conformed** | Full business logic, joins, SCD | ❌ Stubs only |
| **No cross-layer refs** | Silver refs staging only; gold refs silver only | ✅ Correct |
| **Materialization by layer** | Staging=view, Silver=table, Gold=table/view | ✅ Correct in dbt_project.yml |

## Recommended Structure

Consolidate everything into a **single dbt project tree**, using dbt's native
folder conventions:

```
medallion/
└── dbt/
    ├── dbt_project.yml
    ├── packages.yml
    │
    ├── models/
    │   ├── staging/{source}/                ← Bronze → Silver staging views
    │   │   ├── _{source}__sources.yml       ← dbt source definitions
    │   │   └── stg_{source}__{table}.sql    ← Rename + cast (no joins)
    │   │
    │   └── silver/{domain}/                 ← Domain-conformed tables
    │       ├── _{domain}__models.yml        ← FULL schema: all columns, types,
    │       │                                   tests, ontology metadata
    │       └── {entity}.sql                 ← Complete transformation logic
    │
    ├── analyses/{domain}/                   ← Reference DDL (outside DAG)
    │   ├── {domain}-ddl.sql                 ← CREATE TABLE — for DBA reference
    │   └── {domain}-alter.sql               ← FK/UNIQUE constraints — doc only
    │
    └── docs/
        └── diagrams/                        ← ERD diagrams
            ├── master-erd.mmd               ← Cross-domain master ERD
            ├── master-erd.svg               ← Rendered master ERD
            └── {domain}/
                ├── {domain}-erd.mmd         ← Per-domain Mermaid source
                └── {domain}-erd.svg         ← Per-domain rendered SVG
```

### Why this structure

**`models/silver/`** — The dbt YAML schema becomes the **single source of truth**
for silver table definitions. dbt `run` creates the actual tables via
materialization. The `.yml` files contain:
- All columns with types (via `meta.data_type`)
- `not_null`, `unique` tests (derived from SHACL shapes)
- Ontology metadata (`ontology_class`, `ontology_iri`, `domain`)
- Business descriptions (GDPR sensitivity, KYC context)

**`analyses/`** — dbt's designated folder for SQL that lives **outside the DAG**.
These files are compiled by dbt (so Jinja refs work) but never materialized.
Perfect for:
- Reference DDL that DBAs can copy-paste into Fabric manually
- ALTER TABLE constraint scripts (Fabric doesn't enforce them, so they're documentation)
- The DDL stays connected to the dbt project and can reference model schemas

**`docs/diagrams/`** — dbt best practice for supplemental documentation.
ERD SVGs can be linked from model YAML descriptions:
```yaml
models:
  - name: party
    description: |
      ![Party ERD](../../docs/diagrams/party/party-erd.svg)
      Domain entity representing natural persons, legal entities, ...
```
This makes ERDs visible in `dbt docs serve`.

### What gets eliminated

The top-level `medallion/silver/` directory is **removed entirely**. Its contents
are redistributed:

| Current location | New location | Rationale |
|-----------------|--------------|-----------|
| `silver/{domain}/{domain}-ddl.sql` | `dbt/analyses/{domain}/` | Reference SQL outside DAG |
| `silver/{domain}/{domain}-alter.sql` | `dbt/analyses/{domain}/` | Reference constraints |
| `silver/{domain}/{domain}-erd.mmd` | `dbt/docs/diagrams/{domain}/` | Supplemental docs |
| `silver/{domain}/{domain}-erd.svg` | `dbt/docs/diagrams/{domain}/` | Visual documentation |
| `silver/master-erd.mmd` | `dbt/docs/diagrams/` | Master cross-domain ERD |
| `silver/master-erd.svg` | `dbt/docs/diagrams/` | Rendered master ERD |

### What must be completed (prerequisite)

The **dbt silver model generator** (`--target dbt`) currently produces stubs.
It must be enhanced to generate **complete** models matching the DDL:

| Missing in dbt models | Required |
|-----------------------|----------|
| Inheritance flattening (S3) | Discriminator column + flattened subtype properties |
| SCD2 columns | `valid_from`, `valid_to`, `is_current` |
| Audit envelope | `_created_at`, `_updated_at`, `_source_system`, `_load_date`, `_batch_id`, `_row_hash`, `_deleted_at` |
| All domain columns | Currently 2/30 for party — must be complete |
| Partition/cluster config | Via dbt `config()` block |
| FK relationships | Via `relationships` test in YAML |

## Changes Required in kairos-ontology-toolkit

All changes go in the **kairos-ontology-toolkit** repository:

### 1. Complete dbt silver model generation
- The `--target dbt` projector must produce full-column `.sql` models
  (inheritance flattening, SCD2, audit envelope)
- YAML schemas must list all columns with types, tests, ontology metadata
- Add `config(partition_by=..., cluster_by=...)` to silver models

### 2. Relocate silver DDL/ERD into dbt tree
- `--target silver` writes DDL to `medallion/dbt/analyses/{domain}/`
- `--target silver` writes ERD to `medallion/dbt/docs/diagrams/{domain}/`
- Master ERD goes to `medallion/dbt/docs/diagrams/`

### 3. Update dbt_project.yml template
- Add `analysis-paths: ["analyses"]` (already present, just ensure it stays)
- Add `docs-paths: ["docs"]` for supplemental documentation
- No changes needed to model materialization config

### 4. Remove `medallion/silver/` output path
- The `--target silver` no longer writes to a separate directory
- Provide a migration path for existing hubs (move files, update .gitignore)

### 5. Update skill documentation
- **kairos-medallion-silver** skill: update output paths in docs
- **kairos-medallion-projection** skill: reflect new structure
- **kairos-mapping-report** skill: no changes needed (reports are separate)

## Migration Path for Existing Hubs

When hubs upgrade to the new toolkit version:

1. `kairos-ontology update` refreshes managed files
2. Run `kairos-ontology project --target silver` → writes to new paths
3. Run `kairos-ontology project --target dbt` → generates complete models
4. Delete old `medallion/silver/` directory
5. Commit the restructured output

## Summary

| Before | After |
|--------|-------|
| 2 silver folders, unclear authority | 1 dbt project tree, single source of truth |
| DDL is authoritative (30 cols) | dbt YAML is authoritative (complete schema) |
| ERDs disconnected from dbt docs | ERDs in `docs/diagrams/`, linkable from YAML |
| DDL outside dbt | DDL in `analyses/` (dbt-native, non-DAG) |
| dbt silver models are stubs | dbt silver models are complete transforms |
