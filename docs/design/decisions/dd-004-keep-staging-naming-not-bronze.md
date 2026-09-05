# DD-004: Keep "staging" Naming (Not "bronze")

**Status:** ~~Superseded by [DD-014](dd-014-eliminate-staging--silver-reads-bronze-directly.md)~~
**Date:** 2026-04-30
**Affects:** dbt model naming convention, folder structure
**Implementation:** N/A — staging layer removed

### Context

Medallion architecture uses "bronze" but dbt community uses "staging" for the first
transform layer.

### Decision

**Superseded.** There is no staging layer in the dbt project. Bronze is managed by
the data platform (outside dbt). Silver is the first dbt layer and reads from bronze
directly via `{{ source() }}`. See DD-014.
