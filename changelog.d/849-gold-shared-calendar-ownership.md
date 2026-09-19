### Fixed
- **Two domains with an approved calendar can now compile into one target (issue #849).**
  An approved `kairos-ext:calendarProfile` renders to `models/gold/shared/dim_date.sql`,
  deliberately outside the declaring domain's tree because one hub materializes one
  governed calendar. But `cli/compile.py` did not recognise that subtree as shared, so
  those files were claimed by the **per-domain** manifest — and the second domain in a hub
  to author an approved calendar could not `compile --emit` at all:

  ```
  ArtifactCollisionError: artifact destination collides with an unowned path:
  'models/gold/shared/_shared__gold_models.yml'
  ```

  The message named a path the author never wrote and gave no hint that two calendars were
  the cause. `models/gold/shared/` now belongs to the shared manifest, like every other
  cross-domain artifact.

### Changed
- **`_shared__gold_models.yml` records every contributing calendar profile, not the last
  one to compile.** Two domains declaring the same bounds render a byte-identical
  `dim_date.sql` and differ only in the profile URI recorded as provenance — one table
  with two contributors, not a conflict. `calendar_profile` stays a scalar while one
  domain declares it, so every hub shipping today is byte-for-byte unchanged, and becomes
  a sorted list once several do.

### Notes
- A **genuine** disagreement still fails, and now says why. Domains declaring different
  bounds, week patterns or fiscal year starts describe one physical table two incompatible
  ways; reconciling that silently would be worse than the collision it replaces. The error
  names the field that differs and both values, rather than a path.
- Found while building #829, which needs the same subtree to be hub-owned; fixed on its
  own because it blocks any two-calendar hub regardless of Gold products.
