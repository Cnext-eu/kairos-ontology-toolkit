### Changed
- **`kairos-design-domain` now points at the gap decisions, not only at the alignment
  files.** The skill sent an author to `*-alignment.yaml` for drafted properties, which
  holds one for *every* unmappable column — including the ones a reviewer has since ruled
  out. Which were accepted lives in `gap-decisions.yaml` and the disposition ledger, and
  the skill never mentioned either, so a column dispositioned `deferred` or
  `not-business-data` could be modelled anyway, re-opening a decision someone had already
  made. The skill now names both files, says to design against the ledger, and points at
  `scaffold-extensions` for rendering the accepted ones as a reviewable diff.
