### Changed
- **The disposition ledger is one file per source system (#943).**
  `table-dispositions.yaml` held every system's table and column decisions in one file,
  799 KB on one hub. It is now `src-<system>.table-dispositions.yaml`, one per source,
  in the same directory and with the same entry format. Commands read all of them as
  one ledger. The old single file is still read, and the first command that records or
  clears a decision splits it per system. No entry is lost: where both copies hold the
  same key, the per-system one wins, because it was written after the upgrade.

### Performance
- **Recording many decisions went from minutes to under a second (#943).**
  `draft-gap-decisions --apply` / `--auto` / `--accept-proposals` and
  `source-disposition set --all-tables` used to re-read and re-write the entire ledger
  once per column. 1,113 decisions took about 12 minutes, with no output, so the run
  looked like a hang. They now write each source system's file once per batch, and print
  one line per system as it is written. On a 1,127-entry ledger, 1,113 decisions take
  0.24 s.
- The ledger is parsed and written with PyYAML's C loader and dumper when available,
  about 5× faster for the same result. Output is byte-identical, which a test checks.
  This speeds up every `validate`, `compile` and `generate-bindings`, since each one
  reads the ledger.
- Writes are atomic (a temp file, then a replace), so an interrupted run cannot leave a
  half-written ledger. A ledger file that cannot be parsed is now refused instead of
  silently replaced.

### Notes
- `update` splits an existing `table-dispositions.yaml` per source system, and
  `update --check` reports the split without doing it. An entry with no `system` cannot
  be placed, so it stays in the old file, which then holds only such entries.
