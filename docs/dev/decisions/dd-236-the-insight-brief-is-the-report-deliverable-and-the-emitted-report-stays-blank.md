# DD-236: The insight brief is the report deliverable and the emitted report stays blank

**Status:** Accepted
**Date:** 2026-09-24
**Affects:** `emit-gold` (`core/projections/dbt/gold_render._blank_report`), the
`kairos-design-gold` skill, `how-to/design-a-gold-product.md`
**Issue:** #830 (split out of #744 Part 4)

### Context

`emit-gold` produces a semantic model that opens in Power BI Desktop, a per-persona insight
brief (DD-223) and a `.Report` with one empty page. DD-223 stated "a brief, not a report"
but left the question open: "Generating PBIR pages is explicitly not decided here", and
listed report generation under "Deliberately not decided". So the blank report read as an
unfinished feature rather than a decision. That was the actual cost of leaving it untracked.

Two arguments recorded on #744 argued against generating visuals:

- It would mean vendoring Microsoft's `visualContainer` schema family and tracking its
  versioned releases. The package validator is fail-closed on unresolved schema references
  and today vendors only the wrapper schemas. That would be a standing maintenance
  commitment with a different risk profile from everything else in Gold.
- It would put look and feel inside the hub, which contradicts the boundary DD-222 and
  DD-223 draw: the hub owns the model and the evidence, and the BI engineer owns the report.

### Decision

The insight brief is the report deliverable. `<product>-insight-brief.md` states which
question each measure answers, for whom, against what comparison, and whether the model can
answer it. It is what a BI engineer, or Fabric Copilot, builds the report from.

The emitted `<Product>.Report` stays intentionally blank. It is one empty page bound to the
generated model, and it exists only so the project opens. The toolkit does not generate
pages, visuals, bookmarks or a theme, and it does not vendor the visual-container schemas.
This answers the question DD-223 deferred.

### Consequences

- The report is built as a separate Fabric item with its own name, bound to the deployed
  model. The generated `.Report` is republished on every hub release, so edits to it are
  lost; `harvest-gold` (DD-224) is the route for turning a Desktop edit into a hub change.
- Rejected: a default page per persona built only from wrapper-schema constructs, and a
  PBIR skeleton for a human to fill. Both put layout decisions in the hub for little gain
  over a brief a person, or Copilot, reads in a minute.
- Still open: a hub-wide theme and feeding insight demand into `design-landscape`, as DD-223
  lists them. They are unaffected by this.
