### Fixed
- **Bookkeeping columns your bronze loader adds no longer block `compile --check`.** Columns
  such as `_source_file`, `_row_key`, `_parent_row_key` and `_idx` are written by the hub's
  own bronze loader, not by the source system, but the gap report filed them under
  `no-reference-property`. `draft-gap-decisions --auto` left them undecided and the DD-169
  gate failed with `alignment.gap-column-undecided`: 86 such columns on one hub. The gap
  report now classifies them `operational`, and `--auto` records them as
  `not-business-data` without holding them back as conflicts. A name only matches when it
  starts with an underscore and the rest is a small, fixed set of loader names
  (`source_file`, `file_name`, `row_key`, `parent_row_key`, `row_id`, `idx`, `index`,
  `line_no`, and names starting with `load`, `batch` or `ingest`), so `source_file` with no
  underscore is still a gap. A source's own underscore-prefixed message envelope
  (`_message_code`, `_message_send_date`) is left out on purpose because it is source data.
  The operational-column filter on proposed grains is unchanged, so `anchor-tables` does
  not drop `(_parent_row_key, _idx)` from the row identity of an array-expanded child table.
