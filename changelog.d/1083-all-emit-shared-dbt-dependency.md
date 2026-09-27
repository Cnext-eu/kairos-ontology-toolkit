### Fixed
- **`compile --all --emit` publishes a change to a dbt model several domains share.**
  The whole-hub emit runs domain by domain and checked each shared contracted dependency
  against the other domains' previously published state. Changing a model that several
  domains' dbt chains read (a shared `stg_` stage, an `int_merged__` model another domain
  refs) therefore failed the first domain to emit it with `ArtifactCollisionError: …
  has conflicting bytes or casing`, and PR Validation, which runs the same command, failed
  with it. A whole-hub run now treats the domains it has still to emit as pending: their
  recorded state may trail the manifest until they emit, and a shared path takes the
  emitting domain's current bytes. A partial `compile <domain> --emit` keeps the strict
  check, so a genuinely stale sibling still fails loudly.
