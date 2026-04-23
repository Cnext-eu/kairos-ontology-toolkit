---
applyTo: "**"
---

# Kairos Ontology Hub — Copilot Instructions

## Project overview

This is a Kairos ontology hub repository. It contains OWL/Turtle domain ontologies
that are validated and projected into downstream artifacts using the
**kairos-ontology-toolkit** CLI.

## Repository structure

```
├── ontology-hub/                        # Main ontology workspace
│   ├── catalog-v001.xml                 # Local URI → file catalog (auto-chains to reference-models)
│   ├── model/                           # Domain model (ontology-centric)
│   │   ├── ontologies/                  # Domain ontologies (Turtle/RDF)
│   │   ├── shapes/                      # SHACL validation constraints
│   │   ├── extensions/                  # Projection annotations (*-silver-ext.ttl)
│   │   └── mappings/                    # SKOS mappings (per source system subfolder)
│   │       └── {system-name}/           # e.g. adminpulse-to-party.ttl
│   ├── integration/                     # Source system integration
│   │   └── sources/                     # Source system reference docs + bronze vocab
│   │       └── {system-name}/           # Per-system: API specs, SQL DDL, *.vocabulary.ttl
│   └── output/                          # Projection outputs (committed)
│       ├── medallion/                   # Medallion architecture outputs
│       │   ├── silver/                  # Silver canonical DDL / ERD
│       │   ├── gold/                    # Gold dimensional models
│       │   └── dbt/                     # dbt models (bronze → silver)
│       ├── neo4j/ azure-search/ a2ui/ prompt/
│       └── report/                    # HTML mapping reports (per source system)
├── ontology-reference-models/           # Reference ontologies
│   ├── authoritative-ontologies/        # FIBO and other authoritative ontologies
│   ├── derived-ontologies/              # Supply-chain, DCSA, MMT derived models
│   └── catalog-v001.xml                 # OASIS XML catalog for import resolution
```

## Available CLI commands

```bash
# Validate all ontologies (syntax + SHACL)
python -m kairos_ontology validate

# Validate syntax only
python -m kairos_ontology validate --syntax

# Generate all projections
python -m kairos_ontology project

# Generate a specific projection target
python -m kairos_ontology project --target prompt

# Generate silver layer DDL + ERD (requires *-silver-ext.ttl)
python -m kairos_ontology project --target silver

# Test catalog import resolution
python -m kairos_ontology catalog-test --catalog ontology-reference-models/catalog-v001.xml
```

## Ontology conventions

- All ontology files use Turtle (.ttl) syntax and live in `ontology-hub/model/ontologies/`.
- Every ontology MUST declare an `owl:Ontology` with `rdfs:label` and `owl:versionInfo`.
- Use HTTPS namespaces following the pattern in `ontology-hub/README.md`:
  `https://<company-domain>/ont/<domain>#`.
- Read `ontology-hub/README.md` for company context, namespace base, and domain overview.
- Every `owl:Class` must have `rdfs:label` and `rdfs:comment`.
- Every property must have `rdfs:domain`, `rdfs:range`, and `rdfs:label`.
- Naming: PascalCase for classes, camelCase for properties.
- One domain per .ttl file (e.g., `customer.ttl`, `order.ttl`).

## Validation rules

- Always validate syntax before committing changes.
- SHACL shapes live in `ontology-hub/model/shapes/` and are optional.
- Run `kairos-ontology validate` to check all ontologies.

## Projection targets

Available targets: `dbt`, `neo4j`, `azure-search`, `a2ui`, `prompt`, `silver`, `report`.
Each ontology domain produces separate output artifacts per target.
Output is generated into `ontology-hub/output/`.

For the **silver** target (MS Fabric / Delta Lake DDL + Mermaid ERD), first create
a `{domain}-silver-ext.ttl` annotation file in `ontology-hub/model/extensions/` using the
**kairos-medallion-silver** skill.

For the **dbt** target (medallion bronze-to-silver pipeline), first populate
`ontology-hub/integration/sources/` with reference docs, generate bronze vocabulary using the
**kairos-medallion-staging** skill, then create SKOS mappings and run the
**kairos-medallion-projection** skill.

For the **report** target (HTML mapping coverage reports), ensure source vocabularies
and SKOS mappings exist, then run `project --target report`.  Reports go to
`output/report/{system}-mapping-report.html`.  Use the **kairos-mapping-report** skill.

## Workflow

**Always create a feature branch before making changes.** Never commit
directly to `main`.  Use the SC-feature-branch skill to create one.

1. Create a feature branch (e.g., `ontology/add-order-domain`).
2. Read `ontology-hub/README.md` for company context and domain model overview.
3. Check the domain model overview table before creating new `.ttl` files.
4. Create or modify `.ttl` files in `ontology-hub/model/ontologies/`.
5. Update `ontology-hub/model/ontologies/_master.ttl` with `owl:imports` for any new domain.
6. Run `python -m kairos_ontology validate` to check for errors.
7. Run `python -m kairos_ontology project` to regenerate artifacts.
8. Commit changes, push, and open a PR to merge into `main`.
