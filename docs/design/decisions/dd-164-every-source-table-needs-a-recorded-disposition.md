# DD-164: Every source table needs a recorded disposition

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `validate`, kairos-design-domain Gate 1, kairos-design-mapping
**Implementation:** `core/source_disposition.py`, `source-disposition` CLI, wired into
`core/validator.py:run_validation`

### Context

A blueprint deliberately scopes which domains exist (DD-149/DD-150), so a hub will always hold
source tables no blueprint domain claims. `domain-coverage` already reports this — `not-modeled`,
`deferred`, unassigned tables — but reports it advisorily and always exits 0, so nothing obliges
anyone to answer.

Unanswered, the question resolves itself two ways, both unrecorded. The table is dropped ("no
canonical entity"), or it is force-fitted by minting a local class in whatever domain was in
scope. A real run did both to the same table: `comments` (3,149 rows) was skipped in `claims` as
having no canonical home, while a local `Comment` class appeared in commercial, customs, mdm and
roro, and a `hasCommentCategory` property was hung off a leaked `Document` class in party. The
run's transparency report then asserted *"All unbound tables are metadata, schema-lookup, or
workflow tables with no canonical entity target"* — while `qargo.stops` (72,633 rows),
`qargo.shipments` (32,491) and `qargo.resource_allocations` (30,492) sat unbound and unmentioned.
The hand-built `.dap-dbt` project models all three as first-class entities, so they are plainly
business data.

`register-concept` (DD-162) already existed as the sanctioned route for "our source data argued
this concept in". It was referenced by one skill, once, and the run produced
`registered_concepts: []`.

### Decision

Make the outcome an artifact. Every source table above `DEFAULT_ROW_THRESHOLD` (100) rows must be
either bound by an EntityBinding or carry an explicit disposition in
`integration/sources/_analysis/table-dispositions.yaml`. An unbound, undisposed table fails
`validate`; smaller ones warn.

The disposition set is closed: `bound`, `registered-extension`, `deferred`, `not-business-data`,
`blueprint-gap`. The last three require a written rationale, because a reviewer cannot otherwise
distinguish a considered skip from an overlooked table.

This does not force data into the ontology. `not-business-data` remains a good answer — it simply
has to be an answer, attributed and reasoned, rather than the absence of one. `blueprint-gap`
exists so a genuine accelerator shortfall is filed upstream instead of absorbed hub-side, and the
undecided-table remediation names `register-concept` explicitly so the sanctioned path is the
visible one.

### Alternatives rejected

| Alternative | Why not |
|---|---|
| Add a `--strict` flag to `domain-coverage` | Deferred once already (issue #393). An opt-in flag is not run by the pipeline that needs it, and the gap is in `validate`, which stage exits already call. |
| A hub-local extension domain | Solves where a concept lives, not whether anyone decided. Still available later as a disposition value. |
| One record per table | The ledger's value is that a reviewer sees every skipped table in one place and can judge the shape of what the hub declined to model. |
| Threshold on row count alone | A table with no recorded `rowCount` is reported as unknown and still requires a decision: not knowing its size is not evidence that it is empty. |

### Consequences

The CLdN hub reports 56% decision coverage — 42 bound, 0 disposed, 33 undecided of 75 — and 22
blocking errors. Closing them is a human pass over tables that were, until now, invisible.
