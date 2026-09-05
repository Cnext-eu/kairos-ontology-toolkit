# DD-159: LLM Judgment Steps Must Never Auto-Degrade

**Status:** Accepted
**Date:** 2026-07-28
**Affects:** `core/ai_provider.py`, `core/ai_preflight.py`,
`core/generation_outcome.py`, `core/propose_alignment.py`,
`core/analyse_sources.py`, `cli/inspection.py` (`check-ai-config`),
`cli/sources.py`
**Implementation:** `AIProviderError`/`NotConfigured`/`Misconfigured`/`Unreachable`
exception hierarchy, `require_ai_provider`/`preflight_ai_provider`,
`check-ai-config` command, `analyse-sources` total-failure guard
(`AffinityTotalFailureError`), `propose-alignment` preflight via
`require_ai_provider`, skill gate 0 (autopilot Stage 0 pre-flight, mapping
Gate 0, source step 11)

### Context

An LLM judgment step (source affinity analysis, alignment proposal) could
previously fall through to a heuristic or a plausible-empty result when the AI
provider was missing, misconfigured, or unreachable.  The toolkit's
`analyse-sources` even cached fabricated fallback domains at `confidence: 0.0`
as if they were real results, poisoning subsequent runs from cache.  The wrong
CLI flag name (`--allow-fallback-registry` instead of `--allow-fallback-output`)
was also documented in error messages and design docs, sending users to a flag
that does not exist.

### Decision

The toolkit now treats any LLM judgment step as a three-tier policy:

1. **Mechanical** — deterministic passes (imports, vocabulary parsing, lexical
   matching) are always available and are not a "fallback."
2. **Judgment** — the LLM is the sole authority.  It must either run or fail fast
   with a typed `AIProviderError`.  It must never auto-degrade to a heuristic or
   produce plausible-empty output.  `require_ai_provider` is the raising
   preflight gates at the entry of each judgment loop.
3. **Blocked** — explicitly-invalid sentinels (`domain: ""`, `confidence: null`,
   `generation_*` keys on `TableAssignment`) or nothing.  Never plausible.

`ai_preflight.require_ai_provider(role, *, model, probe=False)` is the single
raising wrapper commands call before entering a judgment loop.  It returns the
resolved `AIProviderConfig` so callers do not need a second
`resolve_provider_config` call.  `preflight_ai_provider` / `preflight_all_roles`
never raise for config reasons — they return statuses
(`ok` / `not_configured` / `misconfigured` / `unreachable` / `unprobed`) — so
the `check-ai-config` diagnostic command can report without crashing.

A new `check-ai-config` CLI command prints per-role status with computed
remediation, supports `--format text|json`, `--role`, `--model`, `--probe`,
`--strict`, and never prints secret values (env var names only, no `api_key`
field in JSON).  Probe stays opt-in on working commands (`--preflight-probe`);
`check-ai-config` defaults to `--probe` because it is a diagnostic.

`analyse-sources` now: (1) never caches a failed table
(`generation_outcome == SEMANTIC_SUCCESS` gate); (2) records typed outcomes
(`generation_outcome`/`generation_error`/`generation_provider`/`generation_model`)
on `TableAssignment`; (3) hoists the client and prefights before the cost banner;
(4) stages writes and raises `AffinityTotalFailureError` on total failure (exits
1, caught in `cli/sources.py`).  Failed tables persist with `domain: ""` +
`confidence: null` + `generation_*` keys, so both downstream readers skip them
automatically.

`propose-alignment` calls `require_ai_provider` before per-table fan-out and
deleted the old `except EnvironmentError` swallow that silently fell through to
heuristic mode.  The wrong flag name `--allow-fallback-registry` was corrected
to `--allow-fallback-output` everywhere (code, docs, changelog, tests).
`require_ai_provider` now returns the resolved provider config, eliminating the
second `resolve_provider_config` call (and the need to mock it separately in
tests).

Skill documents pin the preflight as a hard gate:
`kairos-flow-autopilot` Stage 0 pre-flight with a **STOP** guardrail,
`kairos-design-mapping` Gate 0, `kairos-design-source` step 11 amendment.

### Rationale

A tool that silently substitutes a heuristic for an LLM judgment step produces
output that looks trustworthy but is not.  The only safe policy is fail-fast:
surface the missing/misconfigured provider up front with a one-line remediation,
and never let a judgment step fall through to plausible-empty output.  Typed
exceptions (subclassing `EnvironmentError`) preserve existing catch sites and
test assertions.  The preflight-then-return pattern avoids a double env lookup
and keeps the test surface minimal (one mock instead of two).

### Consequences

- `analyse-sources` exits 1 on total provider failure (was 0).  Partial failure
    still exits 0 with a visible warning.
- `*-affinity.yaml` gains optional `generation_*` keys and `domain: ""` for
    failed tables.  `schema_version` stays 2.  External consumers assuming every
    table has a non-empty domain will break.
- A hub with `KAIROS_AI_{ROLE}_ENDPOINT` and no `_KEY` now errors instead of
    401-ing every call.  Opt out with `_KEY=none`.
- The wrong flag name `--allow-fallback-registry` is gone from all surfaces.
