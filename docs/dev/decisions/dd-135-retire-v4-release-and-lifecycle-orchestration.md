# DD-135: Retire V4 Release and Lifecycle Orchestration

**Status:** Accepted
**Date:** 2026-07-27
**Affects:** release evaluation, lifecycle/status scanning, projection readiness, CLI and scaffold
**Implementation:** `docs/dev/stage4-retirement-import-inventory.json`,
`tests/test_stage4_retirement_inventory.py`, and the canonical v5 compiler

### Context

DD-133 made `CompilePlan` the canonical Silver/dbt planning authority. The older release
evaluator, lifecycle gate, projection-readiness planner, and status scanner duplicated planning
and persisted heuristic lifecycle evidence after their production consumers had been cut over.

### Decision

Delete those four modules after the deterministic AST inventory proves their production import
edges are zero. Remove their Click commands and lifecycle-state scaffold. Retained diagnostics
and routing consume ordered compiler diagnostics; source analysis, ontology/reference inventory,
update/version diagnostics, and compiler diagnostics remain supported.

### Rationale

One typed planning authority prevents readiness and release heuristics from disagreeing with the
artifacts the compiler can actually emit. A versioned retirement gate makes deletion reviewable
and prevents a removed subsystem from being reintroduced by an unnoticed import.

### Consequences

- `check-projection`, `check-release`, and `status` are no longer CLI commands.
- Importing any retired module raises `ModuleNotFoundError`.
- New hubs do not scaffold `.kairos-state`; flow and diagnostic skills are stateless.
- Compile success is not a runtime-validation or release-certification claim.
- The transformation evidence/synchronization/candidate, preparation/Silver RDF authority,
  report/session persistence, release-baseline, and obsolete-command waves recorded in the
  same inventory are also retired. Ordinary contracted dbt SQL/YAML source contracts and
  reusable source/ontology/compiler/rendering architecture remain.
