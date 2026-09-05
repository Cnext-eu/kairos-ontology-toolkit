# DD-088: Skill-scoped opt-in design fleet mode

**Status:** Accepted
**Date:** 2026-06-22
**Affects:** Copilot instructions, interactive design skills, scaffold managed files
**Implementation:** `.github/copilot-instructions.md`,
`.github/skills/kairos-design-*/SKILL.md`, scaffold copies

### Context

Kairos design skills were originally interactive-only. This protected stakeholder
confirmation gates for discovery terms, source vocabulary descriptions, domain
modeling, mappings, silver annotations, and gold semantic-model choices. However,
testing a complete lifecycle can be slow when every checkpoint must wait for a
human even when the user explicitly wants AI to make decisions for a test run.

### Decision

Keep the lifecycle-wide design autopilot ban. Interactive mode remains the
default, and no fleet-mode authorization may be inferred from an earlier phase,
stored as a global preference, or propagated during a skill handoff.

A user may explicitly override the ban for **one specific design skill
invocation**. The active skill may offer that choice at startup or accept an
explicit fleet/autopilot/AI-approved request while it is active. Authorization
ends when that skill invocation ends or pauses; another skill, or a later resume,
starts interactive unless the user grants a new override.

Within an authorized invocation, the skill may let AI approve normal checkpoint
decisions, but it must still execute the same phases, evidence gates, validations,
and skill routing as interactive mode. Each AI-made decision must be recorded as
AI-approved with rationale, confidence, and evidence references in the relevant
phase log or review output.

### Rationale

This preserves the no-autopilot governance boundary while allowing a user to
accelerate one well-defined phase deliberately. The speedup comes from replacing
repeated human confirmations inside that invocation with traceable AI decisions,
not from granting blanket lifecycle autonomy or skipping evidence, validation, or
review artifacts.

### Consequences

- Interactive remains the normal governance mode for stakeholder-facing design.
- Fleet consent is skill- and invocation-scoped; it never carries into another
  skill or a resumed invocation.
- A skill that offers fleet mode must explain the implications before asking and
  must make interactive mode the recommended default.
- Fleet mode decisions are explicitly marked AI-approved, not user-confirmed.
- Skills must still stop for ambiguity, low confidence, policy-sensitive choices,
  destructive or irreversible actions, and proprietary/PII risk.
- Existing validation and scaffold sync tests guard the instruction copies.
- **Amended by DD-149**: archetype selection in `kairos-design-discovery` is added to
  the never-fleet-eligible list above — it is always confirmed by a human, never
  AI-approved, even within an active fleet-mode override.
