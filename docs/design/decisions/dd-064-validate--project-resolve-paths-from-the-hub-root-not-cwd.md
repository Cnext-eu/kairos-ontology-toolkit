# DD-064: `validate` / `project` Resolve Paths From the Hub Root (Not CWD)

**Status:** Accepted
**Date:** 2026-06-13
**Affects:** `src/kairos_ontology/cli/main.py` (`validate`, `project`, `_resolve_catalog`)
**Implementation:** `find_hub_root()`-based default resolution in the `validate`/`project` command bodies; hub-root-aware `_resolve_catalog()`

### Context

The `validate` and `project` commands hardcoded CLI option defaults relative to the
current working directory, assuming invocation from the **repo root**:

- `validate`: `--ontologies ontology-hub/model/ontologies`, `--shapes ontology-hub/model/shapes`
- `project`: `--ontologies ontology-hub/model/ontologies`, `--output ontology-hub/output`
- shared `_resolve_catalog` candidates: `ontology-hub/catalog-v001.xml`,
  `ontology-reference-models/catalog-v001.xml`

Running from **inside** `ontology-hub/` (a common workflow) broke both commands
through the same cwd-relative root cause, with two observed symptoms:

1. **`validate` hard-errored before running.** `--ontologies`/`--shapes` used
   `click.Path(exists=True)`, so Click validated the (now wrong) **default** and
   exited 2 ("Path '…' does not exist") before the body ran. The same failure hit
   any hub legitimately lacking a `shapes/` directory (SHACL shapes are optional).
2. **`project` nested its output.** `--output ontology-hub/output` resolved to
   `ontology-hub/ontology-hub/output/`, so generated silver/dbt/powerbi artifacts
   and `projection-report.json` landed doubly-nested instead of under
   `ontology-hub/output/medallion/…`.

Newer commands (`coverage-report`, `discovery-status`, `build-glossary`,
`generate-inventory`) already avoid this by resolving from `find_hub_root()`, which
detects the hub whether cwd is the repo root or the hub itself.

### Decision

Resolve `validate`/`project` default paths from `find_hub_root(cwd)` (mirroring
`coverage-report`):

- Change `--ontologies` / `--shapes` / `--output` / `--catalog` defaults to `None`
  and resolve them in the command body from the detected hub root
  (`hub_root/model/ontologies`, `hub_root/model/shapes`, `hub_root/output`).
- Drop `exists=True` on `--shapes` (optional; `run_validation` already guards with
  `shapes_path.exists()`) and on `--ontologies` (replaced by a manual existence
  check that emits a clear, actionable error).
- Make `_resolve_catalog(explicit, hub_root, cwd)` search the hub catalog
  (`hub_root/catalog-v001.xml`) and the reference-models catalog (via
  `_resolve_ref_models_dir`) first, keeping the legacy cwd-relative candidates as a
  fallback.
- Explicit user-supplied paths always win.

### Rationale

Reusing the established `find_hub_root` pattern makes both commands work identically
from the repo root or from inside `ontology-hub/`, matching the rest of the CLI.
Dropping `exists=True` in favour of manual checks turns Click's opaque
default-validation `UsageError` into a clear message and supports shapes-less hubs.
`project` output anchored at `hub_root/output` permanently eliminates the
doubly-nested output directory.

### Consequences

- `validate` no longer exits 2 when run inside `ontology-hub/` or in a hub without
  `shapes/`; `project` writes to `<hub>/output` regardless of cwd.
- Regression coverage in `tests/test_cli_path_resolution.py` exercises both commands
  from the repo root and from inside the hub, with/without a `shapes/` dir.
- This fixes only *future* runs; a hub that already has a stray nested
  `ontology-hub/ontology-hub/output/` should delete it and regenerate.
