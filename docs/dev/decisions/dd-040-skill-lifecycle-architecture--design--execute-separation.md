# DD-040: Skill Lifecycle Architecture — Design / Execute Separation

**Status:** Accepted
**Date:** 2026-05-30
**Affects:** All Copilot skills, skill naming, routing, scaffold distribution
**Implementation:** See `docs/dev/dd-040-skill-lifecycle-architecture.md` for full ADR

### Context

Skills were originally monolithic (one skill did both interactive design and code
generation). This led to confusion: users invoked a "design" skill expecting output,
or a "generation" skill expecting interactive guidance.

### Decision

Separate all skills into two categories:
1. **Design skills** (`kairos-design-*`) — interactive, require user confirmation at
   checkpoints, produce/modify source files (TTL, YAML)
2. **Execute skills** (`kairos-execute-*`) — run projections/validations/reports,
   produce output artifacts, no interactive gates

### Consequences

- Clear routing: user intent maps unambiguously to skill category
- Design skills are never run in autopilot mode (hard gates require user input)
- Execute skills can be safely automated in CI/CD pipelines
- Existing skills renamed from long-form (`kairos-ontology-modeling`) to short-form
  (`kairos-design-domain`)
