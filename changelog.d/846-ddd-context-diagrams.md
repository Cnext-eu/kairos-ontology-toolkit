### Added
- **`project --target ddd` now draws bounded contexts hub-wide (DD-230, closes #846).** Under
  `ontology-hub-publish/architecture/ddd/contexts/`: `context-map.mmd` (every context and every
  relationship, whichever file declared it, border styled by subdomain type), `all-contexts.mmd`
  (one `classDiagram`, one `namespace` per context — the subject-area view), one `{context}.mmd`
  per non-empty context with neighbours as stubs, and `design-notes.md` (per context: subdomain,
  classes, Silver status, invariants, language, design notes; then every hub class no context
  claims). Membership is annotation-gated, so the import closure never floods a namespace;
  namespace ids come from the context IRI, never the label. Same target, same tracked lane, no
  workflow or gitignore change — a hub on rc3 gets the files on its next toolkit bump.
- **Silver status inside the architecture.** Each class in a context diagram and in
  `design-notes.md` is marked *in Silver contract*, *bound (no contract)* or *not in Silver*, read
  from the authored `model/contracts/*.contract.yaml` and `integration/bindings/*.yaml` — never from
  a CompilePlan. Silver is a subset of the architecture by construction; now it is visible.

### Changed
- **The per-domain `{domain}-context-map.mmd` is retired.** It rendered only the edges its own
  overlay declared, so every other domain's map read as empty. The first `project --target ddd`
  after upgrading removes the old files and writes `contexts/**` plus a
  `.kairos-projection-manifest.json` that reconciles the `ddd` output directory to the run's files
  (a renamed context no longer leaves its diagram behind, #861 for `ddd`). **`git add` the new
  files with the upgrade**: the drift gate diffs tracked paths and does not see untracked
  additions. The manifest is written only for hubs with DDD output.
