# DD-151: Structured logging foundation + opt-in OpenTelemetry bridge

**Status:** Accepted
**Date:** 2026-08-14
**Context:** observability change request (`docs/temp/changerequest.md`)

### Context

The toolkit used `logging.getLogger(__name__)` in ~40 modules but had **no central logging
configuration** and **no root-level `--verbose/--debug/--log-file/--log-format` options**, so
those records effectively went nowhere (Python `lastResort` -> stderr at WARNING only). The change
request motivated this with "dbt execution code fails silently", but after code analysis that
framing was partly misaligned:

1. The toolkit core **does not run real `dbt run`/`build`**. `core/dbt_validation.py` only runs
   *offline* `dbt deps/parse/compile` with credential-free dummy profiles. Real-run observability
   lives in the downstream **dataplatform** repo the toolkit scaffolds - explicitly **out of scope**
   here.
2. A machine-readable diagnostic contract already exists (`CompileDiagnostic` with stable `code`,
   `severity`, `rule_id`, drift-guarded by `docs/design/diagnostic-codes.md` +
   `tests/test_diagnostic_catalog.py`, surfaced via `compile --format json` per DD-133). The CR's
   proposed "diagnostic envelope for skills" would duplicate it.
3. Offline dbt validation already classifies failures (`DbtValidationError(phase, ...)`,
   `_ENVIRONMENT_BLOCK_PATTERNS`, `compile_status="environment_blocked"`).

The real, high-value gap was item (0): no central logging config + no CLI verbosity flags.

### Decision

**Scope: toolkit core + CLI only** (offline validation, compile, projections). Real dbt-run
observability in the dataplatform scaffold is tracked separately.

**Phase 1 - Structured logging foundation (the real gap).** A new subpackage
`core/observability/` provides:
- `logging_config.configure_logging(...)`: idempotent; installs console (+ optional file)
  handlers **only** at the CLI boundary on the `kairos_ontology` logger. Libraries keep
  `getLogger(__name__)` and never configure handlers. `logger.propagate = False` so third-party
  loggers (rdflib, jinja2) stay quiet by default. Handlers are stamped with a `_kairos_observability`
  marker so reconfiguration can find/remove them without touching foreign handlers (e.g.
  pytest's).
- `formatters.JsonFormatter` (NDJSON, stable field set: timestamp, level, logger, message,
  event, `kairos.operation.id`, extras, exception) and `formatters.TextFormatter` (human-readable
  single line with `[event=...]` and `[kairos.operation.id=...]` tags).
- `_redaction.RedactionFilter`: scrubs sensitive keys (password/passwd/secret/token/
  client_secret/api_key/credential/authorization) and secret substrings (tokens, bearer, ODBC
  `password=` fragments, UUID-like secrets) **before** emit. Never drops records.
- `context.OperationContext` + `contextvars.ContextVar`: per-invocation operation id (uuid4) for
  correlating all records in one command. `OPERATION_ID_ATTR = "kairos.operation.id"`.

Root Click group options in `cli/main.py`: `--verbose/-v`, `--debug`, `--log-file`,
`--log-format {text,json}`; `cli` callback calls `configure_logging(...)` once and binds the
operation context; `result_callback` resets it.

**Phase 2 - Instrument offline dbt boundaries.** `core/dbt_validation.py` (deps/parse/compile
phases) emits a small, stable, versioned event catalogue via `observability.events`:
`kairos.dbt.phase.started` / `.completed` / `.failed` / `kairos.dbt.environment_blocked`, with
attributes `kairos.operation.id`, `kairos.dbt.phase`, `duration_ms`, `kairos.retryable`. Genuine
artifact failures are **not** retryable (retrying produces identical output); only
timeout/environment-blocked outcomes are. Captured stdout/stderr is redacted before logging.
`subprocess.run` call sites in `cli/shared.py`, `cli/setup.py`, `cli/operations.py` are similarly
instrumented. **Logging never changes exit codes.**

**Phase 3 - Leverage (do not duplicate) the diagnostic contract.** `compile --format json` now
carries `operation_id` for log<->result correlation. Where offline dbt-validation failures should
be skill-consumable, they are surfaced through the existing `CompileDiagnostic` / JSON path -
**no second machine-readable envelope.**

**Phase 4 - Optional OpenTelemetry bridge (opt-in, off by default).** An `[otel]` extra in
`pyproject.toml` (opentelemetry-api/SDK + OTLP exporter), mirrored in `[dependency-groups]`. The
bridge in `observability/otel.py` activates **only** when the extra is importable **and**
`OTEL_EXPORTER_OTLP_ENDPOINT` is set. Absence of the package is a guarded-import + no-op. Export
failure is caught and never affects the CLI exit code. The handler is flushed in the CLI
`result_callback`. Uses OpenTelemetry semantic-convention attributes where standardized and
namespaces toolkit attributes as `kairos.*`.

### Rejected alternatives

- **Make OTel a hard runtime dependency.** Rejected: the toolkit is a minimal-dependency Apache-2.0
  short-lived CLI; OTel is opt-in.
- **Build a parallel "diagnostic envelope for skills".** Rejected - duplicates
  `CompileDiagnostic` / `--format json` (DD-133). Extend, don't reinvent.
- **Instrument real dbt-run observability in toolkit core.** Rejected - real dbt execution lives
  in the downstream dataplatform repo; out of scope.

### Consequences

- New subpackage `core/observability/`; new tests `tests/test_observability.py` (config idempotency,
  JSON/text formatter shape, redaction, operation-id propagation, third-party logger isolation) and
  `tests/test_observability_events.py` (dbt-validation event emission happy/failure each phase,
  retryable-classification guard, environment-blocked event, phase/operation attributes).
- `compile --format json` payload gains `operation_id`; documented in
  `docs/design/diagnostic-codes.md` ("JSON output envelope" section). `CONSUMING_COMPILE_PLAN.md`
  unchanged (consumer-oriented, not payload-oriented).
- Determinism preserved: logging/telemetry never alters compiler output bytes or artifact paths;
  `tests/scenarios/test_scenario_v5.py` and determinism tests still pass.
- SPDX/Apache-2.0 headers on every new .py file. 100-char ruff lines.
- Future: real-run dbt observability in the dataplatform scaffold is a separate change.

### Amendment (2026-08-21): the boundary renders `OntologyLoadError` diagnostics instead of a traceback (#587)

The unhandled-exception boundary on the root group (`_KairosGroup.invoke`, issue #295,
pinned by `tests/test_cli_exception_boundary.py`) writes one `kairos.cli.command.failed`
record and re-raises, letting Click print the raw traceback. For `OntologyLoadError`
that traceback was actively misleading: the exception carries an `OntologyLoadResult`
whose structured diagnostics (`missing_import` et al.) name the real cause — typically
`kairos-ontology-referencemodels` absent from the running interpreter — while the
generic "closure is incomplete; rerun with degraded=True" message suggests the wrong
remedy (DD-103 keeps fail-closed loading; degraded mode is not the fix for a broken
environment).

The boundary now has a dedicated arm for `OntologyLoadError`, ordered **after** the
DD-151 record and teardown (converting to `click.exceptions.Exit` first would skip the
record — Exit is on the exemption list): it renders `✗ {message}` plus each attached
diagnostic to stderr via `cli/shared.py:render_ontology_load_failure()`
(`missing_import` first, matched on `code` — degraded loads downgrade the *level* to
warning — then other errors, then the rest), appends a wrong-environment hint when
missing imports coincide with `_read_refmodels_provenance()` reporting the package
absent, and raises `Exit(1)`. The per-diagnostic line format is shared with
`resolve-ontology` through `format_load_diagnostic()` so the two renderings cannot
drift; the `resolve-ontology --json-output` payload is unchanged. The arm checks
`sys.modules` for `core.ontology_loader` instead of importing it, keeping rdflib off
the failure path of unrelated exceptions. Exit codes for every other exception class
are untouched.
