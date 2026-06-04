# Dataplatform Extensions Approach

## Overview

This document describes how data engineers can customize and extend the
ontology-hub-generated dbt models **without modifying the hub package itself**.
All customizations live in the dataplatform repo and survive hub re-projections.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  ONTOLOGY HUB (generated, immutable in dataplatform)            │
│  dbt_packages/pkf_bofidi_ontology_hub/                          │
│    models/silver/                                                │
│      silver_client.sql            ← SCD2, type casting, keys    │
│      silver_invoice.sql           ← joins, deduplication        │
│    models/gold/                                                  │
│      dim_client.sql               ← star-schema dimension       │
│      fact_invoice.sql             ← fact table                  │
└──────────────────────────┬──────────────────────────────────────┘
                           │ {{ ref('pkf_bofidi_ontology_hub', 'silver_client') }}
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  DATAPLATFORM — silver_custom/ (Wrappers)                       │
│  models/silver_custom/                                          │
│    silver_client_v.sql            ← computed columns, filters   │
│    silver_invoice_v.sql           ← enrichments, joins          │
└──────────────────────────┬──────────────────────────────────────┘
                           │ {{ ref('silver_client_v') }}
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  DATAPLATFORM — gold/ (Custom Business Logic)                   │
│  models/gold/                                                   │
│    dimensions/dim_client_enriched.sql                            │
│    facts/fact_revenue.sql                                        │
│    reports/rpt_monthly_billing.sql                               │
└─────────────────────────────────────────────────────────────────┘
```

### Key Principle

> The hub generates **transform logic** (SQL with real column names).
> The dataplatform provides **physical binding**, **customization**, and **orchestration**.

---

## Layer 1: Silver Wrappers

### Purpose

Fix, enrich, or filter hub-generated silver models without modifying the package.

### Naming Convention

`silver_{entity}_v.sql` — the `_v` suffix indicates a "view/variant" on top of
the hub model.

### When to Create a Wrapper

| Situation | Action |
|-----------|--------|
| Need extra computed columns | Create `_v` wrapper |
| Need to filter out bad/test rows | Create `_v` wrapper |
| Need to join two hub models together | Create `_v` wrapper |
| Hub model is missing a source column | Fix in hub → re-project |
| Hub model has a type casting bug | Fix in hub (benefits all consumers) |

### Examples

#### Adding computed columns

```sql
-- models/silver_custom/silver_client_v.sql
{{
    config(
        materialized='view',
        schema='silver'
    )
}}

SELECT
    *,
    CONCAT(first_name, ' ', last_name)          AS full_name,
    DATEDIFF(day, created_date, GETDATE())      AS days_since_creation,
    CASE
        WHEN is_active = 1 THEN 'Active'
        WHEN termination_date IS NOT NULL THEN 'Terminated'
        ELSE 'Inactive'
    END                                          AS client_status_label
FROM {{ ref('pkf_bofidi_ontology_hub', 'silver_client') }}
```

#### Filtering bad data

```sql
-- models/silver_custom/silver_invoice_v.sql
{{
    config(
        materialized='view',
        schema='silver'
    )
}}

SELECT *
FROM {{ ref('pkf_bofidi_ontology_hub', 'silver_invoice') }}
WHERE
    client_id NOT IN ('TEST001', 'TEST002')
    AND invoice_date <= GETDATE()
```

#### Joining additional context

```sql
-- models/silver_custom/silver_client_v.sql
{{
    config(
        materialized='view',
        schema='silver'
    )
}}

SELECT
    c.*,
    t.team_name,
    t.team_leader
FROM {{ ref('pkf_bofidi_ontology_hub', 'silver_client') }} c
LEFT JOIN {{ ref('pkf_bofidi_ontology_hub', 'silver_team') }} t
    ON c.team_id = t.team_id
```

---

## Layer 2: Custom Gold Models

### Purpose

Business-specific analytics models that the hub cannot anticipate. Entirely
owned by the data engineering team.

### Folder Structure

```
models/gold/
├── dimensions/
│   ├── dim_client_enriched.sql
│   └── dim_date.sql
├── facts/
│   ├── fact_revenue.sql
│   └── fact_billable_hours.sql
├── reports/
│   ├── rpt_monthly_billing.sql
│   └── rpt_client_profitability.sql
└── _gold_models.yml               ← tests & documentation
```

### Examples

#### Custom fact table

```sql
-- models/gold/facts/fact_revenue.sql
{{
    config(
        materialized='table',
        schema='gold'
    )
}}

WITH invoices AS (
    SELECT * FROM {{ ref('silver_invoice_v') }}
),

clients AS (
    SELECT * FROM {{ ref('silver_client_v') }}
)

SELECT
    i.invoice_id,
    i.invoice_date,
    c.client_id,
    c.client_status_label,
    i.amount_excl_vat,
    i.amount_incl_vat,
    i.amount_incl_vat - i.amount_excl_vat       AS vat_amount,
    i.amount_excl_vat * c.margin_pct / 100.0    AS estimated_margin,
    d.fiscal_year,
    d.fiscal_quarter
FROM invoices i
JOIN clients c ON i.client_id = c.client_id
JOIN {{ ref('dim_date') }} d ON i.invoice_date = d.date_key
```

#### Reporting aggregate

```sql
-- models/gold/reports/rpt_monthly_billing.sql
{{
    config(
        materialized='table',
        schema='gold'
    )
}}

SELECT
    DATE_TRUNC('month', invoice_date)   AS billing_month,
    client_id,
    client_status_label,
    COUNT(*)                            AS invoice_count,
    SUM(amount_excl_vat)                AS total_revenue,
    SUM(estimated_margin)               AS total_margin
FROM {{ ref('fact_revenue') }}
GROUP BY 1, 2, 3
```

---

## Micro-Batch Orchestration

The same abstraction pattern applies to **execution control** — the hub defines
*what* transforms run, the dataplatform defines *when* and *how much*.

### Selectors

Define named run groups in `selectors.yml`:

```yaml
# selectors.yml
selectors:
  - name: micro_batch_frequent
    description: "High-velocity tables — run every 15 min"
    definition:
      method: tag
      value: batch_frequent

  - name: micro_batch_hourly
    description: "Medium-velocity tables — run every hour"
    definition:
      method: tag
      value: batch_hourly

  - name: micro_batch_daily
    description: "Low-velocity tables — run once per day"
    definition:
      method: tag
      value: batch_daily

  - name: gold_refresh
    description: "Gold models — after all silver completes"
    definition:
      union:
        - method: path
          value: models/gold
        - method: path
          value: models/silver_custom
```

### Tag Assignment

Tags are applied in `dbt_project.yml` and override hub model behaviour:

```yaml
models:
  pkf_bofidi_ontology_hub:
    silver:
      silver_invoice:
        +tags: ['batch_frequent']
      silver_client:
        +tags: ['batch_daily']
      silver_relation_address:
        +tags: ['batch_daily']

  bofidi_dataplatform:
    silver_custom:
      +tags: ['batch_hourly']
    gold:
      +tags: ['gold_refresh']
```

### Execution Commands

```bash
# Frequent micro-batch (every 15 min)
dbt build --selector micro_batch_frequent

# Hourly batch
dbt build --selector micro_batch_hourly

# Daily full refresh
dbt build --selector micro_batch_daily

# Gold layer (after all silver completes)
dbt build --selector gold_refresh
```

### Custom Batch Window Macro

For platform-specific control (e.g., Fabric Warehouse CU management):

```sql
-- macros/batch_window.sql
{% macro batch_window(column, hours=1) %}
    {% if is_incremental() %}
        WHERE {{ column }} >= DATEADD(hour, -{{ hours }}, GETUTCDATE())
    {% endif %}
{% endmacro %}
```

Used in wrappers:

```sql
SELECT *
FROM {{ ref('pkf_bofidi_ontology_hub', 'silver_invoice') }}
{{ batch_window('_loaded_at', hours=1) }}
```

### dbt Micro-Batch Strategy (dbt 1.9+)

For time-partitioned processing with automatic backfill:

```sql
-- models/silver_custom/silver_invoice_v.sql
{{
    config(
        materialized='incremental',
        incremental_strategy='microbatch',
        event_time='invoice_date',
        begin='2024-01-01',
        batch_size='day',
        lookback=3
    )
}}

SELECT *
FROM {{ ref('pkf_bofidi_ontology_hub', 'silver_invoice') }}
```

### Orchestration Schedule

```
┌──────────────────────────────────────────────────────────────┐
│  Scheduler (Fabric Pipeline / Airflow / Cron)                │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  Every 15 min:  dbt build --selector micro_batch_frequent    │
│       │                                                      │
│       ▼                                                      │
│  Every hour:    dbt build --selector micro_batch_hourly      │
│       │                                                      │
│       ▼                                                      │
│  Daily 02:00:   dbt build --selector micro_batch_daily       │
│       │                                                      │
│       ▼                                                      │
│  Daily 04:00:   dbt build --selector gold_refresh            │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

## dbt_project.yml Configuration

```yaml
models:
  # Hub-generated models (from dbt deps — do not modify)
  pkf_bofidi_ontology_hub:
    +schema: silver
    +materialized: table

  # Dataplatform custom layers
  bofidi_dataplatform:
    silver_custom:
      +schema: silver
      +materialized: view          # Views = zero storage cost
    gold:
      +schema: gold
      +materialized: table
      reports:
        +materialized: table       # or 'view' for real-time queries
```

---

## Re-Projection Workflow

When the ontology hub is updated and re-projected:

```
1. Hub: update mappings/extensions → re-run projection → tag new version
2. Dataplatform:
     - Update packages.yml: revision: "v0.2.0"
     - Run: dbt deps
     - Run: dbt build
3. Result:
     ✓ Hub silver models updated (new columns, logic fixes)
     ✓ Silver wrappers: SELECT * still works (additive changes)
     ✓ Gold models: automatically see new columns via wrappers
4. Only action needed if hub REMOVES or RENAMES a column used in a wrapper
```

### What Survives Re-Projection?

| Component | Owned by | Re-projection impact |
|-----------|----------|---------------------|
| Silver SQL logic | Hub | ✅ Regenerated safely |
| Incremental strategy | Hub | ✅ Regenerated |
| **Tag assignments** | Dataplatform | ✅ Untouched |
| **Selectors** | Dataplatform | ✅ Untouched |
| **Batch macros** | Dataplatform | ✅ Untouched |
| **Silver wrappers** | Dataplatform | ✅ Untouched |
| **Gold models** | Dataplatform | ✅ Untouched |
| **Orchestrator config** | Dataplatform | ✅ Untouched |

---

## Summary

| Layer | Owner | Purpose | Materialization |
|-------|-------|---------|-----------------|
| Hub silver | Ontology hub (generated) | Base transforms | Table (incremental) |
| Silver wrappers | Data engineers | Fix / enrich / filter | View |
| Custom gold | Data engineers | Business logic & reporting | Table |
| Selectors & tags | Data engineers | Execution orchestration | N/A |
| Batch macros | Data engineers | Micro-batch windowing | N/A |

All dataplatform-owned components are **decoupled from the hub** and survive
re-projections cleanly. The hub defines *what* data flows; the dataplatform
defines *how*, *when*, and *with what additions*.
