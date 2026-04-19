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
   `kairos-ontology validate`

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

### Step 4 — Push the branch

```bash
git push -u origin HEAD
```

### Step 5 — Create the pull request

Use the GitHub CLI (`gh`):

```bash
gh pr create --base main --fill
```

Or with explicit title and body:

```bash
gh pr create --base main \
  --title "<type>: <short description>" \
  --body "## Changes

- <bullet summary of what changed>

## Checklist
- [ ] `kairos-ontology validate` passes
- [ ] `kairos-ontology project` regenerated (if ontology changed)
- [ ] `_master.ttl` updated (if new domain added)
- [ ] Hub README domain table updated (if new domain added)"
```

### Step 6 — Confirm

Print a summary:

```
✅ Pull request created!
   Branch: feature/add-order-domain → main
   PR URL: https://github.com/<org>/<repo>/pull/<number>

Next steps:
  - Review the PR on GitHub
  - After approval and merge, clean up locally:
      git checkout main
      git pull origin main
      git branch -d feature/add-order-domain
```

## Post-merge cleanup (when user comes back after merge)

```bash
git checkout main
git pull origin main
git branch -d <merged-branch>
```

## Error handling

| Situation | Action |
|-----------|--------|
| `gh` not installed | Tell user: `winget install GitHub.cli` (Windows) or `brew install gh` (macOS) |
| `gh` not authenticated | `gh auth login` |
| PR already exists for branch | Show URL: `gh pr view --web` |
| Push rejected (behind remote) | `git pull --rebase origin <branch>` then retry |
| Merge conflicts with main | Help resolve: `git fetch origin main && git rebase origin/main` |

## Ontology-specific checklist

When the PR includes `.ttl` file changes, remind the user:

1. Did you run `kairos-ontology validate`?
2. Did you run `kairos-ontology project` to regenerate artifacts?
3. If a new domain was added:
   - Is it in `ontology-hub/ontologies/_master.ttl`?
   - Is it in the domain table in `ontology-hub/README.md`?
4. Are projection outputs committed (if not gitignored)?
