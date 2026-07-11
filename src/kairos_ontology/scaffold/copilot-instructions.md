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
>
> **Returning?** Would you like me to run a **hub status check** to see where things
> stand? _(invokes the kairos-diagnose-status skill)_

## Project overview

This is a Python toolkit for managing OWL/Turtle ontologies.
It provides validation (syntax + SHACL), multi-target projections (dbt, neo4j,
azure-search, a2ui, prompt), and CLI-based ontology management.

## Code conventions

- Python 3.12+, src-layout (`src/kairos_ontology/`).
- **Package split (MDM-DD-002):** ontology functionality lives in
  `kairos_ontology.core` (validator, projector, `core/projections/`, etc.); the
  design-time MDM layer lives in `kairos_ontology.mdm`. The boundary is **one-way** —
  `mdm` may import `core`, but `core` must **never** import `mdm` (enforced by
  `tests/test_layering.py`; MDM is wired via the projector registry, not a direct
  import). `cli/` depends on both. Public API is re-exported from top-level
  `kairos_ontology/__init__.py`.
- Line length: 100 characters (black + ruff).
- Use `rdflib.Graph` for all RDF operations. Never serialize RDF by string concatenation.
- Tests live under `tests/`.

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
| **Issue auto-close** | Every issue the PR **fully fixes** is referenced with a GitHub closing keyword (`Closes`/`Fixes`/`Resolves #NNN`) in the PR **body** (not just the title) so it auto-closes on merge; follow-up issues that should stay open are referenced as plain `#NNN` |
| **No secrets** | No API keys, tokens, passwords, or internal URLs in code, config, or comments |
| **No PII** | No personal data (names, emails, addresses) in ontology labels, test fixtures, or comments |
| **Design decisions** | If the PR introduces an architectural choice, update `docs/design/toolkit-design-decisions.md` |
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

- **[uv](https://docs.astral.sh/uv/)** manages the virtual environment and dependencies.
  Install: `irm https://astral.sh/uv/install.ps1 | iex` (Windows) or
  `curl -LsSf https://astral.sh/uv/install.sh | sh` (Linux/macOS).
- Run `uv sync` to create/refresh the `.venv` and install all dependencies.
- Run toolkit commands with `uv run kairos-ontology <command>`.
- Run tests with `uv run pytest` or activate the venv and run `py -m pytest`.

## Testing rules

- **Every new function or feature MUST have unit tests.**
- Tests live under `tests/`.
- Mock external calls (GitHub API, OpenAI client) with `unittest.mock` — never hit real APIs in tests.
- Use `pytest-asyncio` with `asyncio_mode = "auto"` for async test functions.
- Run tests with `py -m pytest` (Windows) or `python -m pytest` (Unix).
- Aim for coverage of: happy path and at least one edge/error case per feature.

### Scenario testing rules

The `tests/scenarios/` directory contains an **acme-hub** — a synthetic ontology hub with
two domains (`client`, `invoice`), two source systems, silver/gold extensions, and SKOS
mappings that exercise the full projection pipeline.

**When to update scenario tests:**

| What changed | What to update in `tests/scenarios/` |
|---|---|
| New `kairos-ext:` annotation in a projector | Add the annotation to the relevant `acme-hub/model/extensions/*.ttl` file and add/update a test in `test_scenario_silver.py` or `test_scenario_gold.py` |
| New `kairos-map:` annotation in dbt projector | Add the annotation to a mapping file in `acme-hub/model/mappings/` and add/update a test in `test_scenario_dbt.py` |
| Changed projection logic (SQL generation, column selection, joins) | Verify existing scenario tests still pass; add a new test case if the change covers a pattern not yet tested |
| New extension file type (e.g., a new `*-ext.ttl` convention) | Add the file to `acme-hub/model/extensions/` and add scenario coverage |
| Bug fix for a projection edge case | Add a regression test in the appropriate `test_scenario_*.py` that would have caught the bug |

**Rule**: PRs that add or change projection logic or extension annotations MUST include
corresponding scenario test updates. Run `py -m pytest tests/scenarios/ -v` to verify.

## Ontology conventions

- All ontology files use Turtle (.ttl) syntax.
- Every ontology MUST declare an `owl:Ontology` with `rdfs:label` and `owl:versionInfo`.
- Use HTTP/HTTPS namespaces with `#` or `/` separator.
- Every `owl:Class` must have `rdfs:label` and `rdfs:comment`.
- Every property must have `rdfs:domain`, `rdfs:range`, and `rdfs:label`.
- Naming: PascalCase for classes, camelCase for properties.
- Never modify `main` branch directly — always use feature branches + PRs.

### Modeling skill

When designing or modifying ontologies, use the **kairos-design-domain** skill.
It combines core modeling knowledge (class hierarchies, property design, naming
conventions, reference-model-first workflow, extension annotations) with an
interactive configurator (business alignment checkpoints, session persistence in
`ontology-hub/.kairos-state/phases/`, and structured validation gates). For minor
edits (adding a property, fixing a label) it supports a quick-edit mode that
skips checkpoints.

> **Modeling is a mid-lifecycle step, not the start.** The canonical lifecycle is
> `discovery → source → domain → mapping → silver → gold → validate → project`.
> `kairos-design-domain` is **data-first**: it needs imported, analysed sources as
> evidence (Gate 6 / Source Evidence Table). Treat **"start modeling"** as
> **"begin the modeling lifecycle"**:
> - **Fresh hub / no sources yet (`integration/sources/` empty)** → **auto-hand off
>   to the start of the lifecycle**: invoke **kairos-design-source** first (and offer
>   **kairos-design-discovery**) to import + `analyse-sources`, *then* return to
>   `kairos-design-domain`. Don't model classes against an empty
>   `integration/sources/`.
> - **Sources already exist** → before modeling, **always run an explicit
>   source-completeness check** (the modeling skill's mandatory pre-flight): list the
>   imported/analysed sources and ask whether *additional/other* sources need
>   importing first. This fires on the **first modeling pass too**, not only on
>   restart/extension. If more are needed → back to **kairos-design-source**, then
>   resume. Gate 6 remains the hard evidence constraint.

### Skill routing guide

Use this table to pick the correct skill for a user's intent:

> **Design vs Execute:** The design skills (`kairos-design-discovery`,
> `kairos-design-source`,
> `kairos-design-silver`, `kairos-design-gold`,
> `kairos-design-mapping`, `kairos-design-domain`) create/modify source files
> interactively. The **kairos-execute-project** skill **executes generation**
> from those files — it's the single entry point for producing output artifacts.
> Design first, then project. See DD-033 for the full lifecycle architecture.

> **Start of lifecycle:** the canonical order is
> `discovery → source → domain → mapping → silver → gold → validate → project →
> diagnose → consume` (see kairos-help §2). `kairos-design-domain` sits **after**
> discovery + source — it consumes imported, analysed source evidence. Treat
> "start modeling" as **entering the lifecycle**: on a fresh hub, **auto-hand off**
> to **kairos-design-source** (offer **kairos-design-discovery**) first; when
> sources already exist, run the modeling skill's mandatory **source-completeness
> check** (every time, including the first pass) before proposing classes.

| User intent | Correct skill |
|---|---|
| "Start / where are we / what's next / continue / resume" | **kairos-flow** (single entry point — reads deterministic status + continuation state, then hands off) |
| "Explore company / business model / capture business terminology" | **kairos-design-discovery** |
| "Model / design / create classes / add properties / extend ontology" | **kairos-design-domain** (= begin the modeling lifecycle: fresh hub → auto-hand off to kairos-design-source/discovery first; sources exist → mandatory source-completeness check, first pass included) |
| "Create a new hub repo from scratch" | **kairos-setup-init** |
| "Set up folder structure / configure hub" | **kairos-setup-config** |
| "How does Kairos work? / What is this?" | **kairos-help** |
| "Run projections / generate dbt / silver / gold" | **kairos-execute-project** |
| "Validate my ontology" | **kairos-execute-validate** |
| "Create source/bronze vocabulary" | **kairos-design-source** |
| "Design silver schema / FK annotations" | **kairos-design-silver** |
| "Design gold / Power BI model" | **kairos-design-gold** |
| "Design MDM policy / mastered concepts / match rules / survivorship" | **kairos-design-mdm** |
| "Import / extract TMDL or PBIP files" | CLI: `kairos-ontology import-tmdl` |
| "Analyse sources / pre-model domain contributions" | **kairos-design-source** (Phase 4) |
| "Import CSV/Excel flat files as source" | **kairos-design-source** (Phase 1) |
| "Release / upgrade / version check / update reference models" | **kairos-toolkit-ops** |
| "Map source columns to domain / create SKOS mappings" | **kairos-design-mapping** |
| "Status / progress / what's missing / where are we" | **kairos-flow** (start/continue) or **kairos-diagnose-status** (detailed read-only diagnostic). Both build on the deterministic `kairos-ontology status` CLI. |
| "Set up / scaffold a dataplatform dbt repo" | **kairos-setup-dataplatform** |
| "Import source schema / refresh vocabulary from bronze" | **kairos-design-source** (Phase 2) |
| "Generate coverage report" | CLI: `kairos-ontology coverage-report` |
| "Propose column-to-property alignment" | CLI: `kairos-ontology propose-alignment` |

### Skill-first enforcement (MANDATORY)

**NEVER run `kairos-ontology` CLI commands directly** when the action is covered by
a skill in the routing table above. Always invoke the corresponding skill instead.

Why: Skills contain pre-flight checks (file existence, annotation completeness),
interactive validation gates, and contextual guidance that raw CLI commands bypass.
Running CLI directly can produce incomplete or incorrect output without warning.

**Prohibited patterns:**
- ❌ `python -m kairos_ontology project --target silver` → use **kairos-execute-project** skill
- ❌ `python -m kairos_ontology project --target dbt` → use **kairos-execute-project** skill
- ❌ `python -m kairos_ontology project --target powerbi` → use **kairos-execute-project** skill
- ❌ `python -m kairos_ontology project --target mdm-profile` → use **kairos-execute-project** skill (author policy with **kairos-design-mdm**)
- ❌ `python -m kairos_ontology mdm-validate` → use **kairos-design-mdm** skill
- ❌ `python -m kairos_ontology validate` → use **kairos-execute-validate** skill
- ❌ `python -m kairos_ontology new-repo` → use **kairos-setup-init** skill
- ❌ Directly editing `.ttl` files without invoking the modeling/mapping skill

**Only exceptions:** The `import-tmdl` and `coverage-report`
commands have no corresponding skill and may be run directly via CLI.

**CLI soft skill-gate:** Skill-managed commands (`validate`, `project`, `init`,
`new-repo`, `migrate`, `update`, `update-refmodels`, `import-source`,
`import-flatfile`, `generate-staging`, `analyse-sources`, `mdm-validate`,
`init-dataplatform`)
emit a loud stderr warning when run directly, redirecting to the owning skill,
then still run (soft gate — see DD entry in the design-decisions log). When a
skill legitimately wraps one of these commands, it sets `KAIROS_SKILL_CONTEXT=1`
to silence the warning. If you see this warning, you bypassed a skill — stop and
invoke the named skill instead.

**If you are unsure which skill to use**, invoke **kairos-help** for guidance.

### Design mode policy (MANDATORY)

Design skills are **interactive by default**. They require explicit stakeholder
confirmation at checkpoints (naming alignment, mapping confirmation, annotation
review) unless the user explicitly requests **design fleet mode** for the current
task.

| Skill | Reason |
|-------|--------|
| **kairos-design-discovery** | Company facts and glossary terms must be confirmed by the user; web findings stay inferred until approved |
| **kairos-design-domain** | Hard gates require user naming confirmation before TTL generation |
| **kairos-design-mapping** | Every table→entity and column→property mapping needs explicit user approval |
| **kairos-design-silver** | Extension annotations (SCD types, natural keys, FK) need design review |
| **kairos-design-gold** | Gold measure definitions and star-schema design need stakeholder sign-off |
| **kairos-design-mdm** | MDM policy (match keys, survivorship, auto-action bounds, reference-data licensing) is governance-owned and reviewed before the profile is trusted |
| **kairos-design-source** | Source vocabulary descriptions need verification against source docs |

**Default:** when these skills are invoked, use **interactive mode** — present
proposals, wait for user confirmation, and proceed step-by-step.

**Opt-in design fleet mode:** only when the user explicitly asks for fleet,
autopilot, or AI-approved design decisions, the same seven design skills may run in
autopilot/autopilot-fleet mode for testing and acceleration. In fleet mode:

- Announce that design fleet mode is active and AI will make checkpoint decisions.
- Execute the same phases, pre-flight checks, evidence gates, validations, and
  skill routing as interactive mode; never skip quality gates to go faster.
- Record each AI-made checkpoint decision in the phase log or generated review
  output with rationale, confidence, and evidence references.
- Mark AI-approved business facts, glossary terms, mappings, ontology choices,
  silver annotations, and gold model choices as AI-approved, not user-confirmed.
- Stop and ask the user for ambiguity, low confidence, policy-sensitive choices,
  destructive/irreversible actions, or proprietary/PII risk.

## Validation rules

- Always validate syntax before applying changes.
- SHACL shapes live in `shapes/` and are optional.
- `validate_content()` returns `{"syntax": {"passed": bool}, "shacl": {"passed": bool}}`.

## Projection targets

Available targets: `dbt`, `neo4j`, `azure-search`, `a2ui`, `prompt`, `silver`, `powerbi`, `report`, `mdm-profile`.
Each ontology domain produces separate output artifacts per target.

> **Design-time MDM (`mdm-profile`):** an additive, opt-in projection target
> (not part of `--target all`) owned by the `kairos_ontology.mdm` package. It reads
> `model/extensions/{domain}-mdm-ext.ttl` (`kairos-mdm:` vocabulary) and emits an
> immutable, runtime-neutral MDM profile to `output/mdm/`. Author policy with the
> **kairos-design-mdm** skill; runtime matching/stewardship lives in the separate
> `kairos-mdm-runtime` repo. `core` never imports `mdm` (registry pattern,
> MDM-DD-002). See `docs/mdm/`.

> **Silver FK annotations:** When a domain ontology imports reference models via
> `owl:imports`, imported object properties lack cardinality restrictions and will
> not generate FK columns automatically.  Use `kairos-ext:silverForeignKey` /
> `silverForeignKeyOn` in the silver extension file to declare FK relationships.
> See the **kairos-design-silver** skill §3e for details.

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

## Design decisions log

- All significant design decisions are recorded in `docs/design/toolkit-design-decisions.md`.
- **PR rule:** If a PR introduces or changes an architectural decision, add or update an
  entry in the design decisions log before merging.
- Use the ADR template at the bottom of the file for new entries.
- Increment the DD-NNN number sequentially.
