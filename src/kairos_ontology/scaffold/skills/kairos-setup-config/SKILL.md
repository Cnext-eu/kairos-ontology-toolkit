---
name: kairos-setup-config
description: Configure the stateless v5 ontology-hub layout and authored inputs.
---

# Hub Configuration

Use `kairos-ontology init` through this skill; do not hand-create toolkit-managed files.
Set `KAIROS_SKILL_CONTEXT=1` before CLI calls.

## V5 layout

```text
model/ontologies/<domain>.ttl
model/shapes/
integration/discovery/
integration/sources/<source>/
integration/bindings/<source>-to-<domain>.binding.yaml
integration/transforms/dbt/models/
kairos.yaml
../ontology-hub-publish/
```

`integration/bindings/` contains closed EntityBinding YAML and is the sole source-to-canonical
execution authority. Complex joins, windows, aggregations, JSON expansion, fallback logic, or grain
changes belong in ordinary contracted dbt SQL and properties YAML, then are referenced by
`source.dbtModel`. `../ontology-hub-publish/` (a sibling of the hub) is derived and safe to regenerate.

Configure namespace, catalog, adapters, and selected roots in `kairos.yaml`. Keep each domain in an
OWL ontology with labels/comments and explicit imports. Add optional SHACL in `model/shapes/`.
Validate ontology inputs, then run `compile --check` before emission.

## Databricks Gold semantic-model connection

With `adapter: databricks`, the Gold Power BI semantic model is `directQuery` over a Databricks SQL
warehouse. Authoring cannot be inferred from the ontology, so declare it per environment in
`kairos.yaml`:

```yaml
gold:
  databricks_connection:
    default_environment: DEV
    environments:
      DEV:
        server_hostname: adb-1111111111111111.11.azuredatabricks.net
        http_path: /sql/1.0/warehouses/dev0000000000000
      PROD:
        server_hostname: adb-2222222222222222.22.azuredatabricks.net
        http_path: /sql/1.0/warehouses/prod000000000000
```

The projected TMDL partitions carry the `default_environment` values, and a generated
fabric-cicd `parameter.yml` (at the root of the semantic-model package) rewrites them for the
environment being deployed to. `default_environment` may be omitted only with a single
environment. Gold projection fails closed with `gold.databricks-connection-missing` until the
block exists. `adapter: fabric` needs none of this: a Direct Lake partition resolves its binding
from the workspace it lands in.

## Pin the accelerator (multi-pack hubs)

When the hub ships more than one reference-model accelerator pack, `check-inventory`,
`validate`, and `compile` cannot guess which pack to resolve inventories against and abort
with an `Accelerator selection is ambiguous` error. Pin the pack once in the hub
`pyproject.toml` (not `kairos.yaml`) so every command resolves it without a per-invocation
`--accelerator` flag:

```toml
[tool.kairos]
accelerator = "logistics"
```

An explicit `--accelerator <pack>` on any single command still overrides the pin. A hub with
exactly one installed pack needs neither the pin nor the flag.
