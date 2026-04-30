# Design Decisions — To Validate with Data Architects

This document captures design decisions that need review and validation
with the data architecture team before finalising.

---

## DD-001: Gold Layer Inheritance Strategy — Class-Per-Table

**Status:** Proposed  
**Date:** 2026-04-25  
**Context:** Gold projection G5 rule change

### Problem

The gold projector currently flattens OWL `rdfs:subClassOf` hierarchies into a
single parent table with a discriminator column (mirroring silver's S3 behaviour).
This creates wide, sparse tables that don't align with the ontology structure.

### Decision

Change G5 default to **class-per-table**: each subclass becomes a separate gold
table extending the parent table.

### PK/FK Design

**Chosen approach: Shared PK**

The subtype table's PK is the **same surrogate key column** as the parent table.
It serves as both PK and FK (1:1 relationship).

```
┌─────────────────────┐
│    dim_party         │
├─────────────────────┤
│ party_sk       (PK) │
│ party_name          │
│ party_email         │
│ ...shared props...  │
└─────────────────────┘
          ▲
          │ 1:1 FK
┌─────────────────────┐     ┌──────────────────────────┐
│ dim_legal_entity    │     │ dim_sole_proprietorship   │
├─────────────────────┤     ├──────────────────────────┤
│ party_sk  (PK + FK) │     │ party_sk      (PK + FK)  │
│ registration_number │     │ owner_name               │
│ ...own props only...│     │ ...own props only...     │
└─────────────────────┘     └──────────────────────────┘
```

**Rationale:**
- Mirrors the ontological 1:1 subclass relationship faithfully
- Simpler JOINs (`JOIN ON party_sk = party_sk`)
- No surrogate key proliferation
- Standard pattern in star schemas for type-2 subtypes

**Alternative considered: Own SK**

Each subtype gets its own SK (e.g., `legal_entity_sk`) plus a separate FK column
to the parent. This allows more flexibility (e.g., 1:N if needed in future) but
adds complexity and doesn't reflect the ontology's `rdfs:subClassOf` semantics.

### Opt-out

A `kairos-ext:goldInheritanceStrategy` annotation allows switching back to
`"discriminator"` at ontology or class level.

### Questions for Data Architects

1. Is shared PK the right default, or should some hierarchies use own SK?
2. Should the parent table include a discriminator column even in class-per-table
   mode (for querying "which subtype is this row")?
3. How should SCD Type 2 interact with class-per-table? (valid_from/valid_to on
   both parent and child, or only parent?)
4. Impact on DirectLake / Power BI relationship modelling — any concerns with
   1:1 FK relationships in TMDL?

---

## DD-002: dbt SQL Dialect — Platform-Specific Generation

**Status:** Accepted  
**Date:** 2026-04-30  
**Context:** dbt projection engine multi-platform support

### Problem

dbt Core does NOT abstract SQL dialects. Model `.sql` files are sent verbatim to
the target warehouse engine. Different platforms use different:
- Type names (VARCHAR vs STRING, BIT vs BOOLEAN, DATETIME2 vs TIMESTAMP)
- JSON extraction functions (OPENJSON + CROSS APPLY vs EXPLODE(FROM_JSON(...)))
- String concatenation (`+` vs `CONCAT()`)
- Row limiting (TOP N vs LIMIT N)

### Decision

Generate **platform-specific SQL** controlled by a `target_platform` parameter:
- `"fabric"` (default) — T-SQL dialect for `dbt-fabric` adapter
- `"databricks"` — Spark SQL dialect for `dbt-databricks` adapter

### Portability Strategy

| Layer | Strategy | Rationale |
|-------|----------|-----------|
| **Staging** | Platform-specific templates | Tightly coupled to physical source; JSON extraction is fundamentally different |
| **Silver** | Use `dbt_utils` macros for types + generated Kairos macros | Domain layer should be portable; `dbt_utils.type_*()` resolves correctly per adapter |
| **Gold** | Use `dbt_utils` macros | Same as silver |

### What dbt DOES abstract (safe to be portable)

- CTE syntax (`WITH ... AS`)
- CASE WHEN expressions
- `dbt_utils.generate_surrogate_key()`
- Materialization strategies (incremental merge, snapshots)
- `ref()` and `source()` resolution

### What dbt does NOT abstract (must be platform-specific)

| Concern | Fabric (T-SQL) | Databricks (Spark SQL) |
|---------|----------------|------------------------|
| String type | VARCHAR | STRING |
| Boolean type | BIT | BOOLEAN |
| Timestamp type | DATETIME2 | TIMESTAMP |
| JSON array expansion | `CROSS APPLY OPENJSON(col) WITH (...)` | `LATERAL VIEW EXPLODE(FROM_JSON(col, schema))` |
| JSON value extraction | `JSON_VALUE(col, '$.path')` | `GET_JSON_OBJECT(col, '$.path')` |
| Safe cast | `TRY_CAST(x AS type)` | `TRY_CAST(x AS type)` ✓ (Spark 3.4+) |

### Generated Macros

The projector generates a `macros/` folder with platform-abstraction macros:
- `kairos_safe_cast(column, type)` — safe cast (future-proofs for platforms without TRY_CAST)
- `kairos_json_value(column, path)` — single JSON value extraction
- `kairos_surrogate_key(columns)` — wrapper around dbt_utils for future override

---

## DD-003: Staging = Platform-Specific, Silver = Portable

**Status:** Accepted  
**Date:** 2026-04-30  
**Context:** Multi-platform dbt projection architecture

### Problem

Should we generate one set of models that works on all platforms, or separate models
per platform?

### Decision

**Hybrid approach:**
- **Staging models** are platform-specific (selected by `target_platform` parameter)
- **Silver/gold models** are portable (use dbt macros that resolve per adapter)

### Rationale

Staging is where platform-specific SQL lives (JSON extraction, type coercion from
raw bronze). By the time data reaches silver, all values are simple scalar types
that can be expressed portably via `dbt_utils.type_*()` macros.

This means:
- Changing platforms requires **regenerating staging** (different JSON patterns)
- Silver/gold models can switch platforms by **just changing the dbt profile** (no regen)

---

## DD-004: Keep "staging" Naming (Not "bronze")

**Status:** Accepted  
**Date:** 2026-04-30  
**Context:** dbt model layer naming

### Problem

Should the first dbt transformation layer be called "bronze" (matching medallion
architecture terminology) or "staging" (matching dbt convention)?

### Decision

Keep **"staging"** (`stg_{source}__{table}`).

### Rationale

- "Bronze" = raw data as landed by ingestion (Data Factory / ADF). These are
  Lakehouse tables or Unity Catalog tables — NOT dbt models.
- "Staging" = first dbt transform layer. Performs: rename, type cast, basic cleaning,
  JSON extraction. This IS a dbt model.
- Using "bronze" for dbt models would confuse the boundary between ingestion and
  transformation.
- dbt community convention uses `stg_` prefix universally.

---

## DD-005: Silver References Source-Staging Directly (No Bridge)

**Status:** Accepted  
**Date:** 2026-04-30  
**Context:** Layer wiring in dbt projection

### Problem

Should silver models reference staging directly, or go through an intermediate
"domain staging" layer?

```
Option A: stg_erp__orders → stg_domain__order → silver.order  (bridge)
Option B: stg_erp__orders → silver.order                       (direct)
```

### Decision

**Option B — direct reference.** Silver models `{{ ref('stg_erp__orders') }}`
directly. Mapping transforms (rename, type cast, SK generation) are applied
inline in the silver SELECT.

### Rationale

- Simpler DAG (fewer nodes)
- No intermediate materialization cost
- Mapping transforms are lightweight (column expressions, not joins)
- If a future need arises for a bridge, it can be added without breaking silver

---

## DD-006: Column-Level JSON, Not Table-Level physicalStorage

**Status:** Accepted  
**Date:** 2026-04-30  
**Context:** How to annotate columns that arrive as JSON strings

### Problem

When Data Factory lands data, some columns remain as JSON strings (arrays or objects).
How should we annotate this in the bronze vocabulary?

### Decision

Use **column-level** `kairos-bronze:contentType` annotation:
- `"json-array"` — column contains a JSON array to be expanded
- `"json-object"` — column contains a JSON object to be destructured
- (default: scalar, no annotation needed)

Do NOT add a table-level `physicalStorage` property.

### Rationale

- Data Factory flattens most structures at ingestion time
- Only individual columns end up as JSON strings
- Column-level annotation is more precise and actionable
- Avoids complex table-to-table relationships for storage modeling

---

## DD-007: Extend kairos-ext Namespace (Not New Namespace)

**Status:** Accepted  
**Date:** 2026-04-30  
**Context:** Where to put new projection-related annotations

### Problem

New annotations needed: `populationRequirement`, `derivationFormula`, `naturalKey`.
Should these go in a new namespace or extend existing `kairos-ext:`?

### Decision

Extend `kairos-ext:` namespace in `scaffold/kairos-ext.ttl`.

### Rationale

- These annotations control projection behavior (same domain as existing kairos-ext properties)
- Fewer prefixes for hub authors to manage
- `kairos-ext:` is already well-established in the toolkit

---

## DD-008: Generated Macros Package Alongside Models

**Status:** Accepted  
**Date:** 2026-04-30  
**Context:** How to deliver platform-abstraction macros to hub dbt projects

### Problem

Silver models need macros like `kairos_safe_cast()` and `kairos_json_value()`.
How should these be delivered?

### Decision

Generate a `macros/` folder inside the dbt output directory alongside models.
These macros use `{% if target.type == '...' %}` for platform dispatch.

### Rationale

- No external package dependency (beyond dbt-utils)
- Macros are versioned with the generated output
- Hub repos don't need to install a separate dbt package
- Macros can be regenerated/updated with `kairos-ontology project`
