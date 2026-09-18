### Fixed
- **The dbt `ref()` scan no longer warns on every contracted intermediate (issue #728).**
  `compile --check` and `compile --emit` each reported `ref('X') … matched no model in this
  domain's render scope` for every contracted model a Silver model reads — 24 unique
  warnings and 48 occurrences per CI run on one hub, with a **100% false-positive rate**.
  It was the single largest warning category in the PR gate, and it buried the warnings
  that mattered: 43 unresolved source paths and 2 undeclared PII properties.

  Two independent causes, either of which was enough on its own. `render_canonical_project`
  — the v5 render path — never passed `known_models` to the validation step at all, so the
  scan always ran against an empty set. And the set it would have passed was empty anyway,
  because `BoundSources.contracts` is hard-coded empty on the v5 binding path, so even a
  binding's own directly-bound contract was unknown to the scan. The comment in `render.py`
  claimed the scan saw "the directly-bound contract names", which had not been true.

  The model names now come from `SourceTableFact.ref_model`, already set wherever a
  resolved relation is a dbt model, so no new plumbing from the kernel was needed. The
  check is not weakened: a `ref()` naming something that is neither a rendered model nor
  any binding's declared contract is still reported.

### Known issues
- A `ref()` between two copied intermediates is still outside this scan's view; the
  authoritative whole-project check remains `validate-dbt`, which the scaffolded PR gate
  runs.
