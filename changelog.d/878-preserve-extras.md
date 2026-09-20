### Fixed
- **`update` no longer uninstalls the optional extras the hub runs on.** Every
  `update --upgrade`, `--test-ref` and `--restore` ran a bare `uv sync`, which installs
  the default dependency set and removes everything outside it — so a hub configured
  against Azure Foundry lost its provider SDK on every upgrade and the next
  `anchor-tables` or `propose-alignment` died on a missing package nobody removed. The
  extras a hub is actually running on are now detected before the sync (an extra counts
  as active when every distribution it requires is installed, resolving
  `kairos-ontology-toolkit[foundry]` through the toolkit's own metadata) and re-passed as
  `--extra` flags. This covers the Windows path too, where the only sync that runs is the
  one in the scheduled background refresh.
