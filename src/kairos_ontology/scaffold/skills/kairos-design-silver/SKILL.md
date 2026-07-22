---
name: kairos-design-silver
description: >
  Expert guide for designing silver-layer extension annotations (SCD types,
  natural keys, FK declarations, schema names) and understanding silver
  projection output. Covers R1-R16 annotation vocabulary and S1-S8 Silver
  Fabric Warehouse behaviours.
---

# Kairos Medallion Silver Skill

## Design fleet mode (DD-088)

Default is interactive: ask the user to confirm SCD type, natural key, foreign
key, schema, inheritance, and passthrough annotation choices. If the user
explicitly requests design fleet mode, make those checkpoint decisions with AI
judgment for testing speed, but mark them as **AI-approved** rather than
user-confirmed. Record rationale, confidence, mapping/source evidence, and
projection implications in `phases/silver/<domain>.md`; stop for low-confidence
keys/FKs, destructive history choices, PII/proprietary risk, or annotations that
could break downstream joins.

Any fleet override applies only to this skill invocation. It expires when the
skill ends or pauses and is never inherited by another skill or a later resume.

## Offline sample audit feedback (DD-089)

After dbt/silver projection, `kairos-ontology audit-silver-samples` provides
offline advisory QA for silver design choices. Review findings about missing
natural-key samples, FK-vs-target key shape mismatches, transform/type risks, and
generated SQL traceability before handing the package to the dataplatform.

## Lifecycle state (DD-080)

> The **kairos-flow** skill is the lifecycle orchestrator and the **only** writer of
> `ontology-hub/.kairos-state/status.md`. This skill plugs into that shared state; it
> does not maintain the global status file.

**On start (pre-flight):** read `ontology-hub/.kairos-state/` — the `status.md`
continuation region and this phase's log(s) at `phases/silver/<domain>.md` — to resume
open questions. Ignore `_archive/`. (`kairos-ontology status` gives the objective view.)

**On pause or finish:** append a *State update proposal* to `phases/silver/<domain>.md`
with OKF frontmatter (`type: kairos-phase-log`, `phase: silver`, `instance: <domain>`,
`status:`, `last_updated:`). Record decisions made and an **Open questions** list as the
resume anchor. Do **not** edit `status.md` directly — kairos-flow folds your proposal in.


You are helping the user **design** the silver layer of the medallion architecture.
This skill covers annotation design and output interpretation:

1. **Schema design** — Create and configure `kairos-ext:` annotations in
   `*-silver-ext.ttl` extension files that control silver DDL generation.
2. **Output interpretation** — Understand the DDL, ERD, and dbt model outputs
   produced when the **kairos-execute-project** skill runs the silver/dbt targets.

> **Design/Execute separation (DD-033):** This skill creates annotation files.
> To generate output, invoke the **kairos-execute-project** skill.

> **Draft model input (DD-086):** If
> `model/planning/draft-model/draft-model-report.md` or
> `draft-model-erd.mmd` exists, read it during pre-flight. Use natural-key and
> FK entries as review prompts only. A draft-report relationship or TMDL join is
> not an approved `silverForeignKey` / `silverForeignKeyOn` annotation until the
> user confirms it in this skill.
>
> **Data-product vertical slice:** If
> `model/planning/data-products/<product>/data-product-plan.yaml` exists, read it
> as a scoped agenda for one report pack/data product. Use `silver-question`
> entries to focus natural-key, FK, SCD, and reference-data review. The plan is
> advisory (`projection_authority: false`) and must never write silver TTL or
> bypass claim/mapping approval.

---

## Target-first aspirational stubs (DD-096)

Silver design is normally **binding-first**: a class gets a real Silver model once a
bronze source is mapped to it. The **target-first stub → bind loop** (opt-in, DD-096)
lets an *approved but not-yet-mapped* claim project a **stub** Silver target first, so
downstream Silver/Gold can be designed against a stable contract before mappings exist.

- **Derived, not annotated.** `aspirational` is **not** a silver-ext annotation you
  author — it is derived at projection time (approved, materialization-eligible claim
  ∧ unbound physical model). Do not add a field for it.
- **Typability caveat.** Stub columns are typed where typable
  (`kairos-ext:silverDataType` → `rdfs:range` → `VARCHAR(255)` fallback). Declaring
  `silverDataType` on properties makes stub columns precise before binding.
- **Clearing it.** A stub is cleared by **binding a mapping** (kairos-design-mapping),
  not by editing silver-ext. Re-projection replaces the stub with the real model.
- **OKF capture.** Record any target-first stub decisions in
  `phases/silver/<domain>.md`.

See the **kairos-execute-project** skill for the `--emit-aspirational-stubs` flag.

## Transformation readiness gate (BLOCKING)

Before creating or modifying Silver extension TTL, run:

```bash
$env:KAIROS_SKILL_CONTEXT = "1"
kairos-ontology check-transformation-readiness --stage silver
```

A non-zero result is blocking. Report its reasons verbatim and hand off to
**kairos-develop-dbt-transformation**. For every accepted candidate, the deterministic
gate must confirm the contracted model and synchronized virtual source; the existing
mapping/source coverage gates remain authoritative for virtual-table exact matches,
column mappings, `silverSourceRef`, and direct/replacement conflicts. Deferred candidates
must retain a rationale and distinct-grain statement. `status` is observational and does
not replace this command.

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

> **Transitive folding (issue #172):** discriminator folding is **transitive through
> unclaimed intermediate classes**. A subtype that reaches a claimed discriminator
> ancestor only via *unclaimed* (not separately projected) intermediates is still
> folded into that ancestor's table — and the intermediates' properties fold in too,
> labelled `-- from {SubtypeName}`. The walk stops at the **first claimed ancestor**,
> so single-level folding is unchanged.

### 2c-bis — Exclude a class from silver (`silverExclude`)

> "Should `{ClassName}` be kept in the ontology for inheritance/semantics but **not**
> materialised as its own silver table?" (e.g. an abstract role-marker class.)

```turtle
ex:{ClassName}    kairos-ext:silverExclude "true"^^xsd:boolean .
```

- The class emits **no** table.
- `silverExclude` **overrides** `silverInclude` / `silverIncludeImports`.
- Descendants still **inherit** the excluded class's properties; it is treated as an
  unclaimed (cross-domain) FK target.
- The projector emits a warning if a materialised class depends on the excluded class
  (subclasses it, or FK/junctions to it) so you can confirm the dropped table is
  intentional.


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
| `kairos-ext:scdValidFromColumn` | When source-effective history or as-of FK lookup is required | Mapped Silver timestamp column |
| `kairos-ext:isReferenceData` | ✅ Always | `"false"` |
| `kairos-ext:inheritanceStrategy` | Only if has subclasses | `"class-per-table"` |
| `kairos-ext:silverSourceRef` | If sourcing from bronze_expanded or a contracted model (DD-039/DD-093) | _(none — uses source())_ |
| `kairos-ext:namingConvention` | Ontology-level | `"camel-to-snake"` |
| `kairos-ext:includeNaturalKeyColumn` | Ontology-level | `"true"` |
| `kairos-ext:inlineRefThreshold` | Ontology-level | `"3"` |
| `kairos-ext:silverIncludeImports` | Ontology-level (only if uses `owl:imports`) | `"false"` |
| `kairos-ext:silverInclude` | Only on imported classes | `"false"` |
| `kairos-ext:silverExclude` | Only if a class must NOT get its own table | `"false"` |
| `kairos-ext:silverForeignKey` | On ObjectProperty (imported props lacking cardinality) | `"false"` |
| `kairos-ext:silverForeignKeyOn` | On ObjectProperty (reversal pattern) | _(none)_ |
| `kairos-ext:silverForeignKeyTemporalMode` | On an FK to an SCD2 parent | `"current"` or `"as-of"` |
| `kairos-ext:silverForeignKeyAsOfColumn` | When temporal mode is `"as-of"` | Physical source timestamp column |
| `kairos-ext:silverForeignKeyChangeDetection` | On an FK in an SCD2 child | `"true"` unless relationship changes are explicitly non-historical |

Run a structured semantic scan, then validate the authored extension:
```bash
kairos-ontology show-class-inventory --domain {DOMAIN} --profile kairos-design
kairos-ontology validate --syntax
```
Use the full-URI class list as the annotation checklist. Do not count Turtle text:
imports, alternate serialization, and blank-node expressions make text counts
semantically unreliable.

---

## Phase 3 — Gather per-property design decisions

> ⚠️ **Imported reference model properties** (from `owl:imports`) typically define
> `owl:ObjectProperty` without cardinality constraints. These will **NOT** generate
> FK columns automatically. You MUST annotate each many-to-one relationship with
> `kairos-ext:silverForeignKey "true"` or `kairos-ext:silverForeignKeyOn` in the
> extension file. See [§3e](#3e--dd-022-simplified-fk-annotations) below.

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

> 💡 **For imported properties** that you cannot modify, use the simpler
> `kairos-ext:silverForeignKey "true"` annotation instead of OWL restrictions.
> For parent→child relationships, use `kairos-ext:silverForeignKeyOn` to place
> the FK on the child table. See [§3e](#3e--dd-022-simplified-fk-annotations).

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
> - The target class has `kairos-ext:naturalKey` in its own domain's silver ext file
> - A source column from the current table maps to the NK property of the target
> - Or add an explicit `skos:exactMatch` targeting the ObjectProperty URI
>
> Cross-domain resolution: The projector automatically loads peer domain extension files
> to resolve naturalKey for FK targets in other domains (DD-027). You do NOT need to
> duplicate naturalKey declarations across extension files.

> **Anti-pattern — discriminator columns in naturalKey:**
>
> If your entity is populated from multiple source tables via UNION ALL (e.g.,
> `sales_invoices` + `purchase_invoices` → `Invoice`), you may be tempted to add a
> discriminator column (like `invoiceDirection`) to the naturalKey to ensure uniqueness.
>
> **Don't do this.** A discriminator is derived from *which source table* the row came
> from — it has no SKOS mapping from the source columns. The FK join logic requires every
> NK column to be resolvable via mappings. An unmapped discriminator makes the FK join
> incomplete (partial NULL).
>
> **Instead:** Use the actual business key that uniquely identifies the entity across all
> source tables (e.g., `invoiceId`). If the same ID can appear in both source tables with
> different meaning, the source data needs deduplication or the model needs rethinking —
> the discriminator belongs in a separate descriptive column, not in the naturalKey.

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

### 3e — DD-022: Simplified FK annotations

The standard FK detection (section 3a) relies on `owl:maxQualifiedCardinality 1`
or `owl:FunctionalProperty` to distinguish many-to-one from many-to-many. This
works well for classes defined inside the hub, but **imported reference model
properties** often lack OWL cardinality restrictions — they arrive as plain
`owl:ObjectProperty` with no restrictions in the hub's extension file.

Two extension annotations solve this without requiring changes to the imported
ontology:

#### `kairos-ext:silverForeignKey` (boolean)

Marks an object property as a FK column. Equivalent to declaring
`owl:FunctionalProperty` but works in extension files on imported properties
that cannot be modified.

```turtle
@prefix ref:       <https://referencemodels.kairos.cnext.eu/logistics#> .
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
@prefix xsd:       <http://www.w3.org/2001/XMLSchema#> .

# Mark an imported property as FK (many-to-one)
ref:hasShipperParty
    kairos-ext:silverForeignKey "true"^^xsd:boolean .
```

The FK column is placed on the **domain** table (the class that "has" the
property) by default, just like a standard cardinality-1 relationship.

#### `kairos-ext:silverForeignKeyOn` (class URI)

Overrides **which table** receives the FK column. Set the value to the
**range class** to reverse the FK direction — the range table gets a column
pointing back to the domain table. This is the standard parent→child pattern
(e.g., `Consignment hasConsignmentItem ConsignmentItem` where the FK lives on
`ConsignmentItem`).

```turtle
@prefix ref:       <https://referencemodels.kairos.cnext.eu/logistics#> .
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

# Parent → child: FK lives on the child (range) table
ref:hasConsignmentItem
    kairos-ext:silverForeignKeyOn ref:ConsignmentItem .
```

> **Note:** `silverForeignKeyOn` implies `silverForeignKey "true"` — there is no
> need to set both annotations on the same property.

#### Interaction with other annotations

- **`silverColumnName`** — fully compatible. Use it alongside either annotation
  to control the physical column name:
  ```turtle
  ref:hasShipperParty
      kairos-ext:silverForeignKey "true"^^xsd:boolean ;
      kairos-ext:silverColumnName "shipper_party_sk" .
  ```
- **`silverDataType`** — compatible, overrides the FK column's SQL type.
- **`conditionalOnType`** — compatible, restricts the FK to specific discriminator
  subtypes.
- **`junctionTableName`** — mutually exclusive. Do not combine FK annotations
  with junction-table annotations on the same property.

#### Temporal FK and child-history policy

Every FK to an SCD2 parent must state which parent version is intended:

```turtle
# Current-state loading: exactly one current parent row can match.
ref:issuedTo
    kairos-ext:silverForeignKey "true"^^xsd:boolean ;
    kairos-ext:silverForeignKeyTemporalMode "current" ;
    kairos-ext:silverForeignKeyChangeDetection "true"^^xsd:boolean .

# As-of loading: resolve the parent version effective at the source event time.
ref:Party
    kairos-ext:scdValidFromColumn "party_effective_at" .

ref:occurredAt
    kairos-ext:silverForeignKey "true"^^xsd:boolean ;
    kairos-ext:silverForeignKeyTemporalMode "as-of" ;
    kairos-ext:silverForeignKeyAsOfColumn "event_timestamp" ;
    kairos-ext:silverForeignKeyChangeDetection "false"^^xsd:boolean .
```

- `current` adds `is_current = 1` to the parent lookup and prevents historical
  parent rows from multiplying the child.
- `as-of` joins the source timestamp to `[valid_from, valid_to)`.
- The parent must declare `scdValidFromColumn`; otherwise its validity is system/load
  time and an as-of relationship is rejected rather than producing a plausible wrong join.
- `silverForeignKeyChangeDetection` controls whether the resolved FK surrogate key
  participates in the child `_row_hash`. The default is `true`.
- SCD2 dbt models use timestamp precision for `valid_from`/`valid_to`, so multiple
  changes on the same day remain distinct.

---

## Phase 4 — Generate output (handoff to projection skill)

> **Pre-silver claims gate (MANDATORY — DD-094).** Before generating the
> silver layer, verify that the ontology + mappings actually cover every source
> table the affinity reports assign to the in-scope domains — so silver is built
> against a **complete** ontology, not a partial one (`check-claims` includes the
> pre-silver mapping-coverage check):
>
> ```bash
> kairos-ontology check-claims
> # or scope to a single domain:
> kairos-ontology check-claims --domains <domain>
> ```
>
> - **Exit 0** → every affinity-assigned source table is mapped to a domain entity.
>   Proceed to projection.
> - **Exit 1** → STOP. The listed `(system.table)` pairs have domain affinity but
>   no source-to-domain mapping (no SKOS match on the bronze table or its columns).
>   Complete the mappings via the **kairos-design-mapping** skill (and, if classes
>   are missing, the **kairos-design-domain** skill), then re-check.
>
> `check-claims` is read-only and deterministic (no AI). Use `--warn-only`
> only as a deliberate, documented override (e.g. a domain you intentionally defer).

Once your silver extension annotations are complete **and the claims gate
is green**, generate the artifacts by invoking the **kairos-execute-project** skill
with target `silver` (for DDL + ERD) or `dbt` (for dbt models — requires SKOS
mappings).

For a contracted custom intermediate, first hand off to
**kairos-develop-dbt-transformation**. After `sync-dbt-contracts` and virtual-source
mapping, this skill remains authoritative for semantic natural-key properties, SK/IRI,
SCD/FK policy, and `kairos-ext:silverSourceRef`. The dbt contract owns physical output
columns/types and key columns; custom SQL owns relational logic. Confirm
`silverSourceRef` names the contracted model, then project separately for each required
adapter with `project --target dbt --platform <fabric|databricks>`.
For `meta.kairos.replaces_sources`, this annotation is a blocking part of governed
replacement coverage: it must be on the approved target class and equal the declaring
contract model name.

> **Design/Execute separation (DD-033):** This skill handles annotation *design*.
> The **kairos-execute-project** skill handles *generation*. If you need to
> iterate on outputs, edit the extension file here, then invoke projection again.

> **Next design step (optional):** if this domain also feeds a Power BI semantic
> model, design the gold annotations next via the **kairos-design-gold** skill
> before projecting the `powerbi` target.

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

If adjustments are needed, edit `{DOMAIN}-silver-ext.ttl` and re-run the projection
via the **kairos-execute-project** skill (target `silver` or `dbt`).
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
| 6 | `valid_from`, `valid_to` (TIMESTAMP), `is_current` (SCD Type 2 only) |
| 7 | Audit/lineage envelope: `_created_at`, `_updated_at`, `_source_system`, `_source_record_id`, `_loaded_at`, `_load_date`, `_batch_id` |
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

### FK on imported property (DD-022)

```turtle
# Simple FK — imported property with no OWL cardinality
ref:hasShipperParty
    kairos-ext:silverForeignKey "true"^^xsd:boolean ;
    kairos-ext:silverColumnName "shipper_party_sk" .

# Reversed FK — parent→child, FK lives on the child table
ref:hasConsignmentItem
    kairos-ext:silverForeignKeyOn ref:ConsignmentItem .
```

### Working with imported classes (DD-021)

When a domain ontology uses `owl:imports` to reference external models (e.g.,
reference models), imported classes are **NOT projected as separate tables** by
default. However, **properties from imported parents are always inherited
automatically** via ancestor traversal.

#### Architectural decision matrix

| Your goal | Action | Result |
|-----------|--------|--------|
| Inherit parent properties into child table | **None — automatic** | Child table includes all datatype + FK properties from the full `rdfs:subClassOf` chain |
| Project the parent as its own separate table | Add `silverInclude "true"` on the parent class | Parent gets its own table; child is **folded into it** via S3 (discriminator column) — child loses its own table |
| Project all imported classes as tables | Add `silverIncludeImports "true"` on ontology | All first-level imports get tables (use sparingly — can create many unwanted tables) |

> **Key insight:** `silverInclude` does NOT mean "inherit properties" — inheritance
> always works regardless. It means "project this class as its own table". When a
> parent IS claimed, S3 single-table inheritance activates: the child is folded into
> the parent table with a discriminator column.

#### When to ignore the DD-021 notice

The DD-021 message is **informational** (not a warning). You can safely ignore it when:
- Your domain class extends a reference model parent via `rdfs:subClassOf`
- You want your domain class as its **own** table (not folded into the parent)
- You want inherited parent properties in that table
- → All of this works by default. The notice confirms you have an unclaimed parent.

#### Per-class claiming (when you DO want a parent table)

```turtle
@prefix ref: <https://referencemodels.kairos.cnext.eu/party#> .
ref:TradeParty kairos-ext:silverInclude "true"^^xsd:boolean .
```

⚠️ **Impact:** If your domain has `hub:Customer rdfs:subClassOf ref:TradeParty`,
adding `silverInclude` on `TradeParty` means Customer will be **folded into** the
TradeParty table (S3 single-table inheritance). Customer will NOT get its own table.

#### Bulk claiming (all first-level imported classes)

```turtle
<https://contoso.com/ont/customer> kairos-ext:silverIncludeImports "true"^^xsd:boolean .
```

**Rules:**
- Bulk mode (`silverIncludeImports`) claims all classes from directly imported
  ontologies (first-level `owl:imports` only).
- Peer hub domains (other domains in the same hub) are **excluded** from bulk
  claiming — they have their own extension files.
- The silver schema comes from the **hub domain name** (e.g., `silver_customer`),
  not from the reference model namespace.
- Per-class `silverInclude` overrides bulk mode for individual classes.
- `silverInclude` on a parent triggers S3 — subtypes are folded into the parent table.

**Example extension file** (`customer-silver-ext.ttl`):
```turtle
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
@prefix ref: <https://referencemodels.kairos.cnext.eu/party#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

# Bulk-claim all imported reference model classes (each gets its own table)
<https://contoso.com/ont/customer>
    kairos-ext:silverSchema "silver_customer" ;
    kairos-ext:silverIncludeImports "true"^^xsd:boolean .

# Or claim individual classes (this parent becomes a table; subtypes fold into it)
ref:TradeParty
    kairos-ext:silverInclude "true"^^xsd:boolean ;
    kairos-ext:scdType "2" .
```

### Property inheritance from unprojected parents

When a projected class has a parent that is **not** in the projected set (i.e.,
not claimed via `silverInclude` or `silverIncludeImports`), the projector
automatically inherits datatype properties and FK object properties from the full
`rdfs:subClassOf` chain. **No action is required** — this is the default behavior.

The `_get_class_and_ancestors()` function traverses all ancestors, stopping at:
- W3C vocabulary URIs (`owl:Thing`, `rdfs:Resource`)
- Ancestors that ARE separately projected (S3 handles those via the parent table)

### Reference model extension defaults (DD-023)

Reference model repositories can ship **default extension files** alongside their
ontologies. These provide sensible silver annotations (scdType, naturalKey,
silverInclude, etc.) that downstream hubs inherit automatically.

**Naming convention:**
```
{ontology-stem}-silver-defaults.ttl   # e.g., bsp-party-silver-defaults.ttl
{ontology-stem}-gold-defaults.ttl
```

**Discovery:** When the catalog resolves an `owl:imports` URI, the toolkit looks
for a sibling `*-silver-defaults.ttl` alongside the resolved file.

**Merge priority (highest → lowest):**
1. Hub domain extension (`{domain}-silver-ext.ttl`) — always wins
2. Reference model defaults — fallback layer
3. Built-in projector conventions (rdfs:range inference)

**Override semantics:** If the hub's domain extension declares the same
subject+predicate as the defaults file, the defaults value is skipped.

**Example reference model defaults** (`bsp-party-silver-defaults.ttl`):
```turtle
@prefix kairos-ext: <https://kairos.community/ns/ext#> .
@prefix bsp: <https://bsp.2024.org/party#> .

# Pre-declare which classes are suitable for silver materialization
bsp:TradeParty kairos-ext:silverInclude "true"^^xsd:boolean ;
    kairos-ext:scdType "1" ;
    kairos-ext:naturalKey "partyCode" .

bsp:Buyer kairos-ext:silverInclude "true"^^xsd:boolean ;
    kairos-ext:scdType "1" .
```

**Hub override** (`customer-silver-ext.ttl`):
```turtle
# Override just scdType — naturalKey and silverInclude come from defaults
bsp:TradeParty kairos-ext:scdType "2" .
```

**Benefits:**
- Eliminates per-hub duplication of extension annotations
- `silverInclude` in defaults means hubs don't need to repeat claims
- Reference model repos are standard ontology-hubs with the toolkit installed
- Fully backward-compatible — hubs without defaults work unchanged

**How it works:**
- The projector walks `rdfs:subClassOf` from the projected class upward.
- Ancestor classes that are NOT separately projected contribute their properties
  to the child table.
- Ancestors that ARE projected are skipped (S3 flattening handles those via the
  parent table).
- Cycle protection prevents infinite loops.

**Warning:** The projector emits a DD-021 warning when unclaimed parents are
detected. This is informational — inherited properties will still appear. Review
the warning to confirm you don't need the parent as a separate table.

**Example:** If `Truck rdfs:subClassOf Vehicle` and only `Truck` is projected,
`Vehicle`'s properties (`registrationNumber`, etc.) appear on the `truck` table
automatically.

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
- **Optional custom source vocabulary** in
  `integration/sources/custom-transformations/{model}.vocabulary.ttl`, generated from
  `integration/transforms/dbt/models/**/*.yml` by `sync-dbt-contracts`
- **Silver schema** — domain ontologies with `kairos-ext:` annotations (Part A above)
- **SKOS mappings** in `model/mappings/{system}-to-{domain}.ttl`

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
python -m kairos_ontology project --target dbt --platform <fabric|databricks>

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
data platform repository. See the `kairos-package-dataplatform` skill for
setup instructions on adding it as a dependency via `packages.yml`.

---

## Session Management

> **MANDATORY:** Every silver design session MUST produce a session file that
> captures decisions made, items deferred, and design rationale. This enables
> traceability from projection warnings back to design decisions.

### On start — Check for existing session

```
ontology-hub/.kairos-state/phases/silver/
  └── {domain}.md
```

If a previous session exists, ask the user whether to continue or start fresh.

> **Starting fresh — archive, don't overwrite (DD-071).** When the user chooses to
> start a new session instead of resuming, first move any existing
> `ontology-hub/.kairos-state/phases/silver/{domain}.md` log for this domain into
> `ontology-hub/.kairos-state/_archive/` (create it if missing; use a
> collision-safe filename). Never delete a previous log. Then create the new phase log.

### Session file format

Save to `ontology-hub/.kairos-state/phases/silver/{domain}.md`:

```markdown
# Silver Design Session: {Domain}

**Started:** {ISO-8601}
**Last updated:** {ISO-8601}
**Status:** Complete | In Progress
**Toolkit version:** {version}

## Decisions Made

| Class | SCD Type | Natural Key | Inheritance | FK Relations | Schema | Status |
|---|---|---|---|---|---|---|
| {ClassName} | {1/2} | {key or —} | {discriminator/—} | {fk list or —} | {schema} | ✅/⚠️ |

## Deferred / TODO

| # | Class | Item | Reason | Resolve via |
|---|---|---|---|---|
| 1 | {ClassName} | {what is missing} | {why deferred} | kairos-design-silver |

## Design Rationale

| # | Question | Decision | Rationale |
|---|---|---|---|
| 1 | {question} | {choice made} | {why} |

## Warnings Acknowledged

| # | Warning | Classification | Action |
|---|---|---|---|
| 1 | No naturalKey for {Class} | Deferred — FK-child | Will derive from parent |
```

### Saving rules

- **Auto-save** after each class annotation is confirmed
- Record **every** deferred item with a reason
- When a class is skipped or left incomplete, record it as a deferred item
- On pause/completion, list remaining open items and confirm with user

---

## Related skills

| When you need | Invoke |
|---|---|
| Design/modify domain ontology classes and properties | **kairos-design-domain** |
| Design gold layer (Power BI star schema, measures) | **kairos-design-gold** |
| Create bronze vocabulary from source docs | **kairos-design-source** |
| Map source columns to domain properties | **kairos-design-mapping** |
| Run projections (generate dbt/DDL/TMDL output) | **kairos-execute-project** |
| Consume dbt package in data platform repo | **kairos-package-dataplatform** |
