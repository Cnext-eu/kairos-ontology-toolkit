# DD-188: Ontology semantics live in the reference models, never in the toolkit

**Status:** Accepted
**Date:** 2026-08-17
**Affects:** every toolkit module that inspects a column name, a class name or a
property name — `propose_alignment`, `anchor_tables`, `class_anchoring`,
`gap_decisions`, `source_disposition`
**Supersedes in practice:** the hardcoded vocabularies listed under Consequences

### Context

The toolkit is a domain-agnostic engine. The reference models carry the domain
knowledge, and they are versioned, reviewed and shipped per accelerator pack —
`logistics` and `financial-services` today.

That separation has been leaking. `propose_alignment.py` alone hardcodes:

- **postal-address semantics** across seven constants (`_ADDRESS_PART_TOKENS`,
  `_ADDRESS_QUALIFIER_TOKENS`, `_ADDRESS_WEAK_TOKENS`, `_ADDRESS_CONTEXT_TOKENS`,
  `_ADDRESS_SUBDIVISION_TOKENS`, `_ADDRESS_PROPERTY_TOKENS`,
  `_ADDRESS_PART_TOKEN_KINDS`), including which tokens are "too weak" to be an
  address part without a qualifier;
- **finance semantics** (`_FINANCIAL_COLUMN_TOKENS`);
- **maritime semantics** — `_LOCATION_ROLE_PREFIXES = ("hasplaceof", "hasportof", "has")`.
  `hasportof` is DCSA vocabulary compiled into the engine.

The address vocabulary is also, specifically, *e-commerce* vocabulary: it knows
`billing`, `shipping`, `mailing`, `home`, `work` and `delivery`, but not
`pickup`, `origin` or `destination`. On the live logistics hub that asymmetry
alone was the whole defect — `delivery_location_city` clustered and
`pickup_location_city` did not, so one table's address detection covered 5 of 40
columns.

The obvious repair was to add the missing freight tokens. That is the wrong
repair: it compiles one industry's vocabulary deeper into a product that also
ships a financial-services pack, and it would have been the ninth such constant.

### Decision

**The toolkit must not encode ontology-level semantics — class names, property
names, or the token vocabularies that recognise them — unless a human explicitly
confirms that instance.** Structure is the toolkit's; meaning is the reference
models'.

The line: a rule that would still be true if the customer were a bank belongs in
the toolkit. A rule that names a concept — an address part, a port call, a
charge — does not.

The mechanism already exists and is already used. `core/pattern_loader.py` reads
`blueprints/patterns/<id>/pattern.yaml` from the reference models, and
`validator.py`, `conformance_judge.py`, `compiler/kernel.py` and `cli/sources.py`
consume it. Five patterns are externalised this way today: `temporal-quartet`,
`governed-code-list`, `qualified-role-assignment`, `deferred-relationship`,
`multimodal-order-leg`. Alignment is the stage that bypasses it and transcribes
the library into Python instead — its own comments admit as much
(*"Anchoring-relevant rules from the pattern library. Deliberately the small…"*,
*"Reference classes the pattern library marks as grain collisions"*).

New semantic knowledge therefore lands as pattern data, loaded per accelerator
pack. Not as a constant.

**The confirmed exception.** Some vocabulary is genuinely structural rather than
semantic — audit-column names, vendor placeholders, identifier shapes. Those may
stay, but each needs a comment saying why it is structural and not a concept, so
the next reader can tell a considered exception from an accreted one.

### Consequences

The following are now recorded as debt to be externalised, not extended: the
seven `_ADDRESS_*` vocabularies, `_FINANCIAL_COLUMN_TOKENS`, and `hasportof` in
`_LOCATION_ROLE_PREFIXES`. Adding a token to any of them is a decision that needs
this DD cited against it.

The immediate work this blocks and reshapes: the cross-domain projection detector
(toolkit issue on the alignment stage, reference-models issue for an
`entity-projection` pattern schema). The detection *logic* — cluster columns by
role prefix, require complementary part kinds, resolve the target class in the
domain's closure, emit an advisory candidate — is generic and stays. The
vocabulary that tells it what an address part is moves to the pack, so logistics
ships freight roles and financial-services ships its own.

The cost is a schema negotiation across two repos before code, rather than a
one-line frozenset edit. That is the point: a one-line edit is exactly how eight
of these arrived.
