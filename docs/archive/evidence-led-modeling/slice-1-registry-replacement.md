# Slice 1 — Registry replacement vertical slice (cutover)

**Status:** 🟢 done · **Depends on:** 0B · **Gates:** 2, 3

> **Progress (2026-06-15):** Cutover complete. Registry model + migration +
> producer flip + unified `check-claims` gate landed; alignment YAML and the
> `check-alignment` / `check-source-coverage` commands retired. Full suite green
> (`uv run pytest -m ""`), ruff clean, scaffold in sync, `__version__` → 4.0.0.

## Goal

The coherent cutover: introduce the Claim Registry **and** retire the alignment
YAML in a single shippable slice, with full parity. After this slice the toolkit
has exactly one governance path.

## Scope

- **`claim_registry.py`** — dataclass/Pydantic model + loader + structural
  validator for `model/claims/{domain}-claims.yaml`.
- **`migrate-claims`** CLI — one-way deterministic conversion of existing
  `{domain}-alignment.yaml` → claims. Old alignment files thereafter error with a
  clear migration message (no dual semantics).
- **`propose-alignment` refactor** — emit candidate (`proposed`) claims into the
  registry instead of alignment YAML, preserving table/column coverage, freshness
  hash, and custom-column disposition triage.
- **`check-claims` CLI** — at **parity** with `check-alignment` +
  `check-source-coverage`:
  - schema validity,
  - ownership vs `data-domains.yaml`,
  - duplicate `approved` claims across all `model/claims/*.yaml`,
  - evidence-required, mapping-required,
  - coverage/freshness, status/disposition rules.
  Replaces both old gates; reuse `alignment_coverage.py` / `source_coverage.py`
  backend — no double path.
- **Minimal skill/doc nudge** so modelers stop following the old alignment
  workflow (full skill redesign is Slice 7).

## Affected modules

`propose_alignment.py`, `alignment_coverage.py`, `source_coverage.py`,
`cli/main.py` (retire `check-alignment` / `check-source-coverage`; add
`check-claims`, `migrate-claims`), scaffold dir lists, design skills (minimal).

## Tests (migration-test workstream)

- [x] golden alignment YAML → registry conversion fixtures
      (`tests/test_migrate_claims.py::test_golden_snapshot`, byte-stable + round-trip)
- [ ] scenario acme-hub before/after migration
- [x] freshness-hash + table/column coverage preservation
      (`TestConversion::test_coverage_snapshot`, `test_domain_and_freshness`)
- [x] old-CLI behavior (alignment commands error with guidance) — message +
      detection landed (`legacy_alignment_error`, `find_legacy_alignment_files`);
      now wired into `check-claims`, which hard-rejects any leftover
      `*-alignment.yaml`.
- [x] `check-claims` parity tests vs former `check-alignment` /
      `check-source-coverage` outcomes (`tests/test_claim_coverage.py`, 31 tests:
      ok/missing/invalid/incomplete/stale/unverifiable/orphan/unowned/duplicate/
      strict + CLI).

> **Progress (2026-06-15):** Slice 1 cutover landed. `propose-alignment` now emits
> `proposed` claims into `model/claims/` (merge-preserving human decisions);
> `migrate-claims` converts legacy alignment YAML; the **`check-claims`** gate
> replaces both `check-alignment` and `check-source-coverage` (removed) at parity
> and rejects leftover alignment files; `alignment_coverage` trimmed to the reused
> affinity/freshness primitives + triage heuristics. Skills updated to the claims
> workflow and synced to scaffold. `__version__` → 4.0.0 (breaking) + CHANGELOG.
> Full suite green (`uv run pytest -m ""`), ruff clean. Remaining: scenario
> acme-hub before/after migration fixture (optional polish).

## Acceptance criteria

- [x] Every parity-appendix item (index) is covered.
- [x] `{domain}-alignment.yaml` is fully retired; no dual-path logic remains.
- [x] `check-claims` reproduces former gate decisions on the scenario hub.
- [x] `__version__` bump + CHANGELOG + ruff + scaffold sync.

## Risks / notes

- This is the highest-risk slice: it cannot merge half-done without breaking
  existing hubs. The parity appendix is the merge gate.
