# DD-136: Retire V4 Claim Binding and Completeness Authority

**Status:** Accepted
**Date:** 2026-07-27
**Affects:** claim registry/binding/completeness modules, dbt shared phases, CLI, scaffold,
managed skills, and Stage 4 architecture gates
**Implementation:** `docs/design/stage4-retirement-import-inventory.json`,
`tests/test_stage4_retirement_inventory.py`

### Context

The v5 compiler makes reviewed `EntityBinding` YAML the only materialization authority.
V4 claims, aspirational Silver stubs, and completeness-policy gates duplicated that decision
and left dead authority embedded in otherwise reusable normalization and rendering modules.

### Decision

Delete the claim, binding-analysis, completeness, and source-coverage modules and their command,
scaffold, export, and test surfaces. Remove aspirational/stub and claim-eligibility branches from
shared dbt phases. Retain only source analysis, ontology/reference loading, Gold/MDM consumers,
typed expression/policy structures, renderers, and the ontology-only discriminator predicate
required by active compiler paths.

The deterministic Stage 4 inventory asserts zero production imports, absent retired modules and
commands/assets, mirrored managed skills, and absence of retired production markers.

### Rationale

One binding authority prevents source evidence, claims, stub eligibility, and completeness
heuristics from disagreeing. Extracting narrow shared predicates before deletion preserves the
v5 compiler and downstream consumers without retaining V4 governance semantics.

### Consequences

- V4 claim, aspirational-stub, and completeness commands and Python APIs no longer exist.
- Unbound entities fail through compiler diagnostics; no empty Silver model is emitted.
- Source completeness remains an interactive onboarding question, not projection authority.
- Historical DD-094 through DD-096 describe retired V4 behavior and are superseded here.
