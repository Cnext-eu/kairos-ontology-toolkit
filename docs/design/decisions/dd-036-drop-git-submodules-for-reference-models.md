# DD-036: Drop Git Submodules for Reference Models

**Status:** Accepted
**Date:** 2026-05-31
**Affects:** `cli/main.py` (init, new-repo, update-refmodels), scaffold workflows, hub repos
**Implementation:** `_run_reference_models_update()` in cli/main.py

### Context

Reference models were distributed to hub repos as a git submodule at
`ontology-reference-models/`. This caused friction: CI needed `submodules: true`,
users forgot `git submodule update`, `.gitmodules` got stale, and the Copilot
cloud agent couldn't resolve imports without explicit submodule checkout.

Meanwhile, the `update-refmodels` CLI command already implemented a cleaner
approach: sparse-clone the upstream repo, copy files directly, commit them.

### Decision

Remove all git submodule logic. Reference models are committed directly into
`ontology-reference-models/` as regular files. Updated via `kairos-ontology update-refmodels`.

### Rationale

- Simpler developer experience (no submodule commands needed)
- CI is faster (no recursive submodule checkout)
- Copilot agent can read reference models without special config
- Single update mechanism (`update-refmodels`) instead of two (submodule + script)
- Files are version-controlled in the hub repo — easy to diff/track changes

### Consequences

- Existing hubs must remove their submodule: `git rm ontology-reference-models`,
  delete from `.gitmodules`, then run `kairos-ontology update-refmodels`
- Hub repo size slightly increases (reference model .ttl files are committed)
- `update-refmodels` becomes the single way to refresh reference models

### Amendment (2026-08-14): the location, not the mechanism, is superseded by DD-152 (proposed)

DD-152 proposes fetching reference models into a shared, versioned, per-user cache
(`%LOCALAPPDATA%\kairos\rm\<version>\`, XDG equivalent elsewhere) instead of committing them into the
hub. It reverses **where** the files live and nothing else. Precisely:

**Still holds, unchanged.** Git submodules stay gone permanently — no `.gitmodules`, no
`submodules: true`, no recursive checkout, and no second update path. `update-refmodels` remains the
single way to refresh reference models, and its implementation
(`_fetch_reference_models`: sparse shallow clone → validate → swap into place) is reused verbatim by
DD-152, including the clone-root `VERSION` copy and `FETCH_PROVENANCE.json`. The migration note above
("existing hubs must remove their submodule…") is still correct for any hub still carrying one. The
Copilot/agent-can-read-the-models property is also preserved — DD-152 keeps the models resolvable
through the catalog, just from outside the workspace.

**Superseded by DD-152.** Only the Decision's destination — "committed directly into
`ontology-reference-models/` as regular files" — and the two statements that follow from it: the
accepted consequence *"hub repo size slightly increases"* (at 17.5 MB / 560 files per hub, permanently
in history, this proved not to be slight) and the rationale bullet *"files are version-controlled in
the hub repo — easy to diff/track changes"*, which DD-152 explicitly gives up and replaces with a
committed version pin plus a reference-models stamp in the DD-047 inventory envelope.

**Not invalidated.** DD-152 adds the cache as the **last** entry in `resolve_refmodels_root`'s existing
precedence chain (explicit flag → `KAIROS_REFMODELS_ROOT` → sibling/hub-relative folder scan → cache).
A hub with `ontology-reference-models/` on disk keeps resolving from it exactly as DD-036 specifies. The
vendored layout therefore ceases to be the *default*; it does not become unsupported, and migration is
opt-in per hub.

**Status of this amendment.** DD-152 is `Proposed` and was never implemented. DD-158 (Accepted,
2026-08-15) supersedes DD-152 and takes the package approach DD-152 rejected. Under DD-158,
reference models resolve from an installed Python package (`kairos-ontology-referencemodels`);
the vendored `ontology-reference-models/` directory, the sparse-clone fetch, and the
folder-scan fallback are removed entirely (no backward compatibility). DD-036's destination
("committed directly into `ontology-reference-models/`") is therefore superseded by DD-158
in the same way DD-152 proposed. Until hubs migrate to the package, DD-036 is in force.
