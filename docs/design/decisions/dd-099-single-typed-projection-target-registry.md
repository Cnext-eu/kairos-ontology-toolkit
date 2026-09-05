# DD-099: Single typed projection target registry

**Status:** Accepted
**Date:** 2026-07-21
**Affects:** `src/kairos_ontology/core/projector.py`,
`src/kairos_ontology/cli/main.py`, `src/kairos_ontology/mdm/__init__.py`
**Implementation:** `TargetSpec` and `register_target()` in the core projector

### Context

Projection target metadata was repeated across `VALID_TARGETS`, an alias map,
medallion/architecture/post-domain sets, the `all` expansion, CLI choices, and a
separate external-target registry. Adding or renaming a target required coordinated
edits and could silently diverge in validation, dispatch, placement, or help output.

### Decision

Use one ordered, typed `TargetSpec` registry as the source of truth for canonical
names and aliases, exact output subdirectories and categories, execution phase,
`--target all` participation, and optional external discovery/project callbacks.
Derive the historical `VALID_TARGETS` list, canonical `all` expansion, alias
resolution, output routing, post-domain classification, external dispatch, and CLI
choices from that registry.

External packages register all metadata in one idempotent `register_target()` call.
Conflicting canonical names or aliases fail clearly. The CLI continues to import
`kairos_ontology.mdm` to trigger `mdm-profile` registration; core never imports MDM,
preserving the MDM-DD-002 one-way dependency.

### Rationale

One registration record makes target addition atomic and keeps user-visible order,
dispatch, and placement mechanically consistent. A typed external-dispatch field
retains extensibility without weakening the package boundary.

### Consequences

- Existing target order, output paths, `gold` → `powerbi`, CLI choices, and opt-in
  `mdm-profile` behavior remain unchanged.
- `VALID_TARGETS` remains available as a compatibility list but is refreshed only
  from the registry.
- External targets are excluded from `all` by default and can be registered
  repeatedly only when every metadata field and callback is identical.
