# DD-203: The affinity AI-provider role collapses into alignment: one configured provider for every pre-modeling call

**Status:** Accepted
**Date:** 2026-08-20
**Affects:** `ROLE_AFFINITY` (removed), `AI_ENV_VAR_NAMES`, `DEFAULT_REASONING_EFFORT` (`core/ai_provider.py`); `preflight_all_roles` default (`core/ai_preflight.py`); `_get_openai_client` (`core/analyse_sources.py`); `--model` default (`cli/sources.py`); `--role` choice, `check-ai-config` role list (`cli/inspection.py`)
**Issue:** #562 (Problem 2)

### Context

`analyse-sources` (coarse table → domain classification) and
`propose-alignment` (closed-vocabulary reasoning: pick the right `ref_class`,
map every column) had separate AI-provider roles — `affinity` and
`alignment` — each independently configurable (`KAIROS_AI_{ROLE}_ENDPOINT`/
`_KEY`/`_MODEL`/`_SEED`/`_REASONING_EFFORT`), with `affinity` defaulting to
the cheapest reasoning-effort tier on the theory that a high-volume,
coarse classification call is the one least helped by extended reasoning.
On real hubs this bought nothing measurable and cost real configuration
surface: two providers/models to set up and keep from drifting apart for
what is, at both granularities, the same closed-vocabulary reasoning
problem against the same reference-model catalog. The request (issue #562)
was explicit: keep one role, the strongest configured provider, for every
pre-modeling LLM call.

### Decision

`ROLE_AFFINITY` is removed outright — a hard removal, not a same-string
shim. A shim would silently stop reading `KAIROS_AI_AFFINITY_*` env vars
while pretending compatibility, which is worse than an honest break: an
operator with `KAIROS_AI_AFFINITY_MODEL` set would see it silently ignored
rather than get a clear, greppable rename to `KAIROS_AI_ALIGNMENT_*`.
`_get_openai_client` (`analyse_sources.py`) now calls
`require_ai_provider`/`get_ai_client` with `ROLE_ALIGNMENT`; `cli/sources.py`'s
model-default resolution and `DEFAULT_REASONING_EFFORT`/`AI_ENV_VAR_NAMES`
in `ai_provider.py` drop the affinity entry entirely; `preflight_all_roles`'s
default `roles` tuple becomes `(ROLE_ALIGNMENT,)`; `check-ai-config`'s
`--role` choice drops `"affinity"` (now `alignment`/`all`, both meaning the
same single role today). `ROLE_JUDGMENT` (archetype-conformance) is
untouched — it was never part of this collapse.

### Consequences

This is a deliberate behavior change, not a rename: `analyse-sources`'s
default reasoning effort rises from `low` to `medium` (alignment's tier),
and any `KAIROS_AI_ALIGNMENT_*` tuning now also governs the high-volume
affinity-classification call — cost and latency go up for that call by
design. A hub with `KAIROS_AI_AFFINITY_*` env vars set sees them silently
stop applying (no error, no warning) — the honest cost of a hard removal
over a compatibility shim, accepted because the alternative (pretending to
read a var that no longer does anything) is worse. `analyse-sources` and
`propose-alignment` now share one configured endpoint/model/seed/effort,
matching how a `check-ai-config` operator already thinks about "the AI
provider" for this hub.
