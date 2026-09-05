# DD-202: generate-bindings recognizes non-generatable rows before asking the validator

**Status:** Accepted
**Date:** 2026-08-20
**Affects:** `generate_binding_doc`, `run_generate_bindings` (`core/generate_bindings.py`)
**Issue:** #565

### Context

On a real hub, `generate-bindings` failed 27/59 tables (46%) with
`'relationships' is a required property`. The v5 contract conditionally
requires a non-empty `relationships:` whenever `fields:` is empty — but
`generate_binding_doc` never emits `relationships:` at all (that's
deliberately deferred to `propose-relationships`, per this module's own
docstring), so any table with zero mapped scalar fields was *always*
going to fail the closed-contract validator, regardless of how good its
FK-carrier evidence was. A second, narrower case: a table with
`grain_columns: []`/`natural_key: []` (one row in the sample; the sheet's
own grain detection came back empty) produced the same kind of validator
rejection. Both were reported as `invalid` drafts — the wording of a
defect in *this specific draft* — when the real, deterministic cause is a
property of *the row itself*: nothing about generation went wrong, there
was simply nothing generatable there.

### Decision

`generate_binding_doc` now returns `(doc, reason)` instead of a bare
`Optional[dict]`, with two guards evaluated before any document is built:
empty `grain_columns` returns `(None, "no grain identified on the sheet
row")` immediately (cheapest check, placed first, short-circuits before
the scalar-mapping loop even runs); an empty `fields` list after that loop
returns `(None, reason)`, where *reason* names whether relationship wiring
being deferred to `propose-relationships` is why the table has no scalar
fields (an FK carrier is present) or the table has no fields to map at all
either way — the outcome is identical in both cases, only the wording
differs. `run_generate_bindings` unpacks the tuple and uses *reason*
directly as the `skipped` outcome's note, instead of ever handing either
case to `load_entity_binding`.

### Consequences

Both known non-generatable shapes now report `skipped` with a specific,
accurate reason instead of `invalid` with a generic schema-validator
message. No schema or compiler change was needed — this is purely
generation recognizing a row it cannot write before asking the validator
whether it wrote something valid. A genuinely malformed draft (one that
passes both guards but still violates the contract some other way) still
reports `invalid`, unchanged.
