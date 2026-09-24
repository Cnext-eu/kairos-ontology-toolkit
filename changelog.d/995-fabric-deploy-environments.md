### Changed (BREAKING for existing dataplatform Azure logins)
- **The Power BI deploy job runs in a GitHub Environment (DD-239).** Its `target_environment`
  input names the GitHub Environment, so each target has its own `FABRIC_WORKSPACE_ID`,
  `FABRIC_ITEM_ID`, Azure IDs and required reviewers. Before this, DEV, UAT and PROD shared one
  workspace secret and had no approvals. **Upgrade step:** the Azure federated credential
  subject changes to `repo:<org>/<repo>:environment:<ENV>`. Add one per Environment before the
  first deploy, or `azure/login` fails. Repository-level secrets still resolve inside an
  Environment. Receive the workflow with `kairos-ontology update --refresh-workflows`.

### Added
- **A deploy is green only when the model can read its data.** After publishing, every Direct
  Lake model is refreshed (framed), and the deploy fails when one cannot read its tables: a
  wrong item ID, a missing `gold_*` table, or a missing Warehouse permission. Before this, all
  three surfaced only when a report user opened the report. DirectQuery models are skipped.
  The new `refresh_after_publish` input turns the check off, for diagnosing credentials only.
- `CICD.md` documents the Fabric deploy prerequisites: Environments, federated credentials,
  the "Service principals can use Fabric APIs" tenant setting, the workspace role, capacity,
  Warehouse read access for viewers under SSO, and how the RLS placeholder roles behave.

### Changed
- **`item_id` replaces `lakehouse_id`** in `gold.direct_lake_connection` and in the
  dataplatform's `gold-connections.yml`. dbt writes Gold into a Fabric **Warehouse**, and that
  Warehouse is the item Direct Lake reads through OneLake. The old name sent authors looking for
  a lakehouse that does not hold the tables. `lakehouse_id` still works, with a deprecation
  warning. Setting both is rejected. Emitted artifacts are unchanged.
- fabric-cicd is pinned (1.3.0) instead of installed unpinned, and bumped only with a toolkit
  release. `azure/login` allows a service principal with no Azure subscription.

### Removed
- `.github/fabric/deployment-settings.json.example` is no longer scaffolded: nothing read it.
  Existing copies are harmless.
