# DD-177: The alignment answer is shape-constrained, so a column cannot be skipped

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `propose-alignment`
**Implementation:** `core/propose_alignment.py` (`build_alignment_response_schema`, `normalize_schema_response`), `core/ai_provider.py` (`param_fallbacks`)

### Context

Alignment asked for `{"type": "json_object"}`, which guarantees parseable JSON
and nothing else. Under it the model may simply leave a column out of its answer,
and measurement showed that is exactly what it did — inconsistently.

Three identical runs of the party domain mapped 24, 22 and 23 columns with **zero**
disagreement about what the shared columns meant. The instability was never in the
model's judgement; it was in which columns the model bothered to answer for.

The earlier variance work took stability from 62% to 80% — a fixed seed (DD-174),
then a reproducible prompt (DD-175) — but could not close it. Seeding turns out not
to survive a real prompt: on the 23 KB alignment prompt, one seed produced three
distinct completions from both `gpt-5.5` and `gpt-5.6-terra`, where the same seed on
a short prompt is byte-identical. Provider-side determinism is simply not on offer at
this size, so the remaining lever is the shape of the answer.

### Decision

`column_alignments` is a JSON-schema **object keyed by source column name**, with every
key in `required` and `additionalProperties` false — not an array. Omitting a column
then violates the schema, so the model must return a verdict for each one; a
duplicated or invented column name is impossible for the same reason. `null` remains
a legal `ref_property`, because forcing a *verdict* must not become forcing a
*mapping* — that would be a worse failure than silence.

`ref_property` and `ref_class` are enum-constrained to terms drawn from the same
inventory the prompt renders, so the enum and the prose cannot disagree and a
hallucinated property is unrepresentable rather than caught afterwards (DD-170).

Provider limits, measured by bisection against the live endpoint: at most 1,000 enum
values *in total across one schema*, and `$defs`/`$ref` is required because inlining
the verdict per column exceeds a separate total-size limit at realistic widths. "In
total" is the trap — the class enum is emitted twice and every nullable enum carries
its own `null` — so the property enum takes what remains of a shared budget rather
than a fixed cap. An enum that does not fit is dropped and reported in the returned
notes, never silently.

`create_chat_completion` gains `param_fallbacks`: a model rejecting the strict schema
falls back to plain JSON mode instead of losing the constraint entirely.

### Consequences

Party-domain stability rose from 62-80% to **82-100%** across repeated three-run trials
(100%, 96%, 82% — the byte-identical trial was a favourable draw, not the expected
outcome). Recall improved at the same time, from a drifting 22-24 columns to 24-26.
Forcing a verdict per column recovers the ones the model used to drop.

This is the fix the seed could not be, but it is not determinism. Reruns of the same
configuration still differ, so a re-run may still change a model a human has reviewed;
what the schema removes is the *silent* form of that drift, where a column disappeared
from the answer entirely rather than being answered "no match". The seed and the stable
prompt remain necessary, because a stable question is what makes a stable answer
meaningful.

One confound worth recording: runs whose `--analysis` directory already contained a
previous run's output scored 82%, against 96% from pristine inputs. Prior output appears
to influence the next run, which is a separate thread to pull.

The response shape changes only how the answer is obtained. `normalize_schema_response`
converts the object back to the historical list of per-column dicts, so every consumer
downstream is untouched, and a list response — the JSON-mode fallback path — passes
through unchanged.
