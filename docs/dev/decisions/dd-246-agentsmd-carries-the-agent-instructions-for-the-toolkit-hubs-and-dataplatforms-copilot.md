# DD-246: AGENTS.md carries the agent instructions for the toolkit, hubs and dataplatforms; copilot-instructions.md is a pointer

**Status:** Accepted
**Date:** 2026-09-26
**Affects:** `init`, `new-repo`, `init-dataplatform`, `update` (and `--check`, `--test-ref`,
`--restore`), the hub and dataplatform scaffolds, this repository's own agent instructions,
`scripts/sync_dev_skills.py`, `kairos-toolkit-dev`
**Amends:** DD-040, DD-048, DD-051, DD-053, DD-088, DD-207 (where they name
`.github/copilot-instructions.md` as the home of always-on rules), DD-062 (the root anchor is
unchanged; see Decision 3)
**Issue:** #1031
**Implementation:** `scaffold/AGENTS.md.template`, `scaffold/dataplatform-AGENTS.md.template`,
`scaffold/copilot-instructions.md`, `scaffold/dataplatform-copilot-instructions.md`,
`cli/shared.py` (managed region, snapshot, `CLAUDE.md` advisory), `cli/operations.py`,
`cli/setup.py`, root `AGENTS.md`, `.github/copilot-instructions.md`

### Context

`.github/copilot-instructions.md` did two jobs. It was this repository's Copilot file, and
it was the master that `scripts/sync_dev_skills.py` copied byte-identical into every hub.
Three problems followed:

1. Hubs received about 25 lines of toolkit-developer rules they could not act on: code
   conventions, SPDX headers, the scaffold sync rule, and two "this repository only" rows.
2. Claude Code in a hub read no always-on rules, only skills. The DD-103 rule "never read a
   `.ttl` as text" reached it only through the DD-245 hook, after the read.
3. #1021 added a root `CLAUDE.md` with contributor rules. That split the toolkit's own rules
   across two files.

Checked on 2026-09-26, which file each agent reads:

- `AGENTS.md` is read by the Copilot coding agent, Copilot code review (root only), the
  Copilot CLI and VS Code (`chat.useAgentsMdFile`, on by default), and also by Codex,
  Cursor, Gemini CLI, Windsurf, Zed and Devin. The Agentic AI Foundation (Linux Foundation)
  stewards it.
- Claude Code reads `AGENTS.md` natively, **but only when no `CLAUDE.md` exists**.
  Otherwise the `CLAUDE.md` must import it with an `@AGENTS.md` line.
- `.github/copilot-instructions.md` is still the only file read by github.com Chat,
  JetBrains and Visual Studio chat, and VS Code code review.
- Skills are unaffected: both tools read `.claude/skills/` (DD-207).

### Decision

1. **`AGENTS.md` is the one agent-instruction file.** In this repository it holds the
   contributor rules: #1021's `CLAUDE.md` bullets, the code conventions, the validation and
   scaffold checks, and the overlapping lines of `kairos-toolkit-dev`. The root `CLAUDE.md`
   is deleted, so Claude Code reads `AGENTS.md` natively.
2. **In a hub or dataplatform the toolkit owns a region of `AGENTS.md`, not the file.** The
   region sits between `<!-- kairos-ontology-toolkit:managed-begin vX -->` and
   `<!-- kairos-ontology-toolkit:managed-end -->`.
   - `init`, `new-repo`, `init-dataplatform` and `update` rewrite only the region.
   - A missing file is created with the region plus an empty "Repository notes" section.
   - An `AGENTS.md` without markers gets the region prepended; its text is kept unchanged.
   - `update --check` reports drift inside the region only.
   - `--test-ref` / `--restore` snapshot the file with the other instruction files.

   A whole-file managed `AGENTS.md` was rejected because `update` overwrites any managed
   path whose content differs. It would wipe a repository's own `AGENTS.md`, and
   `managed-check.yml` would then fail its pull requests. The region content is authored in
   `scaffold/AGENTS.md.template` and `scaffold/dataplatform-AGENTS.md.template`. These hold
   the hub-facing sections of the old file, reworded for any agent, not only Copilot.
3. **`.github/copilot-instructions.md` becomes a whole-file managed pointer**, about ten
   lines. It says the instructions are in `AGENTS.md` and repeats the few rules that must
   survive on surfaces that read only this file. It keeps its managed marker, so DD-062's
   root detection (`hub_utils._is_managed_root`) is unchanged. The region marker says
   `managed-begin`, never `managed v`, so `AGENTS.md` is never mistaken for a whole-file
   managed file or a root anchor; a test pins this.
4. **The sync pair is gone.** Hub instructions are authored in the scaffold like every other
   template. This repository's `AGENTS.md` and `.github/copilot-instructions.md` are
   written for contributors and are never copied into a hub.
5. **`update` advises when a `CLAUDE.md` would switch `AGENTS.md` off.** If `CLAUDE.md`,
   `.claude/CLAUDE.md` or `CLAUDE.local.md` exists without an `@AGENTS.md` line, `update`
   and `update --check` print a one-line advisory. It never fails `--check`, the same
   pattern as the `.claude/settings.json` advisory. The file belongs to the repository,
   and the fix is one line in it.

### Rejected

- **Shipping a thin `CLAUDE.md` containing `@AGENTS.md` to hubs.** It collides with a hub's
  own `CLAUDE.md`, and Copilot surfaces that read both files would see the bare import line.
- **Keeping the full content in both `AGENTS.md` and `copilot-instructions.md`.** Surfaces
  that read both would get every rule twice, and the two copies would drift.

### Consequences

- The first `update` after this release adds `AGENTS.md` to every hub and dataplatform and
  shortens `copilot-instructions.md`. `update --check` reports `AGENTS.md` as missing until
  then.
- Claude Code sessions in hubs now read the DD-103 rule, the skill routing and the
  design-interaction policy before acting, unless the hub keeps a `CLAUDE.md` without the
  import. That case gets the advisory.
- A repository's own agent guidance has a supported place: below the managed block.
- Out of scope: nested per-directory `AGENTS.md` files (VS Code support is experimental),
  the Copilot-named workflows, and the devcontainer extension.
