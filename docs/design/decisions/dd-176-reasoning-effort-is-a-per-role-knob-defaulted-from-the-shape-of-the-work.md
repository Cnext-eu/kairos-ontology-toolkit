# DD-176: Reasoning effort is a per-role knob, defaulted from the shape of the work

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `propose-alignment`, `analyse-sources`, `discovery-conformance judge`
**Implementation:** `core/ai_provider.py` (`resolve_reasoning_effort`, `DEFAULT_REASONING_EFFORT`)

### Context

The reasoning-tier models accept a `reasoning_effort` parameter, and the pipeline's three
LLM stages do genuinely different work. Affinity is a one-of-N pick over a short candidate
list, made once per source table — the highest-volume call and the one least helped by
extended reasoning. Alignment and judgment are closed-vocabulary reasoning over a large
candidate set, where a wrong answer is silently wrong.

### Decision

`resolve_reasoning_effort` resolves exactly like the seed (DD-174):
`KAIROS_AI_{ROLE}_REASONING_EFFORT`, then `KAIROS_AI_REASONING_EFFORT`, then a per-role
default of `low` for affinity and `medium` for alignment and judgment. `off` sends no
`reasoning_effort` at all. An unrecognised tier raises rather than being passed through,
so a typo fails at the first call instead of silently reverting to the model's default.

`create_chat_completion` drops `None`-valued kwargs, so a disabled knob is absent from the
request rather than sent as null.

### Consequences

These are defaults, not findings. Effort trades latency against recall, and recall is the
weak axis here — roughly a quarter of source columns map. They should be changed from
measurement, not intuition.

One measurement already argues against reaching for the cheap tier: `gpt-5.6-terra` at
`low` scored 63% stability and 21.7 columns mapped on the party domain, against 80% and 23
for `gpt-5.5` at its default. Speed was the only axis on which the cheaper configuration
won.
