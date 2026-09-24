### Changed
- **The hub PR gate checks the architecture diagrams in their own parallel job.**
  `pr-validate.yml` used to regenerate and diff `ontology-hub-publish/architecture` inside the
  compile job, after the emit. Those two `project` runs were more than half that job on a
  15-domain hub. They read only authored inputs, so they now run in a third job, beside
  `validate` and `compile`, and the compile job is no longer the critical path. The gate still
  covers the same three paths. Receive the workflow with
  `kairos-ontology update --refresh-workflows`. A hub whose branch protection requires the
  `validate` check keeps working; add `architecture` to it if you want it required too.

### Added
- **`project --target` can be repeated.** `project --target erd --target ddd` runs both
  targets over one load of the ontologies, where two separate runs parsed every domain twice.
  CI and `full-validate.yml` now use the combined form.
- **`validate --jobs N`** sets how many domains SHACL checks at once. The default is still the
  CPU count, at most 8, and `KAIROS_VALIDATE_JOBS` still works. SHACL is CPU-bound, so more
  jobs than cores does not speed it up.
