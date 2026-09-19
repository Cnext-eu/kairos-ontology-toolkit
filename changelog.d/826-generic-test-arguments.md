### Fixed
- **Generated properties YAML no longer emits generic tests in dbt's deprecated top-level
  argument form (issue #826).** dbt 1.10 moved a generic test's arguments under an
  `arguments:` key. The toolkit was half converted: its own tests nested correctly while
  the two `dbt_utils.unique_combination_of_columns` emissions kept the old form, so both
  shapes appeared in the same generated file. On dbt 1.12 each of those raises
  `MissingArgumentsPropertyInGenericTestDeprecation`, and dbt has them slated to become
  hard errors — at which point the emitted package stops parsing outright.

  This was invisible from the hub: it validated on dbt 1.10 while the dataplatform
  consuming its output ran 1.12, so deprecations emitted *by the hub* only surfaced
  *downstream*. That divergence closed with the version contract; this makes the emitted
  syntax match it.

  `config` deliberately stays at the top level — it scopes the test (the `where` clause
  that restricts a grain test to current rows) rather than being an argument to it, and
  nesting it would silently stop the scoping from applying.

### Notes
- Builtin `unique` and `not_null` were checked and are unaffected: they are emitted as
  bare strings or with `config` only, neither of which is a deprecated form.
