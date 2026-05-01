---
name: kairos-ontology-medallion-silver
description: >
  Expert guide for designing the silver-layer schema (DDL, ERD, FK scripts)
  AND generating dbt Core silver models from source-to-domain mappings.
  Covers R1-R16 annotation vocabulary, S1-S8 Silver Fabric Warehouse
  behaviours, and the full bronze-to-silver dbt pipeline.
---

# Kairos Medallion Silver Skill

You are helping the user with the **silver layer** of the medallion architecture.
This skill covers two complementary workflows:

1. **Schema design** — Generate MS Fabric / Delta Lake silver schema (DDL, ERD,
   FK constraints) from OWL ontology + `kairos-ext:` annotations.
2. **dbt model generation** — Generate dbt Core models that transform bronze data
   into silver tables using SKOS mappings + `kairos-map:` annotations.

---

## Part A — Silver Schema Design

The silver schema projection is governed by two rule sets:

- **R1-R16** — common annotation vocabulary shared across all projections, encoded as
  `kairos-ext:` annotations in a separate `*-silver-ext.ttl` file (R15 — domain ontologies
  must remain free of physical storage concerns).
- **S1-S8** — Silver Fabric Warehouse-specific behaviours encoded in the silver projector
  (`medallion_silver_projector.py`). These rules adapt the common annotations for the physical
  constraints and conventions of MS Fabric Warehouse / Spark SQL.

---

## Phase 1 — Discover or create the projection extension file

### 1a — Check for existing file

```bash
ls ontology-hub/model/extensions/*-silver-ext.ttl
```

- If found: load it and skip to Phase 2.
- If missing: create it using the template (Step 1b).

### 1b — Create from template

Copy the scaffold template for each domain ontology that should be projected:

```bash
cp "$(python -m kairos_ontology _scaffold_path)/ontology-hub/silver-ext.ttl.template" \
   ontology-hub/model/extensions/{DOMAIN}-silver-ext.ttl
```

Or manually create `ontology-hub/model/extensions/{DOMAIN}-silver-ext.ttl`.

The template is pre-populated with all R1-R16 annotations and defaults.
Replace `{DOMAIN}`, `{DOMAIN_URI}`, `{DOMAIN_ONTOLOGY_URI}`, and `{DOMAIN_EXTENSION_URI}`
with the actual values.

### Required annotation namespace

The annotation namespace must be exactly:
```turtle
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
```

---

## Phase 2 — Gather per-class design decisions

> **⚠️ IMPORTANT — Explicit annotation mandate:**
> Every class MUST have **all applicable annotations written explicitly** in the
> extension TTL, **even when the value matches the projector default**. This ensures
> that the projection output is fully deterministic and reproducible — if the extension
> file is re-created from scratch, the output must remain identical.
>
> **Never rely on implicit defaults.** If a class is SCD Type 2, write `scdType "2"`.
> If a class is NOT reference data, write `isReferenceData "false"`.

For each `owl:Class` in the domain ontology, ask the following questions
and **always write the annotation** — even when the answer is the default:

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
- **S4 note:** reference tables with ≤3 business columns will be automatically inlined
  into the referencing parent table (see S4 — Inline small ref tables).

If **no** (standard table — still write explicitly):
```turtle
ex:{ClassName}
    kairos-ext:isReferenceData "false"^^xsd:boolean .
```

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

For **class-per-table** (default — still write explicitly):
```turtle
ex:{ClassName}
    kairos-ext:inheritanceStrategy "class-per-table" .
```

For **discriminator**:
```turtle
ex:{ClassName}
    kairos-ext:inheritanceStrategy "discriminator" ;
    kairos-ext:discriminatorColumn "entity_type" .
```

> **S3 note:** In the silver layer, ALL subtypes are always flattened into the parent
> table regardless of the `inheritanceStrategy` annotation value. Subtype properties
> become nullable columns with a `-- from {SubtypeName}` comment. The annotation is
> preserved in the extension file for future Gold-layer projections.

### 2d — SCD type (R5)

> "Should `{ClassName}` maintain full history (SCD Type 2, default) or just the current
> record (SCD Type 1, overwrite)?"

Always write explicitly:
```turtle
ex:{ClassName}    kairos-ext:scdType "2" .   -- history (write even though it's default)
ex:{ClassName}    kairos-ext:scdType "1" .   -- overwrite
```

### 2e — Partitioning / clustering (R10)

> "Should `{ClassName}` be partitioned or clustered for query performance?"

```turtle
ex:{ClassName}
    kairos-ext:partitionBy "_load_date" ;
    kairos-ext:clusterBy   "is_current, party_type" .
```

### 2f — Annotation completeness check (new)

After annotating all classes, verify completeness. **Every** non-GDPR, non-satellite
class in the domain MUST have at minimum:

| Annotation | Required? | Default value |
|------------|-----------|--------------|
| `kairos-ext:scdType` | ✅ Always | `"2"` |
| `kairos-ext:isReferenceData` | ✅ Always | `"false"` |
| `kairos-ext:inheritanceStrategy` | Only if has subclasses | `"class-per-table"` |
| `kairos-ext:namingConvention` | Ontology-level | `"camel-to-snake"` |
| `kairos-ext:includeNaturalKeyColumn` | Ontology-level | `"true"` |
| `kairos-ext:inlineRefThreshold` | Ontology-level | `"3"` |

Run a quick scan:
```bash
# Count classes vs annotated classes — they should match
grep -c "owl:Class" ontology-hub/model/ontologies/{DOMAIN}.ttl
grep -c "kairos-ext:scdType" ontology-hub/model/extensions/{DOMAIN}-silver-ext.ttl
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

### 3b — FK auto-inference from natural key

When no explicit SKOS mapping targets the `owl:ObjectProperty` URI, the dbt
projector can **auto-infer** the FK join by matching source columns to the
target class's natural key:

1. The range class has `kairos-ext:naturalKey` (e.g., `"typeCode"`)
2. A source column in the **current table** maps to that NK property (e.g.,
   `bronze:tblClient_TypeCode skos:exactMatch ex:typeCode`)
3. → The projector generates `LEFT JOIN {{ ref('target_model') }}` using the
   NK column in the join condition

This eliminates the need for redundant explicit FK mappings. The auto-inference
only activates when exactly one unambiguous candidate exists per NK component.

> **Tip**: If the FK join shows `CAST(NULL ...)`, check that:
> - The target class has `kairos-ext:naturalKey`
> - A source column from the current table maps to the NK property of the target
> - Or add an explicit `skos:exactMatch` targeting the ObjectProperty URI

### 3c — Nullability overrides (R11)

By default, columns are nullable unless SHACL `sh:minCount 1` is set.
To force NOT NULL:
```turtle
ex:{PropertyName}    kairos-ext:nullable "false"^^xsd:boolean .
```

### 3d — Conditional FK (R14)

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
    --ontology ontology-hub/model/ontologies/{DOMAIN}.ttl \
    --target silver

# Project all domains in a hub
python -m kairos_ontology project --target silver
```

Artifacts are written to the dbt project tree under `output/medallion/dbt/`:

**DDL & constraints** (in `analyses/{DOMAIN}/`):
- `{DOMAIN}-ddl.sql` — CREATE TABLE statements (Spark SQL / MS Fabric Warehouse compatible)
- `{DOMAIN}-alter.sql` — ALTER TABLE statements for UNIQUE and FK constraints

**ERD diagrams** (in `docs/diagrams/{DOMAIN}/`):
- `{DOMAIN}-erd.mmd` — Mermaid `erDiagram` for this domain
- `{DOMAIN}-erd.svg` — SVG render of the ERD (requires Mermaid CLI)

**Automatically generated after all domains are projected:**
- `output/medallion/dbt/docs/diagrams/master-erd.mmd` — cross-domain master ERD (all tables + FK relationships)
- `output/medallion/dbt/docs/diagrams/master-erd.svg` — SVG render of the master ERD

The master ERD merges every `*-erd.mmd` into a single diagram with one section per domain.
It is the primary artifact to review the full silver layer data model at a glance.

### SVG export setup

SVG rendering requires the Mermaid CLI (`mmdc`). If not installed, `.mmd` files are
still generated but SVG export is skipped with an info message.

```bash
# Install in the hub repo (one-time)
npm install

# Or install globally
npm install -g @mermaid-js/mermaid-cli
```

Hub repos scaffolded with `kairos-ontology new-repo` already include a `package.json`
with `@mermaid-js/mermaid-cli` as a dev dependency — just run `npm install`.

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

Open `output/medallion/dbt/docs/diagrams/master-erd.mmd` in a
Mermaid viewer or the Kairos web UI.

Verify:
- All domains and their tables appear
- Cross-domain FK relationships are visible (e.g. `order` → `customer`)
- No orphaned tables

> **Tip**: The master ERD is the best way to review the full silver layer model with
> a client. Share `output/medallion/dbt/docs/diagrams/master-erd.mmd` for stakeholder review.

### Update master ERD manually (if needed)

The master ERD is auto-generated from per-domain ERDs. If you need to add cross-domain
relationships that aren't captured by FK annotations, add them directly to
`output/medallion/dbt/docs/diagrams/master-erd.mmd` after generation:

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
| 8 | `_row_hash` BINARY — SHA-256 hash of business columns (S5) |
| 9 | `_deleted_at` TIMESTAMP NULL — soft-delete tracking (S6) |

## Table ordering convention (within a schema)

| Position | Type |
|----------|------|
| 1 | Root / stand-alone tables (no FK, not ref) |
| 2 | Subtype satellite tables (PK = FK to parent) |
| 3 | Satellite / junction tables (own SK + FK) |
| 4 | Reference tables (`ref_` prefix) |

---

## Standard SHACL integration (R11)

If SHACL shapes are present in `model/shapes/`, they are automatically merged at generation time.
A property becomes `NOT NULL` when:
1. The SHACL property shape has `sh:minCount 1`, **or**
2. `kairos-ext:nullable "false"^^xsd:boolean` is set on the OWL property.

---

## Silver Fabric Warehouse Rules (S1-S8)

These rules are specific to the silver-layer Fabric Warehouse projector and adapt the
common R1-R16 annotation vocabulary to the physical constraints of MS Fabric Warehouse
and Spark SQL.

### S1 — Spark SQL types

All data types are Spark SQL native. Type mappings:

| Logical type | Spark SQL type |
|--------------|---------------|
| Boolean | `BOOLEAN` (not BIT) |
| Timestamp / datetime | `TIMESTAMP` (not DATETIME2) |
| String / text | `STRING` (not NVARCHAR) |
| Floating point | `DOUBLE` (not FLOAT) |

SK, IRI, discriminator, and audit columns all use `STRING`, `TIMESTAMP`, or `BOOLEAN`.

### S2 — Constraints as comments

Fabric Warehouse cannot enforce PK, FK, or UNIQUE constraints. The projector emits them
as DDL comments instead of enforceable SQL:

```sql
-- PK: party_sk
-- FK: party_sk -> silver_customer.party(party_sk)
-- UNIQUE: party_iri
```

The `{DOMAIN}-alter.sql` file is **documentation-only** — it is not executable.

### S3 — Full inheritance flattening

In the silver layer, **all** subtypes are merged into their parent table — not just
empty ones (which was the old R16 behaviour). This applies regardless of the
`inheritanceStrategy` annotation value.

**Behaviour:**
- Subtype properties become nullable columns with a `-- from {SubtypeName}` comment
- A `{table}_type` discriminator column is auto-generated if none is annotated
  via `kairos-ext:discriminatorColumn`
- GDPR satellites are **exempt** — they remain separate tables
- The `inheritanceStrategy` annotation is preserved for future Gold-layer projections

**Example output:**
```sql
-- S3: subtypes flattened: IndividualClient, OrganisationClient, SpecialClient
CREATE TABLE silver_domain.client (
    client_sk       STRING NOT NULL,
    client_iri      STRING NOT NULL,
    client_type     STRING,           -- auto-generated discriminator
    name            STRING,
    special_rating  INT,              -- from SpecialClient
    ...
)
```

### S4 — Inline small ref tables

Reference tables (R8) with **≤3 business columns** are automatically denormalized
(inlined) into the referencing parent table. The inlined columns are prefixed with the
reference entity name.

**Example:** `ref_belgian_legal_form` with columns `code`, `label` →
parent table gets `belgian_legal_form_code STRING`, `belgian_legal_form_label STRING`.

The threshold is configurable via `kairos-ext:inlineRefThreshold` on the ontology:
```turtle
<https://example.org/ontology> kairos-ext:inlineRefThreshold "5"^^xsd:integer .
```

### S5 — _row_hash

A `_row_hash BINARY` column is added to the audit envelope. It contains a SHA-256 hash
of all business columns, enabling efficient incremental MERGE/upsert operations without
comparing every column.

### S6 — _deleted_at

A `_deleted_at TIMESTAMP NULL` column is added to the audit envelope for soft-delete
tracking. When a source system signals a record deletion, this column records the
timestamp instead of physically removing the row.

### S7 — Canonical schema

Each class belongs to exactly one schema — its owning domain (`silver_{domain}`).
Tables are **never** duplicated across domain schemas. Cross-domain references use
FK comments (S2) with schema-qualified names:

```sql
-- FK: customer_sk -> silver_customer.customer(customer_sk)
```

### S8 — No dim_/fact_ prefixes

Silver-layer tables use plain entity names (e.g. `party`, `engagement`).
The `dim_`/`fact_` naming convention is reserved for the Gold layer.

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

---

## Part B — dbt Silver Model Generation

This section covers generating a **dbt Core project** that transforms bronze
(source system) data into silver (domain-conformed) tables. The transformation
is driven by:

- **Domain ontology** — OWL classes and properties defining the silver target schema
- **Bronze vocabulary** — `kairos-bronze:` descriptions of source system tables/columns
- **Source-to-domain mappings** — SKOS match predicates linking source columns to domain
  ontology properties, enriched with `kairos-map:` annotations for SQL transforms
- **SHACL shapes** — data quality constraints converted to dbt tests

### Prerequisites

Before running the dbt projection, ensure these artifacts exist in the hub:

- **Source vocabulary** in `integration/sources/{system-name}/{system-name}.vocabulary.ttl`
- **Silver schema** — domain ontologies with `kairos-ext:` annotations (Part A above)
- **SKOS mappings** in `model/mappings/{system-name}/`

### Architecture

```
Bronze (source systems)          Silver (domain model)
+-------------------+            +------------------+
| adminpulse.ttl    |--SKOS--->  | party.ttl        |
| erp-navision.ttl  |  mappings  | client.ttl       |
+-------------------+            +------------------+
        |                                |
  dbt sources.yml                dbt silver models
                                 dbt schema + tests
```

### Running the projection

```bash
# Generate dbt project for all domains
python -m kairos_ontology project --target dbt

# Generate for a specific ontology
python -m kairos_ontology project --ontology ontology-hub/model/ontologies/client.ttl --target dbt
```

### Output structure

```
output/medallion/dbt/
  models/
    silver/{source}/
      _{source}__sources.yml         # dbt source definitions
    silver/{domain}/
      _{domain}__models.yml          # Schema + SHACL tests
      {entity}.sql                   # Silver entity models (tables)
  dbt_project.yml
  packages.yml                       # dbt_utils, dbt_expectations
```

### SKOS mapping reference

| SKOS Property | Meaning | dbt Behaviour |
|---------------|---------|---------------|
| `skos:exactMatch` | 1:1, same semantics | Direct column mapping (default) |
| `skos:closeMatch` | 1:1 but needs transformation | Same SQL; annotated in `_models.yml` |
| `skos:narrowMatch` | Source more specific → domain broader | Same SQL; annotated in `_models.yml` |
| `skos:broadMatch` | Source broader → filter/split required | Same SQL; annotated in `_models.yml` |
| `skos:relatedMatch` | Indirect — business logic / lookup | Same SQL; annotated in `_models.yml` |

> **Multi-target columns:** One source column can map to multiple target properties
> using separate SKOS match statements. All mappings are generated.

### kairos-map: properties

| Property | Level | Description |
|----------|-------|-------------|
| `kairos-map:mappingType` | Table | `direct`, `split`, `merge` (supported); `pivot`, `lookup` (planned — emits warning) |
| `kairos-map:transform` | Column | SQL expression (`source.` prefix for columns) |
| `kairos-map:sourceColumns` | Column | Space-separated source columns used |
| `kairos-map:defaultValue` | Column | Default when source is NULL |
| `kairos-map:filterCondition` | Table | SQL WHERE fragment |
| `kairos-map:deduplicationKey` | Table | Columns for ROW_NUMBER() dedup |
| `kairos-map:deduplicationOrder` | Table | ORDER BY for dedup |

> **Warning:** Using `pivot` or `lookup` as `mappingType` will emit a warning
> and skip that table mapping. These patterns require manual dbt model authoring.

### dbt test mapping from SHACL

| SHACL constraint | dbt test |
|-----------------|----------|
| `sh:minCount 1` | `not_null` |
| `sh:maxCount 1` | `unique` |
| `sh:in` | `accepted_values` |
| `sh:pattern` | regex test |
| `sh:minLength` / `sh:maxLength` | length constraint |

### Validate locally

```bash
cd output/medallion/dbt
dbt deps       # Install packages
dbt compile    # Validate SQL
dbt run        # Execute models (requires warehouse connection)
dbt test       # Run SHACL-derived tests
```

### Downstream consumption

The generated dbt project is designed to be consumed as a **dbt package** in a
data platform repository. See the `kairos-ontology-dataplatform` skill for
setup instructions on adding it as a dependency via `packages.yml`.
