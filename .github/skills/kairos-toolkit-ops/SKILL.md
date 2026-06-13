---
name: kairos-toolkit-ops
description: >
  Consolidated operations guide for the kairos-ontology-toolkit.
  Covers releasing new versions (stable + pre-release), upgrading hub repos
  via channels (update --upgrade), refreshing managed files, version diagnostics,
  and updating reference models from the upstream repo.
---

# Toolkit Operations Skill

You are helping a user with **kairos-ontology-toolkit operations** — releasing,
upgrading, diagnosing versions, or updating reference models.

Determine which workflow the user needs:
- **Release** → they are a toolkit maintainer publishing a new version
- **Update** → they are a hub-repo user upgrading their toolkit dependency
- **Diagnose** → they want to check versions, channels, or drift
- **Update Reference Models** → they want to sync reference models from the upstream repo

---

## 1. Release Workflow (Toolkit Maintainers)

### Prerequisites

```bash
# Must be on main with a clean working tree
git checkout main
git pull origin main
git status  # should be clean
```

### Running a release

Release steps (all done manually or by Copilot):

```bash
# 1. Bump version in __init__.py (single source of truth)
#    Edit src/kairos_ontology/__init__.py: __version__ = "X.Y.Z"

# 2. Update lock and build
uv lock
uv build

# 3. Commit, tag, and push
git add uv.lock src/kairos_ontology/__init__.py
git commit -m "chore: bump version to X.Y.Z"
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push && git push --tags
```

#### Release levels explained

| Level | When to use | Example tag |
|-------|-------------|-------------|
| **Patch** | Bug fixes, no API changes | `v2.17.1` |
| **Minor** | New features, skill updates, scaffold improvements | `v2.18.0` |
| **Major** | Breaking changes to CLI, API, or projections | `v3.0.0` |
| **Pre-release** | Testing before GA — for hub-repo validation | `v2.18.0-rc.1` |

#### Version format

| Label | Git tag | PEP 440 (__init__.py) |
|-------|---------|--------------------------|
| Stable | `v2.17.0` | `2.17.0` |
| RC | `v2.18.0-rc.1` | `2.18.0rc1` |
| Beta | `v2.18.0-beta.1` | `2.18.0b1` |
| Alpha | `v2.18.0-alpha.1` | `2.18.0a1` |

### What happens after push

The `.github/workflows/release.yml` workflow triggers on `v*` tags:

| Tag type | GitHub Release | PyPI publish |
|----------|---------------|--------------|
| Stable (`v2.17.0`) | ✅ Latest | ✅ Published |
| Pre-release (`v2.18.0-rc.1`) | ✅ Pre-release | ❌ Skipped |

### Verifying the release

```bash
# Check the tag exists
git tag -l "v2.18*"

# Check GitHub Release was created
gh release list --limit 5

# Check workflow status
gh run list --workflow release.yml --limit 3
```

---

## 2. Update Workflow (Hub-Repo Users)

### Channels

Hub repos have a `[tool.kairos]` section in `pyproject.toml`:

```toml
[tool.kairos]
channel = "stable"    # "stable" (default), "preview", or an explicit tag
```

| Channel | Resolves to | Use case |
|---------|-------------|----------|
| `stable` | Latest GA release (e.g. `v2.17.0`) | Production hubs |
| `preview` | Latest release including pre-releases (e.g. `v2.18.0-rc.1`) | Testing new features |
| `v2.16.0` | Explicit pinned version | Locked environments |

### Which channel should I use?

| Situation | Recommended channel |
|-----------|-------------------|
| Day-to-day ontology work, production pipelines | `stable` |
| Validating a new toolkit release before rolling out | `preview` |
| Reproducing a specific issue or locking a CI build | Explicit tag (e.g. `v2.17.0-rc.1`) |
| Toolkit maintainer asked you to test an RC | `preview` or the specific RC tag |

> **Tip:** Most hub repos should stay on `stable`. Only switch to `preview` when
> you actively want to test a pre-release — then switch back once satisfied.

### How channels handle pre-releases

There is **no interactive version picker**. The `update --upgrade` command
automatically resolves the version based on your channel. Here is how it behaves
when the release list looks like this:

```
v2.18.0-rc.1   ← newest (pre-release)
v2.17.0        ← latest stable
v2.16.0
```

| Your channel | `--upgrade` installs | Why |
|--------------|---------------------|-----|
| `stable` | `v2.17.0` | Skips all pre-releases (rc, beta, alpha) |
| `preview` | `v2.18.0-rc.1` | Picks the most recent release of any kind |
| `v2.17.0-rc.1` | `v2.17.0-rc.1` | Explicit pin — always uses that exact tag |

**Key points:**
- `stable` will **never** install an RC, beta, or alpha — even if it is the newest release.
- `preview` always picks the **most recent** release, whether it is stable or pre-release.
- An explicit tag pin is never resolved — it is used as-is.

### Pinning to a specific pre-release

If you want to test a specific RC without using the `preview` channel (which would
auto-advance to newer pre-releases), pin the exact tag:

```toml
[tool.kairos]
channel = "v2.18.0-rc.1"
```

Then run:

```bash
uv run kairos-ontology update --upgrade
uv run kairos-ontology update
```

When testing is complete, switch back to stable:

```toml
[tool.kairos]
channel = "stable"
```

### Upgrading the toolkit

```bash
# Automatic: resolves version from channel
uv run kairos-ontology update --upgrade
```

This will:
1. Read the `channel` from `[tool.kairos]` in `pyproject.toml`
2. Resolve the channel to a git tag via GitHub Releases API (`gh` CLI required)
3. Update the `pyproject.toml` dependency pin to the `.whl` URL
4. Run `uv lock` to update the lock file
5. Run `uv sync` to install the new version
6. **Automatically refresh managed files under the new version** — when the
   version actually changes, `--upgrade` re-execs the refresh in a fresh
   `uv run` so skills/instructions are stamped against the *new* toolkit (no
   manual second `update` needed). (DD-049)

> **Always run via `uv run`.** Invoking `python -m kairos_ontology` or a
> globally-installed `kairos-ontology` may use a different (often older) toolkit
> than the version pinned in this hub. The CLI now warns when the running version
> differs from the `pyproject.toml` pin — if you see that warning, re-run the
> command with `uv run kairos-ontology …` (or `uv sync`). (DD-049)

### Refreshing managed files

`update --upgrade` already refreshes managed files automatically (step 6 above).
You only need to run `update` on its own to refresh without upgrading, e.g. after
pulling someone else's pin bump:

```bash
# Preview what would change
uv run kairos-ontology update --check

# Apply updates (refreshes outdated files + creates missing ones)
uv run kairos-ontology update
```

Managed files:
- `.github/copilot-instructions.md`
- `.github/skills/*/SKILL.md`

#### Stale skill cleanup

When the toolkit renames or removes a skill, `update` automatically removes
the old skill directory from `.github/skills/` — **but only if** it has the
toolkit managed marker (`<!-- kairos-ontology-toolkit:managed ... -->`).
Custom skills you create yourself (without this marker) are never touched.

Example output when a skill was renamed:
```
🗑️  Removed 1 stale managed skill(s):
   .github/skills/kairos-toolkit-update/
✅ Created 1 new file(s) (v2.18.0):
   .github/skills/kairos-toolkit-ops/SKILL.md
```

### Restart Copilot

After refreshing managed files, restart the Copilot CLI to load updated skills:

```
/exit
copilot
```

### Commit the upgrade

```bash
git add .github/ pyproject.toml uv.lock
git commit -m "chore: update kairos-ontology-toolkit to vX.Y.Z"
```

---

## 4. Update Reference Models

Hub repos that use shared ontology reference models (e.g., FIBO Party, W3C Org)
can pull the latest versions from the upstream
[kairos-ontology-referencemodels](https://github.com/Cnext-eu/kairos-ontology-referencemodels)
repository.

### When to update

- After the reference models repo publishes a new release/tag
- When starting work on a new domain that depends on a reference model
- When the toolkit notifies you of a new available version

### Running the update

```powershell
# Default: fetch latest from main
kairos-ontology update-refmodels

# Pin to a specific tag or branch
kairos-ontology update-refmodels --ref v1.2.1
```

### What it does

1. Performs a sparse shallow clone of `Cnext-eu/kairos-ontology-referencemodels`
2. Extracts only the `ontology-reference-models/` subfolder
3. Replaces the local `model/reference-models/` folder with the fetched version
4. Reports the commit SHA and version (if a VERSION file is present)
5. Cleans up the temporary clone (no git history left behind)

### Post-update steps

After updating reference models:

1. **Validate** — run `kairos-ontology validate` to check for breaking changes
2. **Check imports** — verify your domain ontologies' `owl:imports` still resolve
3. **Re-project** — regenerate dbt/silver/gold output to pick up any new
   properties from the reference models
4. **Commit** — commit the updated reference models

```bash
git add model/reference-models/
git commit -m "chore: update reference models to <version/sha>"
```

### Troubleshooting

| Issue | Fix |
|-------|-----|
| `git clone failed` | Check network access to GitHub; verify the ref/tag exists |
| Properties disappeared after update | The upstream may have renamed/removed classes — check the reference models CHANGELOG |
| SHACL violations after update | New constraints may require additional annotations — run `kairos-ontology validate` for details |

### Pre-release testing workflow

1. Switch to preview channel:
   ```toml
   [tool.kairos]
   channel = "preview"
   ```
2. Run the upgrade:
   ```bash
   uv run kairos-ontology update --upgrade
   uv run kairos-ontology update
   ```
3. Test projections, validate ontologies, etc.
4. When satisfied, switch back to stable:
   ```toml
   [tool.kairos]
   channel = "stable"
   ```
5. Run `uv run kairos-ontology update --upgrade` to revert to stable.

---

## 3. Version Diagnostics

### Check installed version

```bash
uv run kairos-ontology --version
```

### Check for drift

```bash
uv run kairos-ontology update --check
```

Exit code 1 means managed files are outdated or missing.

### Check current channel and pin

```bash
grep -A2 '\[tool.kairos\]' pyproject.toml
grep kairos-ontology-toolkit pyproject.toml
```

### List available releases

```bash
gh release list --repo Cnext-eu/kairos-ontology-toolkit --limit 10
```

### Compare installed vs available

```bash
# Installed
uv run kairos-ontology --version

# Latest stable
gh release list --repo Cnext-eu/kairos-ontology-toolkit --exclude-pre-releases --limit 1

# Latest pre-release
gh release list --repo Cnext-eu/kairos-ontology-toolkit --limit 1
```

---

## Agent Instructions

> **IMPORTANT:** Run toolkit commands with `uv run kairos-ontology <command>`.
> Do **NOT** wrap them in `Start-Process`, `Invoke-Expression`, or request
> elevated permissions.

> For releases: follow the steps in §1 above (edit `__init__.py`, `uv lock`,
> `uv build`, commit, tag, push).

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `update --check` reports drift | Toolkit upgraded but files not refreshed | Run `uv run kairos-ontology update` |
| `--version` shows old version | Stale venv or wrong directory | Run `uv sync` to refresh |
| Channel resolution fails | `gh` CLI not installed/authenticated | Install GitHub CLI, run `gh auth login` |
| `--upgrade` picks wrong version | Wrong channel setting | Check `[tool.kairos] channel` in pyproject.toml |
| `uv` not found | uv not installed | `irm https://astral.sh/uv/install.ps1 \| iex` (Windows) |
| Tag already exists | Duplicate release attempt | Delete with `git tag -d vX.Y.Z` and retry |
| Release workflow didn't trigger | Tag not pushed | `git push --tags` |
