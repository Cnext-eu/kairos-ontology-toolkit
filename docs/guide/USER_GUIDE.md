# Kairos Ontology Toolkit v5 — User Guide

V5 turns reviewed ontology and source contracts into one immutable `CompilePlan`, then
checks, explains, or emits that plan. It is deliberately stateless and has no v4
compatibility or migration path.

## 1. Install or create a hub

Python 3.12+, Git, and [uv](https://docs.astral.sh/uv/) are required.

```bash
uv sync
uv run kairos-ontology init --company-domain example.org --domain customer
```

Use synthetic organization and person data in examples and tests. Never commit credentials,
raw personal data, or proprietary samples.

## 2. Author only canonical inputs

```text
ontology-hub/
├── kairos.yaml
├── catalog-v001.xml
├── model/
│   ├── ontologies/<domain>.ttl
│   └── shapes/                              # optional
├── integration/
│   ├── sources/<source>/*.ttl
│   ├── bindings/*.binding.yaml
│   ├── discovery/                           # confirmed context only
│   ├── transforms/dbt/models/               # optional SQL/YAML
│   └── transforms/dbt/seeds/                # optional static reference CSV
└── output/                                  # generated
```

The authored authorities are:

- canonical domain and reference semantics in OWL/Turtle;
- source relations and columns in source-vocabulary Turtle;
- exactly one closed `EntityBinding` per source relation or contracted dbt model;
- ordinary contracted dbt SQL and model YAML only for relational logic outside the closed
  scalar-expression grammar;
- optional dbt seed CSVs for small, static, hand-maintained reference data that belongs in
  version control rather than a warehouse source, with optional sibling `seeds/<name>.yml`
  column docs; and
- optional Gold and MDM policy TTL.

The binding owns source-to-canonical execution. Unknown YAML fields, duplicate keys,
unresolved terms, unsupported expressions, and incomplete runtime policies fail closed.
Multi-source entities use separate bindings joined by one explicit conformance contract.

V5 does not author claims, preparation/Silver extension policy, lifecycle/readiness state,
transformation evidence registries, release baselines, or generated output.

## 3. Configure the adapter

`ontology-hub/kairos.yaml` is the authority:

```yaml
version: 5
name: sample-ontology-hub
adapter: fabric-warehouse
```

Set it at scaffold time so you never have to remember to:

```powershell
kairos-ontology init --adapter databricks --company-domain acme.com
```

| Adapter | Engine | SQL dialect | dbt adapter |
|---|---|---|---|
| `fabric-warehouse` | Microsoft Fabric Warehouse | T-SQL | `dbt-fabric` |
| `databricks` | Azure Databricks | Spark SQL | `dbt-databricks` |

The id names the **engine**, not the vendor, because that is what decides the SQL. Fabric
Lakehouse is Spark SQL rather than T-SQL, so `fabric-lakehouse` is recognised and
rejected rather than compiled as Fabric Warehouse — there is no Spark SQL profile for it
yet, and emitting T-SQL would produce a project that compiles cleanly and fails on its
first warehouse run. Any other value is rejected too; nothing is ever silently mapped to
another dialect, and there is no default (DD-215).

> **`adapter: fabric` still works** and resolves to `fabric-warehouse`, with a warning.
> Adopting the canonical id changes the hub's provenance hash, so the first compile after
> you change it will report drift until you re-emit — the same re-emit a toolkit upgrade
> already asks for.

The adapter also decides the SQL the compiler emits, and the SQL you may hand-write in
`integration/transforms/dbt/`. The dialects are not interchangeable: on
`fabric-warehouse` a `bit` column needs `where flag = 1`, while on `databricks` the same
column needs a bare `where flag` and rejects `= 1`. Write for the target the hub declares
rather than trying to satisfy both; if some logic genuinely must serve both, express it in
the binding, which the compiler renders per adapter.

On `databricks`, the Gold Power BI semantic model is generated as `directQuery` over a
Databricks SQL warehouse, so it needs connection coordinates the ontology cannot supply.
Declare them per environment — one released semantic model is promoted across
environments:

```yaml
adapter: databricks

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

The projected TMDL partitions carry the `default_environment` values, and the projector
emits a fabric-cicd `parameter.yml` beside them whose `find_replace` entries rewrite those
two values for the environment being deployed to (`FabricWorkspace(environment=...)` in
`.github/workflows/deploy-powerbi-semantic-model.yml`). `parameter.yml` must stay at the
root of the directory fabric-cicd is pointed at.

`default_environment` may be omitted only when a single environment is declared. Gold
projection on `databricks` fails closed with `gold.databricks-connection-missing` when the
block is absent, and with `gold.databricks-connection-invalid` when it is malformed —
generating a semantic model that cannot reach a warehouse is not an acceptable outcome.
Fabric Direct Lake uses the sibling `gold.direct_lake_connection` block instead, declaring a
`workspace_id` and `lakehouse_id` per environment. It is equally required: a Direct Lake model
binds through a named expression that embeds those GUIDs, so projection fails closed with
`gold.direct-lake-connection-missing` when the block is absent. Both modes emit a root
`parameter.yml` so fabric-cicd can rewrite the environment-specific values at deploy time.

## 4. Compile

Each invocation resolves its inputs afresh and builds one immutable, graph-free
`CompilePlan`.

```bash
# Write-free validation
uv run kairos-ontology compile customer --check

# Write-free normalized plan inspection
uv run kairos-ontology compile customer --explain
uv run kairos-ontology compile customer --explain --format json

# Deterministic, atomic output to the fixed publish location
uv run kairos-ontology compile customer --emit --confirm-emit
```

The three modes are mutually exclusive. `--check` and `--explain` do not modify the hub.
`--emit` renders only safe entities to the fixed
`ontology-hub-publish/medallion/dbt` location, owns only manifest-listed paths there,
removes stale owned files, and preserves unrelated files. Check success means the
static compile contract passed; it is not deployment, runtime validation, or release
certification.

Gold and MDM are optional consumers of the same `CompilePlan`; they do not re-resolve
ontology, binding, or source authority.

## 5. Complex relational transformations

Keep joins, windows, rankings, aggregation, JSON expansion, fallback logic, and grain
changes in ordinary dbt SQL with authoritative model-contract YAML. Reference both paths
from `source.dbtModel` in one binding. Do not embed raw SQL in binding expressions or
introduce a second Kairos evidence/readiness authority.

## 6. Consume generated artifacts

Publish emitted artifacts at an immutable Git revision or versioned artifact location.
Downstream dataplatforms pin the artifact, run `dbt deps`, `dbt parse`, `dbt build`, and
`dbt test`, and use package-qualified `ref()`. Runtime connection, adapter, and data-test
failures belong to the dataplatform; compiler diagnostics belong to the hub.

See [CompilePlan consumption](CONSUMING_COMPILE_PLAN.md).

## 7. Toolkit updates

```bash
# Refresh managed files
uv run kairos-ontology update

# Preview managed-file drift
uv run kairos-ontology update --check

# Upgrade through the configured stable/preview channel
uv run kairos-ontology update --upgrade

# Reversibly test an unreleased immutable commit
uv run kairos-ontology update --test-ref <branch-or-sha>
uv run kairos-ontology update --restore
```

`--test-ref` resolves a branch or SHA to an immutable commit, saves the exact prior
dependency source, and refreshes managed files. `--restore` restores that source.
Neither operation publishes a tag, package, release asset, or GA release.

## 8. V4 cutover

There is no compatibility flag, dual authoring, automated upgrade, or v4-to-v5 migration
command. Rebuild the hub with the lean v5 scaffold and port only canonical semantics,
source vocabularies, binding intent, ordinary contracted dbt, and current optional
Gold/MDM policy. Historical design decisions remain available for provenance but are not
active guidance.

For step-by-step recipes for individual tasks, see the [how-to guides](how-to/README.md). For the exact supported command list, see [CLI reference](CLI_REFERENCE.md). For the
normative compiler contract, see
[DD-133](https://github.com/Cnext-eu/kairos-ontology-toolkit/blob/main/docs/dev/dd-133-v5-entity-binding-compile.md).
