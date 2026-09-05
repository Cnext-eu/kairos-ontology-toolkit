# DD-210: Version bump moves from mandatory-per-PR to release-time-only

**Status:** Accepted
**Date:** 2026-08-30
**Affects:** `.github/workflows/version-check.yml`, `.github/PULL_REQUEST_TEMPLATE.md`,
`CONTRIBUTING.md`, `.claude/skills/SC-merge-pr/SKILL.md` (synced to
`src/kairos_ontology/scaffold/skills/SC-merge-pr/SKILL.md`), `docs/dev/RELEASING.md`

### Context

Since the CLI scaffolding PR (#2), `version-check.yml` failed any PR that touched `src/` without also
bumping `__version__`, with a `skip-version` label as the only escape hatch. In practice this meant
every ordinary `feat:`/`fix:` PR had to bump the `rc` suffix (e.g. `5.15.0rc7` → `5.15.0rc8`) purely to
satisfy CI, producing frequent, low-value version-check failures on PRs that were not releases. This
contradicted `docs/dev/RELEASING.md` §5's own documented steady state — "Land `feat:` PRs on `main` over the
cycle. When ready, bump minor..." — which already describes bumping only when cutting a release, not on
every merge. The actual release mechanism (`release.yml`, triggered by pushing a `vX.Y.Z` tag and
independently validating the tag against `__version__`) never depended on per-PR bumps in the first
place, so the mandatory gate added CI noise without a corresponding safety benefit.

### Decision

Drop the "must bump if `src/` changed" enforcement from `version-check.yml` (and, with it, the
`skip-version` label's purpose for that case). The job now only fires when a PR *does* change
`__version__` to a stable, non pre-release value, in which case it still requires a matching
`## [X.Y.Z]` `CHANGELOG.md` entry. Version bumps happen exclusively as part of cutting an actual
release, per the flow `docs/dev/RELEASING.md` already documents (§5, §6, and the hotfix cases). Updated
`CONTRIBUTING.md`, `.github/PULL_REQUEST_TEMPLATE.md`, and the `SC-merge-pr` skill to describe the
release-time-only bump instead of a mandatory per-PR one; removed the now-purposeless `skip-version`
references from `docs/dev/RELEASING.md`'s back-merge notes.

### Consequences

Ordinary PRs no longer fail CI for not bumping `__version__`. A contributor cutting a release (or
hotfix) still must bump `__version__` and, for stable versions, add the matching CHANGELOG entry —
enforced exactly as before, just conditionally rather than unconditionally. `release.yml`'s
tag-vs-`__version__` check is unaffected, since it never relied on this gate.
