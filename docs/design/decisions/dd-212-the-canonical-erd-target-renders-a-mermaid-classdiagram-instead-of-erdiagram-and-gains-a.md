# DD-212: The canonical `erd` target renders a Mermaid `classDiagram` instead of `erDiagram`, and gains a plumbing-only overlay hook

**Status:** Accepted
**Date:** 2026-08-30
**Affects:** `core/projections/erd_projector.py`, `core/projector.py` (`_discover_extensions` gains an
`erd` branch; the `erd` dispatch passes `overlay_path`), `tests/test_erd_projector.py`

### Context

DD-209's canonical `erd` target (binding-independent, walks the ontology graph directly) rendered a
Mermaid `erDiagram`, matching the Silver/Gold bound ERDs it sits alongside. `erDiagram` has no syntax
for class inheritance at all, and `erd_projector.py`'s only use of `rdfs:subClassOf` was for OWL
restriction-cardinality traversal (mirroring `projections/shared.py`'s FK cardinality-one detection) —
never for rendering a hierarchy edge. OWL class hierarchies are ordinary, common modeling content, so
the one diagram meant to show the canonical model's *full* shape was silent on a structural feature
that shape routinely has. Separately, `erd` was the only architecture-level target
(`ddd`/`erd`/`report`) with no overlay-extension hook at all — `ddd` already supports
`{domain}-ddd-ext.ttl` — so there was no way to add a future projection-specific hint (grouping,
attribute hiding, diagram-inclusion filters) without new discovery/dispatch plumbing.

### Decision

Rewrite `erd_projector.py`'s rendering from `erDiagram` to Mermaid `classDiagram`, chosen over
PlantUML or another UML tool because it needs zero new tooling — the same optional `mmdc` CLI
(`render_mermaid_svg`) already used elsewhere renders it, and no other diagram technology exists
anywhere in this codebase. Named, non-restriction `rdfs:subClassOf` triples between two domain-local
classes now render as inheritance edges (`Superclass <|-- Subclass`); the existing
`_restriction_bounds` min/max-bound logic is unchanged and now renders as `classDiagram` multiplicity
strings (`"0..1"`/`"1"`/`"0..*"`/`"1..*"`) instead of crow's-foot tokens. The output filename
convention (`{domain}-erd.mmd`) is unchanged — `mmdc` detects the diagram type from the
`classDiagram` keyword inside the file. Silver/Gold bound ERDs are untouched: physical dbt tables
have no class-hierarchy concept, so `erDiagram` remains the right fit there.

Separately, `generate_erd_artifacts` gained an `overlay_path: Optional[Path] = None` parameter, and
`_discover_extensions` gained an `elif target_name == "erd":` branch globbing `{onto_name}-erd-ext.ttl`
(exact match, no wildcard fallback — mirroring `ddd`'s convention, not `silver`'s `*-silver-ext.ttl`
wildcard), read the same established way every overlay file in this codebase is read: a raw
`graph.parse(path, format="turtle")` merge, never through the full `ontology_loader.load_ontology()`
closure-resolution path reserved for base domain ontologies. This is plumbing only — no
`kairos-erd.ttl` vocabulary or annotation properties exist yet; passing no `overlay_path` leaves
output byte-identical to before this parameter existed.

### Consequences

Class hierarchies modeled in the ontology are now visible in the one diagram meant to show the full
canonical shape, with no new diagram tooling. A future ERD-specific hint vocabulary can be added by
touching only `erd_projector.py`'s rendering logic — no further discovery/dispatch plumbing needed.
`tests/test_erd_projector.py` covers inheritance rendering (including that a restriction's blank-node
`subClassOf` is never mistaken for a superclass), multiplicity strings, and the overlay hook (both
that overlay triples are merged and that a missing overlay path leaves output unchanged).

### Amended (#678 / #704): scoped to *reachability*, not to the namespace

As decided above, an inheritance edge rendered only between "two domain-local classes". That made
this decision's own rationale inert in the case the toolkit exists for. A hub's classes specialize
imported reference-model classes — the style `kairos-design-domain` recommends — so every superclass
is out-of-namespace and every edge was discarded. Measured on a real hub: **1 of 29** `subClassOf`
edges and **63 of 237** datatype properties rendered; one domain rendered 3 attributes and hid 49.
The one diagram meant to show the canonical model's full shape drew a single inheritance arrow, and
its header actively claimed it "reflects the ontology graph", so absence read as non-existence.

Four filters caused it, not the two originally reported: the namespace filter on classes, the
`parent in class_set` guard on inheritance, the same guard on relationship *domains*, and attribute
collection via `effective_domain_classes`, which performs no `subClassOf` entailment.

The scope rule becomes **reachability**: a class outside the namespace is drawn when a domain class
inherits from it or an edge touches it, and only then. An unrelated imported class stays out, so the
diagram remains domain-scoped. Concretely:

- an out-of-namespace class renders as a **stub** — a stereotype naming its source model
  (`<<bsp/party>>`), no members. Its attributes are listed on the classes that inherit them, so
  repeating them would double every inherited attribute in the diagram;
- a domain class lists **inherited** datatype properties alongside its own, prefixed `#`;
- an inheritance or relationship edge survives when **either** end is domain-local, which also fixes
  a latent asymmetry: an out-of-namespace *range* already rendered as a bare node with no class
  block, while an out-of-namespace *domain* was dropped entirely;
- a relationship declared on a superclass is drawn from the **subclass** — the class whose instances
  carry it — and labelled `(inherited)`. Cardinality is still read from the declaring class;
- the header states the stub and `#` conventions, so what is omitted is said rather than implied.

`effective_domain_classes` is deliberately **not** widened with `subClassOf` entailment. It is the
DD-131 authority the silver/dbt projectors and the semantic index share, so inherited properties
would begin materializing as **Silver columns** project-wide. The inheritance walk lives in
`erd_projector.py` alone, and is cycle-safe because an imported model may assert a `subClassOf`
cycle.

Verified against `mmdc` 11.12.0: the stereotype, the `#` member prefix and the `(inherited)` edge
label all render. Both pre-existing scoping tests still pass unchanged —
`test_only_domain_local_classes_are_rendered` uses an *orphan* foreign class (still excluded, since
nothing reaches it) and the restriction test's parent is a blank node.
