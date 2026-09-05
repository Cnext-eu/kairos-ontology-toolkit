# DD-113: Governed Semantic-Model Lifecycle

**Status:** Accepted
**Date:** 2026-07-25
**Affects:** DAX/TMDL, measures, calendar/time intelligence, incremental policy,
RLS/OLS, perspectives and DirectLake readiness
**Implementation:** typed measure/calendar/security contracts, dependency and cycle
validation, fail-closed TMDL/security generation, and strict compile/readiness evidence

### Context

Current measure annotations remove their source columns, generic calendars and time
intelligence are generated without approved business assumptions, and security roles are
scaffolds without entitlement or deployment governance.

### Decision

Measures are first-class semantic resources with stable identity, business definition,
dependencies, lifecycle state (`intent`, `provisional`, `validated`, `approved`), format,
owner role, and tests. Measures never remove required physical input columns. Every DAX
dependency resolves against emitted columns/measures; missing references and cycles
block release.

Production time intelligence requires an approved calendar profile covering date range,
fiscal/week pattern, locale, holidays, time zone, period closure, and role-playing dates.
Generic unapproved calendar defaults are non-production.

RLS/OLS output requires a complete projection-time fail-closed security contract:
entitlement source, identity mapping, role policy, filter direction, bindings, and
positive/negative test definitions. Perspectives are discoverability metadata only and
never security. Successful deployment and runtime enforcement remain downstream facts.
Generated TMDL must parse/compile and DirectLake bindings/types must validate.

### Rationale

Semantic-model artifacts are executable contracts. Compilable DAX or a role block is not
evidence that business semantics or access governance are correct.

### Consequences

- Remove property-replaces-column measure behavior, automatic calendar generation, and
  the unpopulated `is_authorized` role assumption.
- Replace GDPR-specific security framing with general data classification/security
  policy.
- Keep entitlement provisioning and runtime identity administration out of the toolkit.
