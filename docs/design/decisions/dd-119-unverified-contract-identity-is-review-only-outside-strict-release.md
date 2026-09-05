# DD-119: Unverified Contract Identity Is Review-Only Outside Strict Release

**Status:** Accepted
**Date:** 2026-07-26
**Affects:** `core/projections/dbt/policy_normalize.py`, `core/projections/dbt/policy_specs.py`,
`core/projections/dbt/materialize.py`, `core/projector.py`, `core/projection_readiness.py`,
`core/transformation_candidates.py`
**Implementation:** `PolicyIssue.projection_blocking`, `ReleasePlan.projection_blocking_rules`,
`evaluate_transformation_readiness`

### Context

DD-118's `identity.contract-unverified` finding raised `PolicyNormalizationError` directly
during normalization, which unconditionally aborted dbt generation — including ordinary,
non-strict `project` runs and `check-projection` — long before any release or strict
evaluation occurred. `evaluate_transformation_readiness` carried the same finding as an
unconditional blocker for every stage, including `mapping`, even though a contracted
transformation's output identity is release/strict-release evidence, not a generation
prerequisite. This made bootstrap generation and everyday mapping/silver readiness checks
fail for a condition (no warehouse evidence yet) that is expected and normal before a
contract has ever been run against a real warehouse.

### Decision

`identity.contract-unverified` is now raised as a `PolicyIssue` (`blocking=True`,
`projection_blocking=False`) instead of a hard `PolicyNormalizationError`. `PolicyIssue`
gains a `projection_blocking` field (default `True`, preserving existing blocker semantics
for every other rule). `ReleasePlan` gains `projection_blocking_rules` — the subset of
`blocking_rules` where `projection_blocking` is true — computed alongside the existing,
unchanged `blocking_rules`/`blocking_reasons` used for DD-114/DD-115 strict-release
evaluation. `_collected_blocker_diagnostics` and `run_projections`'s `check_only` path use
`projection_blocking_rules` to decide pass/fail and diagnostic severity
(`error`/`blocking=True` vs `warning`/`blocking=False`), so ordinary generation and
`check-projection` proceed and surface the finding as a non-blocking diagnostic, while
`project --strict` and release evaluation still fail on it exactly as before (`blocking_rules`
and the `__release_data__.policy_issues` feed into `evaluate_release` unchanged).
`check_projection` in `projection_readiness.py` now always collects a plan's supplied
diagnostics, not only when the plan's status is `"error"`, so review-only diagnostics from a
`"ready"` plan are still reported.

`evaluate_transformation_readiness` mirrors this split for contracted-transformation
readiness: identity-unverified is included in the human-readable `reasons` for every stage,
but only added to the internal blocking-reasons set (and therefore `is_blocking`) when
`stage == "release"`. `mapping`/`silver` readiness — including an otherwise fully in-scope
contract matched by `table_scope` — passes on this reason alone; genuine authored/policy
problems (missing/incomplete decision evidence, contract-sync drift, and, for
`silver`/`release`, incomplete replacement-scope completion) remain blocking at every stage,
unchanged. No evidence is synthesized, waived, or hash-matched incorrectly by this change —
only the failure's blocking scope narrows.

### Rationale

Release/strict-release evaluation (DD-114/DD-115) is the correct, single place to enforce
"no unverified contract identity ships" — it already consumes `blocking_rules` untouched. Any
other consumer that unconditionally blocks on `identity.contract-unverified` duplicates that
gate in a way that stops ordinary, iterative generation before a warehouse has ever run the
contract's tests, which is the normal bootstrap state, not an error.

### Consequences

- Ordinary `project` (non-strict) and `check-projection` succeed with unverified contract
  identity and report it as a `warning`/non-blocking diagnostic; `project --strict` and
  release evaluation remain blocked until current, passing evidence is captured.
- `check-transformation-readiness --stage mapping` (and `silver`, for this reason alone)
  passes for a contract with unverified identity; `--stage release` still blocks.
- Every other `PolicyIssue` and transformation-readiness reason keeps its prior blocking
  behavior; only `identity.contract-unverified` changes scope.
