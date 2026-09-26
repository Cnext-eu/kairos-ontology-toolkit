### Fixed
- **`anchor-tables` no longer crashes on a re-run.** Since the #877 drift summary, every run
  after the first failed with `report() takes 1 positional argument but 2 were given` — after
  the anchoring model calls were billed and before `hub.table-anchors.yaml` was written. A
  skipped design ruling (DD-192) crashed the same way on any run. The CLI callback now takes
  the level the core passes; drift and skipped-ruling warnings still print under `--quiet`,
  the "no drift since the last run" line does not (#1039).
