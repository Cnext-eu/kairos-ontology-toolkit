# Contributing to Kairos Ontology Toolkit

Thank you for your interest in contributing! This project is part of the
**Kairos Community Edition** by [Cnext.eu](https://cnext.eu).

## Developer Certificate of Origin (DCO)

All contributions must be signed off under the
[Developer Certificate of Origin v1.1](https://developercertificate.org/).

By adding a `Signed-off-by` line to your commit messages, you certify that you
wrote the code (or have the right to submit it) and that you agree to release
it under the project's Apache 2.0 license.

```bash
git commit -s -m "feat: add new projection target"
```

This produces a commit message like:

```
feat: add new projection target

Signed-off-by: Your Name <your.email@example.com>
```

> **Tip:** Configure git to sign off automatically:
> `git config --global format.signOff true`

## Getting started

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) for environment and dependency management

### Setup

```bash
git clone https://github.com/Cnext-eu/kairos-ontology-toolkit.git
cd kairos-ontology-toolkit
uv sync --all-groups
```

### Install git hooks

Install the pre-commit hook to auto-sync `.github/` skills to the scaffold:

```powershell
# Windows
powershell scripts/install-hooks.ps1

# Linux/Mac
python scripts/sync_dev_skills.py  # run manually, or set up your own hook
```

The hook ensures that when you edit skills in `.github/skills/` (the master
source), the scaffold copies (`src/kairos_ontology/scaffold/skills/`) stay in
sync automatically. CI will fail if they drift apart.

### Running tests

```bash
# Fast dev cycle (skips slow integration tests — ~15s)
uv run pytest

# Full test suite including slow integration tests (~50s)
uv run pytest -m ""

# Slow integration tests only
uv run pytest -m slow

# Lint check (run separately from tests)
uv run ruff check src/ tests/
```

### Code style

- **Formatter:** Black (line length 100)
- **Linter:** Ruff (`uv run ruff check src/ tests/`)
- Source layout: `src/kairos_ontology/`
- All new functions and endpoints must have unit tests

## How to contribute

### Reporting bugs

Open a [GitHub Issue](https://github.com/Cnext-eu/kairos-ontology-toolkit/issues/new)
with:

- Steps to reproduce
- Expected vs actual behaviour
- Python version and OS

### Suggesting features

Open a GitHub Issue with the `enhancement` label describing:

- The use case
- Proposed solution (if any)
- Alternatives considered

### Submitting a pull request

1. **Fork** the repository and create a feature branch:
   ```bash
   git checkout -b feature/my-improvement
   ```
2. Make your changes — follow existing code conventions.
3. Add or update tests for your changes.
4. Run tests: `uv run pytest` (fast) or `uv run pytest -m ""` (full)
5. Commit with DCO sign-off: `git commit -s`
6. Push and open a Pull Request against `main`.

### Branch naming

| Prefix | Use for |
|--------|---------|
| `feature/*` (or `feat/*`) | New features / capabilities |
| `fix/*` | Bug fixes targeting the next release |
| `hotfix/x.y.z` | Urgent patch to the **released** line when `main` already has unreleased features (cut from the release tag) |
| `chore/*` | Maintenance, dependencies, CI |
| `docs/*` | Documentation only |

Never commit to `main` directly — always branch + PR.

> **Releasing & hotfixes:** see [`docs/RELEASING.md`](docs/RELEASING.md) for the full
> SemVer policy, the bugfix-vs-feature decision tree, and the hotfix/back-merge flow
> (DD-067).

### Commit message convention

| Prefix | When |
|--------|------|
| `feat:` | New feature or capability |
| `fix:` | Bug fix |
| `chore:` | Maintenance, dependencies, CI |
| `docs:` | Documentation only |
| `ontology:` | Ontology file changes |
| `projection:` | Projection output changes |

### PR checklist

- [ ] Tests pass (`uv run pytest` for fast, `uv run pytest -m ""` for full)
- [ ] `python -m kairos_ontology validate` passes (if ontology changes)
- [ ] `python -m kairos_ontology project` regenerated (if ontology changes)
- [ ] DCO sign-off on all commits
- [ ] No secrets, credentials, or PII in code

### Testing a pre-release

If you want hub-repo users to test your changes before a GA release:

1. Edit `src/kairos_ontology/__init__.py` → set version to e.g. `3.7.0-rc.1`
2. Run `uv lock && uv build`
3. Commit, tag (`git tag v3.7.0-rc.1`), and push (`git push --tags`)
4. CI creates a GitHub Release with the `.whl` attached
5. Ask testers to switch their hub `pyproject.toml`:
   ```toml
   [tool.kairos]
   channel = "preview"
   ```
6. Testers run `kairos-ontology update --upgrade` (uses `uv lock` + `uv sync`)
7. After validation, create a GA release and testers switch back to `channel = "stable"`.

> See [`docs/RELEASING.md`](docs/RELEASING.md) for how pre-releases fit into the
> overall release flow (channels, SemVer, hotfixes).

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md).
Please read it before participating.

## License

By contributing, you agree that your contributions will be licensed under the
[Apache License 2.0](LICENSE).
