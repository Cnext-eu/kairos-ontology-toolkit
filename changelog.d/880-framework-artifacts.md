### Fixed
- **Ingestion-framework columns are auto-dispositioned instead of reaching the gap gate
  as business data.** `_rescued_data`, `_corrupt_record`, `ts_ms`, a SQL Server temporal
  period's `ttSys…` bounds and a stray pandas `__index_level_0__` are written by the tool
  that loaded the table, never by the business — but nothing recognised them, so they
  arrived as undecided gap columns and the recurrence heuristic proposed `blueprint-gap`
  for one of them, the disposition that asserts a reference-model defect to file
  upstream. They are matched as adjacent token pairs, because "rescued", "record",
  "index" and "ts" all occur in real business names and this classification silences a
  column without review. The pairs are shared between the classification and the
  cross-check that guards it, so the invariant that every operational name is also
  audit-named now holds by construction.
