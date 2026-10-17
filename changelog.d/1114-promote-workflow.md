### Added
- **Managed `promote.yml`: one commit goes through dev → uat → prod (DD-256).** Merging to
  `main` starts it:
  - it pins the commit to its full SHA;
  - it builds and deploys `dev`;
  - `uat` and then `prod` each wait for their GitHub Environment's reviewers, and approving
    promotes the same commit.

  Each environment is one job: `dbt build --target <env>` with the committed `profiles.yml`,
  then the Power BI deploy. To roll back, run it by hand with `ref` set to an older commit. The
  repository variable `KAIROS_PROMOTION_PATH` shortens the path.
- **`hub-release.lock` pins the hub release a dataplatform deploys.** It holds the tag, the hub
  SHA and the archive SHA-256. `bump-hub <tag>` now writes it with the `packages.yml` pin when
  the tag is a release carrying the Power BI archive. `hub-release` prints it and fails when it
  names another hub commit than `packages.yml`, and `pr-validate` runs that check. Without a
  lock, a promotion builds dbt only.
- **`check-environments`** checks that every environment can be promoted to and names the fix
  for each problem. It covers:
  - dbt targets;
  - `vars.kairos`;
  - the promote path;
  - the lock;
  - with `--github-repo`, the GitHub Environments, including the federated-credential subject.

  `--online` also resolves the Fabric IDs.

### Changed
- **Managed workflow:** `deploy-powerbi-semantic-model.yml` ("Deploy an environment (dbt build +
  Power BI)") is now also a reusable workflow:
  - **New inputs:** `ref` and `build_dbt`.
  - **Release inputs:** the hub release comes from `hub-release.lock` unless all three release
    inputs are given.
  - **Connection:** the environment's Gold connection and workspaces are resolved from its dbt
    target when `profiles.yml` is committed (DD-255).
  - **Concurrency:** deploys run one at a time per environment.

  Dispatching it by hand still works, as the break-glass path.
- **Managed workflow:** `pr-validate.yml` checks `hub-release.lock` against `packages.yml`.
- The scaffolded `profiles.yml` reads `DBT_FABRIC_AUTHENTICATION` (default `environment`). The
  deploy sets it to `cli`, using the federated `azure/login` session, when the Environment has
  no `AZURE_CLIENT_SECRET`.

### Documentation
- The dataplatform `CICD.md` has new "Promotion" and "Rollback and PROD hotfix" sections and an
  "Add an environment" runbook. `kairos-package-dataplatform`, `kairos-setup-dataplatform` and
  `kairos-help` now guide through approving promotions and adding environments, instead of
  dispatching deploys by hand.
- `check-environments` was tested on a real client dataplatform. Three changes came out of it:
  - an endpoint the deploy's GitHub Environment supplies (`env_var('FABRIC_SERVER')`) is
    deferred offline instead of failing;
  - `--github-repo` reaches GitHub Enterprise (`HOST/OWNER/REPO`, or the host of `origin`);
  - it fails when the repository's deploy workflow has no `workflow_call`, which is the case
    for an older or customized copy that `promote.yml` cannot call.
