# Kairos Ontology Toolkit

Kairos compiles governed OWL/Turtle models and source contracts into deterministic data
artifacts. Version 5 is a clean architecture break: it has no v4 compatibility mode,
dual-format authoring, or hub migration path.

> This repository contains a **5.0 candidate**, not a published 5.0 GA release.

## V5 authoring contract

The canonical authored inputs are:

1. domain and optional reference-model **TTL** under `model/ontologies/`;
2. authoritative source-vocabulary **TTL** under `integration/sources/`;
3. one closed `EntityBinding` YAML per source relation or contracted dbt model under
   `integration/bindings/`;
4. optional ordinary contracted dbt **SQL/YAML** for joins, windows, aggregation, JSON
   expansion, fallback rules, or grain changes; and
5. optional Gold and MDM policy TTL.

Claims, authored preparation policy, lifecycle/readiness state, release evidence, and
Silver-extension authority are not v5 inputs.

## Compile

```bash
# Validate one domain without writing
uv run kairos-ontology compile customer --check

# Inspect the same normalized plan
uv run kairos-ontology compile customer --explain
uv run kairos-ontology compile customer --explain --format json

# Atomically emit manifest-owned artifacts
uv run kairos-ontology compile customer --emit ontology-hub/output/medallion/dbt
```

`compile` resolves the hub from `kairos.yaml`, creates one immutable, graph-free
`CompilePlan`, and uses that plan for check, explain, emit, Gold, and MDM consumption.
`--check` and `--explain` are write-free. `--emit` is deterministic and uses a
same-volume stage-and-swap transaction. Supported compiler adapters are `fabric` and
`databricks`, selected in `kairos.yaml`.

## Lean hub layout

```text
ontology-hub/
├── kairos.yaml
├── catalog-v001.xml
├── model/
│   ├── ontologies/
│   └── shapes/                         # optional SHACL
├── integration/
│   ├── sources/
│   ├── bindings/
│   ├── discovery/                      # confirmed context only
│   └── transforms/dbt/                 # optional ordinary SQL/YAML
└── output/                             # derived; never author here
```

Create a hub with `kairos-ontology init` or `new-repo`. Existing v4 hubs must be rebuilt
as fresh v5 hubs; `migrate` only handles an older directory-layout operation and does not
convert v4 authoring to v5.

## Downstream consumption

Publish emitted artifacts at an immutable Git revision or versioned artifact location.
Pin that revision from the dataplatform, run `dbt deps`, `dbt parse`, `dbt build`, and
`dbt test`, and never edit compiler-owned output. See
[CompilePlan consumption](docs/CONSUMING_COMPILE_PLAN.md).

## Unreleased toolkit testing

```bash
uv run kairos-ontology update --test-ref <branch-or-sha>
# test the immutable resolved commit
uv run kairos-ontology update --restore
```

This does not change the configured release channel or publish a release.

## Documentation

- [User guide](docs/USER_GUIDE.md)
- [CLI reference](docs/CLI_REFERENCE.md)
- [CompilePlan consumption](docs/CONSUMING_COMPILE_PLAN.md)
- [Documentation map](docs/README.md)
- [DD-133 v5 compiler contract](docs/design/dd-133-v5-entity-binding-compile.md)
- [Design decisions](docs/design/toolkit-design-decisions.md)

## Development

```bash
uv sync --all-groups
uv run pytest
uv build
```

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and
[CHANGELOG.md](CHANGELOG.md).

Licensed under the [Apache License 2.0](LICENSE). Copyright 2026 Cnext.eu.
