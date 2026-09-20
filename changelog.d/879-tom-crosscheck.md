### Added
- **`import-tmdl` cross-checks its reading against the Microsoft TOM SDK.** The toolkit
  already bundled the real SDK, but only on the write path, where it checks that TMDL the
  toolkit *generated* will open. It now points the same engine — the one Power BI Desktop
  and Fabric use — at the export being imported, and reports where the two readings
  differ: tables the SDK reads and the import did not, measures or columns read short,
  and exports the SDK rejects outright.

  Advisory and automatic: it runs whenever `dotnet` is on PATH, is silently skipped
  otherwise, and never blocks an import. A disagreement is written into the engineering
  pack above the inventory it qualifies, not only logged, because the operator who needs
  it is the one opening the pack later and wondering why it is thinner than the report
  they remember.

  Measured against two real Power BI exports: one agreed exactly (7 tables, 48 columns,
  59 measures, 6 relationships), and one was rejected by the engine as unopenable —
  where the parser had reported a well-formed model with zero tables and thirty-three
  relationships, which nothing downstream can distinguish from a model that genuinely
  has none.

  This is option 3 of the three in the issue. It does not settle whether the SDK should
  *replace* the hand-rolled parser, which is a product call about making `dotnet` a
  prerequisite for BI import; it does start producing the evidence that call needs.

- **The bundled TMDL validator reports an inventory, not just a table count.** Table
  names with their column and measure counts, plus the relationship count, so a
  disagreement can name what is missing rather than only that something is.
