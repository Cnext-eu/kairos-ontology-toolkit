# Slice 8 — Docs, DD consolidation, rollout & upstream

**Status:** ⬜ not started · **Depends on:** 5, 6, 7

## Goal

Promote the methodology from draft to canonical, consolidate decisions, and roll
out across the remaining domains and downstream consumers.

## Scope

- **Promote methodology** draft → `docs/methodology/accelerator-first-modeling.md`
  (reflecting measured spike reality and the A1/A2 decisions, not the hypothesis).
- **Consolidate DD entries** for each architectural decision made across slices
  (registry, retirement, projector authority/A1, A2, MDM gate, contract
  versioning) in `docs/design/toolkit-design-decisions.md`.
- **MDM-first discovery skill update** (`kairos-design-discovery`) to capture
  reference/master-data anchors early.
- **Rollout** — migrate remaining domains in small batches; each batch produces a
  `source-delta`/impact report and passes `check-claims`.
- **Dataplatform consumption notes** — how downstream dbt repos consume the new
  claim-driven projections (`kairos-package-dataplatform`).
- **Upstream follow-ups** — skill Gate-6 relaxation to accelerator-first,
  scaffold foundation template, routing updates (filed as toolkit issues/PRs).

## Acceptance criteria

- [ ] Methodology doc published under `docs/methodology/`.
- [ ] DD entries consolidated and cross-referenced.
- [ ] All in-scope domains migrated with passing `check-claims`.
- [ ] Upstream issues filed and tracked.

## Risks / notes

- Durability depends on the upstream skill Gate-6 change landing; track it to
  closure so hubs don't run "against the grain" indefinitely.
- Roll out per-domain in batches, re-running perf/FK checks (Slice 0A criteria)
  for each batch under the chosen import strategy (A1).
