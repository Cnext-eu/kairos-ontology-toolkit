### Fixed
- **Authored dbt tests are published with the contracted closure (#1152, DD-261).**
  `compile --emit` used to publish a closure model's `.sql` but not its properties file
  unless a binding selected that model, and it never published singular tests under
  `integration/transforms/dbt/tests/`. Those tests never ran in the dataplatform, and nothing
  reported it. Now:
  - the properties file of every closure model, such as an `int_<source>__*` or `stg_*`
    model's `.yml`, is published whole, with its `data_tests`;
  - a singular test is published when every `ref()` it makes resolves to a published model or
    seed. It is emitted under `tests/` as the new dependency kind `test`;
  - a generic test definition is published when a published properties file applies it;
  - a test that reads the closure but also an unpublished model or an undeclared `source()`
    warns `dbt-source.test-not-published`.

  **On upgrade, review your tests:** tests that were silently dropped now run in the
  dataplatform, and one that was wrong all along can fail its build. A publish tree written
  by this release carries the new `test` kind, which an older toolkit rejects.
