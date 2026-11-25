### Fixed
- **`validate-dbt` accepts a contracted model that reaches Silver through another contracted
  model.** Since 5.33.0 the assembled package carries the properties of every contracted
  model. The manifest check then required each of them to have a Silver model as a *direct*
  dependent, which failed every multi-source hub: per-source models unioned into a conformed
  model reach Silver only through it. The check now walks dependents transitively, and still
  fails a contracted model, or chain of them, that reaches no Silver model.
