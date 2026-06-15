# Slice 7 — Skills thin-chat redesign + scaffold sync

**Status:** ⬜ not started · **Depends on:** 2 · **Gates:** 8

## Goal

Keep skills as orchestrators, but move verbose explanation out of chat into
versioned artifacts (concept C10). Validate the "decision packet" UX before
investing heavily — if it feels like building a workflow engine in markdown,
prefer CLI-does-the-work / skills-as-thin-wrappers.

## Scope

- **Skill modes** across design skills (`kairos-design-*`): `guided` (current),
  `concise` (new default), `silent-artifact`, `review-only`.
- **Decision-packet convention** — each checkpoint emits a compact YAML/Markdown
  packet (summary + `requires_decision` + options + artifact path); chat renders
  only the decision rows, full detail goes to the repo / `.sessions-design/`.
- **Stop repeating methodology** after first invocation; link to help/artifacts.
- **End each phase with PR-ready diffs** ("files changed; review in GitHub PR"),
  not a long chat recap.
- **Routing/help updates** reflecting the registry workflow.
- **Scaffold sync** — `.github/skills` ↔ `scaffold/skills`
  (`python scripts/sync-dev-skills.py`); `test_scaffold_sync.py` green.

## Affected files

`.github/skills/kairos-design-*/SKILL.md`, `kairos-help`, `kairos-execute-*`,
`scaffold/skills/*`, `scripts/sync_dev_skills.py` (if convention added).

## Tests

- [ ] `test_scaffold_sync.py` (drift check) green
- [ ] skill markdown lints / referenced commands exist

## Acceptance criteria

- [ ] Concise mode is the documented default; modes are consistent across skills.
- [ ] Decision-packet format defined and used at checkpoints.
- [ ] `.github/skills` and `scaffold/skills` in sync.

## Risks / notes

- The minimal anti-old-workflow nudge already shipped in Slice 1; this is the full
  redesign.
- Watch the C10 risk: don't reimplement orchestration logic inside prose skills.
