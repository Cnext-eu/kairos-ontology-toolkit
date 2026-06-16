---
name: kairos-design-source
description: >
  Expert guide for importing, documenting, and analysing source system data.
  Covers flat-file import, YAML-to-TTL generation, manual bronze vocabulary
  creation, enrichment review, and LLM-powered source-to-domain analysis.
---

# Kairos Source Design Skill

> **🔒 Skill context:** Before running any `kairos-ontology` /
> `python -m kairos_ontology` command in this skill, set the sentinel env var so
> the CLI knows it runs inside a skill and suppresses its skill-gate warning:
> - PowerShell: `$env:KAIROS_SKILL_CONTEXT = "1"`
> - bash/zsh: `export KAIROS_SKILL_CONTEXT=1`

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
- Source data or documentation should be available (CSV/Excel/Parquet files, SQL DDL,
  API specs, or sample data)
- For Phase 4 (analysis): AI provider configured (GITHUB_TOKEN or AZURE_AI_ENDPOINT)

---

## Phase 0 — Determine input type

Ask the user what source material they have:

| Input type | Path |
|---|---|
| **CSV, Excel, or Parquet files** (exports, data dumps) | → Phase 1 (import-flatfile) |
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

> **When to use:** The user has CSV exports, Excel workbooks, Parquet files, or a
> directory of flat files from the source system.
>
> **Note:** Excel support requires the `[flatfile]` extra (openpyxl); Parquet
> support requires the `[parquet]` extra (pyarrow). Install with
> `pip install kairos-ontology-toolkit[flatfile]` /
> `pip install kairos-ontology-toolkit[parquet]` if prompted.

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

**Then unpack the reference models FIRST (required — DD-044/DD-047).** Before the AI
analysis, run the cheap, deterministic, **AI-free** `generate-inventory` so the
reference models are materialized into `referencemodels-unpacked/*-inventory.yaml`:

```bash
kairos-ontology generate-inventory
kairos-ontology check-inventory    # verify the unpacked inventory is present & current
```

> **Why up front:** `generate-inventory` is quick and AI-free, so there's no reason to
> defer it. It gives `analyse-sources` and `propose-alignment` visibility into subclass
> properties (specialization patterns) that raw TTL parsing would miss, **and** it
> satisfies the Step 0c.1b / DD-047 inventory gate that the modeling skill enforces
> later — so unpacking now de-risks that gate instead of hitting it mid-modeling.
> Order: **`generate-inventory` (quick) → `analyse-sources` (the long AI run).**

### 4b — Run the analysis

```bash
kairos-ontology analyse-sources --accelerator logistics
```

**Available options:**

| Option | Default | When to use |
|---|---|---|
| `--accelerator <name>` | none | Classify toward an accelerator pack's **data domains** (party, commercial, ...) with their model URIs — recommended; fast (no owl:imports resolution) |
| `--domains "party,booking"` | all | Focus on specific domains |
| `--model gpt-5.4-mini` | gpt-5.4-mini | LLM model for semantic matching |
| `--max-workers N` | 8 | **Concurrent** per-table LLM calls — the primary speedup on large hubs. Lower to `3-4` on low-TPM Azure deployments; `1` runs serially (old behaviour) |
| `--force` | off | Bypass caching and re-run every table (see 4d) |
| `--max-domains N` | all | Rate limit protection |
| `--shallow` | off | Skip module-class grounding + owl:imports resolution (faster) |
| `--materialize .resolved/` | none | Write the resolved analysis context (manifest + per-domain YAML) for inspection |
| `--verbose` / `--quiet` | off | Per-table progress / suppress progress **and the cost banner** |
| `--threshold` | 0.3 | Deprecated; ignored in table-centric (schema_version 2) analysis |
| `--sources path/` | auto-detect | Override sources directory |
| `--ref-models path/` | auto-detect | Override reference models directory |

Without `--accelerator`, the command falls back to grouping reference-model TTLs
into model-level domains.

> **💸 Cost & speed (DD-065):** `analyse-sources` issues **one paid LLM call per
> source table**, now run **concurrently** (`--max-workers`, default 8). On a large
> hub this is hundreds of calls — the command prints a prominent cost banner before
> running. Keep the AI provider pointed at a cost/value-optimized model
> (**`gpt-5.4-mini`**, the default); avoid frontier models for this bulk task.

### 4d — Caching & re-runs (DD-065)

Re-running `analyse-sources` does **not** re-bill unchanged work:

- A **per-table sidecar cache** under `integration/sources/_analysis/.cache/`
  reuses a table's classification when its columns/samples, model, and candidate
  domains are unchanged (cached tables are marked `(cached)` in verbose output).
- Use `--force` to ignore the cache and re-classify every table (e.g. after
  changing prompt-affecting settings the cache key doesn't capture).
- The `.cache/` directory is regenerable — safe to delete or git-ignore.


### 4c — Review affinity reports

The command produces `{system}-affinity.yaml` files in
`integration/sources/_analysis/`. Each report is **table-centric** (`schema_version: 2`):

- **`tables`** — one entry per source table, each assigned to exactly ONE primary
  data domain
- **`domain`** + **`domain_uris`** — the table's primary data-domain id and the
  reference-model module URI(s) to `owl:imports` (data-domain-first mode)
- **`secondary_domains`** — up to two additional domains the table also feeds
- **`confidence`** — how strongly the table belongs to its primary domain
- **`likely_entity`** — the business entity / reference model class the table most
  likely maps to
- **`indicative_columns`** — key columns that signal domain membership
- **`rationale`** — natural language explanation of the primary choice
- **`domain_summary`** — a rollup grouping tables by primary domain (with `table_count`)

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

> **Optional (DD-045):** Before mapping, you can run
> `kairos-ontology propose-alignment --include-mapping-hints` to enrich the
> alignment YAML with advisory **transform** and **structural** mapping hints.
> The **kairos-design-mapping** skill consumes these for a richer starting point
> while still confirming every non-trivial transform with you. Without the flag,
> the default alignment output (used by **kairos-design-domain** pre-modeling) is
> unchanged. See `docs/instruction-guides/context-engineer-methodology-guide.md`.

### Derive candidate claims (`derive-claims`)

> **When to use:** after `analyse-sources` (Phase 4) **and** `propose-alignment`
> have run, and **before** human curation/approval of claims. This step sits
> between evidence production and approval — it never replaces human review.

`derive-claims` is a **deterministic, AI-free** command that aggregates all the
evidence you have already produced into `proposed` candidate claims in
`model/claims/{domain}-claims.yaml`, so you curate rather than hand-author. The
hard interpretation already happened upstream (`analyse-sources` affinity and
`propose-alignment` column→property — the latter already writes the claims file);
`derive-claims` is the deterministic merge/enrich layer. It joins **five evidence
streams** deterministically on `(system, table[, column])` and ref_class/
ref_property names:

1. **Existing claims registry** — base candidates + any human curation (preserved).
2. **`analyse-sources` affinity** (`integration/sources/_analysis/*-affinity.yaml`)
   — table→domain routing; corroborates class claims and creates new `proposed`
   candidates for affinity tables that have no alignment anchor yet.
3. **`import-tmdl` concept-mapping** (`integration/sources/powerbi/*-concept-mapping.yaml`)
   — corroborates matching class claims; `new_class` actions become `proposed`
   gap candidates when a single domain is processed.
4. **SKOS mappings** (`model/mappings/*.ttl`) — `skos:*Match` links attached as
   `skos_mapping` evidence.
5. **Sample-derived signals** — enum-candidate / FK-shape signals attached as
   `sample_signal` evidence.

Each claim can carry **multiple `evidence_sources`**, keeping strong (anchored
alignment) vs weak (affinity-only) evidence distinguishable.

```bash
kairos-ontology derive-claims --domains client,invoice --max-workers 8
```

Key flags: `--claims-dir`, `--analysis-dir`, `--sources`, `--mappings`,
`--tmdl-dir`, `--domains` (comma-separated filter), `--max-workers` (default 8;
`1` = serial), `--force` (bypass the sidecar cache), `--quiet`. Path defaults
auto-resolve via the hub root.

> **Never auto-approves (C4 guard).** All derived/new claims are
> `status: proposed` — probabilistic evidence must never masquerade as approval.
> Human decisions survive re-runs (`merge_preserving_decisions`), and conflicting
> evidence is surfaced, not silently resolved. There is **no cost banner** because
> nothing is billed (no LLM calls). A future opt-in `--llm-reconcile` flag (LLM
> tie-breaking / rationale synthesis, with a cost banner) is deferred.

→ Curate the proposed claims, then approve them (gated by `check-claims`).

### Claim governance gates (`check-claims`) — MDM / ownership (Slice 4)

`check-claims` is the single deterministic governance gate for the registry. Beyond
coverage/sync, it enforces four MDM/reference-data + ownership rules over the
**curated** registry fields, so set these as you curate:

- **`reference_data`** (`authority_system` / `code_system` / `key` / `scd_type`) +
  **`mdm_anchor: true`** mark a claim as a reference/master anchor (conformed
  dimension, code list, natural key). The **MDM-anchor gate** blocks broad domain
  claims (approved class claims with disposition claim/specialize) with
  `anchor_pending` when declared anchors are still `proposed`, and warns
  `anchor_missing` (pragmatic — anchors must be *known*, not fully built) when a
  domain with broad claims declares no anchors at all.
- **`deviation`** (`reason` / `owner` / `gap_request`) records a client-native
  decision; the **deviation-log** check blocks approved `gap` claims that lack an
  owner + reason with `deviation_missing`.
- **`ownership_override`** (`owner` / `rationale`) is the explicit escape hatch when
  a claim crosses another data-domain's `data-domains.yaml` boundary or is a shared
  conformed dimension. Without it, a cross-boundary approved claim blocks with
  `ownership_conflicts`; with it, a cross-file same-URI duplicate downgrades from the
  `duplicate_approved` block to a `shared_dimensions` warning.
- **`passthrough_reviewed: true`** clears the **passthrough-review** warning
  (`passthrough_review`) raised on high-use passthrough fields (multi-source, or used
  in powerbi measures/slicers/filters/hierarchies/joins/fks, or carrying a `measure`).

Use `check-claims --no-mdm-anchor` / `--no-ownership` to skip those gates for hubs
not yet doing MDM governance. These are governance fields in the YAML registry, not
kairos-ext TTL annotations.

### Change management for a new/changed source (`source-delta-report`)

> **When to use:** when **adding a new source system** or **refreshing an existing
> one** (Phase 0 → "Existing vocabulary TTL" or a brand-new system) — before any
> projection change merges. Core invariant (methodology §13): *new evidence may
> expand silver, but must not silently mutate existing silver.*

`source-delta-report` is an **advisory, deterministic, AI-free** command that compares
a source system's bronze vocabulary against the approved Claim Registry + SKOS mappings
(plus optional affinity hints and an optional baseline vocabulary diff), classifies each
candidate delta (§13.2), emits a markdown impact report (§13.4), and suggests a
silver/gold contract version bump (§13.5) with backward-compatibility tactics (§13.6).
Like `import-tmdl` / `coverage-report` / `pbi-source-fit-gap`, it is **exempt from the
skill soft-gate** and never mutates governed artifacts.

```bash
kairos-ontology source-delta-report --system acme_crm --domain client \
  [--baseline integration/sources/acme_crm/acme_crm.vocabulary.prev.ttl] \
  [--analysis-dir integration/sources/_analysis] \
  [--output integration/reports/acme_crm-source-delta.md] [--fail-on-breaking]
```

Each delta maps deterministically to an impact class and a version bump:
`maps-to-existing-class` / `new-column-to-property` → mapping-only → **patch**;
`new-claim-candidate` / `passthrough-candidate` / `new-reference-list` /
`new-relationship` / backward-compatible `changed-type` widening → additive →
**minor**; `semantic-conflict` / non-widening `changed-type` / `changed-key` /
`changed-grain` / `removed-column` → breaking → **major**. The suggested bump is the
highest-precedence class present (breaking → additive → mapping-only → none). The
current contract version is read from the registry's optional top-level `contract:`
block (`silver_version` / `gold_version`); use `--fail-on-breaking` in CI to block
silent breaking changes. See DD-EL-8 and methodology §13. **Projector emission of the
contract version is deferred** — the version lives in the registry and is suggested by
this report.

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

> **Starting fresh — archive, don't overwrite (DD-071).** When the user chooses to
> start a new session instead of resuming, first move any existing
> `.sessions-design/source-{system-name}-*.md` log(s) for this source system into
> `ontology-hub/.sessions-design/_archive/` (create it if missing; keep the
> original filename). Never delete a previous log. Then create the new session log.
> This applies only to the interactive `.sessions-design/source-*.md` log, not the
> separate `.sessions-design-import/` audit logs.

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

### Automatic import audit log

In addition to this interactive session file, the `import-flatfile` and
`import-source` CLI commands **automatically** write a machine-generated
import-results file to a separate folder:

```
ontology-hub/.sessions-design-import/
  └── import-{system-name}-{YYYY-MM-DD}.md
```

This audit file records what each import run produced (tables, columns, change
report, enrichment) using a template consistent with the session files above.
It is written best-effort whenever a command runs inside a detected hub, and is
distinct from the interactive `.sessions-design/source-*.md` session file you
maintain.

---

## Related skills

| When you need | Invoke |
|---|---|
| Explore company context / capture business terminology first | **kairos-design-discovery** |
| Design/modify domain ontology classes and properties | **kairos-design-domain** |
| Design silver layer (DDL, SCD, FK annotations) | **kairos-design-silver** |
| Design gold layer (Power BI star schema, measures) | **kairos-design-gold** |
| Map source columns to domain properties | **kairos-design-mapping** |
| Run projections after source vocab is complete | **kairos-execute-project** |
