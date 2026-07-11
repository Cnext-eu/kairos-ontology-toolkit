# Slice 6 — Change management & contract versioning

**Status:** ⬜ not started · **Depends on:** 2, 4 · **Gates:** 8

## Goal

Make new systems / new fields safe: they expand silver, never silently mutate it.
Extends the minimal contract semantics defined in Slice 0B.

## Scope

- **`source-delta-report`** — compare a new/changed source system against
  approved claims + mappings; classify each delta (per methodology §13.2):
  maps-to-existing-class, new-claim-candidate, new-column→property, passthrough,
  new-reference-list, new-relationship, semantic-conflict, changed key/type/grain.
  Emit an impact report (expected silver table/column/FK additions, breaking
  changes, required approvals).
- **Contract version policy** — silver/gold contract metadata + version rules
  (per methodology §13.5): additive → minor, changed meaning/type/key/grain →
  major, mapping-only → patch. Backward-compat tactics (additive columns,
  deprecation metadata, compatibility views, aliases, deprecate-before-remove).

## Affected modules

`source_coverage.py` / new `source_delta.py`, `claim_registry.py`
(`silver_impact` + contract fields), silver/gold projectors (version metadata),
`cli/main.py`.

## Tests

- [ ] delta classification across all §13.2 delta types
- [ ] impact report flags breaking vs additive correctly
- [ ] version bump hints match the change taxonomy

## Acceptance criteria

- [ ] A new source produces an impact report before projection changes merge.
- [ ] Breaking changes are distinguishable from additive ones.
- [ ] version + CHANGELOG + ruff + tests.

## Risks / notes

- Invariant to enforce: "new evidence may expand silver, but must not silently
  mutate existing silver."
