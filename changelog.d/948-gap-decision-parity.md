### Fixed
- **`draft-gap-decisions` reported nothing to decide while `compile` blocked (#948).**
  Since #881 only a table-grain `not-business-data` or `blueprint-gap` answers for the
  table's columns in the DD-169 gate. The decision sheet and `--auto` were not updated,
  so a hub with table-grain `deferred` or `bound` entries saw the gate block on thousands
  of columns while the one tool meant to clear it said "0 decision(s) to make". The gate,
  the sheet, `--auto` and `--apply` now use one shared rule (`column_decision`), so they
  cannot disagree again.
  - `--apply` writes only the occurrences the sheet listed. An occurrence that already has
    a column decision keeps it, reported as `skipped_already_decided`, where it used to be
    overwritten by the name-level decision.
  - The unanchored-table gate (DD-180) no longer counts a column-grain entry as deciding
    the whole table.
  - `source-disposition set --disposition deferred` on a table no longer says its gap
    columns "now count as DECIDED". That stopped being true in #881; the message now says
    they still need deciding one by one.
- **`source-disposition clear` exists.** Several messages told you to undo an entry with
  it, but the command was never wired up. It filters by `--system`/`--table`, `--column`
  or `--table-grain-only`, `--disposition` and `--decided-by`, supports `--dry-run`, and
  refuses to run with no filter.

### Notes
- `update` and `update --check` now report table-grain `deferred` / `bound` /
  `registered-extension` entries that no longer decide their tables' columns, with the
  number of gap columns affected. This is advisory only and never changes the exit code.
  Decide the columns with `draft-gap-decisions --suggest`, then `--apply`, or withdraw the
  stale entries with `source-disposition clear --table-grain-only --disposition deferred`.
