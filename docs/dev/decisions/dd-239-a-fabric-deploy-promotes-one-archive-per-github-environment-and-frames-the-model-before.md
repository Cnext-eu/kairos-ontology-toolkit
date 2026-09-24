# DD-239: A Fabric deploy promotes one archive per GitHub Environment and frames the model before it counts

**Status:** Accepted
**Date:** 2026-09-24
**Affects:** `core/projections/dbt/gold_connection.py` (`GoldDirectLakeEnvironmentSpec.item_id`,
the `lakehouse_id` alias), `core/projections/dbt/gold_render.py`, new
`core/projections/dbt/deploy_pins.py`, the dataplatform
`deploy-powerbi-semantic-model.yml` template, `gold-connections.yml.example`, the removed
`deployment-settings.json.example`, `cli/setup.py`, the dataplatform `CICD.md`, `USER_GUIDE.md`,
the `kairos-design-gold`, `kairos-setup-dataplatform`, `kairos-package-dataplatform` and
`kairos-toolkit-ops` skills
**Issue:** #995 (follows #993)

### Context

DD-206 §8 splits a Power BI release between the hub and the dataplatform. The hub builds and
checksums one archive. The dataplatform verifies it and deploys it to each environment with
fabric-cicd, and only rewrites environment parameterisation. Tracing a real Fabric Direct
Lake deploy through that split found it could not work end to end.

- **Parameterisation never shipped (#993).** Every environment silently received the hub's
  default workspace. Fixed separately: `parameter.yml` now ships at the archive root, and
  `apply-gold-connection` fails closed.
- **The target item was misnamed.** `fabric-warehouse` is the only adapter that emits Direct
  Lake, and dbt writes Gold into a Fabric *Warehouse*, schemas `gold_*`. The Direct Lake
  expression, `kairos.yaml` and every doc asked for a `lakehouse_id`. The model worked only if
  someone entered the Warehouse's item ID, which nothing said.
- **No per-environment isolation.** The deploy job had no GitHub Environment. DEV, UAT and
  PROD shared one `FABRIC_WORKSPACE_ID` secret and had no approvals, although `CICD.md`
  promised "that GitHub Environment's credentials".
- **Nothing proved the deployed model could read its data.** A wrong item ID, a missing table
  or a missing permission surfaced only when a report user opened the report.

### Decision

**Direct Lake reads the Warehouse through OneLake.** The emitted expression stays
`AzureStorage.DataLake("https://onelake.dfs.fabric.microsoft.com/<workspace>/<item>")`: Direct
Lake on OneLake, with no fallback to DirectQuery. `<item>` is the Warehouse dbt writes Gold
into, whose Delta tables OneLake serves at `Tables/<schema>/<table>`, matching the emitted
`schemaName`. The key is `item_id` in both `kairos.yaml` and `gold-connections.yml`.
`lakehouse_id` stays accepted as a deprecated alias (with a `FutureWarning`), and setting both
fails. Rendered bytes do not change, so no hub's TMDL moves. Direct Lake on the SQL endpoint
(`Sql.Database`) was not chosen: it needs endpoint configuration, changes every hub's TMDL, and
its one advantage, reading views through DirectQuery fallback, is something the model does not
use.

**SSO by default.** The model reads OneLake with the querying identity, so viewers need read
access on the Warehouse, and the deploying service principal (the model owner) needs it to
frame. No connection is bound. A fixed-identity cloud connection is possible later if the
first live deploy shows service-principal framing needs one.

**One GitHub Environment per target.** The deploy job runs in
`environment: ${{ inputs.target_environment }}`, so each Environment's `FABRIC_WORKSPACE_ID`,
`FABRIC_ITEM_ID`, Azure IDs and required reviewers apply. Repository-level secrets still
resolve inside an Environment, so secrets need no migration. The Azure federated credential
subject does change, to `repo:<org>/<repo>:environment:<ENV>`, which is the one upgrade step
existing dataplatforms must take.

**A refresh gates the deploy.** After publishing, every Direct Lake model in the archive is
refreshed (framed) through the Power BI refresh API. A model that cannot frame fails the deploy.
A DirectQuery model holds no data and is skipped. The `refresh_after_publish` input turns this
off, for diagnosing credentials only.

**Deploy tooling is pinned by the toolkit.** fabric-cicd is installed at `FABRIC_CICD_PIN`
(`deploy_pins.py`, 1.3.0) and bumped only with a toolkit release, in the same manual refresh as
DD-238's pins. `azure/login` sets `allow-no-subscriptions`, because a Fabric-only service
principal usually has no Azure subscription.

**No orphan cleanup.** `unpublish_all_orphan_items` is deliberately not called. The BI
engineer builds reports as separate items in the same workspace (DD-236), and a sweep over the
`Report` type would delete them.

**`deployment-settings.json.example` is removed.** Nothing read it, and it restated what the
workflow and `CICD.md` own.

### Consequences

- The same archive now reaches each environment's own Warehouse, under that environment's
  credentials and approvals, and a deploy is green only when the model can read its tables.
- Existing dataplatforms: `update --refresh-workflows`, then add a federated credential per
  Environment and move `FABRIC_WORKSPACE_ID` / `FABRIC_ITEM_ID` into Environments.
- Hubs should rename `lakehouse_id` to `item_id`. The alias keeps them working meanwhile.
- **Verified offline, not yet live.** fabric-cicd 1.3.0's parameter validator accepts the
  packaged `parameter.yml` for every declared environment. The first live deploy must confirm
  that framing a service-principal-owned Direct Lake on OneLake model works with default
  credentials. If it does not, the SSO decision is revisited, not the refresh gate.
