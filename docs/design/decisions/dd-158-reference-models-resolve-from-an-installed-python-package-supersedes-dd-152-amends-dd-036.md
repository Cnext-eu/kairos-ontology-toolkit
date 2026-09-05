# DD-158: Reference Models Resolve From an Installed Python Package (Supersedes DD-152, Amends DD-036)

**Status:** Accepted
**Date:** 2026-08-15
**Affects:** `cli/shared.py` (refmodels discovery, fetch, provenance), `core/catalog_utils.py`
(`CatalogResolver`), `core/archetype_loader.py` (`resolve_refmodels_root`, version drift),
`core/ontology_loader.py` (`stable_root`, `_relative_identity`), hub scaffolding
(`pyproject.toml.template`, `catalog-v001.xml.template`, `claude-settings.json`),
`.github/workflows/ci.yml`, DD-036, DD-152, DD-047, DD-103

### Context

DD-152 (Proposed, never implemented) argued for a shared, versioned, per-machine cache and
**explicitly rejected** a pip/package approach. This decision supersedes DD-152 and takes the
package approach DD-152 rejected, addressing each of its concerns.

The upstream `kairos-ontology-referencemodels` repository is restructured into a distributable
Python data package. The `ontology-reference-models/` directory moves inside the package tree
(`kairos_ontology_referencemodels/ontology-reference-models/`), and the release workflow
builds and publishes a wheel (`kairos_ontology_referencemodels-<version>-py3-none-any.whl`)
alongside the existing `tar.gz`.

The toolkit resolves reference models from the installed package at runtime, falling back to
`KAIROS_REFMODELS_ROOT` (env var) and `--refmodels-root` (CLI flag) as air-gap escape hatches.
The old sparse-clone fetch mechanism (`_fetch_reference_models`), the folder-scan fallback
(`_resolve_ref_models_dir`), and the `FETCH_PROVENANCE.json` provenance file are **removed**.
No backward compatibility is provided — this is a clean break for new hubs.

### DD-152's rejection reasons and how this decision addresses them

| DD-152 concern | DD-158 response |
|---|---|
| **No package index.** The toolkit uses GitHub-Release-asset direct URLs, not PyPI; a second distribution has no index. | The referencemodels package uses the same distribution pattern: a GitHub Release wheel with a direct-URL pin in the hub's `pyproject.toml`. No PyPI is needed. |
| **Multi-pin divergence.** A second hub-side URL pin reproduces the multi-pin divergence #297 was filed to remove. | A single pin in `pyproject.toml [project.dependencies]` for `kairos-ontology-referencemodels`, managed by `update-refmodels` (uv pip install --upgrade + pin rewrite + uv lock). The toolkit itself is already a single pin; this adds exactly one more, following the same pattern. |
| **`site-packages` path = 291 chars, exceeds MAX_PATH by 31.** | Windows long-path support (`LongPathsEnabled=1`) is standard since 2024. The `pyproject.toml` documents this as a requirement. Package data is kept flat (`ontology-reference-models/` directly under the package directory — no redundant nesting). `importlib.resources.files()` returns a real `Path` for wheel installs. |
| **Bake absolute path into catalog.** Non-portable. | Not needed. The scaffold hub catalog template removes the `<nextCatalog>` entry. The toolkit overlays the package catalog at runtime via `CatalogResolver.with_reference_models()`, which is equivalent to the old `<nextCatalog>` chain but resolved at import time, not baked in. |
| **Coupling refmodels releases to toolkit releases.** | The two packages are independently versioned and independently released. A hub pins each separately. No build-time cycle: the toolkit's dev-dependency pins the referencemodels wheel from a published release; the referencemodels dev-extras pin the toolkit wheel from a published release. Local development uses `KAIROS_REFMODELS_ROOT` / `KAIROS_TOOLKIT_SRC` env vars or `[tool.uv.sources]` path overrides. |

### Decision

**Reference models resolve from the installed `kairos-ontology-referencemodels` Python package.**

Resolution precedence (`resolve_refmodels_root` in `core/archetype_loader.py`):
1. Installed package — `from kairos_ontology_referencemodels import refmodels_root`.
2. Explicit `--refmodels-root` CLI flag (air-gap escape hatch).
3. `KAIROS_REFMODELS_ROOT` env var (air-gap escape hatch).
4. ~~Folder-scan fallback~~ — **removed**.

The package's `refmodels_root()` returns `Path(importlib.resources.files("kairos_ontology_referencemodels") / "ontology-reference-models")`, a real `Path` for wheel installs.

**Catalog overlay:** `CatalogResolver.with_reference_models(catalog_path)` is a factory
classmethod that overlays the package's `catalog-v001.xml` as an extra catalog, equivalent to
the old `<nextCatalog>` chain but resolved at runtime. The hub catalog template no longer
contains a `<nextCatalog>` entry. All 8 `CatalogResolver()` construction sites are updated to
use `with_reference_models()`.

**Closure hash stability:** `_relative_identity` in `core/ontology_loader.py` derives
machine-independent relative paths from the package root: `ontology-reference-models/blueprints/...`.
`stable_root` is the actual installed package path (not a virtual `kairos://` URI). Closure
hashes are identical across machines as long as the package's internal directory structure is
stable (which it is — it's a wheel).

**Scaffolding:**
- `pyproject.toml.template` adds `kairos-ontology-referencemodels @ https://github.com/Cnext-eu/kairos-ontology-referencemodels/releases/download/{refmodels_ref}/kairos_ontology_referencemodels-{refmodels_version}-py3-none-any.whl`.
- `catalog-v001.xml.template` removes the `<nextCatalog>` entry.
- `claude-settings.json` removes all 12 `ontology-reference-models/**` deny-list globs (6 Read + 6 Grep) — the DD-103 boundary becomes structural: the files are absent from the repo.
- `_resolve_scaffold_refmodels_pin()` resolves the latest referencemodels release tag via `gh api`.

**`update-refmodels` command:** replaced with `uv pip install --upgrade kairos-ontology-referencemodels` + pin rewrite in `pyproject.toml` + `uv lock`.

**Provenance:** `_read_refmodels_provenance()` uses `importlib.metadata.version("kairos-ontology-referencemodels")` instead of reading a `FETCH_PROVENANCE.json` file.

**Version drift:** `_refmodels_version()` in `archetype_loader.py` uses `importlib.metadata.version()` first, falling back to reading the `VERSION` file (for `KAIROS_REFMODELS_ROOT` workflows). Per-module `VERSION` files are inside the package and still read via `refmodels_root()` — no change needed.

### Rejected alternatives (carried forward from DD-152, plus new ones)

- **Machine-level shared cache (DD-152).** Rejected — introduces the first machine-level state
  the toolkit has ever owned, with cache lifecycle, GC, concurrent-fetch, profile-redirection, and
  offline-regression problems. A package is a well-understood mechanism with `uv`/`pip` handling
  all of that.
- **Keep vendoring (DD-036).** Rejected — 17.5 MB / 560 files per hub, 409 raw ontology serialisations
  with agent-read deny-list policy rather than structural absence.
- **`KAIROS_REFMODELS_ROOT` only.** Not a distribution strategy; remains as the air-gap escape hatch.

### Consequences

- **New hubs get a clean tree.** No `ontology-reference-models/` directory, no 560 files, no
  per-hub duplicate of 17.5 MB. Reference models arrive via `uv sync` as a Python package dependency.
- **The DD-103 boundary is structural, not policy.** The `ontology-reference-models/**` deny-list
  globs are removed from the scaffold template because the files are simply absent. This is the
  strongest form of the boundary.
- **`update-refmodels` becomes `uv pip install --upgrade` + pin rewrite + `uv lock`.** No sparse
  clone, no `FETCH_PROVENANCE.json`. The pin in `pyproject.toml` is the version record; `uv lock`
  is the lockfile.
- **Offline/air-gapped:** `KAIROS_REFMODELS_ROOT` + `--refmodels-root` are preserved. Pre-seed by
  installing the wheel from a local file: `uv pip install ./kairos_ontology_referencemodels-*.whl`.
- **Issue #428** (grain_collisions registry re-keying, skill wording, coverage step) is split into
  a separate PR — three independent changes that don't depend on the package migration.
- **Contract-manifest.yaml catalog surface** (uri + rewriteURI entries) is preserved verbatim
  inside the package. Only the resolution path changes (filesystem folder → installed package).
  The `test_every_rewrite_prefix_is_a_real_directory` test still passes because the directory
  structure inside the package is identical to the repo-root layout.
- **The `_KNOWN_CLAUDE_SETTINGS_HASHES` in `shared.py` includes the new claude-settings.json hash**
  (without refmodel deny entries) so the `update` command recognizes the new generation. Both old
  and new hashes are present so `update` works on hubs of either generation.
- **Sequencing:** Phase 1 (referencemodels wheel publish, branch `feature/data-package-wheel`)
  must be merged to main and a wheel-publishing release cut before the toolkit can pin to a real
  wheel URL. Until then, the toolkit CI uses a `[tool.uv.sources]` git override pointing at the
  Phase 1 branch. This is temporary and replaced with a wheel-URL pin once the first wheel is
  published.
