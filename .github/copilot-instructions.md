# Kairos Ontology Toolkit — Agent instructions

This repository's agent instructions are in `AGENTS.md` at the repository root. Read it before
acting. This file exists for the Copilot surfaces that do not read `AGENTS.md`, and it carries
only the rules that must never be missed:

- A feature or fix PR adds a `changelog.d/<issue>-<slug>.md` fragment and never edits
  `CHANGELOG.md`; run `uv run ruff check src/ tests/` before opening it.
- Read ontology meaning through `core.ontology_loader.load_ontology` and its `semantic_index`,
  never a bare `Graph().parse` of one file (DD-243).
- The instructions a hub receives are authored in `src/kairos_ontology/scaffold/`
  (`AGENTS.md.template`, `copilot-instructions.md`), not in this file (DD-246).
