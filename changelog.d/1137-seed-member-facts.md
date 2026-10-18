### Changed
- **A generated reference-list seed now carries its list's version and source, whether
  each code is withdrawn, and every fact the members state (DD-258, #1137).**
  `export-reference-list` used to write `code_list, code, name, iri` and nothing else. A
  hub had nowhere to read a list's version from, so it typed a snapshot date into SQL that
  no refresh would ever update. Withdrawn codes also came through as ordinary rows: on ISO
  4217 from SIX (reference models 1.42.0), that is 129 of 307.
  - **New columns.** Every row now has `list_version`, `list_source` and `deprecated`, then
    one column per datatype property of the members. For ISO 4217 those are
    `numeric_code`, `minor_unit`, `withdrawal_date` and `is_fund`.
  - **Withdrawn codes.** They stay rows, marked `deprecated=true`.
  - **Upgrading.** Every generated seed reads as stale until you run
    `kairos-ontology export-reference-list --all`, and `pr-validate`'s `--all --check`
    fails until you do. A contracted model that unions a `_local` seed with `select *`
    fails on the column count: name the columns.
  - **Currencies.** Bind them to `iso4217:CurrencyCode` (SIX), not
    `unece:CurrencyCodeList`, which lags ISO.
