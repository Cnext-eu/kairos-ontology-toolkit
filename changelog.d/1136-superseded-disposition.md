### Added
- **`superseded`: a source table another binding replaced (DD-259, #1136).** Move a
  list's binding from an imported table to a shipped reference list's seed, and the old
  table keeps business data that nothing binds. The DD-169 gate then failed, and no
  disposition described the table truthfully. Hubs retired such tables by hand across
  nine files, and an operational system's next import restored them.
  - **Recording it.** `kairos-ontology source-disposition set --system <s> --table <t>
    --disposition superseded --superseded-by <binding metadata.name> --rationale "..."`
    decides the table and its columns, and stops `generate-bindings` from drafting a
    binding for it.
  - **Checks.** The command refuses a binding name that doesn't exist, and a table a
    binding still reads. `validate` fails with
    `disposition.superseded-by-unknown-binding` if the replacing binding later disappears.
  - **Docs.** The how-to *Use reference data and code lists* has a new section, "Replace a
    list you used to load from a source".
