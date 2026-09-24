### Fixed
- **`FABRIC_WORKSPACE_ID` can be an Environment variable, not only a secret.** The Direct Lake
  override step read the variable first and fell back to the secret, but publish, refresh and
  the advisory BPA run read only the secret. A workspace ID stored as an Environment variable
  passed the override and then published nowhere. Every step now reads it the same way.
  Receive the workflow with `kairos-ontology update --refresh-workflows`.
- **The advisory BPA run analyses every semantic model in the release.** It used to analyse
  the first one only, and took the storage mode from any TMDL file in the whole package, so a
  mixed release could run the Direct Lake checks against a DirectQuery model. Each model now
  gets its own run in its own mode, and one model's failure does not skip the rest.
- A Direct Lake model published with `refresh_after_publish: false` has read no data, so its
  cardinality and VertiPaq rules find nothing. The BPA step now says so in a notice.
- The refresh step reports a published model that is missing from the workspace as an error
  naming the model, instead of failing with a Python traceback.
