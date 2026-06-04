---
name: kairos-design-source
description: >
  Expert guide for importing, documenting, and analysing source system data.
  Covers flat-file import, YAML-to-TTL generation, manual bronze vocabulary
  creation, enrichment review, and LLM-powered source-to-domain analysis.
---

# Kairos Source Design Skill

You are helping the user **import, document, and analyse source systems** for the
ontology hub. This skill orchestrates the full source onboarding workflow — from
raw data files to bronze vocabulary TTL and domain affinity analysis.

## Overview — Source onboarding workflow

```
Phase 0          Phase 1              Phase 2             Phase 3
Input type? ──→  Import flat files ──→ Generate vocab ──→  Review & validate
                 (import-flatfile)     (import-source)
                      OR                                       │
                 Manual creation ─────────────────────────────→│
                                                               ▼
                                                          Phase 4
                                                          Analyse sources
                                                          (analyse-sources)
                                                               │
                                                               ▼
                                                          Phase 5
                                                          Next steps
```

## Prerequisites

- The ontology hub must be initialized (`kairos-ontology init` or `new-repo`)
- Source data or documentation should be available (CSV/Excel files, SQL DDL,
  API specs, or sample data)
- For Phase 4 (analysis): AI provider configured (GITHUB_TOKEN or AZURE_AI_ENDPOINT)

---

## Phase 0 — Determine input type

Ask the user what source material they have:

| Input type | Path |
|---|---|
| **CSV or Excel files** (exports, data dumps) | → Phase 1 (import-flatfile) |
| **Pre-extracted YAML** (from `extract-schema` dbt macro or manual) | → Phase 2 (import-source) |
| **SQL DDL, API specs, or other docs** (no structured data) | → Phase 3 (manual creation) |
| **Existing vocabulary TTL** (refresh/update) | → Phase 2 (import-source with merge) |

### Pre-flight checks

Before proceeding, verify the hub structure:

```bash
ls ontology-hub/integration/sources/
```

If the system folder doesn't exist yet, create it:

```bash
mkdir -p ontology-hub/integration/sources/{system-name}
```

---

## Phase 1 — Import flat files (`import-flatfile`)

> **When to use:** The user has CSV exports, Excel workbooks, or a directory of
> flat files from the source system.

### 1a — Determine options

Ask the user:
1. **Source path** — where are the files? (single file or directory)
2. **System name** — what to call this source system (default: derived from filename)
3. **Column exclusions** — any metadata/technical columns to exclude?

### 1b — Run the import

```bash
kairos-ontology import-flatfile \
  --from {source-path} \
  --system {system-name}
```

**Available options:**

| Option | Default | When to use |
|---|---|---|
| `--exclude-columns "col1,col2"` | none | Remove metadata columns (volume, subfolder, etc.) |
| `--keep-technical` | false | Keep auto-detected technical columns |
| `--sample-size N` | 5 | More/fewer sample rows per table |
| `--max-rows N` | 1000 | More rows for better type inference |

### 1c — Review output

The command produces:
- `_manifest.yaml` — system metadata
- Per-table YAML files — schema + samples
- `.samples.yaml` files — sample data rows

```bash
ls ontology-hub/integration/sources/{system-name}/
```

**Checkpoint:** Show the user what was generated. Ask if any tables should be
excluded or if column names need correction before proceeding to Phase 2.

→ Proceed to **Phase 2** to generate the vocabulary TTL.

---

## Phase 2 — Generate vocabulary (`import-source`)

> **When to use:** Source schema YAML files exist (from Phase 1 or from the
> `extract-schema` dbt macro) and need to be converted to bronze vocabulary TTL.

### 2a — Run the import

```bash
kairos-ontology import-source \
  --from ontology-hub/integration/sources/{system-name}/
```

**Available options:**

| Option | Default | When to use |
|---|---|---|
| `--enrich` / `--no-enrich` | enabled | Disable enrichment if source has no sample data |
| `--enum-threshold N` | 25 | Adjust max distinct values for enum detection |
| `--dry-run` | false | Preview changes without writing |
| `--split-tables` | false | Only generate per-table files (skip monolithic) |

### 2b — Review enrichment annotations

If enrichment was enabled, the generated TTL contains inference annotations.
Review these with the user:

| Annotation | What it tells you | Action |
|---|---|---|
| `kairos-bronze:suggestedEnum true` | Low-cardinality column (≤N distinct values) | Ask: "Should this be a code list?" |
| `kairos-bronze:enumValues "A \| B \| C"` | Actual distinct values observed | Show values for confirmation |
| `kairos-bronze:formatHint "email"` | Samples match a known format | Suggest `xsd:string` with format constraint |
| `kairos-bronze:formatHint "date"` | Date-like values stored as string | Suggest `xsd:date` or `xsd:dateTime` |
| `kairos-bronze:formatHint "uuid"` | UUID identifiers | Likely a natural key or FK reference |
| `kairos-bronze:suggestedForeignKey <uri>` | Column likely references another table | Ask: "Does this reference [target]?" |
| `kairos-bronze:fkConfidence "high"` | Name-based match (strong signal) | Present as default recommendation |
| `kairos-bronze:fkConfidence "medium"` | Cardinality-based match (weaker) | Present as suggestion, ask to confirm |
| `kairos-bronze:rowCount N` | Table size | Prioritize high-volume tables |
| `kairos-bronze:sampleValues "val1 \| val2"` | Actual data samples | Show for user to validate semantics |

### 2c — Output review

The command writes:
- `{system-name}.vocabulary.ttl` — monolithic vocabulary file
- `vocabulary/` — per-table TTL files

**Checkpoint:** Show the user a summary of tables and columns generated.
Verify the TTL is valid:

```bash
kairos-ontology validate
```

→ Proceed to **Phase 4** (analyse) or **Phase 5** (next steps).

---

## Phase 3 — Manual vocabulary creation

> **When to use:** The user has SQL DDL, API specs, or documentation but no
> structured data files. The vocabulary must be hand-crafted from reference docs.

### 3a — Verify source documentation

Check what documentation is available in the source folder:

| Material | Location | Priority |
|----------|----------|----------|
| SQL DDL (CREATE TABLE) | `sql-ddl/*.sql` | ⭐ Best — exact schema |
| API specs (OpenAPI/Swagger) | `api-specs/*.yaml` or `*.json` | ⭐ Good — typed endpoints |
| Sample data (CSV/JSON) | `samples/*` | 🔶 Useful — infer types |
| Database documentation | `docs/*` | 🔶 Context — business meaning |
| Notes / observations | `README.md`, `notes.md` | 📝 Context |

### 3b — Review the source system README

Read `ontology-hub/integration/sources/{system-name}/README.md` for:
- System name and version
- Connection type (jdbc, odbc, api, file, lakehouse)
- Database and schema names
- Owner and contact info

### 3c — Extract schema information

**From SQL DDL:** Extract table names, column names, data types, PKs, FKs,
nullable constraints, defaults.

**From API specs:** Map resources/endpoints to tables, properties to columns,
types to data types, required to NOT NULL.

**From sample data:** Infer column names from headers/keys, types from values,
nullable from empty values.

### 3d — Generate the vocabulary TTL

Create `ontology-hub/integration/sources/{system-name}/{system-name}.vocabulary.ttl`:

```turtle
@prefix bronze-{prefix}: <https://{company-domain}/bronze/{system-name}#> .
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .

bronze-{prefix}:{SystemName} a kairos-bronze:SourceSystem ;
    rdfs:label "{System Display Name}" ;
    kairos-bronze:connectionType "{jdbc|odbc|api|file|lakehouse}" ;
    kairos-bronze:database "{DatabaseName}" ;
    kairos-bronze:schema "{SchemaName}" .
```

For each table:

```turtle
bronze-{prefix}:{tableName} a kairos-bronze:SourceTable ;
    rdfs:label "{tableName}" ;
    kairos-bronze:sourceSystem bronze-{prefix}:{SystemName} ;
    kairos-bronze:tableName "{tableName}" ;
    kairos-bronze:primaryKeyColumns "{PK1} {PK2}" ;
    kairos-bronze:incrementalColumn "{ModifiedDate}" .
```

For each column:

```turtle
bronze-{prefix}:{tableName}_{columnName} a kairos-bronze:SourceColumn ;
    kairos-bronze:sourceTable bronze-{prefix}:{tableName} ;
    kairos-bronze:columnName "{columnName}" ;
    kairos-bronze:dataType "{dataType}" ;
    kairos-bronze:nullable "{true|false}"^^xsd:boolean ;
    kairos-bronze:isPrimaryKey "{true|false}"^^xsd:boolean .
```

### Data type mapping reference

| Source (SQL Server) | Source (API/JSON) | kairos-bronze:dataType |
|--------------------|--------------------|----------------------|
| `int` | `integer` | `"int"` |
| `bigint` | `integer (int64)` | `"bigint"` |
| `nvarchar(N)` | `string` | `"nvarchar(N)"` |
| `varchar(N)` | `string` | `"varchar(N)"` |
| `datetime2` | `date-time` | `"datetime2"` |
| `date` | `date` | `"date"` |
| `bit` | `boolean` | `"bit"` |
| `decimal(P,S)` | `number` | `"decimal(P,S)"` |
| `uniqueidentifier` | `string (uuid)` | `"uniqueidentifier"` |

### 3e — Validate

```bash
kairos-ontology validate
```

Verify:
- [ ] Every table from the source has a `kairos-bronze:SourceTable` entry
- [ ] Every column has a `kairos-bronze:SourceColumn` entry
- [ ] All primary key columns are marked with `kairos-bronze:isPrimaryKey "true"`
- [ ] Data types are filled in for all columns
- [ ] The source system README is up to date

→ Proceed to **Phase 4** (analyse) or **Phase 5** (next steps).

---

## Phase 4 — Analyse sources (`analyse-sources`)

> **When to use:** All source vocabularies have been created (via any Phase 1-3
> path) and you want to understand which reference model domains each source
> contributes to. **Requires AI provider** (GITHUB_TOKEN or AZURE_AI_ENDPOINT).

### 4a — Pre-flight check

Verify source vocabularies exist:

```bash
ls ontology-hub/integration/sources/*/*.vocabulary.ttl
```

Verify reference models are available:

```bash
ls ontology-reference-models/
```

### 4b — Run the analysis

```bash
kairos-ontology analyse-sources
```

**Available options:**

| Option | Default | When to use |
|---|---|---|
| `--domains "party,booking"` | all | Focus on specific domains |
| `--threshold 0.3` | 0.3 | Minimum affinity confidence |
| `--model gpt-5.4-mini` | gpt-5.4-mini | LLM model for semantic matching |
| `--max-domains N` | all | Rate limit protection |
| `--materialize .resolved/` | none | Write merged TTLs per domain for inspection |
| `--sources path/` | auto-detect | Override sources directory |
| `--ref-models path/` | auto-detect | Override reference models directory |

### 4c — Review affinity reports

The command produces `{system}-affinity.yaml` files in
`integration/sources/_analysis/` with:

- **`domain_contributions`** — ranked list of reference model domains each
  source feeds
- **Per-table domain relevance** — how strongly each table belongs to a domain
- **`likely_entity`** — which reference model class the table most likely maps to
- **`indicative_columns`** — key columns that signal domain membership
- **`rationale`** — natural language explanation of why the table fits

**Checkpoint:** Review the affinity reports with the user. Ask:
- Do the domain assignments make sense?
- Are there any unexpected matches or missing domains?
- Should any domains be re-run with different parameters?

→ Proceed to **Phase 5**.

---

## Phase 5 — Next steps

After the source vocabulary and analysis are complete:

1. **Design domain ontology** — invoke the **kairos-design-domain** skill.
   It uses the affinity reports from Phase 4 as a mandatory prerequisite
   (Step 0a) to scope which tables to model per domain.
2. **Create SKOS mappings** — invoke the **kairos-design-mapping** skill to
   map source columns to domain ontology properties
3. **Design silver annotations** — invoke the **kairos-design-silver** skill
4. **Generate output** — invoke the **kairos-execute-project** skill

---

## Source system folder structure reference

```
ontology-hub/integration/sources/{system-name}/
  README.md                            # System description, owner, connection details
  {system-name}.vocabulary.ttl         # Source vocabulary (kairos-bronze: TTL)
  vocabulary/                          # Per-table TTL files
  _manifest.yaml                       # System metadata (from import-flatfile)
  *.yaml                               # Per-table schema (from import-flatfile)
  *.samples.yaml                       # Sample data (from import-flatfile)
  sql-ddl/                             # CREATE TABLE exports
  api-specs/                           # OpenAPI / Swagger specs
  samples/                             # Sample data files (CSV, JSON, XML)
  docs/                                # Additional documentation
  _analysis/                           # Affinity reports (from analyse-sources)
  notes.md                             # Free-form observations
```

---

## Session Management

> **MANDATORY:** Every source design session MUST produce a session file that
> captures what was documented, what gaps remain, and design decisions.

### On start — Check for existing session

```
ontology-hub/.sessions-design/
  └── source-{system-name}-{YYYY-MM-DD}.md
```

If a previous session exists, ask the user whether to continue or start fresh.

### Session file format

Save to `ontology-hub/.sessions-design/source-{system-name}-{YYYY-MM-DD}.md`:

```markdown
# Source Design Session: {system-name}

**Started:** {ISO-8601}
**Last updated:** {ISO-8601}
**Status:** Complete | In Progress
**Toolkit version:** {version}

## Import Method

{flat-file | yaml-import | manual}

## Tables Documented

| # | Table | Columns | Data Types Verified | Notes |
|---|---|---|---|---|
| 1 | {table_name} | {count} | ✅/❌ | {any notes} |

## Enrichment Review

| # | Table.Column | Annotation | Value | User Decision |
|---|---|---|---|---|
| 1 | {table.col} | suggestedEnum | true | ✅ Confirmed / ❌ Rejected |

## Analysis Results

| # | Domain | Affinity | Top Tables | Notes |
|---|---|---|---|---|
| 1 | {domain} | {score} | {tables} | {notes} |

## Deferred / TODO

| # | Table/Column | Item | Reason | Resolve via |
|---|---|---|---|---|
| 1 | {name} | {what is missing} | {why deferred} | kairos-design-source |

## Design Decisions

| # | Question | Decision | Rationale |
|---|---|---|---|
| 1 | {question} | {choice made} | {why} |

## Source Evidence Gaps

| # | Gap | Impact | Resolution |
|---|---|---|---|
| 1 | {what documentation is missing} | {which mappings/projections are blocked} | {how to resolve} |
```

### Saving rules

- **Auto-save** after each phase completion
- Record tables that could not be fully documented with reasons
- On pause/completion, list remaining gaps and their downstream impact

---

## Related skills

| When you need | Invoke |
|---|---|
| Design/modify domain ontology classes and properties | **kairos-design-domain** |
| Design silver layer (DDL, SCD, FK annotations) | **kairos-design-silver** |
| Design gold layer (Power BI star schema, measures) | **kairos-design-gold** |
| Map source columns to domain properties | **kairos-design-mapping** |
| Run projections after source vocab is complete | **kairos-execute-project** |
