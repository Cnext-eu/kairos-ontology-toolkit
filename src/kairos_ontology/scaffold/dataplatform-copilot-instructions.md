# Kairos Dataplatform — Agent instructions

This repository's agent instructions are in `AGENTS.md` at the repository root. Read it before
acting. This file exists for the Copilot surfaces that do not read `AGENTS.md`, and it carries
only the rules that must never be missed:

- Never edit compiler-owned output; keep downstream-only logic in ordinary dbt models.
- Pin an immutable Git revision or versioned artifact, never a moving production branch.
- Invoke the owning `kairos-*` skill under `.claude/skills/` before changing how this repository
  consumes the hub.
