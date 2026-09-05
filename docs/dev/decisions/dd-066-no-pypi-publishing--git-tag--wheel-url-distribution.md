# DD-066: No PyPI Publishing — Git-Tag + Wheel-URL Distribution

**Status:** Accepted
**Date:** 2026-06-14
**Affects:** `.github/workflows/release.yml`, `README.md`, `kairos-toolkit-ops` +
`SC-merge-pr` skills (and scaffold copies)
**Implementation:** `release.yml` `build` + `github-release` jobs (no `publish-pypi`
job, no `id-token` permission)

### Context

The `release.yml` workflow carried a `publish-pypi` job (and an `id-token: write`
permission for OIDC trusted publishing), but it was **commented out** and its own
note read *"trusted publisher not configured for this project."* The project has
never been published to PyPI. In practice the toolkit is distributed and consumed
entirely through **GitHub Releases**: `release.yml` attaches the built wheel + sdist
to the release, and hub repos pin the toolkit to a git tag / `.whl` asset URL that
`kairos-ontology update --upgrade` resolves via the GitHub Releases API (DD-013).

The dormant PyPI scaffolding was dead weight and actively misleading: skills claimed
a stable release "Publishes to PyPI", and the README advertised
`pip install kairos-ontology-toolkit` plus a non-functional PyPI version badge.

### Decision

Drop PyPI publishing from the toolkit entirely:

- Remove the commented-out `publish-pypi` job and the now-unused `id-token: write`
  permission from `release.yml` (keep `contents: write` for the GitHub Release).
- The `build` + `github-release` jobs are unchanged — every tagged release still
  produces a GitHub Release with the wheel + sdist attached, for **both** stable and
  pre-release tags.
- Correct all docs/skills: install + upgrade instructions reference the git-tag /
  wheel-URL flow, not `pip install` from PyPI.

### Rationale

- `pip install git+https://…@vX.Y.Z` (and the wheel-URL pin used by hubs) already
  covers every install/upgrade path — PyPI adds nothing for this internal/community
  toolkit.
- Removing the inert job eliminates a confusing "is this published?" question and an
  unnecessary high-privilege (`id-token`) permission on the release workflow.
- Keeping artifacts on the GitHub Release preserves the existing, working
  `update --upgrade` resolution (DD-013) with zero behavioural change.

### Consequences

- The toolkit is **not** installable from PyPI; the README and skills now reflect
  this. No PyPI version badge.
- Re-enabling PyPI later means registering the project and adding a publish job back
  (configure OIDC trusted publishing, gate on non-pre-release tags) — a deliberate
  future decision, not a default.
- Supersedes the PyPI-publish aspects of **DD-013** (its "skips PyPI publish" wording
  is now historical; no release publishes to PyPI).
