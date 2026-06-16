# Slice 5 — Power BI/source fit-gap & gold seed

**Status:** ✅ done · **Depends on:** 2, 3 · **Gates:** 8

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

- [x] fit/gap/defer/reject classification on a scenario PBI + claims set
- [x] passthrough-dependency detection
- [x] gold-ext seed produces valid measure/hierarchy annotations

## Acceptance criteria

- [x] Fit-gap report classifies every PBI field against claims.
- [x] Gold seed is candidate-only (no auto-approval).
- [x] version + CHANGELOG + ruff + ext-coverage + tests.

## Risks / notes

- Resist as-is→to-be gravity: the report informs claims; it does not approve them.

## Implementation note (2026-06-16)

Slice 5 landed two **advisory** CLI commands (DD-EL-7) that treat existing Power BI
as *evidence, not authority* (methodology §3.5, §7):

- **`pbi-source-fit-gap SOURCE`** compares a TMDL/PBIP model against the approved
  Claim Registry and writes an advisory markdown fit-gap report
  (`integration/reports/{domain}-claim-fit-gap.md`). It classifies every PBI field /
  measure / relationship as `fit`, `gap`, `defer`, `reject`, or
  `passthrough-dependency`, and lists *source supply without reporting demand*. It is
  advisory — always exits 0 when gaps exist (errors still non-zero) and it *informs*
  claims, never approves them.
- **`tmdl-to-gold-ext SOURCE`** seeds a **candidate** gold-layer extension TTL
  (`model/extensions/{domain}-gold-ext.candidate.ttl`) emitting
  `kairos-ext:measureExpression` / `measureFormatString` from PBI measures and
  `kairos-ext:hierarchyName` / `hierarchyLevel` from PBI hierarchies, marked as a
  human-confirm candidate for `kairos-design-gold`.

The claim↔PBI linkage is **deterministic and AI-free**: claims link to PBI artifacts
via their `tmdl_concept_mapping` evidence; a claim counts as *source-backed* when it
carries an evidence type in `{source_table, source_column, affinity, skos_mapping,
sample_signal}` bound to a system; *passthrough* means the claim disposition is
`passthrough`. Both commands are exempt from the skill soft-gate, like `import-tmdl`.
No new `kairos-ext:` annotations were introduced.
