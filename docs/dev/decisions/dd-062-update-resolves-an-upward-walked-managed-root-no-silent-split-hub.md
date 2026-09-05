# DD-062: `update` Resolves an Upward-Walked Managed Root (No Silent Split-Hub)

**Status:** Accepted
**Date:** 2026-06-13
**Affects:** `src/kairos_ontology/hub_utils.py`, `src/kairos_ontology/cli/main.py` (`update`)
**Implementation:** `find_managed_root()` in `hub_utils.py`; re-root + guards in the `update` command

### Context

A hub user ran `uv run kairos-ontology update --upgrade` from the `ontology-hub/`
*content* subdirectory of their hub. Instead of updating the real hub at the repo
root, the command **scaffolded an entire second hub** under `ontology-hub/`
(`pyproject.toml`, `uv.lock`, `.venv`, `.github/`, skills) and left the real
repo-root pin untouched — a silent split-hub.

Three root causes:

1. **`update` trusted `Path.cwd()` and never walked up.** It hard-coded
   `Path.cwd()` for both the toolkit pin and the managed-file root. Unlike git,
   uv, npm, and cargo, it did not search ancestors for the project root.
   Even `find_hub_root` only inspects `cwd` and `cwd/ontology-hub`, never parents.
2. **Silent legacy `pyproject.toml` fabrication.** When `cwd/pyproject.toml` was
   missing, `--upgrade` generated a brand-new hub pin from the scaffold template —
   the actual trigger that manufactured the second hub from a non-hub subdir.
3. **No nested-execution guardrail.** Nothing detected that an ancestor already
   *was* a hub (had the `[tool.kairos]` pin / managed `.github/`).

Note the dual layout in such hubs: the *managed root* (pin + `.github/`) is the
repo root, while the *content root* is `ontology-hub/`. `update` only ever touches
managed files + the pin, so it must anchor on the **managed root**, independent of
the content root.

### Decision

Add `find_managed_root(cwd)` to `hub_utils.py` that walks **up** from `cwd` and
returns the first ancestor that is a managed root — detected by any positive
anchor: a `pyproject.toml` referencing `kairos-ontology-toolkit` or `[tool.kairos]`,
a `.github/copilot-instructions.md` carrying the managed marker, or a dataplatform
root (`dbt_project.yml` + a `.github/`).

The `update` command now, before doing anything:

- Resolves `managed_root = find_managed_root(cwd)`. If found and different from
  `cwd`, it prints a notice (`↪ Detected hub root at … — operating there.`) and
  `os.chdir`s to it, so the existing `Path.cwd()`-based pin write, `uv lock`/`sync`,
  re-exec, and Windows detached refresh all target the real root.
- **Refuses to fabricate** a `pyproject.toml` (and refuses the plain refresh) when
  `managed_root is None` — it hard-errors with guidance to run from a hub root or
  use `new-repo`/`init`. Legacy fabrication is kept **only** when a managed root is
  positively detected (e.g. a `.github`-marked hub that predates the pin file).

### Rationale

Auto-re-rooting (chosen over hard-erroring on subdir invocation) matches familiar
project-tool ergonomics — users can run `update` from anywhere inside the hub. The
hard guard against fabrication-without-evidence eliminates the destructive failure
mode (a second hub) while preserving the legitimate legacy-migration path.
`find_hub_root` (content-command resolution) is intentionally left unchanged; this
fix is scoped to `update`'s managed-root resolution.

### Consequences

- Running `update`/`--upgrade` from a content subdir now correctly updates the real
  hub and never creates a second one.
- Running in a non-hub directory hard-errors instead of silently scaffolding.
- Legacy hubs (managed `.github`, no pin) still get a generated `pyproject.toml`.
