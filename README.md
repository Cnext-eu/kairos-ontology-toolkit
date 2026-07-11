<p align="center">
<pre align="center">

    $$\   $$\  $$$$$$\  $$$$$$\ $$$$$$$\   $$$$$$\   $$$$$$\
    $$ | $$  |$$  __$$\ \_$$  _|$$  __$$\ $$  __$$\ $$  __$$\
    $$ |$$  / $$ /  $$ |  $$ |  $$ |  $$ |$$ /  $$ |$$ /  \__|
    $$$$$  /  $$$$$$$$ |  $$ |  $$$$$$$  |$$ |  $$ |\$$$$$$\
    $$  $$<   $$  __$$ |  $$ |  $$  __$$< $$ |  $$ | \____$$\
    $$ |\$$\  $$ |  $$ |  $$ |  $$ |  $$ |$$ |  $$ |$$\   $$ |
    $$ | \$$\ $$ |  $$ |$$$$$$\ $$ |  $$ | $$$$$$  |\$$$$$$  |
    \__|  \__|\__|  \__|\______|\__|  \__| \______/  \______/

              O N T O L O G Y   T O O L K I T

</pre>
</p>

<p align="center">
  <strong>Kairos Ontology Toolkit</strong><br>
  <em>Part of the <a href="https://github.com/Cnext-eu">Kairos Community Edition</a> by Cnext.eu</em>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue.svg" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.12%2B-brightgreen.svg" alt="Python">
</p>

---

**Turn OWL/Turtle ontologies into production-ready data artifacts** — medallion-layer
SQL schemas, dbt models, Power BI semantic models, graph databases, search indexes,
and AI prompt context — with built-in validation and a single CLI command.

> 📖 **New here?** Read the [User Guide](docs/USER_GUIDE.md) for a complete walkthrough.

---

## ✨ Key Features

| Category | Highlights |
|----------|-----------|
| 🔍 **Validation** | 3-level pipeline: RDF/OWL syntax → SHACL constraints → SPARQL consistency |
| 🏗️ **8 Projection Targets** | Silver DDL, dbt, Power BI / TMDL, Neo4j, Azure Search, a2ui, prompt, HTML report |
| 🥈 **Medallion Architecture** | Full silver + gold layers with SCD2, GDPR satellites, junction tables, conformed dimensions |
| 📦 **Hub Scaffolding** | `kairos init` bootstraps a complete ontology repository with CI, skills, and config |
| 🔗 **Full Traceability** | SKOS-based source→domain lineage in every generated SQL comment and schema YAML |
| 🌐 **Multi-Domain** | Each domain deploys independently; cross-domain FK joins resolve automatically |
| 📊 **Power BI** | Star-schema gold layer, TMDL import/export, DAX measures, hierarchies, RLS |

## 🚀 Quick Start

```bash
# Install from a tagged GitHub release (the toolkit is not published to PyPI)
pip install "git+https://github.com/Cnext-eu/kairos-ontology-toolkit.git@v3.16.0"

# Scaffold a new ontology hub
kairos-ontology init my-ontology-hub

# Validate ontologies
kairos-ontology validate --all

# Generate all projection targets
kairos-ontology project --target all
```

## 🎯 Projection Targets

| Target | Output | Use Case |
|--------|--------|----------|
| **silver** | `CREATE TABLE` DDL, `ALTER TABLE`, Mermaid ERD + SVG | Fabric/Databricks warehouse physical layer |
| **dbt** | SQL models, `schema.yml`, `dbt_project.yml` (silver + gold) | dbt-based ELT pipelines on Fabric/Databricks |
| **powerbi** | Star schema DDL, TMDL, DAX measures, hierarchies | Power BI DirectLake semantic models |
| **neo4j** | Cypher `CREATE` statements | Knowledge graph databases |
| **azure-search** | JSON index definitions | Azure AI Search |
| **a2ui** | JSON Schema messages | UI generation / form builders |
| **prompt** | JSON context documents | LLM prompt engineering |
| **report** | HTML mapping report with data flow diagrams | Source-to-domain coverage review |
| **mdm-profile** | Immutable, content-addressed MDM policy profile (JSON + review MD) | Master Data Management — consumed by `kairos-mdm-runtime` (opt-in; requires `*-mdm-ext.ttl`) |

Each target produces per-domain output — deploy and version domains independently.

## 🏛️ Architecture

```
kairos-ontology-toolkit/
├── src/kairos_ontology/              # Core toolkit (pip-installable)
│   ├── cli/                          # Click CLI (validate, project, init, import-tmdl)
│   ├── projections/                  # 8 projection generators
│   │   ├── medallion_silver_projector.py   # Silver DDL + ERD
│   │   ├── medallion_dbt_projector.py      # dbt models (silver + gold)
│   │   ├── medallion_gold_projector.py     # Gold star-schema definitions
│   │   └── ...                             # neo4j, azure-search, a2ui, prompt, report
│   ├── scaffold/                     # Hub repo templates (distributed via init/update)
│   ├── templates/                    # Jinja2 output templates per target
│   ├── validator.py                  # 3-level validation pipeline
│   └── projector.py                  # Multi-domain projection orchestrator
└── tests/                            # pytest test suite (1000+ tests)
    └── scenarios/                    # Full-pipeline scenario tests (acme-hub)
```

## 📂 Hub Repository Structure

When you run `kairos-ontology init`, you get a fully configured ontology hub:

```
my-ontology-hub/
├── model/
│   ├── ontologies/          # Domain ontologies (.ttl) — the single source of truth
│   ├── extensions/          # Silver/gold extension annotations (*-silver-ext.ttl, *-gold-ext.ttl)
│   ├── mappings/            # SKOS source-to-domain column mappings
│   └── reference-models/    # Shared/imported ontologies + XML catalog
├── sources/                 # Bronze source vocabulary descriptions
├── output/                  # Generated projections (per target, per domain)
│   └── medallion/
│       ├── dbt/             # dbt project (models/, macros/, dbt_project.yml)
│       ├── silver/          # DDL + ERD diagrams
│       └── powerbi/         # TMDL + star schema
├── shapes/                  # SHACL validation shapes (optional)
└── .github/skills/          # Copilot agent skills for interactive modeling
```

## 🛠️ Development

```bash
git clone https://github.com/Cnext-eu/kairos-ontology-toolkit.git
cd kairos-ontology-toolkit
uv sync --all-groups              # install all deps
uv run pytest                     # 1000+ tests
```

[uv](https://docs.astral.sh/uv/) manages dependencies, environments, and builds.
See [CONTRIBUTING.md](CONTRIBUTING.md) for the full development workflow.

## 🤝 Community

This project is part of the **Kairos Community Edition** — an open-source suite of
tools for ontology-driven data architecture.

| | |
|---|---|
| 📋 [Contributing Guide](CONTRIBUTING.md) | How to contribute (DCO sign-off, PR process) |
| 📜 [Code of Conduct](CODE_OF_CONDUCT.md) | Contributor Covenant v2.1 |
| 🔒 [Security Policy](SECURITY.md) | Vulnerability reporting |
| 📝 [Changelog](CHANGELOG.md) | Release history |
| 📖 [User Guide](docs/USER_GUIDE.md) | Complete walkthrough & reference |
| 🏗️ [Design Decisions](docs/design/toolkit-design-decisions.md) | ADR log for architectural choices |

## 📄 License

Licensed under the **Apache License, Version 2.0** — see [LICENSE](LICENSE) for details.

Copyright 2026 [Cnext.eu](https://cnext.eu) — Built with ❤️ as part of the
**Kairos Community Edition**.