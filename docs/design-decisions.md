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
