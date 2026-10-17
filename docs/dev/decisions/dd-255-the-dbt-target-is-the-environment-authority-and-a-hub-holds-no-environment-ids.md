# DD-255: The dbt target is the environment authority, and a hub holds no environment IDs

**Status:** Accepted
**Date:** 2026-10-17
**Affects:** `core/dbt_environment.py`, `core/fabric_api.py`, `cli/environment.py`
(`resolve-environment`), `apply-gold-connection --from-dbt-target`,
`core/projections/dbt/gold_render.py` and `gold_connection.py` (optional connection blocks),
the dataplatform scaffold (committed `profiles.yml`, `vars.kairos` in `dbt_project.yml`), the
`kairos-setup-config`, `kairos-setup-dataplatform` and `kairos-design-gold` skills
**Issue:** #1114 (follows DD-239 and DD-253; the managed promotion workflow follows separately)

### Context

Promoting a client platform from DEV to UAT showed that its environment configuration lived in
five places, across two repositories:

- the hub's `kairos.yaml` (`gold.direct_lake_connection.environments`);
- the dataplatform's `.github/fabric/gold-connections.yml`;
- an authored-report `parameter.yml`;
- the GitHub Environment variables;
- dbt's `profiles.yml`.

Adding an environment meant editing both repositories and re-releasing the hub only to add a
key. The same IDs sat in several files that could drift. The hub was otherwise
environment-agnostic, and its scaffolded `CICD.md` already argued it should not hold
environment IDs.

dbt already gives the dataplatform what this needs: targets (one per environment),
configuration with defaults (package `vars`), and a file every dbt run already reads. The
environment-key casing problem (`dev` vs `DEV`) was fixed separately, by lowercasing every key
(#1114 P1).

### Decision

**The dataplatform's dbt target names the environment and identifies its Gold connection, and
Kairos reads both from it instead of keeping a parallel declaration.**

1. **`profiles.yml` is committed.** The dataplatform scaffold writes it at the repository root
   with a `dev`, `uat` and `prod` target. It holds endpoints and database names only;
   credentials stay in environment variables (`env_var()` or the adapter's own). dbt finds it
   without flags. `.dbt/profiles.yml` stays gitignored, for personal overrides and PR CI's
   placeholder `ci` profile.
2. **The target name is the environment key.** It is lowercased once
   (`normalize_environment_key`). The same string names the dbt build, the GitHub Environment
   and the `parameter.yml` key.
3. **The Gold connection is derived, not declared.**
   - A Databricks target's `host` and `http_path` *are* the connection.
   - A Fabric target's `server` (the SQL endpoint) and `database` identify a Warehouse. Kairos
     lists the workspaces the deploy identity can see through the Fabric REST API and picks the
     one Warehouse whose `connectionString` host and display name match. It fails closed on no
     match or several, and lists what it saw.
4. **What dbt cannot know goes in namespaced vars.** `vars.kairos.environments.<env>` in
   `dbt_project.yml` may name `models_workspace` and `reports_workspace` (by display name or
   GUID). Both default to the Gold workspace. `gold_workspace` narrows the Warehouse search. It
   is read as YAML only; dbt sees a global var named `kairos`.
5. **Explicit variables still win.** `FABRIC_ITEM_ID` (with `FABRIC_GOLD_WORKSPACE_ID`, else
   `FABRIC_WORKSPACE_ID`), `FABRIC_WORKSPACE_ID` and `FABRIC_REPORTS_WORKSPACE_ID` override the
   derivation, so an existing deploy keeps working unchanged. Every resolved value reports its
   source.
6. **`resolve-environment --target <t>` shows the result.**
   - `--offline` checks the target and vars without calling Fabric.
   - `--format github-output` feeds a workflow.
   - `apply-gold-connection --from-dbt-target <t>` applies the resolved connection to the
     archive's `parameter.yml` instead of reading `gold-connections.yml`.
7. **The hub's connection blocks are optional.** Without `gold.direct_lake_connection` (or
   `gold.databricks_connection`):
   - the TMDL carries a recognisable, unresolvable placeholder, and `parameter.yml` finds it
     with no environment declared;
   - `apply-gold-connection` must add the target environment, or it fails closed and says the
     hub declares none;
   - a model that somehow deploys unrewritten cannot frame, and the DD-239 refresh gate fails
     the deploy.

   A hub that keeps its block is unchanged.

`profiles.yml` values are rendered with `env_var()` only. Other Jinja is rejected, and only the
fields resolution reads are rendered, so an unset secret elsewhere in a target does not block
it. The Fabric client is read-only. It takes its token from `azure-identity` when installed and
otherwise from the Azure CLI, which a workflow has after `azure/login`.

### Consequences

- A new environment is a new dbt target, plus a GitHub Environment for its secrets and
  approvals. The hub is not touched or re-released. Wiring this into a managed promotion
  workflow (one SHA through dev → uat → prod) is the next step of #1114, and until then the
  deploy workflow still reads `gold-connections.yml`.
- `gold-connections.yml` becomes a fallback for setups that cannot use the API. It is not
  removed.
- The scaffolded `profiles.yml` replaces `.dbt/profiles.yml.example`, and the local commands in
  the dataplatform README drop `--profiles-dir .dbt`. Existing dataplatforms are not changed:
  `profiles.yml` is not a managed file.
- The deploy identity needs read access, through the Fabric API, to the workspace that holds
  the Gold Warehouse, which a Direct Lake binding needs anyway.
- A hub without a connection block can no longer be opened against real data in Power BI
  Desktop straight from the emitted folder. Declare the block for that.
- Rejected: keeping workspace and item IDs in the hub per environment. That is the duplication
  this removes.
- Rejected: resolving the Warehouse from the SQL endpoint host alone. Several Warehouses share
  a workspace's endpoint, so the name is needed too.
- Rejected: rendering `profiles.yml` with full dbt Jinja. Kairos would then need dbt's context
  (`target`, `var()`), and a profile needs only `env_var()`.
- Verified offline and in tests with a fake Fabric transport. A live resolution against a Fabric
  tenant is still owed, as it is for DD-239 and DD-253.
