# Silver Layer: Relationship Types (FK Columns)

## Overview

When running the silver projection (`project --target silver`), FK columns are
generated only when the projector can detect that an `owl:ObjectProperty`
represents a **many-to-one** relationship.  Without an explicit signal, the
projector cannot distinguish many-to-one from many-to-many or one-to-many.

## Recommended approach: `kairos-ext:` annotations (DD-022)

Use the DD-022 FK annotations in your `*-silver-ext.ttl` file.  These work on
any property — local or imported — and require only one line per FK.

### Simple FK (domain class holds the FK)

When the `rdfs:domain` class is the FK holder (e.g. `Order.placedBy → Customer`):

```turtle
ex:placedBy kairos-ext:silverForeignKey "true"^^xsd:boolean .
# → order table gets customer_sk column
```

### Reverse FK (range class holds the FK)

When the FK belongs on the child/range class (e.g. `Consignment.hasItem → Item`):

```turtle
mmt:hasConsignmentItem kairos-ext:silverForeignKeyOn mmt:ConsignmentItem .
# → consignment_item table gets consignment_sk column
```

> `silverForeignKeyOn` implies `silverForeignKey "true"` — no need to set both.

### Junction table (many-to-many)

```turtle
ex:usedSurvivorshipRule kairos-ext:junctionTableName "merge_survivorship_rule" .
```

## Decision framework

For each `owl:ObjectProperty`:

```
Is the relationship many-to-one from the domain class's perspective?
├── YES (e.g. Order → Customer via placedBy)
│   └── kairos-ext:silverForeignKey "true"  → FK on domain table
│
├── YES, but FK belongs on the OTHER side (parent → child)
│   └── kairos-ext:silverForeignKeyOn <ChildClass>  → FK on child table
│
├── NO — it is many-to-many
│   └── kairos-ext:junctionTableName "..."  → junction/bridge table
│
└── UNSURE / cross-domain connector
    └── Ask the domain expert; check cardinality in business rules
```

## Complete extension file example

```turtle
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
@prefix xsd:        <http://www.w3.org/2001/XMLSchema#> .
@prefix mmt:        <https://www.kairosflow.ai/ont/mmt/consignment#> .

# --- Ontology-level ---
<https://example.com/ont/consignment>
    kairos-ext:silverSchema            "silver_consignment" ;
    kairos-ext:silverIncludeImports    "true"^^xsd:boolean ;
    kairos-ext:namingConvention        "camel-to-snake" ;
    kairos-ext:includeNaturalKeyColumn "true"^^xsd:boolean .

# --- Class annotations ---
mmt:Consignment     kairos-ext:silverInclude "true"^^xsd:boolean ;
                    kairos-ext:scdType "2" .
mmt:ConsignmentItem kairos-ext:silverInclude "true"^^xsd:boolean ;
                    kairos-ext:scdType "2" .

# --- FK annotations (DD-022) ---
mmt:hasConsignmentItem kairos-ext:silverForeignKeyOn mmt:ConsignmentItem .
# → consignment_item table gets consignment_sk FK column

mmt:operatedBy kairos-ext:silverForeignKey "true"^^xsd:boolean .
# → inland_leg table gets inland_carrier_sk FK column
```

## Alternative: OWL cardinality restrictions

For ontological purity, you can use standard OWL restrictions instead of
`kairos-ext:` annotations.  This approach requires more lines but keeps the
extension file purely ontological:

```turtle
# Define inverse property (child → parent direction)
:belongsToConsignment a owl:ObjectProperty ;
    rdfs:domain mmt:ConsignmentItem ;
    rdfs:range  mmt:Consignment ;
    owl:inverseOf mmt:hasConsignmentItem .

# Add cardinality restriction
mmt:ConsignmentItem rdfs:subClassOf [
    a owl:Restriction ;
    owl:onProperty :belongsToConsignment ;
    owl:maxQualifiedCardinality "1"^^xsd:nonNegativeInteger ;
    owl:onClass mmt:Consignment
] .
```

The projector also accepts `owl:FunctionalProperty` as a FK signal:

```turtle
ex:placedBy a owl:ObjectProperty , owl:FunctionalProperty ;
    rdfs:domain ex:Order ; rdfs:range ex:Customer .
```

## Notes

- **Cross-domain FKs** (e.g. Consignment → Party) use schema-qualified FK
  references per S7.  Both domains must be projected.
- **S3 flattening:** Subtypes are folded into parent tables.  FKs between
  subtypes become self-referential FKs via the discriminator column.
- **S4 inlining:** Small reference tables (≤ `inlineRefThreshold` columns)
  are inlined — no separate table, no FK column generated.