# Kairos Ontology Toolkit — Copilot Instructions

## Session greeting (mandatory)

On the first response of every conversation, display this before answering:

> 👋 Welcome to the **Kairos Ontology Toolkit** — an ontology-driven platform that
> generates data pipelines, BI models, search indexes, and more from OWL/Turtle
> domain models.
>
> **New here?** Invoke **kairos-help** for an orientation.
>
> **Returning?** I can run a read-only hub diagnostic with **kairos-diagnose-status**.

## V5 architecture

Kairos v5 is stateless and has one source-to-canonical execution authority:

```text
model/ontologies/<domain>.ttl
model/shapes/
integration/discovery/
integration/sources/<source>/
integration/bindings/<source>-to-<domain>.binding.yaml
integration/transforms/dbt/models/
kairos.yaml
../ontology-hub-publish/
```

- OWL defines canonical meaning; source TTL defines physical relations and columns.
- A closed `EntityBinding` YAML document defines one canonical entity from one source relation or
  one ordinary contracted dbt model. Unknown fields and duplicate YAML keys are errors.
- Complex joins, windows, aggregations, JSON expansion, fallback logic, or grain changes belong in
  ordinary dbt SQL plus an enforced dbt properties contract, referenced by `source.dbtModel`.
- `compile` builds one immutable, graph-free `CompilePlan`. Check, explain, emit, Gold, and MDM
  consume this plan; they must not independently resolve or rebuild canonical Silver/dbt inputs.
- `../ontology-hub-publish/` (a sibling of the hub) is derived. Never hand-edit compiler-owned artifacts.
- V5 is a clean authoring break. Create older hubs again from fresh; do not invent compatibility.

Canonical commands:

```powershell
kairos-ontology compile <domain> --check --format json
kairos-ontology compile <domain> --explain --format json
kairos-ontology compile <domain> --emit
```

Passing compilation does not replace downstream dbt, adapter, deployment, security, or data tests.

## Code conventions

- Python 3.12+, src layout under `src/kairos_ontology/`, 100-character lines.
- Core ontology/compiler code lives in `kairos_ontology.core`; design-time MDM lives in
  `kairos_ontology.mdm`. MDM may import core; core must never import MDM.
- Public APIs are re-exported from `kairos_ontology/__init__.py`.
- Use `rdflib.Graph` for RDF. Never serialize RDF by string concatenation.
- Every new or modified `.py` file starts with:

  ```python
  # SPDX-License-Identifier: Apache-2.0
  # Copyright 2026 Cnext.eu
  ```

- Tests live under `tests/`. New behavior needs a happy-path and error/edge test.
- Mock external APIs. Use pytest-asyncio for async tests.
- Run with uv: `uv sync`, `uv run pytest`, `uv run kairos-ontology ...`.

## Ontology conventions

- Every ontology declares `owl:Ontology`, `rdfs:label`, and `owl:versionInfo`.
- Use HTTP(S) namespaces. Classes are PascalCase; properties are camelCase.
- Every class has a label and comment. Every property has domain, range, and label.
- Validate syntax before applying ontology changes.
- Never modify `main` directly; use a feature branch and PR.

## Semantic access (DD-103)

- Never read `.ttl` files directly as raw text — an LLM cannot reliably reconstruct
  prefix-relative IRIs, transitively inherited properties across an `owl:imports` chain, or
  equivalence/inverse relationships from serialized Turtle. Use the CLI's semantic commands
  instead: `kairos-ontology resolve-ontology`, `kairos-ontology show-class-inventory`,
  `kairos-ontology explain-term`, `kairos-ontology list-class-properties`.
- `.claude/settings.json` denies `Read`/`Grep` on `model/ontologies/**/*.ttl`,
  `model/shapes/**/*.ttl`, and `ontology-reference-models/**/*.ttl` to enforce this for
  Claude Code sessions; other agents must follow the same rule voluntarily.

## Skill routing

| User intent | Skill |
|---|---|
| Start, continue, or determine next action | `kairos-flow` |
| Business context and terminology | `kairos-design-discovery` |
| Import, document, or analyse source schemas | `kairos-design-source` |
| Create or change OWL classes/properties | `kairos-design-domain` |
| Author source-to-canonical EntityBinding YAML | `kairos-design-mapping` |
| Create a complex contracted dbt model | `kairos-develop-dbt-transformation` |
| Design Gold/Power BI products | `kairos-design-gold` |
| Design MDM policy | `kairos-design-mdm` |
| Validate ontology and compile diagnostics | `kairos-execute-validate` |
| Compile or generate artifacts | `kairos-execute-project` |
| Review bindings and compiler explanation | `kairos-execute-report` |
| Detailed read-only hub diagnostic | `kairos-diagnose-status` |
| Create a fresh hub | `kairos-setup-init` |
| Configure a hub | `kairos-setup-config` |
| Create or consume a dataplatform | `kairos-setup-dataplatform`, `kairos-package-dataplatform` |
| Update toolkit/managed files/reference models or release toolkit | `kairos-toolkit-ops` |
| Toolkit development | `kairos-toolkit-dev` |

Always invoke the owning skill before a skill-managed command or authored design change. Set
`KAIROS_SKILL_CONTEXT=1` only while a skill legitimately wraps a command.

## Design interaction

Discovery, source, ontology, mapping, dbt transformation, Gold, and MDM design are interactive by
default. An explicit fleet override applies only to the active skill invocation and expires when it
ends or pauses. Fleet mode keeps all validation and evidence checks, records each AI-approved choice
with rationale, confidence, and references, and stops for ambiguity, low confidence, sensitive or
proprietary data, policy choices, and destructive actions.

## Validation and tests

- `validate_content()` returns syntax and SHACL result sections.
- Run the smallest focused tests first; projection/compiler changes require scenario coverage.
- EntityBinding/compiler changes should run `tests/scenarios/test_scenario_v5.py` and relevant
  compiler tests.
- Skill or instruction changes must keep `.github/skills/<name>/SKILL.md` byte-identical to
  `src/kairos_ontology/scaffold/skills/<name>/SKILL.md` and run scaffold sync/managed tests.

## Scaffold and open-source checks

Changes affecting hub repositories must also update `src/kairos_ontology/scaffold/`. Keep both
Copilot instruction copies byte-identical. Architectural changes update
`docs/design/toolkit-design-decisions.md`.

Before a PR, verify SPDX headers, no secrets or PII, Apache-2.0-compatible dependencies, NOTICE for
bundled third-party components, no proprietary examples, DCO sign-off, and issue-closing keywords in
the PR body for fully fixed issues.
