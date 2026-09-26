# DD-242: One command run is one trace of task spans, and OpenTelemetry export is opt-in

**Status:** Accepted
**Date:** 2026-09-26
**Affects:** `compile`, `emit-gold`, `package-powerbi-release`, `project`, `validate-dbt`, the run log, `kairos-ontology logs show`
**Issue:** #1011
**Implementation:** `src/kairos_ontology/core/observability/spans.py`, `src/kairos_ontology/core/observability/otel.py`, `src/kairos_ontology/cli/main.py`, `src/kairos_ontology/cli/logs.py`

### Context

#1011's first part made every diagnostic a structured `kairos.diagnostic.reported` record and
gave writing commands a default run log. Four gaps remained:

1. **No structure.** A record carried a `kairos.task` and a `kairos.gate` string. Nothing said
   which gate ran inside which domain, or how long each one took. The perf work behind #598 had
   to time gates by hand.
2. **The OpenTelemetry bridge exported nothing.** DD-151 Phase 4 installed an SDK
   `LoggingHandler()` with no `LoggerProvider`. The handler therefore fell back to the global
   no-op provider. `otel.py` built a `Resource` and threw it away, and it imported
   `TracerProvider` only as a probe. Setting `OTEL_EXPORTER_OTLP_ENDPOINT` changed nothing.
3. **Failing runs lost their record.** `_KairosGroup.invoke` re-raised `Exit`, `ClickException`,
   `Abort` and `SystemExit` before the observability teardown, and Click's result callback only
   runs on success. The runs with the most findings (a failing `compile`, and every `emit-gold`
   refusal) wrote no summary and never flushed the export. `log_run_summary` also wrote nothing
   when a run had no diagnostics, so a refusal that carried none, such as a Gold contract error,
   left no record of how the run ended.
4. **Findings that bypassed the log.** Several findings were printed but never logged:
   - compile gate refusals;
   - Fabric package and TMDL failures;
   - `emit-gold`'s unresolved-relationship, unresolved-bridge and insight-gap reports;
   - compile's deferred-bridge and stale-dependent notes;
   - `project`'s swallowed per-domain failure.

### Decision

**A run is a tree of spans.** The tree has five kinds:
- `run`: the command;
- `domain`: one compiled domain;
- `product`: a Gold product, `gold:<name>`;
- `gate`: a check that can refuse, named by its `core/gates.py` registry id where it has one;
- `stage`: a step that writes or renders (`emit`, `erd`, `archive`, `dbt.<phase>`).

`core/observability/spans.task_span` keeps its own ContextVar stack. When a span ends, it
writes one `kairos.span.completed` record (`kairos.console=False`) with its parent, kind, name,
duration, status and the diagnostics counted in its subtree. The status is `ok`, `refused` or
`error`. A gate that refuses and then raises to stop the command stays `refused`. Every
diagnostic record names its span in `kairos.span.id`. This works with no tracing SDK
installed, so the JSON run log alone carries the hierarchy and the durations.

**OpenTelemetry export is real, and still opt-in.**
- **Opt-in.** With `OTEL_EXPORTER_OTLP_ENDPOINT` set and the `[otel]` extra installed,
  `configure_otel` builds a `TracerProvider` and a `LoggerProvider` with OTLP exporters
  (`OTEL_EXPORTER_OTLP_PROTOCOL`: `http/protobuf` by default, or `grpc`). The endpoint variable
  is read before anything is imported, so a run without it never imports OpenTelemetry.
- **Spans.** Each Kairos span is also an OTel span and uses the OTel span id. Diagnostics become
  `kairos.diagnostic` span events.
- **Trace id.** The trace id **is** the run's operation id. A uuid4 hex is 128 bits and never
  zero, so a `kairos.operation.id` found in any log record is the trace to open.
- **Log records.** They go through the same `RedactionFilter` before export. Dict-valued extras
  such as `kairos.summary` are sent as JSON strings, on a copy of the record, so the run log
  after that handler still receives the structured value.
- **Isolation.** The providers are local to the invocation, with `shutdown_on_exit=False`, and
  are flushed and shut down at teardown. A second in-process invocation starts clean.

**Every exit tears down once.** `_KairosGroup.invoke` runs the teardown in a `finally` block,
guarded so it runs once, with the exit code taken from `Exit`, `ClickException`, `SystemExit` or
an unhandled exception. `kairos.run.summary` is always written. It now carries
`kairos.outcome` (`ok`/`failed`) and `kairos.exit_code`. The one exception is a clean `Exit(0)`
such as `--help`, which logged nothing. The teardown order is:
1. the summary, written inside the run span;
2. end the run span;
3. reset the operation context;
4. flush the export;
5. reset logging.

**Every printed finding is logged.** The paths listed in the context now call
`log_diagnostic`. Findings that are not a `CompileDiagnostic` get stable codes:
- `gold.package-invalid`, `gold.tmdl-invalid`, `gold.tmdl-unavailable`;
- `gold.profile-missing`, `gold.insights-unusable`;
- `gold.unresolved-relationship`, `gold.unresolved-bridge`, `gold.insight-unanswerable`;
- `compile.gold-note`, `compile.deferred-bridge`, `compile.deferred-reference`,
  `compile.stale-dependent`;
- `projection.domain-failed`.

`project` always writes, so it keeps a default run log like the other writing commands.
`validate-dbt` gets spans through the run span and `events.timed_phase`. It usually runs in a
dataplatform repo with no hub, so `--log-file` is its record there.

**`kairos-ontology logs show`** reads one run log back: the newest one in the hub, or a PATH. It
shows how the run ended, the span tree with durations, and the diagnostics grouped by task
(nested under their span), code or severity. `--format json` is available. It writes nothing.

### Consequences

- This amends DD-151 Phase 4, which bridged logs only and assumed that installing a handler was
  enough to export. The rest of DD-151 (formatters, redaction, the operation id, exit-code
  neutrality) is unchanged. Telemetry still never changes an exit code or an artifact byte.
- `--check` and `--explain` stay write-free (DD-133/140). They get the same records, spans
  included, only through `--log-file`. The default run log remains a writing-command feature.
- A run log from before this change has no span records. `logs show` falls back to grouping by
  `kairos.task` for such a log.
- Each span costs one ContextVar push/pop and one INFO record. A 15-domain `compile --all` adds
  about a hundred records to a log that already holds its diagnostics.
- Langfuse (DD-184) installs itself as the global OTel tracer provider. A Kairos span lives in
  the shared context, so an LLM command's Langfuse spans would record a Kairos parent that
  Langfuse never receives. That is acceptable: compile, emit and packaging make no LLM calls,
  and the LLM commands trace to Langfuse on their own.
- Considered and rejected:
  - **The OTel SDK as the only span store.** It would make the span tree depend on an optional
    extra, and the run log is the record most users actually have.
  - **A global `set_tracer_provider`.** It can be set once per process. An in-process second
    invocation (every CLI test) would silently keep the first run's provider, and so would an
    embedder.
  - **A separate trace-id attribute on every record.** Using the operation id as the trace id
    makes the join free.
