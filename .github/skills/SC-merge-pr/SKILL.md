---
name: SC-merge-pr
description: >
  Create a pull request to merge the current feature branch into main.
  Covers commit hygiene, push, PR creation via gh CLI, and post-merge cleanup.
---

# SC — Merge via Pull Request

You are helping the user finish a feature branch and create a pull request
to merge into `main`. The mechanical git/gh choreography below is delegated to
`python scripts/finish_pr.py` (toolkit-repo-only tooling — it is not shipped
to hub repos). Everything that requires judgment — commit wording, conflict
resolution, the security review, which issues this PR fully resolves, PR
title/body prose, and whether/how to bump the version — stays your call; the
script only executes what you've already decided.

## Before you start

1. Confirm the user is on a feature branch (not `main`).
2. Check for uncommitted changes.
3. Ask if they want to run validation before creating the PR:
   `python -m kairos_ontology validate`
4. **Version bump (toolkit repo only):** the CI `version-check` job fails any
   PR that changes `src/` but doesn't bump `__version__`. Decide the bump
   **now** and commit it to the feature branch *before* creating the PR — see
   [Step 8](#step-8--tag-the-release-version-bump-already-on-the-branch).
   Because `main` is protected, bundling the bump into the feature PR avoids a
   separate bump-only PR and keeps the release tag reachable from `main`.
   For pre-release work, increment the `rc`/`b`/`a` suffix; for a real release,
   follow the SemVer bump rules.

## Workflow

### Step 1 — Verify branch and status

```bash
python scripts/finish_pr.py pre-pr --check
```

Reports the current branch and whether the working tree is clean. If on
`main`, stop and tell the user to switch to their feature branch. If
uncommitted changes exist, ask the user to commit or stash first.

### Step 2 — Ensure all changes are committed

If there are staged or unstaged changes, decide the commit message yourself
(the wording is your judgment call — the script does not commit for you):

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

If conflicts arise, help the user resolve them before continuing — this
requires reading the actual conflicting changes and is not scriptable.

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

If any issues are found, fix them before proceeding. Do NOT create the PR
with known security problems — this review requires reading the actual diff
and is not scriptable.

### Step 5 — Push the branch

```bash
python scripts/finish_pr.py pre-pr --push
```

### Step 6 — Link issues with closing keywords (MANDATORY)

Before creating the PR, identify which open issues this PR **fully
resolves** — this is your judgment call, not the script's. For each one, the
PR **body** must contain a GitHub **closing keyword** so the issue auto-closes
when the PR merges:

```
Closes #175
Fixes #174
Resolves #166
```

> ⚠️ **Why this matters:** an issue reference like `#175` on its own — or a
> reference in the PR **title** — does **NOT** auto-close the issue on merge.
> Without a closing keyword the issue stays open after the fix ships (this is
> exactly what left #174/#175 open after PR #177 merged). Only the keywords
> above, in the PR **body** or a commit message, trigger auto-close.

| Use | Keyword (any case) | When |
|-----|--------------------|------|
| **Auto-close** | `close` / `closes` / `closed`, `fix` / `fixes` / `fixed`, `resolve` / `resolves` / `resolved` followed by `#NNN` | The PR **fully fixes** the issue |
| **Reference only** (no close) | plain `#NNN` (no keyword) | The PR is *related to* / *partially addresses* the issue, or the issue is a follow-up that should stay open |

- One keyword **per issue** (`Closes #1, #2` does NOT close #2 — pass
  `--closes 1 --closes 2`).
- For a follow-up/spin-off issue that must stay open, pass it as `--follow-up`
  so it is linked but **not** closed.

### Step 7 — Create the pull request

The script renders the `## Changes` / `## Closes` / `## Checklist` body
structure; you supply the title, bullet summary, and issue numbers decided in
Step 6:

```bash
python scripts/finish_pr.py pre-pr --create \
  --title "<type>: <short description>" \
  --body-bullet "<bullet summary of what changed>" \
  --closes 175 --closes 174 \
  --follow-up 176
```

### Step 7b — Merge the pull request

After the PR has been reviewed and approved:

```bash
python scripts/finish_pr.py post-merge --merge
```

This merges with `--squash --delete-branch`, so the remote branch is cleaned
up automatically.

### Step 7c — Confirm

Print a summary:

```
✅ Pull request created!
   Branch: feature/add-order-domain → main
   PR URL: https://github.com/<org>/<repo>/pull/<number>
   🗑️  Remote branch will be deleted automatically after merge.

Next steps:
  - Review the PR on GitHub
  - After merge, run: python scripts/finish_pr.py post-merge --cleanup
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

### Step 8a — Clean up local branch

The remote branch is already deleted (via `--delete-branch`). Clean up the
local branch:

```bash
python scripts/finish_pr.py post-merge --cleanup
```

Do NOT ask for confirmation — the branch was already merged, so the safe
delete will succeed.

### Step 8 — Tag the release (version bump already on the branch)

> **Only applies to the `kairos-ontology-toolkit` repo itself.**
> Skip this step for ontology hub repos (they don't publish packages).

> ⚠️ **`main` is a protected branch** — you CANNOT `git push` commits directly to
> it, and you must NOT create a separate "bump-only" PR after merge (it produces a
> tag that is not reachable from `main`). The version bump belongs **in the feature
> branch, before the PR** (see the pre-flight below), so the bump lands on `main`
> in the same merge. After merge you only **tag the merged commit**.

**Pre-flight (do this on the feature branch, before Step 7 "Create the PR"):**
If this change should ship a release, ask the user which bump to apply — this
decision is yours, not the script's:

| Type | When |
|------|------|
| `patch` | Bug fixes, small skill/doc changes |
| `minor` | New features, new projections, new CLI commands |
| `major` | Breaking API changes |

```bash
# On the feature branch, BEFORE creating the PR:
python scripts/finish_pr.py tag-release --bump <patch|minor|major>
uv lock && uv build
git add uv.lock src/kairos_ontology/__init__.py CHANGELOG.md
git commit -m "chore: bump version to X.Y.Z"
```

**After the PR is merged** (Step 7b) and local `main` is synced (Step 8a),
tag the merged commit on `main`:

```bash
git checkout main && git pull origin main      # main now contains the bump
python scripts/finish_pr.py tag-release --tag  # tags v<current __version__>, pushes only the tag
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
| Push to `main` rejected (protected branch hook) | Expected — never push to `main`. Land changes via a PR; for a release, only the tag push (Step 8) after merge. |
| Unsure what a `finish_pr.py` step will do | Add `--dry-run` — every subcommand prints what it would run instead of calling git/gh. |

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
