---
name: SC-feature-branch
description: >
  Create a feature branch from main for a new piece of work.
  Ensures clean working tree, up-to-date main, and consistent branch naming.
---

# SC — Create Feature Branch

You are helping the user start a new piece of work on a feature branch.

## Before you start

1. Confirm the user has described **what** the feature/fix is about.
2. Derive a branch name from the description using the naming convention below.

## Branch naming convention

```
<type>/<short-description>
```

| Type | When to use |
|------|-------------|
| `feature/` | New functionality or domain additions |
| `fix/` | Bug fixes |
| `chore/` | Maintenance, dependency updates, CI changes |
| `docs/` | Documentation-only changes |
| `ontology/` | Ontology modeling changes (add/modify domains) |

Rules:
- Lowercase, hyphens between words.
- Max 50 characters for the description part.
- Examples: `feature/add-order-domain`, `fix/customer-namespace`, `ontology/logistics-domain`, `chore/update-toolkit-v1.3`.

## Workflow

### Step 1 — Ensure clean state

```bash
git status
```

If there are uncommitted changes, ask the user whether to:
- **Stash** them (`git stash push -m "WIP before <branch>"`)
- **Commit** them first
- **Discard** them (only if user explicitly confirms)

### Step 2 — Update main

```bash
git checkout main
git pull origin main
```

### Step 3 — Create and switch to feature branch

```bash
git checkout -b <type>/<short-description>
```

### Step 4 — Confirm

Print a summary:

```
✅ Feature branch created: feature/add-order-domain
   Based on: main (up to date)

Next steps:
  1. Make your changes
  2. Commit with descriptive messages
  3. When ready, use the SC-merge-pr skill to create a pull request
```

## Error handling

| Situation | Action |
|-----------|--------|
| Branch name already exists | Suggest a suffix: `feature/add-order-domain-v2` |
| Not a git repo | Tell user to run `git init` or check they're in the right directory |
| Remote is ahead | `git pull --rebase origin main` before branching |
| Detached HEAD | `git checkout main` first |
