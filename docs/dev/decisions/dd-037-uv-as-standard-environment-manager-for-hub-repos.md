# DD-037: uv as Standard Environment Manager for Hub Repos

**Status:** Accepted
**Date:** 2026-05-31
**Affects:** scaffold/setup-env.ps1, scaffold/setup-env.sh, CLI update --upgrade,
copilot-setup-steps.yml, kairos-setup-init skill, kairos-toolkit-ops skill

### Context

Hub repos are ontology content repositories that depend on the kairos-ontology-toolkit
CLI. Previously, environment setup used a custom `setup-env.ps1` that:
1. Manually created a `.venv` via `py -m venv`
2. Ran `pip install -e ".[dev]"` (wrong — hub repos aren't editable Python packages)
3. Was Windows-only (no Linux/macOS/CI support)
4. Had no lock file for reproducible installs
5. The `update --upgrade` command used `pip install` directly, bypassing any venv

This caused recurring "stale install" issues where `pip install` in one hub
silently overwrote the toolkit in a shared global Python environment.

### Decision

Adopt **uv** (https://docs.astral.sh/uv/) as the sole environment manager for hub repos:
- `uv sync` replaces `py -m venv` + `pip install` (creates `.venv` automatically)
- `uv run <cmd>` replaces manual venv activation
- `uv.lock` provides reproducible installs (committed to the hub repo)
- `update --upgrade` updates `pyproject.toml` then runs `uv lock` + `uv sync`
- No backward compatibility with pip-based setup (clean break)

### Rationale

- **Cross-platform:** uv works on Windows, Linux, macOS — single workflow for all
- **Fast:** 10-100x faster than pip for dependency resolution and install
- **Reproducible:** `uv.lock` ensures all developers and CI get identical environments
- **No stale installs:** `uv sync` always installs exactly what `pyproject.toml` + lock declare
- **PEP 621 compatible:** Our `pyproject.toml` template works with uv natively
- **CI-native:** `astral-sh/setup-uv` action provides one-line CI integration
- **Eliminates confusion:** `uv run kairos-ontology <cmd>` is clearer than
  "activate venv, then run python -m kairos_ontology"

Alternatives considered:
- **pipx / uv tool:** Only installs CLI tools globally, can't pin per-repo or include pytest
- **Keep pip + fix bugs:** Still leaves Windows-only, no lock file, manual venv management
- **Docker / devcontainer:** Too heavy for a CLI tool dependency

### Consequences

- **Breaking change:** Hub repos must install `uv` before using the toolkit.
  Install instructions provided in setup scripts and skill docs.
- `setup-env.ps1` and `setup-env.sh` are now thin wrappers that check uv and run `uv sync`.
- `copilot-setup-steps.yml` uses `astral-sh/setup-uv@v4` action.
- Existing hub repos need to run `kairos-ontology update --force` to get the new scripts.
- The editable install stale-guard in `tests/conftest.py` (toolkit dev repo) remains
  as a safety net for toolkit development itself (which still uses Poetry).
