# Slice 7 — Skills thin-chat redesign + scaffold sync

**Status:** ✅ done · **Depends on:** 2 · **Gates:** 8

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

- [x] `test_scaffold_sync.py` (drift check) green
- [x] skill markdown lints / referenced commands exist

## Acceptance criteria

- [x] Concise mode is the documented default; modes are consistent across skills.
- [x] Decision-packet format defined and used at checkpoints.
- [x] `.github/skills` and `scaffold/skills` in sync.

## Risks / notes

- The minimal anti-old-workflow nudge already shipped in Slice 1; this is the full
  redesign.
- Watch the C10 risk: don't reimplement orchestration logic inside prose skills.

## Delivered (2026-06-16)

Slice 7 is a **skills/docs-only** slice (no runtime code beyond the `__version__`
bump) that applies a thin-chat presentation convention across the evidence-led
design skills, realizing concept C10 (DD-EL-9).

### Four interaction modes

- `guided` — the former verbose behaviour (full explanation in chat).
- `concise` — the **new documented default**: minimal chat, decisions as packets,
  detail in artifacts.
- `silent-artifact` — write straight to artifacts with minimal chat; still stops at
  blocking decisions (never auto-confirms).
- `review-only` — summarize current state / proposed diffs without advancing.

### Decision-packet format

Each checkpoint emits one compact packet — `summary` / `requires_decision` /
`options` / `artifact` path / `mode`. Chat renders only the decision rows; full
detail goes to the repo / `.sessions-design/` session files / the Claim Registry.
Methodology is stated once then linked to `kairos-help`, and each phase ends with
**PR-ready diffs** instead of a long chat recap. The no-autopilot rule is preserved
(`silent-artifact` never auto-confirms a blocking decision).

### Skills updated

`kairos-design-discovery`, `kairos-design-source`, `kairos-design-domain`,
`kairos-design-mapping`, `kairos-design-silver`, `kairos-design-gold` each carry a
tailored "Interaction Modes & Decision Packets" section, with the **canonical
definition in `kairos-help` §11** ("Skill interaction modes & decision packets").
`.github/skills` and `scaffold/skills` mirrors are in sync.

### C10 scope note

These modes and packets are a **presentation layer over the existing checkpoints**,
not a new orchestration/workflow engine. Any real branching stays in deterministic
CLI commands (CLI-does-the-work); skills remain thin wrappers. This guard was the
key design risk the slice validated.
