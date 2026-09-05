# DD-149: Human-Confirmed Archetype Selection (Amends DD-088/DD-090)

**Status:** Accepted
**Date:** 2026-08-10
**Affects:** `kairos-design-discovery` skill, `conformance_artifact.py`
**Implementation:** `.github/skills/kairos-design-discovery/SKILL.md` (+ scaffold copy),
`src/kairos_ontology/core/conformance_artifact.py`

### Context

Archetype selection (`kairos-design-discovery` Phase 2.5, `discovery-conformance load
--archetype <id>`) had no confirmation step at all: the skill never documented how `<id>` should
be chosen or that a human must confirm it, and no code path enforced this — `archetype_loader.py`
resolves strictly by the id it's given, with no automatic matching/scoring logic to guard. This
was raised as the likely root cause of "the archetype is not always selected properly," and is a
consequential choice: it scopes the entire downstream reference-model import closure, so getting
it wrong is effectively irreversible once modeling begins.

### Decision

Archetype selection is never fleet-eligible. A new Gate A ("Archetype confirmation") in
`kairos-design-discovery` requires listing candidate archetypes, presenting them to the human, and
stopping for an explicit human reply naming the archetype id — recorded in the interview log —
before proceeding to `discovery-conformance load`. This choice is added to DD-088's list of
decisions fleet mode may never make on its own, alongside ambiguity, low confidence,
policy-sensitive choices, destructive/irreversible actions, and PII risk.

`build_artifact()` requires an explicit `archetype_confirmed_by="human"` value, stamped as
`archetype.confirmed_by` in the artifact; omission and every other value fail before an artifact
is built. The supported CLI mirrors that requirement in the judgments file. Its generated
template contains a blocking `<CONFIRM_HUMAN_ARCHETYPE:...>` sentinel, and
`discovery-conformance build` exits before writing until the field is explicitly changed to
`human`.

### Consequences

- Archetype selection now has the same paper trail as fleet-mode concept judgments (DD-148):
  a machine-checkable field, not just skill-prompt discipline.
- Enforcement is code-level for the evidence available to the toolkit: neither the builder nor
  CLI infers confirmation, and the scaffold remains mechanically incomplete until the explicit
  marker is authored. The toolkit cannot independently verify who typed a value in a YAML file;
  the interview log remains the auditable record of the human reply.
- Pairs with DD-148 (discovery-before-design hard gates), closing both gaps surfaced by the same
  client-hub review.
