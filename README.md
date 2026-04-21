<p align="center">
  <strong>Kairos Ontology Toolkit</strong><br>
  <em>Part of the <a href="https://github.com/Cnext-eu">Kairos Community Edition</a> by Cnext.eu</em>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue.svg" alt="License"></a>
  <a href="https://pypi.org/project/kairos-ontology-toolkit/"><img src="https://img.shields.io/pypi/v/kairos-ontology-toolkit.svg" alt="PyPI"></a>
  <img src="https://img.shields.io/badge/python-3.12%2B-brightgreen.svg" alt="Python">
</p>

---

**Turn OWL/Turtle ontologies into production-ready data artifacts** — DDL schemas,
dbt models, graph databases, search indexes, UI schemas, and AI prompt context — with
built-in validation and a single CLI command.

> 📖 **New here?** Read the [User Guide](docs/USER_GUIDE.md) for a complete walkthrough.

---

## ✨ Key Features

- 🔍 **3-Level Validation** — Syntax (RDF/OWL), SHACL constraints, and SPARQL consistency checks
- 🏗️ **6 Projection Targets** — Generate downstream artifacts from a single ontology source
- 🥈 **Silver Layer DDL** — Full CREATE TABLE generation with SCD2, GDPR satellites, junction tables, and ERD diagrams
- 📦 **Hub Scaffolding** — `kairos init` bootstraps a complete ontology repository in seconds
- 🤖 **AI Chat Service** — FastAPI + GitHub Copilot SDK for conversational ontology management
- 🔗 **Traceability** — Every generated artifact links back to its source ontology IRI and version
- 🌐 **Multi-Domain** — Each domain deploys independently with domain-scoped output folders

## 🚀 Quick Start

```bash
# Install
pip install kairos-ontology-toolkit

# Validate your ontologies
python -m kairos_ontology validate --all

# Generate all projections
python -m kairos_ontology project --target all
```

To scaffold a brand-new ontology hub repository:

```bash
python -m kairos_ontology init my-ontology-hub
```

## 🎯 Projection Targets

| Target | Output | Use Case |
|--------|--------|----------|
| **silver** | `CREATE TABLE` DDL, `ALTER TABLE`, Mermaid ERD + SVG | Data warehouse physical layer |
| **dbt** | SQL models + `schema.yml` | dbt-based transformation pipelines |
| **neo4j** | Cypher `CREATE` statements | Knowledge graph databases |
| **azure-search** | JSON index definitions | Azure AI Search |
| **a2ui** | JSON Schema messages | UI generation / form builders |
| **prompt** | JSON context documents | LLM prompt engineering |

Each target produces per-domain output — deploy and version domains independently.

## 🏛️ Architecture

```
kairos-ontology-toolkit/
├── src/kairos_ontology/           # Core toolkit (pip-installable)
│   ├── cli/                       # Click CLI (validate, project, init)
│   ├── projections/               # 6 projection generators
│   ├── templates/                 # Jinja2 output templates
│   ├── validator.py               # 3-level validation pipeline
│   └── projector.py               # Projection orchestrator
├── service/                       # FastAPI REST API + AI chat
│   ├── app/routers/               # Endpoints: ontology, validate, project, chat
│   └── app/services/              # GitHub integration, Copilot SDK
├── tests/                         # pytest test suite (172+ tests)
└── docker-compose.yml             # One-command service deployment
```

## 🌐 Web Service

The toolkit ships with a FastAPI service for REST-based ontology management and an
AI chat interface powered by the GitHub Copilot SDK.

```bash
# Docker (production)
docker compose up --build

# Local dev mode (no GitHub App required)
KAIROS_DEV_MODE=true uvicorn service.app.main:app --reload
```

Key endpoints: `/api/validate`, `/api/project`, `/api/ontology/query`, `/api/chat`

➡️ See the [User Guide — Service section](docs/USER_GUIDE.md) for full endpoint
documentation and setup instructions.

## 📂 Hub Repository Structure

When you run `kairos init`, you get:

```
my-ontology-hub/
├── ontologies/           # Your domain ontologies (.ttl)
├── shapes/               # SHACL validation shapes
├── reference-models/     # External ontologies + XML catalog
└── output/               # Generated projections (per target, per domain)
    ├── silver/  dbt/  neo4j/  azure-search/  a2ui/  prompt/
```

➡️ See the [User Guide](docs/USER_GUIDE.md) for namespace conventions, multi-domain
architecture, and detailed examples.

## 🛠️ Development

```bash
git clone https://github.com/Cnext-eu/kairos-ontology-toolkit.git
cd kairos-ontology-toolkit
pip install -e ".[dev]"
python -m pytest                   # 172+ tests
```

[Poetry](https://python-poetry.org/) is used for packaging and releases.
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

## 📄 License

Licensed under the **Apache License, Version 2.0** — see [LICENSE](LICENSE) for details.

Copyright 2026 [Cnext.eu](https://cnext.eu) — Built with ❤️ as part of the
**Kairos Community Edition**.