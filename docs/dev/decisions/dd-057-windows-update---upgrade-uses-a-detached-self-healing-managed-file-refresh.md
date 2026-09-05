# DD-057: Windows `update --upgrade` Uses a Detached Self-Healing Managed-File Refresh

**Status:** Accepted
**Date:** 2026-06-13
**Affects:** `update --upgrade` (Windows)
**Implementation:** `src/kairos_ontology/cli/main.py`
(`_schedule_windows_refresh`, `update()` upgrade branch),
`tests/test_cli_update_upgrade.py`

### Context

`kairos-ontology update --upgrade` bumps the `pyproject.toml` pin, runs `uv lock`, and
then refreshes the toolkit-managed files under the **new** version. Because the running
process has the *old* toolkit module loaded in memory (`_toolkit_version` /
`_SCAFFOLD_DIR`), the refresh must happen under a freshly-installed version. Previously
this was done by synchronously re-exec'ing `uv run kairos-ontology update` via
`subprocess.run`.

On Windows this is impossible: the running `kairos-ontology.exe` holds an exclusive lock
on its own executable for its entire lifetime. The synchronous re-exec keeps the parent
alive (blocked in `subprocess.run`), so the child's implicit `uv sync` cannot overwrite
the locked `kairos-ontology.exe` and the refresh fails with a file-lock error — leaving
the pin bumped but managed files stale.

### Decision

On Windows, when the target version differs from the running version, the upgrade no
longer re-execs synchronously. Instead it spawns a **detached** PowerShell helper
(`_schedule_windows_refresh`) that:

1. `Wait-Process -Id <parent-pid>` — blocks until the current process exits, releasing
   the `.exe` lock;
2. runs `uv sync` to install the newly-pinned version;
3. runs `uv run kairos-ontology update` (propagating `--check`) to refresh managed files.

The parent prints a "refresh scheduled" message and exits 0 immediately. Output is
mirrored to a transcript log at `.kairos/upgrade-refresh.log` so the result is durable
after the spawned console closes. If the helper cannot be launched, the command falls
back to printing manual guidance and exits non-zero.

Non-Windows platforms keep the existing inline `uv sync` + blocking re-exec, which has no
lock constraint.

### Rationale

The parent process can never release its own `.exe` lock while alive, so an in-process or
synchronously-chained refresh is fundamentally unworkable on Windows. Deferring the
sync+refresh until after the process exits is the only reliable single-command path, and a
detached helper keeps the upgrade fully automatic ("self-healing") rather than forcing the
user into a manual two-step. A wheel-extract refresh (reading scaffold from the downloaded
`.whl` without syncing) was considered but rejected as more complex and leaving the venv
out of sync with the pin.

### Consequences

- Windows upgrades complete automatically without a file-lock error; the refresh appears in
  a new console window shortly after the command returns.
- A transcript log (`.kairos/upgrade-refresh.log`) records the deferred refresh outcome.
- The detached helper depends on `uv` being on the system `PATH` (it is, since the upgrade
  itself ran via uv).
- `--upgrade --check` is honoured: the scheduled refresh runs `update --check`.
