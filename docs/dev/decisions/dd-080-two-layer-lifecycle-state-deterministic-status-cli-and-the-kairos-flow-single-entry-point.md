# DD-080: Two-layer lifecycle state, deterministic `status` CLI, and the `kairos-flow` single entry point

**Status:** Accepted
**Date:** 2026-06-20
**Affects:** `src/kairos_ontology/status.py`, `cli/main.py` (`status` command),
`.github/skills/kairos-flow/`, `.github/skills/kairos-diagnose-status/`, scaffold
skills, `kairos-help`, methodology doc §21
**Implementation:** `src/kairos_ontology/status.py` (scanner),
`status` CLI command, `kairos-flow` skill (state owner + orchestrator)

### Context

Each design phase was a separate skill with its own bespoke pre-flight and its own
ad-hoc `.sessions-design/{phase}-{name}-{date}.md` log. There was no single formal
status overview, no resumable per-step state that captured open questions, and no
single "start" instruction. Status was re-derived by LLM scanning in
`kairos-diagnose-status`, which is non-deterministic and not authoritative.

### Decision

Split lifecycle state into **two layers**:

1. **Objective** — derived deterministically from committed artifacts by a new
   read-only, AI-free CLI `kairos-ontology status` (module `status.py`). It emits
   per-phase / per-instance `not-started | in-progress | done`. Exempt from the
   skill-gate (like `check-alignment`). `kairos-diagnose-status` becomes a thin
   wrapper that runs it and enriches the result.
2. **Continuation** — an **OKF v0.1** markdown bundle at
   `ontology-hub/.kairos-state/` (`status.md` with scan/continuation/phase-index
   regions + per-instance `phases/<phase>/<instance>.md` logs with an Open
   Questions resume anchor). OKF is used purely as a storage convention.

A new **`kairos-flow`** skill is the single entry point: it runs the scan, loads
and reconciles the continuation state, presents the overview, offers clean-start
vs continue, and **hands off** to the correct phase skill (interactive-only).
`kairos-flow` is the only writer of `status.md`; phase skills only read state and
append a "state update proposal" to their own instance log.

### Rationale

A persisted hand-maintained status file risks drifting from the real artifacts, so
objective facts are computed deterministically and the markdown layer is confined
to intent/open-questions. Centralizing `status.md` writes in `kairos-flow` (rather
than a write-contract spread across eight prose skills) avoids reliance on
distributed LLM obedience. Per-instance logs match the real cardinality of source/
mapping/silver/gold work. Clean-hub assumption: no `.sessions-design/` migration —
`.kairos-state/` is the only state system going forward.

### Consequences

- New deterministic CLI `kairos-ontology status` (+ unit tests on the acme-hub
  scenario) is the authoritative objective backbone.
- New `kairos-flow` skill is the recommended starting point ("start / where are we
  / continue"); `kairos-help` and the routing table point to it.
- Phase skills gain a lightweight read-state + state-proposal contract (rolled out
  incrementally); they stop writing new `.sessions-design/` logs.
- Reconciliation rules are explicit (scan wins for facts; continuation wins for
  intent).

### Addendum (2026-07-21): Machine-readable per-instance facts + schema versioning (DD-101)

**Affects:** `src/kairos_ontology/core/status.py`, `src/kairos_ontology/core/binding_analysis.py`.

`status.py`'s objective scan stayed limited to a `not-started|in-progress|done`
triad; consumers that needed finer machine-readable state (claim `proposed`/
`approved` counts, Silver `bound`/`aspirational` classes, validation pass/fail)
had to re-derive it themselves (e.g. `kairos-diagnose-status`'s hand-rolled
aspirational-vs-bound section). `InstanceStatus` gains an additive `facts: dict`
bag, populated only where objectively knowable from committed authorities:

- **claims** — `{"proposed": N, "approved": N}`, a raw count of the registry's own
  `status` field (no governance rule re-derived; `check-claims` remains the
  authority for bucket/blocking semantics).
- **silver** — `{"bound_classes": [...], "aspirational_classes": [...],
  "release_eligible": bool}`, from the same canonical
  `binding_analysis.BindingAnalysis` snapshot the state/detail computation already
  used (D4) — one computation, not two.
- **validate** — `{"data_valid": bool}` when the persisted
  `validation-report.json` has recognizable `{section: {"failed": int}}` counts;
  omitted (not guessed) otherwise.

The shared "load hub authorities and build a `BindingAnalysis`" logic previously
inlined in `status._domain_aspirational_stubs` is now the canonical
`binding_analysis.analyze_domain_from_hub(hub_root, domain)`, reused by both the
scan and the new DD-101 lifecycle gate; `_domain_aspirational_stubs` is now a
thin, behavior-preserving wrapper (same signature, same return value, still
directly unit-tested). `HubStatus.to_dict()` gains `"schema_version": 2`
(v1 had neither the version key nor `facts`); every v1 key is unchanged, so v1
consumers keep working — only additive keys were introduced, hence no
backward-compatibility break.
