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
│   └── transforms/dbt/models/               # optional SQL/YAML
└── output/                                  # generated
```

The authored authorities are:

- canonical domain and reference semantics in OWL/Turtle;
- source relations and columns in source-vocabulary Turtle;
- exactly one closed `EntityBinding` per source relation or contracted dbt model;
- ordinary contracted dbt SQL and model YAML only for relational logic outside the closed
  scalar-expression grammar; and
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
adapter: fabric
```

Compiler adapters are `fabric` and `databricks`. An unsupported value is rejected; it is
never silently mapped to another dialect.

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
This block is Databricks-only: a Fabric Direct Lake partition resolves its binding from the
workspace it is deployed into and needs no connection configuration.

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
uv run kairos-ontology compile customer --emit
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

For the exact supported command list, see [CLI reference](CLI_REFERENCE.md). For the
normative compiler contract, see
[DD-133](design/dd-133-v5-entity-binding-compile.md).
