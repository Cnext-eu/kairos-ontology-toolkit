### Fixed
- **Crosswalk checks accept a reference list's local extension codes (#1156).** The governed
  list is shipped plus local, but `validate-dbt-contracts` read only the generated seed a
  crosswalk's `relationships` test named. A crosswalk that mapped a source code to a code in
  the `<list>_local` extension seed then failed the PR with
  `dbt-contract.crosswalk-unknown-code`, although the mapping was correct. Pointing the test
  at the hub's union model instead skipped the offline check entirely. Now:
  - a seed target is read together with its `<target>_local` sibling. A code found only in
    the extension is no longer an error, but warns `dbt-contract.crosswalk-targets-shipped-only`,
    because dbt's test against the generated seed alone fails at build;
  - a model target that reads nothing but seeds, such as `int_reference__<list>`, is checked
    offline through those seeds. A model that reads a source or another model is still left to
    dbt.

### Documentation
- **Point a crosswalk's `relationships` test at the list as Silver sees it (#1156).** The
  reference-data how-to, the dbt-transformation skill and DD-257 now point the test at the
  contracted model that unions the shipped seed with its `_local` extension, not at the
  generated seed alone. Hubs whose crosswalks target a generated seed keep working; move the
  test once you add a local code, or when the new warning names one.
