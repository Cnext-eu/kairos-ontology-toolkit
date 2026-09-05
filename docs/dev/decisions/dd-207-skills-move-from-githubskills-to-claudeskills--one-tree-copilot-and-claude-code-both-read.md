# DD-207: Skills move from `.github/skills/` to `.claude/skills/` — one tree Copilot and Claude Code both read

**Status:** Accepted
**Date:** 2026-08-27
**Affects:** `.claude/skills/` (replaces `.github/skills/`), `scripts/sync_dev_skills.py`,
`src/kairos_ontology/cli/shared.py` (`_managed_scaffold_map`, `_managed_dataplatform_map`,
managed-file snapshot/restore), `src/kairos_ontology/cli/setup.py`, `src/kairos_ontology/cli/
operations.py` (stale-skill cleanup), toolkit and hub/dataplatform copilot-instructions.md

### Context

`SKILL.md` (frontmatter `name`/`description` plus markdown body) is a cross-tool open standard.
Claude Code reads only `.claude/skills/<name>/SKILL.md` (project), `~/.claude/skills/` (personal),
or a plugin's `skills/` directory — never `.github/skills/`. Every Kairos skill lived only under
`.github/skills/`, so Claude Code sessions in this repo and in every generated hub/dataplatform
repo had no access to any `kairos-*` skill; only Copilot did.

A first pass mirrored every skill into both `.github/skills/` and `.claude/skills/` so each tool
read its own tree. That turned out to be unnecessary: GitHub's own Agent Skills documentation lists
`.github/skills`, `.claude/skills`, and `.agents/skills` as equally supported project locations,
read by the Copilot cloud agent, Copilot code review, the Copilot CLI, the Copilot app, and VS Code
agent mode (support landed December 2025). Copilot already reads `.claude/skills/` directly, so
keeping a `.github/skills/` copy duplicated a tree for no tool that actually needed it.

### Decision

`.claude/skills/<name>/SKILL.md` is now the one authored source, read directly by both tools.
`.github/skills/` is removed everywhere:

- This repo: `scripts/sync_dev_skills.py` now copies `.claude/skills/` (master) to
  `src/kairos_ontology/scaffold/skills/` (distribution copy) — a single sync direction, not the two
  a mirrored-tree approach would need. It explicitly excludes contributor-workflow skills that live
  in this repo's `.claude/skills/` alongside the toolkit's own (e.g. `langfuse`) and the
  Claude-reserved `synced` directory, so only `kairos-*`/`SC-*` skills reach the scaffold.
- Hub/dataplatform repos: `_managed_scaffold_map()` and `_managed_dataplatform_map()` in `cli/
  shared.py` emit a single `.claude/skills/<name>/SKILL.md` entry per skill (previously two), so
  `setup-init`, `new-repo`, and `update` write and version-track one tree. The `--test-ref`/
  `--restore` managed-file snapshot and the `update` stale-skill cleanup likewise operate on
  `.claude/skills/` alone (`_MANAGED_SKILLS_TREE`).

No skill frontmatter changed: every `SKILL.md` already used only `name`/`description`, the portable
subset of the Agent Skills spec.

### Consequences

A skill authored once under `.claude/skills/` loads identically in Copilot and Claude Code, in this
repo and in every repo the toolkit scaffolds, with no duplicated tree to keep in sync and no symlink
to manage (which would have needed Developer Mode/admin plus `core.symlinks=true` to survive a
clone on Windows — a contributor footgun this avoids entirely, not just mitigates). The tradeoff is
depending on GitHub's current Copilot rollout of `.claude/skills/` support holding across the
surfaces this toolkit's users actually run (its documentation does not explicitly confirm JetBrains,
nor guarantee every surface treats all three locations identically). If a gap surfaces on some
Copilot surface, the fix is to reintroduce a generated `.github/skills/` mirror for that surface
specifically, not to move the authored source back.
