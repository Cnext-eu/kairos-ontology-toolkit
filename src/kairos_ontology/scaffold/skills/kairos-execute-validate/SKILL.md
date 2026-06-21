---
name: kairos-execute-validate
description: >
  Comprehensive ontology review — syntax, SHACL, modeling best practices,
  and extension/mapping correctness. Produces a structured report with
  what's good, what's broken, and what can be improved.
---

# Ontology Validation & Review Skill

## Lifecycle state (DD-080)

> The **kairos-flow** skill is the lifecycle orchestrator and the **only** writer of
> `ontology-hub/.kairos-state/status.md`. This skill plugs into that shared state; it
> does not maintain the global status file.

**On start (pre-flight):** read `ontology-hub/.kairos-state/` — the `status.md`
continuation region and the validate log at `phases/validate.md` — to resume open
questions. Ignore `_archive/`. (`kairos-ontology status` gives the objective view.)

**On pause or finish:** append a *State update proposal* to `phases/validate.md` with OKF
frontmatter (`type: kairos-phase-log`, `phase: validate`, `instance: hub`, `status:`,
`last_updated:`). Record decisions made and an **Open questions** list as the resume
anchor. Do **not** edit `status.md` directly — kairos-flow folds your proposal in.


> **🔒 Skill context:** Before running any `kairos-ontology` /
> `python -m kairos_ontology` command in this skill, set the sentinel env var so
> the CLI knows it runs inside a skill and suppresses its skill-gate warning:
> - PowerShell: `$env:KAIROS_SKILL_CONTEXT = "1"`
> - bash/zsh: `export KAIROS_SKILL_CONTEXT=1`

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

## Draft SHACL from source samples (`suggest-shapes`, DD-076)

Hand-writing shapes from scratch is tedious. `suggest-shapes` generates a
**DRAFT** SHACL file from bronze source profiling metadata (datatype, format
patterns, nullability, and `distinctCount`-backed enums) to give you a starting
point you then review and edit.

> **Skill context.** This command is skill-gated. Set the sentinel before
> running so the soft-gate stays quiet:
> - PowerShell: `$env:KAIROS_SKILL_CONTEXT = "1"`
> - bash/zsh: `export KAIROS_SKILL_CONTEXT=1`

```bash
kairos-ontology suggest-shapes --source integration/sources/crm/crm.vocabulary.ttl
```

| Option | Purpose |
|--------|---------|
| `--source` | Bronze vocabulary TTL (auto-detected if a single one exists) |
| `--out` | Output path (default `output/shapes-draft/<name>.ttl`) |
| `--enum-distinct-max` | Max distinct values to emit an `sh:in` enum (default 12) |
| `--no-sample-values` | Suppress masked example values in comments |
| `--force` | Overwrite an existing draft |

**What it emits (all advisory, `rdfs:comment`-annotated):**
- `sh:datatype` — always, from the logical type.
- `sh:pattern` — only when a single format pattern matches all samples.
- `sh:minCount 1` — only from `nullable:false` metadata.
- `sh:in (...)` — only when a reliable `distinctCount` ≤ `enum-distinct-max`
  fully matches the sampled distinct values, **and never for PII columns**.
- No sample-derived `sh:minInclusive`/`sh:maxInclusive` (5 rows are not a range).

**Important constraints:**
- Output goes to `output/shapes-draft/` — **outside** `model/shapes/` — and uses
  the `.ttl` suffix (not `.shacl.ttl`), so the validator does **not** load it
  automatically. You must review and move shapes into `model/shapes/` yourself.
- PII values are never enumerated into `sh:in` and are always masked in comments.
- The command refuses to overwrite an existing file unless `--force`.

**Workflow:** run `suggest-shapes` → open the draft → keep/edit the constraints
you trust → move the curated shape into `model/shapes/<name>.shacl.ttl` → re-run
Level 2 SHACL validation.

---

## Level 3 — Modeling best practices

> **Reference**: The full modeling rule set is defined in the
> **kairos-design-domain** skill.  Invoke that skill for detailed
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

### Reference model strategy consistency (DD-032)

| Check | Rule |
|-------|------|
| Enforced domains have `silverInclude` or `silverIncludeImports` | 🐛 If a domain uses `owl:imports` of external ref models (Enforced strategy), imported classes need explicit whitelisting via `silverInclude` / `silverIncludeImports` in the silver-ext file — otherwise imported classes are silently excluded from projection |
| Inspired domains have `rdfs:seeAlso` back-references | 💡 If a domain uses locally-adopted patterns from a reference model (Inspired strategy), classes should have `rdfs:seeAlso` pointing to the reference model URI for traceability |
| No mixed strategy for same reference model | 💡 A domain should not both `owl:imports` a ref model AND locally re-declare the same classes — pick one strategy per reference model |

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
| `naturalKey` set on non-reference classes | 🐛 Without NK, surrogate key (SK) and IRI generation will produce NULL placeholders. **The dbt projector now emits a warning** when a class with bronze mappings lacks `naturalKey`. |
| `scdType` is `"1"` or `"2"` | 🐛 Other values are unsupported |
| `discriminatorColumn` + subclass `conditionalOnType` | If parent has discriminator, each subclass MUST have `conditionalOnType` |
| `isReferenceData` on enum/lookup classes | 💡 Ensures correct table materialization |
| `gdprSatelliteOf` points to valid class | 🐛 URI must match an existing `owl:Class` in the domain |
| `partitionBy` / `clusterBy` reference valid properties | 💡 Column name must exist in the class |
| `junctionTableName` on M:N object properties | 💡 Required for bridge table generation |
| `silverForeignKey` points to valid object property | 🐛 Must be set on an `owl:ObjectProperty` — silently ignored on datatype properties (DD-022) |
| `silverForeignKeyOn` is domain or range of the property | 🐛 Must reference either the domain or range class of the annotated object property — other values are silently ignored (DD-022) |
| `inheritanceStrategy` has valid value | 🐛 Must be `"class-per-table"` or `"discriminator"` — invalid values silently fall back to default |
| `silverTableName` is snake_case | 💡 Should follow SQL naming convention |
| `silverSourceRef` references a plausible model name | 💡 Hard to validate statically — flag for review (DD-039) |
| `inlineRefThreshold` is positive integer | 💡 Ontology-level setting; non-integer values cause parse errors |
| `populationRequirement` has valid value | 🐛 Must be `"required"`, `"optional"`, `"derived"`, or `"unmapped"` — invalid values silently treated as optional |
| `derived` properties have `derivationFormula` | 🐛 A property with `populationRequirement "derived"` MUST have a `derivationFormula` — otherwise column is always NULL |
| `required` properties have source mapping | 🐛 A property with `populationRequirement "required"` should have a corresponding `skos:exactMatch` source mapping — missing mapping = required column is always NULL |

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
| `goldTableName` is snake_case (without dim_/fact_ prefix) | 💡 Prefix is auto-added by G2 — don't include it in the override |
| `goldColumnName` is snake_case | 💡 Should follow SQL naming convention |
| `goldDataType` is valid SQL type | 🐛 Must be a recognized Fabric Warehouse type (INT, DECIMAL, NVARCHAR, etc.) |
| `measureFormatString` is paired with `measureExpression` | 🐛 A format string without a measure expression is meaningless — flag if orphaned |
| `degenerateDimension` only on properties of fact classes | 💡 Only meaningful on properties whose owning class is a fact table — on dimension properties it has no effect |
| `olsRestricted` on sensitive columns | 💡 Verify property is on a fact or dimension class — OLS only applies to columns visible in the semantic model |
| RESERVED: `rolePlayingAs` used but not yet consumed | ⚠️ If set, warn that the gold projector does not yet render role-playing dimensions — annotation is declared but inactive |
| RESERVED: `incrementalColumn` used but not yet consumed | ⚠️ If set, warn that the gold projector does not yet render incremental refresh policies — annotation is declared but inactive |
| RESERVED: `surrogateKeyStrategy` used but not yet consumed | ⚠️ If set, warn that surrogate keys are currently generated unconditionally — annotation is declared but inactive |

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
| `deduplicationKey` references valid source column(s) | Space-separated column names for ROW_NUMBER dedup — columns must exist in the source table | 🐛 Invalid column names cause dbt compilation errors |
| `deduplicationOrder` is valid SQL ORDER BY expression | Expression for dedup window function ordering (e.g. `"modified_date DESC"`) | 🐛 Invalid expression causes dbt compilation errors |
| `deduplicationKey` and `deduplicationOrder` are paired | If one is set, the other should be too — dedup key without order produces non-deterministic results | 💡 Warn if only one is present |
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
| Cross-domain FK peer extension available | If a cross-domain FK references another domain, that domain's `*-silver-ext.ttl` must exist with a `naturalKey` on the target class — otherwise the FK join cannot resolve the target's surrogate key | 🐛 Missing peer ext = FK column generated but join produces NULL |
| Cross-domain `skos:exactMatch` targets resolve | If a mapping targets a property in a different domain namespace, that property must exist in the other domain's ontology | 🐛 Same as target-URI issue but across domain boundaries |

### Population coverage cross-check

These checks combine extension and mapping data to identify data quality risks.

| Check | What to verify | Severity |
|-------|---------------|----------|
| `required` properties have source mappings | For every property with `populationRequirement "required"`, verify at least one source mapping exists (`skos:exactMatch` target) | 🐛 Required column always NULL = data quality blocker |
| `derived` properties have formulas | For every property with `populationRequirement "derived"`, verify `derivationFormula` is set | 🐛 Derived column without formula = always NULL |
| High NULL-column ratio per entity | If > 50% of an entity's properties have no source mapping and no derivation formula, flag the entity | 💡 May indicate incomplete mapping or over-modeled entity |

### DD-023 shared defaults validation

| Check | What to verify | Severity |
|-------|---------------|----------|
| Default extension files parse successfully | If `*-silver-defaults.ttl` or `*-gold-defaults.ttl` exist in a reference model, verify they parse | 🐛 Syntax errors in defaults silently break projection |
| No conflicting annotations between defaults and hub ext | If a hub extension and a ref-model default both annotate the same class/property, the hub extension wins — flag the overlap for awareness | 💡 Unintentional overlap may indicate stale defaults |

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

## Report persistence (MANDATORY)

After displaying the validation report in chat, **always** save it as a Markdown file:

- **Path:** `output/reports/validation-{YYYY-MM-DD-HHmmss}.md` (relative to the hub root).
  Use the current UTC timestamp for `{YYYY-MM-DD-HHmmss}` (e.g. `validation-2026-06-10-205500.md`).
- **Content:** The full rendered report (all levels + summary table) exactly as
  displayed in chat.
- **History:** Each run creates a new file — previous reports are preserved for
  comparison and audit trail.
- **Git:** Do NOT commit the file automatically. The user decides when to commit.

**Steps:**
1. After assembling the full report, write it to `output/reports/validation-{ts}.md`
   using the `create` or `edit` tool.
2. Tell the user: "📄 Report saved to `output/reports/validation-{ts}.md`."

---

## Remediation workflow

1. Fix all 🐛 **Issues** first — these will cause projection failures.
2. Address 💡 **Suggestions** for better output quality.
3. Re-run validation: `python -m kairos_ontology validate`
4. Run projection: `python -m kairos_ontology project --target all`
5. Inspect generated output to confirm annotations took effect.

---

## Related skills

| When you need | Invoke |
|---|---|
| Design/modify domain ontology classes and properties | **kairos-design-domain** |
| Design silver layer (DDL, SCD, FK annotations) | **kairos-design-silver** |
| Run projections (generate artifacts after validation) | **kairos-execute-project** |
| Map source columns to domain properties | **kairos-design-mapping** |
| Check hub status and completeness | **kairos-diagnose-status** |
