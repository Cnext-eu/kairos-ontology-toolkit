### Fixed
- **Promoting a Power BI release to another environment now actually repoints it.** The
  release archive left out `parameter.yml`, the file fabric-cicd uses to rewrite the model's
  OneLake URL (or Databricks warehouse) per environment. `apply-gold-connection` then reported
  "nothing to parameterise" and exited 0, and **every environment silently deployed the
  hub's default workspace and item**. The hub-wide `parameter.yml` now ships at the archive
  root, which is where fabric-cicd reads it. Products that render different
  parameterisations fail the packaging instead of shipping one of them. (#993)
- **`${VAR}` values in `.github/fabric/gold-connections.yml` resolve.** The deploy step passed
  only the target environment name, so the documented `${FABRIC_PROD_WORKSPACE_ID}` form
  always failed with "unset or empty". The step now passes `FABRIC_WORKSPACE_ID` and
  `FABRIC_ITEM_ID` (a repository variable, or secret, of that name). Only the *target*
  environment is resolved, so a DEV deploy no longer fails on PROD's unset variables.

### Changed (BREAKING for deploys that relied on the silent fallback)
- **`apply-gold-connection` fails closed** when the archive carries no `parameter.yml`, or
  when the target environment is declared neither by the hub nor by `gold-connections.yml`.
  Environment keys are case-sensitive. A `DEV`/`dev` mismatch used to deploy the default
  workspace without a word. A release packaged by an older toolkit has no `parameter.yml`:
  re-release the hub. Existing dataplatforms receive the fixed workflow and example with
  `kairos-ontology update --refresh-workflows`; update `gold-connections.yml` to the
  `${FABRIC_WORKSPACE_ID}` / `${FABRIC_ITEM_ID}` form.
