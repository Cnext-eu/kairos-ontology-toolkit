### Fixed
- **`owner-ambiguous` rows from `anchor-tables` are now listed under `--quiet` too.** The
  DD-247 lines that name each table kept in its first owner were printed at info level, so
  `--quiet` hid the worklist they exist to show. The `kairos-design-source` skill now says
  how to settle such a row, and that an anchors run is a draft: pin a judged row with
  `status: confirmed` or `edited` (#1040 follow-up).
