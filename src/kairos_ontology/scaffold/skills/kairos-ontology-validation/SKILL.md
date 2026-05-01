---
name: kairos-ontology-validation
description: >
  Comprehensive ontology review — syntax, SHACL, modeling best practices,
  and extension/mapping correctness. Produces a structured report with
  what's good, what's broken, and what can be improved.
---

# Ontology Validation & Review Skill

You help users validate and review their ontology hub for correctness,
completeness, and projection readiness.  Go beyond syntax checking — apply
the full set of modeling rules, extension annotation conventions, and
mapping best practices.

## Before you start

1. Identify the hub root (look for `model/ontologies/`, `model/extensions/`,
   `model/mappings/`).
2. Run the CLI syntax check first:
   ```bash
   python -m kairos_ontology validate
   ```
3. Then perform the 4-level review below on each domain.

---

## Level 1 — Syntax validation

Parse every `.ttl` file and report errors.

| Check | How |
|-------|-----|
| Turtle parse | `python -m kairos_ontology validate` or `rdflib.Graph().parse()` |
| Encoding | Files must be UTF-8 (no BOM) |
| Prefix consistency | Every prefix used in triples must be declared with `@prefix` |

### Common syntax errors

| Error | Cause | Fix |
|-------|-------|-----|
| "Bad syntax (expected directive)" | Missing `@prefix` or `@base` | Add missing prefix declaration |
| "Unresolved prefix" | Using prefix not declared | Add `@prefix ex: <...> .` |
| "Unexpected end of file" | Missing final `.` | Add period after last triple |
| "Invalid IRI" | Spaces or special chars in URI | URL-encode or fix the namespace |

---

## Level 2 — SHACL validation

If `model/shapes/` contains `.ttl` files, validate the domain ontologies
against those shapes.

| Check | What it catches |
|-------|----------------|
| `sh:minCount` | Missing required properties |
| `sh:datatype` | Wrong literal types |
| `sh:class` | Object property pointing at wrong class |
| `sh:pattern` | String format violations |

### SHACL shape patterns reference

```turtle
# Required property
:CustomerShape a sh:NodeShape ;
    sh:targetClass :Customer ;
    sh:property [
        sh:path :customerName ;
        sh:minCount 1 ;
        sh:datatype xsd:string ;
    ] .

# String constraint
sh:property [
    sh:path :customerEmail ;
    sh:minLength 5 ;
    sh:maxLength 254 ;
    sh:pattern "^[^@]+@[^@]+\\.[^@]+$" ;
] .

# Relationship cardinality
sh:property [
    sh:path :hasOrder ;
    sh:class :Order ;
    sh:minCount 0 ;
] .
```

---

## Level 3 — Modeling best practices

Review every domain ontology `.ttl` file against the Kairos modeling
conventions.  These are design rules — they won't cause parse errors but
will lead to poor projection output or downstream issues.

### Ontology declaration

| Check | Rule |
|-------|------|
| `owl:Ontology` declared | Every `.ttl` must have exactly one `owl:Ontology` resource |
| `rdfs:label` on ontology | Human-readable name is required |
| `owl:versionInfo` on ontology | Semantic version string required |
| Namespace uses `https://` | Never use `http://` — always `https://` |
| Namespace ends with `#` or `/` | Ensures fragment or path-based local names |

### Class design

| Check | Rule |
|-------|------|
| Every `owl:Class` has `rdfs:label` | 🐛 Missing label = unnamed table in projections |
| Every `owl:Class` has `rdfs:comment` | 💡 Missing comment = no description in schema YAML |
| Hierarchy depth ≤ 3 | 💡 Deeper hierarchies create complex split patterns |
| No circular `rdfs:subClassOf` | 🐛 Causes infinite loops in projector chain walking |
| One domain per `.ttl` file | 💡 Mixing domains makes projections unpredictable |

### Property design

| Check | Rule |
|-------|------|
| Every property has `rdfs:domain` | 🐛 Without domain, property won't appear in any table |
| Every property has `rdfs:range` | 🐛 Without range, projector can't determine SQL type |
| Every property has `rdfs:label` | 💡 Missing label = poor column descriptions |
| `owl:DatatypeProperty` range is `xsd:*` | 🐛 Non-XSD range causes type mapping failures |
| `owl:ObjectProperty` range is `owl:Class` | 🐛 Range must be a declared class for FK generation |
| No orphan properties (domain class not declared) | 🐛 Property domain references a non-existent class |

### Naming conventions

| Check | Rule |
|-------|------|
| Classes use PascalCase | `Customer` ✅, `customer` ❌, `CUSTOMER` ❌ |
| Properties use camelCase | `customerName` ✅, `CustomerName` ❌, `customer_name` ❌ |
| No underscores in local names | OWL uses camelCase; snake_case is for SQL output |

### Cross-domain references

| Check | Rule |
|-------|------|
| `owl:imports` for cross-domain references | If class A references class B from another domain, the ontology must import B's namespace |
| `_master.ttl` includes all domains | Every domain `.ttl` must be listed in `_master.ttl` via `owl:imports` |

---

## Level 4 — Extension & mapping review

Review `model/extensions/` and `model/mappings/` for projection readiness.
This is where most "it generated wrong output" bugs originate.

### Extension file structure

| Check | Rule | Severity |
|-------|------|----------|
| Silver extension exists | `model/extensions/<domain>-silver-ext.ttl` | 💡 Optional but recommended |
| Gold extension exists | `model/extensions/<domain>-gold-ext.ttl` | 💡 Optional but recommended |
| No mixed silver/gold in one file | Silver annotations in silver-ext only, gold in gold-ext only | 🐛 Causes confusing projections |
| Extension references correct ontology URI | Must annotate the same `owl:Ontology` URI as the domain | 🐛 Annotations silently ignored if URI mismatch |
| Extension imports domain namespace | `@prefix` matches the domain ontology namespace | 🐛 Annotations reference wrong resources |

### Silver extension annotations (`kairos-ext:`)

#### Ontology-level (on `owl:Ontology`)

| Check | What to verify |
|-------|---------------|
| `silverSchema` | Present and matches expected warehouse schema name |
| `namingConvention` | If set, must be `"camel-to-snake"` (only supported value) |
| `auditEnvelope` | Boolean string `"true"` / `"false"` — not `true` (unquoted) |
| `includeNaturalKeyColumn` | Boolean string — defaults to `"true"` |

#### Class-level

| Check | What to verify |
|-------|---------------|
| `naturalKey` set on non-reference classes | 🐛 Without NK, surrogate key generation may produce duplicates |
| `scdType` is `"1"` or `"2"` | 🐛 Other values are unsupported |
| `discriminatorColumn` + subclass `conditionalOnType` | If parent has discriminator, each subclass MUST have `conditionalOnType` |
| `isReferenceData` on enum/lookup classes | 💡 Ensures correct table materialization |
| `gdprSatelliteOf` points to valid class | 🐛 URI must match an existing `owl:Class` in the domain |
| `partitionBy` / `clusterBy` reference valid properties | 💡 Column name must exist in the class |
| `junctionTableName` on M:N object properties | 💡 Required for bridge table generation |

#### Property-level

| Check | What to verify |
|-------|---------------|
| `silverColumnName` is snake_case | 💡 Should match SQL naming convention |
| `silverDataType` is valid SQL type | 🐛 Must be a recognized Fabric Warehouse type |
| `nullable` is boolean string | 🐛 Use `"true"` / `"false"` |
| `derivationFormula` is valid SQL expression | 💡 Hard to validate statically — flag for manual review |

### Gold extension annotations (`kairos-ext:`)

#### Ontology-level

| Check | What to verify |
|-------|---------------|
| `goldSchema` present | 💡 Defaults to `gold_<domain>` if absent |
| `goldInheritanceStrategy` is valid | Must be `"class-per-table"` or `"single-table"` |
| `generateDateDimension` | Boolean string |
| `generateTimeIntelligence` | Boolean string |

#### Class-level

| Check | What to verify |
|-------|---------------|
| `goldTableType` is valid | Must be `"dimension"`, `"fact"`, or `"bridge"` |
| Fact tables have FK object properties | 🐛 Fact without FKs to dimensions = isolated table |
| `goldExclude` on utility/internal classes | 💡 Exclude base classes not meant for BI |
| `measureExpression` on properties of fact classes | 💡 Facts without measures have no aggregatable columns |
| `hierarchyName` + `hierarchyLevel` are paired | 🐛 One without the other is incomplete |
| `perspective` references consistent group name | 💡 Typos create orphan perspectives |

### Mapping file review (`kairos-map:`)

| Check | What to verify | Severity |
|-------|---------------|----------|
| Mapping file exists per source system | `model/mappings/<source>-to-<domain>.ttl` | 🐛 No mapping = no dbt models |
| File name follows convention | `<source-system>-to-<domain>.ttl` | 💡 Convention enables auto-discovery |
| `skos:exactMatch` or `skos:narrowMatch` on each table | Table-level SKOS mapping present | 🐛 Missing = source table ignored |
| `kairos-map:mappingType` declared | `"direct"`, `"split"`, or `"merge"` | 💡 Defaults to direct if absent |
| Split patterns: `filterCondition` on each subclass mapping | Each `skos:narrowMatch` to a subclass must have its own filter | 🐛 Missing filter = all rows go to all splits |
| Split patterns: filter values are distinct | No two subclasses share the same `filterCondition` value | 🐛 Duplicate filter = duplicate rows |
| Column mappings: `skos:exactMatch` per property | Each domain property has a source column mapping | 💡 Unmapped properties become NULL |
| Column `transform` expressions are valid SQL | `"CAST(source.id AS STRING)"` etc. | 💡 Hard to validate statically — flag for review |
| `defaultValue` is appropriate type | String default for string column, numeric for numeric | 💡 Type mismatch may cause runtime cast errors |
| `sourceColumns` count matches target NK | For composite FK joins, source column count must match | 🐛 Mismatch = incomplete join |
| Bronze vocabulary exists for referenced source | `integration/sources/<system>/<system>.vocabulary.ttl` | 🐛 Missing bronze = column lookups fail |
| Mapped column URIs match bronze vocabulary | Column URIs in mapping must exist in bronze `.ttl` | 🐛 Typo in URI = silently unmapped |

---

## Output format

After completing all 4 levels, produce a **structured review report** for each
domain.  Group findings by severity:

```
## Validation Report: <domain>

### ✅ Passed (N checks)
- Ontology declaration complete (label, version, https namespace)
- All 12 classes have rdfs:label and rdfs:comment
- Silver extension correctly references ontology URI
- 3 mapping files found for 3 source systems
- All split patterns have distinct filterCondition values

### 🐛 Issues (N findings) — must fix before projection
1. **Property `orderDate` missing `rdfs:range`** — projector cannot determine SQL type
   → Add `rdfs:range xsd:date`
2. **`IndividualClient` missing `conditionalOnType`** — split pattern will include all rows
   → Add `kairos-ext:conditionalOnType "2"`
3. **Mapping `erp-to-order.ttl` references bronze column `tblOrder_Status` not in vocabulary**
   → Check URI spelling in bronze vocabulary file

### 💡 Suggestions (N findings) — recommended improvements
1. **Class `AuditableEntity` has no `naturalKey`** — SK generation may produce duplicates
   → Add `kairos-ext:naturalKey "entityId"`
2. **Gold extension missing `measureExpression` on `fact_order`** — no aggregatable measures
   → Add DAX measure expressions for revenue, quantity
3. **3 properties missing `rdfs:comment`** — schema YAML will have empty descriptions
   → Add descriptive comments for downstream documentation
```

### Summary table

End with a summary:

```
| Level | Passed | Issues | Suggestions |
|-------|--------|--------|-------------|
| Syntax | ✅ | 0 | 0 |
| SHACL | ✅ | 0 | 0 |
| Modeling | ✅ | 1 | 3 |
| Extensions & Mappings | ⚠️ | 2 | 2 |
| **Total** | — | **3** | **5** |
```

---

## Remediation workflow

1. Fix all 🐛 **Issues** first — these will cause projection failures.
2. Address 💡 **Suggestions** for better output quality.
3. Re-run validation: `python -m kairos_ontology validate`
4. Run projection: `python -m kairos_ontology project --target all`
5. Inspect generated output to confirm annotations took effect.
