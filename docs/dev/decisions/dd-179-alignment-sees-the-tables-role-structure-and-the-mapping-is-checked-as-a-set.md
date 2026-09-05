# DD-179: Alignment sees the table's role structure, and the mapping is checked as a set

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `propose-alignment`
**Implementation:** `core/propose_alignment.py` (`group_columns_by_role`, `format_role_structure`, `flag_role_collisions`)

### Context

The prompt presented source columns as a flat list, one line each, and asked for a
property per column. The reference-model side was already graph-shaped — DD-172 renders
`hasShipper (Organization) [OBJECT PROPERTY]` — but the source side was not, so the
strongest signal a flat table carries was left on the floor.

A flat table hides its relationships in its naming. `shipper_code`, `shipper_name`,
`consignee_code`, `consignee_name` is not four unrelated columns: it is two references
to the same kind of entity, in two different roles. That is exactly what distinguishes
`hasShipper` from `hasConsignee`, two object properties with the same range that no
amount of per-column name similarity can separate. Presented flat, the model had to
rediscover the structure on every call, and nothing prevented it mapping both roles
onto one property — a mistake that is individually defensible for each column and only
visible when the set is examined together.

### Decision

The prompt gains an `APPARENT ROLE STRUCTURE` block listing columns grouped by shared
leading token, with the rule that two different groups must not map to the same object
property. Separately, `flag_role_collisions` checks the finished mapping as a set and
records a `role-collision` flag on the table when two distinct roles do land on one
property.

Grouping is deliberately conservative, because a false group asserts a relationship the
data does not have. A group needs a shared leading token, at least two members, no more
than half the table (beyond that it is the table's *subject*, not a related entity),
no structural token like `is`/`created`/`total`, and at least one member that actually
identifies or names something (`code`, `name`, `id`, `key`, `ref`, …).

That last condition came from the corpus, not from theory: a prefix-only rule produced
`ActualDate`/`ActualTimeFrom` and `KmLoadingTotal`/`KmUnloadingTotal`, which share a
prefix for reasons unrelated to entity identity. With it, 98 of 150 source tables carry
a role structure, and they are the right ones — `origin(16)`/`destination(16)` on the
orders table, `pickup(8)`/`delivery(8)` on stops.

The guard flags and never blocks. Two roles legitimately share a property when the
reference model is deliberately coarser than the source, and that is a design decision
for a human, not an error to reject automatically.

### Consequences

Measured on the party domain, three parallel runs: recall rose from 24-25 columns to a
steady **28** (+15%), with stability at 93% — inside the 82-100% band established in
DD-177, and traded for materially more coverage on the axis that was weakest.

The guard immediately earned itself, firing identically on all three runs: the `company`
and `reference` roles both mapped to `partyIdentifier`. That is precisely the failure
this decision exists to surface — plausible per column, wrong as a set.

One honest cost: a single column mapped to different properties across runs, where
earlier configurations had shown zero such conflicts. More columns attempted means more
opportunity to disagree.

A table with no role group renders no block, so its prompt is byte-identical to before,
and `consistency_flags` is emitted only when a rule fires.

Declared relationships from Power BI semantic models (`import-tmdl` already parses 17 of
them across this hub's two models) remain unused. They are real relational evidence, but
the BI table names are the semantic model's, not the source tables' — wiring them in
needs a name-resolution step that this decision does not attempt.
