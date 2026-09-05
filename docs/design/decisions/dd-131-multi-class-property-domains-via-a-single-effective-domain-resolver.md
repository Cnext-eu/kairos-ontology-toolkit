# DD-131: Multi-Class Property Domains via a Single Effective-Domain Resolver

**Status:** Accepted
**Date:** 2026-07-26
**Affects:** `core/projections/shared.py`, `core/semantic_index.py`,
`core/projections/dbt/bind.py`, `core/projections/medallion_dbt_projector.py`,
`validate-mapping` (`core/design_validation.py`)
**Implementation:** `effective_domain_classes()` / `properties_with_domain()` in
`core/projections/shared.py`, consumed by the semantic index, dbt bind, and the
medallion dbt projector's datatype-property membership loops.

### Context

A property whose domain legitimately spans several classes with **no common local
parent** (e.g. a `currency`/`amount` shared by `Invoice` and a parentless charge
line) could not be declared in a DL-correct way that the toolkit honoured
(issue #240). `owl:unionOf` domains and `schema:domainIncludes` were silently
ignored, and repeated `rdfs:domain` only "worked" by accident in SPARQL-based
projectors while being unreliable in dbt, which read a **single-valued**
`graph.value(prop, RDFS.domain)`. Because each projector resolved domains its own
way, the same ontology could be answered differently depending on the target.

### Decision

1. Introduce one shared resolver, `effective_domain_classes(graph, prop)`, that
   returns the union of: (a) direct `rdfs:domain` URIRef objects, (b) members of an
   `rdfs:domain [ owl:unionOf ( ... ) ]` blank node, and (c) `schema:domainIncludes`
   URIRefs. A companion `properties_with_domain(graph)` enumerates every property
   carrying any of these forms. `SCHEMA = Namespace("http://schema.org/")`.
2. Route the semantic index (the `validate-mapping` resolution path), dbt
   `bind.active_properties`, and the medallion dbt projector's datatype-property
   membership loops through this single helper. Repeated `rdfs:domain` is formally
   **treated as union** (not DL intersection) for projection/validation.
3. Scope is intentionally limited to **Silver + dbt + `validate-mapping`** — the
   acceptance-criteria minimum. a2ui / azure-search / neo4j / gold / prompt / MDM
   remain out of scope.

### Rationale

Computing domain membership in exactly one place removes the "answered differently
by accident" trap the issue calls out and makes the single-URIRef case
behaviour-preserving (no baseline churn). The helper lives in `core` and is imported
by `core` consumers only, respecting the one-way `core`↛`mdm` layering (MDM-DD-002).

### Consequences

- A datatype property with a union / `domainIncludes` domain is now recognised on
  **every** member class by the semantic index, so `validate-mapping` accepts a
  column mapped to it from any member class's table (no false
  `mapping.property-outside-target-class`).
- Silver columns remain **mapping-driven** (a property becomes a column only when a
  source column is mapped to it — DD-110 parity manifest), so the projector changes
  affect DDL/analyses/schema-facts and virtual-source (unmapped-table) inclusion,
  while the resolution/validation layer is where multi-class domains take effect.
- Object-property / FK union-domain resolution is **not** changed (datatype-only);
  extending it is a possible follow-up.
