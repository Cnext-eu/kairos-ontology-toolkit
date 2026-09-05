# DD-118: Contracted dbt Output as Verified Source Identity

**Status:** Accepted
**Date:** 2026-07-26

### Context

DD-108 accepted physical `RecordKeyPolicy` and `ArrayChildContract` authorities only. A
keyless raw source whose governed dbt transformation forms a unique output grain could not
represent that identity truthfully. Declared tests were insufficient because they prove no
warehouse result.

### Decision

`sync-dbt-contracts` emits a typed `kairos-dbt:ContractIdentity` containing its contract/model
reference, virtual table, ordered grain columns, contract-output scope, replacement lineage,
required uniqueness/non-null tests, canonical CDC bindings, decision evidence/status, and a
canonical SHA-256 content hash covering contract identity fields and SQL.

DD-108 accepts this as its third `sourceIdentity` authority. It remains source/output-scoped
and never establishes enterprise identity. Actual passing dbt test results are captured from
supplied `run_results.json` plus its manifest in a versioned deterministic evidence artifact.
Evidence v2 requires matching non-empty invocation IDs and dbt versions, an unambiguous model,
and exact executed tests. Ordinary standard dbt manifest v12 and run-results artifacts are the
authority: the model path, raw code, and dbt SHA-256 checksum bind current SQL, while standard
model, column, config/contract, constraint, generic-test, singular-test, and unit-test fields
bind current YAML semantics. Custom manifest fields and post-run current-file attestations are
not accepted. Unbound v1 evidence is rejected rather than upgraded or synthesized.
Missing, incomplete, or hash-stale evidence surfaces `identity.contract-unverified`
(amended by DD-119: review-only outside `--strict`/release evaluation).
Readiness evaluates discovered contracts even with no transformation candidates.
The transformation-scoped readiness view also reuses contract discovery, synchronization,
candidate governance, completeness, and projection normalization to report grain, decision
evidence, replacement, CDC, dependency, implementation, and test blockers. An absent or empty
candidate inventory never suppresses checks for synchronized contracts.

Canonical `__` and legacy slash virtual-column IRIs remain supported.

### Consequences

- Keyless physical input may safely form identity at a verified contracted output boundary.
- Contract, SQL, key, test, CDC, decision, or replacement changes invalidate prior evidence.
- The toolkit never claims warehouse execution without supplied dbt results.
