---
name: kairos-hub-setup
description: >
  Guide for setting up a new ontology hub repository.
  Covers folder structure, starter ontologies, SHACL shapes, and projections.
---

# Hub Setup Skill

You guide users through setting up a new Kairos ontology hub.

> **IMPORTANT:** Always use the `python -m kairos_ontology` CLI commands to scaffold
> the hub structure.  Do NOT manually create directories, READMEs, .gitignore,
> skills, or other scaffold files — the CLI handles all of this automatically.

## How hubs are created

Hub repos are created using `kairos-ontology new-repo` (see the
kairos-quickstart skill).  The `init` command then scaffolds the hub
structure and adds domains inside an existing repo.

## Standard hub structure

```
<name>-ontology-hub/
├── .github/
│   ├── copilot-instructions.md
│   ├── skills/                          # AI skills for Copilot
│   └── workflows/managed-check.yml
├── ontology-hub/
│   ├── README.md                        # Company context + domain overview
│   ├── model/                           # Domain model (ontology-centric)
│   │   ├── ontologies/
│   │   │   ├── _master.ttl              # Master ontology (imports all domains)
│   │   │   ├── customer.ttl
│   │   │   └── README.md
│   │   ├── shapes/                      # SHACL validation constraints
│   │   │   └── README.md
│   │   ├── extensions/                  # *-silver-ext.ttl projection annotations
│   │   └── mappings/                    # Source-to-silver SKOS + kairos-map: mappings
│   │       └── README.md                #   (also ontology alignment to external standards)
│   ├── integration/                     # Source system integration
│   │   └── sources/                     # Source system reference docs + bronze vocab
│   │       ├── README.md
│   │       └── source-system-template/  # Template for new source systems
│   └── output/                          # All projection outputs (committed)
│       ├── medallion/
│       │   ├── silver/                  # Silver DDL/ERD
│       │   ├── gold/                    # Gold dimensional models
│       │   └── dbt/                     # dbt models (bronze → silver)
│       ├── neo4j/
│       ├── azure-search/
│       ├── a2ui/
│       └── prompt/
├── ontology-reference-models/           # Git submodule (sparse checkout)
│   ├── authoritative-ontologies/
│   ├── derived-ontologies/
│   └── catalog-v001.xml
├── .gitignore
├── pyproject.toml                       # kairos-ontology-toolkit dependency
└── README.md
```

## Adding a domain with `init`

```bash
python -m kairos_ontology init --company-domain contoso.com --domain customer
```

- `--company-domain` (required) — sets namespace base: `https://contoso.com/ont/`
- `--domain` (optional) — creates a starter `.ttl` file
- Also creates `ontology-hub/README.md` and `_master.ttl` if they don't exist

The first `init` after `new-repo` can be done on `main` (initial setup).
After that, always use a feature branch.

## Multi-domain architecture

- Each `.ttl` file = one independently deployable domain.
- Domains can reference each other via `owl:imports`.
- Keep domains small and focused (5–15 classes per domain).
- Different teams can own different domains.

## Naming the ontology file

The filename becomes the domain identifier:
- `customer.ttl` → domain "customer"
- `sales-order.ttl` → domain "sales-order"
- Use lowercase with hyphens for multi-word names.

## Adding a new domain checklist

- [ ] Create a feature branch (`ontology/<domain-name>`)
- [ ] Run `python -m kairos_ontology init --company-domain <domain> --domain <name>`
- [ ] Edit `ontology-hub/model/ontologies/<name>.ttl` — add classes and properties
- [ ] Update domain overview table in `ontology-hub/README.md`
- [ ] Add `owl:imports` to `ontology-hub/model/ontologies/_master.ttl`
- [ ] Validate: `python -m kairos_ontology validate`
- [ ] Generate projections: `python -m kairos_ontology project --target prompt`
- [ ] (Optional) Generate silver layer: add `*-silver-ext.ttl` in `ontology-hub/model/extensions/`, then `python -m kairos_ontology project --target silver`
- [ ] (Optional) Add source system docs in `ontology-hub/integration/sources/` and generate bronze vocab with **kairos-medallion-staging** skill
- [ ] (Optional) Create source-to-silver mappings in `ontology-hub/model/mappings/{system-name}/` (SKOS + `kairos-map:`) and run **kairos-medallion-projection** skill for dbt models
- [ ] Optionally add SHACL shapes in `ontology-hub/model/shapes/`
- [ ] Commit, push, and open PR to merge into main
