### Fixed
- **`import-tmdl` now reads a flat TMDL export, and names each export after its own model.**
  A Power BI export saved without the `definition/` wrapper drops every `<table>.tmdl` flat
  beside `model.tmdl`. The parser only ever looked in `definition/tables/`, so it read zero
  tables and reported every table the model declares as "absent from this export" — advice
  that could not be followed, because the files were in the folder it was pointed at. The
  engineering pack and concept-mapping worksheet came out empty, and `design-landscape`'s
  `bi_weight` and `draft-model-report` consumed nothing. A second defect compounded it: a
  flat export was named after its *parent* directory, so every export staged in one folder
  produced `<staging>-engineering-pack.md` and `<staging>-concept-mapping.yaml` and each
  import silently overwrote the last. Both layouts are now read, and an export names itself.
  Exports that genuinely omit table definitions still report them, unchanged.
