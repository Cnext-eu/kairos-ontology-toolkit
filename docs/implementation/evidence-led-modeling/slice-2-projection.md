# Slice 2 — Projection vertical slice + foundation/thin scaffold

**Status:** ⬜ not started · **Depends on:** 1 · **Gates:** 4, 5, 6, 7

## Goal

Close the loop from approved claims to materialized output, so the registry
actually drives projection. Shape depends on the **A1/A2** decisions from 0B.

## Scope

- **`claims-to-silver-ext`** — generate `silverInclude` / extension annotations
  (or, under A2, regenerate thin-ontology stubs too) from `approved` claims.
- **Projector wiring** — projector consumes/validates annotations against the
  registry:
  - If A1 = import-all: enforce **no-bypass** (fail on materializing a class not
    `approved`; gate bulk `silverIncludeImports` / ref-model default includes).
  - If A1 = claims-drive-imports: generate each domain's `owl:imports` /
    sub-pack selection from approved claims (no suppression needed).
- **`claim<->extension sync` gate** added to `check-claims` (the generator now
  exists — this was the forward dependency removed from the old plan).
- **Scaffold templates** — `_foundation.ttl` + thin per-domain ontology.
- **`kairos-ext.ttl` coverage** for any new annotation (guarded by
  `test_ext_vocabulary_coverage.py`).

## Affected modules

`projector.py` (`_discover_whitelisted_imports`), `projections/*`, `cli/main.py`,
`scaffold/`, `kairos-ext.ttl`, `check_claims` backend.

## Tests

- [ ] generation: approved claims → expected annotations (scenario acme-hub)
- [ ] projector no-bypass / import-generation behavior (per A1)
- [ ] `claim<->extension sync` detects drift both ways
- [ ] scenario silver + dbt projection still green

## Acceptance criteria

- [ ] Approved claims deterministically produce projection annotations/imports.
- [ ] Registry bypass is impossible (or structurally absent under A1).
- [ ] sync gate green on scenario hub.
- [ ] version + CHANGELOG + ruff + ext-coverage + scaffold sync.

## Risks / notes

- Under A1 this slice is simpler (generate imports). Under import-all it carries
  the no-bypass enforcement complexity flagged in concept C2.
