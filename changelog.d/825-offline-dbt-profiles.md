### Fixed
- **`validate-dbt` passes offline on dbt-fabric 1.10.1 (#825).** The offline profile used
  service-principal authentication. dbt-fabric turns that into an `Authority Id`
  connection keyword, which the mssql-python driver in dbt-fabric 1.10.1+ rejects before
  connecting ("Unknown keyword 'authority id'"). So the gate could not pass on any
  current dbt-fabric, and hubs were pinned to exactly `dbt-fabric==1.10.0`. The profile
  now supplies an access token instead. Verified against dbt-fabric 1.10.0 and 1.10.1:
  both parse, then fail only at the connection attempt, which reads as
  `environment-blocked`, as the offline gate intends. The pin is now
  `dbt-fabric>=1.10.0,<1.11`; 1.11 needs dbt-core 1.11, which is outside the supported
  range.
- **`validate-dbt` no longer spends 120 s failing on databricks (#922).** dbt-databricks
  connects during `compile`, and its SQL connector retried name resolution 30 times, so
  the phase never finished and was reported as a timeout. The offline profile now makes
  one connection attempt with short timeouts, so compile reaches `environment-blocked`
  in seconds. The host is now a bare hostname: dbt-databricks adds `https://` itself, and
  the old value made its log blame a host named `https`.

### Notes
- Hubs scaffolded before this release pin `dbt-fabric==1.10.0` in their `pyproject.toml`.
  That keeps working, and they can widen it to `>=1.10.0,<1.11`.
