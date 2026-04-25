# Kairos Ontology Toolkit — Copilot Instructions

## Session greeting (MANDATORY)

**IMPORTANT:** On the VERY FIRST response of every new conversation, ALWAYS start
by displaying the welcome message below BEFORE addressing the user's question.
This applies even if the user's first message is a direct question — greet first,
then answer.

### Welcome message

> 👋 Welcome to the **Kairos Ontology Toolkit** — an ontology-driven platform that
> generates data pipelines, BI models, search indexes, and more from OWL/Turtle
> domain models.
>
> **New here?** Invoke the **kairos-help** skill for a full orientation — it covers
> the shift-left design philosophy, hub folder structure, available projections,
> CLI commands, and best practices.

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

## Open-source & licensing

This project is **open source** under the **Apache License 2.0**, part of the
**Kairos Community Edition** by Cnext.eu.

### SPDX headers (mandatory)

Every `.py` file MUST start with these two lines:

```python
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
```

When creating a new Python file, always include the SPDX header as the very
first lines, before any docstrings or imports.

### PR / code-review checklist (open-source)

When reviewing or creating a pull request, verify:

| Check | What to look for |
|-------|-----------------|
| **SPDX headers** | Every new or modified `.py` file has the `SPDX-License-Identifier` + `Copyright` header |
| **No secrets** | No API keys, tokens, passwords, or internal URLs in code, config, or comments |
| **No PII** | No personal data (names, emails, addresses) in ontology labels, test fixtures, or comments |
| **Dependency licenses** | New dependencies must be compatible with Apache 2.0 (BSD, MIT, Apache, ISC are OK; GPL is NOT) |
| **DCO sign-off** | Contributor commits should have `Signed-off-by:` trailer (enforced by convention) |
| **NOTICE file** | If adding a bundled third-party component, update `NOTICE` with attribution |
| **No proprietary content** | Ontology examples, sample data, and docs must not contain client-specific or proprietary information |

### Key open-source files

| File | Purpose |
|------|---------|
| `LICENSE` | Apache License 2.0 full text |
| `NOTICE` | Required attribution file (Apache 2.0 §4d) |
| `CONTRIBUTING.md` | Contribution guidelines + DCO workflow |
| `CODE_OF_CONDUCT.md` | Contributor Covenant v2.1 |
| `SECURITY.md` | Vulnerability reporting policy |
| `CHANGELOG.md` | Release history |

## Dev toolchain

- **Poetry** manages dependencies and builds the package. It must be installed separately
  on the developer's machine — it is NOT a pip dependency.
  Install: `(Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | python -`
  or `pipx install poetry`.
- Run tests with `py -m pytest` (Windows) — Poetry's venv is not required for tests if
  dependencies are already installed via pip.

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

Available targets: `dbt`, `neo4j`, `azure-search`, `a2ui`, `prompt`, `silver`, `powerbi`, `report`.
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
| New core functionality (projections, annotations, CLI commands) | Update `kairos-help` skill in `.github/skills/kairos-help/` + scaffold copy |

**Rule**: After adding or modifying a skill in `.github/skills/`, always copy it to
`src/kairos_ontology/scaffold/skills/` before committing. Run `py -m pytest` to confirm
no packaging tests break.
