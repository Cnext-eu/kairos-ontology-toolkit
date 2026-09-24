### Added
- **`validate` checks every cross-domain join key against the parent's binding (#934).**
  An `externalReference.key` must name a column the parent *emits*, not a source column
  of the child's binding. `compile` checks this only against the parent's Silver
  contract, and most hubs author none. So a join on a column the parent never emits
  passed `compile --check`, emitted SQL and cleared `audit-silver-samples`, and failed in
  the warehouse. `validate` now derives the parent's columns from its binding (a
  `technicalFields` name, or else the mapped property's snake_case name) and warns on a
  key that is not among them (`relationship.external-reference-key-not-emitted`). Where
  the parent has a Silver contract, `compile` stays the authority.
- **`compile` says when it could not check a join key.** A new info-level note,
  `relationship.external-reference-key-unverified`, replaces the silence when no Silver
  contract declares the parent class. It never blocks.
- **A warning when a Silver model is mostly raw passthrough (#854).**
  `binding.carried-outnumbers-canonical` fires, per binding, when there are more
  `technicalFields` of `purpose: carried` than ontology-backed `fields:`. On one hub the
  ratio was 89 to 82, with columns that looked canonical downstream and were not.
- **`validate-dbt-contracts` enforces the dbt layering rule, as warnings (#949).**
  - `dbt-contract.merge-model-reads-source`: an `int_merged__` model calls `source()`.
  - `dbt-contract.staging-model-joins`: a `stg_` model joins.

  The managed `transforms/dbt/README.md` and the `kairos-develop-dbt-transformation`
  skill now state the three layers as rules, with migration steps: move each source's
  logic into its own `int_<source>__` model and compare Silver row counts and keys
  before and after.
