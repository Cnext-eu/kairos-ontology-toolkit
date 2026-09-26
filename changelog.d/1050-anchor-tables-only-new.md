### Added
- **`anchor-tables --only-new` anchors only what is new.** When a source is added to a hub
  whose anchors are done, a plain run re-proposed every existing row. About a quarter of
  those tables came back with a different anchor, and each of them was then re-aligned by
  `propose-alignment`, because the anchor is part of its cache key. With `--only-new`,
  every existing entry whose source schema is unchanged is kept verbatim and left out of
  the model call. Only tables with no entry, entries whose schema changed and `rejected`
  entries are anchored, and nothing is sent to the model when none are left. The default
  run is unchanged (#1050).

### Fixed
- **A pinned anchor row is no longer released by a column exclusion recorded after
  anchoring.** The DD-190 schema hash, which decides whether a `confirmed` or `edited` row
  is kept, was computed after the disposition ledger's exclusions, not from the source
  schema. Every gap decision that excluded a column therefore changed the hash and
  released the pin, although nothing in the source had changed. On the GDW hub, with 749
  exclusions, 2 of 107 rows still matched. The hash now covers the raw source columns.
  A row stamped with the old hash is still accepted when that hash matches, and is
  re-stamped. A row whose exclusions changed since it was written is re-proposed once
  (#1050).
- **A re-run that only adds tables no longer prints an empty `DRIFT` headline** or the
  reproducibility warning; it says no existing entry moved and lists the new tables.
