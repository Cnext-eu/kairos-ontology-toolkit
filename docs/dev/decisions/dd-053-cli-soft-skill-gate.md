# DD-053: CLI Soft Skill-Gate

**Status:** Accepted
**Date:** 2026-06-13
**Affects:** `cli/main.py` (group + skill-covered commands), gated `*/SKILL.md`
files, `.github/copilot-instructions.md` (+ scaffold copy)
**Implementation:** `_warn_if_no_skill_context()` + `_SKILL_COVERED_COMMANDS`
in `src/kairos_ontology/cli/main.py`

### Context

The toolkit's "skill-first" rule lived **only in prose**
(`copilot-instructions.md`). Prose guardrails are advisory and are weakest
exactly when the raw CLI succeeds, because nothing pushes back: Copilot runs
e.g. `python -m kairos_ontology project` directly, gets a correct result, and
silently bypasses the skill's pre-flight checks and interactive validation
gates. Reliable skill adoption needs **friction at the CLI layer**, not just
more instructions.

### Decision

Add a **soft skill-gate** to the CLI. Skill-managed commands (`validate`,
`project`, `init`, `new-repo`, `migrate`, `update`, `update-refmodels`,
`import-source`, `import-flatfile`, `generate-staging`, `analyse-sources`,
`init-dataplatform`) emit a loud stderr warning that names the owning skill,
then **still run** (soft, non-blocking). The check is wired once into the Click
group via `ctx.invoked_subcommand`, so individual command bodies are untouched.

A sentinel env var (`KAIROS_SKILL_CONTEXT`, also `KAIROS_VIA_SKILL`) suppresses
the warning. Each gated `SKILL.md` instructs setting it, so the **skill path is
silent and only the raw path nags**. CLI-only commands (`import-tmdl`,
`coverage-report`, `propose-alignment`, `generate-inventory`, `check-inventory`,
`catalog-test`, `lifecycle`) are not gated.

### Rationale

- A soft gate redirects the agent without breaking automation, scripts, or CI.
- Single insertion point (group context) keeps the map declarative and testable.
- The env-var escape hatch lets skills, power users, and CI opt out explicitly.
- Chosen over a hard gate (exit non-zero) — selected by the maintainer — to avoid
  breaking existing non-interactive flows.

### Consequences

- New gated commands must be added to `_SKILL_COVERED_COMMANDS`, and the owning
  `SKILL.md` must set `KAIROS_SKILL_CONTEXT=1` (else it warns during legit use).
- Skill edits must be mirrored to `scaffold/skills/` via `sync_dev_skills.py`.
