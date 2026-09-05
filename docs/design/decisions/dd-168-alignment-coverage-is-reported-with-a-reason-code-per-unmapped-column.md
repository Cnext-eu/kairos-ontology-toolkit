# DD-168: Alignment coverage is reported with a reason code per unmapped column

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `propose-alignment`, kairos-design-discovery
**Implementation:** `core/alignment_report.py`, `propose-alignment alignment-report`

### Context

Alignment finished with no statement of what it had *not* done. On the live corpus it
mapped 494 of 1,994 columns; the other 1,096 simply vanished from view. "75 tables aligned"
reads as completion. The first version of the report was worse than silence: it printed
"0 gaps" because it looked for `example_values` on entries that never carry that key, so
the no-evidence branch always fired and every gap was filtered away as noise.

### Decision

Every source column not bound to a reference property is reported with one code from a
closed set: `no-reference-property`, `low-confidence-suggestion`, `no-sample-evidence`,
`vendor-slot`, `operational`. Evidence is read from the source vocabulary, not from the
proposal. A column whose evidence cannot be established counts as a **gap**, never as
noise — the fallback must be the direction that gets a human to look.

### Consequences

`GAP_REASONS` names the two codes that mean the domain model is short of a property, which
is the subset that blocks (DD-169). Grouping by column name collapsed 1,096 gap columns to
609 distinct names, of which 258 recur across tables and cover 745 columns — the recurring
names are the tractable work.
