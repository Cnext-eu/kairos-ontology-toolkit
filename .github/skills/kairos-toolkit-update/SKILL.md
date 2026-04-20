---
name: kairos-toolkit-update
description: >
  Guide for updating the kairos-ontology-toolkit in a hub repository.
  Covers checking versions, upgrading the package, refreshing managed files,
  and updating the dependency pin.
---

# Toolkit Update Skill

You are helping a user update the **kairos-ontology-toolkit** in their ontology
hub repository.

## Before you start

Check the current state:

```bash
# Installed toolkit version
python -m kairos_ontology --version

# Check if managed files are outdated
python -m kairos_ontology update --check

# Current dependency pin in pyproject.toml
grep kairos-ontology-toolkit pyproject.toml
```

## Update workflow

### Step 1 — Upgrade the package

```bash
# Reinstall latest from main (the default dependency target)
pip install --upgrade --force-reinstall "kairos-ontology-toolkit @ git+https://github.com/Cnext-eu/kairos-ontology-toolkit.git@main"

# Or install a specific version tag
pip install "kairos-ontology-toolkit @ git+https://github.com/Cnext-eu/kairos-ontology-toolkit.git@v1.3.0"
```

### Step 2 — Refresh managed files

The toolkit stamps version markers in files it owns (copilot-instructions.md,
skill files).  After upgrading, refresh them:

```bash
# Preview what would change
python -m kairos_ontology update --check

# Apply the updates
python -m kairos_ontology update
```

This updates:
- `.github/copilot-instructions.md`
- `.github/skills/*/SKILL.md`

### Step 3 — Reinstall hub dependencies

Since the hub's `pyproject.toml` points to `@main`, reinstalling picks up
the latest:

```bash
pip install -e . --force-reinstall --no-deps
```

No `pyproject.toml` edit is needed — it always tracks `main`.

### Step 4 — Commit

```bash
git add .github/ pyproject.toml
git commit -m "chore: update kairos-ontology-toolkit to vX.Y.Z"
```

## Version detection

The toolkit uses semantic versioning (`MAJOR.MINOR.PATCH`):
- **Patch** — bug fixes, no scaffold changes.
- **Minor** — new features, skill updates, scaffold improvements.  Always run
  `python -m kairos_ontology update` after a minor upgrade.
- **Major** — breaking changes.  Read the changelog before upgrading.

Managed files carry a version stamp:
```
<!-- kairos-ontology-toolkit:managed v1.2.0 -->
```

When the installed toolkit version is newer than the stamp, `update --check`
reports drift and exits with code 1 (useful for CI).

## CI integration

Add to your CI workflow to catch outdated managed files:

```yaml
- name: Check toolkit managed files
  run: python -m kairos_ontology update --check
```

This is already included in `.github/workflows/managed-check.yml` if your
repo was scaffolded by `kairos-ontology new-repo`.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `update --check` reports drift | Toolkit was upgraded but managed files weren't refreshed | Run `python -m kairos_ontology update` |
| Managed files missing | Repo was created before the skill was added | Run `python -m kairos_ontology init --company-domain <domain>` |
| `--version` shows old version | pip cache or wrong virtualenv | `pip install --force-reinstall kairos-ontology-toolkit` |
| pyproject.toml pin too old | Never updated after toolkit upgrade | Edit the `>=X.Y.Z` constraint manually |
