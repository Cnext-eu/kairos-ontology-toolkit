# DD-003: Staging = Platform-Specific, Silver = Portable

**Status:** ~~Superseded by [DD-014](dd-014-eliminate-staging--silver-reads-bronze-directly.md)~~
**Date:** 2026-04-30
**Affects:** Template selection logic in `_gen_staging_models()`, silver model generation
**Implementation:** `staging_model.sql.jinja2` (Fabric), `staging_model_databricks.sql.jinja2`

### Context

Should we generate one set of models for all platforms or separate per platform?

### Decision

**Superseded.** The staging layer has been removed entirely (see DD-014).
Silver now reads directly from bronze and handles all platform-specific logic
via `dbt_utils` macros and generated platform macros.

Original decision was: Platform-specific staging templates, portable silver via `dbt_utils`.
