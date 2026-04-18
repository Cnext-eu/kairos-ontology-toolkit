---
name: hub-setup
description: >
  Guide for setting up a new ontology hub repository.
  Covers folder structure, starter ontologies, SHACL shapes, and projections.
---

# Hub Setup Skill

You guide users through setting up a new Kairos ontology hub.

## Standard hub structure

A Kairos ontology hub is a GitHub repository with this layout:

```
my-ontology-hub/
├── ontologies/           # OWL/Turtle domain ontologies
│   ├── customer.ttl
│   ├── order.ttl
│   └── product.ttl
├── shapes/               # SHACL validation shapes (optional)
│   ├── customer.shacl.ttl
│   └── order.shacl.ttl
├── reference-models/     # External ontologies (FIBO, Schema.org)
│   ├── catalog-v001.xml  # Import resolution catalog
│   └── fibo/
└── output/               # Generated projection artifacts
    ├── dbt/
    ├── neo4j/
    ├── azure-search/
    ├── a2ui/
    └── prompt/
```

## Setup steps

1. **Choose a domain name** — e.g., "customer", "order", "product". Each domain gets its own .ttl file.
2. **Define the namespace** — Use a descriptive HTTP URI: `http://{org}.example.org/ontology/{domain}#`
3. **Create the ontology file** — Must include:
   - `owl:Ontology` declaration with `rdfs:label` and `owl:versionInfo`
   - At least one `owl:Class` with label and comment
   - Properties with domain, range, and label
4. **Validate** — Run syntax + SHACL validation before committing.
5. **Generate projections** — Run projections to verify the ontology produces usable artifacts.

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

- [ ] Create `ontologies/` directory
- [ ] Create first domain .ttl file with ontology declaration
- [ ] Add at least one class with properties
- [ ] Validate (syntax should pass)
- [ ] Generate prompt projection to verify structure
- [ ] Optionally add SHACL shapes for constraints
- [ ] Commit on a feature branch, open PR for review
