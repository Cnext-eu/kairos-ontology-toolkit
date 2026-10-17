### Added
- **`resolve-environment --target <t>`: the dbt target is the environment authority
  (DD-255).** The dataplatform's dbt target now names an environment and identifies its Gold
  connection:
  - A Fabric target's `server` and `database` find its Gold Warehouse through the Fabric REST
    API.
  - A Databricks target's `host` and `http_path` are the connection itself.
  - `vars.kairos.environments.<env>` in `dbt_project.yml` names the models and reports
    workspaces. Both default to the Gold workspace.
  - The explicit `FABRIC_*` variables still take precedence.

  Each value is printed with its source. `--offline` checks the target without calling Fabric,
  and `--format github-output` feeds a workflow. `apply-gold-connection --from-dbt-target <t>`
  applies the resolved connection instead of `gold-connections.yml`.

### Changed
- **A hub no longer has to declare `gold.direct_lake_connection` or
  `gold.databricks_connection`.** Without one, the emitted model carries an unresolvable
  placeholder and `parameter.yml` declares no environment. The dataplatform's deploy then
  binds the model to the environment it deploys to, and `apply-gold-connection` fails closed
  when nothing supplies one. Hubs that keep their block are unchanged. The
  `gold.*-connection-missing` errors are gone.
- **`init-dataplatform` writes a committed `profiles.yml`** at the repository root, with `dev`,
  `uat` and `prod` targets and no credentials. It replaces the gitignored
  `.dbt/profiles.yml.example`. `dbt_project.yml` gains a commented `vars.kairos` example.
  Existing dataplatforms are not changed.
