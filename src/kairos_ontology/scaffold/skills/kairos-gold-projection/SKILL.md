---
name: kairos-gold-projection
description: >
  Placeholder design document for the Gold layer projection (Power BI / dimensional model).
  Defines G1-G8 rules inferred from kairos-ext: annotations. No projector code exists yet.
---

# Kairos Gold Projection Skill (Placeholder)

This skill documents the **planned Gold layer projection rules** for generating
Power BI / dimensional model artifacts from OWL ontologies annotated with `kairos-ext:`
properties.

> **Status: Design document only.** No `gold_projector.py` code exists yet.
> These rules (G1-G8) capture the intended design for a future projection target.

## Architecture Context

The Kairos projection system uses a three-layer rule architecture:

```
R1-R16: Common Annotation Rules (kairos-ext:)
    ├── S1-S8: Silver Fabric Warehouse (implemented)
    └── G1-G8: Gold Power BI / DW (this document — planned)
```

The common annotations (R1-R16) define the shared vocabulary. Silver (S1-S8) and
Gold (G1-G8) projectors interpret these annotations differently for their target
platforms.

## Gold Rules G1-G8

| Rule | Name | Description | Uses Common Rule |
|------|------|-------------|-----------------|
| G1 | Star schema modeling | Classify tables as fact or dimension based on relationship patterns | New |
| G2 | dim_/fact_ prefixes | Gold tables use `dim_` and `fact_` prefixes | Counterpart to S8 |
| G3 | SCD Type 2 dimensions | Full history maintained on dimension tables | R5 (scdType) |
| G4 | GDPR row-level security | GDPR satellite → separate security role on dimension | R7 (gdprSatelliteOf) |
| G5 | Materialized hierarchies | Flatten inheritance into dimension columns for drill-down | R6 (inheritanceStrategy) |
| G6 | Reference → shared dimension | Reference data promoted to shared dimension with dim_ prefix | R8 (isReferenceData) |
| G7 | Aggregate tables | Pre-aggregated fact tables for common measures | New |
| G8 | Power BI optimized types | INT for booleans, date keys for date columns, optimized for DirectQuery/Import | New |

## G1 — Star Schema Modeling

**Intent:** Automatically classify OWL classes as facts or dimensions based on
their relationship patterns in the ontology.

**Heuristic (proposed):**
- Classes with many outgoing object properties (FK relationships) → **fact** tables
- Classes referenced by many other classes → **dimension** tables
- Reference data classes (R8) → always **dimension**
- GDPR satellites (R7) → dimension sub-tables with security roles

## G2 — dim_/fact_ Prefixes

**Intent:** Gold tables use `dim_` and `fact_` prefixes for Power BI naming conventions.
Silver tables (S8) use plain names — the prefix is added only in the Gold layer.

## G3 — SCD Type 2 Dimensions

**Intent:** Dimension tables use full SCD Type 2 history (valid_from, valid_to, is_current).
This uses the same `kairos-ext:scdType` annotation as Silver (R5), but Gold always
applies SCD2 to dimensions regardless of the annotation value.

## G4 — GDPR Row-Level Security

**Intent:** GDPR satellite tables (R7) map to separate security roles in Power BI.
Row-level security (RLS) rules are generated to restrict access to PII columns.

## G5 — Materialized Hierarchies

**Intent:** OWL class hierarchies (R6) are flattened into dimension columns for
Power BI drill-down navigation. Parent-child hierarchies become level columns
(Level1, Level2, etc.).

## G6 — Reference → Shared Dimension

**Intent:** Reference data tables (R8) are promoted to shared dimensions with
`dim_` prefix and connected to all fact tables that reference them.

## G7 — Aggregate Tables

**Intent:** Pre-aggregated fact tables for common measures, reducing query time
in Power BI Import mode.

## G8 — Power BI Optimized Types

**Intent:** Type mappings optimized for Power BI DirectQuery and Import modes:
- BOOLEAN → INT (Power BI handles INT more efficiently)
- DATE → INT date keys (YYYYMMDD format)
- Decimal precision tuned for DAX calculations

## Future Implementation Notes

When implementing `gold_projector.py`:
1. Read the same `kairos-ext:` annotations as the silver projector
2. Apply G1-G8 rules instead of S1-S8
3. Output artifacts: Power BI dataset definition, DAX measures template, RLS rules
4. The `--target gold` CLI flag should invoke this projector
