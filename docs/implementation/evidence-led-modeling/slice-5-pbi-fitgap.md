# Slice 5 — Power BI/source fit-gap & gold seed

**Status:** ⬜ not started · **Depends on:** 2, 3 · **Gates:** 8

## Goal

Reconcile existing reporting demand (Power BI) against source supply (approved,
source-backed claims), and seed the gold layer from validated reporting assets.
Output stays **advisory** — source/stakeholder evidence remains the approval
basis (concept C7 guardrail).

## Scope

- **`pbi-source-fit-gap`** — compare TMDL/PBIP inventory against approved
  source-backed claims + mappings; classify each PBI field/measure/relationship:
  - `fit` (covered by approved source mapping),
  - `gap` (reporting demand, no source evidence),
  - `defer` / `reject` (legacy/unused report artifact),
  - `passthrough-dependency` (measure depends on a passthrough field → review).
  Emit a markdown fit-gap report (per methodology §7.3).
- **`tmdl-to-gold-ext`** — seed gold measures + hierarchies from existing Power BI
  for `kairos-design-gold` (candidate, human-confirmed).

## Affected modules

`import_tmdl.py`, `tmdl_parser.py`, new `pbi_fit_gap.py`, gold projector /
`kairos-ext.ttl` (gold annotations), `cli/main.py`.

## Tests

- [ ] fit/gap/defer/reject classification on a scenario PBI + claims set
- [ ] passthrough-dependency detection
- [ ] gold-ext seed produces valid measure/hierarchy annotations

## Acceptance criteria

- [ ] Fit-gap report classifies every PBI field against claims.
- [ ] Gold seed is candidate-only (no auto-approval).
- [ ] version + CHANGELOG + ruff + ext-coverage + tests.

## Risks / notes

- Resist as-is→to-be gravity: the report informs claims; it does not approve them.
