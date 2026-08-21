# Kairos Ontology Toolkit

Kairos is an ontology-driven platform for turning governed business meaning into
deterministic data-platform artifacts. It combines OWL/Turtle domain models,
source-system contracts, and explicit mappings to generate consistent dbt,
business intelligence, search, and MDM outputs.

This repository is the **Kairos meta-repository**. It contains the Python
toolkit, compiler, command-line interface, client-hub scaffold, validation
rules, projectors, Copilot skills, and maintainer documentation used to create
and operate client ontology hubs. Client business models and source mappings do
not belong here; each client receives a separate ontology-hub repository.

## How the Kairos repositories fit together

| Repository | Responsibility |
|---|---|
| **[Kairos Ontology Toolkit](https://github.com/Cnext-eu/kairos-ontology-toolkit)** | Scaffolds client hubs, validates authored inputs, compiles one canonical plan, and emits deterministic artifacts. |
| **[Kairos Reference Models](https://github.com/Cnext-eu/kairos-ontology-referencemodels)** | Publishes reusable industry and cross-domain ontology foundations, patterns, vocabularies, and shared contracts. |
| **Client ontology hub** | Owns one client's business context, source metadata, canonical ontologies, mappings, and transformation contracts. |
| **Published hub output** | Contains generated, immutable artifacts consumed by downstream data-platform repositories and deployment pipelines. |

The toolkit and reference models are installed as pinned Python dependencies in
each client hub. This keeps a hub reproducible while allowing toolkit and model
updates to be reviewed independently.

## What the toolkit does

Kairos supports the complete client-hub lifecycle:

1. scaffold a governed ontology-hub repository;
2. capture confirmed business terminology and source-system metadata;
3. design canonical OWL/Turtle domain models using shared reference models;
4. map source relations to canonical entities with closed `EntityBinding` YAML;
5. validate ontology syntax, SHACL constraints, contracts, and compiler rules;
6. compile all authored inputs into one immutable, graph-free `CompilePlan`;
7. project that plan into deterministic dbt, BI, search, Gold, and MDM
   artifacts.

Version 5 is a clean architecture break. It has no v4 compatibility mode,
dual-format authoring, or automatic v4-to-v5 hub conversion.

## Create a client ontology hub

### Prerequisites

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)
- Git
- An authenticated [GitHub CLI](https://cli.github.com/) session

For interactive setup in GitHub Copilot, invoke the `kairos-setup-init` skill.
It performs the required preflight checks and creates the repository through
the supported workflow.

Toolkit developers can scaffold a hub directly from this checkout:

```powershell
uv sync
uv run kairos-ontology new-repo acme `
  --company-domain acme.com `
  --org Cnext-eu `
  --path ..

cd ..\acme-ontology-hub
uv sync
uv run kairos-ontology init --company-domain acme.com --domain logistics
```

`new-repo` creates a separate `<name>-ontology-hub` Git repository, installs the
managed scaffold, initializes Git, creates the GitHub repository, and configures
branch protection. The generated hub pins compatible toolkit and
reference-model releases in its `pyproject.toml`.

## V5 authoring contract

A client hub has five canonical types of authored input:

1. domain and optional reference-model TTL under `model/ontologies/`;
2. authoritative source-vocabulary TTL under `integration/sources/`;
3. one closed `EntityBinding` YAML per source relation or contracted dbt model
   under `integration/bindings/`;
4. optional ordinary contracted dbt SQL/YAML for joins, windows, aggregations,
   JSON expansion, fallback rules, or grain changes; and
5. optional Gold and MDM policy TTL.

Claims, authored preparation policy, lifecycle/readiness state, release
evidence, and Silver-extension authority are not v5 inputs.

## Client hub layout

```text
<client>-ontology-hub/
├── ontology-hub/                       # Authored inputs
│   ├── kairos.yaml
│   ├── catalog-v001.xml
│   ├── model/
│   │   ├── ontologies/
│   │   └── shapes/                     # Optional SHACL
│   └── integration/
│       ├── sources/
│       ├── bindings/
│       ├── discovery/                  # Confirmed context only
│       ├── transforms/dbt/models/      # Optional ordinary SQL/YAML
│       └── transforms/dbt/seeds/       # Optional static reference CSV
└── ontology-hub-publish/               # Derived output; never hand-edit
```

Existing v4 hubs must be rebuilt as fresh v5 hubs. The `migrate` command only
supports older directory-layout changes; it does not convert v4 authoring
contracts into v5.

## Compile a client domain

Run these commands from a client ontology-hub repository:

```powershell
# Validate one domain without writing files
uv run kairos-ontology compile customer --check --format json

# Inspect the same normalized plan without writing files
uv run kairos-ontology compile customer --explain --format json

# Atomically emit manifest-owned artifacts
uv run kairos-ontology compile customer --emit
```

`compile` resolves the hub from `kairos.yaml` and creates one immutable
`CompilePlan`. Check, explain, emit, Gold, and MDM all consume that same plan.
`--check` and `--explain` are write-free; `--emit` uses a same-volume
stage-and-swap transaction. Supported compiler adapters are `fabric` and
`databricks`.

Passing compilation does not replace downstream dbt, adapter, deployment,
security, or data tests.

## Downstream consumption

Publish emitted artifacts at an immutable Git revision or versioned artifact
location. Pin that revision from the data-platform repository, run `dbt deps`,
`dbt parse`, `dbt build`, and `dbt test`, and never edit compiler-owned output.
See [CompilePlan consumption](docs/CONSUMING_COMPILE_PLAN.md).

## Test an unreleased toolkit version

A client hub can temporarily test an unreleased toolkit branch or commit
without changing its configured release channel:

```powershell
uv run kairos-ontology update --test-ref <branch-or-sha>
# Test the immutable resolved commit.
uv run kairos-ontology update --restore
```

## Documentation

- [User guide](docs/USER_GUIDE.md)
- [CLI reference](docs/CLI_REFERENCE.md)
- [CompilePlan consumption](docs/CONSUMING_COMPILE_PLAN.md)
- [Documentation map](docs/README.md)
- [DD-133 v5 compiler contract](docs/design/dd-133-v5-entity-binding-compile.md)
- [Design decisions](docs/design/toolkit-design-decisions.md)

## Develop the toolkit

```powershell
uv sync --all-groups
uv run pytest
uv build
```

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and
[CHANGELOG.md](CHANGELOG.md).

Licensed under the [Apache License 2.0](LICENSE). Copyright 2026 Cnext.eu.
