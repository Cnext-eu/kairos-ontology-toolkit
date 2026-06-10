---
name: kairos-execute-report
description: >
  Generate advanced HTML mapping reports showing how source systems map to
  the domain ontology. Combines source-centric and entity-centric views with
  data flow diagrams, transform expressions, coverage dashboards, and action items.
---

# Mapping Report Skill

You help users generate and review functional mapping reports that show how
source system concepts align with the domain ontology.

## Before you start

0. **Quick toolkit version check** — run `python -m kairos_ontology update --check` once
   at the start of the session.  If it reports outdated files, run
   `python -m kairos_ontology update` and commit the refresh before doing any other work.
   See the kairos-toolkit-ops skill for full upgrade steps.

## What this report is

The mapping report is an **advanced, business-level** HTML document combining
two complementary perspectives:

### Source-centric view (organized by source table)

- **Table-to-entity mappings** — which source tables map to which domain ontology classes
- **Column-to-property mappings** — source columns → ontology properties with transform details
- **SKOS match types** — color-coded semantic alignment badges
- **Coverage bars** — per-table and overall source coverage

### Entity-centric view (organized by target domain entity)

- **Domain entity sections** — collapsible, grouped by target ontology class
- **Domain badges** — shows which ontology domain each property belongs to
- **Transform expressions** — `kairos-map:transform` SQL expressions displayed inline
- **Filter conditions** — `kairos-map:filterCondition` type discriminators
- **Source table associations** — which source tables feed each entity, with mapping type

### Dashboards and summaries

- **Data flow overview** — visual diagram: Source → Bronze → Mapping → Silver
- **Executive summary** — stat cards for tables, columns, source coverage %, domain coverage %
- **Match type distribution** — color bars showing exact/close/narrow/broad/related/unmapped counts
- **Table-to-entity overview** — compact summary of all source→entity relationships
- **Out-of-scope tables** — source tables with no mappings
- **Uncovered domain properties** — ontology properties not reached by any source mapping
- **Action items** — errors, warnings, and info items with severity counts

## kairos-map: annotations

The report extracts these annotations from mapping TTL files when present:

| Annotation | Purpose | Example |
|-----------|---------|---------|
| `kairos-map:transform` | SQL transform expression | `TRIM(source.name)` |
| `kairos-map:filterCondition` | Row filter / type discriminator | `source.type = 1` |
| `kairos-map:mappingType` | Mapping pattern | `direct`, `split`, `merge`, `pivot`, `lookup` |
| `kairos-map:sourceColumns` | Multi-column source | `first_name last_name` |
| `kairos-map:defaultValue` | Default when NULL | `'Unknown'` |
| `kairos-map:deduplicationKey` | ROW_NUMBER partition | `source.relation_id` |
| `kairos-map:deduplicationOrder` | ROW_NUMBER order | `source.modified_date DESC` |

If no `kairos-map:` annotations are present, the report still works — transform
columns show "—" and the report degrades gracefully to the basic SKOS view.

## Prerequisites

Before generating a report, ensure:

1. **Source vocabulary exists** — `integration/sources/{system}/*.vocabulary.ttl`
   describes the source system's tables and columns using `kairos-bronze:` vocabulary.

2. **Domain ontology exists** — `model/ontologies/{domain}.ttl` defines the target
   classes and properties.

3. **SKOS mappings exist** — `model/mappings/{system}-to-{domain}.ttl` contains SKOS alignment
   between source column/table URIs and domain ontology URIs.

4. **kairos-map: annotations** (optional) — enrich mappings with transform expressions,
   filter conditions, and mapping types for richer reports.

## Generating the report

```bash
# Generate reports for all source systems
kairos-ontology project --target report

# Or generate all projections including reports
kairos-ontology project --target all
```

Output goes to: `output/reports/details/{system}-mapping-report-{YYYY-MM-DD-HHmmss}.html`

## Understanding the report

### Report sections

1. **Header** — source system name, database, schema, connection type
2. **Data Flow Overview** — visual pipeline: Source System → Bronze Layer → SKOS Mapping → Silver Layer
3. **Executive Summary** — four stat cards with key metrics
4. **Match Type Distribution** — color-coded bars showing mapping quality breakdown
5. **Table-to-Entity Overview** — compact table of all source→entity relationships
6. **Domain Entity Details** — collapsible sections per target entity with column mappings
7. **Source Table Details** — collapsible sections per source table with column details
8. **Out-of-Scope Tables** — tables intentionally excluded from mapping
9. **Uncovered Domain Properties** — ontology properties not yet mapped
10. **Action Items** — prioritized list with error/warning/info counts

### Match type color coding

| Badge | SKOS Type | Meaning |
|-------|-----------|---------|
| 🟢 Exact | `skos:exactMatch` | Source concept is semantically identical to domain property |
| 🟡 Close | `skos:closeMatch` | Very similar but not identical — may need transformation |
| 🟠 Narrow | `skos:narrowMatch` | Source concept is more specific than domain property |
| 🟠 Broad | `skos:broadMatch` | Source concept is broader than domain property |
| 🔴 Related | `skos:relatedMatch` | Loosely related — needs careful review |
| ⚪ Unmapped | (none) | No mapping defined yet |

### Coverage metrics

- **Source coverage** — % of source columns that have at least one SKOS mapping
- **Domain coverage** — % of domain ontology properties covered by at least one source column
- **Per-entity coverage** — % of properties covered for each target entity (shown in entity sections)

### Action items

Sorted by severity:
1. **Errors** — unmapped tables, missing critical mappings
2. **Warnings** — close matches that may need business validation
3. **Info** — unmapped columns that may be intentionally excluded

## When to regenerate

Run the report after:
- Adding or modifying SKOS mappings in `model/mappings/`
- Adding `kairos-map:` annotations (transforms, filters) to mapping files
- Adding new source tables/columns to vocabulary files
- Updating domain ontology classes or properties
- Before business review meetings to get current coverage status

## Workflow with other skills

1. **kairos-design-domain** — defines the domain ontology (report target)
2. **kairos-design-source** — creates source vocabulary (report source)
3. **kairos-design-mapping** — guides interactive mapping creation with checkpoints
4. **kairos-execute-report** — generates coverage report (this skill)
5. **kairos-design-silver** — uses mappings for dbt transforms (technical layer)

The mapping report helps identify gaps *before* investing in dbt transform work.
