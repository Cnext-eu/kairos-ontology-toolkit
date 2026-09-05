# DD-137: Derived, Stateless Readiness Proposal (`kairos-ontology next`)

**Status:** Accepted
**Date:** 2026-07-28
**Affects:** CLI (`next`), `core/next_actions.py`, `core/hub_inspection.py`, `kairos-flow` and
`kairos-diagnose-status` skills (and their scaffold copies)
**Implementation:** `src/kairos_ontology/core/next_actions.py`,
`src/kairos_ontology/core/hub_inspection.py`, `src/kairos_ontology/cli/inspection.py`,
`tests/test_next_actions.py`, `tests/test_cli_next.py`

### Context

V5 is stateless (DD-133/DD-135): design skills surface next actions conversationally, but nothing
persists them and `kairos-flow` must never create a continuation record. Two skills independently
encoded a next-action decision tree in non-deterministic, untestable LLM prose, so routing could
drift between sessions and between skills. Users asked for a repeatable, drift-free way to
recompute and present the next action without reintroducing a stored state file.

### Decision

Add a read-only `kairos-ontology next` command that gathers a defensible, in-memory snapshot of
authored inputs and canonical compiler status, then derives an advisory, deterministic
`NextActionProposal`. The pure proposer (`core/next_actions.py`) performs no I/O and holds no
state; the I/O gatherer (`core/hub_inspection.py`) reuses the existing binding loader and compiler
entry points rather than adding an alternate resolver. The command is the **single deterministic
routing authority**: `kairos-flow` and `kairos-diagnose-status` consume its JSON and map stable
action kinds to owning skills instead of re-deriving their own decision tree.

The proposal reports only defensible observations — authored input present/missing/unreadable,
canonical compile status and ordered diagnostics, and authored optional (Gold/MDM) policy presence.
Stages whose completion cannot be proven from authored inputs are emitted as
`human_decision_required`; when the compile check is skipped, downstream readiness is
`indeterminate`. JSON is clean on stdout with the advisory banner on stderr; exit is `0` for any
advisory proposal (including blocking diagnostic actions, which are data) and non-zero only for an
operational error such as an unresolved hub.

### Rationale

One deterministic routing authority prevents the two skills' heuristics from disagreeing and makes
routing testable and byte-stable. Keeping the proposal derived and advisory — recomputed every run,
never persisted — preserves the stateless architecture instead of reviving a state file.

### Contrast with the retired DD-135/DD-136 readiness subsystem

This is explicitly **not** the retired lifecycle/status/completeness authority. It never persists a
continuation record, never claims semantic completeness from file presence, and never becomes an
alternate compile or materialization authority. File presence is reported as presence only; the
canonical compiler remains the sole planning authority and its diagnostics are surfaced verbatim.

### Consequences

- `kairos-ontology next` exists as a read-only advisory command; no state is written.
- `kairos-flow` and `kairos-diagnose-status` stop independently routing and consume the proposal.
- A passing compile check reported here is not a downstream runtime or release guarantee.
- Adding a new action kind requires extending the single `ACTION_SKILLS` routing map.

### Amendment (proposal schema v2): optional offline dbt gate

`SCHEMA_VERSION` is bumped to `2`. The snapshot gains one additional **defensible emitted-output
observation**, `emitted_dbt_project` (presence/unreadable/missing of
`output/medallion/dbt/dbt_project.yml`), plus the configured `adapter` used only to render a
command. When an emitted project is observed **and** at least one domain currently passes the
compile check, the proposer surfaces a single hub-level `validate-dbt` action with status
`optional` (never `blocking`, never a mandatory sequential step). This deliberately does **not**
reintroduce lifecycle state: the observation is presence-only, cannot prove the emitted project is
fresh or that the current CompilePlan produced it, and disappears when the emitted project is
absent. The action routes to `kairos-execute-validate`, matching the opt-in offline
`deps → parse → manifest → compile` gate (see the DD-110 parity check in `core/dbt_validation.py`).
An unreadable emitted project yields `human_decision_required` instead.
