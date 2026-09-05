# DD-204: `rdfs:domain owl:Thing` gets its own diagnostic, on both sides of the boundary, instead of being read as a missing `owl:imports`

**Status:** Accepted
**Date:** 2026-08-20
**Affects:** `_warn_unattached_property_domains` (`core/analyse_sources.py`), `validate_naming_conventions` (`core/validator.py`)
**Issue:** #328

### Context

Issue #328 was closed by #330, but #330's own diff explicitly left this
half of the problem "deliberately unchanged": a property whose
`rdfs:domain` is `owl:Thing` attaches to no class and is invisible to the
compiler and every projector, with no diagnostic anywhere. Reopened with
fresh evidence: on a real client hub's `coverage-report`, 49
property-domain assertions in the reference-models package's own
`onerecord.iata.org/ns/cargo` module — a vendor reference model, not a
hub-authored domain — could not attach to any class, and debug-logging
every one showed all 49 declare `rdfs:domain owl:Thing`.

The root cause (confirmed by reading `_class_uris` in
`core/semantic_index.py`, ~427): `owl:Thing` is the OWL spec's implicit
universal class. No real ontology file ever declares it
`owl:Class`/`rdfs:Class`, so it never enters `_class_uris`, and
`build_semantic_index` (~472-499) then finds no bucket for it and records
the property as unattached — indistinguishable, at that point, from a
property whose module genuinely forgot an `owl:imports`. But the two
causes are not the same defect and do not share a fix: no amount of
importing makes `owl:Thing` a declared class. The existing warning in
`_warn_unattached_property_domains` collapsed both into one message that
told an author to check `owl:imports`, which is actively wrong advice for
the `owl:Thing` case.

Whether an `owl:Thing`-domain property should instead attach to every
class in the closure (making the cross-cutting shape work by construction)
is a bigger semantic decision the issue itself leaves open — "if
`schema:domainIncludes` is the answer, say so... if it is not, the gap
needs a decision" — and is explicitly **not** decided here. This DD only
makes the existing silent failure loud, on both sides of the boundary
where it can occur.

### Decision

Two independent, additive diagnostics, neither changing attachment
semantics in `semantic_index.py` or `effective_domain_classes`:

1. `_warn_unattached_property_domains` now buckets each unattached
   `(property, class)` pair by cause before logging: pairs whose class URI
   is `owl:Thing` get their own warning naming issue #328 and stating
   plainly that this is *not* a missing `owl:imports`; pairs whose class
   URI is anything else keep the original wording and the original
   `data-domains.yaml does NOT resolve it` guidance. Both messages can fire
   in the same run, each counting only its own pairs — this is the only
   human-facing surface `unattached_property_domains` reaches (the field is
   deliberately excluded from any hashed/serialized report payload), so
   fixing the message here is sufficient to fix it everywhere a human reads
   it.
2. `validate_naming_conventions` gets a new warning,
   `property_domain_owl_thing`, mirroring the shape of the
   `property_range_owl_thing` warning #330 already shipped for the range
   side: an `owl:DatatypeProperty`/`owl:ObjectProperty` in a hub's own
   authored file whose `rdfs:domain` includes `owl:Thing` gets a warning
   (not an error — this is currently the only escape a cross-cutting
   property has, so it must not block a build) pointing at issue #328 and
   suggesting `schema:domainIncludes` as the alternative that does not
   require an `owl:imports` cycle. This only ever fires on hub-authored
   files validation actually parses; reference-model files are never
   validated (DD-188), so the 49-property vendor case that motivated this
   DD is caught only by diagnostic 1, not this one — that boundary is
   correct and unchanged.

### Consequences

An author or operator now gets an accurate, actionable message for both
directions this defect can be found in, instead of either silence or
advice that sends them looking for a missing `owl:imports` that was never
missing. Whether `owl:Thing`-domain properties should attach everywhere,
and whether `schema:domainIncludes` is the prescribed modelling answer for
the cross-cutting shape, remain open — a future DD, not this one.
