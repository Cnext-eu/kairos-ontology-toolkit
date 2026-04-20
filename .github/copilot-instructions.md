---
applyTo: "**"
---

# Kairos Ontology Toolkit — Copilot Instructions

## Project overview

This is a Python toolkit + FastAPI service for managing OWL/Turtle ontologies.
It provides validation (syntax + SHACL), multi-target projections (dbt, neo4j,
azure-search, a2ui, prompt), and an AI chat interface via the GitHub Models API.

## Code conventions

- Python 3.12+, src-layout (`src/kairos_ontology/`).
- Line length: 100 characters (black + ruff).
- Use `rdflib.Graph` for all RDF operations. Never serialize RDF by string concatenation.
- Async endpoints in FastAPI routers; sync helpers in the core toolkit.
- Service code lives under `service/app/`.
- Tests live under `tests/` (toolkit) and `tests/service/` (API endpoints).

## Testing rules

- **Every new function, service, or endpoint MUST have unit tests.**
- Toolkit tests go in `tests/`, service/API tests go in `tests/service/`.
- Mock external calls (GitHub API, OpenAI client) with `unittest.mock` — never hit real APIs in tests.
- Use `pytest-asyncio` with `asyncio_mode = "auto"` for async test functions.
- Run tests with `py -m pytest` (Windows) or `python -m pytest` (Unix).
- Aim for coverage of: happy path, auth failure (401), and at least one edge/error case per endpoint.

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

Available targets: `dbt`, `neo4j`, `azure-search`, `a2ui`, `prompt`, `silver`.
Each ontology domain produces separate output artifacts per target.

## Scaffold packaging rules

The scaffold folder `src/kairos_ontology/scaffold/` is what gets distributed to hub repos
via `init`, `new-repo`, and `update`. Any change in this repo that affects hub repos MUST
also be applied to the corresponding scaffold location:

| What changed | Scaffold location to update |
|---|---|
| New or updated Copilot skill in `.github/skills/` | `src/kairos_ontology/scaffold/skills/<skill-name>/SKILL.md` |
| New output target directory | Add to the `for d in [...]` directory lists in `cli/main.py` |
| New scaffold template / config file | `src/kairos_ontology/scaffold/ontology-hub/` or `src/kairos_ontology/scaffold/` |

**Rule**: After adding or modifying a skill in `.github/skills/`, always copy it to
`src/kairos_ontology/scaffold/skills/` before committing. Run `py -m pytest` to confirm
no packaging tests break.
