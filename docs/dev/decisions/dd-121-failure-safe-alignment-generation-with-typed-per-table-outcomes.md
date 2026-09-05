# DD-121: Failure-Safe Alignment Generation with Typed Per-Table Outcomes

**Status:** Accepted
**Date:** 2026-07-27
**Affects:** `core/propose_alignment.py`, `core/ai_provider.py`,
`core/claim_registry.py`, `core/migrate_claims.py`, `core/completeness_model.py`,
`core/claim_coverage.py`, `cli/main.py`
**Implementation:** `TableAlignment.generation_outcome`/`generation_provider`/
`generation_model`/`generation_error`, `OUTCOME_SEMANTIC_SUCCESS` /
`OUTCOME_PROVIDER_FAILURE` / `OUTCOME_FALLBACK_ONLY`, `AlignmentTotalFailureError`,
`ClaimRegistry.generation_outcomes` (`GenerationOutcome`), `ClaimCheckReport
.incomplete_generation`, `propose-alignment --allow-fallback-output`,
`ai_provider.create_chat_completion`/`sanitize_provider_error`

### Context

`propose-alignment`'s LLM call for a table could fail (provider outage, timeout,
malformed response) or run with zero reference classes to align against (fallback
only, no LLM call at all), and both cases previously looked identical to a genuine
semantic result: the domain claims file was written unconditionally, with no signal
that a table's alignment was incomplete or never actually generated. A total
provider outage across every table in a run still exited 0 and reported success.
There was also no capability-aware handling for a provider rejecting an unsupported
request parameter — any such rejection surfaced as a raw exception.

### Decision

`align_table()` and the per-table pipeline now classify every table into one of
three typed outcomes — `semantic_success`, `provider_failure` (LLM call raised),
or `fallback_only` (no reference classes were available, so the LLM was never
called) — carried on `TableAlignment` plus sanitized `generation_provider`/
`generation_model`/`generation_error` (via `ai_provider.sanitize_provider_error`,
which redacts API keys/bearer tokens and caps message length). `alignment_to_dict`
only emits these fields when the outcome is not `semantic_success`, preserving a
byte-identical happy-path serialization.

A run-level tally (`run_attempted`, `run_semantic_success`, `run_provider_failures`)
drives three behaviors: (1) a failed table's per-table dict is never cached, so a
transient provider outage is retried on the next run instead of being persisted as
a permanent result; (2) a domain where every table came back `provider_failure` is
never written, and failed tables are always reported (not gated behind `--verbose`);
(3) when every attempted table across the whole run fails, `_propose_alignments`
raises `AlignmentTotalFailureError` after flushing the cache — the CLI catches this
distinctly from `EnvironmentError`/`ValueError`, prints no success line, and exits
1. A domain whose tables are 100% `fallback_only` is skipped by default (an
all-placeholder registry must never masquerade as a real proposal); the new
`--allow-fallback-output` flag opts into writing it anyway, with its
`generation_outcomes` recording the incomplete status.

`ClaimRegistry` gains an additive `generation_outcomes: list[GenerationOutcome]`
field (empty list omitted from serialization, matching the schema's existing
sparse-optional convention), populated by `migrate_claims.alignment_to_registry`
from each table's non-success `generation_outcome` key, and threaded through
`merge_preserving_decisions` as fresh per-run reliability metadata (never a curated
decision, so it is always taken from the new run like `coverage`/`freshness`).
`claim_coverage.evaluate_claims_coverage` renders any non-success outcome as a
`ClaimCheckReport.incomplete_generation` warning — included in `has_warnings` but
deliberately excluded from `is_blocking`, since this is a *semantic-generation
completeness* signal distinct from the structural claim validity the gate already
enforces (a table can be structurally valid while still lacking real semantic
content). This is additive to, and does not rewrite, the gate's existing blocking
composition or the separate ontology-binding/release-eligibility notion of
"semantic generation completeness" introduced by the concurrent claim-gates work
(`claim_check_result.py`).

`ai_provider.create_chat_completion` centralizes unsupported-request-parameter
handling: on a provider error that names a specific unsupported parameter, it drops
that one parameter and retries exactly once (no hard-coded per-model capability
table); any other error, or a second failure after the retry, propagates unchanged.
`propose-alignment` preflights the effective role model via
`resolve_provider_config`/`resolve_role_model` before per-table fan-out and reports
it up front, so a misconfiguration is visible before cost is incurred rather than
discovered mid-run on the first table.

### Rationale

Treating "the LLM call did not happen" and "the LLM call happened and produced a
real semantic result" as distinguishable, typed outcomes — rather than both
collapsing into "here is a claims file" — is the only way to prevent an incomplete
or failed run from being indistinguishable from a trustworthy one downstream. Not
caching failures keeps transient provider issues self-healing on retry. Making
total failure a distinct, loud, non-zero-exit condition (never printing success)
follows the same never-invent-success discipline as the rest of the toolkit's
typed-report conventions (DD-106–DD-115, DD-120). Keeping the new fields additive
(sparse, non-empty-only) and the new gate signal warning-only avoids destabilizing
any existing registry, gate, or the concurrent claim-gates work's own composition.

### Consequences

- Existing `propose-alignment` runs where every table succeeds are byte-identical
  (no new keys emitted, no new CLI output beyond the model preflight line).
- A domain with all tables `fallback_only` is no longer written by default — a
  behavioral change from writing an all-placeholder registry unconditionally;
  `--allow-fallback-output` restores the old file-producing behavior explicitly.
- A total-failure run now exits 1 instead of 0; callers/scripts relying on the old
  silent-success behavior on total outage must handle the new exit code.
- `check-claims` output gains a non-blocking `incomplete_generation` warning
  section; existing blocking behavior (`is_blocking`, exit code) is unchanged.
- **Superseded in part by DD-128:** the per-domain write gate alone did not cover a
  domain mixing `provider_failure` with `fallback_only` tables, nor an opted-in
  fallback-only domain. Writes are now staged and committed only after the run-wide
  verdict, so `AlignmentTotalFailureError` guarantees *no* registry was written by
  the run. DD-128 also makes the preflight's provider config endpoint/auth-only —
  the caller-resolved model is authoritative and is never re-derived from
  `KAIROS_AI_{ROLE}_MODEL` here.
