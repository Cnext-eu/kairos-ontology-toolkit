### Fixed
- **Code-list columns are no longer dropped when the bronze vocabulary is scanned.**
  `load_source_column_types` found a column only when `kairos-bronze:sourceTable` was its last
  triple. `import-source` writes `kairos-bronze:suggestedEnum` after it on code-list columns,
  so every such column was skipped: 117 of 359 on a client hub, among them the package and
  pack-type codes. `generate-bindings` lost their type hints, and the deferred backlog's
  sibling detection (#1077) missed their casing and so their siblings.
