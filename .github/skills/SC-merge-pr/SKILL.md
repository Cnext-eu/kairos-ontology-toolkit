---
name: SC-merge-pr
description: >
  Create a pull request to merge the current feature branch into main.
  Covers commit hygiene, push, PR creation via gh CLI, and post-merge cleanup.
---

# SC — Merge via Pull Request

You are helping the user finish a feature branch and create a pull request
to merge into `main`.

## Before you start

1. Confirm the user is on a feature branch (not `main`).
2. Check for uncommitted changes.
3. Ask if they want to run validation before creating the PR:
   `python -m kairos_ontology validate`
4. **Release intent (toolkit repo only):** if this change will ship a release,
   decide the version bump **now** and commit it to the feature branch *before*
   creating the PR — see [Step 7b](#step-7b--tag-the-release-version-bump-already-on-the-branch).
   Because `main` is protected, bundling the bump into the feature PR avoids a
   separate bump-only PR and keeps the release tag reachable from `main`.

## Workflow

### Step 1 — Verify branch and status

```bash
git branch --show-current
git status
```

- If on `main`: stop — tell the user to switch to their feature branch.
- If uncommitted changes exist: ask user to commit or stash first.

### Step 2 — Ensure all changes are committed

If there are staged or unstaged changes:

```bash
git add .
git commit -m "<type>: <description>"
```

Commit message convention:

| Prefix | When |
|--------|------|
| `ontology:` | Ontology file changes |
| `feat:` | New feature or capability |
| `fix:` | Bug fix |
| `chore:` | Maintenance, deps, CI |
| `docs:` | Documentation |
| `projection:` | Projection output changes |

### Step 3 — Rebase on latest main (optional but recommended)

```bash
git fetch origin main
git rebase origin/main
```

If conflicts arise, help the user resolve them before continuing.

### Step 4 — Security review

Before pushing, scan the changed files for common security issues:

```bash
git diff main --name-only
```

**For Python / service code changes**, check:

| Check | What to look for |
|-------|-----------------|
| **SPDX headers** | Every new/modified `.py` file starts with `# SPDX-License-Identifier: Apache-2.0` and `# Copyright 2026 Cnext.eu` |
| **Path traversal** | User input used in file paths without sanitising `/`, `\`, `..` |
| **Command injection** | `subprocess` calls using `shell=True` or string concatenation |
| **Secret exposure** | Tokens, keys, or passwords in code, config defaults, or API responses |
| **CORS** | `allow_origins=["*"]` in production settings |
| **Auth bypass** | Endpoints missing `Authorization` header requirement |
| **Dependency pinning** | New dependencies without version pins or from untrusted sources |
| **Dependency license** | New dependencies must be Apache-2.0-compatible (BSD, MIT, ISC OK; GPL is NOT) |

**For ontology / scaffold changes**, check:

| Check | What to look for |
|-------|-----------------|
| **Template injection** | User-controlled values interpolated into templates without sanitising |
| **Namespace hijacking** | Namespace URIs pointing to domains the org doesn't control |
| **Sensitive data in ontology** | PII, credentials, or internal URLs embedded in `.ttl` labels/comments |
| **No proprietary content** | No client-specific or proprietary information in examples or sample data |

If any issues are found, fix them before proceeding.  Do NOT create the PR
with known security problems.

### Step 5 — Push the branch

```bash
git push -u origin HEAD
```

### Step 4b — Link issues with closing keywords (MANDATORY)

Before writing the PR body, identify which open issues this PR **fully
resolves**. For each one, the PR **body** (description) MUST contain a GitHub
**closing keyword** so the issue auto-closes when the PR merges:

```
Closes #175
Fixes #174
Resolves #166
```

> ⚠️ **Why this matters:** an issue reference like `#175` on its own — or a
> reference in the PR **title** — does **NOT** auto-close the issue on merge.
> Without a closing keyword the issue stays open after the fix ships (this is
> exactly what left #174/#175 open after PR #177 merged). Only the keywords
> below, in the PR **body** or a commit message, trigger auto-close.

| Use | Keyword (any case) | When |
|-----|--------------------|------|
| **Auto-close** | `close` / `closes` / `closed`, `fix` / `fixes` / `fixed`, `resolve` / `resolves` / `resolved` followed by `#NNN` | The PR **fully fixes** the issue |
| **Reference only** (no close) | plain `#NNN` (no keyword) | The PR is *related to* / *partially addresses* the issue, or the issue is a follow-up that should stay open |

- One keyword **per issue** (`Closes #1, #2` does NOT close #2 — write
  `Closes #1` and `Closes #2`).
- For a follow-up/spin-off issue that must stay open, reference it as a plain
  `#NNN` (e.g. "follow-up: #176") so it is linked but **not** closed.

### Step 5 — Create the pull request

Use the GitHub CLI (`gh`):

```bash
gh pr create --base main --fill
```

Or with explicit title and body (note the **`Closes:` section** — see
[Step 4b](#step-4b--link-issues-with-closing-keywords-mandatory)):

```bash
gh pr create --base main \
  --title "<type>: <short description>" \
  --body "## Changes

- <bullet summary of what changed>

## Closes
Closes #<issue fully fixed by this PR>
Fixes #<another issue fully fixed by this PR>

<!-- Follow-up / related issues that should STAY OPEN: reference without a
     keyword, e.g. 'Follow-up: #176' -->

## Checklist
- [ ] Closing keywords (\`Closes/Fixes/Resolves #NNN\`) added for every issue this PR fully fixes
- [ ] \`python -m kairos_ontology validate\` passes
- [ ] \`python -m kairos_ontology project\` regenerated (if ontology changed)
- [ ] \`_master.ttl\` updated (if new domain added)
- [ ] Hub README domain table updated (if new domain added)
- [ ] Security review passed (no path traversal, no secrets, no shell=True)"
```

### Step 5b — Merge the pull request

After the PR has been reviewed and approved, merge it with `--delete-branch`
so the remote branch is cleaned up automatically:

```bash
gh pr merge --squash --delete-branch
```

> `--delete-branch` tells GitHub to delete the remote branch automatically
> after the merge completes.

### Step 6 — Confirm

Print a summary:

```
✅ Pull request created!
   Branch: feature/add-order-domain → main
   PR URL: https://github.com/<org>/<repo>/pull/<number>
   🗑️  Remote branch will be deleted automatically after merge.

Next steps:
  - Review the PR on GitHub
  - After merge, run local cleanup:
      git checkout main && git pull origin main && git branch -d feature/add-order-domain
```

After the PR is merged, **verify the linked issues actually closed**. If any
issue you intended to fix is still open, the PR body was missing a closing
keyword — close it manually and add the keyword next time:

```bash
gh issue list --state open    # fixed issues should NOT appear here
gh issue close <number> --comment "Fixed by #<pr-number>"   # manual fallback
```

## Post-merge cleanup and release

After the PR is merged, perform **all** of the following steps automatically.

### Step 7a — Clean up local branch

The remote branch is already deleted (via `--delete-branch`).
Clean up the local branch:

```bash
BRANCH=$(git branch --show-current)
git checkout main
git pull origin main
git branch -d "$BRANCH"
```

Do NOT ask for confirmation — the branch was already merged, so `-d`
(safe delete) will succeed.  If the user is already on `main`, detect
the merged branch from context or the PR URL and delete it.

### Step 7b — Tag the release (version bump already on the branch)

> **Only applies to the `kairos-ontology-toolkit` repo itself.**
> Skip this step for ontology hub repos (they don't publish packages).

> ⚠️ **`main` is a protected branch** — you CANNOT `git push` commits directly to
> it, and you must NOT create a separate "bump-only" PR after merge (it produces a
> tag that is not reachable from `main`). The version bump belongs **in the feature
> branch, before the PR** (see the pre-flight below), so the bump lands on `main`
> in the same merge. After merge you only **tag the merged commit**.

**Pre-flight (do this on the feature branch, before Step 5 "Create the PR"):**
If this change should ship a release, ask the user which bump to apply, then commit
the bump as part of the feature branch so it is included in the PR:

| Type | When |
|------|------|
| `patch` | Bug fixes, small skill/doc changes |
| `minor` | New features, new projections, new CLI commands |
| `major` | Breaking API changes |

```bash
# On the feature branch, BEFORE creating the PR:
# 1. Bump __version__ in src/kairos_ontology/__init__.py to X.Y.Z
# 2. Move CHANGELOG [Unreleased] items under a new [X.Y.Z] — YYYY-MM-DD heading
# 3. Refresh the lock + sanity-build
uv lock && uv build
git add uv.lock src/kairos_ontology/__init__.py CHANGELOG.md
git commit -m "chore: bump version to X.Y.Z"
```

**After the PR is merged** (Step 5b) and local `main` is synced (Step 7a),
tag the merged commit on `main` and push only the tag:

```bash
git checkout main && git pull origin main      # main now contains the bump
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z                          # tag only — never push to main
```

This keeps the tag reachable from `main` and needs no extra branch.

The tag push triggers the **release.yml** workflow which:
- Builds the package (wheel + sdist)
- Creates a **GitHub Release** with the built artifacts attached

> No PyPI publishing — the toolkit is distributed via git-tag / wheel-URL pins
> (see DD-066).

> **If you forgot to bump on the branch** and already merged: do NOT push to `main`.
> Open a small `chore/bump-X.Y.Z` PR with the bump, merge it, then tag the merged
> commit on `main`. (This is the fallback, not the default path.)

Wait for the release workflow to complete and confirm success:

```bash
gh run list --workflow release.yml --limit 1
```

Print a summary:

```
✅ Release complete!
   Version: v1.3.0
   Release: https://github.com/Cnext-eu/kairos-ontology-toolkit/releases/tag/v1.3.0
```

## Error handling

| Situation | Action |
|-----------|--------|
| `gh` not installed | Tell user: `winget install GitHub.cli` (Windows) or `brew install gh` (macOS) |
| `gh` not authenticated | `gh auth login` |
| PR already exists for branch | Show URL: `gh pr view --web` |
| Push rejected (behind remote) | `git pull --rebase origin <branch>` then retry |
| Merge conflicts with main | Help resolve: `git fetch origin main && git rebase origin/main` |
| Push to `main` rejected (protected branch hook) | Expected — never push to `main`. Land changes via a PR; for a release, only `git push origin vX.Y.Z` (tag) after merge. |

## Ontology-specific checklist

When the PR includes `.ttl` file changes, remind the user:

1. Did you run `python -m kairos_ontology validate`?
2. Did you run `python -m kairos_ontology project` to regenerate artifacts?
3. If a new domain was added:
   - Is it in `ontology-hub/model/ontologies/_master.ttl`?
   - Is it in the domain table in `ontology-hub/README.md`?
4. Are projection outputs committed (if not gitignored)?
5. If new core functionality was added (projections, annotations, CLI commands):
   - Is the `kairos-help` skill updated in `.github/skills/kairos-help/SKILL.md`?
   - Is the scaffold copy updated in `src/kairos_ontology/scaffold/skills/kairos-help/`?
