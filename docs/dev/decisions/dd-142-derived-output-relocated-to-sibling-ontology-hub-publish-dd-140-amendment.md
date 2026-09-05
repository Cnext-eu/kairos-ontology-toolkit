# DD-142: Derived Output Relocated to Sibling `ontology-hub-publish/` (DD-140 Amendment)

**Status:** Accepted
**Date:** 2026-07-30
**Affects:** `compile --emit`, `project`, `validate` report/shapes-draft paths, coverage/silver
reports, standalone projector defaults, scaffold `.gitignore`, `packages.yml.template`,
`release-projections.yml`, `init`/`new-repo`/`migrate`, and downstream dataplatform consumption
**Implementation:** `publish_root(hub) = hub.parent / "ontology-hub-publish"` in
`core/hub_utils.py`, routed through every hub-anchored `…/output` path; `output` removed from the
hub marker directories and the fresh-hub directory contract.

### Context

DD-140 placed the derived emit tree **inside** the hub at `<hub>/output/…`. In practice this caused
recurring "wrong output folder" confusion: bare `--emit` was hub-anchored, but an explicit
`--emit <path>` resolved against the process **cwd** and skipped the canonical `…/medallion/dbt`
suffix, so running from a subdirectory produced wrong or duplicate output trees. Derived artifacts
also sat inside the authored hub, mixing generated output with authored inputs.

### Decision

Relocate the **entire** derived output tree to a **sibling** folder at the repository root, named
literally **`ontology-hub-publish`** (`<hub.parent>/ontology-hub-publish/…`). All targets move
together — `medallion/dbt`, `medallion/powerbi`, `neo4j`, `azure-search`, `a2ui`, `prompt`,
`reports/details`, `architecture/ddd`, `mdm`, validation reports, and `shapes-draft`.

The `--emit` contract (superseded by the DD-142 amendment below):

- Bare `--emit` → `publish_root(hub)/medallion/dbt` (the only value that receives the suffix).
- Explicit `--emit DIRECTORY` → the **exact** dbt project directory (no suffix appended); relative
  values are anchored to the **hub root**, never the process cwd, fixing the wandering-output bug.
- The now-inverted "outside this hub" warning is removed — the canonical target is intentionally a
  sibling of the hub.

> **Amendment (2026-07-30):** the explicit `--emit DIRECTORY` argument caused a recurring
> misplacement bug — a relative value such as `--emit ontology-hub-publish/medallion/dbt` was
> anchored to the hub root, nesting the publish tree **inside** the hub
> (`ontology-hub/ontology-hub-publish/medallion/dbt`). The emit target is therefore no longer
> configurable: `--emit` is now a **pure flag** that always writes to the fixed
> `publish_root(hub)/medallion/dbt`. Passing a directory to `--emit` is rejected. This removes the
> last way to place derived output anywhere other than the canonical sibling location.

`output` is no longer a hub marker directory (markers are `model` and `integration`), and the
fresh-hub directory contract no longer scaffolds `output/*` inside the hub. The publish tree is
still scaffolded with `.gitkeep` slot markers, but in the sibling; `.gitignore` ignores
`ontology-hub-publish/**` while preserving those markers. Distribution consumers
(`packages.yml.template` git `subdirectory:`, `release-projections.yml`) simply repoint to the new
location — the tree stays in the repository, so no outside-VCS distribution redesign is introduced.

### Rationale

A single shared `publish_root` seam removes every ad-hoc `…/output` construction and the cwd-vs-hub
ambiguity that caused duplicate trees. Separating derived artifacts from authored inputs makes the
hub directory contain only human-authored content, which is easier to review, diff, and reason
about. Keeping the tree in the repository preserves existing git and distribution behavior with a
one-line path repoint.

### Consequences

- Emitted/derived artifacts now live at `<repo>/ontology-hub-publish/…`, a sibling of
  `ontology-hub/`, not inside the hub.
- Callers must pass the **hub root** to `publish_root`; for an undiscovered hub use the
  `publish_root(cwd / "ontology-hub")` fallback (never `publish_root(cwd)`).
- Existing hubs that emitted under `<hub>/output/…` should migrate; `migrate` retargets the move to
  the sibling. The old in-hub `output/` slot is no longer created.
