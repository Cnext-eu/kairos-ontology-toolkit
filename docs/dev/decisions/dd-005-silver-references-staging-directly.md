# DD-005: Silver References Staging Directly

**Status:** ~~Superseded by [DD-014](dd-014-eliminate-staging--silver-reads-bronze-directly.md)~~
**Date:** 2026-04-30
**Affects:** Silver model generation, dbt DAG structure
**Implementation:** Silver models use `{{ source('system', 'table') }}` directly

### Context

Should silver models reference staging directly or go through a bridge layer?

### Decision

**Superseded.** Silver now references bronze directly via `{{ source() }}` — there
is no staging layer at all. See DD-014.
