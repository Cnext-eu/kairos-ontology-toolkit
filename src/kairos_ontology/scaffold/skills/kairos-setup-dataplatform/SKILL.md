---
name: kairos-setup-dataplatform
description: Scaffold a downstream dbt repository that consumes v5 compile output.
---

# Dataplatform Setup

The ontology hub compiles canonical dbt artifacts; the dataplatform supplies physical connections,
deployment configuration, and runtime tests.

1. From a v5 hub, run `kairos-ontology compile <domain> --check --format json` for each selected
   domain and resolve all errors.
2. Set `KAIROS_SKILL_CONTEXT=1`, then run
   `kairos-ontology init-dataplatform <name> --platform <platform>`
   (`fabric-warehouse` or `databricks` — the same vocabulary the hub's `kairos.yaml`
   uses, and normally the same value; `fabric-lakehouse` is no longer offered because
   the compiler has no Spark SQL profile for it, see DD-215). This also scaffolds the
   managed root `CICD.md` and `CONTRIBUTING.md` — confirm both exist and point users
   to them for the CI target, promotion, rollback, and hotfix workflow.
3. `profiles.yml` (committed, at the repository root) is the environment authority
   (DD-255): one dbt target per environment, `dev`, `uat` and `prod`, already active for the
   chosen `--platform`. Fill in each target's endpoint and database — never a credential;
   those come from environment variables — and commit it. The name of a target is the
   environment's key everywhere: `dbt build --target uat`, the GitHub Environment, and the
   Power BI binding. If the semantic models or reports live in a different workspace from the
   Gold Warehouse, name it under `vars.kairos.environments.<env>` in `dbt_project.yml`.
   Check each target with `uv run kairos-ontology resolve-environment --target <env>`
   (`--offline` when no Fabric sign-in is at hand).
   The scaffold also writes the managed `.github/workflows/promote.yml` (DD-256): merging to
   `main` promotes one commit through `dev`, `uat` and `prod`, each environment waiting for its
   GitHub Environment's reviewers. Pin the hub with `kairos-ontology bump-hub <release tag>`,
   which writes `packages.yml` and `hub-release.lock` together, and commit both.
   `--platform` picks where **this dbt project's own silver/gold models write** and which
   adapter is templated — bronze source data can live in any same-workspace item (e.g. a
   Fabric Lakehouse) regardless of the chosen platform; bind it via `database:` in
   `_sources.yml` using the platform's native cross-item SQL, no second connection needed.
   **Read the hub's `kairos.yaml` `adapter:` and use the same value unless the user
   deliberately wants otherwise.** Nothing verifies that the two agree, and a mismatch
   surfaces only as an opaque SQL error on the first real run — the hub's emitted SQL is
   written for the hub's adapter, not this project's.
4. Bind physical databases, schemas, and source relations in the downstream dbt project.
5. Consume the compiler-emitted dbt package at an immutable Git revision or artifact version.
6. Run `dbt deps`, `dbt parse`, `dbt build`, and `dbt test` against the target adapter.
7. Validate generated Power BI assets in the selected Fabric/Power BI deployment toolchain when
   Gold output is consumed. Before the first promotion, walk the user through
   `CICD.md` "Fabric deploy prerequisites" and "Add an environment": one GitHub Environment
   per dbt target (`dev`, `uat`, `prod`) holding the Azure IDs, required reviewers on `uat` and
   `prod`, a federated credential per Environment, the service-principal tenant setting and
   workspace role (DD-239). `FABRIC_WORKSPACE_ID`/`FABRIC_ITEM_ID` are optional once
   `profiles.yml` identifies the Gold Warehouse (DD-255). Finish with
   `kairos-ontology check-environments --github-repo <org>/<repo> --online`, which names each
   missing piece. The scaffold includes `fabric/KairosModelBpa.Notebook`, which the
   deploy workflow runs after publishing as an advisory Best Practice Analyzer check (DD-238).
   To keep its findings, create a lakehouse and set the `FABRIC_BPA_LAKEHOUSE_ID` and
   `FABRIC_BPA_LAKEHOUSE_NAME` repository variables. Without them findings are only printed in
   the notebook run. The step never blocks a deploy; see `CICD.md` for the per-target
   differences.

Source schema extraction may feed reviewed source TTL in the hub. Complex upstream logic must be an
ordinary contracted dbt SQL/YAML model and referenced directly by an EntityBinding. The
dataplatform must not redefine canonical grain, identity, load behavior, or field mappings.
