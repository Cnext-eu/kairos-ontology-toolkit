### Fixed
- **The dataplatform deploy workflow now installs uv before running `kairos-ontology`.**
  `deploy-powerbi-semantic-model.yml` ran `uv run kairos-ontology apply-gold-connection`
  in a job that never installed uv or synced the locked environment, so a deploy failed
  before publishing anything. The job now runs `astral-sh/setup-uv` (the same pinned
  version as `pr-validate.yml`) and `uv sync --locked` first. Existing dataplatforms
  receive the fix through `update`: the previous workflow generation is recorded, so an
  untouched copy refreshes automatically instead of reporting "customized". (#983)
