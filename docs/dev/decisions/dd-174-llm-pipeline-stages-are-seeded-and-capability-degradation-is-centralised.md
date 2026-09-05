# DD-174: LLM pipeline stages are seeded, and capability degradation is centralised

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `propose-alignment`, `analyse-sources`, `discovery-conformance judge`
**Implementation:** `core/ai_provider.py` (`resolve_ai_seed`, `create_chat_completion`), `tests/test_ai_determinism_guard.py`

### Context

The LLM stages are analysis, not authorship: the same evidence should yield the same
proposal on Tuesday as on Monday, or a re-run silently rewrites a model a human already
reviewed. Measured on one domain, three identical runs mapped 21, 26 and 25 columns.

Three defects underlay this, all invisible to review:

1. `temperature=0.1` had never taken effect on the reasoning tier. Those models reject the
   parameter outright; the provider wrapper caught the rejection and retried without it.
   The setting read as variance control and was a no-op.
2. The affinity and judgment stages called `chat.completions.create` directly, bypassing
   that wrapper. They worked only because they happened to point at a model tolerating
   `temperature`; repointing either at a reasoning model was a hard 400.
3. The discovery round-trip was paid once per source table, not once per model.

Measured on this provider: `temperature` and `top_p` rejected on the reasoning tier,
`seed` accepted on every model, and with a seed 3/3 completions byte-identical against
3/3 different without.

### Decision

Every pipeline completion passes `seed=resolve_ai_seed(role)`, resolving
`KAIROS_AI_{ROLE}_SEED` then `KAIROS_AI_SEED` then `DEFAULT_AI_SEED`, where `off` disables
seeding so run-to-run variation can still be measured deliberately and a non-integer value
raises rather than silently unseeding. Every stage routes through `create_chat_completion`,
which now remembers a per-model parameter rejection for the process.

### Consequences

Seeding is best-effort by construction: it removes sampling noise, not the effect of a
changed prompt, model or provider backend. This provider returns no `system_fingerprint`,
so a backend change is undetectable from the response — which is why the seed is recorded
next to the model in artifact provenance rather than assumed. A source-level guard fails
any new stage that forgets either the seed or the wrapper.
