# Working in the kairos-ontology-toolkit repository

This file is for AI agents changing **this toolkit**. It is not shipped to hubs or
dataplatforms. Hub-facing agent instructions live in `.github/copilot-instructions.md`, which
`scripts/sync_dev_skills.py` copies into the scaffold. Do not put toolkit-only rules there.

Load the `kairos-toolkit-dev` skill for the development workflow. The rules below are the ones
most often missed:

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
