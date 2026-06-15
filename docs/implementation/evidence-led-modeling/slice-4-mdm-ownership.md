# Slice 4 — MDM/reference-data rules + ownership hardening

**Status:** ⬜ not started · **Depends on:** 2 · **Gates:** 6

## Goal

Make the MDM-first concept (C6) enforceable and harden ownership, now that
`reference_data` claims and projected artifacts are concrete.

## Scope

- **MDM-anchor gate** in `check-claims` — block approval of broad domain claims
  before required reference/master anchors (conformed dimensions, code lists,
  natural keys) for that domain are known/approved.
- **Ownership override/deviation mechanism** — allow a documented exception
  (owner + rationale) when a claim crosses a `data-domains.yaml` boundary or a
  class is shared as a conformed dimension.
- **`passthrough-review`** check — flag repeated / high-use passthrough fields
  (multi-source, used in measures/joins/filters) for promotion review.
- **`deviation-log` check** — require every client-native (`gap`) class to have a
  recorded deviation/gap decision.

## Affected modules

`check_claims` backend, `claim_registry.py` (reference_data semantics),
`data-domains.yaml` consumption, `cli/main.py`.

## Tests

- [ ] MDM-anchor gate blocks/passes correctly on scenario hub
- [ ] ownership override requires owner + rationale
- [ ] passthrough-review flags repeated passthrough columns
- [ ] deviation-log fails on undocumented native classes

## Acceptance criteria

- [ ] Reference-data anchors gate broad claims.
- [ ] Ownership conflicts blocked unless explicitly overridden.
- [ ] version + CHANGELOG + ruff + tests.

## Risks / notes

- Keep the MDM gate pragmatic: require *major* anchors known, not every reference
  table fully implemented (per methodology §5.4).
