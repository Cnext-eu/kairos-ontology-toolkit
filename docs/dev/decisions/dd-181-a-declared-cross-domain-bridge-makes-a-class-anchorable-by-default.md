# DD-181: A declared cross-domain bridge makes a class anchorable, by default

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `propose-alignment`, `scaffold-domain`
**Implementation:** `core/analyse_sources.py` (`load_cross_domain_bridges`, `bridge_anchor_classes`), `core/propose_alignment.py` (`resolve_bridge_anchor_classes`, `_bridge_tag`)

### Context

A source table often holds rows of an entity its domain *references* rather than
*owns*. `stops` sits under `consignment`, but each row is a transport call — a
concept `route-schedule` owns. Offered only its home classes, the model has nothing
truthful to pick and correctly declines to anchor.

That is how 306 columns across nine tables ended up unanchored (DD-180), and the
only routes forward were both bad: import a module the domain has no business owning
(recreating the boundary erosion that DD-163 exists to catch, and that produced
`Booking` in `party` in the first place), or move the table to a domain that fits the
class but not the grain.

The blueprint already had the right mechanism and nothing read it for this purpose.
`cross_domain_relationships` declares exactly this — `source_domain` may reference
`range_class_uri`, owned by `target_domain`, through a named `property_uri` — and the
logistics pack ships 24 of them. The existing cross-module machinery is opt-in behind
`--cross-module --accelerator` and widens the *property* pool, not the anchor pool, so
a hub could declare a bridge and alignment would still not offer the class.

Reference-models v1.28.1 confirmed this is not a vocabulary problem: it added 663
resolved properties and **zero** classes, leaving all nine tables unanchored.

### Decision

Classes reachable through a bridge declared *from* a domain join that domain's anchor
candidate pool, tagged with the domain that owns them. Ownership does not move — the
tag is what lets the boundary check (DD-163) distinguish an authorised reference from
a redeclaration, and it tells the model in as many words that anchoring to the class
is allowed while minting a local copy is not.

**On by default, with no flag.** A bridge in the blueprint *is* the authorisation;
requiring a CLI flag to honour it would mean the default run ignores governance the
hub already expressed. Bridges load whenever a reference-models directory is present,
independently of `--cross-module`, and a test pins that ordering so the two cannot be
re-coupled by accident.

`load_cross_domain_bridges` returns bridges verbatim rather than filtering on
populated fields, because the scaffold header needs only `property_uri` while the
anchor pool needs `range_class_uri`. `cli/setup.py` now delegates to it, so a scaffold
header and an anchor pool cannot disagree about what the blueprint authorises.

### Consequences

On the live hub, `consignment`'s anchor pool goes from 25 to 33 classes —
`Invoice`, `TransportEvent`, `ServiceLoop`, `CustomsDeclaration` and four more, each
marked with its owner.

This supplies the mechanism, not the cure. **None of DD-180's nine tables is fixed by
the bridges that exist today**: no bridge declares `TransportCall`, and `compliance`
declares none at all. What changes is the shape of the remedy — a one-line blueprint
declaration that the toolkit then honours everywhere, instead of nine hand-added
imports that erode boundaries and trip DD-163. Landing the 306 columns needs, at
minimum, `consignment → route-schedule : TransportCall` (237 columns) and
`compliance → events : Event` (25).

A bridge is directional by construction: `booking → consignment` does not let
`consignment` anchor to `booking`'s classes.
