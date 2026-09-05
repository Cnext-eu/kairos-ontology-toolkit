# DD-105: Imported dbt evidence is governed before Mapping and Silver

**Status:** Accepted
**Date:** 2026-07-22
**Affects:** source onboarding, transformation planning, lifecycle status and release gates,
Mapping/Silver preflight, custom dbt contracts, adapter validation, and accelerator selection
**Implementation:** `core/transformation_candidates.py`, `core/status.py`,
`core/lifecycle_gate.py`, `core/dbt_contracts.py`, `core/dbt_contract_sync.py`,
`core/reference_modules.py`, CLI commands, and lifecycle skills

### Context

Imported authored SQL can reveal joins, aggregation, ranking, survivorship, or a changed row
grain before a governed custom dbt contract exists. The lifecycle previously considered only
executable contracts under `integration/transforms/dbt/`, so Mapping and Silver could proceed
without assessing imported transformation evidence. SQL found in prototypes or downstream
Power BI parity projects must remain evidence; discovery alone cannot make it executable,
assign a semantic target, or grant source-replacement authority.

Three related contract/preflight defects also surfaced: generated virtual-source nullability
ignored explicit non-key `not_null` tests, contracts were forced to declare both supported
warehouse adapters, and scoped validation/projection did not consistently resolve the hub's
accelerator context.

### Decision

Explicit repository-contained SQL/dbt roots are inventoried into the committed,
non-executable planning artifact
`model/planning/dbt-transformations/candidates.yaml`. The artifact declares
`projection_authority: false`. Normalized repository-relative model paths are stable
candidate identities; SHA-256 is a separate freshness signal. Content changes force
reassessment, while a rename produces an orphan and a new candidate requiring explicit
re-linking.

The inventory separates deterministic observations (path, checksum, model references,
source references, operation signals, and explicit grain metadata) from governed decisions
(grain interpretation, semantic target, authority class, replacement scope, disposition,
rationale, confidence, evidence, and approval). Power BI and migration/parity evidence never
become source authority by location or SQL complexity.

Every governed disposition records the artifact checksum it assessed. Implemented candidates
also record the discovered dbt contract model name explicitly, so contract identity is not
coupled to an imported artifact filename.

`dbt-transformation` remains a checkpoint implemented by the existing
`kairos-develop-dbt-transformation` skill and OKF phase-log directory; it is not added to
`PHASE_ORDER`. `status` reports additive candidate facts but remains observational.
`check-transformation-readiness --stage mapping|silver` is the deterministic, non-writing
preflight authority. Mapping and Silver skills must stop on a non-zero result and route to
the transformation checkpoint.

The readiness evaluator is also a first-class component of `LifecycleGateReport`; its
`is_blocking` participates in the gate's existing OR composition without duplicating rules
inside `lifecycle_gate.py`. Because this broadens the meaning of the aggregate release
decision, the lifecycle-gate report schema is versioned accordingly. Hubs without a
candidate inventory retain existing behavior.

Accepted/implemented candidates reuse the DD-092/DD-093 authority path:
`DbtContractModel`, `meta.kairos.replaces_sources`, synchronized custom-transform vocabulary,
SKOS mapping, and `silverSourceRef`. The candidate inventory does not duplicate executable
contract authority.

Contract columns retain explicit `not_null` tests/constraints. Natural-key membership and
explicit `not_null` independently imply non-null virtual columns. Contracts may declare any
non-empty valid subset of supported adapters; projection configuration selects the active
adapter and rejects a model that does not support it. Accelerator resolution follows
explicit CLI option, then hub configuration, then unambiguous single-pack inference.

### Rationale

A committed planning artifact makes decisions reviewable and machine-readable without
turning raw imports into runtime code. Separating observations from decisions prevents static
SQL heuristics or LLM interpretation from becoming semantic authority. Reusing the existing
contract/replacement path keeps one implementation authority, while a dedicated preflight
command provides a concrete testable gate instead of relying on skill prose.

Keeping the checkpoint outside the canonical phase order avoids destabilizing deterministic
status semantics and mirrors other advisory planning artifacts. Independent adapter,
nullability, and accelerator fixes remain reviewable without coupling them to candidate
inventory internals.

### Consequences

- Source onboarding inventories only roots explicitly selected by the user; broad recursive
  scanning of all imported archives is intentionally unsupported.
- Imported SQL stays in place and is never copied into the executable dbt bundle
  automatically.
- Changed or orphaned candidates remain visible and require reassessment/re-linking.
- Mapping/Silver automation must invoke the deterministic readiness command before writes.
- Release checks can newly fail when governed transformation evidence remains unresolved.
- Single-adapter contracts are valid, but projection fails for a selected unsupported
  adapter.
- Required non-key contract columns now project as non-null in managed virtual vocabularies.
- Ambiguous accelerator installations require explicit CLI or hub configuration.
