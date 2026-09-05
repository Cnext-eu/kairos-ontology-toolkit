# DD-152: Reference Models Resolve From a Shared, Versioned Machine-Level Cache (Supersedes DD-036's Location)

**Status:** Superseded by DD-158 (2026-08-15). Never implemented.
**Date:** 2026-08-14
**Affects:** `cli/shared.py` (`_fetch_reference_models`, refmodels discovery), `core/catalog_utils.py`
(`CatalogResolver`), `core/archetype_loader.py` (`resolve_refmodels_root`, version drift),
`core/ontology_loader.py` (`stable_root`), hub scaffolding (`claude-settings.json`, `.gitignore`),
hub CI workflows, DD-036, DD-047
**Implementation:** None — proposal for review. Nothing is implemented until this entry is Accepted.

### Context

A hub vendors **17.5 MB / 560 files** of reference models into `ontology-reference-models/`, **409 of
them raw ontology serialisations** (297 `.rdf` + 112 `.ttl`), all committed to git, and `init` fetches
them by default (#290). DD-036 chose this deliberately over submodules and accepted "hub repo size
slightly increases" as the cost. At one client hub the cost is no longer slight, and it is paid three
times over: permanently in every hub's git history, once per client as a pinned duplicate of bytes
nobody edits, and once per agent workspace — raw ontology sitting inside the tree the agent reads.

That third cost is why the DD-103 agent boundary has to exist as a **deny-list** at all. The
concurrent DD-103 amendment extends those globs to `.rdf`/`.owl` and re-anchors them to the project
root, which closes the holes that were open — but a deny-list is a guardrail, not a sandbox: `Bash`,
`cat` and `git show` still reach the files, and the rules only bind agents that honour that settings
file. The boundary is a policy over files that are present. Absence is stronger than policy.

Nothing about the vendored *content* is wrong. What is wrong is the *location*.

### Decision

**Reference models are fetched into a shared, versioned, per-user location outside every repository**
— `%LOCALAPPDATA%\kairos\rm\<version>\` on Windows, the XDG equivalent
(`${XDG_CACHE_HOME:-~/.cache}/kairos/rm/<version>/`) elsewhere. One copy per version per machine,
shared by every hub on it. The hub does not gitignore the models; it simply does not contain them.

**The short prefix is a requirement, not an aesthetic.** The longest path inside the tree is **144
characters** relative to the inner reference-models root (170 including the
`ontology-reference-models/` prefix; the upstream FIBO `fibo/BE/GovernmentEntities/…` paths are the
binding constraint). Against `MAX_PATH` that leaves 115 characters of prefix budget. Vendored in a
realistic user-profile hub the total is **235** — it fits, which is why nobody has hit this.
`.venv\Lib\site-packages\kairos_ontology_referencemodels\ontology-reference-models\…` totals **291**,
exceeding `MAX_PATH` by **31**; a global Python or `uv tool` install totals 286/287. A
`%LOCALAPPDATA%\kairos\rm\<version>\` prefix sits well under. **These figures are arithmetic, not
observed failures** — the machine they were measured on has `LongPathsEnabled=1` and therefore cannot
reproduce the fault. Any location this decision picks must carry the short-prefix constraint
explicitly, because the constraint is invisible to the developers most likely to change it.

**Fetching reuses `_fetch_reference_models` (`cli/shared.py:1724-1847`) as-is.** #290's work is
preserved, not replaced: the sparse shallow clone, the assemble-off-to-the-side-then-swap that keeps a
partial Windows `copytree` from leaving a tree that "looks valid", the clone-root `VERSION` copied in
beside the subtree, and `FETCH_PROVENANCE.json`. Only the destination changes.

**Resolution is an additive catalog overlay.** `CatalogResolver.__init__`
(`core/catalog_utils.py:138-142`) gains `extra_catalogs`, with the default resolved **inside
`__init__`** rather than threaded through `load_ontology`. This is the load-bearing choice in the
whole proposal. There are **8 `CatalogResolver` construction sites** (`cli/shared.py:1392`,
`core/analyse_sources.py:859`, `core/archetype_topology.py:159`, `core/catalog_test.py:41`,
`core/inventory.py:609`, `core/ontology_loader.py:241`, `core/propose_alignment.py:462`,
`core/reference_modules.py:587`) and roughly **14 independent catalog-discovery sites** across
`cli/` and `core/` that locate `catalog-v001.xml` by their own means (five in `cli/inspection.py`
alone). A threaded parameter would reach a small minority, and the majority would degrade **silently**
— a `<nextCatalog>` that does not exist is a `warning`-level diagnostic
(`catalog_utils.py:210-216`), not an error, so the failure mode of a missed site is a hub that quietly
resolves less of its closure. Defaulting in the constructor is the only variant where forgetting a
call site is inert rather than harmful. The `catalog_path is not None` gate at
`core/ontology_loader.py:241` must be fixed in the same change, and note that
`core/design_landscape.py:403-408` *raises* on a missing reference-models directory where everything
else warns.

**The overlay must be additive-only, and this is a correctness constraint, not a style preference.**
`stable_root` derives from `Path(catalog_path).resolve().parent`
(`core/ontology_loader.py:233-239`) and feeds `source_identity` → `_closure_hash` → the DD-047
inventory envelope. If the overlay can displace or reorder the hub catalog's own resolutions, closure
hashes become machine-dependent and every inventory in every hub churns on the next run. Additive-only
means: the hub catalog is still the root, its entries still win, and the overlay only supplies
resolutions the hub catalog does not already provide.

**Precedence extends `resolve_refmodels_root`'s existing chain** (`core/archetype_loader.py:139-184`)
rather than replacing it: explicit `--refmodels-root`, then `KAIROS_REFMODELS_ROOT`, then the existing
sibling/hub-relative folder scan, then the cache. A hub that still has
`ontology-reference-models/` on disk keeps resolving from it and is unaffected. Migration is therefore
opt-in per hub, and DD-036's layout stays valid — it stops being the *default*, it does not become
wrong.

If resolution is ever moved into an installed package, use `importlib.resources.files()`, which
returns a real `pathlib.Path` for both wheel and editable installs, and **assert
`isinstance(root, Path)` so a zip-import regression fails loudly**. Never call `as_file()` on a
directory traversable: its default behaviour recursively replicates the tree into a temp directory
deleted on context exit — a 17.5 MB extraction per invocation. House convention for packaged data is
`__file__`-relative (`core/design_validation.py:284-286`, `core/binding_archetypes.py:40-43`).

### Rejected alternatives

- **Ship reference models as a Python wheel resolved via `importlib.resources`.** Rejected on
  distribution, and the path budget is only the second reason. **There is no package index.** The
  toolkit itself installs from a GitHub-Release-asset direct URL
  (`scaffold/pyproject.toml.template:7`, `.github/workflows/release.yml:105-109`), so a second
  distribution has exactly two options: pin it *inside* the toolkit wheel — which makes every
  reference-models release require a toolkit release, destroying the only reason to separate them — or
  add a second hub-side URL pin, which reproduces the multi-pin divergence #297 was filed to remove
  (five strings for one version, kept in agreement by nothing). "`update-refmodels` becomes
  `pip install -U`" is simply not on offer. Separately, `site-packages` is the *worst* location on path
  length: **291 characters, over `MAX_PATH` by 31**, some 56 characters worse than vendoring.
- **Bake an absolute cache path into the committed `catalog-v001.xml`.** The catalog is a committed,
  shared, user-editable artifact; an absolute machine path makes it non-portable across every developer
  and CI runner, and because `stable_root` is the catalog's parent directory it would also make
  `source_identity` machine-specific. Rejected.
- **Generate the catalog at run time.** Turns a committed contract artifact into a build output.
  `catalog-v001.xml` is referenced by name from ~14 discovery sites and both scaffold templates, is the
  one `.xml` the DD-103 boundary deliberately lets an agent read, and is intentionally hand-editable
  under DD-024's hash-tolerant resolution. Generation would also silently discard whatever a hub had
  added to it. Rejected.
- **Symlink or junction the hub path into the cache.** Windows symlink creation needs Developer Mode
  or elevation; junctions are directory-only and unknown to git, so git either tracks a placeholder or
  walks through and stages the 560 files this decision exists to remove. It also buys nothing on path
  length, since resolution still traverses the hub-side prefix. Rejected.
- **`KAIROS_REFMODELS_ROOT` only.** This is the status quo, not a decision — the variable already
  exists and is already second in `resolve_refmodels_root`'s precedence. As the *primary* mechanism it
  requires every user, shell, IDE, CI job and agent session to set it correctly, manages no fetching or
  versioning, and when unset degrades through a `warning`-level missing-`nextCatalog` path rather than
  failing. It remains essential as the air-gap escape hatch; it is not a distribution strategy.

### Consequences

- **This is the first machine-level state the toolkit has ever owned.** There is currently no
  `Path.home()`, `%APPDATA%` or `platformdirs` use anywhere in `src/` — the toolkit reads and writes
  only inside the repo it was pointed at. That property ends here, and with it come failure modes the
  codebase has no precedent for: profile redirection and roaming profiles in managed corporate estates,
  per-user caches on shared build agents, and read-only or quota-limited profile directories.
- **Cache lifecycle becomes the toolkit's problem.** Nothing deletes a `<version>` directory, so
  versions accumulate at 17.5 MB each. Two hubs can fetch the same version concurrently — the existing
  build-off-to-the-side-then-swap makes a partial tree unlikely but does not make the swap atomic
  against a concurrent reader. Invalidation, a `--prune`/GC story, and a documented "delete this
  directory" recovery step are in scope for the implementation, not optional follow-ups.
- **Every hub's CI must populate the cache.** Today the models arrive with the checkout and nothing
  needs to know they exist. After this, every workflow that runs `compile`, `validate`,
  `check-inventory`, `design-landscape` or `discovery-conformance` needs a fetch step and a cache key.
  This is the largest migration cost and it lands in client repositories, not in this one.
- **Offline and air-gapped use regresses.** A clone is currently self-sufficient. Afterwards, a cold
  machine with no network cannot resolve the closure at all. `KAIROS_REFMODELS_ROOT` plus a documented
  pre-seed procedure (copy a known-good `<version>` directory into place) are therefore mandatory
  deliverables, not documentation nice-to-haves.
- **Historical reproducibility weakens, and this is the direct counterweight to DD-036's rationale.**
  DD-036 valued "files are version-controlled in the hub repo — easy to diff/track changes". Under
  DD-152 a hub no longer records the bytes it was authored against; `FETCH_PROVENANCE.json` moves into
  the cache along with the models. A committed pin in the hub is the replacement, and the DD-047
  envelope stamp below is where it becomes verifiable.
- **The DD-103 boundary becomes structural for migrated hubs but the deny-list cannot be deleted.**
  The `ontology-reference-models/**` globs in `scaffold/claude-settings.json` become vestigial once a
  hub has no such directory, and remain necessary for every hub that still does. They stay, inert, for
  as long as both layouts are supported — a permanent piece of dead-looking configuration that a future
  reader will be tempted to remove. The `model/ontologies/**` and `model/shapes/**` globs are
  untouched: hub-authored ontology never leaves the repo, so the deny-list remains the only mechanism
  there.
- **Path budget improves rather than merely holding.** The tree moves from 235 characters to a prefix
  well inside budget, which also removes the latent `copytree` hazard `_fetch_reference_models`
  currently documents in its own docstring.
- **The acceptance test is byte-equality, not "it works".** Closure hashes and DD-047 inventory
  filenames must be identical before and after the move on the same hub; a `compile --check` and
  `validate` must complete with **zero `missing_import` warnings** and no `ontology-reference-models/`
  in the hub. Silent partial resolution is the failure this proposal must be tested against, because it
  is the failure the warning-level catalog diagnostics make easy.

### Open questions

These are genuinely unresolved. This entry should not move to Accepted until both have answers.

1. **What is `<version>` in the cache path — which string is authoritative?** `VERSION` is **15
   files**, not one: the repository root plus 14 per-module and per-pack files under
   `ontology-reference-models/` (`blueprints/{archetypes,ontology,patterns}`,
   `accelerator-packs/{financial-services,logistics}`, and nine `derived-ontologies/*`). Only the root
   one is a candidate for substitution by a distribution version; the 14 are read by `_module_version`
   (`core/archetype_loader.py:411-456`) to check `compatible_with.ontology_versions` pins and must keep
   shipping verbatim. Meanwhile `repo_tag_range` (`core/archetype_loader.py:459-495`) is a **git tag**
   range whose schema the reference-models repo owns, compared via `packaging` against whatever
   `_refmodels_version` reads — which is why `_fetch_reference_models` copies the clone-root `VERSION`
   in beside the subtree at all. So the git tag (`v1.16.0`), the root `VERSION` (`1.16.0`) and any
   future distribution version are three strings kept in agreement by nothing, and PEP 440
   normalisation diverges from tag form for non-final releases. The straightforward candidate is the
   **resolved git ref actually fetched**, since that is what `_fetch_reference_models` accepts and what
   `FETCH_PROVENANCE.json` records — but naming it here without settling the relationship to
   `repo_tag_range` would just move the ambiguity into a directory name.
2. **Aggregate third-party attribution is not reaching hubs today, and the cache inherits that.**
   FIBO (MIT, © 2020 Enterprise Data Management Council) and IATA ONE Record (MIT, © 2025 IATA-Cargo)
   each carry a `LICENSE` inside their `current/` directory, and those files *are* vendored. An
   aggregate `NOTICE` naming both, with paths, copyrights and the Apache-2.0/MIT compatibility
   statement, exists at the **upstream reference-models repository root** — but
   `_fetch_reference_models` copies only the `ontology-reference-models/` subtree plus the clone-root
   `VERSION`, so neither the root `LICENSE` nor the root `NOTICE` has ever reached a hub. Moving to a
   cache does not create this gap and does not fix it; it carries it to a new location while removing
   the per-file `LICENSE` copies from the repo a downstream consumer would clone. Recorded as an
   observation for review, not as legal advice: whoever owns redistribution terms should decide whether
   the fetch should also copy the root `LICENSE`/`NOTICE`.
