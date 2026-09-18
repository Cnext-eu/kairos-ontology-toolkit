### Fixed
- **`import-tmdl` no longer reports an incomplete export as an empty model (issue #807).**
  Table discovery was a glob over `definition/tables/`, and the `ref table` pointers in
  `model.tmdl` — which name every table the model expects — were never read. An export
  shipped without its table bodies therefore produced `Tables: 0`, `tables: []` and a
  success exit, indistinguishable in every artifact written from a model that genuinely
  has no tables. Downstream, `design-landscape` then reported no BI weight for it and gave
  no hint anything was missing; on one hub that hid a 34-table / 375-field / 163-measure
  semantic model, the largest piece of BI demand evidence available. `import-tmdl` now
  names the unresolved pointers in a warning and in an `## Incomplete Export` section of
  the Engineering Pack, and qualifies the table count rather than printing a bare zero.

### Added
- **`import-tmdl --fail-on-partial`** exits non-zero when any `model.tmdl` declares tables
  its export does not contain. Off by default, since a batch import of many exports should
  not fail wholesale because one of them is incomplete.
