# DD-101: Consolidated deterministic lifecycle gate (`check-release`)

**Status:** Accepted
**Date:** 2026-07-21
**Affects:** `src/kairos_ontology/core/lifecycle_gate.py` (new),
`src/kairos_ontology/core/binding_analysis.py`, `src/kairos_ontology/core/status.py`,
`src/kairos_ontology/cli/main.py` (`check-release`), `.github/skills/kairos-flow/`,
`.github/skills/kairos-diagnose-status/`, `.github/skills/kairos-execute-project/`,
`.github/skills/kairos-help/`
**Implementation:** `core/lifecycle_gate.py` (`evaluate_lifecycle_gate`,
`LifecycleGateReport`), `check-release` CLI command

### Context

Release readiness was spread across independently-run checks: `check-claims`
(claim validity/freshness, source completeness, extension sync), `project
--strict` (aspirational release blockers, DD-096), and `kairos-ontology
validate`/`project` (validation, projection artifacts) — each with its own exit
code and text output, and no single machine-readable place to consult "may this
hub ship?". `kairos-diagnose-status` re-derived the bound-vs-aspirational split
by hand (SPARQL-ish TTL reasoning) instead of the canonical `BindingAnalysis`,
risking drift from DD-096's D4 authority. DD-096 §11 open decision #4 explicitly
asked for this consolidation ("make `--strict` block release... this gate is
part of the design, not deferrable").

### Decision

Add one deterministic, read-only, side-effect-free entrypoint,
`lifecycle_gate.evaluate_lifecycle_gate`, exposed as `kairos-ontology
check-release`, that **composes** — never re-derives — the existing evaluators:

- **claim validity/freshness** (+ MDM-anchor/deviation/ownership/passthrough
  governance) — the literal `claim_coverage.check_claims_coverage` result.
- **source completeness** — the literal `source_coverage.check_source_coverage`
  result.
- **extension sync** — the literal `claim_projection_sync.evaluate_projection_sync`
  result (consumed via its public API only; the module itself is not modified).
- **aspirational release blockers** (DD-096) — a new shared
  `binding_analysis.analyze_domain_from_hub(hub_root, domain)`, which lifts the
  "load claims + ontology + Silver-ext + sources + mappings, then run the
  canonical `build()`" logic that was inlined in
  `status._domain_aspirational_stubs` into one reusable, hub-relative entrypoint.
  `status.py`'s D4 behavior is unchanged (`_domain_aspirational_stubs` is now a
  thin wrapper); the gate calls the same function to additionally read
  `bound_classes`/`reasons`, so status and the gate can never diverge on "is this
  bound?".
- **validation** and **projection** — read from `status.scan_hub_status`'s
  `validate`/`project` phases (never re-run).

`LifecycleGateReport.is_blocking` is a pure `OR` of each section's own blocking
signal (`ClaimCheckReport.is_blocking`, `SourceCoverageReport.is_blocking`,
`ProjectionSyncReport.is_blocking`, any domain's `release_eligible is False`,
`validation.passed is False`) — no new blocking rule is invented. Every section's
`to_dict()` projection keeps the original field names, so the reasons a caller
sees are byte-identical to running `check-claims`/inspecting `status` directly.

`core/status.py` gains additive, versioned (`schema_version: 2`) per-instance
`facts` so it remains the sole machine truth for objective per-phase/instance
state (see the DD-080 addendum); `lifecycle_gate.py` is the composition layer on
top, not a second source of truth. No AI/LLM calls; no claim is auto-approved; no
`aspirational`/`bound`/`release_eligible` flag is persisted — everything is
recomputed on every call.

### Rationale

Reusing each evaluator's own return value keeps one implementation of every rule
(claim governance stays in `claim_coverage.py`, mapping coverage in
`source_coverage.py`, sync drift in `claim_projection_sync.py`, binding
classification in `binding_analysis.py`) while still answering the
cross-cutting "ship or not" question in one call. Reading validation/projection
facts from the committed `status` scan rather than re-running either keeps the
gate side-effect-free and fast enough to call from `kairos-flow`/
`kairos-diagnose-status` on every resume. Composing via a pure `OR` means adding
the gate can only ever surface a pre-existing blocking condition earlier — it
cannot introduce a new way to block that a standalone `check-claims`/`project
--strict`/`validate` run would not already have flagged.

### Consequences

- One new CLI command, `check-release` (`--format text|json`, `--warn-only`,
  and the same scope/skip flags as `check-claims`), exempt from the skill-gate
  like `check-claims`/`status` (deterministic, AI-free, read-only).
- `kairos-flow`, `kairos-diagnose-status`, and `kairos-execute-project` are
  updated to consume `status`/`check-release` output for proposed/approved/
  aspirational/bound/release-eligible/validation facts instead of restating or
  hand-deriving them.
- `docs/draft/silverfirstdesign.md` is reconciled as the shipped reference
  design. Its §11 now lists only genuinely deferred extensions.
- Regression coverage: `tests/test_lifecycle_gate.py` (unit + CLI), the
  `facts`-focused additions to `tests/test_status.py`, and the complete
  `tests/scenarios/test_scenario_silver_first_e2e.py` lifecycle.
