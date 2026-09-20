### Fixed
- **The emitted dbt project parses again.** `dbt_project.yml` carried
  `require-dbt-version: '>=1.10'`, which dbt's own semver rejects — it requires all three
  version components, so dbt refused the whole project file with `">=1.10" is not a valid
  semantic version` before reading anything else, and `dbt deps` failed on every emitted
  medallion project. A two-part specifier is valid for pip and not for dbt; the floor is
  now spelled `>=1.10.0`, which is the same range. Regression tests assert three-part
  spelling for both the emitted floor and the scaffolded requirement, and check them
  against dbt's parser where dbt is installed.
