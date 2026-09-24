### Fixed
- **Alignment staleness now covers the resolved import closure, not only the activated
  module list (#865).** `design-landscape` reported an alignment as stale only when the
  blueprint added or removed an activated module. Two changes slipped past it: a
  reference-models upgrade that adds an `owl:imports` inside a module, and new classes in
  a module already imported. Both change the class inventory the alignment was built
  from, and both left the file silently stale.
  - `propose-alignment` now also records `resolved_closure_sha256`, a fingerprint of the
    canonical loader's closure hashes for the inventory it aligned against.
  - `design-landscape` recomputes it when the catalog is available, and reports a
    mismatch as "stale against the domain's resolved import closure".
  - An alignment written before this release has no fingerprint, and a check without a
    catalog has nothing to compare, so neither is reported as stale.
