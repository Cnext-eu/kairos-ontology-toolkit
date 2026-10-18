### Added
- **`kairos-ontology export-reference-list <class> --domain <domain>` writes a shipped
  reference list as a dbt seed (#1126 P2, DD-257).** Pass a list the reference models ship
  with members (UNECE Rec 19/20/21, ISO 3166 countries and subdivisions …) or your
  governed class that such lists subclass.
  - **The seed.** One row per member under `integration/transforms/dbt/seeds/`, keyed on
    `(code_list, code)`, with the upstream IRI as a column.
  - **Its docs.** They record each list's snapshot version and source, and type every
    column as your adapter's text type, so codes such as `02` keep their leading zero.
  - **Safe re-runs.** Re-run after each reference-models upgrade. `--check` writes nothing
    and exits 1 when the seed is stale. The command refuses to overwrite a seed it did not
    generate (`--force` overrides), never touches the `<name>_local` extension seed, and
    refuses a class with no members (a hub-loaded or client-owned list).
