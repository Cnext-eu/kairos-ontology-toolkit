# DD-256: A promotion is one workflow run that carries one commit and its hub release through every environment

**Status:** Accepted
**Date:** 2026-10-17
**Affects:** the dataplatform scaffold (new managed `promote.yml`,
`deploy-powerbi-semantic-model.yml` generation 9, `pr-validate.yml`, `profiles.yml`, `CICD.md`),
`core/hub_release_lock.py`, `bump-hub`, `hub-release`, `check-environments`, the
`kairos-package-dataplatform`, `kairos-setup-dataplatform` and `kairos-help` skills
**Issue:** #1114 (implements DD-206 §12 item 6; builds on DD-239 and DD-255)

### Context

DD-206 settles the promotion strategy: dbt targets, never branches, select environments, and
GitHub Environments promote the exact dataplatform SHA through DEV, UAT and PROD. Its §12 item 6,
"exact-SHA DEV/UAT/PROD workflows", was never built. The scaffold shipped only the Power BI deploy
workflow, so a promotion meant the following:

- building dbt by some means the scaffold did not provide;
- dispatching the deploy with a hand-typed environment, the run ID of that build, a hub release
  tag, the hub SHA and the archive's SHA-256;
- repeating it for each environment, with nothing tying the runs to one commit.

`CICD.md` described a "commit D8 → DEV → approval → UAT → approval → PROD" flow and a rollback "from
deployment history" that no workflow implemented. DD-255 made the dbt target the environment
authority, which is what such a workflow needs.

### Decision

**A managed `promote.yml` carries one dataplatform commit through `dev`, `uat` and `prod`, and the
hub release it deploys is pinned in a reviewed file beside the dbt package pin.**

1. **One run, one commit.** A push to `main` starts `promote.yml`. Its first job resolves the
   commit to a full SHA. Every environment then checks out that SHA, so a merge landing while
   `uat` waits for approval cannot change what `uat` or `prod` receive.
2. **One job per environment, so one approval per environment.** Each environment calls
   `deploy-powerbi-semantic-model.yml` as a reusable workflow with `build_dbt: true`. The job runs
   in that environment's GitHub Environment and does the following, in order:
   - `dbt build --target <env>` with the committed `profiles.yml`;
   - resolving the environment (DD-255);
   - deploying the Power BI archive;
   - framing it (DD-239).

   A separate dbt job would ask for a second approval of the same environment. Required reviewers
   on `uat` and `prod` are the promotion gate: approving is promoting.
3. **The hub release is a file, not workflow inputs.** `hub-release.lock` (tag, hub SHA, archive
   SHA-256) sits at the dataplatform root. `bump-hub <tag>` writes it together with the
   `packages.yml` pin. It reads the archive checksum the hub release publishes, and the pull
   request that commits both is where the release is reviewed. The deploy verifies the tag and
   checksum against the lock exactly as it verified the inputs. `pr-validate` (`hub-release`)
   fails when the lock names another hub commit than `packages.yml`: a dbt package and a semantic
   model from different hub commits would disagree on the Gold tables. Without a lock, a
   promotion builds dbt only.
4. **Rollback and hotfix are the same workflow at another commit.** Dispatching `promote.yml` with
   `ref` set to an older (or hotfix) commit promotes it through the same approvals, and its
   `packages.yml` and lock travel with it.
5. **The path is the dbt targets `dev`, `uat`, `prod`.** The repository variable
   `KAIROS_PROMOTION_PATH` shortens it (for example `dev,prod`). A skipped environment does not
   stop the next one, but a failed one does. Another target is deployed by dispatching the deploy
   workflow, which stays available as the break-glass path. Dispatch takes `build_dbt` or a dbt
   run ID, and the lock or all three release inputs.
6. **`check-environments` says what is missing.** For every target it reports:
   - whether the target resolves (offline, or `--online` through Fabric);
   - whether its `vars.kairos` entry names a real target;
   - whether the target is on the promote path;
   - whether the lock is consistent with `packages.yml`;
   - with `--github-repo`, whether a GitHub Environment of the same name exists.

   It prints the fix for each problem, the Entra federated-credential subject included.
7. **dbt authenticates the way the Environment allows.** The scaffolded profile reads
   `DBT_FABRIC_AUTHENTICATION` (default `environment`). The deploy sets it to `cli`, the
   federated `azure/login` session, when the Environment holds no `AZURE_CLIENT_SECRET`.

### Consequences

- Promoting is merging and approving. No SHA, checksum or run ID is typed, and the
  `dbt_build_run_id` convention survives only for a dispatch without `build_dbt`.
- The deploy workflow is now named "Deploy an environment (dbt build + Power BI)" and keeps its
  file name. Generation 8 is recorded as superseded, so dataplatforms refresh it.
  `pr-validate.yml` generation 6 is recorded too. `promote.yml` is new, and `update` installs it.
- An existing dataplatform without a committed `profiles.yml` can still use dispatch, but not
  `promote.yml`, whose dbt build needs the targets. `check-environments` names the gap.
- `pr-validate` does not run the full `check-environments`. A fresh scaffold's placeholders in
  `uat` and `prod` would fail its first pull request, so the full check is a manual step in the
  setup runbook.
- The reusable workflow is resolved at the run's ref, not at the promoted commit. A rollback
  therefore runs today's deploy logic against yesterday's content, which is the intended
  direction.
- The workflows reach the hub through a GitHub App token (`KAIROS_HUB_APP_CLIENT_ID` +
  `KAIROS_HUB_APP_PRIVATE_KEY`) when one is set up, else `HUB_REPO_TOKEN`. They read the Azure
  IDs from variables before secrets, so a federated user-assigned managed identity needs no
  secret. A client dataplatform had frozen its deploy workflow to get both.
- Concurrency is per environment and never cancels a running deploy. A newer push queues behind
  an older one at the same environment.
- Rejected: a dbt job and a deploy job per environment. Each would need its own approval.
- Rejected: reading the hub release from the latest hub release at deploy time. It would promote
  something nobody reviewed, and a rollback could not return to the old release.
- Rejected: running `check-environments` in `pr-validate`. See above.
- Verified offline (workflow structure, lock, commands) and in tests. A live run of `promote.yml`
  through `dev` and `uat` on a Fabric tenant is still owed, including the `cli` dbt
  authentication and the federated-credential subject casing of an Environment named `DEV` but
  addressed as `dev`.
