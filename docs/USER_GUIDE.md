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

## 4. Compile

Each invocation resolves its inputs afresh and builds one immutable, graph-free
`CompilePlan`.

```bash
# Write-free validation
uv run kairos-ontology compile customer --check

# Write-free normalized plan inspection
uv run kairos-ontology compile customer --explain
uv run kairos-ontology compile customer --explain --format json

# Deterministic, atomic output
uv run kairos-ontology compile customer \
  --emit ontology-hub/output/medallion/dbt
```

The three modes are mutually exclusive. `--check` and `--explain` do not modify the hub.
`--emit` renders only safe entities, owns only manifest-listed paths below the selected
target, removes stale owned files, and preserves unrelated files. Check success means the
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
