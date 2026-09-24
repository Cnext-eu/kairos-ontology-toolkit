### Changed
- **`scaffold-staging` generates all three dbt layers (#949).** For each `--source` it
  now writes an `int_<source>__<entity>` model between the `stg_<source>__<entity>`
  stage and `int_merged__<entity>`. That model starts as a passthrough and is where the
  source's joins, filters, main-record rankings and code mapping go. The merge model now
  reads only the `int_<source>__` models, never a stage or `source()`. Adding a third
  source then means adding its own `int_` model, not editing the merge. What the
  scaffold writes passes the `validate-dbt-contracts` layering warnings added in
  5.22.0rc1. The `kairos-develop-dbt-transformation` skill and its examples follow the
  same rule.
