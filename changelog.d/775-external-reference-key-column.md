### Fixed
- **`compile --check` now rejects an `externalReference.key[].column` the parent domain's
  contract does not materialize (#775).** The key names the *parent's* output column, but the
  rename that produces that column happens in the parent's binding -- so the source-side name is
  the one an author has just been looking at. Four bindings in one hub drifted the same way
  independently, all four passed CI, `--emit` rendered joins against a column that does not
  exist, and the failure surfaced only when a downstream dataplatform ran `dbt run` against a
  real warehouse, taking five Silver models and three Gold facts with it. Nothing needed to
  change about per-domain statelessness to catch it: `discover_contract_paths` already admits a
  foreign domain's contract whenever this domain points a relationship at a class it declares,
  and already hashes it into provenance -- it was simply never parsed. The check consults the
  parent's *declared* interface (DD-213), never its emitted artifacts, and is keyed on the
  resolved target class rather than the model name. New diagnostic
  `relationship.external-reference-key-column-unknown`, which lists the parent's available
  columns. Fails open by construction: an ungoverned parent compiles exactly as it did before.
