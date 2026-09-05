# DD-110: Typed Projection Contract and Silver Output Parity

**Status:** Accepted
**Date:** 2026-07-25
**Affects:** dbt phase architecture, Silver dbt/DDL/ERD/schema/report output, Gold
registry and projection tests
**Implementation:** Gates 3a and 3b introduced typed logical builders and graph-free,
deeply immutable phase records in `core/projections/dbt/`. Gate 3c added the complete
DD-106–DD-115 authoring facts and effective policy specifications in
`dbt/policy_specs.py`, bind-only RDF/file extraction in `dbt/policy_bind.py`, and
fail-closed, provenance-bearing classification in `dbt/policy_normalize.py`. The same
authoritative `MedallionPolicySpec` now flows through `ProjectionContract`,
`NormalizedProjectFacts`, `ShapedProject`, materialization, adapter negotiation, and the
release plan; each shaped Silver model carries its shared column/identity/audit/history/
FK/DQ/capability authority. The `silver-parity` gate extends that authority with exact
ordered canonical columns, key/grain/FK contracts, adapter-mapped physical columns,
unenforced constraint/index metadata, DQ/quarantine links, and deterministic provenance.
The dbt renderer now emits SQL, schema YAML, Fabric/Databricks DDL, constraint metadata,
ERD, and a field-level parity manifest from the same `SilverModelSpec`. The explicit
`silver` target invokes the identical bind/normalize/shape/materialize/render pipeline
and fails closed when source, preparation, mapping, or policy evidence is absent.
`medallion_silver_projector` is a graph-free render facade only.

**Remaining implementation debt:** external adapter compile evidence and the
DD-112/DD-113 Gold renderer redesign remain later gates. Gold must consume the generated
Silver registry and parity evidence; it must not establish a second Silver authority.

### Context

DD-102 created named phases but deliberately retained mutable graphs and interleaved
shape/materialize/render behavior inside a large monolith for byte compatibility. That
compromise cannot support prep, shared Silver dbt/DDL semantics, or strict capability
evidence.

### Decision

Supersede DD-102 while retaining the ordered phase names:

`bind → normalize → shape → materialize → render`

Every handoff is a deeply immutable typed value. RDF and authoring inputs are read only
inside bind. Normalize is the sole policy-classification phase and emits effective
policy with provenance. Shape creates logical specs and no artifact bytes. Materialize
selects physical plans through adapter capabilities. Render accepts physical plans only
and cannot read RDF, reclassify policy, or choose deviations.

`SilverModelSpec` is the sole logical contract for dbt SQL, schema YAML, DDL, ERD, Gold
registry, quality tests, and reports. Differences between outputs are permitted only
when an explicit adapter capability requires them and the deviation is reported.
DDL-only operational promises are removed. Reference inlining becomes an explicit Gold
product optimization rather than Silver behavior.

### Rationale

One typed contract prevents each projector from independently inventing columns, keys,
history, or constraints. Removing byte-compatibility debt is appropriate for fresh hubs.

### Consequences

- Extract builders before adding feature renderers; this is the redesign's hard
  implementation gate.
- Remove rendered content, mutable containers, graphs, and Jinja objects from phase
  results.
- Amend DD-011, DD-026, DD-029, and DD-104.
- Existing private helper imports and byte-golden compatibility are intentionally
  unsupported.
