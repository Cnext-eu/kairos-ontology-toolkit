# Logging & Observability (DD-151)

The Kairos toolkit emits **structured logs** from a central configuration at the CLI
boundary, with an optional **OpenTelemetry** bridge that is opt-in and off by default.
This covers toolkit core + CLI only (offline dbt validation, compile, projections).
Real `dbt run`/`build` observability lives in the downstream dataplatform the toolkit
scaffolds — see [CONSUMING_COMPILE_PLAN.md](CONSUMING_COMPILE_PLAN.md).

## Verbosity flags

All commands accept these root options (before the subcommand):

| Flag | Effect |
|---|---|
| `--verbose`, `-v` | Emit INFO-level log output to the console. |
| `--debug` | Emit DEBUG-level log output (implies verbose). |
| `--log-file PATH` | Also write logs to `PATH` (same format as console). |
| `--log-format {text,json}` | Structured log format; `text` is the default. |

```powershell
kairos-ontology --verbose --log-format json compile party --check --format json
```

## JSON log shape

Each JSON log record is one NDJSON object with a stable field set:

```json
{"timestamp": "...", "level": "INFO", "logger": "kairos_ontology.dbt",
 "event": "kairos.dbt.phase.completed", "kairos.operation.id": "<uuid4>",
 "kairos.dbt.phase": "compile", "duration_ms": 123,
 "message": "dbt compile completed"}
```

- `event` — stable, versioned name (see the event catalogue below). Machine consumers
  key off this, not the free-text `message`.
- `kairos.operation.id` — per-invocation uuid4; all records in one command correlate.
  The same id appears as `operation_id` in `compile --format json`.

Sensitive values (passwords, tokens, connection strings) are redacted before emit.

## Unhandled exceptions

Any exception that escapes every command body — one that no `except` clause in the
CLI converts to a `click.ClickException`/`click.UsageError` (the deliberate
user-error channel) or a `raise SystemExit(...)` (the deliberate non-zero-exit
channel) — is caught once, at the root `_KairosGroup.invoke` boundary in
`cli/main.py`, and logged as a single structured record before the exception is
re-raised so Click's `standalone_mode` still renders the traceback to stderr and
sets the process exit code exactly as it always has:

```json
{"timestamp": "...", "level": "ERROR", "logger": "kairos_ontology.cli",
 "event": "kairos.cli.command.failed", "kairos.operation.id": "<uuid4>",
 "exception.type": "RuntimeError", "exception.message": "...",
 "exception.stacktrace": "Traceback (most recent call last): ...",
 "message": "unhandled exception: RuntimeError"}
```

| Field | Description |
|---|---|
| `event` | Always `kairos.cli.command.failed`. |
| `exception.type` | The exception class name (`type(exc).__name__`). |
| `exception.message` | `str(exc)`. |
| `exception.stacktrace` | The full formatted traceback, as text — **not** attached via `exc_info`. |
| `kairos.operation.id` | The same per-invocation id as every other record from the run. |

**The stacktrace is redacted, and therefore lossy for debugging.** Like every other
structured `extra` field, `exception.stacktrace` passes through `redact_text` before
it reaches a formatter. That function's first pattern is
`(?i)(token|secret|password|passwd|client_secret|api[-_]?key)\S*`, so a frame whose
file path or local variable happens to contain one of those words — e.g. a line
referencing `.../token_store.py` — is masked to `[REDACTED]` in the persisted record.
The unredacted traceback still reaches the console today via Click's normal
exception rendering (unchanged behavior); only the structured copy is redacted.

**Exit codes are unchanged.** The boundary only adds a log record; it re-raises the
original exception (or `SystemExit`/`ClickException`/`click.Abort`/`KeyboardInterrupt`,
which are exempted and pass through untouched) so Click's `standalone_mode` still owns
every exit code.

**Limitation — root option parsing and command resolution are not covered.**
`--help`, `--version`, an unknown subcommand, an invalid `--log-format` value, or a
bare `kairos-ontology` with no arguments all fail (or exit) *inside*
`Group.invoke` **before** `super().invoke(ctx)` runs the group callback that calls
`configure_logging`. Any exception in that window — including Click's own
`Exit`/`UsageError` raised while resolving the invocation — carries no operation id
and never reaches `--log-file`, because logging has not been configured yet. This is
by design: `click.exceptions.Exit` is explicitly exempted from the boundary (in click
8.4.1 its MRO includes `RuntimeError`/`Exception`, so `--help`'s internal `Exit(0)`
would otherwise be logged as a failure on every subcommand).

## dbt-validation event catalogue

Emitted around the offline `dbt deps`/`parse`/`compile` phases in
`core/dbt_validation.py`:

| Event | When | Key attributes |
|---|---|---|
| `kairos.dbt.phase.started` | Before each phase | `kairos.dbt.phase`, `kairos.dbt.platform` |
| `kairos.dbt.phase.completed` | Phase succeeded | + `duration_ms` |
| `kairos.dbt.phase.failed` | Phase raised | + `duration_ms`, `kairos.retryable`, `error_type` |
| `kairos.dbt.environment_blocked` | Compile blocked by environment/credentials | `kairos.retryable=true` |

`kairos.retryable` distinguishes transient/environmental failures (timeout, missing
credentials — safe to retry) from genuine artifact failures (parse/compile errors —
retrying produces identical output, so not retryable).

## projection event catalogue

Emitted around optional projection integration calls (DD-151). These are
non-fatal by design: a skipped/failed step degrades to Markdown-only output
rather than failing the command.

| Event | When | Key attributes |
|---|---|---|
| `kairos.projection.step.started` | Before an optional render/external call | `kairos.projection.step`, `source` |
| `kairos.projection.step.completed` | Step succeeded | + `artifact`, `duration_ms` |
| `kairos.projection.step.skipped` | Prerequisite absent (e.g. `mmdc` not installed) | `kairos.projection.step`, `source` |
| `kairos.projection.step.failed` | Step raised (caught, non-fatal) | + `duration_ms`, `error_type` |

Currently emitted for the Mermaid SVG render (`kairos.projection.step="mermaid_render"`)
in `core/projections/medallion_silver_projector.py`.

## compiler debug trace points

The compiler's stable machine-readable contract is `CompileDiagnostic` (codes, severities,
`rule_id`), surfaced via `compile --format json` — it is **not** a log event stream.
On top of that contract, the compiler emits targeted `logger.debug(...)` trace points
(visible only under `--debug`) at high-value decision points, for human diagnosis and
skill-assisted tracing. These are deliberately not part of the event catalogue above.

| Logger | Trace point | Example message |
|---|---|---|
| `kairos_ontology.core.compiler.kernel` | Scope resolution | `compile scope resolved: domain=... binding_paths=N provenance=...` |
| `kairos_ontology.core.compiler.kernel` | Binding selection (skipped/blocked/valid) | `binding skipped (domain mismatch): ...`, `binding blocked (adapter): ... codes=...`, `binding selection: selected=N valid=N blocked=N` |
| `kairos_ontology.core.compiler.kernel` | `compile_domain` entry | `compile domain: domain=... mode=... cached_plan=...` |
| `kairos_ontology.core.compiler.emit` | Emission plan + commit lifecycle | `emit plan: target=... artifacts=N ...`, `emit commit: target=... written=N removed=N` |
| `kairos_ontology.core.compiler.emit` | Interrupted-emit recovery + rollback | `emit recovery: target=... backups=N stages=N`, `emit commit: rollback restored ...` |

None of these alter compiler output bytes, artifact paths, or exit codes. They are
suppressed at INFO and above.

## compile `--format json`

The JSON payload now includes `operation_id` for correlating a compile result with the
structured logs emitted during the same invocation. Per [DD-151](design/toolkit-design-decisions.md),
the envelope fields are:

| Field | Description |
|---|---|
| `domain` | Compiled domain name. |
| `mode` | Compile mode (`check`, `explain`, `check+explain`, `emit`, ...). |
| `succeeded` | Boolean; `false` when any `error`-severity diagnostic is present. |
| `provenance_hash` | Stable hash of resolved inputs; equality guarantees identical artifacts. |
| `operation_id` | Per-invocation identifier (see DD-151); also stamped on every log record as `kairos.operation.id`. `null` only when the CLI was not the entry point. |
| `diagnostics` | Ordered list of `CompileDiagnostic` (`code`, `severity`, `rule_id`, `message`, `pointer`). |
| `explain` | Structured explain report, or `null` outside `--explain`. |
| `artifacts` | Emitted artifact paths (empty unless `--emit`). |

Skills drive self-healing off `diagnostics` (`code` + `rule_id` are the stable contract),
not free-text messages. `operation_id` lets a skill correlate a failed compile with the
structured logs emitted during the same run. See
[diagnostic-codes.md](design/diagnostic-codes.md) for the full diagnostic code catalogue.

## Enabling OpenTelemetry (optional)

Install the extra:

```powershell
pip install kairos-ontology-toolkit[otel]
# or, with uv in the toolkit repo:
uv sync --group otel
```

Then opt in via standard `OTEL_*` environment variables:

```powershell
$env:OTEL_EXPORTER_OTLP_ENDPOINT = "http://localhost:4317"
$env:OTEL_SERVICE_NAME = "kairos-ontology"
kairos-ontology --verbose compile party --check
```

The bridge installs an OTel `LoggingHandler` on the `kairos_ontology` logger only when
**both** the extra is importable **and** `OTEL_EXPORTER_OTLP_ENDPOINT` is set. Absence
of either is a no-op. Export failure is caught and **never changes the command exit
code**. The handler is flushed before the CLI exits.

## Design reference

See [DD-151](design/toolkit-design-decisions.md) for the full decision, scope, and
rejected alternatives.
