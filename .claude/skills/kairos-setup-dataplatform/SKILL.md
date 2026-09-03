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
3. `.dbt/profiles.yml.example` is already pre-activated for the chosen `--platform` — its block
   is uncommented under `dev:`, the other platform remains as a commented reference block.
   Copy it to `.dbt/profiles.yml` and fill in real connection details/credentials only; no
   manual comment-toggling between platforms is required.
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
   Gold output is consumed.

Source schema extraction may feed reviewed source TTL in the hub. Complex upstream logic must be an
ordinary contracted dbt SQL/YAML model and referenced directly by an EntityBinding. The
dataplatform must not redefine canonical grain, identity, load behavior, or field mappings.
