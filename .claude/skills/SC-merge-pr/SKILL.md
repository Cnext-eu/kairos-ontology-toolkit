---
name: SC-merge-pr
description: >
  PR rules the CLI must follow when merging a feature branch into main:
  version bump, security checklist, closing keywords, tag reachability.
  Git choreography is delegated to finish_pr.py — this skill captures what
  is NOT obvious and easy to forget.
---

# SC — Merge via Pull Request: non-obvious rules

Standard git/gh operations (branch, commit, push, `gh pr create`, `gh pr
merge`) are not repeated here. This skill documents the **toolkit-specific
rules that are easy to forget and cause CI failures or broken releases.**

This skill stays in the toolkit repository and is no longer copied into scaffolded repos
(DD-219). Everything below is specific to **this repository's own** release process
(`src/kairos_ontology/__init__.py`, `scripts/finish_pr.py`), neither of which exists in a
hub or dataplatform — those follow the SHA-pinned release model in their generated
`CICD.md`.

## 1. Version bump happens at release time, not per PR

Most PRs land on `main` without touching `__version__` — see
`docs/RELEASING.md` for the full versioning flow. Only bump the version when
this PR **is** the release: promoting `main` to a new tagged release.

| Bump type | When |
|-----------|------|
| `patch` | Cutting a bugfix release |
| `minor` | Cutting a feature release |
| `major` | Cutting a breaking-change release |

Commit the bump on the release branch **before** creating the PR. Because
`main` is protected, bundling the bump avoids a separate bump-only PR.

The CI `version-check` job only fires when `__version__` changes: pre-release
versions (with `rc`, `b`, `a` suffix) don't need a CHANGELOG entry; stable
releases must have a `## [X.Y.Z]` section in `CHANGELOG.md`.

```bash
python scripts/finish_pr.py tag-release --bump <patch|minor|major>
uv lock && uv build
git add uv.lock src/kairos_ontology/__init__.py CHANGELOG.md
git commit -m "chore: bump version to X.Y.Z"
```

## 2. Closing keywords (or issues stay open)

GitHub only auto-closes issues when the PR **body** or a commit message
contains `Closes #N`, `Fixes #N`, or `Resolves #N`. A plain `#N` reference
does **not** auto-close. One keyword per issue — `Closes #1, #2` does **not**
close #2.

After merge, verify linked issues actually closed:

```bash
gh issue list --state open    # fixed issues should NOT appear here
```

### This repo's auto-close workflow (parenthetical references)

On top of GitHub's native keywords, `.github/workflows/auto-close-issues.yml`
closes any issue referenced **in parentheses** in a merged PR's title or body —
e.g. the squash-title convention `fix: … (#286, #338) (#402)` closes #286 and
#338 on merge.

- **Partial fix?** Add a qualifier right after the number — `(#562 P2)`,
  `(#562 P3+P4)`, or `(#562 Problem 2)` — and the workflow leaves the issue
  open. Never bare-parenthetical a multi-part issue the PR doesn't fully fix
  (PR #577 closed #562 that way before the qualifier rule existed).
- **Mention without closing?** Use a bare `#N` (no parentheses) or prefix with
  `Refs`/`Related`/`Deferred to`.

## 3. Security review before pushing

Scan changed files for:

**Python / service code:**
- SPDX headers on every new/modified `.py` file (`# SPDX-License-Identifier: Apache-2.0` / `# Copyright 2026 Cnext.eu`)
- Path traversal (unsanitised `/`, `\`, `..` in file paths)
- Command injection (`shell=True` or string concatenation in `subprocess`)
- Secret exposure (tokens, keys, passwords in code or config defaults)
- Dependency pinning and Apache-2.0-compatible licenses (BSD, MIT, ISC OK; GPL is NOT)

**Ontology / scaffold changes:**
- Template injection (user-controlled values in templates without sanitising)
- Namespace hijacking (URIs pointing to domains the org doesn't control)
- PII or credentials embedded in `.ttl` labels/comments
- No proprietary content in examples or sample data

## 4. Tag reachability (protected main)

`main` is protected — never push directly to it. The version bump must be on
the feature branch **before** the PR so it lands on `main` in the same merge.
After merge, only **tag** the merged commit:

```bash
git checkout main && git pull origin main
python scripts/finish_pr.py tag-release --tag  # tags v<__version__>, pushes only the tag
```

If you forgot to bump on the branch and already merged: do NOT push to `main`.
Open a small `chore/bump-X.Y.Z` PR with the bump, merge it, then tag.

## 5. Ontology-specific checks (when .ttl files change)

1. Run `python -m kairos_ontology validate`
2. Run `python -m kairos_ontology project` to regenerate artifacts
3. New domain in `model/ontologies/_master.ttl` and README.md domain table?
4. Projection outputs committed (if not gitignored)?
5. `kairos-help` skill updated (both `.claude/skills/` and scaffold copy)?
