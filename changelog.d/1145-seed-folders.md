### Fixed
- **`export-reference-list` regenerates a seed in the folder it is in.** It used to write
  and compare every generated seed at the seeds root. A seed moved to a subfolder then
  failed `--all --check` in `pr-validate`, and `--all` wrote a second copy at the root.
  Both `--all` and the single-class form now find the seed by name anywhere under
  `seeds/`, and refuse a name found in more than one folder.
- **Two seeds of one name in different folders are an error.** dbt names a seed by its
  file name, whatever its folder, and refuses a project with two of them. The bundle only
  compared paths, so it emitted both. `validate-dbt-contracts` now reports
  `dbt-contract.seed-duplicate-name`, and `compile --emit` fails on it. Seed lint findings
  name the seed's real path instead of `seeds/<name>.csv`.

### Changed
- **A new generated seed goes to `seeds/reference/` (DD-260).** `export-reference-list`
  writes there unless the hub already keeps generated seeds at the seeds root, so an
  existing hub does not split. `--dir` chooses another folder. To adopt the layout, move
  each generated seed's `.csv` and `.yml` to `seeds/reference/`; `--all` follows them.

### Documentation
- **Organise the seeds folder by kind.** The how-to *Use reference data and code lists*
  gains a section on keeping generated seeds, extensions, crosswalks and hub-owned lists in
  their own folders, with a `CODEOWNERS` example, and why a prefix per kind would break
  every `ref()`.
