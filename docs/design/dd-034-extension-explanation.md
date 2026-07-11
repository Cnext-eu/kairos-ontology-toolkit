# Extension Vocabulary Explanation (`kairos-ext:`)

**Audience:** ontology hub authors writing `*-silver-ext.ttl` / `*-gold-ext.ttl`
extension files.
**Source of truth:** `src/kairos_ontology/scaffold/kairos-ext.ttl`
(namespace `https://kairos.cnext.eu/ext#`, prefix `kairos-ext:`).
**Related:** DD-007 (extend kairos-ext namespace), DD-021 (import whitelisting),
DD-022 (FK annotations), DD-034 (vocabulary as single source of truth).

---

## 1. What this vocabulary is for

Domain ontologies (`model/ontologies/*.ttl`) describe the **business meaning** of
entities and must stay free of physical storage concerns (R15). The medallion
projections (silver DDL/ERD, gold Power BI star schema) need **physical hints** —
table names, SCD types, surrogate-key definitions, measures, etc. Those hints live
in **separate extension files** that `owl:imports` the domain ontology and annotate
its classes/properties with `kairos-ext:` annotations.

```
model/
  ontologies/client.ttl        # business meaning (no storage concerns)
  extensions/
    client-silver-ext.ttl      # silver physical hints (imports client.ttl)
    client-gold-ext.ttl        # gold/Power BI hints (imports client.ttl)
```

---

## 2. Naming conventions (DD-034)

- **Layer-prefixed names** (`silver*`, `gold*`, `bronze*`) are layer-specific.
- **Bare names** denote cross-layer or layer-neutral concepts (e.g. `naturalKey`,
  `scdType`, `partitionBy`, `populationRequirement`).
- A local name is **never reused** across the `kairos-ext`, `kairos-bronze`, and
  `kairos-map` vocabularies — see the `incrementalColumn` caveat in §7.
- Every annotation a projector reads **must be declared** in `kairos-ext.ttl`. A
  guard test (`tests/test_ext_vocabulary_coverage.py`) enforces this.

**RESERVED** in the tables below means the annotation is declared (and documented)
but **not yet consumed** by a projector — safe to ignore until it is wired up.

---

## 3. Silver layer annotations

### 3a. Ontology-level (set on the `owl:Ontology` resource)

| Annotation | Range | Purpose | Default |
|---|---|---|---|
| `silverSchema` | string | Target Delta Lake / Fabric schema name (R1) | `silver_{domain}` |
| `surrogateKeyStrategy` | string | **RESERVED** — intended SK generation strategy (R2). SKs are currently generated unconditionally | `uuid` |
| `includeNaturalKeyColumn` | boolean | Include `{table}_iri` IRI lineage column (R3) | `true` |
| `namingConvention` | string | Column/table naming convention (R4). Values: `camel-to-snake` | `camel-to-snake` |
| `auditEnvelope` | string | Comma-separated `name TYPE` audit columns appended to every non-reference table (R9) | — |
| `inlineRefThreshold` | integer | Max business columns for a reference table to be inlined into the parent (S4) | `3` |

### 3b. Class-level

| Annotation | Range | Purpose |
|---|---|---|
| `silverTableName` | string | Explicit table name override (R4) |
| `scdType` | string | Slowly Changing Dimension type (R5, R8). `1` = overwrite, `2` = history (default `2`) |
| `inheritanceStrategy` | string | OWL subclass projection (R6, R16). `class-per-table` (default) or `discriminator` |
| `discriminatorColumn` | string | Discriminator column name; only with `inheritanceStrategy = discriminator` (R6) |
| `gdprSatelliteOf` | class | Marks this class as a GDPR satellite whose PK/FK points to the given parent (R7) |
| `isReferenceData` | boolean | Reference/code-list table → `ref_` prefix + SCD type 1 (R8) |
| `partitionBy` | string | Column(s) for `PARTITIONED BY` (R10) |
| `clusterBy` | string | Column(s) for Delta Lake Liquid Clustering `CLUSTER BY` (R10) |
| `naturalKey` | string | Space-separated property names (camelCase) forming the business key — drives SK generation and IRI construction. See §5 |

> **S3 Inheritance behaviour (DD-035):** The `inheritanceStrategy` annotation
> controls whether child classes (subtypes) get their own tables or are folded into
> the parent:
>
> - **`class-per-table`** (default): each subtype gets its own table with inherited
>   properties copied down. This is the safe default that preserves all information.
> - **`discriminator`**: subtypes are folded into the parent table, which gains a
>   discriminator column and any subtype-specific columns. Use when subtypes share a
>   single source table distinguished by a type column.
>
> All three projectors (silver, dbt, gold) now respect this annotation consistently.

### 3c. Property-level

| Annotation | Range | Purpose |
|---|---|---|
| `silverColumnName` | string | Explicit column name override (R4, R12) |
| `silverDataType` | string | SQL data type override, e.g. `NVARCHAR(64)` (R12) |
| `nullable` | boolean | Nullability override (R11). `false` = NOT NULL (SHACL `sh:minCount 1` also implies NOT NULL) |
| `populationRequirement` | string | Intent: `required` / `optional` (default) / `derived` / `unmapped` |
| `derivationFormula` | string | SQL expression for a `derived` property; may reference sibling columns |
| `junctionTableName` | string | Junction/bridge table name for a many-to-many object property (R13) |
| `conditionalOnType` | string | Space-separated discriminator subtypes for which this FK column is active (R14) |

---

## 4. Gold layer annotations (Power BI star schema, G1–G8)

### 4a. Ontology-level

| Annotation | Range | Purpose | Default |
|---|---|---|---|
| `goldSchema` | string | Target gold schema name | `gold_{domain}` |
| `goldInheritanceStrategy` | string | Gold subclass strategy: `class-per-table` (default) or `discriminator` | `class-per-table` |
| `generateDateDimension` | boolean | Auto-generate a `dim_date` table | `true` |
| `generateTimeIntelligence` | boolean | Generate a Time Intelligence calculation group (YTD, QTD, PY, YoY %). Requires a date dimension | `false` |

### 4b. Class-level

| Annotation | Range | Purpose |
|---|---|---|
| `goldTableType` | string | Override star-schema classification (G1): `fact` / `dimension` / `bridge` |
| `goldTableName` | string | Explicit gold table name (without `dim_`/`fact_` prefix) |
| `goldExclude` | boolean | Exclude this class from gold projection entirely |
| `perspective` | string | Space-separated perspective names; each generates a Power BI perspective grouping its member tables |
| `incrementalColumn` | string | **RESERVED** (read into a field but not yet rendered) — intended date column for a Power BI incremental refresh policy. **Distinct from `kairos-bronze:incrementalColumn`** — see §7 |

### 4c. Property-level

| Annotation | Range | Purpose |
|---|---|---|
| `goldColumnName` | string | Gold column name override (bypasses camel-to-snake) |
| `goldDataType` | string | SQL data type override for gold (G8) |
| `measureExpression` | string | DAX measure expression (e.g. `SUM([amount])`); property becomes a measure, not a column |
| `measureFormatString` | string | DAX format string for the measure (e.g. `$#,##0.00`) |
| `hierarchyName` | string | Power BI hierarchy this property belongs to (G5) |
| `hierarchyLevel` | integer | Level order within the hierarchy (1 = top) (G5) |
| `degenerateDimension` | boolean | Keep this attribute on the fact table instead of a separate dimension (G1) |
| `olsRestricted` | boolean | Add column to the Object-Level Security `RestrictedColumns` role |
| `rolePlayingAs` | string | **RESERVED** (projector code path commented out) — role names for role-playing dimensions |

---

## 5. Identity & the `naturalKey` warning (FK-children)

`naturalKey` drives surrogate-key (`{class}_sk`) and IRI generation. A class **with
no `naturalKey`** produces NULL SK/IRI columns, so the dbt projector emits a warning.

For **FK-child** entities — a class targeted by `kairos-ext:silverForeignKeyOn` (its
FK column lands on the child's table pointing back to the parent) — the warning is
**context-aware**: it names the parent and explains the options.

```
Class 'Address' has no kairos-ext:naturalKey and is an FK-child of Party
(via kairos-ext:silverForeignKeyOn) — its surrogate key and IRI will be NULL.
If this is a weak entity, add a kairos-ext:naturalKey for its composite business
key (e.g. a type/discriminator column distinguishing rows under the same parent);
if it has its own source identity, add that key; if it is purely embedded,
consider denormalising it onto the parent table. Resolve via: kairos-design-silver
```

There is **no `identityStrategy` annotation** — it was evaluated in CR-3 and
**deferred** (DD-034). The improved warning (Option 4) is the current mechanism;
add the appropriate `naturalKey` to resolve it. See
`docs/archive/CR3-naturalKey-identity-strategy-2026-05-30.md`.

---

## 6. Import whitelisting (DD-021) & FK annotations (DD-022)

### Import whitelisting — imported classes are NOT projected by default

| Annotation | Level | Range | Purpose |
|---|---|---|---|
| `silverInclude` | class | boolean | Claim one imported class for silver projection |
| `silverIncludeImports` | ontology | boolean | Bulk-claim all first-level imported classes for silver (peer hub domains excluded) |
| `goldInclude` | class | boolean | Claim one imported class for gold projection |
| `goldIncludeImports` | ontology | boolean | Bulk-claim all first-level imported classes for gold |

### Foreign keys — declare FKs without OWL cardinality restrictions

| Annotation | Level | Range | Purpose |
|---|---|---|---|
| `silverForeignKey` | object property | boolean | Mark an object property as a FK column (equivalent to `owl:FunctionalProperty`, works on imported properties) |
| `silverForeignKeyOn` | object property | class | Override which class receives the FK column (must be the domain or range). When set to the range, the FK lands on the range table pointing back to the domain. Implies `silverForeignKey true` |

> See the **kairos-design-silver** skill §3e for using `silverForeignKey` /
> `silverForeignKeyOn` when a domain imports reference models whose object
> properties lack cardinality restrictions.

---

## 7. Caveat: two `incrementalColumn` annotations

| Annotation | Namespace | Status | Consumed by |
|---|---|---|---|
| `kairos-bronze:incrementalColumn` | `https://kairos.cnext.eu/bronze#` | **Live** | dbt projector — drives incremental silver loads |
| `kairos-ext:incrementalColumn` | `https://kairos.cnext.eu/ext#` | **RESERVED** | Read by the gold projector but not rendered |

They share a local name but are **different annotations on different resources**.
Use `kairos-bronze:incrementalColumn` on a bronze `SourceTable` to drive dbt
incremental materialization; do **not** expect `kairos-ext:incrementalColumn` to
affect gold output today. (A future rename of the gold one is tracked in DD-034.)

---

## 8. Reserved annotations summary

These are declared and documented but **not yet consumed** — safe to ignore:

- `kairos-ext:surrogateKeyStrategy` (silver, ontology-level)
- `kairos-ext:incrementalColumn` (gold, class-level)
- `kairos-ext:rolePlayingAs` (gold, property-level)

If you set them today, nothing changes in the generated output.
