### Fixed
- **A bridge endpoint that is also a Silver relationship is emitted once.** A bridge whose
  endpoint binding named a column its own EntityBinding already relates (the usual case: a
  party-role link table relating both the consignment and the party) got that relationship
  twice, once from Silver and once from the bridge. Power BI keeps one relationship per
  pair active, so the copy was written `isActive: false`, reported as
  `gold.role-playing-dimension` naming the same column as both the active and the inactive
  role, and the bridge's cross-filter direction was never decided. The Silver edge is kept,
  so existing relationship identities do not change.
