---
name: kairos-flow-autopilot
description: >
  Fleet-managed, bounded-stage autonomous execution of the hub lifecycle to
  deliver a real client hub — scaffold through a stage boundary declared up
  front — with full decision-log traceability and a human-readable
  transparency report as the primary deliverable. NOT for hunting toolkit
  gaps (kairos-toolkit-dogfood, an adversarial posture this skill explicitly
  avoids) and not a replacement for kairos-flow's single-step advisory
  router, which this skill's autopilot loop calls repeatedly under the hood.
---
<!-- kairos-ontology-toolkit:managed v2.35.0 -->

# Flow Autopilot

Autopilot means unattended execution a human can trust after the fact, not
unattended execution a human has to re-verify from scratch. The deliverable is
twofold and neither half is optional: the hub itself, built to the declared stage
boundary, and a complete, human-readable account of every decision the autopilot
made without asking — what was decided, on what evidence, and how confident the run
was. A hub delivered without that account is not an autopilot delivery, it's an
unreviewable black box.

This skill borrows the same underlying stage-owning skills and several process
disciplines (fleet sequencing rules, Decision Log materiality) as
**kairos-toolkit-dogfood**, but the intent is the opposite. Dogfood mode wants
friction — it's hunting for toolkit gaps and treats the hub as instrumental.
Autopilot mode wants a clean, correct, on-time hub — friction found along the way is
reported (see Guardrails below), never chased down a toolkit-fix side-quest that
would blow the delivery timeline. If you notice yourself wanting to stop and design a
toolkit fix mid-run, that's a signal you're in the wrong skill for this session's
goal — finish or escalate the current stage, then switch.

## The contract: declare the bounded scope before starting

Before any work begins, state explicitly and get it confirmed (by the requesting
human, or recorded as an explicit instruction if already given):

1. **Which stage this run stops at** (see the ladder below) — never "as far as you
   get." A run scoped to "Stage 3, domain models only" that happens to also produce
   clean bindings has overrun its contract just as much as one that stops short of
   its target; report the overrun, don't just keep going because it was easy.
2. **Source of truth for inputs** — which source systems, which business-discovery
   material, and — critically — what is explicitly reused from a reference hub
   versus what must be re-derived from this client's own evidence. State exclusions
   as explicitly as inclusions (design artifacts — ontologies, bindings, decisions,
   catalog — almost never transfer; raw source/BI material sometimes does).
3. **Toolkit version**: a real released version via the normal channel, pinned in
   `pyproject.toml` the ordinary way. Autopilot delivery runs are not the place to
   test an unmerged branch — that risk belongs to `kairos-toolkit-dogfood`. If a
   specific pre-release must be used, say so explicitly and record why.
4. **Escalation contact** — who gets asked when a guardrail (below) fires. An
   autopilot run with nobody to escalate to is a run that will either stall
   indefinitely or make a policy call it had no authority to make; resolve this
   before starting, not when the first guardrail fires.

## The stage ladder

| Stage | Produces | Owning skill(s) |
|---|---|---|
| 0 | Hub scaffolded, git-initialized, sources imported | `kairos-setup-init`, `kairos-design-source` |
| 1 | BI/business-discovery artifacts staged and parsed | `kairos-design-source` |
| 2 | Validated archetype-conformance artifact; DD-148 gate unblocked for domains in scope | `kairos-design-discovery` |
| 3 | Ontology domains authored, `_master.ttl` synced, `validate` clean | `kairos-design-domain` |
| 4 | EntityBindings authored, `compile --check`/`--explain` clean per domain | `kairos-design-mapping`, `kairos-develop-dbt-transformation` |
| 5 | Silver dbt emitted (`compile --emit`), `validate-dbt`/`audit-silver-samples` run against real samples | `kairos-execute-project` |
| 6 | Pattern-conformance / Gold / MDM projections, if in scope | `kairos-design-gold`, `kairos-design-mdm` |

Each stage completes with its own gate genuinely green (`validate`, `compile --check`,
etc. — not merely attempted) before the next stage starts. A stage that cannot be
made to pass within the guardrails below stops the run at that boundary and escalates
— it does not proceed on a known-broken foundation because the schedule wants it to.

## Guardrails: when autopilot stops and asks

This skill's fleet work in Stage 4 is still `kairos-design-mapping`'s "design fleet
mode (DD-088)" underneath, and DD-088's own six stop-conditions still apply in
full — low confidence, ambiguous identity or grain, policy-sensitive choices,
proprietary/PII risk, unsafe/lossy expressions, and complex relational logic. Do not
treat the list below as replacing DD-088's; it extends it to the whole lifecycle and
raises where the escalation goes:

- **Every DD-088 stop-condition, unchanged**, now escalates to this run's declared
  contact (see the contract) rather than defaulting to an AI-approved decision —
  autopilot mode does not get to relax a stop-condition design-mapping itself
  already treats as blocking.
- **Any judgment call outside Stage 4 that is structurally the same shape as a
  DD-088 stop-condition** — a discovery resolution, a domain-scoping call, a
  multi-source merge-vs-single-source decision made during Stage 2 or 3 rather than
  Stage 4 — escalates on the same grounds, since DD-088's conditions describe the
  kind of decision, not the specific stage it happens to occur in.
- **A real toolkit blocker with no known workaround.** Report it plainly (this may
  still warrant a toolkit issue — file it, per `kairos-toolkit-dogfood`'s findings
  discipline, but do not open a fix-implementation side-quest inside an autopilot
  delivery run). Then escalate: continue past it only if the contact approves a
  specific documented workaround.
- **A stage's exit gate won't go green** within a reasonable number of iterations —
  escalate with the diagnostic history, don't silently keep retrying or, worse,
  weaken the gate to force a pass.

A run that never escalates is not necessarily a good run — for any real client hub,
zero escalations across all declared stages is itself worth a second look.

## Fleet execution rules

Same sequencing constraints as any hub build, restated because autopilot mode is
where getting this wrong is most expensive (an unattended collision is harder to
catch than one made in front of a person):

- **Sequential, always**: `init --domain` (shared `catalog-v001.xml`/`_master.ttl`),
  edits to the discovery judgments file, `compile --emit` (shared dbt project
  scaffolding).
- **Parallel, no isolation needed**: per-domain EntityBinding authoring once each
  domain's own `init --domain` has run; per-source-system import; per-domain
  ontology content authoring after sequential registration.
- Compile-time reads (`--check`/`--explain`) are always parallel-safe.
- No toolkit-code fleet work happens in this skill at all — a real toolkit blocker
  is a Guardrail escalation, never a worktree-isolated fix dispatched mid-run.

## Decision Log as the primary deliverable

This is the single biggest difference from dogfood mode's discipline: in dogfood
mode the Decision Log supports findings; in autopilot mode **it is the record a
human uses to trust a run they didn't watch**. Treat every non-mechanical judgment
made without escalation as mandatory to record, not optional-when-it-feels-material:

- Every discovery judgment resolved without a live human, with its evidence and
  confidence — not just the ones that "feel" non-obvious. A reviewer auditing an
  autopilot run cannot tell mechanical from judgment-call after the fact unless both
  are recorded the same way.
- Every multi-source merge-vs-single-source decision, with the evidence checked
  (grain, keys, column overlap) — this is exactly the kind of claim a reviewer will
  want to spot-check, so the record must contain enough to spot-check it without
  re-deriving it.
- Every `likely_domains` scoping decision, at the batch level, with rationale.
- Run `decision sync-index` at the end of every stage.

## Verification

Lighter than dogfood mode's adversarial stance, but still real — "autopilot" is not
license to skip checking:

- Independently confirm each stage's own exit gate (`validate`, `compile --check`)
  rather than relying on a sub-agent's reported exit code.
- Spot-check at least one multi-source or low-confidence decision per domain against
  its cited evidence directly.
- Stage 5 (`validate-dbt`, `audit-silver-samples` against real samples) is part of
  the stage's exit criteria if Stage 5 is in the declared scope — "emit exited 0" is
  not sufficient evidence the silver layer is correct.

## Transparency report

End of run (or end of the declared stage boundary), produce a report a human who was
not watching can act on without re-deriving anything:

- The declared contract (scope, stopping stage, toolkit version, input sources) as
  actually honored — flag any deviation explicitly, including overruns.
- Stage-by-stage status against the ladder, each with its exit-gate result.
- Every Decision Log entry created this run, summarized in one line each, with a
  link/path to the full record.
- Every guardrail escalation raised, how it was resolved, and by whom.
- Any toolkit gap reported (filed issue link), clearly marked as a byproduct, not
  this run's purpose.
- What remains for the next stage, if the contract stopped short of the full ladder.
- A generated field-mapping workbook per bound source system, for anyone reviewing
  the delivery who wants field-level detail without reading bindings directly:

  ```powershell
  $env:KAIROS_SKILL_CONTEXT = "1"
  uv run kairos-ontology field-mapping-report --source-system <system>
  ```

  Written to `ontology-hub-publish/reports/field-mapping-<system>.xlsx` — link each
  one from the report rather than hand-building an equivalent workbook.

## Anti-patterns

- Proceeding past a declared stopping stage because the next stage looked easy from
  where the run happened to land.
- Making a judgment call that belongs in Guardrails because escalating felt like it
  would slow the run down.
- Treating a real toolkit blocker as an invitation to fix the toolkit mid-run instead
  of escalating and reporting it.
- Recording only the decisions that "seem important" in the Decision Log — a
  reviewer cannot distinguish an omitted mechanical choice from an omitted judgment
  call after the fact, so both get recorded.
- Delivering a hub with no transparency report, or a report that only says "done."
- Using this skill's autonomy to justify skipping a stage's own exit gate.

## Related skills

- **kairos-toolkit-dogfood** — same lifecycle, opposite intent: use it instead of
  this skill when the goal is finding toolkit gaps, not delivering a hub.
- **kairos-flow** — the stateless single-step advisor this skill's loop calls
  repeatedly; use `kairos-flow` directly for a human-paced, one-step-at-a-time
  session instead of a bounded autonomous run.
- **kairos-toolkit-ops** — pin the real toolkit release used for delivery.
- **kairos-setup-init**, **kairos-design-source**, **kairos-design-discovery**,
  **kairos-design-domain**, **kairos-design-mapping**,
  **kairos-develop-dbt-transformation**, **kairos-execute-project** — the
  stage-owning skills this one orchestrates; their gates are not relaxed by running
  under autopilot.
