# Challenge / Verification of `improve.md`

Verification of the toolkit-improvement notes in [`improve.md`](./improve.md) against the
**current** toolkit source (not the pinned SHA the notes were captured against). Every verdict
cites `src/` file:line so it is auditable.

> **Important environment caveat.** The notes were captured against toolkit **v5.0.0** installed
> from git ref `feature/v5-stage2-4` @ SHA `c4dd565…` (see `toolkit-issues.md` header). Several
> symptoms are **already addressed on `main`**. "Outdated" below means *the current tree no longer
> exhibits the reported behaviour*, not that the observation was wrong when logged.

## Verdict legend

- **Confirmed** — reproducible in current code; the fix idea is still actionable.
- **Partial** — the core claim holds, but a sub-claim or the proposed fix is inaccurate.
- **Outdated** — already fixed / mitigated in current code.
- **Refuted** — not true of the current toolkit.
- **Duplicate** — already tracked in `toolkit-issues.md`.

## Summary table

| Item | Claim (short) | Verdict | Key evidence |
|---|---|---|---|
| A1 | `missingParent: null` (YAML null → None) fails the string-`"null"` enum; opaque error | **Confirmed** | `core/compiler/schema/entity-binding.schema.json:217,236,260` |
| A2 | Relationship `join.local` FK column must also be declared as a `fields:` entry | **Confirmed** | `core/projections/dbt/normalize.py` (`mapping.unresolved-join-input`, DD-107) |
| A3 | `--emit DIR` resolves relative to CWD, not hub root | **Partial** | `cli/compile.py:_BARE_EMIT_SENTINEL`, `compile_cmd` |
| A4 | `--format text` prints nothing on Windows (cp1252 can't encode glyphs) | **Outdated** | `cli/shared.py:30 _ensure_utf8_stdio`, called `cli/main.py:99` |
| A5 | Version-pin banner always warns (semver vs SHA) and pollutes `--format json` | **Partial** | `cli/shared.py:668 _warn_if_version_mismatch` (stderr), `:241 _tag_to_version` |
| A6 | No cross-domain `externalReference` worked example; key contract undocumented | **Confirmed** | `schema/example-entity-binding.yaml:52-53` (same-domain only) |
| A7 | `owl:imports` re-triggers DD-133 default-prefix ambiguity | **Plausible** (not deep-verified) | design: `docs/design/dd-133-*.md` |
| A8 | Emit ships **two** dbt layouts; unified `output/` has no `macros/` dir | **Refuted** | `cli/compile.py:_is_shared_artifact` emits `macros/`; default target `output/medallion/dbt` |
| B (Phase 0) | Add `dbt deps && dbt parse` gate; premise "macros not emitted" | **Partial** (premise refuted) | `core/projections/dbt/render.py:` writes `macros/{name}`; `core/dbt_validation.py` exists |

---

## Per-item detail

### A1 — `missingParent: null` footgun — **Confirmed**
The schema enumerates the **string** `"null"` for `missingParent` (and `ambiguousParent`
uses `"error"|"first"`) in all three relationship modes:
`entity-binding.schema.json:217` (non-temporal), `:236` (current), `:260` (as-of). YAML `null`
parses to Python `None`, which fails the enum → the opaque `is not valid under any of the given
schemas` error. All three fix ideas remain valid; note the *loader-alias* option (accept YAML
`null`) is the least surprising for authors.

### A2 — FK join-local column must be materialized as a field — **Confirmed**
`core/projections/dbt/normalize.py` raises `mapping.unresolved-join-input` (rule
`DD-107-source-ownership`) with the message *"add a `fields:` entry mapping the FK join local
column"*. The requirement is real and the emitted diagnostic is (as the note says) precise. The
"auto-materialize like `organisation_sk`" fix idea is worth an issue; the doc-only alternative is
cheaper.

### A3 — `--emit` path relative to CWD — **Partial**
Nuance the note misses: only the **bare** `--emit` (no argument) resolves to the hub root —
`cli/compile.py` maps the `_BARE_EMIT_SENTINEL` to `hub / output/medallion/dbt`. When an
**explicit** directory is passed (`--emit output/`), it is used verbatim and `.resolve()`d against
CWD (`_emit_compile_artifacts`). So the reported stray `./output/` came from passing an explicit
path from the repo root. The default already does the right thing; the actionable fix is narrower
than stated: **warn when an explicit `--emit` target is outside the hub tree**, or resolve explicit
relative paths against the hub root.

### A4 — empty console on `--format text` (Windows encoding) — **Outdated**
`cli/shared.py:30 _ensure_utf8_stdio()` reconfigures `stdout`/`stderr` to
`encoding="utf-8", errors="replace"`, and it is invoked at process start
(`cli/main.py:99`). The docstring explicitly cites the cp1252/cp437 problem this note reports. The
symptom should no longer occur on current `main`; the `--no-emoji` idea is now optional polish, not
a bug fix.

### A5 — version-pin banner noise — **Partial**
Two sub-claims, different verdicts:
- *"pollutes `--format json`"* — **Refuted for stdout.** The banner is emitted with `err=True`
  (`_warn_if_version_mismatch`, `cli/shared.py:690`), so JSON on **stdout** is clean. It only
  "pollutes" if the caller merges streams (`2>&1`), which the note's environment did.
- *"always warns because it compares semver vs SHA"* — **Still valid for legacy git-SHA pins.**
  `_read_pinned_toolkit_version` parses the tag from a `.whl` release URL first, else a
  `git+https://…@<tag>` pin; `_tag_to_version` (`:241`) only strips a leading `v` and normalises
  rc/beta/alpha. A bare 40-char SHA passes through unchanged, never equals the running semver, and
  `packaging.version.parse(SHA)` throws → the banner prints "different from" on every command.
  So the note's exact scenario reproduces, **but** hubs pinned to a release tag/`.whl` URL compare
  correctly. Recommended framing: this is a *legacy-pin* edge case, not a universal bug.

### A6 — cross-domain `externalReference` undocumented — **Confirmed** (and complements ISSUE-7)
`externalReference` is a real feature (`entity-binding.schema.json`, `compiler/kernel.py`,
`compiler/bindings.py`), but `schema/example-entity-binding.yaml:52-53` only demonstrates a
**same-domain** `party:hasCountry → ref:Country` relationship. There is no cross-domain
`externalReference` worked example and the accepted canonical `type` tokens aren't enumerated for
authors — both fix ideas stand. Note this is the **authoring counterpart** to
`toolkit-issues.md` ISSUE-7 (compiler-wired relationships can't target another domain's binding):
`externalReference` is precisely the supported cross-domain path, so documenting it also partially
answers ISSUE-7.

### A7 — DD-133 prefix ambiguity on `owl:imports` — **Plausible, not deep-verified**
Consistent with the documented DD-133 default-prefix behaviour and the note self-reports it as a
known, already-anticipated recurrence (no lost iteration). Treat as a low-cost ergonomics item
(auto-suggest the exact `@prefix` line); left un-reproduced here as it needs a multi-ontology
fixture.

### A8 — "two dbt layouts / missing `output/macros/`" — **Refuted**
- **Macros are emitted.** `cli/compile.py:_is_shared_artifact` treats any `macros/…` path as a
  shared artifact, and `_emit_compile_artifacts` writes shared artifacts to the target;
  `core/projections/dbt/render.py` populates `artifacts["macros/{name}"]` (incl.
  `kairos_current_timestamp`), and `compiler/kernel.py` lists `macros/{name}` among expected paths.
  So a correctly emitted project **does** contain `macros/`.
- **There is one canonical layout, not two.** The default/bare emit target is the **unified**
  `output/medallion/dbt` (all domains under `models/silver/<domain>/`, single `dbt_project.yml`).
  The "two parallel representations" the note observed are an artifact of its own A3 mistake:
  an explicit `--emit output/` wrote a second tree at the repo root alongside the canonical
  `output/medallion/dbt`. The toolkit does not intentionally emit two competing dbt projects.

  Actionable residue: the confusion is real, so a `output/README.md` / packaging-skill note naming
  `output/medallion/dbt` as *the* build target is still worthwhile — but the premise that macros are
  missing and that the layout is dual-by-design is incorrect.

### Part B — `dbt parse` validation loop — **Partial (worthwhile idea, premise refuted)**
The *strategic* proposal (offline `dbt deps && dbt parse` gate; no warehouse needed) is sound and
worth pursuing. But its stated Phase-0 blockers are largely already handled:
- **"`kairos_current_timestamp` not emitted / no `output/macros/`"** — **Refuted** (see A8); macros
  are emitted as shared artifacts.
- The toolkit already ships **`core/dbt_validation.py`** (parses `dbt_project.yml`, reads the dbt
  `manifest`, manages temp project/packages dirs) — i.e. a dbt-parse capability already exists to
  build on, rather than starting from zero. Any B-phase plan should extend that module, not assume
  greenfield.
- Genuinely-missing prerequisites that remain valid: a scratch `profiles.yml` (no-connect), running
  `dbt deps` for `dbt_utils`/`dbt_expectations`, and choosing the adapter for `dbt compile` (T-SQL
  bracket quoting for the dataplatform). These are legitimate and unaffected by the above.

Net: keep Part B as a proposal, but re-baseline it — the "self-contained macros" toolkit change it
hinges on is **already done**, which makes Phase 0 cheaper than the note assumes.

---

## Corrected priority

Given the above, the note's priority list should be rebalanced:

1. **A1** (confirmed, cheap, high-frequency) — schema enum ergonomics.
2. **A6** (confirmed docs gap) — cross-domain `externalReference` example + `type` token list;
   reconcile with `toolkit-issues.md` ISSUE-7.
3. **A3** (partial) — warn on explicit `--emit` outside the hub tree.
4. **A2** (confirmed) — decide auto-materialize vs document the FK-field pairing.
5. **Part B Phase 0** (re-baselined) — extend `core/dbt_validation.py` into an opt-in offline
   parse gate; the macro-emission prerequisite is already satisfied.
6. **A5** (partial) — make `_tag_to_version` return `None` for unparseable/SHA tags so legacy
   git-SHA pins stop mis-warning.
7. **A7** (plausible) — DD-133 import-prefix auto-suggestion.
8. **A4, A8** — **already addressed**; downgrade to doc/UX polish only
   (`--no-emoji`; `output/README.md` naming the build target).

## Cross-references
- `docs/draft/improve.md` — the notes under challenge.
- `docs/draft/toolkit-issues.md` — ISSUE-7 (cross-domain relationship resolution) overlaps A6.
