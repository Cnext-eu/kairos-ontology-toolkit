# Relationship-proposal hub

A synthetic hub whose only job is to put every `propose-relationships` join tier, and every
shape that must *not* resolve, in one place. Consumed by
`tests/scenarios/test_scenario_relationship_proposals.py`.

The unit tests in `tests/test_relationship_evidence.py` pin `_match_join` in isolation. This
fixture exists because the defects in #722 were not tier bugs in isolation — they were tier
*interactions* on a real hub: a rule that looked high-precision matched every pair of
relations at once, because that hub named every primary key the same thing.

Eight bindings across two domains (`sales`, `ref`), one synthetic source system (`erp`):

| Binding | Shape it exercises | Expected outcome |
|---|---|---|
| `order` | cross-domain child with a declared carrier | resolves `declared-fk`, gets a DD-138 `externalReference` |
| `order-line` | composite grain `[order_id, line_no]`; `order_id` is part of the identity but not all of it | still resolves `name` — the line-item archetype must survive DD-220's exclusion |
| `order-line` | a second declared carrier (`product_id`) aimed at a different parent | each carrier matches its own parent by name, never positionally |
| `order-ext` | 1:1 extension keyed by its parent's key, undeclared | sentinel — DD-220's accepted cost |
| `order-addendum` | the same shape, declared `purpose: relationship` | resolves `declared-fk` — the escape hatch for that cost |
| `shipment` / `shipment-leg` | uniform surrogate identity on both sides | sentinel plus a `join_candidates` hint — the #722 defect |
| `ref-customer` / `ref-product` | cross-domain parents | supply the `externalReference` contracts |

Nothing here is a fixture for compilation: the bindings map no `fields:`, so they are not
emittable and are not meant to be. `propose-relationships` reads authored YAML directly
rather than through the compiler loader, which is what makes that legal and what keeps the
fixture readable.

All names, classes, columns and namespaces are invented for this scenario. There is no
client data, no personal data, and no values drawn from any real source system.
