# DD-023: Shared Extension Defaults for Reference Models

**Status:** Proposed
**Date:** 2026-05-19
**Affects:** silver projector, gold projector, dbt projector, `projector.py`, `catalog_utils.py`, `shared.py`
**Implementation:** `src/kairos_ontology/projector.py`, `src/kairos_ontology/catalog_utils.py`, `src/kairos_ontology/projections/shared.py`

### Context

When a hub domain imports a reference model via `owl:imports` and claims imported classes for silver projection (DD-021), the hub must still provide per-class silver extension annotations (scdType, naturalKey, silverDataType, silverForeignKey, etc.). When multiple hub domains — or multiple hub repos — import the same reference model, the same extension annotations are duplicated in each hub's extension file.

This creates maintenance burden and inconsistency risk: if the reference model evolves, every downstream hub must independently update their extension annotations.

### Decision

Reference model repositories may ship **default extension files** alongside their ontologies:

- `{ontology-stem}-silver-defaults.ttl` — default silver annotations
- `{ontology-stem}-gold-defaults.ttl` — default gold annotations

The toolkit's projection pipeline discovers these via catalog resolution and loads them as a **fallback layer** beneath the hub's own domain extension.

**Merge priority (highest → lowest):**

1. Hub domain extension (`model/extensions/{domain}-silver-ext.ttl`)
2. Reference model defaults (discovered alongside catalog-resolved imports)
3. Built-in projector conventions (rdfs:range → SQL type inference)

**Override semantics:** Fallback triples are only added when the subject+predicate pair is NOT already declared in the hub domain extension. This ensures hub-local annotations always win.

**Discovery mechanism:** When the catalog resolves an `owl:imports` URI to a local file path, the toolkit looks for a sibling file matching `{stem}-silver-defaults.ttl`. Falls back to checking a sibling `extensions/` directory.

**Key capability:** `silverInclude` may be declared in defaults files — allowing reference models to pre-declare which classes are suitable for silver materialization, eliminating the need for each hub to repeat these claims.

### Rationale

| Approach | Pros | Cons |
|----------|------|------|
| Manual extension per hub | Full control | Duplication, inconsistency across hubs |
| Auto-include all imports | Zero config | Pollution from large ref models (FIBO) |
| Shared defaults (this) | Single source of truth, hub can override | Requires convention; ref model repo must be toolkit-enabled |
| Domain-local subclasses | Full OWL control | Semantic drift, property duplication |

The shared defaults pattern was chosen because:
- It eliminates duplication across hubs importing the same reference model
- Hub authors retain full override capability (domain ext always wins)
- It is fully backward-compatible (hubs without defaults work unchanged)
- Reference model repos are just standard ontology-hubs with the toolkit installed
- The convention is simple and discoverable (sibling file naming)

### Consequences

- Reference model repos should ship `*-silver-defaults.ttl` and/or `*-gold-defaults.ttl` alongside their ontology files.
- The `merge_ext_graph()` function gains a `fallback_paths` parameter for layered merging.
- A new `resolve_import_paths()` utility in `catalog_utils.py` exposes catalog-resolved paths.
- A new `_discover_ref_model_defaults()` helper in `projector.py` locates sibling defaults files.
- `silverInclude` / `goldInclude` annotations in defaults files are inherited by downstream hubs.
- No changes required for existing hubs — the feature is purely additive.
