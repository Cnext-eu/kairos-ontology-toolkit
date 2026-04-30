---
name: kairos-toolkit-ops
description: >
  Consolidated operations guide for the kairos-ontology-toolkit.
  Covers releasing new versions (stable + pre-release), upgrading hub repos
  via channels, refreshing managed files, and version diagnostics.
---

# Toolkit Operations Skill

You are helping a user with **kairos-ontology-toolkit operations** — releasing,
upgrading, or diagnosing versions.

Determine which workflow the user needs:
- **Release** → they are a toolkit maintainer publishing a new version
- **Update** → they are a hub-repo user upgrading their toolkit dependency
- **Diagnose** → they want to check versions, channels, or drift

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

The toolkit uses an interactive release script:

```powershell
.\release.ps1
```

The script presents a menu:

```
Select release type:
  [1] Patch (bug fixes)           2.17.0 -> 2.17.1
  [2] Minor (new features)        2.17.0 -> 2.18.0
  [3] Major (breaking changes)    2.17.0 -> 3.0.0
  [4] Pre-release (rc/beta/alpha) 2.17.0 -> 2.18.0-rc.1
```

#### Release levels explained

| Level | When to use | Example tag |
|-------|-------------|-------------|
| **Patch** | Bug fixes, no API changes | `v2.17.1` |
| **Minor** | New features, skill updates, scaffold improvements | `v2.18.0` |
| **Major** | Breaking changes to CLI, API, or projections | `v3.0.0` |
| **Pre-release** | Testing before GA — for hub-repo validation | `v2.18.0-rc.1` |

#### Pre-release sub-menu

When selecting [4], the script asks for a label:

```
Select pre-release label:
  [1] rc    (release candidate — feature-complete, final testing)
  [2] beta  (feature-complete, may have bugs)
  [3] alpha (early preview, unstable)
```

The sequence number auto-increments from existing tags (e.g., if `v2.18.0-rc.1`
exists, the next will be `v2.18.0-rc.2`).

#### Version format

| Label | Git tag | PEP 440 (pyproject.toml) |
|-------|---------|--------------------------|
| Stable | `v2.17.0` | `2.17.0` |
| RC | `v2.18.0-rc.1` | `2.18.0rc1` |
| Beta | `v2.18.0-beta.1` | `2.18.0b1` |
| Alpha | `v2.18.0-alpha.1` | `2.18.0a1` |

### What the script does

1. Bumps version in `pyproject.toml` and `src/kairos_ontology/__init__.py`
2. Updates `poetry.lock`
3. Builds the package (`poetry build`)
4. Commits changes
5. Creates an annotated git tag
6. Pushes commit + tag to GitHub

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
python -m kairos_ontology update --upgrade
python -m kairos_ontology update
```

When testing is complete, switch back to stable:

```toml
[tool.kairos]
channel = "stable"
```

### Upgrading the toolkit

```bash
# Automatic: resolves version from channel
python -m kairos_ontology update --upgrade
```

This will:
1. Read the `channel` from `[tool.kairos]` in `pyproject.toml`
2. Resolve the channel to a git tag via GitHub Releases API (`gh` CLI required)
3. Install the resolved version with pip
4. Update the `pyproject.toml` dependency pin to match

### Refreshing managed files

After upgrading, refresh toolkit-owned files:

```bash
# Preview what would change
python -m kairos_ontology update --check

# Apply updates (refreshes outdated files + creates missing ones)
python -m kairos_ontology update
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
git add .github/ pyproject.toml
git commit -m "chore: update kairos-ontology-toolkit to vX.Y.Z"
```

### Pre-release testing workflow

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
3. Test projections, validate ontologies, etc.
4. When satisfied, switch back to stable:
   ```toml
   [tool.kairos]
   channel = "stable"
   ```
5. Run `python -m kairos_ontology update --upgrade` to revert to stable.

---

## 3. Version Diagnostics

### Check installed version

```bash
python -m kairos_ontology --version
```

### Check for drift

```bash
python -m kairos_ontology update --check
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
python -m kairos_ontology --version

# Latest stable
gh release list --repo Cnext-eu/kairos-ontology-toolkit --exclude-pre-releases --limit 1

# Latest pre-release
gh release list --repo Cnext-eu/kairos-ontology-toolkit --limit 1
```

---

## Agent Instructions

> **IMPORTANT:** Run all `pip` and `python` commands directly in the shell —
> do **NOT** wrap them in `Start-Process`, `Invoke-Expression`, or request
> elevated permissions. If a pip install fails with "Permission denied", retry
> with the `--user` flag.

> For releases: the `release.ps1` script is interactive. Run it with
> `mode="async"` and use `write_powershell` to send menu selections.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `update --check` reports drift | Toolkit upgraded but files not refreshed | Run `python -m kairos_ontology update` |
| `--version` shows old version | pip cache or wrong venv | `pip install --force-reinstall ...` |
| Channel resolution fails | `gh` CLI not installed/authenticated | Install GitHub CLI, run `gh auth login` |
| `--upgrade` picks wrong version | Wrong channel setting | Check `[tool.kairos] channel` in pyproject.toml |
| release.ps1 fails on git tag | Tag already exists | Delete with `git tag -d vX.Y.Z` and retry |
| Release workflow didn't trigger | Tag not pushed | `git push --tags` |
| Pre-release on PyPI | Workflow bug | Check `release.yml` — pre-releases should skip PyPI |
| Permission denied on pip | System Python | Add `--user` flag |
