# DD-128: Intent-Preserving Coverage Classification, Run-Atomic Registry Writes, and Authoritative Model Precedence

**Status:** Accepted
**Date:** 2026-07-26
**Affects:** `core/claim_coverage.py`, `core/claim_registry.py`, `core/lifecycle_gate.py`,
`core/propose_alignment.py`, `cli/main.py` (`check-claims`, `propose-alignment`)
**Implementation:** `ClaimCheckReport.unresolved_anchor_tables`,
`claim_registry.ANCHOR_STATE_UNRESOLVED`, the staged-write commit phase in
`_propose_alignments`, the provider preflight in `_propose_alignments`

### Context

Three defects surfaced in review of the RC7 lifecycle work (DD-121, DD-122, DD-124):

1. **Intent lost in the coverage gate.** DD-124 makes an unresolved-anchor table emit
   *zero* claims and *zero* covered columns on purpose. DD-121/F6's column-omission gate
   compares registry-covered columns against the affinity `total_columns` and therefore
   read that deliberate emptiness as a **blocking** truncation ("columns were dropped
   before the Claim Registry"), telling the operator to re-run `propose-alignment` for a
   condition re-running can never fix.
2. **A write that contradicted the failure contract.** `AlignmentTotalFailureError` states
   that no registry was written. The per-domain write gate only skipped a domain that was
   *entirely* `provider_failure` or *entirely* `fallback_only`, so a domain **mixing** the
   two (e.g. one table with an ambiguous anchor, one whose provider call failed) — and an
   opted-in `--allow-fallback-output` domain — was written inside the loop, before the
   run-wide verdict existed. The error then claimed nothing had been written.
3. **Model precedence inverted.** `propose_alignment_cmd` resolves model precedence
   (explicit `--model` > `--high-accuracy` preset > `KAIROS_AI_ALIGNMENT_MODEL` >
   default), but `_propose_alignments`' provider preflight reassigned
   `model = provider_config.model`, re-applying `resolve_role_model` and letting the env
   override silently beat an explicitly pinned model — for the real LLM calls, the cache
   params hash, and the recorded `model_used`.

### Decision

**(1) Deliberate emptiness is classified as its own fact.** `claim_registry` names the
state (`ANCHOR_STATE_UNRESOLVED`), and the F6 comparison in
`claim_coverage.evaluate_claims_coverage` skips any table whose registry coverage carries
it. Such tables are reported in a new, **non-blocking**
`ClaimCheckReport.unresolved_anchor_tables` facet (domain → `"system.table (class anchor
unresolved — no claims emitted for N source column(s))"`), included in `has_warnings`,
excluded from `is_blocking`, projected additively into `_claim_report_to_dict` (hence
`check-claims --format json`), and rendered by `check-claims` with remediation that points
at the anchor decision (`{domain}-unresolved-anchors.yaml` / the conformance artifact) —
not at a re-run. Genuine omissions still block, including for a domain that has both.

**(2) Registry writes are run-atomic.** `_propose_alignments` no longer writes inside the
per-domain loop. Each eligible domain is *staged* (registry + unresolved-anchors document,
in domain order, alongside freshness-cache-skipped domains so the returned path order is
unchanged) and committed only **after** the run-wide tally is known and the total-failure
check has passed. The no-write guarantee therefore holds for every total-semantic-failure
run — mixed domains and opted-in fallback-only domains included — and pre-existing files
are never touched by a failed run. The per-domain gates are retained: they still skip
all-`provider_failure` and (without opt-in) all-`fallback_only` domains, and still report
why.

**(3) The caller-resolved model is authoritative.** The preflight keeps
`resolve_provider_config` for provider/endpoint/auth discovery and reporting, but never
reassigns `model`. When the per-role override differs from the caller's model, a verbose
note says it was not applied. `KAIROS_AI_ALIGNMENT_MODEL` keeps its documented role as the
*default* — the CLI still applies it when neither `--model` nor `--high-accuracy` pins one.

### Rationale

A governance gate that cannot distinguish "intentionally empty" from "silently truncated"
trains operators to ignore it; naming the intent (rather than widening the blocking rule)
keeps truncation integrity strict while making the pending anchor decision actionable.
Staging writes is the only way to make the error message and the filesystem agree without
either weakening the message or inventing a rollback of files already written — the run
simply has no side effect until its verdict is known. And precedence must be decided in
exactly one place: the caller that knows whether the operator pinned a model, since an
environment default silently overriding an explicit flag is indistinguishable from a bug
at the point of use.

### Consequences

- `check-claims` gains a non-blocking `⚠ Unresolved class anchors` section and an additive
  `registry.unresolved_anchor_tables` JSON key (additive → no
  `CLAIM_CHECK_RESULT_SCHEMA_VERSION` bump). Registries written before the `"unresolved"`
  anchor state existed never carry one, so their classification is unchanged.
- A domain whose only shortfall was an unresolved anchor no longer blocks `check-claims`;
  it now reaches the ordinary freshness bucketing (`ok`/`stale`/`unverifiable`).
- `propose-alignment`'s `✓ Written` / `🧭 Unresolved anchors` lines are now printed after
  all domains are processed (the commit phase), not interleaved with per-domain analysis.
  Returned paths, file contents, and per-domain skip reporting are unchanged.
- On total semantic failure, an opted-in (`--allow-fallback-output`) fallback-only domain
  is no longer written — a deliberate narrowing of DD-121's stated behavior, in favor of the
  stronger, uniform no-write guarantee.
- `KAIROS_AI_ALIGNMENT_MODEL` no longer overrides `--model`/`--high-accuracy`; a hub that
  relied on it winning must drop the explicit flag (its default behavior is unchanged).
- New tests: `tests/test_claim_coverage.py::TestUnresolvedAnchorCoverage`,
  `tests/test_propose_alignment.py::TestTotalFailureNoWriteGuarantee`, and
  `tests/test_propose_alignment.py::TestModelPrecedence`.
