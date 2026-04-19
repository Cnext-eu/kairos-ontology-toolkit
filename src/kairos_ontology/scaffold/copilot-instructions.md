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
│   ├── ontologies/                      # Domain ontologies (Turtle/RDF)
│   ├── shapes/                          # SHACL validation constraints
│   ├── mappings/                        # SKOS synonym mappings
│   └── output/                          # Generated projections (gitignored)
│       ├── dbt/ neo4j/ azure-search/ a2ui/ prompt/
├── ontology-reference-models/           # Reference ontologies
│   ├── authoritative-ontologies/        # FIBO and other authoritative ontologies
│   ├── derived-ontologies/              # Supply-chain, DCSA, MMT derived models
│   └── catalog-v001.xml                 # OASIS XML catalog for import resolution
```

## Available CLI commands

```bash
# Validate all ontologies (syntax + SHACL)
kairos-ontology validate

# Validate syntax only
kairos-ontology validate --syntax

# Generate all projections
kairos-ontology project

# Generate a specific projection target
kairos-ontology project --target prompt

# Test catalog import resolution
kairos-ontology catalog-test --catalog ontology-reference-models/catalog-v001.xml
```

## Ontology conventions

- All ontology files use Turtle (.ttl) syntax and live in `ontology-hub/ontologies/`.
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
- SHACL shapes live in `ontology-hub/shapes/` and are optional.
- Run `kairos-ontology validate` to check all ontologies.

## Projection targets

Available targets: `dbt`, `neo4j`, `azure-search`, `a2ui`, `prompt`.
Each ontology domain produces separate output artifacts per target.
Output is generated into `ontology-hub/output/`.

## Workflow

**Always create a feature branch before making changes.** Never commit
directly to `main`.  Use the SC-feature-branch skill to create one.

1. Create a feature branch (e.g., `ontology/add-order-domain`).
2. Read `ontology-hub/README.md` for company context and domain model overview.
3. Check the domain model overview table before creating new `.ttl` files.
4. Create or modify `.ttl` files in `ontology-hub/ontologies/`.
5. Update `ontology-hub/ontologies/_master.ttl` with `owl:imports` for any new domain.
6. Run `kairos-ontology validate` to check for errors.
7. Run `kairos-ontology project` to regenerate artifacts.
8. Commit changes, push, and open a PR to merge into `main`.
