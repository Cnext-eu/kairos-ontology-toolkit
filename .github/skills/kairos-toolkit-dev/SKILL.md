---
name: kairos-toolkit-dev
description: Develop and test the Kairos v5 toolkit, compiler, CLI, scaffold, and projections.
---

# Toolkit Development

Kairos is Python 3.12+ with a src layout. Core code is under `src/kairos_ontology/core`, CLI command
modules under `src/kairos_ontology/cli`, MDM under `src/kairos_ontology/mdm`, service code under
`service/app`, and tests under `tests`.

## Architecture

- Closed EntityBinding YAML is the sole source-to-canonical execution authority.
- `core/compiler` resolves authored inputs and returns one immutable, graph-free `CompilePlan`.
- Check, explain, emit, Gold, and MDM consume the same plan; do not add alternate resolution paths.
- Complex relational inputs are ordinary contracted dbt models.
- Core never imports MDM. Register optional consumers without reversing this dependency.
- Use rdflib for RDF and Jinja/templates or typed renderers for output.

## Change workflow

1. Inspect the relevant implementation and focused tests.
2. Make surgical changes. Every modified/new Python file needs Apache-2.0 SPDX and Cnext.eu
   copyright headers.
3. Add happy-path and edge/error tests; mock external APIs.
4. For compiler/projection behavior, add scenario coverage and verify deterministic paths/bytes.
5. For a skill change, edit both `.github/skills/<name>/SKILL.md` and
   `src/kairos_ontology/scaffold/skills/<name>/SKILL.md` identically.
6. For managed scaffold behavior, update scaffold sources and managed mappings/tests.
7. Run focused pytest, then scaffold sync/reference/managed tests when those surfaces change.

Use `uv sync`, `uv run pytest`, and `uv build`. Keep lines to 100 characters. Significant
architecture changes require a design-decision update. Releases update the single package version,
changelog, lock, build artifacts, tag, and GitHub workflow verification through
`kairos-toolkit-ops`.
