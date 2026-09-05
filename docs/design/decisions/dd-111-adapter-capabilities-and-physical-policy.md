# DD-111: Adapter Capabilities and Physical Policy

**Status:** Accepted
**Date:** 2026-07-25
**Affects:** Fabric/Databricks rendering, types, hashes, JSON, merge, constraints,
partitioning/clustering, adapter validation and release gates
**Implementation:** `core/projections/dbt/capabilities.py` provides the versioned v1
Fabric and Databricks registry for canonical types, canonical SHA-256 hashing, scalar and
array JSON, merge/upsert/delete, constraints, deployment-owned physical layout,
quarantine/tests, security, and TMDL. Materialization negotiates exact typed requirements
to `supported`, approved `deviation`, or `blocking` results carrying the normative rule
and evidence; unknown adapters and the former Spark alias fail closed. Authored capability
and compile-evidence statements are normalized separately from registry capability.
Successful adapter compile runs and versioned compile-evidence reporting remain a later
implementation gate, so registry support alone is not strict-release compile proof.

### Context

A shared semantic contract does not make Fabric and Databricks behavior equivalent.
Types, collation, timestamps, JSON, merge, constraints, and physical layout differ.
Conditional code and a default platform can silently degrade unsupported behavior.

### Decision

Every adapter has a versioned capability record. Unknown adapters and unsupported
feature combinations fail with structured diagnostics; no “non-Fabric means
Databricks” fallback is allowed. Semantic types are mapped explicitly with disclosed
lossiness.

`partitionBy`, `clusterBy`, indexes, and storage layout are target deployment-profile
policy based on measured workload, not ontology truth. “Supported/applied” requires
successful compile evidence for every required adapter. `environment_blocked` is not a
strict-pass result.

### Rationale

Capability negotiation makes portability testable without forcing identical physical
SQL or silently lowering guarantees.

### Consequences

- Add Fabric and Databricks golden/compile scenarios for semantic parity.
- Remove unsupported Silver physical annotations from the semantic extension surface.
- Amend DD-002, DD-009, and DD-104 without changing Fabric as the default user choice.
