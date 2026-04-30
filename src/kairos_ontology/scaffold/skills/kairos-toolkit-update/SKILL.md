---
name: kairos-toolkit-update
description: >
  Guide for updating the kairos-ontology-toolkit in a hub repository.
  Covers checking versions, upgrading the package, refreshing managed files,
  channel-based version resolution, and updating the dependency pin.
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

# Current channel setting
grep -A2 '\[tool.kairos\]' pyproject.toml
```

## Channels

Hub repos have a `[tool.kairos]` section in `pyproject.toml` that controls
which toolkit version is resolved during upgrades:

| Channel | Resolves to | Use case |
|---------|-------------|----------|
| `stable` (default) | Latest GA release (e.g. `v2.17.0`) | Production hubs |
| `preview` | Latest release including pre-releases (e.g. `v2.18.0-rc.1`) | Testing new features |
| `v2.16.0` | Explicit pinned version | Locked environments |

To switch channels, edit `pyproject.toml`:

```toml
[tool.kairos]
channel = "preview"   # or "stable", or an explicit tag like "v2.16.0"
```

## Update workflow

> **Agent instructions (IMPORTANT):**
> Run all `pip` and `python` commands directly in the shell — do **NOT** wrap
> them in `Start-Process`, `Invoke-Expression`, or request elevated permissions.
> If a pip install fails with "Permission denied", retry with the `--user` flag.

### Step 1 — Upgrade the package (recommended: use --upgrade)

```bash
# Automatic: resolves version from channel in [tool.kairos]
python -m kairos_ontology update --upgrade
```

This will:
1. Read the `channel` from `[tool.kairos]` in `pyproject.toml`
2. Resolve the channel to a git tag via GitHub releases API
3. Install the resolved version with pip
4. Update the `pyproject.toml` dependency pin to match

Alternatively, install manually:

```bash
# Install latest stable release
python -m pip install --upgrade "kairos-ontology-toolkit @ git+https://github.com/Cnext-eu/kairos-ontology-toolkit.git@v2.17.0"

# Install a pre-release for testing
python -m pip install --upgrade "kairos-ontology-toolkit @ git+https://github.com/Cnext-eu/kairos-ontology-toolkit.git@v2.18.0-rc.1"
```

### Step 2 — Refresh managed files

The toolkit stamps version markers in files it owns (copilot-instructions.md,
skill files).  After upgrading, refresh them:

```bash
# Preview what would change
python -m kairos_ontology update --check

# Apply the updates (refreshes outdated files + creates missing ones)
python -m kairos_ontology update
```

This updates:
- `.github/copilot-instructions.md`
- `.github/skills/*/SKILL.md`

New managed files (e.g., skills added in a newer toolkit version) are
**created automatically** — no need to re-run `init`.

### Step 3 — Restart Copilot to load updated skills

After refreshing managed files, the `.github/skills/` files on disk have
changed but Copilot's in-memory skill cache is stale.

1. Type `/exit` in the Copilot CLI to quit the current session.
2. Restart Copilot (`copilot` or your usual launch command).

This ensures new or updated skills are available immediately.

### Step 4 — Commit

```bash
git add .github/ pyproject.toml
git commit -m "chore: update kairos-ontology-toolkit to vX.Y.Z"
```

## Pre-release testing workflow

To test a pre-release in a hub repo:

1. Switch to preview channel:
   ```toml
   [tool.kairos]
   channel = "preview"
   ```
2. Run the upgrade:
   ```bash
   python -m kairos_ontology update --upgrade
   python -m kairos_ontology update
   ```
3. Test your projections, validate ontologies, etc.
4. When satisfied, switch back to stable:
   ```toml
   [tool.kairos]
   channel = "stable"
   ```
5. Run `python -m kairos_ontology update --upgrade` to revert to stable.

## Version detection

The toolkit uses semantic versioning (`MAJOR.MINOR.PATCH`) with optional
pre-release labels:
- **Patch** — bug fixes, no scaffold changes.
- **Minor** — new features, skill updates, scaffold improvements.  Always run
  `python -m kairos_ontology update` after a minor upgrade.
- **Major** — breaking changes.  Read the changelog before upgrading.
- **Pre-release** — `rc`, `beta`, `alpha` suffixes (e.g. `2.17.0rc1`).
  Only available on the `preview` channel.

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
| Managed files missing | Repo was created before the skill was added | Run `python -m kairos_ontology update` (creates missing files automatically) |
| `--version` shows old version | pip cache or wrong virtualenv | `python -m pip install --force-reinstall kairos-ontology-toolkit` |
| Permission denied on pip install | System Python without write access | Add `--user` flag: `python -m pip install --user ...` |
| Channel resolution fails | `gh` CLI not installed or not authenticated | Install GitHub CLI and run `gh auth login` |
| `--upgrade` picks wrong version | Wrong channel setting | Check `[tool.kairos] channel` in pyproject.toml |
