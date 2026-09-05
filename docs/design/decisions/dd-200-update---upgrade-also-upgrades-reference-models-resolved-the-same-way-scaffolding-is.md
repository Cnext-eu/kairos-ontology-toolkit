# DD-200: `update --upgrade` also upgrades reference models, resolved the same way scaffolding is

**Status:** Accepted
**Date:** 2026-08-20
**Affects:** `_resolve_refmodels_tag` (new, `cli/shared.py`), `_upgrade_refmodels` (new, `cli/operations.py`), `update_refmodels` (`update-refmodels` command), `update --upgrade`
**Issue:** #551

### Context

`update-refmodels` (no `--version`) ran `uv pip install --upgrade
kairos-ontology-referencemodels` and reported whatever
`importlib.metadata.version()` returned afterward as the new pin. Reference
models ship only as a GitHub Release wheel (DD-158), never to a package
index — there is no `kairos-ontology-referencemodels` for `uv pip install
--upgrade` to find there, so the install silently did nothing while the
command still printed success. This is exactly how a real hub's pin sat
thirteen minor versions behind (#541): the command that exists to fix pin
drift could not actually move the pin forward at all.

A second, independent bug in the same command: with an explicit
`--version`, the tag was written into the pin/wheel URL verbatim, without
the `v`-prefix normalization `_resolve_scaffold_refmodels_pin` already
applies (`1.33.1` and `v1.33.1` name the same release, but only the latter
is a valid tag/URL segment) — an unprefixed `--version` produced a 404 pin.

A third gap, this time in `update --upgrade`: it only ever rewrote the
toolkit pin. Reference models drifted independently, with nothing in this
command's own path to catch it — the same pin-drift class as #541, just
without even a broken command to run against it.

### Decision

New `_resolve_refmodels_tag(version_tag)` in `cli/shared.py` resolves the
tag an upgrade should install: with no `version_tag`, the latest published
**stable** release via the same draft-filtering, version-ordered resolver
(`_list_published_release_tags` / `_latest_stable_tag`) every other caller
already uses — a fourth caller of one policy, not a second reimplementation
(the mistake #542 was). With an explicit `version_tag`, normalizes a bare
version to the `v`-prefixed form. Unlike the scaffold-time resolver, there
is **no fallback to a hardcoded tag** when the release list can't be
fetched: scaffolding with no evidence still needs something to pin, but an
upgrade is protecting an existing, working pin — refusing (`None`) is
correct, not silently reusing a stale hardcoded tag.

`update_refmodels`'s whole body is extracted into `_upgrade_refmodels(version_tag) -> str`
in `operations.py`, reusable by both the standalone command and `update
--upgrade`. It always installs the exact wheel URL for the resolved tag —
the pip-index path is gone entirely, so `importlib.metadata.version()` can
no longer diverge from what was actually resolved, and the pin written to
`pyproject.toml` is always the normalized tag.

`update --upgrade` gains a new step, right after the toolkit pin is
upgraded: if the hub's `pyproject.toml` declares a
`kairos-ontology-referencemodels` dependency at all (a dataplatform repo
never does, and is skipped), it calls `_upgrade_refmodels(None)`. A failure
there is caught and reported by name — "Toolkit upgraded to X, but
reference models upgrade failed: ...; run `kairos-ontology
update-refmodels` to retry" — and exits 1, rather than leaving the hub on a
new toolkit with a silently stale reference-models pin. This is
deliberately **not** wrapped in the existing `_dependency_files_transaction`
helper: the toolkit half of `--upgrade` was never transactional either, so
this matches existing behavior rather than inventing an uneven new
guarantee for only one half of the command.

### Consequences

`update-refmodels` (with or without `--version`) now always installs the
exact release it reports installing, and a bare `--version` no longer
produces a 404 pin. `update --upgrade` on a hub that pins reference models
upgrades both in one run; a refmodels-side failure is named and non-zero,
never silent. A hub whose `pyproject.toml` has no refmodels dependency
(dataplatform repos) is entirely unaffected — the new step is a no-op for
them, not a new failure mode.
