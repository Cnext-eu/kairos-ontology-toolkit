# DD-199: Per-PR CI only gates on the PR's own diff; global-state checks move to a schedule

**Status:** Accepted
**Date:** 2026-08-20
**Affects:** `.github/workflows/ci.yml`, `.github/workflows/dependency-audit.yml`, new `.github/workflows/refmodels-pin.yml`

### Context

Four sibling PRs (#567–#570), all forked from the same `main` commit, sat
open at the same time. While they were open, `kairos-ontology-referencemodels`
published v1.35.2. The `refmodels-pin` job in `ci.yml` ran on every PR and
checks the release feed against the pin at run time, not the PR's own
diff — so all four PRs failed the identical check simultaneously, for a
reason none of their authors could have prevented by changing their PR, and
each needed a follow-up commit before it could merge. A per-PR gate that
fails on external state a contributor cannot control by editing their PR is
a false signal: it looks like "your PR broke something" when nothing in the
PR caused it.

`Analyze (actions)`/`Analyze (python)` (CodeQL, via the repo's code-scanning
default setup) is the slowest job on every PR and, like `refmodels-pin`,
tests the whole codebase rather than the diff — appropriate for a periodic
sweep, not for gating merge on every change.

### Decision

Per-PR CI (`ci.yml`'s `test` job, `check-version`) stays as the only
required gate — both are fast and both are actually about the PR's own
diff. Everything that tests state independent of the diff moves off the
per-PR path:

- `refmodels-pin` is removed from `ci.yml` entirely and reimplemented as a
  new scheduled workflow (`refmodels-pin.yml`, daily): on drift, it updates
  the pin, re-locks, runs the full suite against the new bundle, and opens
  a `chore/refmodels-pin-<version>` PR automatically — the busywork of
  bumping the pin no longer falls on whichever PR happens to be open when
  upstream ships a release.
- `pip-audit` (`dependency-audit.yml`) stays on every PR for visibility
  (a newly disclosed CVE is worth seeing) but is non-blocking there
  (`continue-on-error` when `github.event_name == 'pull_request'`); it
  stays blocking on push-to-main and its existing weekly schedule, so a
  real vulnerability is still enforced before it reaches a release.
- CodeQL's per-PR analysis is a repo-level code-scanning **default setup**
  setting (Settings → Code security → Code scanning), not a workflow file
  in this repo, and changing it requires repo-admin access this change did
  not have — left as a follow-up for whoever holds that access: switch the
  default setup's trigger from every-PR to its existing weekly schedule (or
  to an advanced-setup workflow scoped to `schedule` + release tags).

### Consequences

A PR's CI status now reflects only things that PR actually did. Reference-
models pin drift is caught and fixed automatically, same-day, without
touching whatever unrelated PRs happen to be open — it will never again
require four simultaneous rebase-and-bump commits for one upstream release.
A real dependency CVE is visible on every PR (not silently hidden) but
no longer blocks an unrelated PR's merge; it still blocks `main` and the
weekly audit. CodeQL's per-PR gating is unchanged until someone with repo
admin access applies the follow-up above.
