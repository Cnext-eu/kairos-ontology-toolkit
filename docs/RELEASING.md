# Release management

This is the single source of truth for how we version and release the
**kairos-ontology-toolkit**. It is intentionally lightweight — tuned for a small
team that supports **only the latest release line**. (Decision: DD-067.)

> **TL;DR**
> - `fix:` → **patch**, `feat:` → **minor**, breaking → **major** (SemVer).
> - A bugfix to the released version goes out as its **own patch release** — never
>   bundled into a feature (minor) release.
> - We support **only the latest release**. No long-lived maintenance branches.
> - When `main` already holds unreleased features, patch via a short-lived
>   **`hotfix/x.y.z` branch cut from the release tag**, then **back-merge to `main`**.

---

## 1. Versioning (SemVer)

`X.Y.Z` = `MAJOR.MINOR.PATCH`. The version lives in **one** place —
`src/kairos_ontology/__init__.py` (`__version__`).

| Change | Commit prefix | Bump | Example |
|--------|---------------|------|---------|
| Bug fix, no API change | `fix:` | **patch** `Z` | `3.16.0` → `3.16.1` |
| New feature / capability | `feat:` | **minor** `Y` | `3.16.1` → `3.17.0` |
| Breaking CLI/API/projection change | `feat!:` / `BREAKING CHANGE` | **major** `X` | `3.17.0` → `4.0.0` |
| Docs / chore / CI only | `docs:` / `chore:` | usually **none** | — |

The toolkit is **not** published to PyPI — every release is a **GitHub Release with
the built wheel + sdist attached**, consumed by hub repos via git-tag / wheel-URL
pins and `kairos-ontology update --upgrade` (DD-066, DD-013).

---

## 2. Support policy

**We support only the latest released version.** Once a new minor ships
(`3.17.0`), the previous line (`3.16.x`) is no longer patched — users upgrade
forward. This is what keeps the branching model simple: there are **no maintenance
branches**, only `main` plus the occasional ephemeral hotfix branch.

Pre-releases do **not** become the latest supported stable line. If `main` contains
V4 release-candidate work (for example `v4.4.0rc11`) while the GitHub **Latest**
stable release is still `v3.24.1`, production/stable fixes still target the
`v3.24.x` line. In that situation, never tag `main` as a stable patch; cut the
patch from the stable tag as described in Case B below.

> If the team ever needs to support multiple older minors at once, revisit DD-067
> and introduce `release/X.Y` maintenance branches. Don't add that machinery before
> it's actually needed.

---

## 3. Branch naming

| Branch | Purpose | Cut from | Merges to |
|--------|---------|----------|-----------|
| `feature/*` (or `feat/*`) | New functionality for the next minor | `main` | `main` |
| `fix/*` | Bug fix that can wait for the next release | `main` | `main` |
| `hotfix/x.y.z` | **Urgent** patch to the released line when `main` has diverged | the release **tag** `vX.Y.Z` | tag + back-merge to `main` |
| `chore/*`, `docs/*` | Maintenance, CI, documentation | `main` | `main` |

All work lands on `main` via PR. **Never commit to `main` directly.**

---

## 4. The core question: bugfix vs feature release

> **Never put a bugfix in a feature (minor) release.** A patch ships on its own
> `vX.Y.(Z+1)` tag; features accumulate separately for the next `vX.(Y+1).0`.

When a bug is found in the current release `vX.Y.Z`, ask **one** question:

> **Does `main` already contain unreleased feature work?**
> ```bash
> git fetch --tags origin
> git log --oneline vX.Y.Z..origin/main      # what's on main but not yet released?
> ```

### Case A — `main` is clean (no unreleased features)

Most common case. Just fix on `main` and cut a patch:

```bash
git switch -c fix/short-description origin/main
# ...fix + add a regression test...
# bump PATCH in src/kairos_ontology/__init__.py  (e.g. 3.16.0 -> 3.16.1)
# promote CHANGELOG [Unreleased] -> ## [3.16.1] — YYYY-MM-DD
git commit -s -am "fix: <what> "
git push -u origin fix/short-description
gh pr create --base main --fill        # review + CI, then merge
```

Then tag the merged commit on `main` (see §6).

### Case B — `main` already has unreleased features

Don't tag `main` — that would publish the unreleased features. Patch the release
line on a throwaway hotfix branch, then bring the fix back to `main`:

```bash
# 1. Branch off the RELEASE TAG, not main
git fetch --tags origin
git switch -c hotfix/3.16.1 vX.Y.Z          # e.g. v3.16.0

# 2. Fix + regression test, bump PATCH, promote CHANGELOG to [3.16.1]
git commit -s -am "fix: <what>"
git push -u origin hotfix/3.16.1

# 3. Release straight from the hotfix branch (it becomes the new "Latest")
git tag -a v3.16.1 -m "Release v3.16.1"
git push origin v3.16.1                      # release.yml builds + publishes

# 4. Back-merge so the next feature release keeps the fix
gh pr create --base main --head hotfix/3.16.1 \
  --title "fix: back-merge v3.16.1 hotfix into main" --fill
```

**Back-merge notes:**
- On a `__version__` conflict, **keep `main`'s** (higher, in-progress) version — the
  fix's patch number is already shipped on its own tag.
- The back-merge PR changes `src/` without bumping `main`'s version, so the
  `version-check` CI gate will flag it → add the **`skip-version`** label to the PR.
- Make sure the fix's CHANGELOG bullet also appears under `main`'s `[Unreleased]`
  (or its in-progress version section).

> **Why a hotfix branch off the tag instead of a `release/X.Y` branch?** Because we
> only support the latest line, a maintenance branch would sit idle between hotfixes
> and just add merge overhead. The `hotfix/*` branch is created only when needed and
> deleted after back-merge.

### Case C — V4 RC on `main`, V3 still latest stable

This is a special case of Case B. `main` is the V4 preview line, but stable users
still consume the latest GA release (for example `v3.24.1`). A V3 production fix
must be made from the stable tag, not from `main`.

Recommended local setup: use a separate worktree so V3 hotfix work cannot be
mixed with V4 RC work:

```powershell
cd G:\Git
git -C kairos-ontology-toolkit fetch --tags origin
git -C kairos-ontology-toolkit worktree add kairos-ontology-toolkit-v3 v3.24.1
```

Start each V3 hotfix from that worktree:

```powershell
cd G:\Git\kairos-ontology-toolkit-v3
git switch -c hotfix/3.24.2-short-bug-name
```

Before tagging a V3 patch, run these guardrails:

```powershell
git merge-base --is-ancestor v3.24.1 HEAD
git log --oneline v3.24.1..HEAD
git branch --show-current
```

The `merge-base` command should exit 0, proving the hotfix branch descends from
the stable tag. The log should contain only the V3 bugfix, its regression test,
and the patch version/changelog bump. If it contains V4 feature commits, stop:
you are on the wrong line.

Patch-release runbook:

```powershell
# In G:\Git\kairos-ontology-toolkit-v3 on hotfix/3.24.2-short-bug-name
# 1. Fix + regression test
# 2. Bump src/kairos_ontology/__init__.py: 3.24.1 -> 3.24.2
# 3. Add CHANGELOG.md heading: ## [3.24.2] — YYYY-MM-DD
uv lock
uv build
git add .
git commit -m "fix: short bug description"
git tag -a v3.24.2 -m "Release v3.24.2"
git push -u origin hotfix/3.24.2-short-bug-name
git push origin v3.24.2
```

After the release workflow succeeds, bring the actual fix back to `main` without
replacing `main`'s V4 version:

```powershell
cd G:\Git\kairos-ontology-toolkit
git switch main
git pull origin main
git switch -c fix/backmerge-v3.24.2
git cherry-pick <fix-commit-sha>       # avoid cherry-picking the V3 version bump if possible
```

If the version or changelog conflicts, keep `main`'s V4 version and add the bugfix
note to `main`'s current changelog section. Open a PR to `main`; if CI's
version-check flags the back-merge because `src/` changed without bumping V4, add
the `skip-version` label.

Stable/preview channel expectations:

| Hub channel | Should resolve to | Why |
|-------------|-------------------|-----|
| `stable` | latest GA, e.g. `v3.24.1` or `v3.24.2` | skips RC/beta/alpha releases |
| `preview` | latest release including RC, e.g. `v4.4.0rc11` | used for V4 validation |
| explicit tag | exactly that tag | reproducible testing or pinned production |

---

## 5. Feature releases

No special handling — this is the steady-state flow:

1. Land `feat:` PRs on `main` over the cycle.
2. When ready, bump **minor** (`vX.(Y+1).0`), promote the CHANGELOG, tag `main`.

If hub users should validate features before GA, ship a **pre-release** first
(`vX.Y.0-rc.1`) and have them set `[tool.kairos] channel = "preview"`; switch back
to `stable` after GA (DD-013, and the `kairos-toolkit-ops` skill §2).

---

## 6. Release checklist

Run from a clean `main` (or the hotfix branch in Case B):

1. **Bump** `__version__` in `src/kairos_ontology/__init__.py`.
2. **CHANGELOG** — promote `[Unreleased]` to `## [X.Y.Z] — YYYY-MM-DD`; leave a fresh
   empty `[Unreleased]` above it. *(CI enforces a matching entry for GA tags.)*
3. **Lock + build**: `uv lock` then `uv build`.
4. **Commit** (`chore: bump version to X.Y.Z`), open/merge the PR (or, for a hotfix,
   tag the branch directly).
5. **Tag** the released commit on `main`: `git tag -a vX.Y.Z -m "Release vX.Y.Z"` and
   `git push origin vX.Y.Z`. *(Never push commits straight to `main`; push the tag.)*
6. **Verify**:
   ```bash
   gh run list --workflow release.yml --limit 1     # build + github-release succeeded
   gh release list --limit 3                          # vX.Y.Z is "Latest"
   ```

Pre-release tags (`-rc.N` / `-beta.N` / `-alpha.N`) are exempt from the CHANGELOG
gate and are published as GitHub **pre-releases** (never marked Latest).

---

## 7. Out of scope (for now)

Deliberately **not** adopted while the team is small — revisit only if it grows:

- Automated version bumps / changelog generation (release-please, semantic-release).
- Supporting more than the latest minor in parallel (`release/X.Y` branches).
- Artifact signing / SLSA provenance / PyPI publishing (see DD-066).

See also: [`docs/design/toolkit-design-decisions.md`](design/toolkit-design-decisions.md)
DD-067 (this policy), DD-066 (distribution), DD-013 (channels), and the
`kairos-toolkit-ops` skill for the operational walkthrough.
