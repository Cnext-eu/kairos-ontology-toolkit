# DD-148: Discovery-Before-Design and Fleet-Mode Open-Question Hard Gates (Amends DD-059)

**Status:** Accepted
**Date:** 2026-08-10
**Affects:** `kairos-ontology compile`/`validate`/`discovery-conformance validate`,
`kairos-ontology next`, `kairos-design-domain` skill
**Implementation:** `src/kairos_ontology/core/conformance_artifact.py`,
`src/kairos_ontology/cli/compile.py`, `src/kairos_ontology/cli/validation.py`,
`src/kairos_ontology/cli/sources.py`, `src/kairos_ontology/core/hub_inspection.py`,
`src/kairos_ontology/core/next_actions.py`, `.github/skills/kairos-design-domain/SKILL.md`
(+ scaffold copy)

### Context

DD-059 made discovery-completeness a recommendation, not a hard block, because source data
(Gate 6) remained the authoritative evidence — discovery only improves naming alignment. In
practice this let real design proceed on inferred business terms (order lifecycle states, party
roles, "on-time" definitions) without ever running discovery, surfaced during a client-hub
review of a `TransportOrder` domain slice.

Separately, `kairos-design-discovery`'s own instructions already claimed discovery entries could
carry `confidence`, `rationale`, `references`, and `needs_confirmation`, and that fleet mode
(DD-088, unattended AI pre-fill) must record AI-approved choices distinctly from user-confirmed
ones — but `conformance_artifact.py`, the code that actually builds/validates the artifact,
implemented none of these fields. There was no way to *detect*, let alone block on, "this
discovery artifact has unresolved fleet-mode items."

A prior attempt to relabel `ActionStatus.BLOCKING` inside `kairos-ontology next` was found to
have zero mechanical effect: that status is set only for compile-diagnostics, is never read or
branched on anywhere, and `next` always exits 0 by design (DD-137) — it is advisory, recomputed,
and never authority.

### Decision

1. **Machine-checkable open questions.** `conformance_artifact.py` gains a required
   artifact-level `mode: "interactive" | "fleet"` field, and per-concept `confidence`,
   `rationale`, `references`, `needs_confirmation`, and `decided_by: "user" | "ai"` fields.
   `open_questions(artifact)` returns the AI-decided concepts (explicit `decided_by: "ai"`, or
   absent under `mode: fleet`) that are either `needs_confirmation: true` or have no recorded
   `confidence` — interactive-mode artifacts never produce open questions.
2. **Real enforcement in `compile`/`validate`.** A new `check_discovery_gate(hub_root)` helper
   hard-fails (non-zero exit, no bypass flag) when there is **neither** a `businessdiscovery/`
   narrative (DD-048) **nor** a conformance artifact (DD-090) — the two are independent
   discovery outputs and either satisfies this baseline; a hub with only a narrative and no
   archetype-conformance run is not blocked. When a conformance artifact does exist, the gate
   additionally fails when `open_questions()` is non-empty, regardless of the narrative. It is
   called from `kairos-ontology compile` and `kairos-ontology validate` — the two commands that
   already exit non-zero on failure (Gate 5's syntax check, compile-diagnostics) — deliberately
   without the outcome-codes catalog dependency `validate_artifact()` needs, so the gate never
   requires resolving an accelerator. `discovery-conformance validate` gets the unresolved-items
   check plus a `--allow-unresolved` escape hatch, since that command is also used
   standalone/diagnostically.
3. **`kairos-ontology next` mirrors this as an advisory signal, not the enforcement.** Missing
   discovery and unresolved fleet-mode items are labeled `ActionStatus.BLOCKING` (a new
   `resolve-discovery-open-questions` action, priority 25) purely for visibility — the label has
   no exit-code effect in `next` itself, consistent with the DD-137 advisory contract.
4. **`kairos-design-domain` Gate 1** changes from "offer kairos-design-discovery" to a STOP
   condition: no confirmed discovery artifact, or an unresolved fleet-mode artifact, must invoke
   `kairos-design-discovery` before design proceeds.
5. `ARTIFACT_SCHEMA_VERSION` bumps 1→2 as an accepted breaking change — no hub was in production
   when this landed, so existing fixtures were updated in place rather than dual-supported.

### Consequences

- DD-059's "recommendation, not a hard block" framing is superseded: discovery completeness is
  now enforced the same way Gate 5/compile-diagnostics already are, via `compile`/`validate`
  exit codes, not via skill-prompt discipline alone.
- Every hub fixture used by CLI-level compile/validate tests needed a discovery artifact added;
  fixtures exercising `build_compile_plan`/`compile_domain` directly (library calls, not the CLI
  wrapper) are unaffected, since the gate lives in the CLI layer only.
- Pairs with DD-149 (human-confirmed archetype selection), which closes a related gap in the same
  skill.
