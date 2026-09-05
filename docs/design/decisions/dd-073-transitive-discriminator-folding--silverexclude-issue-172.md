# DD-073: Transitive discriminator folding + silverExclude (issue #172)

**Status:** Accepted
**Date:** 2026-06-14
**Affects:** `src/kairos_ontology/projections/medallion_silver_projector.py`,
`src/kairos_ontology/scaffold/kairos-ext.ttl`,
`kairos-design-silver` SKILL.md (+ scaffold copy)
**Implementation:** `_nearest_claimed_ancestor()` (new), URI-keyed `folded_subtypes`,
bounded-ancestor merge in the S3 post-pass, `silverExclude` filter +
`_warn_silver_exclude_dependents()`.

### Context

Two related gaps in the silver projector:

- **B (bug).** S3 discriminator folding inspected only the **direct**
  `rdfs:subClassOf` parent. A subtype reaching a claimed discriminator ancestor
  only through **unclaimed** intermediates (e.g.
  `VesselCarrier → ShipOperator(unclaimed) → Organization(discriminator)`) was not
  folded and got its own near-empty ROOT table.
- **A.** Silver had no way to keep a class in the ontology (for inheritance /
  semantics) while suppressing its physical table — gold already had `goldExclude`.

### Decision

**B — transitive fold.** `_nearest_claimed_ancestor()` walks `rdfs:subClassOf`
breadth-first, traversing **only unclaimed** intermediates, and returns the
**first claimed ancestor**. The pre-scan classifies a class by that ancestor's
strategy (`discriminator` → fold; else → TPC). The S3 post-pass now merges the
subtype's own properties **plus those of the unclaimed intermediates up to the
claimed fold target** (achieved by passing `class_uris` to `_add_data_properties`
and `inherit_ancestors=True` to `_add_object_property_fk_cols`, since
`_get_class_and_ancestors` already stops at claimed ancestors). `folded_subtypes`
is URI-keyed (not name-keyed) for namespace safety. Traversal is deterministic
(sorted URIs); conflicting strategies among same-depth claimed ancestors emit a
warning and pick the lexicographically smallest URI. **Depth-1 single-inheritance
behaviour is byte-identical.**

**A — `silverExclude`.** A new `kairos-ext:silverExclude` boolean annotation
filters classes out of `domain_classes` (mirroring gold's `goldExclude`). It
**overrides** `silverInclude` / `silverIncludeImports`. An excluded class behaves
like an unclaimed / cross-domain FK target; descendants still inherit its
properties. `_warn_silver_exclude_dependents()` warns when a materialised class
subclasses or FK/junctions to an excluded class.

### Rationale

Walking only through unclaimed intermediates and stopping at the first claimed
ancestor contains the blast radius and keeps existing single-level folds
unchanged, while fixing the multi-level case. Reusing `_get_class_and_ancestors`'
existing "stop at claimed" semantics gives the bounded property merge for free.

### Consequences

- **Out of scope (pre-existing, documented):**
  1. A claimed TPC intermediate that is itself folded and still referenced by a
     descendant produces the same inconsistency today via direct-parent logic;
     this change does not worsen it.
  2. `_has_max_cardinality_1(graph, cls_uri, prop)` checks the child, not the
     property's domain ancestor — an inherited FK arising solely from a
     cardinality restriction on an ancestor is still skipped. Independent of #172;
     the common FK signals (`silverForeignKey`, `owl:FunctionalProperty`,
     `silverColumnName`, datatype properties) all fold correctly.
- Scenario coverage added to `tests/scenarios/acme-hub` additively (a separate
  `Organization → ShipOperator → VesselCarrier` chain + a `BaseMarker`/`ActiveMarker`
  exclude case) so existing logistics asserts stay green. Unit tests added to
  `tests/test_silver_projector.py`.
