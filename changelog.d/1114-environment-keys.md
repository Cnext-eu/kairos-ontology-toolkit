### Fixed
- **Environment keys are case-insensitive: `DEV` and `dev` are one environment.** A hub that
  followed its own `kairos.yaml` template declared `dev`, the deploy workflow defaulted to
  `DEV`, and fabric-cicd matches `parameter.yml` keys case-sensitively, so the deploy failed
  (or, before #993, silently deployed the default workspace). The hub's
  `direct_lake_connection` and `databricks_connection`, `gold-connections.yml`,
  `apply-gold-connection --environment` and the deploy workflow's `target_environment` now
  all normalise to lowercase. An older hub's `DEV`/`PROD` keys in a shipped `parameter.yml`
  are renamed at deploy time and the rename is logged. The same rename happens when an
  authored reports `parameter.yml` is staged. Two keys that differ only in case fail closed.
  Existing `DEV`/`UAT`/`PROD` GitHub Environments keep working, because GitHub matches
  Environment names case-insensitively.
- **`apply-gold-connection` no longer writes a OneLake URL into a Databricks model.** It
  rewrote every `replace_value` in `parameter.yml`, including a directQuery model's
  `server_hostname` and `http_path`. An override now rewrites only the entries of its own
  kind, and a mismatched override (Direct Lake keys for a Databricks model, or the reverse)
  fails closed. `gold-connections.yml` also accepts `server_hostname`/`http_path` per
  environment, so a dataplatform can point a Databricks model at its own warehouse.

### Changed
- **Managed workflow:** `deploy-powerbi-semantic-model.yml` now defaults `target_environment`
  to `dev` and normalises it once for every step. Existing dataplatforms pick this up through
  `update`.

### Documentation
- `kairos-setup-config` no longer claims a Fabric Direct Lake hub needs no connection block.
  The `kairos.yaml`, user-guide, README, `CICD.md` and `gold-connections.yml` examples use
  lowercase `dev`/`uat`/`prod`. `CICD.md` names the optional `AZURE_SUBSCRIPTION_ID` and
  says the `${VAR}` values come from the deploy's GitHub Environment.
