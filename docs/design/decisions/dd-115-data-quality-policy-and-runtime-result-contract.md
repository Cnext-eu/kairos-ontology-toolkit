# DD-115: Data-Quality Policy and Runtime-Result Contract

**Status:** Accepted
**Date:** 2026-07-25
**Affects:** SHACL/extensions, generated dbt tests, quarantine models, reports, adapter
capabilities and release gates
**Implementation:** typed DQ policy/runtime-result specs, closed declarative
expressions, `kairos_dq_*` dbt macros, persistent result/test artifacts,
row-level quarantine routing, and immutable downstream evidence import

### Context

Generated null, uniqueness, regex, and relationship tests cover contract shape but not
operational fitness. A projection-time toolkit can generate checks and schemas but
cannot claim live freshness, trend health, or alert delivery.

### Decision

Every DQ rule has stable ID/version, category (`contract`, `source`, `business`,
`operational`), scope, severity, tolerance, action (`warn`, `quarantine`, `block`),
abstract owner role, evidence, and executable test reference.

The toolkit generates supported dbt tests, quarantine/reject models, and a portable
runtime-result schema containing run/snapshot/adapter identity, rule ID/version/hash,
status, measured value, threshold, affected/quarantined counts, reconciliation values,
and evidence URI. Runtime observations are imported immutable evidence; the toolkit does
not provide monitoring, alerts, or trend storage.

Prefer toolkit-owned namespaced tests/macros. External packages require approved-package
governance, compatible licensing, and adapter capability evidence. Unsupported checks
block or become approved deviations; uncompilable tests are never emitted.

### Rationale

Static policy and portable results make quality governable without pretending that
generated SQL has executed or that the toolkit operates a data platform.

### Consequences

- Add freshness, volume, duplicate-rate, range/distribution, reconciliation,
  referential-coverage, and cross-field rule types where adapter capabilities permit.
- Missing/stale runtime results block only profiles/rules that explicitly require them.
- DD-089 offline sample audit remains evidence, not runtime telemetry.

### v5 wiring (issue #256)

The v5 stateless compiler collects `kairos-ext:DataQualityRule` individuals that are attached to a
canonical `owl:Class` via `kairos-ext:dataQualityRule`. Collection happens inside `resolve_scope`
while the ontology graph is still loaded; the rules are carried graph-free on
`ResolutionContext.data_quality_rules`, set on the merged `MedallionPolicyFacts.data_quality`, and
normalized into the same `CompilePlan.quality_models` that emit and explain consume. The governing
class is retained on `DataQualityRuleFact`/`DataQualityRuleSpec` so scope resolution can disambiguate
property/relationship-scoped rules and reject attachment/scope conflicts (`dq.scope-owner-conflict`).
`compile --emit` writes the result model, singular test, quarantine relations (row-level actions),
and runtime-result contract; `compile --explain` surfaces each rule per entity (`data_quality[]`).
