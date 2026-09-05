# DD-049: Self-Upgrade Re-exec & Running-vs-Pinned Version Guard

**Status:** Accepted
**Date:** 2026-06-13
**Affects:** `cli/main.py` (`update --upgrade`, `cli()` group callback), `kairos-toolkit-ops` skill (both copies)
**Implementation:** `src/kairos_ontology/cli/main.py` (`update`, `_read_pinned_toolkit_version`, `_warn_if_version_mismatch`), `tests/test_cli_update_upgrade.py`, `tests/test_cli_version_guard.py`

### Context

Two related failure modes left hubs silently running the wrong toolkit version:

1. **Stale in-process refresh after `--upgrade`.** `kairos-ontology update --upgrade`
   bumps the `pyproject.toml` pin and runs `uv lock`/`uv sync`, then refreshes the
   hub's managed files **in the same process**. But that process still has the
   *old* package imported (`_toolkit_version`, `_SCAFFOLD_DIR`,
   `_managed_scaffold_map()` are bound to the previously-loaded module). On Windows
   the new wheel isn't even active until the next `uv run`. So the managed-file
   refresh compared/stamped against the **old** version, forcing the user to
   manually re-run `update` to actually pick up new/changed scaffold files.

2. **Running a different toolkit than the hub pins.** Users who run
   `python -m kairos_ontology` / a globally-installed `kairos-ontology` instead of
   `uv run kairos-ontology` could silently execute an older global toolkit. The
   existing `_warn_if_outside_venv()` heuristic is mechanism-based and misses the
   case where the running interpreter is in *some* environment with a different
   pinned version.

### Decision

1. **Auto re-exec the refresh under the new version.** After `--upgrade` performs
   the lock/sync, if the resolved target version differs from the running
   `_toolkit_version`, the command re-execs `uv run kairos-ontology update
   [--check]` (a fresh process that loads the new package), propagates that exit
   code, and skips the stale in-process refresh. It never re-passes `--upgrade`
   (no recursion), preserves `--check`, and falls back to a clear message if the
   re-exec cannot be launched. A no-op upgrade (target == running) keeps the
   in-process path.
2. **Exact version guard.** A new `_warn_if_version_mismatch()` (wired into the
   `cli()` group callback alongside the venv heuristic) reads the toolkit version
   pinned in the hub's `pyproject.toml` (`.whl` URL or legacy `git+…@<tag>` via
   `_read_pinned_toolkit_version()`) and emits a non-blocking stderr warning when
   it differs from the running version, highlighting when the running version is
   older and pointing at `uv run` / `uv sync`.

### Consequences

- `update --upgrade` is now a single seamless command: it upgrades **and**
  refreshes managed files against the new version.
- Every CLI invocation in a hub cross-checks the running version against the pin,
  surfacing global/stale-toolkit usage without blocking.
- Tests: `tests/test_cli_update_upgrade.py` (re-exec on change, `--check`
  passthrough, exit-code propagation, no-op no-reexec) and
  `tests/test_cli_version_guard.py` (pin parsing + warning behaviour).
- `packaging.version` is used for older/newer comparison (already an indirect
  dependency); a string-inequality fallback keeps it non-fatal.

### Amendment (2026-08-21): the outside-venv guard is identity-based, not mechanism-based (#587)

The Context above already named the gap: `_warn_if_outside_venv()` asked *"am I in
some venv?"* (`sys.prefix != sys.base_prefix`) and returned early for **any** venv.
A pipx / `uv tool` global install of `kairos-ontology` IS a venv, so users running a
global toolkit inside a hub got no warning — and then hit opaque
`OntologyLoadError` failures because hub-pinned companion packages
(`kairos-ontology-referencemodels`) were absent from that interpreter.

The guard now asks *"am I in THIS hub's venv?"*: it resolves the managed hub root
via `find_managed_root()` and, when that root has a `.venv`, compares
`Path(sys.prefix).resolve()` against it. Any mismatch — foreign venv or bare system
Python — warns that commands may lack hub-pinned packages such as
`kairos-ontology-referencemodels` and points at `uv run kairos-ontology …`. Outside
a managed root (or when the hub has no `.venv`) the original bare-global heuristic
(no venv at all + a local `./.venv` or `../.venv`) remains as a fallback, so
non-hub usage stays exactly as quiet as before. Still a non-blocking stderr
warning; the guard never changes exit codes.
