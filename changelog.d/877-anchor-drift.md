### Added
- **`anchor-tables` reports what moved since the last run.** Anchoring is not reproducible
  at the prompt size it operates at — DD-177 recorded that for a 23 KB alignment prompt,
  and this one is 121 KB. Measured back to back on a real hub, with the prompt
  byte-identical across processes and the same seed sent and honoured: the anchor class
  moved on 12 of 39 tables, the natural key on 13, two tables were given entirely disjoint
  keys, and one was anchored in one run and unanchored in the next. Provider-side
  determinism is not on offer at that size, so the defect was never the movement — it was
  that a re-run overwrote every unpinned row in silence. DD-190 built sticky review
  statuses on the premise that review effort concentrates where it belongs, without ever
  saying where that is. The diff now names it: which tables moved, in which fields, with
  both values, and a separate note for `natural_key`, which is not an advisory label but
  the binding's identity and the silver contract's uniqueness test. Written to the console
  and into the artifact, so it survives the terminal that produced it. A first run reports
  nothing; an unchanged re-run says so.
