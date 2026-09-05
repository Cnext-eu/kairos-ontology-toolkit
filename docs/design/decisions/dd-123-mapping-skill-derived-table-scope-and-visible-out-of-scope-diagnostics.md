# DD-123: Mapping-Skill-Derived Table Scope and Visible Out-of-Scope Diagnostics

**Status:** Accepted
**Date:** 2026-07-26
**Affects:** `.github/skills/kairos-design-mapping/SKILL.md` (and its scaffold copy),
`core/transformation_candidates.py`
**Implementation:** `evaluate_transformation_readiness`'s implemented-contract loop

### Context

Gate 6 of **kairos-design-mapping** invoked `check-transformation-readiness --stage
mapping` with no `--table` scope, even though the command already accepted a repeatable
`--table` option and `evaluate_transformation_readiness` already treated direct
table/virtual-source overlap as the sole scope authority (DD-107/DD-118/DD-119). Every
Gate 6 run therefore evaluated the whole hub's contracts, so an unrelated domain's blocked
transformation (e.g. missing decision evidence) could be confused for a blocker on the
table this mapping session actually confirmed, and there was no persisted place to reuse a
derived scope across a pause/resume.

Separately, `evaluate_transformation_readiness`'s loop over discovered (non-inventoried)
dbt contracts skipped a contract entirely (`continue`) when it did not overlap the
requested `table_scope`, rather than surfacing it as a non-blocking diagnostic the way an
out-of-scope inventoried candidate already did. A blocked contract for another domain
simply vanished from a scoped report instead of remaining visible for awareness.

### Decision

**Skill:** Phase 1 (Table-to-Entity Alignment) of `kairos-design-mapping` now derives a
**Confirmed table scope** list — the absolute source-table/virtual-source IRI of every row
confirmed to an entity, excluding `operational`/`deprecated`/`out-of-scope`/`gap` rows —
and persists it in the phase log (`phases/mapping/<source>-to-<domain>.md`) so a resumed
session reuses it verbatim instead of re-deriving it. Gate 6 now passes this list as a
repeatable `--table` per confirmed IRI to `check-transformation-readiness --stage
mapping`. The scope is never widened by following FK/dependency relationships to other
tables — direct table/virtual-source overlap remains the sole authority, matching the
existing evaluator. Unscoped invocation (no `--table`) remains reserved for hub-wide
status/release checks (**kairos-diagnose-status**, **kairos-flow**, `check-release`); the
mapping skill never drops its scope to route around an unrelated blocker.

**Evaluator:** the implemented-contract loop in `evaluate_transformation_readiness` no
longer skips a non-overlapping contract outright. It now evaluates the contract's reasons
exactly as before but records `is_blocking = in_scope and bool(blocking_reasons)`, where
`in_scope` is the existing `_contract_overlaps_table_scope` result. An out-of-scope
contract's blocking reasons (evidence, sync, identity, replacement completion) stay in its
`reasons` tuple for review; only its contribution to `is_blocking`/`report.is_blocking` is
suppressed. When `table_scope` is empty (the unscoped hub-status/release path),
`_contract_overlaps_table_scope` still returns `True` for every contract, so unscoped
behavior is unchanged byte-for-byte.

### Rationale

Deriving the `--table` scope from the same Table Alignment Proposal the user already
confirmed avoids inventing a second, hand-maintained scope list, and persisting it keeps a
resumed session from silently re-scoping mid-flow. Making out-of-scope blockers visible
but non-blocking mirrors the treatment inventory candidates already receive for the
`accepted` status (DD-119's own precedent), so scoped and inventoried findings behave
consistently instead of one path silently dropping information the other already surfaces.

### Consequences

- `test_scoped_readiness_ignores_unrelated_noninventoried_contract` is renamed to
  `test_scoped_readiness_surfaces_unrelated_contract_as_nonblocking_diagnostic` and now
  asserts the unrelated contract is present with `is_blocking is False` and non-empty
  `reasons`, instead of an empty `candidates` tuple.
- A new two-domain regression
  (`test_two_domain_scope_isolates_blocked_domain_from_ready_domain`) confirms one domain's
  blocked contract stays a non-blocking diagnostic while a second domain's scoped,
  contract-clean tables remain mapping-ready, and that an in-scope contract whose only
  issue is unverified identity still follows the DD-119 release-only semantics in this
  multi-domain setting.
- No change to `--stage silver`/`--stage release` blocking semantics for in-scope
  contracts, to candidate-based (inventoried) readiness, or to any consumer that already
  passes an empty/no `table_scope`.
