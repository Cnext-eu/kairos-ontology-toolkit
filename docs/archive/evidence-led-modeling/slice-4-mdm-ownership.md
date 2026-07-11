# Slice 4 — MDM/reference-data rules + ownership hardening

**Status:** ✅ done · **Depends on:** 2 · **Gates:** 6

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

- [x] MDM-anchor gate blocks/passes correctly on scenario hub
- [x] ownership override requires owner + rationale
- [x] passthrough-review flags repeated passthrough columns
- [x] deviation-log fails on undocumented native classes

## Acceptance criteria

- [x] Reference-data anchors gate broad claims.
- [x] Ownership conflicts blocked unless explicitly overridden.
- [x] version + CHANGELOG + ruff + tests.

## Risks / notes

- Keep the MDM gate pragmatic: require *major* anchors known, not every reference
  table fully implemented (per methodology §5.4).

## Implementation note (2026-06-15)

Slice 4 landed the MDM/reference-data + ownership hardening (DD-EL-6) entirely
**inside `check-claims`** — the single deterministic governance gate — plus the
registry schema it needs. `claim_registry.py` gained three dataclasses
(`ReferenceData`, `Deviation`, `OwnershipOverride`, each omitting None/default keys
in `to_dict`/`from_dict`) and five `Claim` fields (`reference_data`, `mdm_anchor`,
`deviation`, `ownership_override`, `passthrough_reviewed`), all preserved across
re-runs via `merge_preserving_decisions` / `HUMAN_CURATED_FIELDS` and all omitted
from output when default so the **byte-stable golden registry** is unchanged.
`validate_registry` does only **structural** well-formedness (warns on
`reference_data`/`mdm_anchor` set on a non-`reference_data` claim; errors on an
`ownership_override` missing owner or rationale); the **policy** judgement lives in
the gate. `check_claims_coverage` / `ClaimCheckReport` added four checks: the
**MDM-anchor gate** (§5.4 — blocking `anchor_pending` when a domain has broad
claims and declared `mdm_anchor` anchors still `proposed`; pragmatic warning
`anchor_missing` when broad claims have no declared anchors at all),
**deviation-log** (§12/§14 — blocking `deviation_missing` for approved `gap` classes
without an owner+reason record), **ownership-boundary** (§14 — blocking
`ownership_conflicts` when an approved `class_uri` falls under another data-domain's
`data-domains.yaml` `uris` prefix, unless an `ownership_override` with owner+rationale
is present), and **passthrough-review** (§11.2 — warning `passthrough_review` for
high-use passthrough claims not yet `passthrough_reviewed`). Cross-file same-URI
approved claims now downgrade to a `shared_dimensions` **warning** (instead of the
`duplicate_approved` block) when either side carries an `ownership_override`, making
conformed-dimension sharing an explicit, owned decision. New CLI flags
`--no-mdm-anchor` / `--no-ownership` give a deliberate named bypass. These are
governance fields, not ontology semantics, so `kairos-ext.ttl` is untouched.
