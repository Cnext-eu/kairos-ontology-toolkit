### Added
- **A run log is now a tree of tasks, with durations (#1011, DD-242).** Every command run
  writes a `kairos.span.completed` record for each task: the run, each domain or Gold
  product, each gate (`alignment.table-unanchored`, `compile`, `gold-shape`,
  `package-validation`, `gold.tmdl-structural-validation`, ...) and each stage (`emit`,
  `erd`, `archive`). Each record carries its parent, status (`ok`, `refused`, `error`),
  duration and diagnostic counts. Every diagnostic record names the span that reported it
  (`kairos.span.id`), so a run's findings group under the domain, product and gate that
  produced them.
- **`kairos-ontology logs show`.** It reads the newest run log in `<hub>/.kairos/logs/`
  (or a PATH) back as the span tree with each diagnostic under its task. `--group-by code`
  and `--group-by severity` group the diagnostics instead, and `--format json` is available.
  It reads any `--log-file PATH --log-format json` log, too.
- **`project` keeps a default run log**, like the other writing commands.

### Fixed
- **OpenTelemetry export now exports.** With `OTEL_EXPORTER_OTLP_ENDPOINT` set and the
  `[otel]` extra installed, the old bridge installed a log handler with no provider, so
  nothing reached the collector, and there were no spans. Each command run is now one
  trace:
  - a child span per domain, product, gate and stage;
  - diagnostics as span events;
  - redacted log records carrying the trace context;
  - the trace id equals the run's operation id.

  `OTEL_EXPORTER_OTLP_PROTOCOL` selects `http/protobuf` (default) or `grpc`. Without the
  endpoint, nothing from OpenTelemetry is imported.
- **A failing or refused run now writes its summary.** `Exit`, `ClickException` and
  `SystemExit` used to skip the observability teardown, so a failing `compile` or a refused
  `emit-gold` left no `kairos.run.summary` and flushed nothing. The summary is now written
  on every exit, even for a clean run. It carries `kairos.outcome` and `kairos.exit_code`.
- **Findings that were printed but never logged now reach the run log.** These are:
  - compile gate refusals;
  - Fabric package and TMDL failures, and an unavailable TOM SDK;
  - `emit-gold`'s unresolved-relationship, unresolved-bridge and insight-gap reports;
  - compile's deferred-bridge and stale-dependent notes;
  - `project`'s per-domain failures.

  The findings that are not compiler diagnostics get stable codes (`gold.package-invalid`,
  `gold.tmdl-invalid`, `compile.stale-dependent`, ...; see `docs/guide/OBSERVABILITY.md`).
  `package-powerbi-release` now attributes a blocked member's diagnostics to that domain.
