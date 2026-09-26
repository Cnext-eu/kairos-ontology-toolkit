# Kairos Ontology Toolkit — Agent instructions

This file is for AI agents changing **this toolkit**. It is not shipped to hubs or dataplatforms.
What a hub's agent reads is authored in the scaffold (DD-246):

- `src/kairos_ontology/scaffold/AGENTS.md.template` — the managed block of a hub's `AGENTS.md`;
- `src/kairos_ontology/scaffold/dataplatform-AGENTS.md.template` — the same for a dataplatform;
- `src/kairos_ontology/scaffold/copilot-instructions.md` and
  `dataplatform-copilot-instructions.md` — the short pointers for Copilot surfaces that do not
  read `AGENTS.md`.

Do not put toolkit-only rules in those files, and do not put hub rules here.

Load the `kairos-toolkit-dev` skill for the development workflow. Claude Code reads this file
because the repository has no `CLAUDE.md`; if you add one, it must contain `@AGENTS.md`.

## Rules most often missed

- **Changelog: fragments only.** A feature or fix PR adds
  `changelog.d/<issue>-<slug>.md` (format in `changelog.d/README.md`) and never edits
  `CHANGELOG.md`. Only a release PR, one that bumps `__version__`, touches `CHANGELOG.md`, and
  it does so with `scripts/collect_changelog.py --apply`. CI (`version-check.yml`) rejects a
  `CHANGELOG.md` edit in any other PR: parallel PRs editing `[Unreleased]` conflict on every
  merge.
- **Lint before a PR:** `uv run ruff check src/ tests/`. CI lints before it runs pytest. Do not
  run a repo-wide `ruff format`; format only the files you created.
- **Decision records** (`docs/dev/decisions/dd-NNN-*.md`) take the next free number. The
  register forbids gaps (`tests/test_design_decisions_consistency.py`).
- **Issue references:** a bare `(#123)` in a PR title or body closes the issue on merge
  (`auto-close-issues.yml`). For a partial fix write `(#123 P2)` or `Refs #123`.
- **Ontology meaning comes from the closure (DD-243).** Read a domain or reference ontology
  through `core.ontology_loader.load_ontology` and its `semantic_index`, never a bare
  `Graph().parse` of one file: the file's `owl:imports` carry the parents and inherited
  properties. `tests/test_dd103_closure_boundary.py` inventories every direct parse; a prompt
  that lists ontology terms renders them with `core.prompt_context`; read a profile-dependent
  index field only after `index.carries(field)`.
- **Managed workflows:** changing a template under `src/kairos_ontology/scaffold/` that is
  registered in `_LIVE_WORKFLOW_TEMPLATE_DIGESTS` (`tests/test_workflow_refresh.py`) means you
  must record the outgoing generation under `scaffold/superseded-workflows/`, register it in
  `_SUPERSEDED_WORKFLOW_TEMPLATES`, and update the digest. Otherwise existing hubs stop
  auto-refreshing it.

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

## Semantic access in this repository

The DD-103 rule hubs follow applies here too: do not read an ontology serialization (`.ttl`,
`.rdf`, `.owl`) as text to learn what it means; use `kairos-ontology explain-term`,
`list-class-properties`, `show-class-inventory` or `resolve-ontology`. This repository has no
`.claude/settings.json` deny-list or read hook, so the rule is a convention here, not an enforced
boundary. Reading a fixture's bytes to test a parser or a serializer is fine.

## Validation and tests

- `validate_content()` returns syntax and SHACL result sections.
- Run the smallest focused tests first; projection/compiler changes require scenario coverage.
- EntityBinding/compiler changes should run `tests/scenarios/test_scenario_v5.py` and relevant
  compiler tests.
- Skill changes must keep `.claude/skills/<name>/SKILL.md` byte-identical to
  `src/kairos_ontology/scaffold/skills/<name>/SKILL.md`; run `scripts/sync_dev_skills.py` and
  the scaffold sync/managed tests.

## Scaffold and open-source checks

Changes affecting hub repositories must also update `src/kairos_ontology/scaffold/`. The hub
and dataplatform agent instructions listed at the top are authored there directly; they are not
synced from this file. An architectural change adds a decision file under
`docs/dev/decisions/` and its row in `docs/dev/toolkit-design-decisions.md`.

Before a PR, verify SPDX headers, no secrets or PII, Apache-2.0-compatible dependencies, NOTICE for
bundled third-party components, no proprietary examples, DCO sign-off, and issue-closing keywords in
the PR body for fully fixed issues.
