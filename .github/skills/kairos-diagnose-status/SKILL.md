---
name: kairos-diagnose-status
description: >
  Perform a comprehensive status review of an ontology hub repository.
  Inspects sources, modeling, extensions, mappings, and projection outputs to
  report where the implementation stands and what's missing.
---

# Ontology Hub Status Review Skill

You are performing a **status review** of an ontology hub repository. Your goal is
to inspect the hub structure and produce a clear, actionable report showing where
the implementation stands and what remains to be done.

## Before you start

0. **Locate the hub root** — look for `catalog-v001.xml` or `model/ontologies/`
   to identify the hub root directory. If not found, ask the user for the path.

1. **Quick toolkit check** — run `python -m kairos_ontology update --check` once.
   If outdated, note it in the report but continue.

---

## What to inspect

### 1. Context & Inputs

Check these directories and files:

| What to check | Where | What it tells you |
|---------------|-------|-------------------|
| Source systems | `integration/sources/` | Each sub-folder = one source system. Look for `*.vocabulary.ttl` files with `kairos-bronze:` namespace |
| TMDL / PBIP definitions | `integration/sources/*/` or `integration/tmdl/` | Presence of `.tmdl`, `.tmd`, or `.pbip` files indicates Power BI reverse-engineering input |
| Accelerator / Reference model | `catalog-v001.xml` | Look for `<uri>` entries pointing to external reference models (e.g. `kairos-ref-*`) |
| Hub config | `pyproject.toml` `[tool.kairos]` | Channel, toolkit version pin |

**Commands to run:**
```bash
# Count source systems
ls integration/sources/ 2>/dev/null || echo "No sources directory"

# Check for TMDL files
find integration/ -name "*.tmdl" -o -name "*.tmd" 2>/dev/null | head -5

# Check catalog for reference models
grep -i "kairos-ref\|reference" catalog-v001.xml 2>/dev/null
```

### 2. Domain Modeling

Check `model/ontologies/` for domain TTL files:

| What to check | How |
|---------------|-----|
| Domain count | Count `*.ttl` files in `model/ontologies/` (exclude `_master.ttl`) |
| Per-domain stats | Parse each TTL: count `owl:Class`, `owl:ObjectProperty`, `owl:DatatypeProperty`; read `owl:versionInfo` |
| Accelerator coverage | If a reference model is configured, check which ref-model domains are claimed via `owl:imports` |
| Custom domains | Domains NOT importing a reference model = custom/local |
| Completeness | Does each class have `rdfs:label`, `rdfs:comment`? Do properties have domain/range? |

**Commands to run:**
```bash
# List ontology domains
ls model/ontologies/*.ttl 2>/dev/null | grep -v _master

# Quick class count per domain
for f in model/ontologies/*.ttl; do
  echo "$f: $(grep -c 'a owl:Class' $f) classes"
done
```

**For accelerator analysis:** Read `catalog-v001.xml` to find the reference model
path, then compare which domains the reference model offers vs which ones the hub
has created local ontologies for.

### 3. Projection Configuration

Check `model/extensions/` and `model/mappings/`:

| What to check | Where | Expected |
|---------------|-------|----------|
| Silver extensions | `model/extensions/*-silver-ext.ttl` | One per domain that will project to silver |
| Gold extensions | `model/extensions/*-gold-ext.ttl` | One per domain that will project to gold/Power BI |
| SKOS mappings | `model/mappings/{source}-to-{domain}.ttl` | One mapping file per (source × domain) combination |
| Mapping coverage | Inside mapping TTLs | Check if all source tables have `skos:exactMatch` to domain classes |

**Key questions to answer:**
- Which domains have NO silver extension? (Can't project to dbt silver)
- Which domains have NO gold extension? (Can't project to Power BI gold)
- Which source systems have NO mappings? (Source data can't flow to silver)
- Are there domain × source combinations with no mapping file?

**Commands to run:**
```bash
# List extensions
ls model/extensions/*-silver-ext.ttl 2>/dev/null
ls model/extensions/*-gold-ext.ttl 2>/dev/null

# List mapping files
ls model/mappings/*.ttl  2>/dev/null
```

### 4. dbt / Medallion Status

Check if projections have been run:

| What to check | Where |
|---------------|-------|
| dbt output exists | `output/medallion/dbt/` |
| Silver models generated | `output/medallion/dbt/models/silver/` |
| Gold models generated | `output/medallion/dbt/models/gold/` |
| Last session logs | `.sessions-projection/dbt-*.md` |
| Projection report | `output/projection-report.json` |
| Coverage report | `output/medallion/dbt/coverage-report.json` |

**Commands to run:**
```bash
# Check for recent dbt session logs
ls -t .sessions-projection/dbt-*.md 2>/dev/null | head -5

# Read the most recent one for each domain
for f in $(ls -t .sessions-projection/dbt-*.md 2>/dev/null | head -3); do
  echo "=== $f ==="; head -20 "$f"; echo
done

# Check coverage report
cat output/medallion/dbt/coverage-report.json 2>/dev/null | python -m json.tool | head -30
```

---

## Output Format

Produce a structured Markdown report:

```markdown
# 🏗️ Ontology Hub Status — {hub-name}

**Reviewed:** {date}  
**Toolkit version:** {version}  
**Hub path:** {path}

## 1. Context & Inputs

| Item | Status | Detail |
|------|--------|--------|
| Source systems | ✅ N defined | {list names} |
| TMDL definitions | ✅/❌ | {found or not} |
| Accelerator | ✅/❌ | {name + version, or "None — custom hub"} |

## 2. Domain Modeling

| Domain | Classes | Properties | Version | Type |
|--------|---------|------------|---------|------|
| {name} | N | N | x.y.z | accelerator / custom |

**Summary:** N accelerator domains claimed, N custom domains. N total classes.

## 3. Projection Configuration

| Domain | Silver Ext | Gold Ext | Mappings | Sources Mapped |
|--------|-----------|----------|----------|---------------|
| {name} | ✅/❌ | ✅/❌ | ✅ N/M / ❌ | {source names} |

## 4. dbt Projection Status

| Domain | Last Run | Entities | Skipped | Warnings |
|--------|----------|----------|---------|----------|
| {name} | {date} / Never | N/M | N | N |

## 📋 Recommendations

{Numbered list of actionable next steps, prioritized}
```

---

## Recommendation priorities

When generating recommendations, use this priority order:

1. **Blockers** (❌ can't project without these):
   - Missing source vocabulary files
   - Missing SKOS mappings for domains that need projection
   - Missing silver extensions for domains that need dbt output

2. **Gaps** (⚠️ partial coverage):
   - Domains with incomplete class definitions (missing labels/comments)
   - Source systems with no mapping files
   - Domains without gold extensions (if Power BI is desired)

3. **Improvements** (ℹ️ nice to have):
   - Run projections if output is stale or missing
   - Add TMDL for Power BI reverse-engineering
   - Consider accelerator for uncovered standard domains

---

## Agent instructions

> **IMPORTANT:** This skill is read-only — do NOT modify any hub files.
> Only inspect and report. If the user wants to fix issues, route them to the
> appropriate skill (modeling, hub-setup, medallion-silver, etc.).

> Use `glob` and `view` tools to inspect files. Use `grep` to count patterns.
> Parse TTL files by looking for key patterns (`a owl:Class`, `rdfs:label`, etc.)
> rather than loading them into rdflib (which may not be available in the hub repo).

> On Windows, use PowerShell equivalents:
> - `Get-ChildItem` instead of `ls`/`find`
> - `Select-String` instead of `grep`
> - `Get-Content` instead of `cat`

---

## Skill routing (after review)

Based on the findings, suggest the appropriate next skill:

| Gap found | Recommend |
|-----------|-----------|
| No source vocabularies | **kairos-design-source** |
| Missing domain ontologies | **kairos-design-domain** |
| Missing extensions | **kairos-design-silver** or **kairos-design-gold** |
| Missing mappings | **kairos-design-mapping** |
| Projections not run | **kairos-execute-project** |
| Hub not set up | **kairos-setup-config** |
