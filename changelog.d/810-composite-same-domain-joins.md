### Added
- **A same-domain relationship may now join on a composite key.** The cross-domain shape
  always could — `externalReference.key` is a list and `target_columns` was built from all
  of it — but the same-domain branch truncated to `relationship.on[0]` and two guards
  rejected the shape before it got there, reporting
  `safety.adapter-unsupported: composite relationship joins are deferred beyond the v5
  first slice`.

  Nothing downstream needed changing: `JoinSpec` already carried a source column per entry
  in `relationship.on`, and the renderer already zipped those against `target_columns`
  with `strict=True` and joined them with `AND`. A two-column join now emits
  `on src.A = parent.A AND src.B = parent.B`, as the cross-domain form always did.

  This matters for any hub whose parent entity has a composite natural key. On the hub
  this was found against, the unit entity could not be related to the leg entity carrying
  its route and sailing date — the leg's key is three columns — so the Power BI volume
  model the hub exists to serve had every ingredient in Silver and no way to join them.

  The join's local columns must still be materialized on the child, by a `fields:` entry
  or a `technicalFields` carrier; that requirement is unchanged and the diagnostic already
  names it.
