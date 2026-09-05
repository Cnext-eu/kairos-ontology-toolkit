# DD-002: dbt SQL Dialect — Platform-Specific Generation

**Status:** Accepted (amended by [DD-215](dd-215-the-target-platform-names-the-engine-and-boolean-ness-is-rendered-per-adapter.md))
**Date:** 2026-04-30
**Affects:** `medallion_dbt_projector.py`, silver/gold templates, type maps
**Implementation:** Type maps `_SOURCE_TO_FABRIC`, `_SOURCE_TO_DATABRICKS`, `_PLATFORM_TYPE_MAPS`

### Context

dbt Core does NOT abstract SQL dialects. Model `.sql` files are sent verbatim to
the target warehouse engine. Different platforms use fundamentally different:
- Type names (VARCHAR vs STRING, BIT vs BOOLEAN)
- JSON functions (OPENJSON + CROSS APPLY vs EXPLODE(FROM_JSON(...)))
- String concatenation, row limiting

### Decision

Generate **platform-specific SQL** controlled by a `target_platform` parameter:
- `"fabric"` (default) — T-SQL dialect for `dbt-fabric` adapter
- `"databricks"` — Spark SQL dialect for `dbt-databricks` adapter

### What dbt DOES Abstract (safe to share)

- CTE syntax, CASE WHEN, `dbt_utils.generate_surrogate_key()`
- Materialization strategies, `ref()` / `source()` resolution

### What dbt Does NOT Abstract (must be platform-specific)

| Concern | Fabric (T-SQL) | Databricks (Spark SQL) |
|---------|----------------|------------------------|
| String type | VARCHAR | STRING |
| Boolean | BIT | BOOLEAN |
| Timestamp | DATETIME2 | TIMESTAMP |
| JSON array | `CROSS APPLY OPENJSON(col) WITH (...)` | `LATERAL VIEW EXPLODE(FROM_JSON(col, schema))` |
| JSON value | `JSON_VALUE(col, '$.path')` | `GET_JSON_OBJECT(col, '$.path')` |

### Amendment (DD-215): the Boolean row is a rendering rule, not only a type map

This decision was enforced for **type names** — `_PLATFORM_TYPE_MAPS` — but not for
**positions**. Because Fabric has no boolean type, the `BIT` row above also means a
canonically-BOOLEAN expression cannot stand alone wherever a condition is expected
(`WHERE`, `HAVING`, `ON`, `CASE WHEN`, an `AND`/`OR`/`NOT` operand), and conversely a
native predicate cannot stand in a value position. See
[DD-215](dd-215-the-target-platform-names-the-engine-and-boolean-ness-is-rendered-per-adapter.md).
