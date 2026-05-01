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
2. **Ask the user which review mode** they want:

   | Mode | What it covers | When to use |
   |------|---------------|-------------|
   | **Quick** (default) | Level 1 (syntax) + Level 2 (SHACL) | Fast check after small edits |
   | **Detailed** | All 4 levels including modeling + extensions/mappings | Before PR, after major changes, or first-time review |

3. Run the CLI syntax check first:
   ```bash
   python -m kairos_ontology validate
   ```
   **Important**: Capture the full CLI output — it includes GDPR/PII scan
   results that feed into the Level 4 report.

4. For **Quick** mode: report Level 1 + 2 results and stop.
   For **Detailed** mode: continue through all 4 levels below.

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

> **Reference**: The full modeling rule set is defined in the
> **kairos-ontology-modeling** skill.  Invoke that skill for detailed
> guidance on class design, property design, naming conventions, and
> common patterns.  This level provides a **summary checklist** — do
> NOT duplicate the modeling skill's full content here.

Review every domain ontology `.ttl` file against this checklist.  These
are design rules — they won't cause parse errors but will lead to poor
projection output or downstream issues.

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

### Property type correctness

| Check | Rule |
|-------|------|
| ObjectProperty not declared as DatatypeProperty | 🐛 A property with `rdfs:range` pointing to an `owl:Class` MUST be `owl:ObjectProperty`, not `owl:DatatypeProperty` — mistyped properties generate wrong SQL types and missing FK joins |
| DatatypeProperty not declared as ObjectProperty | 🐛 A property with `rdfs:range` of `xsd:*` MUST be `owl:DatatypeProperty` — mistyped properties generate spurious FK lookups |
| Single-valued object properties have `owl:FunctionalProperty` | 💡 Without `owl:FunctionalProperty`, the projector may not generate FK columns — add it for 1:1 and N:1 relationships (e.g., `service:belongsToCategory`) |

### Naming conventions

| Check | Rule |
|-------|------|
| Classes use PascalCase | `Customer` ✅, `customer` ❌, `CUSTOMER` ❌ |
| Properties use camelCase | `customerName` ✅, `CustomerName` ❌, `customer_name` ❌ |
| No underscores in local names | OWL uses camelCase; snake_case is for SQL output |

### Controlled vocabulary consistency

| Check | Rule |
|-------|------|
| Enum classes use consistent modelling pattern | 💡 Pick ONE pattern and use it everywhere: either named individuals (`owl:NamedIndividual` members of a class) OR `kairos-ext:isReferenceData "true"` with a discriminator. Mixing patterns (some enums as individuals, others as string columns) causes inconsistent projection output |
| Reference data classes have `isReferenceData` annotation | 💡 If a class represents a controlled vocabulary/code list, annotate it in the silver extension |

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

### Target-URI cross-validation (critical)

This is the **highest-impact check** — missing target property URIs cause broken
dbt models that compile but produce wrong output.

| Check | What to verify | Severity |
|-------|---------------|----------|
| Target property URIs exist in domain ontology | Every `skos:exactMatch` target (the object of the mapping triple) must resolve to an existing `owl:DatatypeProperty` or `owl:ObjectProperty` in the domain ontology graph | 🐛 Non-existent target = column silently missing from generated SQL |
| Target class URIs exist in domain ontology | Every `skos:narrowMatch` / `skos:exactMatch` table-level target must resolve to an existing `owl:Class` | 🐛 Non-existent class = entire model generation fails silently |
| Target URIs use correct namespace | Target URIs must use the domain's namespace (e.g., `client:clientName`), not a typo'd or wrong namespace | 🐛 Wrong namespace = property treated as non-existent |

**How to check**: For each mapping file, load both the mapping graph and the
domain ontology graph. For every `skos:exactMatch` / `skos:narrowMatch` object URI,
verify it exists as a subject in the ontology with the expected `rdf:type`.

### Cross-domain analysis

These checks require analysing **all domains together**, not independently.

| Check | What to verify | Severity |
|-------|---------------|----------|
| Property name collisions across namespaces | If two domains define properties with the same local name (e.g., `client:status` and `invoice:status`), flag for review — may cause confusion in downstream SQL where snake_case names collide | 💡 Not always a bug, but worth flagging for explicit acknowledgement |
| Cross-domain FK targets are importable | If an `owl:ObjectProperty` range points to a class in another domain, that domain's ontology must be importable (present in `_master.ttl` or `owl:imports`) | 🐛 Broken cross-domain FK = NULL placeholder in dbt model |
| Cross-domain `skos:exactMatch` targets resolve | If a mapping targets a property in a different domain namespace, that property must exist in the other domain's ontology | 🐛 Same as target-URI issue but across domain boundaries |

### CLI output incorporation

Incorporate results from the `python -m kairos_ontology validate` CLI output
that was run in the "Before you start" step.

| Check | What to incorporate | Severity |
|-------|--------------------|----------|
| GDPR/PII warnings | If the CLI reports unprotected PII properties (names, emails, addresses, phone numbers), list them with count | 💡 Flag properties that should have `gdprSatelliteOf` protection or `olsRestricted` annotation |
| Projection warnings | If the CLI emits projection warnings (missing NK, unsupported FK, etc.), include them in the report | 🐛 Projection warnings indicate generation issues |

### Hub documentation completeness

| Check | What to verify | Severity |
|-------|---------------|----------|
| Hub README exists and has content | `README.md` at hub root should not be empty | 💡 Empty README = no project documentation |
| Domain model overview table populated | README should have a table listing all domains with name, description, and status | 💡 Empty table = discoverability problem |
| Every ontology file has a README row | Each `.ttl` in `model/ontologies/` (except `_master.ttl`) should appear in the domain table | 💡 Missing rows = undocumented domains |
| Section headings are consistent | TTL files with section-separator comments should use consistent patterns (e.g., `# --- Classes ---`) | 💡 Cosmetic but aids readability |

---

## Output format

After completing the applicable levels, produce a **structured review report**
for each domain.  Group findings by severity:

```
## Validation Report: <domain>

### ✅ Passed (N checks)
- Ontology declaration complete (label, version, https namespace)
- All 12 classes have rdfs:label and rdfs:comment
- Silver extension correctly references ontology URI
- 3 mapping files found for 3 source systems
- All split patterns have distinct filterCondition values
- All mapping target URIs resolve to existing properties

### 🐛 Issues (N findings) — must fix before projection
1. **Property `orderDate` missing `rdfs:range`** — projector cannot determine SQL type
   → Add `rdfs:range xsd:date`
2. **`IndividualClient` missing `conditionalOnType`** — split pattern will include all rows
   → Add `kairos-ext:conditionalOnType "2"`
3. **Mapping target `kyc:acceptedBy` does not exist** — property not declared in kyc.ttl
   → Either add the property to kyc.ttl or fix the URI in the mapping
4. **`belongsToCategory` is ObjectProperty but missing `owl:FunctionalProperty`**
   → Add `a owl:FunctionalProperty` to generate FK column

### 💡 Suggestions (N findings) — recommended improvements
1. **Class `AuditableEntity` has no `naturalKey`** — SK generation may produce duplicates
   → Add `kairos-ext:naturalKey "entityId"`
2. **Property name collision**: `client:status` and `order:status` both become `status` in SQL
   → Consider renaming to `clientStatus` / `orderStatus` for clarity
3. **26 properties flagged as PII** by CLI scan — consider GDPR satellite protection
   → Review `gdprSatelliteOf` and `olsRestricted` annotations
4. **README domain table is empty** — add rows for each domain
```

### Summary table

End with a summary:

```
| Level | Passed | Issues | Suggestions |
|-------|--------|--------|-------------|
| Syntax | ✅ | 0 | 0 |
| SHACL | ✅ | 0 | 0 |
| Modeling | ✅ | 2 | 1 |
| Extensions & Mappings | ⚠️ | 3 | 4 |
| **Total** | — | **5** | **5** |
```

---

## Remediation workflow

1. Fix all 🐛 **Issues** first — these will cause projection failures.
2. Address 💡 **Suggestions** for better output quality.
3. Re-run validation: `python -m kairos_ontology validate`
4. Run projection: `python -m kairos_ontology project --target all`
5. Inspect generated output to confirm annotations took effect.
