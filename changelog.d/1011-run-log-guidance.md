### Changed
- **Writing commands name their run log as their last line (#1011).** `compile --emit`,
  `emit-gold`, `package-powerbi-release` and `project` end with
  `Run log: .kairos/logs/<utc>-<command>-<id>.jsonl  (kairos-ontology logs show)` on stderr,
  including when they fail, so the grouped findings are one command away instead of
  scrolled off the terminal. The line is omitted under `--log-format json`, where stderr is
  a JSON-lines stream, and when the run log is off (`--log-file`, `KAIROS_RUN_LOG=0`).

### Documentation
- **The skills and guides use the run log.**
  - `kairos-execute-project` reviews an emit's findings with `logs show --group-by code`
    instead of console output.
  - `kairos-diagnose-status` reads the last run's log when asked how an emit went.
  - `kairos-design-gold` works through `emit-gold` findings from the log.
  - `kairos-flow-autopilot` cites run logs in its transparency report.
  - `kairos-help` and the Copilot instructions list `logs show`.
  - The compile-and-emit and Gold how-tos, the user guide and `CICD.md` say where the log is
    and how to read it.
  - `OBSERVABILITY.md` now ships to hubs under `docs/toolkit/`.
