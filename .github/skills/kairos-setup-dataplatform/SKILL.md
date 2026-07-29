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
   `kairos-ontology init-dataplatform <name> --platform <platform>`.
3. Configure `profiles.yml` without committing credentials.
4. Bind physical databases, schemas, and source relations in the downstream dbt project.
5. Consume the compiler-emitted dbt package at an immutable Git revision or artifact version.
6. Run `dbt deps`, `dbt parse`, `dbt build`, and `dbt test` against the target adapter.
7. Validate generated Power BI assets in the selected Fabric/Power BI deployment toolchain when
   Gold output is consumed.

Source schema extraction may feed reviewed source TTL in the hub. Complex upstream logic must be an
ordinary contracted dbt SQL/YAML model and referenced directly by an EntityBinding. The
dataplatform must not redefine canonical grain, identity, load behavior, or field mappings.
