### Added
- **`propose-alignment` re-offers a closure candidate with the table's class pinned
  (#1051, DD-248 §4).** For a table whose unmatched columns have `closure_candidates`, one
  further call is made for those columns only, against the classes that own the
  candidate properties with those properties listed first, so the prompt's cut cannot
  drop them again. A mapping the retry makes is flagged `closure_retry: true` on the
  column; a `custom` answer leaves the first-pass entry and its candidates untouched.
  The merged result is what gets cached, so the cost is paid once per table.
  `--no-closure-retry` skips the pass and is part of the per-table cache key.
