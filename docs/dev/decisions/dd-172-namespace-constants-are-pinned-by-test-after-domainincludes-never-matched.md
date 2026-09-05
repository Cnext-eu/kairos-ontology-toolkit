# DD-172: Namespace constants are pinned by test, after `domainIncludes` never matched

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** every projection and reader touching schema.org terms
**Implementation:** `core/projections/shared.py`, `tests/test_namespace_constants.py`

### Context

`SCHEMA = Namespace("http://schema.org/")`. Every reference model in the pack binds
`https://schema.org/`. The constant had therefore **never matched a single triple** in the
project's life, so the REUSABLE domainless-property pattern — `schema:domainIncludes` —
was invisible to every consumer. `TradeParty` presented 9 properties instead of 13, and
the four it hid were `hasAddress`, `hasBillingAddress`, `hasShippingAddress`, `hasContact`.
The live symptom was the aligner replying that *no address property is listed on
TradeParty* while `hasBillingAddress` to `Address` sat in the list it was reading.

A second instance of the same class of defect: object properties rendered identically to
datatype ones, so `hasBillingAddress (Address)` looked like a string property named
Address.

### Decision

Match both spellings (`DOMAIN_INCLUDES_PREDICATES`), mark object properties explicitly in
the prompt, and pin every namespace constant with a test that asserts the constant matches
what the shipped reference models actually bind.

### Consequences

A silently-never-matching constant produces no error, no warning and a plausible answer —
it can only be caught by asserting against real data. The guard was verified by
reintroducing the bug: it fails 2 of 3. The other 13 namespace constants were audited and
are correct.
