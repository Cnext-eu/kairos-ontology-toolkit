# DD-038: Bronze Source Introspection & Layered dbt Architecture

**Status:** Proposed
**Date:** 2026-06-01
**Affects:** `integration/sources/`, `_sources.yml` generation, dataplatform repos, dbt projector
**Implementation:** See `docs/design/dd-038-bronze-introspection-architecture.md` for full ADR

### Context

Vocabulary TTL files (DD-015) are manually maintained bronze contracts. Actual lakehouse
tables drift over time. The hub's dbt projector generates `_sources.yml` with physical
database/schema info, coupling the hub to a specific environment.

### Decision

1. **Hybrid introspection pipeline**: Dataplatform extracts schema via dbt's
   `adapter.get_columns_in_relation()` → YAML → toolkit's `import-source` refreshes
   vocabulary TTL.
2. **Layered source separation**: Hub generates logical `{{ source() }}` refs without
   database/schema; dataplatform owns physical `_sources.yml` binding.
3. **Dataplatform scaffold**: New `init-dataplatform` CLI + skill to bootstrap consumer repos
   with dbt project, extraction macro, and toolkit as uv dependency.

### Rationale

- dbt adapter layer provides platform-agnostic introspection (no custom SQL)
- YAML intermediate is dbt-ecosystem aligned and human-readable
- Source separation follows dbt multi-project best practices
- Vocabulary remains the semantic contract; introspection keeps it current

### Consequences

- Existing dataplatforms need to add their own `_sources.yml` (breaking change, requires
  major version bump)
- Two-step refresh (extract + import) rather than fully automated
- JSON content_type requires manual annotation (adapters don't expose this)

  ---
