# Silver Layer: Relationship Types (FK Columns)

> **Resolved in DD-022.** The `kairos-ext:silverForeignKey` and
> `kairos-ext:silverForeignKeyOn` annotations (v2.29.0+) provide a simplified
> way to declare FK columns in extension files without OWL cardinality
> restrictions. See [DD-022](toolkit-design-decisions.md#dd-022-simplified-fk-annotations-for-silver-projection)
> and the silver skill for usage details.
>
> **Quick fix for the problem described below:**
> ```turtle
> # Instead of 5+ lines of OWL restrictions, use one annotation:
> mmt:hasConsignmentItem kairos-ext:silverForeignKeyOn mmt:ConsignmentItem .
> ```

## Problem

When running the silver projection (`project --target silver`), the generated DDL
produces tables with **no FK columns** — every table is an isolated island containing
only its surrogate key, IRI, business columns, and audit envelope. The ERD shows
entities but no relationship lines between them.

**Example — expected vs actual:**

```sql
-- EXPECTED: consignment_item has FK to parent consignment
CREATE TABLE silver_consignment.consignment_item (
    consignment_item_sk    STRING NOT NULL,
    consignment_item_iri   STRING NOT NULL,
    consignment_sk         STRING NULL,        -- ← FK to parent (MISSING!)
    item_sequence_number   BIGINT NULL,
    ...
);

-- ACTUAL: no FK column generated
CREATE TABLE silver_consignment.consignment_item (
    consignment_item_sk    STRING NOT NULL,
    consignment_item_iri   STRING NOT NULL,
    item_sequence_number   BIGINT NULL,
    ...
);
```

## Root Cause

The silver projector uses **R12** to determine which `owl:ObjectProperty` values
become FK columns. R12 requires an explicit `owl:maxQualifiedCardinality 1`
restriction on the class to signal "this class points to at most one instance of
the target class" — i.e., the relationship is **many-to-one** and should become a
FK column.

Without this restriction, the projector cannot distinguish:
- Many-to-one relationships (→ FK column on this table)
- Many-to-many relationships (→ junction table)
- One-to-many "has" relationships (→ FK belongs on the OTHER table)

Most reference models define `owl:ObjectProperty` declarations but **do not include
cardinality restrictions**, leaving the projector unable to generate FKs.

## Solution

### Step 1 — Define inverse properties in the domain ontology

Reference models typically define "parent → child" properties (e.g.
`hasConsignmentItem` from Consignment to ConsignmentItem). But the FK column belongs
on the **child** table. OWL cardinality restrictions apply to the **domain class** of
the property. Therefore, we need an **inverse property** with the child as domain:

```turtle
# In the hub's domain ontology file (e.g. consignment.ttl)
:belongsToConsignment a owl:ObjectProperty ;
    rdfs:domain mmt-consignment:ConsignmentItem ;
    rdfs:range  mmt-consignment:Consignment ;
    rdfs:label  "belongs to consignment"@en ;
    rdfs:comment "Links a consignment item to its parent consignment."@en ;
    owl:inverseOf mmt-consignment:hasConsignmentItem .
```

> **Why not modify the reference model?** Reference models are shared/upstream
> ontologies. Hub-specific inverse properties belong in the hub's domain ontology
> file — which already imports the reference model.

### Step 2 — Add cardinality restrictions in the silver extension file

In the `*-silver-ext.ttl`, add the max-cardinality-1 restriction on the child class:

```turtle
# In consignment-silver-ext.ttl
mmt-consignment:ConsignmentItem rdfs:subClassOf [
    a owl:Restriction ;
    owl:onProperty :belongsToConsignment ;
    owl:maxQualifiedCardinality "1"^^xsd:nonNegativeInteger ;
    owl:onClass mmt-consignment:Consignment
] .
```

This tells the projector: "ConsignmentItem points to **at most one** Consignment"
→ generate a FK column `consignment_sk` on the `consignment_item` table.

### Step 3 — For existing many-to-one properties (already correct direction)

Some properties already have the FK-holding class as their domain (e.g.
`operatedBy` with domain InlandLeg, range InlandCarrier). For these, just add the
restriction directly — no inverse property needed:

```turtle
# In intermodal-silver-ext.ttl
mmt-inland:InlandLeg rdfs:subClassOf [
    a owl:Restriction ;
    owl:onProperty mmt-inland:operatedBy ;
    owl:maxQualifiedCardinality "1"^^xsd:nonNegativeInteger ;
    owl:onClass mmt-inland:InlandCarrier
] .
```

### Step 4 — For many-to-many relationships (junction tables)

If a relationship is genuinely many-to-many (e.g. a merge event can use multiple
survivorship rules, and a rule can be used in multiple merges), annotate with a
junction table:

```turtle
# In mdm-silver-ext.ttl
:usedSurvivorshipRule
    kairos-ext:junctionTableName "merge_event_survivorship_rule" .
```

### Step 5 — Re-run the projection

```bash
python -m kairos_ontology project --target silver
```

## Decision Framework

Use this decision tree for each `owl:ObjectProperty`:

```
Is the property direction FROM the FK-holding class?
├── YES (e.g. operatedBy: InlandLeg → InlandCarrier)
│   └── Add max-1 restriction on the domain class → FK column generated
│
├── NO — property goes FROM parent TO child (e.g. hasOrderLine: PO → OrderLine)
│   └── Is it many-to-one from child's perspective?
│       ├── YES → Define inverse property on child + add max-1 restriction
│       └── NO (many-to-many) → Add kairos-ext:junctionTableName
│
└── UNCLEAR / cross-domain connector (no explicit domain)
    └── Skip — handle in cross-domain FK pass later
```

## Common Patterns in Freight/Logistics Ontologies

| Pattern | Example | FK Location |
|---------|---------|-------------|
| Parent → Child (composition) | Consignment → ConsignmentItem | Child table |
| Entity → Reference data | Crosswalk → SourceSystem | Entity table |
| Entity → Entity (association) | InlandLeg → InlandCarrier | The "many" side |
| Self-referential | GoldenRecord → GoldenRecord (mergedInto) | Same table |
| Cross-domain | Consignment → Party (hasConsignor) | Consignment table (later pass) |

## What the Extension File Should Look Like (Complete Example)

```turtle
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
@prefix xsd:        <http://www.w3.org/2001/XMLSchema#> .
@prefix :           <https://frachtgroup.com/ont/consignment#> .
@prefix mmt:        <https://www.kairosflow.ai/ont/mmt/consignment#> .

# --- Ontology-level annotations ---
<https://frachtgroup.com/ont/consignment>
    kairos-ext:silverSchema            "silver_consignment" ;
    kairos-ext:silverIncludeImports    "true"^^xsd:boolean ;
    kairos-ext:namingConvention        "camel-to-snake" ;
    kairos-ext:includeNaturalKeyColumn "true"^^xsd:boolean ;
    kairos-ext:inlineRefThreshold      "3"^^xsd:integer .

# --- Class annotations ---
mmt:Consignment
    kairos-ext:scdType              "2" ;
    kairos-ext:isReferenceData      "false"^^xsd:boolean ;
    kairos-ext:inheritanceStrategy  "class-per-table" ;
    kairos-ext:partitionBy          "_load_date" ;
    kairos-ext:clusterBy            "is_current" .

mmt:ConsignmentItem
    kairos-ext:scdType              "2" ;
    kairos-ext:isReferenceData      "false"^^xsd:boolean .

# --- Cardinality restrictions (FK generation) ---
mmt:ConsignmentItem rdfs:subClassOf [
    a owl:Restriction ;
    owl:onProperty :belongsToConsignment ;
    owl:maxQualifiedCardinality "1"^^xsd:nonNegativeInteger ;
    owl:onClass mmt:Consignment
] .

mmt:GoodsItem rdfs:subClassOf [
    a owl:Restriction ;
    owl:onProperty :belongsToConsignmentItem ;
    owl:maxQualifiedCardinality "1"^^xsd:nonNegativeInteger ;
    owl:onClass mmt:ConsignmentItem
] .
```

## Notes

- **Cross-domain FKs** (e.g. Consignment → Party for consignor/consignee) require
  the target domain to already be projected. These use schema-qualified FK comments
  per S7 (e.g. `-- FK: consignor_sk -> silver_party.trade_party(trade_party_sk)`).
  Handle in a separate pass after all within-domain FKs are established.

- **S3 flattening:** Subtypes (e.g. MasterConsignment, HouseConsignment) are
  flattened into the parent table. FKs between subtypes (hasHouseConsignment:
  Master → House) become self-referential FKs on the flattened table via the
  discriminator column.

- **Reference data inlining (S4):** If a referenced class has ≤3 business columns
  and is marked `isReferenceData "true"`, it gets inlined (no separate table, no FK
  column). The `inlineRefThreshold` annotation controls this.
