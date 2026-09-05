# DD-130: Silver-ext Shape Discovery with Packaged Fallback and Windows-Safe Loading

**Status:** Accepted
**Date:** 2026-07-26
**Affects:** `validate-silver-ext` / `scaffold-silver-ext` CLI commands, `core/design_validation.py`
**Implementation:** `resolve_silver_ext_shapes()` and the shape-load block in
`core/design_validation.py`; `validate_silver_ext_cmd` / `scaffold_silver_ext_cmd` in `cli/main.py`

### Context

`validate-silver-ext` hardcoded the hub-local shape at
`model/shapes/kairos-ext-shapes.shacl.ttl` and passed the absolute `Path` straight to
`rdflib.Graph.parse()`. On a hub missing that managed shape (older or partially migrated
hubs), the missing path fell through to rdflib's URL handling, which on Windows mis-read a
drive letter (`G:\...`) as URI scheme `g` — a misleading error that blocked DD-108/DD-109
validation from ever starting. There was no `--shapes` override and no packaged fallback.

### Decision

1. Add a shared `resolve_silver_ext_shapes(hub)` resolver: prefer the hub-local managed
   shape, else fall back to the packaged canonical shape shipped in the scaffold; report the
   selected source on stderr (stdout stays pure JSON).
2. In `validate_silver_extension`, return a dedicated `silver.shapes-missing` diagnostic when
   the shape file does not exist, and parse via a resolved `file://` URI so a drive-letter
   path is never treated as a URL scheme. Malformed Turtle still yields the existing
   `silver.shapes-load-error`.
3. Add a `--shapes` override validated by `click.Path(exists=True, ...)` so a bad path fails
   at Click parsing, before rdflib. `scaffold-silver-ext` reuses the same resolver.

### Rationale

Centralising transport/existence handling in the core validator fixes every caller at once,
while the packaged fallback keeps older hubs validating without weakening checks. New/updated
hubs still receive the managed shape via scaffold install, so the fallback is additive.

### Consequences

- `validate-silver-ext` runs on Windows when the hub-local shape is absent but the packaged
  shape exists, and reports which shape source was used.
- A missing shape now surfaces as `silver.shapes-missing`, never as URL scheme `g`.
- CLI stdout remains pure JSON; the selected-source line is emitted on stderr, so callers that
  parse output must read stdout (tests updated accordingly).
