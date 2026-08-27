---
name: kairos-toolkit-dogfood
description: >
  Run an adversarial dogfood session against a real client's source data, on a
  toolkit build under test, with the explicit goal of finding and fixing gaps
  in the TOOLKIT itself. The hub built along the way is instrumental, not the
  deliverable — a hub built for its own sake, autonomously and at production
  quality, is kairos-flow-autopilot's job, not this skill's. NOT for
  developing the toolkit's own code directly (kairos-toolkit-dev, used once a
  gap is confirmed) or releasing/updating a hub's dependency pin
  (kairos-toolkit-ops, consumed by this skill for `--test-ref` pinning).
---
<!-- kairos-ontology-toolkit:managed v2.35.0 -->

# Toolkit Dogfooding

A dogfood session is not "use the toolkit" — it is a deliberate audit. The mindset is
adversarial curiosity, not delivery: build a real hub end-to-end against real client
data, treat every point of friction as a candidate defect rather than something to
quietly work around, and close the loop by feeding confirmed findings back as
toolkit issues (and, in a follow-up cycle, fixes). **The success criterion is the
number and quality of real, confirmed findings — not how polished or complete the
hub ends up.** A session that stalls for two hours on one confusing error and then
files a sharp, well-evidenced issue about it did its job; a session that breezes
through five domains without incident and files nothing almost certainly wasn't
looking hard enough.

This is the fork of the hub lifecycle whose purpose is finding gaps. If the actual
goal is to deliver a working client hub — production intent, bounded stages,
decision-log transparency as the deliverable rather than a debugging aid — use
**kairos-flow-autopilot** instead; do not use this skill's adversarial, exploratory
posture on a real delivery timeline.

This is DD-148/DD-133-aware process guidance, not a new compiler contract. It borrows
its stage model and several hard-earned rules from a prior session's handover
(toolkit issue #339) — read that issue once before your first dogfood session; do not
rediscover its findings from scratch.

## When to use

Use this skill when the goal is explicitly to exercise the toolkit against a real
(or realistic) client dataset to find gaps — a new client onboarding rehearsal, a
regression dogfood after a fix batch, or a scheduled "does this still work end to
end" pass. Do not use it for routine hub work with no audit intent, and do not use it
when a client actually needs a delivered hub at the end — both of those are
`kairos-flow-autopilot`.

## Stage 0: Prerequisites (do not skip)

Confirm and record each of these before Stage 1 begins. Treat an unrecorded prereq
the same as a missing one — "I decided X" that lives only in chat history is not a
prerequisite that transfers to a resumed or handed-off session.

1. **Toolkit-under-test is pinned explicitly.** Use `kairos-ontology update --test-ref
   <branch-or-sha>` (owned by `kairos-toolkit-ops`) to pin an unmerged branch under
   test, or a real released version via the normal channel. Do not point `--project`
   at a local toolkit checkout as a substitute — `--test-ref` records restore
   metadata and is itself part of what you are dogfooding; an ad hoc override skips
   exercising that mechanism and leaves nothing for `--restore` to undo.
2. **The new hub is git-initialized at creation**, not late. `git init -b main`
   immediately after scaffold, before the first source import, so every later stage
   diffs cleanly and `guard-scope` (which needs a git history to compare against) is
   usable from Stage 1 onward, not bolted on after the fact.
3. **Source and business-discovery inputs are staged and their reuse scope is
   explicit.** If reusing `.import/sources/` or `.import/businessdiscovery/` content
   from a reference hub, state in the session record exactly what is reused and what
   is explicitly excluded (ontologies, bindings, decisions, catalog — prior hub
   design artifacts almost never transfer, since the point is to re-derive them
   against this hub's own evidence). Copy business-discovery content through a
   scratch temp directory first, not directly into `.import/businessdiscovery/` —
   `init` pre-scaffolds a stub `README.md` there, and a direct recursive copy nests
   one level too deep.
4. **The accelerator pack is selected** (`[tool.kairos] accelerator` in
   `pyproject.toml`) and matches the client's actual domain (logistics, freight,
   etc.) — confirm with `suggest-anchor`, not by assumption.
5. **The session's stopping stage is declared up front.** Say which of the stages
   below the session is scoped to reach (see next section) before starting — this is
   a scope decision, not a discovery you make along the way. A session legitimately
   stops after domain design in one run and continues through silver dbt in the
   next; both are valid, but which one this run is doing must be stated, not
   inferred from how far you happened to get.

## Stages

Adopted from #339, which independently converged on the same shape as this session's
two runs. A session may stop at any stage boundary per its Stage 0 declaration;
stopping early is not a failure, it's a scope decision.

| Stage | What it produces | Owning skill(s) |
|---|---|---|
| 0 | Hub scaffolded, git-initialized, sources imported | `kairos-setup-init`, `kairos-design-source` |
| 1 | BI/business-discovery artifacts staged and parsed | `kairos-design-source` |
| 2 | Validated archetype-conformance artifact; DD-148 gate unblocked for the domains in scope | `kairos-design-discovery` |
| 3 | Ontology domains authored, `_master.ttl` synced, `validate` clean | `kairos-design-domain` |
| 4 | EntityBindings authored, `compile --check`/`--explain` clean per domain | `kairos-design-mapping`, `kairos-develop-dbt-transformation` |
| 5 | Silver dbt emitted (`compile --emit`), `validate-dbt`/`audit-silver-samples` run against real samples | `kairos-execute-project` |
| 6 | Pattern-conformance / Gold / MDM projections, if in scope | `kairos-design-gold`, `kairos-design-mdm` |

Stage 5 (`validate-dbt`, `audit-silver-samples` against real data, not just `compile
--emit` succeeding) was skipped in both of this repo's dogfood runs so far — treat
"emit succeeded" as necessary, not sufficient, evidence that the silver layer is
correct; a session that reaches Stage 4 should say explicitly whether Stage 5's real-
data checks ran, not just that emit exited 0.

## Fleet-mode execution rules

Multiple agents may work a stage in parallel only when their outputs cannot collide
on a shared file. Decide this before dispatching, not after a collision:

- **Sequential, always**: any step that calls `init --domain` (writes
  `catalog-v001.xml` and `_master.ttl`), edits the discovery judgments file, or runs
  `compile --emit` (writes shared `dbt_project.yml`, `packages.yml`, the shared
  sources YAML, and per-domain compile manifests under one publish root).
- **Parallel, no isolation needed**: hub-data operations scoped to disjoint files —
  one agent per domain authoring that domain's EntityBinding(s), one agent per
  source system on initial import, one agent per domain's ontology *content*
  authoring once each domain's own `init --domain` has already run sequentially.
- **Parallel, worktree-isolated**: only when agents edit the *toolkit's own code*
  concurrently (a follow-up fix-implementation cycle, not the dogfood session
  itself) — worktree isolation is expensive and pointless for hub data agents that
  don't share files.
- Compile-time reads (`compile <domain> --check`/`--explain`) are always safe in
  parallel — they do not write hub files.

## Decision Log discipline

`kairos-design-mapping`'s materiality rule ("if a mapping choice resolves a genuine
tension or real gap, persist it with `decision new`") applies with equal force to
Stages 2 and 3, not only Stage 4 — extend it explicitly:

- Every discovery judgment resolved without a live human (fleet mode, per
  `kairos-design-discovery`) that reaches `conforms-with-rename`, `deviates`, or
  `not-applicable` on real evidence is a genuine tension resolved — it earns a
  Decision Log entry when the resolution is non-obvious from the label alone (a
  rename from ambiguous evidence, a deviation from client-specific terminology), not
  when it's a mechanical rubber-stamp of an already-obvious match.
- A `likely_domains` re-scoping decision (tagging a judgment to a not-yet-modeled
  future domain, per DD-148's domain-scoped gate) is itself a decision worth
  recording once, at the batch level — not one record per item, but one record
  documenting the domain clusters chosen and why, so a later session doesn't
  silently re-derive or contradict it.
- Run `decision sync-index` at the end of every stage that touched
  `decisions/`, not only when a human notices `index.md` looks stale.

## Verification discipline

Never accept a fleet agent's self-report as ground truth — this applies doubly in a
dogfood session, where the entire point is catching what would otherwise go
unnoticed. Per stage, verify directly:

- **Ontology authoring**: parse with `rdflib.Graph().parse()` independently of the
  authoring agent's own claimed triple count; run `validate --syntax --domain <x>`
  yourself.
- **EntityBinding authoring**: re-run `compile <domain> --check`/`--explain` yourself
  after the agent reports success — do not relay a reported exit code you did not
  see.
- **Multi-source decisions**: when an agent asserts "single-source, no merge
  needed," spot-check its cited evidence (grain, primary key, column overlap)
  directly rather than trusting the narrative — a plausible-sounding justification
  for skipping the more expensive merge path is exactly the kind of assertion worth
  distrusting most.
- **Fix batches from a follow-up implementation cycle**: diff review plus, for the
  most consequential fixes, a live empirical run against this session's own real
  hub data — not unit tests alone.
- **Guard-scope**: use it, but know its Windows caveat (`--allow=<glob>` equals-form,
  not the space form) and its blindness to gitignored paths — it narrows what to
  review, it does not replace reviewing it.
- **Before hand-building any review artifact, check it doesn't already exist as a
  toolkit command.** `field-mapping-report --source-system <sys>` already produces
  a per-domain, per-source-system Excel field-mapping workbook with real sample
  values (`ontology-hub-publish/reports/field-mapping-<sys>.xlsx`) — a dogfood
  session in this repo's own history hand-built an equivalent report from scratch,
  in the wrong location, because no skill referenced the command that already did
  it. Grep `.claude/skills/*/SKILL.md` and `cli/*.py --help` output before
  concluding something needs building.

## Finding capture and GitHub issue discipline

Keep a running findings note during the session — do not reconstruct findings from
memory at the end. For each candidate finding, decide immediately which bucket it's
in:

- **Hub content mistake** (wrong key name, missed field, typo) — fix directly in the
  hub, note it in the session record, no GitHub issue.
- **Real toolkit gap** — confirmed reproducible, not hub-specific — candidate for a
  GitHub issue.
- **Uncertain** — leave open in the running note; resolve before the session ends,
  don't let it silently drop.

Before ending a session (or before declaring a stage complete), run a closing
self-audit: re-read the running findings note and confirm every "real toolkit gap"
item is either already filed, filed just now, or explicitly deferred with a
recorded reason. This is not optional busywork — the second dogfood session in this
repo's history filed one finding immediately and left three more confirmed,
independently-reproduced gaps unfiled until asked to check.

When filing, combine related findings into one issue rather than filing one per
symptom — group by root-cause proximity ("the design-time tooling doesn't check
what its own gate is supposed to check"), not by which stage surfaced them. Cite exact
file:line, a real repro against this session's hub, and — critically — confirm the
finding is not already filed or already fixed before writing it up (`gh issue list
--search <keyword>`); more than one dogfood session has cited a bug already fixed
three releases earlier.

**Privacy rule** (from #339, non-negotiable): real client data stays local. Issue
bodies, repro steps, and code comments quote toolkit paths, command output, and
synthetic/redacted examples only — never real column values, sample rows, customer
names, or client-identifying business terms beyond what's already public knowledge
about the engagement.

## Pre-flight, before the adversarial-review round

If this session's findings lead to a follow-up fix-implementation cycle, run this
checklist on each fix plan before finalizing it — before the adversarial-review
round, not instead of it (see toolkit issue #339's comment thread for the full
rationale and case-by-case evidence that this catches a distinct class of defect the
adversarial round does not reliably catch on its own):

1. Grep the toolkit's own design-decision record for the mechanism before designing
   a new one — implement or correct the existing decision rather than inventing a
   policy that might disagree with one already on record.
2. Trace one hop of downstream consumers for any field, column, or check the plan
   reinterprets.
3. If the plan adds a rejection or narrows a gate, run the accepted alternative
   against a real failing case first — not "should compile," actually try it.
4. Any comparative or quantitative claim in the plan ("most," "rare," "the common
   case") gets measured against this session's real hub/source corpus before it's
   written down, or it doesn't ship in the plan.

## Model tier and delegation

- Cheaper/faster models for mechanical fleet work (source import, straightforward
  single-domain binding authoring); higher-effort models for triage, multi-source
  judgment calls, and adversarial review.
- All git and GitHub actions (commits, branches, pushes, issue/PR creation) stay
  with the driving session — never delegate these to a subagent, even a
  worktree-isolated one authoring the underlying change.

## Session handover

If a session is paused, exceeds context, or is handed off, produce a handover note
(see #339 for the reference format) recording at minimum: the resume command(s), the
toolkit ref under test, the hub's git state (path, commit), Stage 0 prerequisites as
actually recorded, which stages completed, findings filed vs. deferred (with
reasons), and any local-only state that does not transfer (sample data locations,
uncommitted scratch files). A session that ends without this is not resumable — the
next session re-derives everything it already knew.

## Anti-patterns

- Treating "compile --emit exited 0" as proof the silver layer is correct without
  Stage 5's real-data validation.
- Filing a GitHub issue for a hub content mistake, or silently fixing a real
  toolkit gap in hub content instead of filing it.
- Pinning the toolkit under test with an ad hoc `--project` override instead of
  `update --test-ref`.
- Parallelizing any step that writes `catalog-v001.xml`, `_master.ttl`, or the
  discovery judgments file.
- Ending a session without a closing findings audit or a handover note.
- Designing a fix plan for a follow-up cycle without the pre-flight checklist,
  then relying on the adversarial round to catch what a five-minute self-check
  would have.

## Related skills

- **kairos-flow-autopilot** — same hub lifecycle, opposite intent: use it instead of
  this skill when the goal is a delivered client hub, not toolkit gap-hunting.
- **kairos-toolkit-ops** — pin the toolkit under test (`update --test-ref`,
  `--restore`); release fixes that come out of a follow-up cycle.
- **kairos-toolkit-dev** — implement toolkit fixes found during the session.
- **kairos-setup-init**, **kairos-design-source**, **kairos-design-discovery**,
  **kairos-design-domain**, **kairos-design-mapping**,
  **kairos-develop-dbt-transformation**, **kairos-execute-project** — the stage-owning
  skills this one wraps; this skill adds process discipline around them, it does not
  replace their gates.
