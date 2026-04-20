---
name: kairos-silver-projection
description: >
  Expert guide for designing and running the silver-layer projection.
  Guides the ontology designer through annotation decisions (R1-R15),
  generates MS Fabric DDL, Mermaid ERD, and ALTER TABLE FK scripts.
---

# Kairos Silver Projection Skill

You are helping the user generate a **MS Fabric / Delta Lake silver layer** from an OWL
ontology.  The silver layer is a structured relational layer (medallion architecture) where
ontology classes map to Delta Lake tables, properties map to columns, and relationships
become FK constraints or junction tables.

The projection rules (R1-R15) are encoded in `silver_projector.py` and driven by
`kairos-ext:` annotations in a separate `*-silver-ext.ttl` file (R15 — domain ontologies
must remain free of physical storage concerns).

---

## Phase 1 — Discover or create the projection extension file

### 1a — Check for existing file

```bash
ls ontology-hub/ontologies/*-silver-ext.ttl
```

- If found: load it and skip to Phase 2.
- If missing: create it using the template (Step 1b).

### 1b — Create from template

Copy the scaffold template for each domain ontology that should be projected:

```bash
cp "$(python -m kairos_ontology _scaffold_path)/ontology-hub/silver-ext.ttl.template" \
   ontology-hub/ontologies/{DOMAIN}-silver-ext.ttl
```

Or manually create `ontology-hub/ontologies/{DOMAIN}-silver-ext.ttl`.

The template is pre-populated with all R1-R15 annotations and defaults.
Replace `{DOMAIN}`, `{DOMAIN_URI}`, `{DOMAIN_ONTOLOGY_URI}`, and `{DOMAIN_EXTENSION_URI}`
with the actual values.

### Required annotation namespace

The annotation namespace must be exactly:
```turtle
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
```

---

## Phase 2 — Gather per-class design decisions

For each `owl:Class` in the domain ontology, ask the following questions
(only those that apply — skip irrelevant ones):

### 2a — Is this a reference / code list table? (R8)

> "Is `{ClassName}` a reference table (e.g. code list, enumeration seeded from named
> individuals)?"

If **yes**:
```turtle
ex:{ClassName}
    kairos-ext:isReferenceData "true"^^xsd:boolean ;
    kairos-ext:scdType "1" .
```
- Table will get `ref_` prefix.
- No SCD columns, no audit envelope.

### 2b — Is this a GDPR-sensitive satellite? (R7)

> "Does `{ClassName}` contain personal data that should be isolated in a 1:1 satellite
> table for access control (GDPR Art. 5(1)(f))?"

If **yes**, identify the parent class:
```turtle
ex:{ClassName}
    kairos-ext:gdprSatelliteOf ex:{ParentClass} .
```
- No surrogate key generated; PK = FK to parent.
- Recommend separate access-control policy on this table.

### 2c — Is this part of an inheritance hierarchy? (R6)

> "Does `{ClassName}` have subclasses? If yes, which inheritance strategy:
> `class-per-table` (joined-table) or `discriminator` (flat table with type column)?"

For **class-per-table** (default — no annotation needed):
- Each subclass gets its own table; PK = FK to supertype.

For **discriminator**:
```turtle
ex:{ClassName}
    kairos-ext:inheritanceStrategy "discriminator" ;
    kairos-ext:discriminatorColumn "entity_type" .
```

### 2d — SCD type (R5)

> "Should `{ClassName}` maintain full history (SCD Type 2, default) or just the current
> record (SCD Type 1, overwrite)?"

```turtle
ex:{ClassName}    kairos-ext:scdType "2" .   -- default, no need to annotate
ex:{ClassName}    kairos-ext:scdType "1" .   -- overwrite
```

### 2e — Partitioning / clustering (R10)

> "Should `{ClassName}` be partitioned or clustered for query performance?"

```turtle
ex:{ClassName}
    kairos-ext:partitionBy "_load_date" ;
    kairos-ext:clusterBy   "is_current, party_type" .
```

---

## Phase 3 — Gather per-property design decisions

For each `owl:ObjectProperty` in the domain:

### 3a — FK column vs junction table (R12 / R13)

> "Is `{PropertyName}` many-to-one (at most one value per subject) or many-to-many?"

**Many-to-one** → FK column (add `owl:maxQualifiedCardinality 1` restriction):
```turtle
ex:{ClassName} rdfs:subClassOf [
    a owl:Restriction ;
    owl:onProperty ex:{PropertyName} ;
    owl:maxQualifiedCardinality "1"^^xsd:nonNegativeInteger ;
    owl:onClass ex:{RangeClass}
] .

# Optional: override FK column name (R12)
ex:{PropertyName}
    kairos-ext:silverColumnName "fk_column_name" ;
    kairos-ext:silverDataType   "NVARCHAR(16)" .
```

**Many-to-many** → junction table (R13):
```turtle
ex:{PropertyName}
    kairos-ext:junctionTableName "{domain}_{property}_link" .
```

### 3b — Nullability overrides (R11)

By default, columns are nullable unless SHACL `sh:minCount 1` is set.
To force NOT NULL:
```turtle
ex:{PropertyName}    kairos-ext:nullable "false"^^xsd:boolean .
```

### 3c — Conditional FK (R14)

For FK columns only meaningful for certain discriminator subtypes:
```turtle
ex:{PropertyName}
    kairos-ext:conditionalOnType "SubtypeA SubtypeB" .
```

---

## Phase 4 — Run the projection

```bash
# Project a single ontology file + extension
python -m kairos_ontology project \
    --ontology ontology-hub/ontologies/{DOMAIN}.ttl \
    --target silver

# Project all domains in a hub
python -m kairos_ontology project --target silver
```

Artifacts are written to `output/silver/{DOMAIN}/`:
- `{DOMAIN}-ddl.sql` — CREATE TABLE statements (T-SQL / MS Fabric compatible)
- `{DOMAIN}-alter.sql` — ALTER TABLE statements for UNIQUE and FK constraints
- `{DOMAIN}-erd.mmd` — Mermaid `erDiagram` for this domain

**Automatically generated after all domains are projected:**
- `output/silver/master-erd.mmd` — cross-domain master ERD (all tables + FK relationships)
- `application-models/master-erd.mmd` — same file copied for display in the Kairos web UI

The master ERD merges every `*-erd.mmd` into a single diagram with one section per domain.
It is the primary artifact to review the full silver layer data model at a glance.

---

## Phase 5 — Review outputs

### Check per-domain DDL

Key things to verify:
- Schema name matches expected (`silver_{domain}`)
- Tables appear in correct order: root → subtype → satellite → reference
- Column ordering per table: SK → IRI → FK → discriminator → business → SCD → audit
- Reference tables have `ref_` prefix and no SCD/audit columns
- GDPR satellites use parent SK as PK, no own SK

### Check master ERD

Open `output/silver/master-erd.mmd` (or `application-models/master-erd.mmd`) in a
Mermaid viewer or the Kairos web UI.

Verify:
- All domains and their tables appear
- Cross-domain FK relationships are visible (e.g. `order` → `customer`)
- No orphaned tables

> **Tip**: The master ERD is the best way to review the full silver layer model with
> a client. Share `application-models/master-erd.mmd` for stakeholder review.

### Update master ERD manually (if needed)

The master ERD is auto-generated from per-domain ERDs. If you need to add cross-domain
relationships that aren't captured by FK annotations, add them directly to
`application-models/master-erd.mmd` after generation:

```
erDiagram
    %% Master ERD — my-hub (all domains)

    %% --- Domain: customer ---
    ...

    %% --- Domain: order ---
    ...

    %% Cross-domain relationships (manually added)
    CUSTOMER ||--o{ ORDER : "places"
```

### Fix and iterate

If adjustments are needed, edit `{DOMAIN}-silver-ext.ttl` and re-run:
```bash
python -m kairos_ontology project --target silver
```
The master ERD is regenerated automatically on every run.

---

## Column ordering convention (reference)

| Position | Column(s) |
|----------|-----------|
| 1 | `{table}_sk` — surrogate key (PK) |
| 2 | `{table}_iri` — OWL IRI lineage (UNIQUE) |
| 3 | FK columns (one per max-cardinality-1 object property) |
| 4 | Discriminator column (only for discriminator strategy) |
| 5 | Business columns (from OWL data properties) |
| 6 | `valid_from`, `valid_to`, `is_current` (SCD Type 2 only) |
| 7 | Audit envelope: `_created_at`, `_updated_at`, `_source_system`, `_load_date`, `_batch_id` |

## Table ordering convention (within a schema)

| Position | Type |
|----------|------|
| 1 | Root / stand-alone tables (no FK, not ref) |
| 2 | Subtype satellite tables (PK = FK to parent) |
| 3 | Satellite / junction tables (own SK + FK) |
| 4 | Reference tables (`ref_` prefix) |

---

## Standard SHACL integration (R11)

If SHACL shapes are present in `shapes/`, they are automatically merged at generation time.
A property becomes `NOT NULL` when:
1. The SHACL property shape has `sh:minCount 1`, **or**
2. `kairos-ext:nullable "false"^^xsd:boolean` is set on the OWL property.

---

## Common patterns

### Full annotated class block

```turtle
ex:Party
    kairos-ext:scdType "2" ;
    kairos-ext:partitionBy "_load_date" ;
    kairos-ext:clusterBy "is_current" .

ex:BelgianLegalForm
    kairos-ext:isReferenceData "true"^^xsd:boolean ;
    kairos-ext:scdType "1" .

ex:ContactDetails
    kairos-ext:gdprSatelliteOf ex:Party .
```

### Override column name and type

```turtle
ex:hasLegalForm
    kairos-ext:silverColumnName "legal_form_code" ;
    kairos-ext:silverDataType   "NVARCHAR(16)" .
```

### Junction table

```turtle
ex:hasEngagementMember
    kairos-ext:junctionTableName "engagement_team_member" .
```
