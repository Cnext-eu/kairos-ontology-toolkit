---
name: kairos-execute-project
description: >
  Knowledge about generating downstream artifacts from ontologies.
  Covers all 7 projection targets and when to use each.
---

# Projection Generation Skill

> **🔒 Skill context:** Before running any `kairos-ontology` /
> `python -m kairos_ontology` command in this skill, set the sentinel env var so
> the CLI knows it runs inside a skill and suppresses its skill-gate warning:
> - PowerShell: `$env:KAIROS_SKILL_CONTEXT = "1"`
> - bash/zsh: `export KAIROS_SKILL_CONTEXT=1`

You help users generate and understand projection artifacts.

> **When to use this skill vs design skills (DD-033):**
> - Use **this skill** when the user wants to **generate output** — run projections,
>   produce DDL, dbt models, TMDL, ERDs, JSON artifacts, or reports.
> - Use **medallion-silver** when the user needs to **design** silver extension
>   annotations (SCD types, natural keys, FK declarations) — the design phase.
> - Use **medallion-gold** when the user needs to **design** gold extension
>   annotations (fact/dimension types, measures, hierarchies) — the design phase.
> - Use **medallion-source** when the user needs to **create** bronze vocabulary
>   descriptions from source system documentation — the design phase.
>
> **Rule of thumb:** Design skills create/modify annotation files.
> This skill generates output FROM those files. Design first, then project.

## Before you start

0. **Quick toolkit version check** — run `python -m kairos_ontology update --check` once
   at the start of the session.  If it reports outdated files, run
   `python -m kairos_ontology update` and commit the refresh before doing any other work.
   See the kairos-toolkit-ops skill for full upgrade steps.

## Pre-flight checks (medallion targets)

Before running a **medallion target** (`silver`, `dbt`, or `powerbi`), you MUST check
that prerequisite files exist. Non-medallion targets (`prompt`, `neo4j`, `azure-search`,
`a2ui`, `report`) need no pre-flight — run them immediately.

### Check matrix

| Target | Required files | Design skill |
|--------|---------------|--------------|
| **silver** | `model/extensions/<domain>-silver-ext.ttl` | `kairos-design-silver` |
| **dbt** | Silver ext (above) + at least one `integration/sources/<system>/*.vocabulary.ttl` + at least one `model/mappings/<system>-to-<domain>.ttl` | Extensions: `kairos-design-silver`; Mappings: `kairos-design-mapping` |
| **powerbi** | `model/extensions/<domain>-gold-ext.ttl` | `kairos-design-gold` |

### Procedure

1. Identify which medallion targets the user requested (explicit `--target` or implied via bare `project`).
2. For each medallion target, check whether the required files exist in the hub.
3. **If files are missing:**
   - List what is missing (e.g. "No `*-silver-ext.ttl` found in `model/extensions/`").
   - Explain what the extension file provides (annotation decisions: natural keys, SCD types, FK declarations, schema names).
   - Offer the user a choice:
     - **(Recommended)** Invoke the design skill to create the extensions first.
     - Run anyway with defaults (all columns SCD Type 1, no natural keys, no FK — produces valid but incomplete output).
4. **If files are present:** proceed with projection normally.
5. **For bare `project` (all targets):** run non-medallion targets immediately; apply the pre-flight check only for the medallion subset.

### Source-coverage gate (silver / dbt — MANDATORY, DD-061)

When the hub has affinity reports (`integration/sources/_analysis/*-affinity.yaml`),
**also** run the deterministic claims gate before projecting `silver` or
`dbt`, so the silver layer is built against a **complete** ontology rather than a
partial one (the gate includes the pre-silver mapping-coverage check):

```bash
kairos-ontology check-claims
```

- **Exit 0** → every affinity-assigned source table is mapped to a domain entity.
  Proceed with projection.
- **Exit 1** → STOP. The listed `(system.table)` pairs have domain affinity but no
  source-to-domain mapping. Hand off to **kairos-design-mapping** (and
  **kairos-design-domain** if classes are missing) to close the gaps, then re-run
  the gate. Override only deliberately with `--warn-only`.

`check-claims` is read-only and deterministic (no AI). Skip it only when
no affinity reports exist yet (the hub hasn't run `analyse-sources`).

#### Claim-driven extension sync (Slice 2)

When a domain has an **approved** Claim Registry (`model/claims/{domain}-claims.yaml`),
approved imported-class claims deterministically drive that domain's external
`owl:imports` and silver-extension `silverInclude` annotations. `check-claims`
includes a **sync gate** that flags drift between the approved claims and the
generated projection surfaces; materialize the surfaces with:

```bash
kairos-ontology claims-to-silver-ext
```

This rewrites the domain ontology's external `owl:imports` and the
`*-silver-ext.ttl` `silverInclude` set to exactly match the approved imported
claims (A1). The generated TTL stays human-reviewable (A2-lite). The
`silver`, `dbt`, and `powerbi` projectors enforce an **authority gate**: if a
claims file exists and the surfaces are out of sync, projection fails with a
pointer to run `claims-to-silver-ext`. Use `check-claims --no-extension-sync`
to skip only the sync portion of the gate.

#### MDM / reference-data + ownership gates (Slice 4)

`check-claims` also enforces four MDM/ownership rules over the registry's curated
governance fields (`reference_data`, `mdm_anchor`, `deviation`, `ownership_override`,
`passthrough_reviewed`):

- **MDM-anchor gate (§5.4)** — broad domain claims (approved class claims with
  disposition claim/specialize) block with `anchor_pending` when declared
  `mdm_anchor` reference-data claims are still `proposed`, and warn `anchor_missing`
  (pragmatic — anchors must be *known*, not fully implemented) when no anchors are
  declared at all.
- **deviation-log (§12/§14)** — approved `gap` (client-native) claims without a
  `deviation` (owner + reason) block with `deviation_missing`.
- **ownership-boundary (§14)** — approved claims crossing another data-domain's
  `data-domains.yaml` `uris` prefix block with `ownership_conflicts` unless an
  `ownership_override` (owner + rationale) is present; that override also downgrades
  a cross-file same-URI duplicate from `duplicate_approved` to a `shared_dimensions`
  warning (conformed-dimension share).
- **passthrough-review (§11.2)** — high-use passthrough claims not yet
  `passthrough_reviewed` warn with `passthrough_review`.

Skip those gates with `check-claims --no-mdm-anchor` / `--no-ownership`.


### Example interaction

```
User: "project to silver"

You:
  1. Check model/extensions/*-silver-ext.ttl → NOT FOUND
  2. "The silver target requires a silver extension file with kairos-ext: annotations
     (naturalKey, silverSchema, scdType, etc.). None found in model/extensions/.
     Would you like me to invoke kairos-design-silver to create it,
     or run the projection with defaults?"
```

## Available targets

| Target | Output | Use case |
|--------|--------|----------|
| **dbt** | SQL models + schema.yml | Data warehouse modeling |
| **neo4j** | Cypher schema scripts | Graph database setup |
| **azure-search** | Index + synonym map JSON | Azure AI Search configuration |
| **a2ui** | Message schema JSON | UI generation / form scaffolding |
| **prompt** | Compact + detailed context JSON | LLM prompt context injection |
| **silver** | DDL + ALTER + Mermaid ERD | MS Fabric / Delta Lake silver layer |
| **powerbi** | Star schema DDL + TMDL + DAX + ERD | Power BI / MS Fabric gold layer |
| **report** | HTML mapping reports | Business analyst mapping coverage review |

## When to use each target

- **dbt**: When the ontology drives a data warehouse using dbt Core. Generates a complete dbt project with silver entity models (from source systems via SKOS mappings), schema YAML with SHACL-derived tests, and project config. Requires source vocabulary files (`*.vocabulary.ttl`) in `integration/sources/{system-name}/` for source system descriptions and `model/mappings/{system}-to-{domain}.ttl` for SKOS column mappings to domain ontology properties. The dbt projector scans `integration/sources/` recursively for `*.ttl` files with the `kairos-bronze:` namespace. See the **kairos-design-silver** skill.
- **neo4j**: When building a knowledge graph. Generates `CREATE CONSTRAINT` statements and relationship patterns.
- **azure-search**: When building a search index. Maps ontology properties to Azure Search field types with filters and facets.
- **a2ui**: When generating UI forms. Creates JSON schemas that describe the data structure for automatic UI rendering.
- **prompt**: When using the ontology as LLM context. Generates a compact version (entity→fields map) and a detailed version (with types, descriptions, relationships).
- **silver**: When building the silver layer of a medallion data platform (e.g. MS Fabric warehouse). Generates T-SQL DDL (`CREATE TABLE`), FK/UNIQUE constraints (`ALTER TABLE`), and a Mermaid ERD. Requires a `*-silver-ext.ttl` annotation file in `model/extensions/`. Imported classes (via `owl:imports`) are not projected by default — use `silverInclude` or `silverIncludeImports` to claim them (DD-021). See the **kairos-design-silver** skill.

## CLI commands

```bash
# Generate all projections for all domains
python -m kairos_ontology project

# Generate a single target
python -m kairos_ontology project --target prompt

# Generate silver layer (requires *-silver-ext.ttl in model/extensions/)
python -m kairos_ontology project --target silver

# Available targets: dbt, neo4j, azure-search, a2ui, prompt, silver, powerbi, report
```

## Medallion pipeline

The **medallion targets** (`silver`, `dbt`, `powerbi`) together produce a complete
data platform from ontology → warehouse → BI layer.  They all write to
`output/medallion/` and share annotations from `model/extensions/`.

### What each medallion target generates

| Target | What it does | Key inputs | Key outputs |
|--------|-------------|------------|-------------|
| **silver** | Generates the **physical schema** for the silver warehouse layer | `*-silver-ext.ttl` | DDL (`CREATE TABLE`), FK/UNIQUE constraints (`ALTER TABLE`), Mermaid ERD + SVG |
| **dbt** | Generates a **dbt Core project** with transformation models that populate the silver schema from bronze sources | `*-silver-ext.ttl` + bronze vocabularies + SKOS mappings | SQL models, `schema.yml` with tests, `dbt_project.yml`, macros |
| **powerbi** | Generates the **gold layer** star schema + Power BI semantic model | `*-gold-ext.ttl` | Gold DDL, TMDL semantic model, DAX measures, star-schema ERD |

> **Import whitelisting (DD-021):** The silver and powerbi targets only project
> classes defined in the hub domain by default. Imported classes (via `owl:imports`)
> require explicit claiming with `silverInclude`/`silverIncludeImports` or
> `goldInclude`/`goldIncludeImports` in the appropriate extension file.

### How they relate (execution order)

```
┌─────────────────────────────────────────────────────────────────────┐
│  Ontology (.ttl)  +  Extensions  +  Sources/Mappings                │
└────────────┬────────────────┬────────────────┬──────────────────────┘
             │                │                │
             ▼                ▼                ▼
      ┌─────────────┐  ┌──────────┐  ┌──────────────┐
      │   silver    │  │   dbt    │  │   powerbi    │
      │  (schema)   │  │ (models) │  │ (star schema)│
      └──────┬──────┘  └────┬─────┘  └──────┬───────┘
             │               │               │
             ▼               ▼               ▼
      DDL + ALTER      dbt project      TMDL + DAX
      + ERD            (silver SQL)     + gold DDL + ERD
```

### Running the full medallion pipeline

There is no `--target medallion` shorthand — run `--target all` (default) or
run the three targets individually:

```bash
# All three medallion targets (plus neo4j, prompt, etc.)
python -m kairos_ontology project

# Just the medallion pipeline (run separately)
python -m kairos_ontology project --target silver
python -m kairos_ontology project --target dbt
python -m kairos_ontology project --target powerbi
```

### Prerequisites for each medallion target

| Target | Required files | Skill for guidance |
|--------|---------------|-------------------|
| **silver** | `model/extensions/<domain>-silver-ext.ttl` with `kairos-ext:` annotations (naturalKey, silverSchema, scdType, etc.) | `kairos-design-silver` |
| **dbt** | All silver prerequisites PLUS `integration/sources/<system>/*.vocabulary.ttl` (bronze) AND `model/mappings/<system>-to-<domain>.ttl` (SKOS mappings) | `kairos-design-silver` |
| **powerbi** | `model/extensions/<domain>-gold-ext.ttl` with gold annotations (goldTableType, goldSchema, measureExpression, etc.) | `kairos-design-gold` |

### What gets generated in detail

**Silver target** — physical schema definition:
- `CREATE TABLE` with typed columns, SK, IRI, audit envelope columns
- `ALTER TABLE` for UNIQUE constraints (from SHACL) and FK relationships
- Mermaid ERD showing entity relationships
- Master ERD combining all domains

**dbt target** — transformation logic:
- One `.sql` model per entity per source system (e.g., `silver_client__crmsystem.sql`)
- `schema.yml` with column descriptions + SHACL-derived dbt tests (not_null, unique, regex)
- `dbt_project.yml` with materialisation config
- Macros for surrogate key generation (`generate_sk.sql`)
- Handles split patterns (one source → multiple entity subtypes)
- Handles merge patterns (multiple sources → one entity)
- Cross-domain FK joins via surrogate keys

**Power BI target** — analytical layer:
- Star-schema DDL (dimension + fact + bridge tables)
- TMDL semantic model (`.tmdl` files for Power BI Desktop / Fabric)
- DAX measures from `measureExpression` annotations
- Hierarchies, perspectives, calculation groups
- Gold-layer Mermaid ERD

## Output structure

Output is generated into `ontology-hub/output/<target>/`:

```
ontology-hub/output/
├── projection-report.json              # run summary (always generated)
├── medallion/
│   ├── dbt/customer/models/silver/
│   │   ├── customer.sql
│   │   └── schema_customer.yml
│   ├── silver/customer/
│   │   ├── customer-ddl.sql               # CREATE TABLE (T-SQL / MS Fabric)
│   │   ├── customer-alter.sql             # ALTER TABLE (UNIQUE + FK constraints)
│   │   ├── customer-erd.mmd               # Mermaid erDiagram
│   │   └── customer-erd.svg               # SVG render (requires Mermaid CLI)
│   └── powerbi/customer/
│       ├── customer-gold-ddl.sql          # Star schema CREATE TABLEs
│       ├── customer-gold-alter.sql        # FK constraint documentation
│       ├── customer-gold-erd.mmd          # Star schema Mermaid ERD
│       ├── customer-gold-erd.svg          # SVG render (requires Mermaid CLI)
│       └── semantic-model/                # TMDL + DAX measures
├── neo4j/
│   └── customer-schema.cypher
├── azure-search/customer/indexes/
│   └── customer-index.json
├── a2ui/customer/schemas/
│   └── customer-message-schema.json
└── prompt/
    ├── customer-context.json              # compact
    └── customer-context-detailed.json     # verbose
```

## Projection report (`projection-report.json`)

Every `kairos-ontology project` run writes `output/projection-report.json` with a
machine-readable summary of everything that happened. Use it for CI/CD gates,
dashboards, and debugging failed projections.

### Report structure

| Key | Description |
|-----|-------------|
| **toolkit_version** | Version of the toolkit that produced the report |
| **generated_at** | ISO-8601 timestamp of the run |
| **targets_requested** | List of targets that were run (e.g. `["dbt","silver","prompt"]`) |
| **summary** | Aggregate counts — `domains_found`, `domains_loaded`, `domains_failed_to_load`, `total_files_generated`, `errors`, `warnings`, `skipped` |
| **domains** | Per-domain load status: `file`, `triples`, `namespace`, `status` (`ok`/`error`), optional `error` message |
| **projections** | Per-target × per-domain results: `status` (`ok`/`error`/`skipped`), `files` list on success, `error` + `traceback` on failure |
| **post_steps** | Status of post-processing steps such as master ERD generation and SVG export |
| **events** | Structured log entries with `level` (`info`/`warning`/`error`) and optional `domain` and `target` context |

### Using the report in CI/CD

```bash
# Fail the pipeline if any projection error occurred
python -c "
import json, sys
report = json.load(open('output/projection-report.json'))
if report['summary']['errors'] > 0:
    print(f'Projection failed with {report[\"summary\"][\"errors\"]} error(s)')
    sys.exit(1)
print('All projections succeeded')
"
```

You can also check `summary.warnings` or inspect `projections` entries with
`status == "skipped"` to enforce stricter quality gates.

## Property type mapping

| OWL/XSD Type | dbt | neo4j | Azure Search | a2ui | silver (T-SQL) |
|---|---|---|---|---|---|
| `xsd:string` | VARCHAR | String | Edm.String | string | NVARCHAR(MAX) |
| `xsd:integer` | INTEGER | Integer | Edm.Int64 | integer | BIGINT |
| `xsd:decimal` | DECIMAL | Float | Edm.Double | number | DECIMAL(18,4) |
| `xsd:boolean` | BOOLEAN | Boolean | Edm.Boolean | boolean | BIT |
| `xsd:dateTime` | TIMESTAMP | DateTime | Edm.DateTimeOffset | date-time | DATETIME2 |
| `xsd:date` | DATE | Date | Edm.DateTimeOffset | date | DATE |

## Tips

- Generate `prompt` projection first to quickly verify the ontology structure is correct.
- Use `dbt` projection when you want to see the full property extraction including SHACL tests.
- Run all targets at once to catch issues specific to certain mappings.
- For `silver`: run the **kairos-design-silver** skill first to set up `kairos-ext:` annotations in `model/extensions/` before projecting.

## Common warnings

| Warning | Meaning | Action |
|---------|---------|--------|
| **DD-021: Unclaimed parent** | A projected class has a parent NOT in the projection set. Properties are auto-inherited from unprojected parents. | Review whether the parent should be a separate table (`silverInclude`) or if inheritance is sufficient. |
| **PII detected** | A property name matches PII keywords but the class lacks `kairos-ext:gdprClassification`. | Add GDPR annotations or confirm the property is not sensitive. |

---

## Related skills

| When you need | Invoke |
|---|---|
| Design/modify domain ontology classes and properties | **kairos-design-domain** |
| Design silver layer (DDL, SCD, FK annotations) | **kairos-design-silver** |
| Design gold layer (Power BI star schema, measures) | **kairos-design-gold** |
| Map source columns to domain properties | **kairos-design-mapping** |
| Validate ontology syntax + SHACL | **kairos-execute-validate** |
| Consume dbt package in data platform repo | **kairos-package-dataplatform** |
