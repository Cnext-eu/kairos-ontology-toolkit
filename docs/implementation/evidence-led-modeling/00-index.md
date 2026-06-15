# Evidence-Led Accelerator-First Modeling — Implementation Tracking

Tracking folder for implementing the methodology in
[`../../draft/evidence-led-accelerator-first-modeling-approach-2026-06-15.md`](../../draft/evidence-led-accelerator-first-modeling-approach-2026-06-15.md).

Work is structured as **coherent vertical slices**, not horizontal feature
phases. Each slice leaves the toolkit in a releasable state. Alignment YAML is
retired only in Slice 1, together with its full replacement.

> Status legend: ⬜ not started · 🟡 in progress · ✅ done · ⛔ blocked

## Slice map

| Slice | Title | Status | Depends on |
|---|---|---|---|
| [0A](slice-0a-closure-spike.md) | Full-closure spike (perf/FK only) | 🟢 findings | — |
| [0B](slice-0b-schema-authority.md) | Registry schema + migration + projector-authority gate (+ A1/A2 forks) | 🟢 decided | 0A |
| [1](slice-1-registry-replacement.md) | Registry replacement vertical slice (cutover) | ✅ | 0B |
| [2](slice-2-projection.md) | Projection vertical slice + foundation/thin scaffold | ⬜ | 1 |
| [3](slice-3-derive-claims.md) | derive-claims (richer evidence aggregation) | ⬜ | 1 |
| [4](slice-4-mdm-ownership.md) | MDM/reference-data rules + ownership hardening | ⬜ | 2 |
| [5](slice-5-pbi-fitgap.md) | Power BI/source fit-gap & gold seed | ⬜ | 2, 3 |
| [6](slice-6-change-management.md) | Change management & contract versioning | ⬜ | 2, 4 |
| [7](slice-7-skills-thin-chat.md) | Skills thin-chat redesign + scaffold sync | ⬜ | 2 |
| [8](slice-8-rollout-upstream.md) | Docs, DD consolidation, rollout & upstream | ⬜ | 5, 6, 7 |

## Dependency graph

```text
0A ─▶ 0B ─▶ 1 ─┬─▶ 2 ─┬─▶ 4 ─▶ 6 ─▶ 8
               │      ├─▶ 7 ─────────▶ 8
               │      └─▶ 5 ─────────▶ 8
               └─▶ 3 ─▶ 5
```

Slices 1–2 are mostly serial (registry is foundational). 3–7 parallelize once 2
lands.

## Concept evaluation summary

The conceptual assessment driving this implementation (full detail in the
session plan):

- **Strong spine — build with confidence:** materialize-on-claim, evidence-led
  claims, thin ontologies, MDM-first, silver-passthrough, contract versioning.
- **Sound-with-caveats:** Claim Registry (third source-of-truth risk), PBI
  fit-gap (as-is→to-be gravity), thin-chat skills (workflow-engine-in-markdown
  risk), alignment retirement (parity concern).
- **Most questionable — C2:** import-all accelerator + no-bypass projector fights
  OWL/closure semantics. Two forks (A1/A2) are decided in Slice 0B.

## Conceptual forks (decided in Slice 0B)

- **A1 — claims drive imports** (generate `owl:imports`/sub-pack from approved
  claims) vs **import-all-then-suppress**. A1 would resolve C2's perf/FK/no-bypass
  risk. **Slice 0A result (2026-06-15): A1 is now the recommended default.** The
  acme-hub spike confirmed claim-driven suppression of unclaimed *imports* leaks
  no FKs (correctness PASS), but acme-hub structurally cannot test catalog full-
  closure resolution or scale perf — so C2's motivating risk is unresolved. Adopt
  C2 only if a separate real large-closure spike clears perf + FK-leak. Also carry
  the 0A **Finding 3** decision into 0B: are *local* domain classes claim-gated, or
  implicitly claimed by being authored in the thin ontology?
- **A2 — collapse authored surfaces** (registry as the only authored artifact;
  generate extensions *and* thin-ontology stubs) vs three coherent surfaces.

## Parity-requirements appendix (gate for retiring alignment YAML)

Slice 1 may not merge until the Claim Registry demonstrably preserves every
guarantee the alignment path provided. The registry schema v1 (Slice 0B) MUST
cover **(all items satisfied as of 2026-06-15 — Slice 1 cutover complete)**:

- [x] per-(system, table, column) coverage snapshot (not just claim-level)
- [x] `source_sha256`-equivalent freshness hash for staleness detection
- [x] algorithm / prompt-contract version field
- [x] custom-column triage / disposition (`model` / `silver-passthrough` / `skip`)
- [x] anchor / ref-class validation state
- [x] evidence references at table/column granularity
- [x] deterministic alignment-YAML → registry conversion with golden tests
- [x] old alignment files error with a clear migration message (no dual path)

## Cross-cutting per-slice checklist

Every slice PR must satisfy:

- [ ] SPDX header (`Apache-2.0` / `Copyright 2026 Cnext.eu`) on new `.py` files
- [ ] Unit tests + scenario (acme-hub) tests for new behavior
- [ ] `__version__` bump + matching `CHANGELOG.md` entry (version-check CI)
- [ ] `uv run ruff check src/ tests/` clean
- [ ] `kairos-ext.ttl` vocabulary coverage for any new annotation
- [ ] `.github/skills` ↔ `scaffold/skills` synced (`scripts/sync-dev-skills.py`)
- [ ] DD entry in `docs/design/toolkit-design-decisions.md` if architectural
- [ ] Docs / skill updates shipped **with** the slice, not deferred
