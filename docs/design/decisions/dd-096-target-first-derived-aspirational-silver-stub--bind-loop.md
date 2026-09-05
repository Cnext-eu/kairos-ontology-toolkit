# DD-096: Target-first derived-aspirational Silver stub → bind loop

**Status:** Accepted

**Date:** 2026-07-21

**Affects:** `src/kairos_ontology/core/binding_analysis.py`,
`src/kairos_ontology/core/projections/medallion_dbt_projector.py`
(`_gen_silver_models`, `_stub_columns`, `_gen_schema_yaml`, `generate_dbt_artifacts`),
`src/kairos_ontology/core/projector.py` (`run_projections`, `_run_projection`),
`src/kairos_ontology/cli/main.py` (`project --emit-aspirational-stubs`),
`src/kairos_ontology/templates/dbt/silver_stub_model.sql.jinja2`,
`src/kairos_ontology/core/determinism.py`, shipped reference design
`docs/draft/silverfirstdesign.md`

**Implementation:** Flag-gated stub emission on top of the canonical
`BindingAnalysis` service (B0) and the Claim Registry (DD-094). Determinism context
(A) is a prerequisite so re-projection stays byte-identical.

### Context

The silver dbt projector historically **skips** any class with no bronze mapping
("no broken placeholders"). That means an *approved but unmapped* claim has no Silver
**target** until a mapping exists, so downstream models cannot be built target-first.
The Silver-First design (`docs/draft/silverfirstdesign.md`) asks for an approved,
unbound claim to project a **stub** — a stable Silver target that transparently
"binds" once a mapping arrives, all via re-projection with no hand-editing. Two
critiques had to be resolved first: (1) `aspirational` must not become a persisted
field that forks the claim state machine, and (2) empty stubs must not create
false-green CI (vacuous 0-row tests passing).

Five blocking inputs (DEC-1…DEC-5) were resolved before implementation.

### Decision

Add an **opt-in, flag-gated** target-first stub → bind loop:

- **Derived, not persisted.** `aspirational` is computed at projection time by the
  canonical `BindingAnalysis` (B0): a class is aspirational iff it is a
  materialization-eligible approved claim (**DEC-5**: `disposition ∈ {claim,
  specialize}` ∧ `type ∈ {class, reference_data}` ∧ `status == approved`) **and** its
  physical Silver model is unbound (no source, not a folded discriminator subtype). No
  new field is added to `Claim`/`SilverImpact`; the status/disposition state machine is
  untouched.
- **Opt-in flag.** `generate_dbt_artifacts(emit_aspirational_stubs=…,
  eligible_class_uris=…)`, threaded through `run_projections`/`_run_projection` and the
  CLI `project --emit-aspirational-stubs` (dbt/all only), with env fallback
  `KAIROS_EMIT_ASPIRATIONAL_STUBS`. **Feature-off is byte-identical to today.**
- **Typed zero-row stub (DEC-3/DEC-4).** `silver_stub_model.sql.jinja2` emits a
  `materialized='view'` model tagged `kairos_aspirational_stub` with
  `meta.is_aspirational=true`, selecting `cast(null as <type>) as <col>` for the
  surrogate-key + IRI structural columns and every (inherited) datatype-property
  column, guarded by `where 1 = 0`. Columns are **typed where typable** via
  `kairos-ext:silverDataType` → `rdfs:range` (`_xsd_to_target`) → the projector's
  established string fallback `VARCHAR(255)` (the value of `_xsd_to_target(None)`;
  this supersedes the earlier `varchar(4000)` draft to stay consistent with the
  projector default). Binding is a plain re-projection; incremental/SCD models use
  `on_schema_change='sync_all_columns'` and the first bound run is a full refresh
  (safe/cheap — the stub had zero rows).
- **Schema YAML marker.** The stub's `_models.yml` entry carries a read-only, derived
  `meta.is_aspirational`.
- **Obsolete-output reconciliation (C3).** The dbt projector writes a
  `.kairos-projection-manifest.json` at the output root recording the files it
  generated; the next run deletes any manifest-recorded file it no longer produces
  (pruning emptied directories). This converges re-projection on the current output —
  a stale stub is removed when the feature is disabled or its claim is deferred —
  while only ever deleting toolkit-recorded files, so hand-authored files are never
  touched.
- **Release-eligibility, not existence, is the gate (DEC-1/DEC-2).** All approved,
  materialization-eligible, *unbound* claims are release-blocking under the strict
  gate; no required/optional field is added (per-claim waiver deferred). Implemented as
  `project --strict` (env fallback `KAIROS_PROJECT_STRICT`, dbt/all only): the dbt
  projector surfaces the unbound-eligible set via an internal `__unbound_eligible__`
  artifact key (computed from the same `class_to_sources`/eligibility as stub emission,
  independent of whether stubs are emitted), and `run_projections` raises
  `ProjectionRunError` when any remain. The scaffold `release-projections.yml` runs the
  projection step with `--strict` so an incomplete hub cannot ship. Gold/Power BI is
  still generated over a stub dependency (star schema stays stable) but any model in a
  stub's dependency closure is **non-release-eligible**; the strict gate blocks release
  while a release-blocking stub exists.
- **Status-scan awareness (D4).** The deterministic `kairos-ontology status` scan
  distinguishes stub vs bound by running the canonical `BindingAnalysis` over the
  hub's *authorities* — the Claim Registry (materialization-eligibility), the domain
  graph, source vocabulary, and SKOS mappings — **not** by reading generated
  `meta.is_aspirational` (absent when the flag is off or the output is stale). A silver
  domain with an approved-but-unbound eligible claim is reported `in-progress`
  ("N aspirational stub(s) pending binding: …") instead of `done`, so `kairos-flow`
  reconciliation and `kairos-diagnose-status` stay correct. The scan degrades to
  today's file-presence result (`done`) when a domain has no claims registry or on any
  load error, preserving the scanner's robust, LLM-free determinism.
- **Determinism prerequisite (A).** Generated artifacts embed an injected
  `generated_at` + `toolkit_version` context (env-overridable via
  `KAIROS_GENERATED_AT`/`SOURCE_DATE_EPOCH`) and sort all RDFLib iteration, so
  re-projection is byte-identical across processes and hash seeds.

### Rationale

Deriving `aspirational` keeps a single source of truth (the Claim Registry + mappings)
and avoids a parallel persisted state that could drift from governance. The opt-in
flag guarantees zero behaviour change for existing hubs (byte-identical output),
letting the loop roll out incrementally. Typed zero-row stubs give downstream models a
stable contract while `where 1 = 0` prevents vacuous green tests from masking an
unbound target. Gating on release-*eligibility* rather than artifact existence keeps
output byte-stable and avoids cascading suppression of gold. Centralizing bound/stub/
folded/skipped classification in one `BindingAnalysis` service means the projector,
coverage, release gate, and status scan never diverge on "is this bound?".

### Consequences

- Hubs can build Silver/Gold **target-first** against approved claims before mappings
  exist; adding a SKOS mapping transparently binds the stub on the next projection.
- Feature-off output (and absence of the new metadata) is unchanged — a hard
  backward-compat constraint enforced by tests.
- Coverage/status must distinguish stub vs bound (a stub is not "done"); the release
  gate blocks while release-blocking stubs remain.
- Deferred (out of scope): per-claim release waivers, `contract.enforced`
  promotion, and the drift report. DD-095 has since shipped conformance as a
  deterministic **proposed-only** evidence driver; it still cannot approve.
- The authoritative complete lifecycle regression is
  `tests/scenarios/test_scenario_silver_first_e2e.py`.

### Addendum (2026-07-21): `BindingAnalysis` consolidated as the single result; aspirational decoupled from stub emission

**Affects:** `src/kairos_ontology/core/binding_analysis.py`,
`src/kairos_ontology/core/claim_projection_sync.py`,
`src/kairos_ontology/core/status.py`,
`src/kairos_ontology/core/projections/medallion_dbt_projector.py`.

The original write-up derived `STUB` only when the projector's stub flag was on, so a
consumer that needed the aspirational/release facts with stubs **off** (status, the
`--strict` gate) had to force `stubs_enabled=True` — coupling two independent concerns
and risking divergence. `BindingAnalysis` is now the **one canonical materialization
result**, refined as follows (no behaviour change to feature-off output):

- **Aspirational is derived independently of stub emission.** `classify_binding`
  no longer takes `stubs_enabled`: an unbound, materialization-eligible, non-folded
  class is :data:`STUB` (aspirational) regardless of the flag. Stub *byte emission*
  is a separate gate — `BindingAnalysis.should_emit_stub()` = aspirational **and**
  `stubs_enabled`. The projector still emits stubs only under
  `--emit-aspirational-stubs`, so **feature-off output stays byte-identical**.
- **One result, one set of helper APIs.** `BindingAnalysis` exposes
  `is_aspirational`/`aspirational_class_uris` (status), `is_release_blocking`/
  `release_blocking_class_uris` (strict gate), `should_emit_stub`/`is_materialized`/
  `materialized_class_uris` (projection inclusion), plus `state`/`reason`. `build(...)`
  accepts a pre-computed `SourceBindings` so the dbt projector classifies from the
  **same** `compute_source_bindings` result it materializes from (no recompute, no
  divergent inline logic). `status` no longer forces `stubs_enabled=True`; the dbt
  projector's stub-emission and `__unbound_eligible__` release set are read from the
  canonical analysis.
- **Registry-fact filters are canonical too.** `materialization_eligible_class_uris`
  (unchanged rules) and the new `approved_imported_class_uris` are the single claim
  filters; `claim_projection_sync` consumes the latter (applying only its
  external-to-domain rule) instead of reimplementing the approved/imported/disposition
  test. The Claim Registry remains the sole eligibility authority (DD-094) — status,
  disposition, and type rules are unchanged.
- **Still derived, never persisted.** No field is added to `Claim`/`SilverImpact`;
  `core` still never imports `mdm`. Parity is covered by
  `tests/scenarios/test_scenario_binding_parity.py` plus the decoupling/reasons cases
  in `tests/test_binding_analysis.py` and the sync-delegation case in
  `tests/test_claim_projection_sync.py`.

### Addendum (2026-07-21): §11 open decision #4 resolved — one composed release gate (DD-101)

**Affects:** `src/kairos_ontology/core/lifecycle_gate.py`,
`src/kairos_ontology/core/binding_analysis.py`, `src/kairos_ontology/core/status.py`,
`src/kairos_ontology/cli/main.py` (`check-release`).

`docs/draft/silverfirstdesign.md` §11 open decision #4 asked for separate,
named states — *schema-valid vs bound vs data-valid vs release-eligible* — so a
stub's vacuous-green-CI risk could be told apart from real completion, and for
`--strict` to be "part of the design, not deferrable." `--strict` already blocked
release inside `run_projections`; this addendum makes the four states themselves
machine-readable **without duplicating that rule**:

- **schema-valid** — a class exists in the domain ontology (trivially true for any
  projected class; no new fact needed).
- **bound** / **release-eligible** — `binding_analysis.BindingAnalysis.is_bound` /
  `release_blocking_class_uris`, now reachable hub-side (no projection required)
  via `analyze_domain_from_hub`, and surfaced per-domain by both the `status`
  scan (`silver` phase facts) and the new `check-release` CLI / `lifecycle_gate`
  module (DD-101).
- **data-valid** — read (never re-derived) from the persisted
  `validation-report.json` via `status`'s `validate` phase fact.

`check-release` composes these with the existing claim/source-coverage/extension-
sync evaluators into one pass/fail decision, so a CI pipeline has a single command
to consult instead of separately running `check-claims`, `project --strict`, and
inspecting `status` output by hand. `project --strict` remains the enforcement
point for an actual projection run (unchanged); `check-release` is the read-only,
side-effect-free preflight/report that can run *before* a projection is attempted
or in `kairos-diagnose-status`/`kairos-flow` without generating artifacts.
