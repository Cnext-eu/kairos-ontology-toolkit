# DD-007: Extend kairos-ext Namespace

**Status:** Accepted
**Date:** 2026-04-30
**Affects:** Annotation vocabulary, `scaffold/kairos-ext.ttl`
**Implementation:** New properties in `kairos-ext:` namespace

### Context

New annotations needed (`populationRequirement`, `derivationFormula`, `naturalKey`).
Should these go in a new namespace or extend `kairos-ext:`?

### Decision

Extend `kairos-ext:` namespace.

### Rationale

- Same domain as existing kairos-ext properties (projection control)
- Fewer prefixes for hub authors
- `kairos-ext:` is well-established
