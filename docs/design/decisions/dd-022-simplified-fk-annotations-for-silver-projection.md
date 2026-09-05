# DD-022: Simplified FK Annotations for Silver Projection

**Status:** Proposed
**Date:** 2026-05-01
**Affects:** `projections/shared.py`, all three medallion projectors, `kairos-ext.ttl`
**Implementation:** `classify_foreign_keys()` / `ForeignKeyDescriptor` in
`src/kairos_ontology/core/projections/shared.py`

### Context

The silver projector generates FK columns (R12) only when an object property
has one of three signals: `kairos-ext:silverColumnName`, `owl:FunctionalProperty`,
or `owl:maxQualifiedCardinality 1` restriction. Reference models imported via
`owl:imports` (BSP, MMT, DCSA, FIBO) typically lack all three, producing tables
without FK columns — every table becomes an isolated island.

The existing workaround requires hub authors to define inverse properties and
add verbose OWL restriction syntax in extension files (5+ lines per FK). This is
error-prone and creates drift risk when reference models add new properties.

### Decision

Introduce two new `kairos-ext:` annotations for simplified FK declaration:

1. **`kairos-ext:silverForeignKey`** (boolean on `owl:ObjectProperty`):
   Acts as a 4th FK trigger. When `true`, the domain class's table gets a FK
   column pointing to the range class — equivalent to `owl:FunctionalProperty`
   but usable in extension files on imported properties.

2. **`kairos-ext:silverForeignKeyOn`** (class URI on `owl:ObjectProperty`):
   Overrides which class receives the FK column. Must be either the domain or
   range of the property. When set to the range class, the FK is placed on the
   range table pointing back to the domain table (reverse placement). Implies
   `silverForeignKey true`.

The OWL direction, qualification signals, redirection, authored physical column
names, nullability, and holder/target class endpoints are normalized once into
an immutable internal FK descriptor. Silver DDL, dbt Silver, and Gold consume
that descriptor rather than independently interpreting the annotations. Each
layer still applies its existing physical key type and naming rules.

Usage examples:

```turtle
# Simple: Order.placedBy → Customer (FK on Order table)
ex:placedBy kairos-ext:silverForeignKey true .

# Reverse: Consignment.hasItem → Item (FK on Item table, not Consignment)
ex:hasConsignmentItem kairos-ext:silverForeignKeyOn mmt:ConsignmentItem .

# With column name override
ex:placedBy kairos-ext:silverForeignKey true ;
            kairos-ext:silverColumnName "buyer_sk" .
```

### Rationale

| Approach | Pros | Cons |
|----------|------|------|
| OWL restrictions (current) | Ontologically pure | Verbose (5+ lines/FK), reference models lack them |
| `silverForeignKey` annotation | 1 line, works on imports | Slightly less OWL-pure |
| Auto-infer from property names | Zero config | Unreliable, model-dependent |

The annotation approach is the best trade-off: explicit (no guessing), minimal
syntax (1 line vs 5), and compatible with the DD-021 import whitelisting
workflow where extension files already claim imported classes.

### Consequences

- **Extension files become the FK control point** for imported reference models.
  Hub authors annotate the exact properties they want as FKs.
- **Backward compatible**: existing `owl:FunctionalProperty` and cardinality
  restrictions continue to work unchanged.
- **`silverForeignKeyOn` eliminates inverse property definitions** for
  parent→child relationships — the most common FK pattern in reference models.
- **Validation warnings** are emitted for invalid `silverForeignKeyOn` targets
  (class not in domain/range) or missing domain/range declarations.
- **No separate gold annotation is required** — Gold consumes the same normalized
  relationship while retaining Gold-specific dimension-key naming and types.
