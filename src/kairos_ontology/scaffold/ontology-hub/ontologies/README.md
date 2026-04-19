# Ontologies

This directory contains OWL/Turtle domain ontology files. Each `.ttl` file
represents one independently deployable data domain.

## Conventions

- One domain per file (e.g., `customer.ttl`, `order.ttl`).
- Filename becomes the domain identifier.
- Every file must declare an `owl:Ontology` with `rdfs:label` and `owl:versionInfo`.
- Classes use PascalCase, properties use camelCase.

## Commands

```bash
# Validate all ontologies
kairos-ontology validate

# Generate projection artifacts
kairos-ontology project
```
