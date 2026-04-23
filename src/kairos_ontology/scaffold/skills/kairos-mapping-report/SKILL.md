---
name: kairos-mapping-report
description: >
  Generate HTML mapping reports showing how source systems map to the domain
  ontology. For business analysts — shows SKOS match types, coverage, and
  action items. No dbt/SQL transforms.
---

# Mapping Report Skill

You help users generate and review functional mapping reports that show how
source system concepts align with the domain ontology.

## Before you start

0. **Quick toolkit version check** — run `python -m kairos_ontology update --check` once
   at the start of the session.  If it reports outdated files, run
   `python -m kairos_ontology update` and commit the refresh before doing any other work.
   See the kairos-toolkit-update skill for full upgrade steps.

## What this report is

The mapping report is a **business-level** HTML document showing:

- **Table-to-entity mappings** — which source tables map to which domain ontology classes
- **Column-to-property mappings** — which source columns map to which ontology properties
- **SKOS match types** — color-coded semantic alignment (exact, close, narrow, broad, related)
- **Coverage dashboard** — percentage of source columns mapped and domain properties covered
- **Action items** — unmapped columns, non-exact matches needing review, missing table mappings

It does **NOT** show dbt transforms, SQL, or technical medallion details.

## Prerequisites

Before generating a report, ensure:

1. **Source vocabulary exists** — `integration/sources/{system}/*.vocabulary.ttl`
   describes the source system's tables and columns using `kairos-bronze:` vocabulary.

2. **Domain ontology exists** — `model/ontologies/{domain}.ttl` defines the target
   classes and properties.

3. **SKOS mappings exist** — `model/mappings/{system}/*.ttl` contains SKOS alignment
   between source column/table URIs and domain ontology URIs.

## Generating the report

```bash
# Generate reports for all source systems
kairos-ontology project --target report

# Or generate all projections including reports
kairos-ontology project --target all
```

Output goes to: `output/report/{system}-mapping-report.html`

## Understanding the report

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

### Action items

Sorted by severity:
1. **Errors** — unmapped tables, missing critical mappings
2. **Warnings** — close matches that may need business validation
3. **Info** — unmapped columns that may be intentionally excluded

## When to regenerate

Run the report after:
- Adding or modifying SKOS mappings in `model/mappings/{system}/`
- Adding new source tables/columns to vocabulary files
- Updating domain ontology classes or properties
- Before business review meetings to get current coverage status

## Workflow with other skills

1. **kairos-ontology-modeling** — defines the domain ontology (report target)
2. **kairos-medallion-staging** — creates source vocabulary (report source)
3. **kairos-mapping-report** — generates coverage report (this skill)
4. **kairos-medallion-projection** — uses mappings for dbt transforms (technical layer)

The mapping report helps identify gaps *before* investing in dbt transform work.
