# DD-170: A model-proposed hub-local property is validated, not trusted

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `propose-alignment`
**Implementation:** `core/propose_alignment.py` (`normalize_local_proposal`, `flag_risky_proposals`)

### Context

When no reference property fits, the aligner may propose a hub-local one. Left unchecked
the model returns IRI-shaped names, ranges that are classes, and role-flavoured properties
(`isShipper`, `customerFlag`) that are the `subclass-identity-by-role` anti-pattern wearing
a property's clothes.

### Decision

Local proposals pass `normalize_local_proposal`, which rejects IRI-shaped `name`, `range`
and `on_class`, and `flag_risky_proposals`, which flags role-shaped names for review. A
rejected proposal degrades to a gap column (DD-168) rather than entering the registry.

### Consequences

The two checks are coded, not prompt instructions — a prompt can be talked out of a rule,
a normalizer cannot.
