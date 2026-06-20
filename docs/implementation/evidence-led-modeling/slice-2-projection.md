# Slice 2 — Projection vertical slice + foundation/thin scaffold

**Status:** ✅ · **Depends on:** 1 · **Gates:** 4, 5, 6, 7

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

- [x] generation: approved claims → expected annotations (scenario acme-hub)
- [x] projector no-bypass / import-generation behavior (per A1)
- [x] `claim<->extension sync` detects drift both ways
- [ ] scenario silver + dbt projection still green

## Acceptance criteria

- [x] Approved claims deterministically produce projection annotations/imports.
- [x] Registry bypass is impossible (or structurally absent under A1).
- [ ] sync gate green on scenario hub.
- [x] version + CHANGELOG + ruff + ext-coverage + scaffold sync.

## Risks / notes

- Under A1 this slice is simpler (generate imports). Under import-all it carries
  the no-bypass enforcement complexity flagged in concept C2.

## Slice 2 implementation note (2026-06-15)

Slice 2 closed the claim→projection loop under **A1** (DD-EL-4):

- **`claim_projection_sync.py`** — deterministically derives, from **approved
  imported** class claims in `model/claims/{domain}-claims.yaml`, the domain
  ontology's external `owl:imports` set and per-class `kairos-ext:silverInclude`
  assertions in `{domain}-silver-ext.ttl`. Exposes `evaluate_projection_sync`
  (drift report) and `apply_projection_sync` (rewrite surfaces).
- **`claims-to-silver-ext` CLI command** — generates/regenerates the imports +
  `silverInclude` surfaces from approved claims; `--check-only` reports drift and
  exits 1 without writing.
- **`check-claims` sync gate** — new claim↔projection sync check (skippable with
  `--no-extension-sync`) that blocks when imports / `silverInclude` drift from
  approved claims, or when a `silverIncludeImports` bulk-bypass flag is present.
- **Projector authority gate** — for silver/dbt/powerbi targets, if a
  `{domain}-claims.yaml` exists, projection of that domain FAILS (records a
  projection error) when claim-derived imports/includes are out of sync. DD-021's
  no-bypass guarantee is retained but is now claim-driven.
- **Scaffold** — added `foundation.ttl.template`; the starter domain ontology now
  `owl:imports` the thin `_foundation` ontology (A2-lite thin scaffold).

This realizes A1 (claims drive imports) while keeping DD-021 as a claim-authority
gate, and keeps the generated TTL surfaces reviewable per DD-EL-3 (A2-lite).
