---
applyTo: "**"
---

# Kairos Ontology Toolkit — Copilot Instructions

## Project overview

This is a Python toolkit + FastAPI service for managing OWL/Turtle ontologies.
It provides validation (syntax + SHACL), multi-target projections (dbt, neo4j,
azure-search, a2ui, prompt), and an AI chat interface via the GitHub Copilot SDK.

## Code conventions

- Python 3.12+, src-layout (`src/kairos_ontology/`).
- Line length: 100 characters (black + ruff).
- Use `rdflib.Graph` for all RDF operations. Never serialize RDF by string concatenation.
- Async endpoints in FastAPI routers; sync helpers in the core toolkit.
- Service code lives under `service/app/`.
- Tests live under `tests/` (toolkit) and `tests/service/` (API endpoints).

## Ontology conventions

- All ontology files use Turtle (.ttl) syntax.
- Every ontology MUST declare an `owl:Ontology` with `rdfs:label` and `owl:versionInfo`.
- Use HTTP/HTTPS namespaces with `#` or `/` separator.
- Every `owl:Class` must have `rdfs:label` and `rdfs:comment`.
- Every property must have `rdfs:domain`, `rdfs:range`, and `rdfs:label`.
- Naming: PascalCase for classes, camelCase for properties.
- Never modify `main` branch directly — always use feature branches + PRs.

## Validation rules

- Always validate syntax before applying changes.
- SHACL shapes live in `shapes/` and are optional.
- `validate_content()` returns `{"syntax": {"passed": bool}, "shacl": {"passed": bool}}`.

## Projection targets

Available targets: `dbt`, `neo4j`, `azure-search`, `a2ui`, `prompt`.
Each ontology domain produces separate output artifacts per target.
