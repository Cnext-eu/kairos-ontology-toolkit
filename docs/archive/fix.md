# Toolkit Scaffold Fixes — Dataplatform

Issues discovered during first-time setup of a freshly scaffolded dataplatform repo.

## 1. Profile name mismatch

**Problem:** `dbt_project.yml` uses `name: 'bofidi_dataplatform'` but has no
explicit `profile:` key. dbt infers the profile name from `name`, but
`dbt run-operation` fails to resolve it without an explicit `profile:` field.
`dbt debug` works fine — only `run-operation` (and likely `run`, `build`) fails.

**Fix:** The scaffold should include an explicit `profile:` key in `dbt_project.yml`:
```yaml
name: 'bofidi_dataplatform'
profile: 'bofidi_dataplatform'
```

---

## 2. Empty `tables:` in `_sources.yml` causes parse crash

**Problem:** Scaffolded sources with no tables use bare `tables:` (YAML null),
which causes a `TypeError: 'NoneType' object is not iterable` during `dbt parse`.

```yaml
# This crashes:
tables:

# This works:
tables: []
```

**Fix:** Scaffold should emit `tables: []` for sources with no tables defined.

---

## 3. Cannot introspect warehouse when `packages.yml` references unreleased tag

**Problem:** `packages.yml` pins to a hub release (e.g., `v0.0.1`) that doesn't
exist yet. Running any dbt command (including `run-operation` for introspection)
fails with:

```
Error checking out spec='v0.0.1' ... fatal: couldn't find remote ref v0.0.1
```

This blocks the entire introspection workflow on a fresh setup where the hub
hasn't published its first release yet.

**Fix options:**
1. Scaffold `packages.yml` with the package commented out by default, with a
   note to uncomment once the first hub release is available.
2. Add a `run_query_print` helper macro so users can introspect without needing
   `dbt deps` to succeed first (or document a workaround).
3. The `kairos-develop-dataplatform` skill should detect this situation and
   temporarily comment out `packages.yml` before introspecting, then restore it.

---

## 4. No `run_query` macro available out of the box

**Problem:** The skill documentation references `dbt run-operation run_query` for
ad-hoc schema discovery, but no such macro exists in the scaffold. Only
`extract_source_schema` is provided (which requires sources to be fully declared).

**Fix:** Include a lightweight `run_query_print` macro in the scaffold:
```sql
{% macro run_query_print(sql) %}
    {% set results = run_query(sql) %}
    {% if execute %}
        {% for row in results.rows %}
            {{ print(row.values() | join(' | ')) }}
        {% endfor %}
    {% endif %}
{% endmacro %}
```

---

## 5. Placeholder values in `_sources.yml` don't match actual warehouse

**Problem:** Scaffolded `_sources.yml` uses `database: "your_bronze_database"`
and `schema: "raw_adminpulse"`, plus lists tables that may not exist yet in the
warehouse. This is expected for a template, but the introspection workflow should
update these values automatically.

**Fix:** The `kairos-develop-dataplatform` skill's introspection flow should
overwrite placeholder values with discovered database/schema/tables rather than
expecting the user to manually edit first.

---

## 6. `import-source` writes to wrong repo (CWD-relative output)

**Problem:** The `kairos-develop-dataplatform` skill (Step 5) tells users to run
`kairos-ontology import-source --from extracted/adminpulse/` from the dataplatform
repo. The command defaults `--output` to `integration/sources/{system}/` relative
to CWD, which creates an `integration/` folder in the **dataplatform** root instead
of the **ontology-hub** repo where it belongs.

In a typical workspace:
```
C:\code\
├── bofidi-dataplatform/          ← CWD (dataplatform)
│   └── integration/              ← ❌ WRONG — created here by accident
└── pkf-bofidi-ontology-hub/
    └── ontology-hub/
        └── integration/sources/  ← ✅ CORRECT — should go here
```

**Fix options:**
1. The skill should instruct users to pass explicit `--output`:
   ```bash
   kairos-ontology import-source \
     --from extracted/adminpulse/ \
     --output ../pkf-bofidi-ontology-hub/ontology-hub/integration/sources/adminpulse
   ```
2. OR instruct users to `cd` into the ontology-hub repo before running import.
3. The skill should detect if it's running from a dataplatform repo (presence of
   `dbt_project.yml` + absence of `catalog-v001.xml`) and warn/prompt for the
   correct output path.

**Format clarification (for documentation):**
- `extracted/<system>/*.yaml` → stays in **dataplatform** (human-readable, re-runnable)
- `integration/sources/<system>/*.vocabulary.ttl` → lives in **ontology-hub** (consumed by SKOS mappings, SHACL validation, projection engine)

Both formats are needed. They serve different audiences and repos.

---

## 7. Per-column sample values lose row context for ontology modelers

**Problem:** The generated `*.vocabulary.ttl` stores sample values per-column:
```ttl
adminpulse:RelationAddress_city  kairos-bronze:sampleValues "Brussel | Anderlecht" .
adminpulse:RelationAddress_street kairos-bronze:sampleValues "Rue Haute | Kerkstraat" .
```

The ontology modeler cannot see which values belong together in a single row
(e.g., "Rue Haute" is in "Brussel", not "Anderlecht"). This makes it harder to
understand entity structure, field relationships, and cardinality patterns.

**Current value:** Per-column samples are useful for format/enum detection
(e.g., recognizing email patterns, date formats, low-cardinality enums).

**Missing value:** Row-level samples that preserve field co-occurrence — critical
for understanding:
- Which address fields form a complete address
- Which foreign keys point to which parent records
- How fields combine to describe a real entity

**Proposed fix — add table-level row samples:**

Option A — TTL annotation (machine-readable):
```ttl
adminpulse:RelationAddress a kairos-bronze:SourceTable ;
    kairos-bronze:sampleRows """
id | relationId | street | city | country
A001 | REL-001 | Rue Haute 123 | Brussel | BE
A002 | REL-002 | Kerkstraat 45 | Antwerpen | BE
""" .
```

Option B — Companion YAML alongside TTL (human-readable):
```yaml
# integration/sources/adminpulse/adminpulse.samples.yaml
tables:
  - name: RelationAddress
    sample_rows:
      - {id: A001, relationId: REL-001, street: "Rue Haute 123", city: Brussel, country: BE}
      - {id: A002, relationId: REL-002, street: "Kerkstraat 45", city: Antwerpen, country: BE}
```

Option C — Both (recommended): TTL for tooling, YAML for human reference.

**Recommendation:** Option C. Keep per-column samples for automated detection,
add row-based samples for the ontology modeler's benefit.

---

## Summary of recommended toolkit changes

| Priority | Area | Change |
|----------|------|--------|
| 🔴 High | Scaffold | Add explicit `profile:` to `dbt_project.yml` |
| 🔴 High | Scaffold | Use `tables: []` not bare `tables:` |
| 🟡 Medium | Scaffold | Comment out `packages.yml` entry until first release |
| 🟡 Medium | Scaffold | Include `run_query_print` macro |
| 🟡 Medium | Skill | Handle missing package gracefully during introspection |
| 🟡 Medium | Skill | `import-source` should detect CWD context and warn/prompt for hub path |
| 🟡 Medium | CLI | Add row-based sample output to `import-source` / `extract-schema` |
| 🟢 Low | Skill | Auto-update `_sources.yml` placeholders from discovery |
