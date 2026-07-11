# Kairos Ontology Toolkit — Improvement Specification

> **Purpose:** This document is intended as input for an LLM tasked with improving the Kairos Ontology Toolkit (currently v2.16.0). The findings below are derived from a real-world deployment but are written to be **project-agnostic** — they describe gaps in the toolkit's capabilities, not in any specific consumer project.
>
> **Scope:** The toolkit's dbt projection engine, which generates staging, silver, and gold dbt models from a bronze vocabulary, ontology definitions, and mapping files.

---

## Executive Summary: The Three-Layer Solution

The findings in this document fall into three categories that map to three layers of metadata. Each layer solves a different class of problem, and **all three are needed** to achieve a fully functional generated output.

| Layer | Purpose | Solves |
|---|---|---|
| **Ontology tags + enforced layer contracts** | What must be populated, what's derived, what's optional; staging consumes only from source; silver consumes only from staging | The "wiring" problem (Findings 1, 8, 9, 12, 16) |
| **Vocabulary annotations** | What physically exists in bronze and how it's stored | The "what's actually there" problem (Findings 2, 3, 5, 6, 7) |
| **Platform configuration** | How to express SQL for the target engine | The "make it run" problem (Finding 4) |

The **highest-ROI single change** is enforcing layer contracts and tagging ontology properties — this fixes the architectural disconnect that currently blocks 100% of silver models from running. However, this change alone does not produce a fully working output. Without the vocabulary and platform layers, the generated SQL still fails at runtime due to physical storage mismatches and dialect incompatibilities.

The recommended phased approach is at the end of this document.

---

## Toolkit Architecture (As Observed)

The toolkit pipeline is:

```
1. Source documentation (README, API specs)
        ↓
2. Bronze vocabulary TTL          (integration/sources/<system>/<system>.vocabulary.ttl)
   — describes source tables and columns
        ↓
3. Domain ontologies TTL          (model/ontologies/<domain>.ttl)
   — defines classes and properties per business domain
        ↓
4. Mapping files TTL              (model/mappings/<system>-to-<domain>.ttl)
   — SKOS mappings from source columns to ontology properties,
     with filter conditions, transformations, deduplication
        ↓
5. Layer extension files TTL      (model/extensions/<domain>-silver-ext.ttl, *-gold-ext.ttl)
   — layer-specific annotations (SCD type, surrogate keys, GDPR satellites)
        ↓
6. Projection engine (toolkit core)
        ↓
7. Generated dbt models           (output/medallion/dbt/models/{staging,silver,gold}/)
```

Each step has known gaps, documented below in priority order.

---

## CRITICAL FINDINGS (P0 — Toolkit Output Does Not Run)

### Finding 1: Disconnect Between Generated Staging and Silver Layers

**Severity:** Critical (Blocks Everything)
**Affected:** 100% of generated silver models

#### Problem

The projection engine generates staging models named after **source systems and tables**:
- `stg_<source_system>__<source_table>` (e.g., `stg_<source>__<table>`)

But generates silver models that reference staging models named after **ontology domains and entities**:
- `{{ ref('stg_<ontology_domain>__<ontology_entity>') }}` (e.g., `stg_<domain>__<entity>`)

The `stg_<domain>__<entity>` staging models are **never generated**. There is no bridge between source-aligned staging and domain-aligned silver. Every silver model references a non-existent staging table.

#### Evidence in Generated Output

```sql
-- output/medallion/dbt/models/silver/<domain>/<entity>.sql (toolkit-generated)
{{ config(materialized='table', schema='silver_<domain>', enabled=false) }}

with stg_<domain>__<entity> as (
    select * from {{ ref('stg_<domain>__<entity>') }}   -- ❌ DOES NOT EXIST
)

select
    CAST(NULL AS NVARCHAR(255)) as <entity>_sk,
    CAST(NULL AS NVARCHAR(255)) as <entity>_iri
from stg_<domain>__<entity>
```

The body is also empty — only NULL placeholders. No transformation logic from the mapping TTL is applied.

#### Self-Awareness in Toolkit Output

Many generated silver models include `enabled=false`, suggesting the projector knows the output is non-functional but has no resolution strategy.

#### Mapping Information Already Exists But Is Not Used

The mapping TTL files contain everything needed to generate functional silver models:

```turtle
# Filter conditions for entity discrimination
<bronze>:<table> skos:narrowMatch <domain>:<subclass> ;
    kairos-map:filterCondition "source.<discriminator> = <value>" .

# Column transformations
<bronze>:<table>_<column> skos:exactMatch <domain>:<property> ;
    kairos-map:transform "<sql_expression>" .

# Multi-column derived values
<bronze>:<table>_<column> skos:closeMatch <domain>:<property> ;
    kairos-map:transform "CASE WHEN ... END" ;
    kairos-map:sourceColumns "<col1> <col2>" .
```

The projector reads these but does not apply them in silver generation.

#### Required Toolkit Change: Enforce Layer Contracts

The projector must enforce layer dependency rules:
- **Staging models** may consume **only from source** (`{{ source(...) }}`)
- **Silver models** may consume **only from staging** (`{{ ref('stg_...') }}`)
- **Gold models** may consume **only from silver** (`{{ ref('silver_...') }}`)

If a silver model needs `stg_<domain>__<entity>`, that staging model must also be generated. The projector should fail at generation time if any reference is unresolvable, rather than producing non-functional models with `enabled=false`.

Recommended implementation:

**Option A: Generate domain-aligned intermediate staging layer**
For each ontology entity, generate `stg_<domain>__<entity>` that:
- Reads from `stg_<source_system>__<source_table>` (the existing source-aligned staging)
- Applies `kairos-map:filterCondition` from the mapping TTL as WHERE clauses
- Applies `kairos-map:transform` from the mapping TTL as SELECT expressions
- Renames source columns to ontology property names
- Silver models then become trivial `SELECT * FROM stg_<domain>__<entity>` + audit columns

**Option B: Generate silver models that reference source staging directly**
Inline the mapping logic into silver SELECT statements, referencing `stg_<source_system>__<source_table>`. Simpler but less DRY when multiple silver models share the same source.

**Option C: Multi-source UNION when applicable**
When an ontology entity is sourced from multiple systems, generate UNIONs across staging models with consistent column aliases.

Combined with Finding 8 (tagging ontology properties as required/optional), this allows the projector to validate end-to-end: every required ontology property must have a traceable path from a source column through staging into silver.

---

### Finding 2: Bronze Vocabulary Assumes Normalized Tables That Don't Exist Physically

**Severity:** Critical (Blocks Staging Generation)
**Affected:** Any source with denormalized or document-store data

#### Problem

The vocabulary describes each `kairos-bronze:SourceTable` as a standalone physical table. The projector generates one `{{ source() }}` reference per SourceTable. But many source systems (especially APIs ingested into data lakes/warehouses) deliver:
- **Denormalized tables** — child entities flattened as inline columns in a parent table
- **JSON-nested structures** — child collections stored as JSON arrays/objects within a column
- **Wide tables** — hundreds of columns in a single table

When the vocabulary defines child entities as separate SourceTables but the bronze layer stores them inline or as JSON, the generated SQL fails with "table not found" errors.

> **Note:** This is a vocabulary-layer concern that ontology tagging cannot solve. Even with perfectly tagged ontology properties and enforced layer contracts (Finding 1), the projector still needs to know how to physically extract data from the bronze layer.

#### Required Vocabulary Extension

Introduce a `physicalStorage` annotation distinguishing how data is physically stored:

```turtle
# Physical separate table (default, current behavior)
<bronze>:<entity> a kairos-bronze:SourceTable ;
    kairos-bronze:physicalStorage "table" ;
    kairos-bronze:tableName "<table_name>" .

# Inline columns within a parent table (denormalized)
<bronze>:<child_entity> a kairos-bronze:SourceTable ;
    kairos-bronze:physicalStorage "inline" ;
    kairos-bronze:parentTable <bronze>:<parent_entity> ;
    kairos-bronze:columnPrefix "<prefix>" .
    # Columns identified by prefix (e.g., "address" matches addressStreet, addressCity)
    # OR explicit column list:
    # kairos-bronze:inlineColumns "<col1> <col2> <col3>" .

# JSON array within a column
<bronze>:<child_entity> a kairos-bronze:SourceTable ;
    kairos-bronze:physicalStorage "json-array" ;
    kairos-bronze:parentTable <bronze>:<parent_entity> ;
    kairos-bronze:sourceColumns "<json_column1> <json_column2>" ;
    kairos-bronze:jsonPath "$" ;
    kairos-bronze:jsonSchema <bronze>:<schema_definition> .

# JSON object with nested array
<bronze>:<child_entity> a kairos-bronze:SourceTable ;
    kairos-bronze:physicalStorage "json-object" ;
    kairos-bronze:parentTable <bronze>:<parent_entity> ;
    kairos-bronze:sourceColumns "<json_column>" ;
    kairos-bronze:jsonPath "$.<nested_path>" ;
    kairos-bronze:jsonSchema <bronze>:<schema_definition> .
```

#### Required Projection Logic

The projector must generate different SQL patterns per `physicalStorage`:

| Storage Type | Generated Pattern (T-SQL) |
|---|---|
| `table` | `SELECT ... FROM {{ source(parent, table) }}` |
| `inline` | `SELECT prefixed_columns FROM {{ source(parent, parent_table) }} WHERE relevant_columns IS NOT NULL` |
| `json-array` | `SELECT ... FROM {{ source() }} CROSS APPLY OPENJSON(json_col) WITH (...)` |
| `json-object` | `SELECT ... FROM {{ source() }} CROSS APPLY OPENJSON(json_col, '$.path') WITH (...)` |

Equivalent patterns for other dialects (Snowflake `LATERAL FLATTEN`, BigQuery `UNNEST`, Databricks `EXPLODE` + `FROM_JSON`).

---

### Finding 3: JSON Column Schemas Are Not Describable in the Vocabulary

**Severity:** Critical (Blocks JSON Extraction)
**Affected:** Any source with JSON columns

#### Problem

The current vocabulary spec has no concept of "JSON-typed column" or "schema for JSON content". A column containing JSON is just `kairos-bronze:dataType "nvarchar(max)"` with no further information about the JSON structure inside.

The projector cannot generate JSON extraction SQL without knowing:
1. Which columns contain JSON
2. Whether the JSON is an object or an array
3. What fields exist within JSON elements
4. The data type of each JSON field
5. The JSON path to navigate to the data

> **Note:** This is also a vocabulary-layer concern. Ontology tagging cannot describe the physical JSON structure of source data.

#### Required Vocabulary Extension

```turtle
# Mark a column as JSON-typed
<bronze>:<table>_<column> a kairos-bronze:SourceColumn ;
    kairos-bronze:dataType "nvarchar(max)" ;
    kairos-bronze:contentType "json-array" ;       # or "json-object"
    kairos-bronze:jsonSchema <bronze>:<schema_id> ;
    kairos-bronze:jsonPath "$" .                    # navigation path

# Define a reusable JSON schema
<bronze>:<schema_id> a kairos-bronze:JsonSchema ;
    kairos-bronze:jsonField [
        kairos-bronze:fieldName "<field_name>" ;
        kairos-bronze:fieldType "<sql_type>" ;
        kairos-bronze:jsonPath "$.<path>" ;
        kairos-bronze:nullable "true"^^xsd:boolean
    ] ,
    [
        kairos-bronze:fieldName "<nested_field>" ;
        kairos-bronze:fieldType "<sql_type>" ;
        kairos-bronze:jsonPath "$.<parent>.<child>"
    ] .
```

#### JSON Extraction Safety Rule

**JSON type definitions must always extract values as VARCHAR/STRING**, not as the target numeric/date/boolean type. Numeric and date casting should happen in a downstream layer using `TRY_CAST` (T-SQL/Snowflake), `SAFE_CAST` (BigQuery), or equivalent.

Reason: dirty JSON data (non-numeric strings in numeric fields, malformed dates) causes the entire extraction to fail with cryptic errors. Extracting as VARCHAR + safe-casting later isolates the failure to individual rows.

The projector should generate:

```sql
-- Generated staging (extraction as VARCHAR)
CROSS APPLY OPENJSON(<json_col>) WITH (
    <field> varchar(<length>) '$.<path>',
    <numeric_field> varchar(50) '$.<path>',   -- VARCHAR even for numeric fields
    <date_field> varchar(50) '$.<path>'       -- VARCHAR even for date fields
) j

-- Generated silver (safe casting)
TRY_CAST(<numeric_field> AS DECIMAL(18,4)) AS <numeric_field>,
TRY_CAST(<date_field> AS DATETIME2) AS <date_field>
```

Additionally, JSON validation guards should wrap extractions:

```sql
WHERE <json_col> IS NOT NULL
  AND LEN(<json_col>) > 2
  AND ISJSON(<json_col>) = 1   -- T-SQL specific; equivalent per dialect
```

---

### Finding 4: Target Platform Dialect Is Not Configurable

**Severity:** Critical (Blocks Deployment to Specific Platforms)
**Affected:** Any platform where SQL types differ from defaults

#### Problem

Generated SQL uses hardcoded type names like `NVARCHAR(255)`, `STRING`, `BOOLEAN`. These are not portable:

| Generic Type | T-SQL (Standard) | Microsoft Fabric | Snowflake | BigQuery | Databricks |
|---|---|---|---|---|---|
| String | NVARCHAR | VARCHAR (NVARCHAR not supported) | VARCHAR | STRING | STRING |
| Boolean | BIT | BIT | BOOLEAN | BOOL | BOOLEAN |
| Identifier | UNIQUEIDENTIFIER | VARCHAR(36) | VARCHAR | STRING | STRING |
| Large text | NVARCHAR(MAX) | VARCHAR(8000) | VARIANT | STRING | STRING |
| Timestamp | DATETIME2 | DATETIME2 | TIMESTAMP_NTZ | TIMESTAMP | TIMESTAMP |

The error messages when this fails are particularly hard to diagnose because invalid types in upstream views propagate to downstream tables, making the downstream table appear broken when the actual issue is upstream.

> **Note:** This is a platform-layer concern, completely independent of ontology and vocabulary. No amount of metadata tagging can substitute for a target dialect configuration.

#### Required Vocabulary/Config Extension

Introduce a platform definition with type mapping and dialect functions:

```turtle
<bronze>:<source_system> a kairos-bronze:SourceSystem ;
    kairos-bronze:targetPlatform <kairos-platform>:<platform_id> .

<kairos-platform>:<platform_id> a kairos-bronze:TargetPlatform ;
    kairos-bronze:typeMapping [
        kairos-bronze:genericType "string" ;
        kairos-bronze:platformType "<platform_string_type>"
    ] , [
        kairos-bronze:genericType "boolean" ;
        kairos-bronze:platformType "<platform_bool_type>"
    ] , [
        kairos-bronze:genericType "uuid" ;
        kairos-bronze:platformType "<platform_uuid_type>"
    ] ;
    kairos-bronze:jsonExtractionFunction "<platform_function>" ;
    kairos-bronze:jsonExtractionPattern "<platform_pattern>" ;
    kairos-bronze:safeCastFunction "<platform_safe_cast>" ;
    kairos-bronze:jsonValidationFunction "<platform_json_validator>" ;
    kairos-bronze:stringLengthLimit <integer> ;
    kairos-bronze:supportsNvarchar "<true|false>"^^xsd:boolean .
```

#### Standard Platform Profiles to Ship

The toolkit should bundle pre-defined platform profiles:

| Profile | String type | JSON extraction | Safe cast | JSON validation |
|---|---|---|---|---|
| `microsoft-fabric` | VARCHAR only | OPENJSON + CROSS APPLY | TRY_CAST | ISJSON |
| `azure-synapse` | NVARCHAR supported | OPENJSON + CROSS APPLY | TRY_CAST | ISJSON |
| `sql-server` | NVARCHAR supported | OPENJSON + CROSS APPLY | TRY_CAST | ISJSON |
| `snowflake` | VARCHAR | LATERAL FLATTEN + PARSE_JSON | TRY_CAST | IS_VALID_JSON |
| `databricks` | STRING | EXPLODE + FROM_JSON | TRY_CAST | schema-of-json |
| `bigquery` | STRING | JSON_EXTRACT_ARRAY + UNNEST | SAFE_CAST | JSON_QUERY |
| `postgres` | TEXT | jsonb_array_elements | NULLIF + CAST | jsonb_typeof |

---

## HIGH-PRIORITY FINDINGS (P1 — Limits Output Quality)

### Finding 5: Vocabularies Built From API Documentation Are Out-of-Sync With Bronze Reality

**Severity:** High (Causes Incorrect Type Assumptions)
**Affected:** Any source where bronze ingestion transforms types

#### Problem

The current process relies on humans reading API documentation (`api-data-model.md`) and writing the vocabulary TTL by hand. The vocabulary then describes the **logical API model**, not the **physical bronze table**.

In typical data ingestion pipelines:
- API delivers JSON with typed values (`{"type": 0, "isActive": true}`)
- Ingestion lands data in bronze where everything becomes VARCHAR/STRING
- Nested JSON often gets flattened or stored as JSON strings
- Field names may be mangled (camelCase → snake_case, prefixes added)
- Some columns are added (`_load_date`, `_source_file`, `_batch_id`)

The vocabulary describes what the API spec says, but the projector generates SQL against the bronze table — they don't match.

#### Required Process Change

The `integration/sources/<system>/` folder structure should mandate sample data:

```
integration/sources/<system>/
├── README.md
├── api-data-model.md                       # API/source documentation
├── <system>.vocabulary.ttl                 # Bronze vocabulary
└── sample-data/                            # ⬅ NEW: required
    ├── <bronze_table_1>.sample.json       # 3-10 actual rows from bronze
    ├── <bronze_table_2>.sample.json
    └── README.md                          # How sample was extracted
```

#### What Sample Data Provides

1. **Validates vocabulary completeness** — every column in the sample must appear in the vocabulary
2. **Detects vocabulary excess** — columns in the vocabulary not in samples are suspect
3. **Reveals physical types** — exposes when everything is VARCHAR despite spec saying INT/BOOL
4. **Exposes denormalization** — JSON strings in columns, inline child entity fields
5. **Documents enum values** — real examples of values used (e.g., `"type": "0"` not `"type": 0`)
6. **Catches missing columns** — columns in bronze but absent from vocabulary

#### Toolkit Validator (New Component)

A new toolkit component should validate the vocabulary against samples:

```
$ kairos-toolkit validate-vocabulary integration/sources/<system>/
✓ Vocabulary defines table 'X' (matches sample)
✓ Column 'Y' type matches sample (varchar)
✗ Column 'Z' declared as int but sample shows varchar values
✗ Sample contains column 'W' not declared in vocabulary
⚠ Vocabulary defines table 'V' but no sample provided
```

---

### Finding 6: Source Discriminators Not Modeled in Vocabulary

**Severity:** High (Causes Incorrect Entity Splitting)
**Affected:** Any source using type discriminator columns

#### Problem

Many sources use a single table for multiple entity types, distinguished by a discriminator column (e.g., `type` enum, `entity_type` string, `kind` field). The mapping TTL captures this with `kairos-map:filterCondition`, but:

1. The vocabulary doesn't formally identify which column is the discriminator
2. Different mappings can use ambiguous filter logic (e.g., `is_person` boolean that doesn't perfectly correlate with `type` enum)
3. Documentation of valid discriminator values is in API docs, not in the vocabulary

The result: silver models may use approximate filtering logic that doesn't perfectly match the source semantics.

#### Required Vocabulary Extension

```turtle
<bronze>:<table> a kairos-bronze:SourceTable ;
    kairos-bronze:discriminatorColumn <bronze>:<table>_<column> ;
    kairos-bronze:discriminatorValues [
        kairos-bronze:value <value1> ;
        kairos-bronze:label "<entity_type_1>" ;
        kairos-bronze:description "<semantic_meaning>"
    ] , [
        kairos-bronze:value <value2> ;
        kairos-bronze:label "<entity_type_2>"
    ] .
```

The mapping TTL can then reference discriminator labels semantically rather than encoding numeric values:

```turtle
<bronze>:<table> skos:narrowMatch <domain>:<subclass> ;
    kairos-map:filterByDiscriminator "<entity_type_1>" .   # human-readable
```

The projector resolves this back to the correct numeric/string filter at generation time.

---

### Finding 7: Enum Values Not Modeled in Vocabulary

**Severity:** High (Forces Manual Enum Mapping)
**Affected:** Any source with coded enum columns

#### Problem

Many source columns store enum codes (numeric or short string) that need to be resolved to human-readable labels. The vocabulary has no concept of enums. The mapping layer occasionally references specific values in filter conditions, but there is no centralized enum definition.

Result: silver/gold models output raw codes, requiring downstream consumers to maintain their own lookup tables. Or developers manually write large CASE statements (e.g., a 51-value CASE statement for a single column).

#### Required Vocabulary Extension

```turtle
<bronze>:<table>_<column> a kairos-bronze:SourceColumn ;
    kairos-bronze:dataType "<type>" ;
    kairos-bronze:enumValues [
        kairos-bronze:value <code> ;
        kairos-bronze:label "<readable_name>" ;
        kairos-bronze:description "<optional_description>"
    ] , [
        kairos-bronze:value <code2> ;
        kairos-bronze:label "<readable_name_2>"
    ] .
```

Or, for reusable enums shared across columns:

```turtle
# Define enum once
<bronze>:<enum_id> a kairos-bronze:Enumeration ;
    kairos-bronze:enumValue [
        kairos-bronze:code <code1> ; kairos-bronze:label "<label1>"
    ] , [
        kairos-bronze:code <code2> ; kairos-bronze:label "<label2>"
    ] .

# Reference from columns
<bronze>:<table>_<column> a kairos-bronze:SourceColumn ;
    kairos-bronze:dataType "<type>" ;
    kairos-bronze:enumeration <bronze>:<enum_id> .
```

#### Required Generation Behavior

The projector should generate, for every enum-typed column, either:

**Option A: Inline CASE statements in silver layer**
```sql
CASE CAST(<column> AS <type>)
    WHEN <code1> THEN '<label1>'
    WHEN <code2> THEN '<label2>'
    ELSE 'Unknown (' + CAST(<column> AS VARCHAR) + ')'
END AS <column>_label
```

**Option B: Separate dbt seed files**
```
output/medallion/dbt/seeds/<system>/<column>_lookup.csv
```
Plus JOIN-based resolution in silver models.

Option B is cleaner but requires source mapping; Option A is simpler. Best: configurable per enum.

---

### Finding 8: Ontology Properties Not Tagged with Population Requirements

**Severity:** High (Allows Silent Coverage Gaps)
**Affected:** All ontology properties

#### Problem

The ontology defines classes with their properties but does not annotate which properties are:
- **Required** — must be populated; failure to map is an error
- **Optional** — may be NULL; failure to map is acceptable
- **Derived** — computed from other properties; no source mapping needed
- **Unmapped** — known to have no current source; explicitly deferred

Without these tags, the projector cannot distinguish between "this property is intentionally NULL" and "this property is accidentally NULL because the mapping is missing". The toolkit silently produces output with hundreds of NULL columns and no signal that anything is wrong.

Combined with incomplete vocabulary coverage (Finding 5), this means columns that exist in the bronze table get marked NULL in silver because no one noticed they could be mapped.

#### Required Ontology Extension

```turtle
<domain>:<class> a owl:Class .

<domain>:<property> a owl:DatatypeProperty ;
    rdfs:domain <domain>:<class> ;
    rdfs:range xsd:string ;
    kairos-ont:populationRequirement "required" ;       # required | optional | derived | unmapped
    kairos-ont:semanticDescription "<what this property represents>" ;
    kairos-ont:derivationFormula "<expression for derived properties>" .
```

#### Required Validation

The projector should validate at generation time that every `required` property in every ontology class has at least one source-to-property mapping in the mapping TTL files. If not, fail loudly:

```
$ kairos-toolkit project
✗ Class <domain>:<class> requires property <property> but no mapping exists
✗ Class <domain>:<class2> requires property <property2>; mapping references column <column>
  but vocabulary has no such column
⚠ Class <domain>:<class> property <property3> tagged as derived but no derivationFormula provided
✓ Class <domain>:<class4> all required properties have mappings
```

This combined with Finding 1 (enforced layer contracts) creates an end-to-end traceability check: every required ontology property must be reachable from a source column through staging into silver. Broken chains are detected at projection time, not at runtime.

---

### Finding 9: No Coverage Reports for Mapping Completeness

**Severity:** Medium (Becomes High When Combined With Finding 8)

**Problem:** No way to see which ontology properties are populated vs. NULL across silver models, or which staging columns are used vs. ignored.

**Required Output:** The projector should generate a coverage report alongside dbt models:

```json
// output/coverage-report.json
{
    "<domain>": {
        "<entity>": {
            "ontology_properties_total": 15,
            "ontology_properties_required": 8,
            "ontology_properties_optional": 5,
            "ontology_properties_derived": 2,
            "populated_from_source": 7,
            "always_null": 8,
            "null_columns": ["<col1>", "<col2>"],
            "missing_required_mappings": ["<col_x>"],
            "source_coverage": {
                "<source_system>__<source_table>": {
                    "available_columns": 40,
                    "consumed_columns": 12,
                    "unused_columns": ["<col_a>", "<col_b>"]
                }
            }
        }
    }
}
```

This makes data gaps visible and actionable. When Finding 8 is implemented (required/optional tagging), this report becomes the primary tool for ontology-vocabulary-mapping completeness tracking.

---

## MEDIUM-PRIORITY FINDINGS (P2 — Limits Reusability and Maintainability)

### Finding 10: Multi-Valued Attributes Have No Unpivoting Pattern

**Severity:** Medium
**Problem:** Sources commonly store multi-valued attributes as parallel columns (e.g., `phone1`/`phone2`, `email_personal`/`email_work`, `address_billing`/`address_shipping`). The vocabulary treats each as a separate column. Generated silver/gold models inherit this wide structure instead of unpivoting to normalized rows.

**Required Vocabulary Extension:**

```turtle
<bronze>:<table>_<column1> a kairos-bronze:SourceColumn ;
    kairos-bronze:multiValuedAttribute <bronze>:<attribute_group> ;
    kairos-bronze:multiValuedDiscriminator "<value1>" .

<bronze>:<table>_<column2> a kairos-bronze:SourceColumn ;
    kairos-bronze:multiValuedAttribute <bronze>:<attribute_group> ;
    kairos-bronze:multiValuedDiscriminator "<value2>" .

<bronze>:<attribute_group> a kairos-bronze:MultiValuedAttribute ;
    kairos-bronze:targetEntity <domain>:<entity> ;
    kairos-bronze:discriminatorColumn "<discriminator_column_name>" ;
    kairos-bronze:valueColumn "<value_column_name>" .
```

**Required Generation:** UNPIVOT/UNION ALL pattern producing one row per (parent, attribute_type, value).

---

### Finding 11: Deduplication Strategy Not Distinguished by Table Type

**Severity:** Medium
**Problem:** All silver models use the same generation pattern, but dimension-style entities (lookup tables for software, departments, categories) need `SELECT DISTINCT`, while fact-style entities don't.

**Required Ontology/Extension Annotation:**

```turtle
<domain>:<entity> a owl:Class ;
    kairos-ext:tableType "dimension" ;       # or "fact" or "satellite"
    kairos-ext:naturalKey "<column_name>" .
```

**Required Generation:** Dimension entities get `SELECT DISTINCT` or `GROUP BY <natural_key>`; fact entities do not.

---

### Finding 12: Derived Columns and Computed Values Not Modeled

**Severity:** Medium
**Problem:** Some ontology properties cannot be 1:1 mapped from source columns — they require computation:
- `is_active` derived from `end_date IS NULL`
- `domain_name` derived from `SUBSTRING(email, CHARINDEX('@', email) + 1, ...)`
- `latest_fiscal_year_end` derived from `MAX(end_date)` aggregated per parent

Currently, the mapping TTL supports `kairos-map:transform` for column-level expressions, but not for:
- Aggregations (`MAX`, `MIN`, `SUM` per group)
- Cross-row derivations
- Pattern-based extractions (string parsing, regex)

**Required Mapping Extension:**

```turtle
<bronze>:<column> skos:closeMatch <domain>:<property> ;
    kairos-map:derivationType "aggregation" ;
    kairos-map:aggregationFunction "MAX" ;
    kairos-map:groupByColumns "<col1> <col2>" ;
    kairos-map:transform "<sql_expression>" .
```

---

### Finding 13: GDPR Satellites and Sensitive Data Not Auto-Isolated

**Severity:** Medium
**Problem:** The extension TTL files mention `kairos-ext:gdprSatelliteOf` for sensitive entities (email, phone), but the projector doesn't generate separate satellite tables, masking patterns, or access controls.

**Required Generation:**
- Sensitive columns moved to satellite tables joined via surrogate key
- Configurable masking expressions (`SHA2_256(<column>)`, `LEFT(<column>, 3) + '***'`)
- Generation of dbt grants/permissions configs

---

### Finding 14: SCD Type 2 Tracking Not Generated

**Severity:** Medium
**Problem:** Extension TTL declares `kairos-ext:scdType "2"` but the projected silver models don't include the standard SCD2 columns (`valid_from`, `valid_to`, `is_current`, `version_hash`).

**Required Generation:** When `scdType "2"` is declared, generate:
- Surrogate key column (configurable strategy: UUID, hash, sequence)
- `_valid_from`, `_valid_to`, `_is_current`, `_version_hash` columns
- dbt snapshot configs or merge logic
- Audit envelope columns from extension config

---

## LOW-PRIORITY FINDINGS (P3 — Quality of Life)

### Finding 15: No Source-System-Agnostic Templates for Common Patterns

**Problem:** Cross-system patterns (deduplication, SCD2, audit columns, GDPR masking) are reimplemented per source. Should be reusable Jinja macros generated by the toolkit.

---

### Finding 16: No Lineage Documentation Generated

**Problem:** Generated dbt models lack column-level lineage comments documenting the source-to-target mapping. Useful for governance and debugging.

**Recommended:** Generate column-level YAML descriptions including the source vocabulary IRI and any transformations applied. Combined with enforced layer contracts (Finding 1), this becomes automatic and reliable.

---

### Finding 17: No Test Generation from Vocabulary Constraints

**Problem:** The vocabulary declares `kairos-bronze:nullable false`, `kairos-bronze:isPrimaryKey true`, etc. — these are not translated into dbt tests (`not_null`, `unique`).

**Recommended:** Auto-generate dbt schema YAML with tests derived from vocabulary constraints.

---

### Finding 18: No Incremental Materialization Hints

**Problem:** Vocabulary declares `kairos-bronze:incrementalColumn` but the projector ignores it. Silver/gold models default to full-refresh.

**Recommended:** When `incrementalColumn` is declared, generate `materialized='incremental'` with appropriate `unique_key` and `incremental_strategy` for the target platform.

---

## SUMMARY: Prioritized Roadmap

The improvements break naturally into four phases. Each phase is independently valuable, but the full transition from "manually rewrite 80% of generated models" to "0% manual rewrites needed" requires all four.

### Phase 1 — Fix the Wiring (Highest ROI)

Solves Findings 1, 8, 9, 12, 16. This is the **single most impactful change**: it fixes the architectural disconnect that currently makes 100% of silver models non-functional.

1. **Tag ontology properties** (Finding 8) — required / optional / derived / unmapped
2. **Enforce layer contracts** (Finding 1) — staging consumes only from source; silver consumes only from staging
3. **Generate the missing intermediate `stg_<domain>__<entity>` models** bridging source-aligned staging to domain-aligned silver
4. **Apply mapping TTL transformations** in the generated bridge layer (filters, column renames, computed values)
5. **Generate coverage reports** (Finding 9) — surface mapping gaps as first-class output

After Phase 1: silver models connect to staging; the projector fails loudly on broken contracts; coverage gaps are visible. But generated SQL still fails at runtime due to physical storage mismatches and dialect issues.

### Phase 2 — Fix the Extraction

Solves Findings 2, 3. The vocabulary now describes physical reality, not idealized normalization.

6. **Add `physicalStorage` annotation** (Finding 2) — `table` / `inline` / `json-array` / `json-object`
7. **Add JSON schema definitions** (Finding 3) — describe nested structures with field-level types and paths
8. **Generate appropriate extraction patterns** per `physicalStorage` value
9. **Apply VARCHAR-extraction safety rule** for JSON, with TRY_CAST in downstream layers

After Phase 2: generated staging actually matches physical bronze. But generated SQL may still fail on platforms with different dialect rules.

### Phase 3 — Fix the Dialect

Solves Finding 4. Generated SQL runs on the chosen target platform.

10. **Add platform configuration** (Finding 4) — type mapping + dialect functions per platform
11. **Ship standard platform profiles** — fabric, synapse, sql-server, snowflake, bigquery, databricks, postgres
12. **Apply platform type mapping** consistently across all generated models

After Phase 3: generated SQL runs on the target platform without modification. Output is functional.

### Phase 4 — Polish

Solves Findings 5, 6, 7, 10, 11, 13, 14, 15, 17, 18. Improves output quality and maintainability.

13. **Require sample data + validator** (Finding 5)
14. **Model discriminator columns** (Finding 6)
15. **Model enum values + auto-generate CASE/seeds** (Finding 7)
16. **Multi-valued attribute unpivoting** (Finding 10)
17. **Distinguish dimension vs. fact tables** (Finding 11)
18. **Generate GDPR satellite isolation** (Finding 13)
19. **Generate SCD Type 2 tracking** (Finding 14)
20. **Reusable Jinja macros, dbt tests from constraints, incremental materialization** (Findings 15, 17, 18)

---

## What Each Phase Solves Alone

It's important to understand that the phases are necessary but not individually sufficient:

| Phase | Without other phases, what works? | What still fails? |
|---|---|---|
| **Phase 1 alone** | Layer dependency chain is correct; mapping logic flows from source to silver | Extraction fails on denormalized/JSON sources; SQL fails on platforms with strict type rules |
| **Phase 2 alone** | Staging correctly extracts from physical storage | Silver layer still references non-existent `stg_<domain>__*` models |
| **Phase 3 alone** | Generated SQL is dialect-correct | Silver layer still disconnected; staging assumes wrong physical structure |
| **Phases 1+2+3** | Generated output runs end-to-end on the target platform | Quality issues remain (raw enum codes, NULL placeholders, no SCD tracking) |
| **All four phases** | Generated output runs end-to-end with high data quality | — |

The toolkit cannot reach "100% of generated models work" through any single phase. Phase 1 unlocks the architecture; Phases 2 and 3 unlock physical execution; Phase 4 unlocks production-grade quality.

---

## Acceptance Criteria for Toolkit Improvements

A toolkit version that addresses all P0 + P1 findings (Phases 1–3 plus Findings 5, 8) should be able to:

1. Take a vocabulary describing a denormalized source table with JSON columns
2. Take an ontology with properties tagged as required/optional/derived
3. Take mapping files describing how source columns map to ontology properties (with filters, transformations, discriminators)
4. Take a target platform configuration (e.g., "microsoft-fabric")
5. Generate dbt staging, silver, and gold models that **run successfully against the actual bronze tables without manual modification**
6. Fail at generation time (not runtime) when required ontology properties cannot be sourced
7. Produce a coverage report showing populated vs. NULL columns and unused source columns

The current toolkit version requires ~80% of generated models to be manually rewritten before they can run. The target should be ≤5%.

---

## Test Case for Validation

To validate any toolkit improvement, the test case should be:

1. A source system with:
   - At least one denormalized table with both inline child entities and JSON columns
   - At least one type discriminator column
   - At least one enum-coded column with 10+ values
   - At least one nested JSON structure (object containing array)

2. Vocabulary covering all bronze columns with appropriate annotations

3. Mappings to multiple ontology domains, with filters, transformations, and aggregations

4. Ontology with properties tagged as required/optional/derived

5. Target platform: Microsoft Fabric (the strictest dialect — VARCHAR-only, no NVARCHAR)

6. Success criteria:
   - `dbt run` against the actual bronze tables succeeds for 100% of generated models with no manual modifications
   - All required ontology properties are populated (not NULL placeholders) wherever source data exists
   - Coverage report identifies any gaps explicitly
   - Generation fails loudly if any required ontology property cannot be sourced
