# DD-027: Cross-Domain Peer Extension Loading for FK Resolution

**Status:** Accepted
**Date:** 2026-05-27
**Affects:** `projections/shared.py`, `projections/medallion_dbt_projector.py`, `projector.py`
**Implementation:** `merge_ext_graph()` peer_ext_paths parameter; `_run_projection()` peer ext discovery

### Context

DD-019 introduced cross-domain FK resolution via surrogate key joins. However, when a FK
targets a class in another domain (e.g., `financial:chargeForShipment` → `consignment:Shipment`),
the projector could not resolve the target class's `kairos-ext:naturalKey` because it only
loaded the current domain's silver extension file. This forced hub authors to duplicate
naturalKey declarations in every referencing domain's extension file.

DD-023 introduced shared defaults as a fallback layer for reference models, but that mechanism
only addresses shared reference models — not peer hub domains.

### Decision

The dbt projector now loads **all** `*-silver-ext.ttl` files from the hub's `extensions/`
directory as "peer extension paths" for each domain projection. This enables cross-domain
naturalKey resolution without redundant declarations.

**Extended merge priority (highest → lowest):**

1. Hub domain extension (`{domain}-silver-ext.ttl`) — always wins
2. **Peer domain extensions** (other `*-silver-ext.ttl` files) — cross-domain annotations
3. Reference model defaults (DD-023 fallback layer)
4. Built-in projector conventions (rdfs:range inference)

**Override semantics:** Peer extension triples are only added when the subject+predicate pair
is NOT already declared in the domain's own extension (same as fallback semantics).

**Error handling:** Parse failures in peer extension files are silently skipped (graceful
degradation). A broken peer file does not break the current domain's projection.

### Rationale

| Approach | Pros | Cons |
|----------|------|------|
| Manual duplication | Explicit, self-contained | Doesn't scale; drift risk |
| **Peer ext loading (chosen)** | Zero duplication; works automatically | Cross-domain coupling |
| Shared global ext | Flexible | No clear ownership; hard to maintain |
| Require naturalKey in base ontology | Clean | Pollutes domain model with projection concerns |

The peer loading approach was chosen because:
- NaturalKey is inherently a projection annotation (belongs in ext files, not base ontology)
- Hub authors already have all ext files in one directory — the toolkit should leverage this
- Priority rules ensure domain-own annotations always win (no surprises)
- Existing workaround (manual duplication) remains valid but becomes unnecessary

### Consequences

- `merge_ext_graph()` gains a `peer_ext_paths` parameter (backward-compatible: defaults to None)
- `generate_dbt_artifacts()` gains a `peer_ext_paths` parameter
- `projector.py` collects all `*-silver-ext.ttl` paths before the domain loop and passes
  the peer list (excluding current domain's file) to each projection
- Existing hubs with duplicated cross-domain NK declarations continue working (redundant
  declarations are harmless — domain ext wins via priority)
- Future: same pattern could be applied to gold projector for cross-domain goldInclude resolution
