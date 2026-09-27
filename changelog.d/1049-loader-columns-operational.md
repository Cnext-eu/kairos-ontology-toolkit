### Fixed
- **Bookkeeping columns your bronze loader adds no longer block `compile --check`.** Columns
  such as `_source_file`, `_row_key`, `_parent_row_key` and `_idx` are written by the hub's
  own bronze loader, not by the source system, but the gap report filed them under
  `no-reference-property`. `draft-gap-decisions --auto` left them undecided and the DD-169
  gate failed with `alignment.gap-column-undecided`: 86 such columns on one hub. The gap
  report now classifies them `operational`, which takes them out of the gate, and `--auto`
  records the file and load bookkeeping (`_source_file`, `_load_ts`) as
  `not-business-data` without holding it back as a conflict. The loader's row-identity
  columns (`_row_key`, `_parent_row_key`, `_idx`, `_line_no` and similar) are left
  unrecorded and counted as "left for grain": a `not-business-data` entry would hide them
  from `anchor-tables`, and on an array-expanded child table they are the row's only
  identity. A name only matches when it
  starts with an underscore and the rest is a small, fixed set of loader names
  (`source_file`, `file_name`, `row_key`, `parent_row_key`, `row_id`, `idx`, `index`,
  `line_no`, and names starting with `load`, `batch` or `ingest`), so `source_file` with no
  underscore is still a gap. A source's own underscore-prefixed message envelope
  (`_message_code`, `_message_send_date`) is left out on purpose because it is source data.
  The operational-column filter on proposed grains is unchanged, so `anchor-tables` still
  proposes `(_parent_row_key, _idx)` as the grain.
