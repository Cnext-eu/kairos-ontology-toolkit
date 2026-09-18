### Changed
- **Scaffolded hubs now track `ontology-hub-publish/architecture/**` (issue #774).** The
  canonical class diagrams and DDD maps are how a model actually gets reviewed and
  explained — an architecture ERD shows the full canonical surface, including everything
  inherited from the industry tier. Left untracked they rot invisibly: one hub's had
  drifted into mixed vintages, some domains regenerated weeks apart, and nothing surfaced
  it because nothing was watching.

  Tracking alone would be worse than not tracking, so the drift gate regenerates them too:
  `architecture/**` comes from `project`, not from `compile --emit`, so `pr-validate.yml`
  and `full-validate.yml` now run `project --target erd` and `--target ddd` before the diff,
  and the tracked-ness guard covers the new path. A test pins the two halves together — any
  lane the template allowlists must appear in the gate that diffs it.

- **Canonical ERD and DDD diagrams carry a provenance stamp.** They were the only generated
  Mermaid artifacts without one, so a diagram produced by an older projector was
  indistinguishable from a current one — exactly the mixed-vintage problem above. They now
  use the same `mermaid_provenance_comment` helper as the Silver, Gold and contract
  diagrams, which records the toolkit version and deliberately carries **no timestamp**: a
  wall-clock stamp in a tracked, drift-gated file would fail CI on every run. *When* a
  diagram changed is what git history records; only *which version* drew it cannot be
  recovered afterwards.
