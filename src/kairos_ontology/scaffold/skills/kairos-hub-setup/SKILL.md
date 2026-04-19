---
name: kairos-hub-setup
description: >
  Guide for setting up a new ontology hub repository.
  Covers folder structure, starter ontologies, SHACL shapes, and projections.
---

# Hub Setup Skill

You guide users through setting up a new Kairos ontology hub.

## Standard hub structure

A Kairos ontology hub is a GitHub repository with this layout:

```
.
├── ontology-hub/                        # Main ontology workspace
│   ├── ontologies/                      # Domain ontologies (Turtle/RDF)
│   │   ├── customer.ttl
│   │   ├── product.ttl
│   │   ├── order.ttl
│   │   └── README.md
│   ├── shapes/                          # SHACL validation constraints
│   │   ├── customer.shacl.ttl
│   │   ├── product.shacl.ttl
│   │   ├── order.shacl.ttl
│   │   └── README.md
│   ├── mappings/                        # SKOS synonym mappings
│   │   ├── schema-org.ttl               # Schema.org alignments
│   │   └── README.md
│   └── output/                          # Generated projections (gitignored)
│       ├── dbt/                         # Data Build Tool SQL models
│       ├── neo4j/                       # Cypher graph schemas
│       ├── azure-search/                # Azure AI Search indexes
│       ├── a2ui/                        # JSON Schema for UIs
│       └── prompt/                      # LLM prompt contexts
├── ontology-reference-models/           # Reference ontologies submodule (sparse)
│   ├── authoritative-ontologies/        # FIBO and other authoritative ontologies
│   ├── derived-ontologies/              # Supply-chain, DCSA, MMT derived models
│   └── catalog-v001.xml                 # OASIS XML catalog for import resolution
```

## Setup steps

1. **Install the toolkit** — `pip install kairos-ontology-toolkit`
2. **Run init** — `kairos-ontology init --domain customer` scaffolds the full structure.
3. **Choose a domain name** — e.g., "customer", "order", "product". Each domain gets its own .ttl file.
4. **Define the namespace** — Use a descriptive HTTP URI: `http://{org}.example.org/ontology/{domain}#`
5. **Create the ontology file** — Must include:
   - `owl:Ontology` declaration with `rdfs:label` and `owl:versionInfo`
   - At least one `owl:Class` with label and comment
   - Properties with domain, range, and label
6. **Validate** — Run syntax + SHACL validation before committing.
7. **Generate projections** — Run projections to verify the ontology produces usable artifacts.

## Multi-domain architecture

- Each .ttl file = one independently deployable domain.
- Domains can reference each other via `owl:imports`.
- Keep domains small and focused (5-15 classes per domain).
- Different teams can own different domains.

## Naming the ontology file

The filename becomes the domain identifier:
- `customer.ttl` → domain "customer"
- `sales-order.ttl` → domain "sales-order"
- Use lowercase with hyphens for multi-word names.

## First-time checklist

- [ ] Run `kairos-ontology init --domain <name>`
- [ ] Edit `ontology-hub/ontologies/<name>.ttl` — add classes and properties
- [ ] Validate (syntax should pass): `kairos-ontology validate`
- [ ] Generate prompt projection: `kairos-ontology project --target prompt`
- [ ] Optionally add SHACL shapes in `ontology-hub/shapes/`
- [ ] Optionally add SKOS mappings in `ontology-hub/mappings/`
- [ ] Commit on a feature branch, open PR for review
