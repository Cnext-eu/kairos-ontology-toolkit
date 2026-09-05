# DD-184: LLM calls are traced to Langfuse, opt-in, with source values masked

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `propose-alignment`, `analyse-sources`, `discovery-conformance judge`
**Implementation:** `core/tracing.py`, `core/ai_provider.py` (`_openai_class`, `create_chat_completion`)

### Context

Three pipeline stages call a model, and the only durable record was a progress
line plus, on failure, a sanitized error. Diagnosing a questionable mapping meant
re-running the stage under a purpose-written instrumentation script — which is
exactly what it took to discover that `companies` was prompted twice, that its
first shortlist omitted `TradeParty`, and that the retry tripled the token cost.
That should not have required a bespoke harness.

### Decision

Tracing uses Langfuse's OpenAI drop-in wrapper rather than hand-rolled spans, so
model name, token usage and the `generation` observation type are captured
without the call sites knowing tracing exists. `_openai_class()` returns the
instrumented client when tracing is live and the plain one otherwise; nothing in
`create_chat_completion` branches on it beyond attaching `name`/`metadata`, which
only the wrapper accepts.

Calls are grouped by a per-invocation **session id** rather than a parent span.
Alignment fans out across threads, where a context-manager span does not reliably
parent concurrent work, and sessions are the SDK's documented mechanism for
grouping logically-connected traces.

Three properties are non-negotiable and each is pinned by test:

1. **Off unless configured.** All of `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`
   and `LANGFUSE_HOST` must be set. There is deliberately no default host, so a
   hub cannot ship traces anywhere by accident.
2. **Source values masked by default.** Alignment prompts carry real sample data
   from client tables. It already passes the `source-privacy` gate, but "not
   personal" is not "safe to send to a third party". The mask strips the
   `| samples: …` block and keeps column names, types, the reference classes
   offered, the instructions and the model's full response — nearly all the
   diagnostic value at none of the egress. `KAIROS_LANGFUSE_SEND_SAMPLES=1` opts
   in, which is reasonable for a self-hosted collector and a deliberate act
   either way.
3. **Never fails a run.** A missing package, an unreachable collector or a broken
   constructor logs at info level and continues untraced. Observability that can
   break a pipeline is worse than none.

An autouse fixture clears the Langfuse variables and the memoised client around
every test: tracing activates purely from the environment, so a developer with
real credentials in their shell would otherwise export fixture data to a live
project simply by running pytest.

### Consequences

Metadata carries what the earlier bespoke harness had to reconstruct — role,
table, source-column count, candidate-class count, resolved anchor override,
likely entity, and any dropped schema enum — plus the seed and reasoning effort
already recorded for provenance (DD-178). Filtering "every alignment call on a
table where the schema enum was dropped" becomes a query rather than a re-run.

`flush_tracing()` is called before `_propose_alignments` returns. These are
short-lived CLI processes; without it the buffered events are lost at exit and
the run appears never to have happened.

What this does **not** yet cover: the affinity and judgment stages get the traced
client for free through `get_ai_client`, but do not pass `trace_name`/
`trace_metadata`, so their calls arrive with default names and no role tag.
