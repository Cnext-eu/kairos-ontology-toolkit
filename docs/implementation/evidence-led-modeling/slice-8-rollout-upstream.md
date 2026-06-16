# Slice 8 — Docs, DD consolidation, rollout & upstream

**Status:** ✅ done · **Depends on:** 5, 6, 7

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

- [x] Methodology doc published under `docs/methodology/`.
- [x] DD entries consolidated and cross-referenced.
- [ ] All in-scope domains migrated with passing `check-claims`. *(N/A in toolkit repo — rollout procedure documented in the methodology doc)*
- [ ] Upstream issues filed and tracked. *(drafted as follow-ups in the methodology doc; not filed — kept in-repo per user direction)*

## Risks / notes

- Durability depends on the upstream skill Gate-6 change landing; track it to
  closure so hubs don't run "against the grain" indefinitely.
- Roll out per-domain in batches, re-running perf/FK checks (Slice 0A criteria)
  for each batch under the chosen import strategy (A1).

## Delivered (2026-06-16)

- Published canonical methodology `docs/methodology/accelerator-first-modeling.md` (reflecting measured slice reality + A1/A2/MDM/contract decisions).
- Consolidated decisions: DD-080 in `docs/design/toolkit-design-decisions.md` cross-referencing DD-EL-1..9; DD-EL-10 records the 4.0.0-rc1 version freeze and no-cross-repo-push scope.
- MDM-first anchors added to `kairos-design-discovery`; claim-driven consumption notes added to `kairos-package-dataplatform`.
- Rollout = documented per-domain batch procedure; upstream follow-ups drafted (not filed). Everything kept in this repo at version **4.0.0-rc1**; no further version bumps.
