# DD-169: The alignment gap is a hard stop before entity binding

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `compile`, entity binding, kairos-design-domain
**Implementation:** `core/alignment_report.py` (`undecided_gap_columns`, `GAP_RESOLUTIONS`)

### Context

Entity binding is the last point at which an omission is cheap. After it, an unmapped
column with real business signal is not merely missing — the binding asserts a shape that
says the model is complete, and every downstream projection inherits that claim.

### Decision

Gap columns carrying real signal and no recorded decision block the workflow before entity
binding. Not a warning: a stop. Clearing one is an explicit recorded resolution from
`GAP_RESOLUTIONS`, so "we looked at it and it does not belong" is a durable, auditable
answer rather than an absence.

### Consequences

The gate is deliberately upstream of the expensive stage. A gap found here costs a
decision; the same gap found after binding costs a re-model.
