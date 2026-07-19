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

## Objective status comes from the deterministic scanner (DD-080)

> **Run `kairos-ontology status` first — it is the authoritative objective layer.**
> Do **not** hand-derive per-phase completion by ad-hoc reasoning; that is exactly
> what the deterministic scanner exists to prevent.

```bash
kairos-ontology status              # human summary
kairos-ontology status --format json   # machine-readable, per-phase/per-instance
```

The scanner reports, deterministically and AI-free, a `not-started | in-progress |
done` state for every lifecycle phase (`discovery, source, domain, mapping, claims,
silver, gold, validate, project`) and its instances. Use this as the backbone of
your report; the deep-dive sections below only **explain and enrich** that result
(quality of vocabularies, reference-model strategy, version drift, etc.).

> **For "start / where are we / continue / resume", use the `kairos-flow` skill**
> instead — it owns the `.kairos-state/` continuation state (open questions,
> decisions, intent) and routes to the right phase skill. This status-review skill
> is for a detailed *read-only diagnostic*, not for driving the lifecycle.


## Before you start

0. **Locate the hub root** — look for `catalog-v001.xml` or `model/ontologies/`
   to identify the hub root directory. If not found, ask the user for the path.

1. **Quick toolkit check** — run `python -m kairos_ontology update --check` once.
   If outdated, note it in the report but continue.

2. **Ignore archived session logs (DD-071)** — when listing or grepping
   `.kairos-state` or `.sessions-projection` for the last/most-recent session
   log, do not descend into the `_archive/` subfolder. Archived logs are
   historical and must be ignored when determining current progress.

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

#### Source onboarding completeness

For **each** source system folder in `integration/sources/` (exclude `_analysis/`),
check which onboarding phases have been completed:

| Phase | Artifact to check | Status |
|-------|--------------------|--------|
| Phase 1 — Flat-file import | `_manifest.yaml` + `*.yaml` schema files (not `.samples.yaml`) | ✅ if present, ⏭️ if skipped (manual/DDL source) |
| Phase 2 — Vocabulary generated | `{system}.vocabulary.ttl` exists | ✅/❌ |
| Phase 2 — Vocabulary quality | TTL contains `kairos-bronze:SourceSystem`, `kairos-bronze:SourceTable`, `kairos-bronze:SourceColumn` declarations | ✅/❌ |
| Phase 2 — Table coverage | Count of `SourceTable` instances vs schema YAML files (if Phase 1 was used) | N tables / M schemas |
| Phase 2 — Column completeness | Every `SourceColumn` has `kairos-bronze:dataType` and `kairos-bronze:columnName` | ✅/❌ |
| Phase 4 — Source analysis | `_analysis/{system}-affinity.yaml` exists | ✅/❌ |

**How to check vocabulary quality:**
1. For each source folder, parse the `*.vocabulary.ttl` file.
2. Count `kairos-bronze:SourceTable` entries — each should represent one table.
3. Count `kairos-bronze:SourceColumn` entries — each should have `dataType` and `columnName`.
4. Flag sources with 0 tables or 0 columns as **❌ Empty vocabulary**.
5. Flag columns missing `dataType` as **⚠️ Incomplete vocabulary**.

**How to check analysis status:**
1. List files in `integration/sources/_analysis/` (if it exists).
2. For each source system, check if `{system}-affinity.yaml` exists.
3. Sources without an affinity report have not been analyzed (Phase 4 not run).

**Commands to run:**
```bash
# Count source systems
ls integration/sources/ 2>/dev/null || echo "No sources directory"

# Per-source vocabulary check
for d in integration/sources/*/; do
  name=$(basename "$d")
  [ "$name" = "_analysis" ] && continue
  vocab=$(ls "$d"*.vocabulary.ttl 2>/dev/null | head -1)
  if [ -n "$vocab" ]; then
    tables=$(grep -c 'kairos-bronze:SourceTable' "$vocab" 2>/dev/null || echo 0)
    cols=$(grep -c 'kairos-bronze:SourceColumn' "$vocab" 2>/dev/null || echo 0)
    echo "$name: ✅ vocabulary ($tables tables, $cols columns)"
  else
    echo "$name: ❌ NO vocabulary.ttl"
  fi
done

# Check analysis reports
ls integration/sources/_analysis/*-affinity.yaml 2>/dev/null || echo "No analysis reports — Phase 4 not run"

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
| Coverage report | `output/reports/coverage-silver-*.md` or `.json` (most recent) |

#### Version drift detection

Compare the toolkit version that **generated** the current projection output
against the **currently installed** toolkit version. A mismatch means the output
may be stale and should be re-projected.

**How to detect:**
1. Read `output/projection-report.json` → extract `toolkit_version` field.
2. Run `kairos-ontology --version` (or `python -m kairos_ontology --version`) to
   get the currently installed version.
3. If they differ, flag the drift in the report:
   > ⚠️ Projection was run with toolkit **vX.Y.Z** but current installed version
   > is **vA.B.C** — output may be stale. Consider re-running projections.

**Commands to run:**
```bash
# Check for recent dbt session logs
ls -t .sessions-projection/dbt-*.md 2>/dev/null | head -5

# Read the most recent one for each domain
for f in $(ls -t .sessions-projection/dbt-*.md 2>/dev/null | head -3); do
  echo "=== $f ==="; head -20 "$f"; echo
done

# Check projection report for toolkit version used
python -c "
import json, pathlib
p = pathlib.Path('output/projection-report.json')
if p.exists():
    data = json.loads(p.read_text())
    print(f'Projection toolkit version: {data.get(\"toolkit_version\", \"unknown\")}')
    print(f'Generated at: {data.get(\"generated_at\", \"unknown\")}')
else:
    print('No projection-report.json found')
"

# Compare with installed version
kairos-ontology --version 2>/dev/null || python -m kairos_ontology --version

# Check coverage report
cat output/medallion/dbt/coverage-report.json 2>/dev/null | python -m json.tool | head -30
```

### 5. Reference Model Strategy

Determine which reference model alignment strategy each domain uses (see DD-032).

| Strategy | How to detect |
|----------|---------------|
| **Reference Model Enforced** | The domain ontology contains `owl:imports` pointing to an **external** reference model namespace (e.g., `https://refmodel.example/...`, `https://referencemodels.kairos.cnext.eu/...`). Ignore imports between hub-internal domains (same hub namespace). |
| **Reference Model Inspired** | One or more `owl:Class` definitions in the domain ontology have `rdfs:seeAlso` pointing to an external reference model URI. No `owl:imports` of that reference model. |
| **Pure Local** | No `owl:imports` of external reference models AND no `rdfs:seeAlso` back-references to external reference model URIs. |

**Steps:**
1. For each domain TTL file in `model/ontologies/`:
   a. Check for `owl:imports` statements — filter out hub-internal imports (same base namespace).
      Any remaining external imports indicate **Enforced**.
   b. If no external imports, check for `rdfs:seeAlso` on class definitions.
      If found with external URIs, the domain is **Inspired**.
   c. If neither, the domain is **Pure Local**.
2. For Enforced domains, note which reference model(s) are imported.
3. For Inspired domains, note which reference model(s) are referenced via `rdfs:seeAlso`.

**Commands to run:**
```bash
# Check for owl:imports per domain (external reference models)
for f in model/ontologies/*.ttl; do
  echo "=== $f ==="
  grep "owl:imports" "$f" 2>/dev/null || echo "(none)"
done

# Check for rdfs:seeAlso back-references on classes
for f in model/ontologies/*.ttl; do
  echo "=== $f ==="
  grep "rdfs:seeAlso" "$f" 2>/dev/null || echo "(none)"
done
```

### 6. Coverage Summary

If coverage artifacts have been generated (by running projections or the
`coverage-report` CLI), read them and surface key metrics. Do NOT regenerate
coverage data — only report what already exists.

> ⚠️ **Staleness check:** Before reporting coverage numbers, compare the
> `toolkit_version` in the projection report (Section 4) with the currently
> installed version. If they differ, add a **⚠️ Coverage data may be stale**
> banner and recommend re-running projections before trusting the numbers.

| What to check | Where | What it tells you |
|---------------|-------|-------------------|
| Domain coverage (silver NULL columns) | `output/reports/coverage-silver-*.md` or `.json` (most recent) | Per-entity: total properties, populated from source, always-NULL columns, missing required mappings |
| Industry alignment (ontology vs ref model) | `output/reports/coverage-industry-*.yaml` or `output/reports/coverage-industry-*.md` (most recent) | Per-domain: class/property alignment % against reference models, custom vs aligned fields. Generated by `kairos-ontology coverage-report`. |
| Source mapping reports | `output/reports/details/*-mapping-report-*.html` | Per-source-system: mapped vs unmapped columns, match types, action items |

**Steps:**
1. Check if `output/reports/coverage-silver-*.md` (or `.json`) exists. If so, use the most recent:
   a. Read the `summary` section for overall stats (populated_pct, missing_required).
   b. Per domain in `domains`, identify entities with high `always_null` counts.
   c. Flag entities with `missing_required_mappings` > 0 as blockers.
2. Check if `output/reports/coverage-industry-*.yaml` or `output/reports/coverage-industry-*.md` exists
   (industry alignment). If so, use the most recent:
   a. Read `class_coverage_pct` and `property_coverage_pct` per domain.
   b. Identify domains with low alignment (< 50%) — these have many custom fields.
3. Check if `output/reports/details/` contains `*-mapping-report-*.html` files. Count them.
4. If none of these artifacts exist, note that projections/coverage have not been run.

**Commands to run:**
```bash
# Check for coverage artifacts (most recent of each type)
ls -t output/reports/coverage-silver-*.md output/reports/coverage-silver-*.json 2>/dev/null | head -1
ls -t output/reports/coverage-industry-*.yaml output/reports/coverage-industry-*.md 2>/dev/null | head -1
ls output/reports/details/*-mapping-report-*.html 2>/dev/null | wc -l

# Read dbt coverage summary (most recent file)
python -c "
import json, pathlib
files = sorted(pathlib.Path('output/reports').glob('coverage-silver-*.json'))
if files:
    data = json.loads(files[-1].read_text())
    print(f'File: {files[-1].name}')
    print(json.dumps(data.get('summary', {}), indent=2))
else:
    print('No dbt coverage report found')
" 2>/dev/null
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

### Source Onboarding Status

| Source | Vocabulary | Tables | Columns | Data Types | Analysis |
|--------|-----------|--------|---------|------------|----------|
| {name} | ✅/❌ | N | N | ✅ all / ⚠️ N missing | ✅/❌ |

> {If any source has ❌ Vocabulary: "⚠️ Source {name} has no vocabulary — run
> **kairos-design-source** to onboard."}
> {If any source has ❌ Analysis: "ℹ️ Source analysis not run for {names} — run
> `kairos-ontology analyse-sources` or **kairos-design-source** Phase 4."}

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

> ⚠️/✅ Projection was run with toolkit **v{projection_version}** — current installed
> version is **v{installed_version}**. {If different: "Output may be stale — consider
> re-running projections." If same: "Versions match — output is current."}

### Aspirational stub vs bound (DD-096)

When distinguishing whether a Silver entity is a real (bound) model or an
**aspirational stub** (approved claim, no bronze mapping yet), classify over the
**authorities** (Claim Registry + mappings + sources via `BindingAnalysis`), **not** by
reading generated `meta.is_aspirational` — that marker is absent when
`--emit-aspirational-stubs` is off or when output is stale. Report each eligible entity
as **bound** / **stub (aspirational, pending binding)** / **release-eligible**. A stub
is *not* release-eligible merely by existing; surface stubs as open items to bind
(→ kairos-design-mapping), not as `done`.

| Domain | Entity | State | Blocks release? |
|--------|--------|-------|-----------------|
| {name} | {Class} | bound / stub / skipped | yes (unbound stub) / no |

## 5. Reference Model Strategy

| Domain | Strategy | Reference Model(s) | Detail |
|--------|----------|---------------------|--------|
| {name} | Enforced / Inspired / Pure Local | {ref model name or "—"} | {e.g., "owl:imports party ref model" or "rdfs:seeAlso → FIBO Identifier" or "No reference model"} |

**Summary:** N domains Enforced, N domains Inspired, N domains Pure Local.

## 6. Coverage Summary

> {If versions differ: "⚠️ **Coverage data may be stale** — projections were run with
> toolkit v{X} but current version is v{Y}. Re-run projections to refresh coverage."
> If versions match or no projection-report.json: omit this banner.}

| Domain | Silver Populated % | Always-NULL Columns | Missing Required | Industry Alignment % |
|--------|--------------------|---------------------|------------------|----------------------|
| {name} | N% | N | N | N% or "Not run" |

**Overall:** N% silver properties populated across all domains. N missing required mappings.
**Industry alignment:** N% class coverage, N% property coverage (or "Not run").
**Mapping reports:** N source report(s) available in output/reports/details/.

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
   - Vocabulary columns missing `dataType` (incomplete onboarding)
   - Source analysis not run (no `_analysis/*-affinity.yaml`)

3. **Improvements** (ℹ️ nice to have):
   - Run projections if output is stale or missing
   - Add TMDL for Power BI reverse-engineering
   - Consider accelerator for uncovered standard domains
   - Run source analysis for better domain affinity insights

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
| Incomplete vocabulary (missing dataType, 0 columns) | **kairos-design-source** (Phase 2/3 — re-run import or fix manually) |
| Source analysis not run | **kairos-design-source** (Phase 4 — `analyse-sources`) |
| Missing domain ontologies | **kairos-design-domain** |
| Missing extensions | **kairos-design-silver** or **kairos-design-gold** |
| Missing mappings | **kairos-design-mapping** |
| Projections not run | **kairos-execute-project** |
| Coverage artifacts missing or stale | **kairos-execute-project** (re-run projections) or CLI: `kairos-ontology coverage-report` |
| Low industry alignment (many custom fields) | **kairos-design-domain** (consider reference model patterns) |
| Hub not set up | **kairos-setup-config** |
| Want to switch strategy (Enforced ↔ Inspired) | **kairos-design-domain** (see DD-032 migration paths) |

---

## Follow-up recommendation (MANDATORY)

After presenting the status report, **always** ask the user:

> 🔍 Want a deeper quality check? I can run a **detailed validation** (all 4 levels:
> syntax, SHACL, modeling best practices, and extension/mapping correctness) to catch
> issues that the status review doesn't cover.
>
> → Invoke **kairos-execute-validate** in **Detailed** mode (Level 4)

If the user accepts, invoke the `kairos-execute-validate` skill and instruct it to
run in **Detailed** mode (all 4 levels).

---

## Report persistence (MANDATORY)

After displaying the report in chat, **always** save it as a Markdown file:

- **Path:** `output/reports/hub-diagnose-{YYYY-MM-DD-HHmmss}.md` (relative to the hub root).
  Use the current UTC timestamp for `{YYYY-MM-DD-HHmmss}` (e.g. `hub-diagnose-2026-06-10-205500.md`).
- **Content:** The full rendered report (all 6 sections + Recommendations) exactly
  as displayed in chat. Do NOT include the follow-up prompt in the saved file.
- **History:** Each run creates a new file — previous reports are preserved for
  comparison and audit trail.
- **Git:** Do NOT commit the file automatically. The user decides when to commit.

**Steps:**
1. After assembling the full report, write it to `output/reports/hub-diagnose-{ts}.md` using
   the `create` or `edit` tool (or `echo` / `Set-Content` if the tool isn't available).
2. Tell the user: "📄 Report saved to `output/reports/hub-diagnose-{ts}.md`."
