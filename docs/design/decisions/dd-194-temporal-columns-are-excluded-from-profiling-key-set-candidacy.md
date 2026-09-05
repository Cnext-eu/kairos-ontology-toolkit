# DD-194: Temporal columns are excluded from profiling key-set candidacy

**Status:** Accepted
**Date:** 2026-08-19
**Affects:** `core/profile_sources.py` (`profile_table`)
**Found on:** a client hub (real client extracts) — the first hub run of `profile-sources` against a corpus DD-189 was never built or tested against.

### Context

A unique, timezone-aware timestamp column crashed `profile-sources` outright:
`arr.drop_null().to_pylist()` on a tz-aware Arrow timestamp needs a tz
database, which a bare Windows Python install does not ship (`ArrowInvalid:
The zoneinfo module or pytz package must be installed`) unless the `tzdata`
package happens to be present. The column had qualified for key-set
construction only because it was tagged `unique` — the same path any
identifier column takes.

### Decision

`profile_table` excludes temporal-typed columns from key-set construction
outright (`not pa.types.is_temporal(arr.type)`), not merely by handling the
conversion error. Two independent reasons, either sufficient alone:
containment-matching a timestamp value against another table's timestamp
column is never a meaningful join signal the way an identifier's is, and the
crash is real on a platform without a tz database regardless. The column
still gets its `unique`/`date-like` tags (unaffected) — only key-set
candidacy is excluded.

### Consequences

`profile-sources` no longer depends on the host having a timezone database
for hubs whose sources carry timezone-aware timestamps (many source systems do).
No behavioural change for identifier columns — the fix narrows an
over-broad candidacy check, not the join-evidence mechanism itself.
