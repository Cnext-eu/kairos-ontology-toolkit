# DD-173: Reference models resolve live; there is no inventory

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** all reference-model consumers
**Implementation:** `core/class_anchoring.py` (`read_reference_terms`), `core/ontology_loader.py`

### Context

A materialized inventory sat between the resolver and its consumers, kept honest by a
freshness gate. DD-172 showed what that costs: when the resolver was fixed, every cached
inventory kept the old wrong answer, and the fast path *preferred* the cache — so the hubs
that had an inventory were exactly the hubs that stayed broken. The freshness gate could
not see this, because the snapshot was perfectly fresh with respect to a stale resolver.

### Decision

Delete the inventory. `read_reference_terms` resolves live from the catalog through the
canonical loader (DD-103) on every call. `generate-inventory`, `check-inventory` and the
freshness gate are removed with no compatibility shim.

### Consequences

Nothing can drift from the resolver, because nothing is stored. Module selection excludes
the hub's own `model/ontologies` by resolved path — an earlier hostname filter also
excluded every other vendor and all test fixtures.
