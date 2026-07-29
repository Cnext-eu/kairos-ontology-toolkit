# Toolkit & Validation Improvement Notes

Advisory notes captured while authoring the `equipment` SHACL shapes and the
`equipment:Unit → party:Organisation` relationship (session 2026-07-28/29).
These are **toolkit / workflow** improvement suggestions for the Kairos Ontology
Toolkit and the downstream dataplatform — not hub model changes. File actionable
items upstream via **kairos-toolkit-ops** / the toolkit issue tracker.

---

## Part A — Iterations that could have been avoided by improving the toolkit

The relationship change took several compile/emit round-trips. Most were caused by
**toolkit ergonomics**, not by genuine modeling ambiguity. Ranked by cost.

### A1. `missingParent: null` footgun + opaque schema error  ⟵ 1 wasted iteration
- **Symptom:** `compile --check` failed with
  `binding.schema … is not valid under any of the given schemas` (rule `DD-133`),
  dumping the entire relationship dict with no field pointer.
- **Root cause:** the JSON schema enum for `missingParent`/`ambiguousParent` is the
  **string** `"null"`, but YAML `null` parses to `None`, which fails the enum.
  (`core/compiler/schema/entity-binding.schema.json` → `"missingParent": {"enum": ["error","null"]}`.)
- **Fix ideas (toolkit):**
  1. Accept YAML `null` as an alias for the string `"null"` in the binding loader.
  2. Emit a **precise** schema diagnostic: name the failing field, the received
     value, and the allowed enum (`missingParent: got null (None), expected "error" | "null"`)
     instead of "not valid under any of the given schemas".
  3. Rename the enum value so it can't collide with YAML null (e.g. `set-null`).

### A2. FK join-local column must be manually materialized  ⟵ 1 iteration
- **Symptom:** after adding the relationship, check failed with
  `safety.type-incompatible … mapping.unresolved-join-input … add a fields: entry
  mapping the FK join local column … [DD-107-source-ownership]`.
- **Root cause:** a relationship `join.local` column is not automatically added to
  the silver projection; the author must also declare a scalar `fields:` entry
  (here `equipment:subcontractorReference ← subcontractor_company_id`).
- **Note:** the error message here was **good** (told us exactly what to do).
- **Fix ideas (toolkit):**
  1. Auto-materialize `join.local` columns into the silver model (the projector
     already does this for `organisation_sk`), removing the manual field, **or**
  2. Keep it explicit but document the "FK field + relationship" pair in the
     mapping skill and `example-entity-binding.yaml` so it's expected up front.

### A3. `--emit` path resolved relative to CWD, not the hub root  ⟵ 1 iteration + cleanup
- **Symptom:** `compile <d> --emit output/` run from the repo root wrote artifacts
  to `./output/` instead of the canonical `ontology-hub/output/`, creating a stray
  tree that had to be deleted and re-emitted from inside `ontology-hub/`.
- **Fix ideas (toolkit):**
  1. Resolve `--emit` relative to the **hub root** (the `kairos.yaml` location), or
  2. Default the emit directory to the hub's configured output, or
  3. Warn when the target is outside the hub tree.

### A4. Empty console output on `--format text` (Windows encoding)  ⟵ 1 confused iteration
- **Symptom:** `compile --check --format text` printed **nothing** and exited 1;
  only redirecting to a file with `PYTHONIOENCODING=utf-8` revealed the diagnostics.
- **Root cause:** emoji/box-drawing glyphs in the human formatter can't encode to the
  Windows console code page (cp1252), aborting the write.
- **Fix ideas (toolkit):** detect a non-UTF-8 stream and fall back to ASCII markers,
  or force UTF-8 on the CLI's stdout, or provide `--no-emoji`.

### A5. Version-pin warning noise on every command
- **Symptom:** every invocation prints
  `Running kairos-ontology v5.0.0, which is different from the version pinned … (v6a16f7c…)`.
- **Root cause:** the check compares a **semver** (`5.0.0`) against a **git SHA** pin,
  so it can never match and always warns; with `2>&1` it also pollutes `--format json`.
- **Fix ideas (toolkit):** compare like-for-like (resolve the pinned SHA to its
  version), suppress the banner in `--format json`, or route it to a debug channel.

### A6. Cross-domain `externalReference` contract is undocumented  ⟵ heavy investigation
- **Symptom:** determining the correct `key.column` (materialized parent column
  `organisation_reference`, not source `company_id`) and the canonical `type` token
  (`string`) required reading `core/compiler/kernel.py` and
  `core/projections/dbt/policy_normalize.py`.
- **Root cause:** `example-entity-binding.yaml` only shows a **same-domain**
  temporal `ref:Country` relationship; there is **no cross-domain `externalReference`
  worked example**, and the accepted canonical `type` tokens aren't listed for authors.
- **Fix ideas (toolkit):**
  1. Add a cross-domain `externalReference` example (child → parent in another domain)
     to `example-entity-binding.yaml`.
  2. Document the key contract: `key.column` = the **parent's materialized output
     column**; `type` = a canonical token (`string`, `int32`, `decimal`, …) whose
     kind must match the local source column's kind.
  3. Emit a targeted diagnostic when `join.foreign != externalReference.key.column`
     (this one already exists — `safety.relationship-endpoint` — and is good).

### A7. DD-133 prefix ambiguity re-triggered by a new `owl:imports`  (recurring)
- **Symptom:** importing `party` into `equipment.ttl` re-collided the default `:`
  prefix (mmt/equipment# vs party#), needing a manual root `@prefix :` declaration.
  Anticipated this time (no lost iteration) because `booking.ttl` hit it earlier.
- **Fix ideas (toolkit):** when the ambiguity comes only from **imported** ontologies'
  default prefixes and the domain declares none of the colliding terms, downgrade to
  a warning, or auto-suggest the exact `@prefix` line to add.

### A8. `output/` layout is ambiguous — two parallel dbt representations  ⟵ recurring confusion
- **Symptom (this session):** two separate points of confusion about the emit output:
  1. **Where it lands** — the first re-emit wrote a stray `./output/` at the repo root
    (see A3), so it was momentarily unclear which `output/` was authoritative.
  2. **Which subtree is "the" dbt project** — `output/` contains **two** different dbt
    layouts and it wasn't obvious which one to parse/ship:
     - a **unified** top-level project: `output/dbt_project.yml` (profile
       `kairos_medallion_project`) + `output/packages.yml` + `output/models/silver/{booking,equipment,party}/`
       — all domains in one project, so cross-domain `ref()` resolves here; **but** it
       declares `macro-paths: ["macros"]` with **no `output/macros/` directory** present;
     - **per-domain** self-contained projects under
       `output/medallion/dbt/<domain>/` (each with its **own** `dbt_project.yml`,
       `packages.yml`, `models/`) — these can **not** resolve cross-domain refs.
  - The doc itself initially mis-stated this (claimed the emit was "per-domain, not
    parseable in isolation") before the unified top-level project was found — evidence
    the layout is genuinely unclear.
- **Root cause:** the emit produces both a unified project and per-domain projects with
  no README/manifest stating which is the intended dbt build/parse target, and the
  `medallion/` nesting hides the second set of `dbt_project.yml` files.
- **Fix ideas (toolkit):**
  1. Document the `output/` layout (unified vs per-domain) in `output/README.md` and the
     `kairos-package-dataplatform` skill, explicitly naming the **unified top-level project
     as the parse/build target**.
  2. Make the unified project self-contained — emit the `output/macros/` directory
     (at minimum `kairos_current_timestamp`) so `macro-paths` isn't dangling.
  3. Clarify the purpose of `output/medallion/dbt/<domain>/` (per-domain inspection vs
     shippable) so authors don't parse the wrong tree.

**Themes:** (1) schema/enum ergonomics and error precision; (2) auto-materialize what
the projector can infer; (3) path/encoding robustness on Windows; (4) ship worked
examples for the non-trivial (cross-domain, temporal) binding features; (5) make the
`output/` layout self-describing and its parse/build target unambiguous.

---

## Part B — Where to add a `dbt parse` validation loop

### Why it's missing today
Kairos `compile --check` / `validate` intentionally stop at **ontology + SHACL +
static-safety kernel + deterministic artifact planning**. They never invoke dbt, so
**dbt-level** correctness (Jinja renders, `ref()`/`source()` resolve, macros exist,
packages installed, SQL dialect valid) is unchecked. The toolkit states this
explicitly: *"Passing compilation does not replace downstream dbt … tests."*

### Key point: `output/` ships **two** dbt layouts — parse the unified one
The emit produces two parallel dbt representations (see A8), and picking the wrong one
is the main source of confusion:

| Layout | Location | Cross-domain `ref()` | Parse target? |
|---|---|---|---|
| **Unified project** | `output/` (`dbt_project.yml` + `models/silver/<all domains>`) | ✅ resolves | ✅ **yes** |
| Per-domain projects | `output/medallion/dbt/<domain>/` | ❌ can't resolve | no |

Parse the **unified top-level `output/` project**. In isolation it still needs three
things wired up first:
- **no `output/macros/`** dir, yet models call `{{ kairos_current_timestamp() }}` — the
  only custom macro, and `dbt_project.yml` even declares `macro-paths: ["macros"]`
  pointing at a **missing** directory;
- packages in `packages.yml` (`dbt_utils`, `dbt_expectations`) aren't installed
  (`dbt deps`);
- **no `profiles.yml`** / adapter configured.

`dbt parse` and `dbt compile` do **not** require a live warehouse connection — they
validate the graph, refs, macros, and render SQL offline. That makes them a cheap,
high-value CI gate.

### Recommended placement (phased)

**Phase 0 — Basic parseability gate on the unified `output/` project (do this first).**
The top-level emit **is already a single unified dbt project**
(`output/dbt_project.yml`, `output/packages.yml`, all domains under
`output/models/silver/<domain>/`), so cross-domain `ref("organisation")` resolves
there — no unification work is needed. Only three things block a parse today:
1. `kairos_current_timestamp()` — the **only** custom macro referenced by the
   models, and it is **not emitted** (there is no `output/macros/` directory);
2. `dbt_utils` / `dbt_expectations` — declared in `packages.yml` but not installed
   (`dbt deps`);
3. no `profiles.yml` — `dbt parse` needs a profile to **exist** but makes **no**
   DB connection, so any adapter (e.g. `dbt-duckdb`) works and dialect is irrelevant.

Introduce a thin, opt-in post-emit gate, **owned by `kairos-execute-validate`**
(e.g. `kairos-ontology dbt-check` / `validate --dbt-parse`), positioned in
`kairos-flow` right after `compile-emit` and before commit:
```
compile --check ─▶ validate --shacl ─▶ emit → output/ ─▶ [NEW] dbt-check ─▶ commit
```
The gate would:
1. ensure `output/macros/_kairos_runtime.sql` provides `kairos_current_timestamp`
   (and any other `kairos_*` macros) — see the toolkit change below;
2. write a scratch `profiles.yml` (dbt-duckdb, no connection);
3. run `dbt deps`, then `dbt parse` (optionally `dbt compile`);
4. map dbt failures back to the originating binding/ontology as diagnostics.

**Single toolkit change that makes this trivial:** have `emit` write the
`kairos_current_timestamp` (and any `kairos_*`) runtime macro into `output/macros/`
so `output/` is **self-contained**. Then the whole early check reduces to
`dbt deps && dbt parse` inside `output/` — runnable in the hub, no dataplatform and
no warehouse required. `dbt parse`/`compile` never connect to a database, so this is
a fast, offline "fix things early" loop.

**Phase 1 — Dataplatform CI gate (broader home).** In the downstream repo created by
`kairos-setup-dataplatform` / consumed via `kairos-package-dataplatform`, add a CI
step after each emit consume:
```bash
dbt deps
dbt parse       # graph/ref/macro/Jinja validation, no DB
dbt compile     # renders SQL, no DB
# optional, needs a test warehouse:
dbt build --target ci
```
Prerequisites the scaffold must guarantee: the `kairos_current_timestamp` macro, a
`profiles.yml` (a no-connect target is fine for parse/compile), the T-SQL adapter
(`dbt-sqlserver`/`dbt-fabric` — the SQL uses `[bracket]` quoting), and `dbt_utils` +
`dbt_expectations` pinned in `packages.yml` (already emitted).

**Phase 2 — Optional toolkit convenience gate.** Add an opt-in
`kairos-ontology emit --dbt-check` (or a `kairos-execute-validate --dbt` mode) that,
**when** an adapter + profile are configured, shells out to `dbt deps && dbt parse`
in the emitted **unified** project and surfaces failures as diagnostics. Keep it
opt-in so the core toolkit stays free of a hard dbt/adapter dependency.

**Phase 3 — Contract parity check.** Cross-check the emitted `DD-110-COLUMNS` header
and `*-silver-constraints.json` against `dbt compile`'s manifest so a divergence
between the Kairos plan and the rendered dbt model is caught automatically.

### Closing the loop
```
ontology.ttl ──▶ compile --check (static safety)  ✅ exists
            └──▶ validate --shacl (constraints)   ✅ exists
            └──▶ emit → output/                    ✅ exists
                     └──▶ [NEW · Phase 0] dbt deps + parse on the unified output/  ⟵ add here (early, offline)
                              └──▶ [Phase 1] dbt parse/compile in the dataplatform CI
                                       └──▶ dbt build/test against warehouse (existing downstream)
```

**Priority:** A1, A3, A4 (cheap, high-frequency friction) → **B Phase 0** (early,
offline `output/` parse gate — biggest safety gain for least effort) → B Phase 1 →
A2, A6 (docs/ergonomics) → B Phase 2/3.
