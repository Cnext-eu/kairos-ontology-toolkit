# DD-052: Import Commands Auto-Write an Import-Results Session File

**Status:** Accepted
**Date:** 2026-06-13
**Affects:** `import_session.py` (new), `import_source.py`, `import_flatfile.py`,
`cli/main.py` (init/new-repo), `kairos-design-source` skill

### Context

The `import-flatfile` and `import-source` CLI commands produced vocabulary/YAML
artifacts but left **no audit record** of what each run imported. Every
interactive design skill (`kairos-design-source`, `-domain`, `-discovery`)
already drops a markdown session file under `ontology-hub/.sessions-design/`, but
the *non-interactive* import commands did not.

### Decision

The import commands now **auto-write a machine-generated import-results file** to
a dedicated hub folder, using a template consistent with the existing session
files:

```
ontology-hub/.sessions-design-import/
  └── import-{system-name}-{YYYY-MM-DD}.md
```

- A new module `import_session.py` provides a pure `render_import_session_md()`
  renderer and a best-effort `write_import_session()` writer.
- `run_import_source` (method `yaml-import`, including the change report and
  enrichment flag) and `run_import_flatfile` (method `flatfile`) call the writer
  after writing their artifacts.
- The write is **best-effort and hub-root-gated**: it is skipped (never raised)
  when no hub is detected, so it cannot break an import or pollute unit tests
  that run outside a hub.
- `.sessions-design-import/` is created at hub `init`/`new-repo` with a
  `.gitkeep`, consistent with `.sessions-design/`.

### Rationale

- Separates the **auto-generated import audit log** from the **interactive
  design session file**, keeping each concern in its own folder.
- Same-day re-runs overwrite the file, mirroring the session-file convention.
- Best-effort gating preserves the existing pure behaviour of the import
  functions outside a hub.
