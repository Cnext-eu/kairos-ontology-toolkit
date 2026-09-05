# DD-067: Single-Line Release Management with Ephemeral Hotfix Branches

**Status:** Accepted
**Date:** 2026-06-14
**Affects:** `docs/dev/RELEASING.md` (new), `CONTRIBUTING.md`, `kairos-toolkit-ops` skill
(+ scaffold copy)
**Implementation:** Documentation + process only — no tooling or CI changes

### Context

The toolkit ships frequently, and the team (~5 people) needs to patch the
**currently released** version without dragging in unreleased feature work that has
already landed on `main`. Until now the process was purely trunk-based (PR → `main`
→ tag on `main`) with no documented answer for "a bugfix is needed but `main`
already contains the next minor's features." Tagging `main` in that state would
publish those features inside what should be a patch release.

The team confirmed it supports **only the latest release line** — once a new minor
ships, older lines are dropped. Heavier models (per-minor `release/X.Y` maintenance
branches, GitFlow, release automation bots) would be over-engineering at this scale.

### Decision

Adopt **trunk-based development + ephemeral hotfix branches**, documented in a new
`docs/dev/RELEASING.md` (the single source of truth):

- **SemVer discipline:** `fix:` → patch, `feat:` → minor, breaking → major. A bugfix
  always ships as its own patch tag and is **never** bundled into a feature/minor
  release.
- **Bugfix decision tree:**
  - If `main` has **no** unreleased features (`git log vX.Y.Z..main` is empty/chore)
    → fix on `main` via a `fix/*` PR, bump patch, tag `main`.
  - If `main` **already carries** unreleased features → cut `hotfix/x.y.z` from the
    release **tag** `vX.Y.Z`, fix + patch-bump, tag from that branch (it becomes the
    new *Latest* GitHub Release), then **back-merge to `main`** (keep `main`'s
    in-progress version on conflict; apply the `skip-version` label since the
    back-merge touches `src/` without a `main` bump).
- **Feature releases & pre-releases** stay exactly as before (minor bump + tag on
  `main`; RC tags via the `preview` channel — DD-013).
- **No long-lived maintenance branches.** A `hotfix/*` branch is created only when
  needed and deleted after back-merge.
- **Branch naming:** `feature/*`, `fix/*`, `hotfix/x.y.z`, `chore/*`, `docs/*`.

### Rationale

- Cutting the hotfix from the **tag** (not `main`) is what guarantees a clean patch
  with zero unreleased features — the central requirement.
- Supporting only the latest line means a maintenance branch would sit idle and add
  merge overhead; an ephemeral branch is the minimum that solves the problem.
- Reuses existing machinery (tag-triggered `release.yml`, GitHub-Release
  distribution, `version-check` + `skip-version` label) — no new CI or tooling.

### Consequences

- Contributors have a documented, copy-paste flow for patch vs feature releases;
  `CONTRIBUTING.md` and the `kairos-toolkit-ops` skill link to `docs/dev/RELEASING.md`.
- The back-merge step is mandatory after a Case-B hotfix, or the fix would be lost in
  the next minor; the `skip-version` label is the expected escape hatch there.
- **Future, only if the team/scope grows:** per-minor `release/X.Y` maintenance
  branches, release automation (release-please/semantic-release), artifact signing.
  Explicitly out of scope today.
