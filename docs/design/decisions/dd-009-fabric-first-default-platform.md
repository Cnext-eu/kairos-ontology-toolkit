# DD-009: Fabric-First Default Platform

**Status:** ~~Superseded by [DD-215](dd-215-the-target-platform-names-the-engine-and-boolean-ness-is-rendered-per-adapter.md)~~
**Date:** 2026-04-30
**Affects:** `DEFAULT_PLATFORM` constant, dbt_project.yml scaffold
**Implementation:** `medallion_dbt_projector.py: DEFAULT_PLATFORM` (retired v4 projector only)

> **Superseded.** The v5 compile path applies **no** default: it reads `adapter:` from
> `kairos.yaml` and fails closed when it is absent or unsupported, so nothing is ever
> silently compiled as Fabric. `init --adapter` makes the choice explicit at scaffold
> time instead of inheriting one. The `DEFAULT_PLATFORM` constant this decision named
> survives only in the retired v4 projector. DD-111 had already narrowed it
> ("Platform generation is governed by DD-111 capabilities"); DD-215 retires it.

### Context

Need a sensible default when `target_platform` is not explicitly set.

### Decision

Default to **Microsoft Fabric** (`"fabric"`).

### Rationale

- Primary deployment target for Kairos Community Edition users
- T-SQL is the dominant SQL dialect in the Microsoft data ecosystem
- Databricks users must opt-in with `target_platform="databricks"`
- Fabric is the target for DirectLake + Power BI gold layer
