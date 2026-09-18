### Added
- **`validate-dbt --structural-only` now detects duplicate dbt resource names (issue
  #786).** It previously ran exactly one check — a dangling-`ref()` text scan — so it could
  not see two resources sharing a name, which is the one defect class that makes an
  assembled package fail at *parse* time. No `--select` or `--exclude` works around that,
  and no downstream dataplatform can consume the package at all. #777 and #779 were both
  this shape, and both passed `compile --check`, `--emit` and `--structural-only` before
  dbt itself rejected the manifest downstream. The compiler bugs behind them are fixed;
  this is the gate that stops the next one reaching a hub the same way.

  Two scans, both needing no warehouse and no dbt install, which is what lets them live in
  the phase a hub's CI release loop actually runs: model SQL stems against seed CSV stems
  (they share the `ref()` namespace, the same pairing the dangling-ref scan already makes),
  and `data_tests` entries that repeat identically on one model or column — dbt derives a
  generic test's name from the test name plus its arguments, so byte-identical entries
  collide. Both run before the dangling-`ref()` scan, since a duplicate name makes every
  other structural finding downstream noise.
