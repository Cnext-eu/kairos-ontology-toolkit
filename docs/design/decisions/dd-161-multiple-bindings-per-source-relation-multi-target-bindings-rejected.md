# DD-161: Multiple bindings per source relation; multi-target bindings rejected

**Status:** Accepted
**Date:** 2026-08-15
**Affects:** DD-133 EntityBinding authoring guidance, kairos-design-mapping skill
**Implementation:** `.github/skills/kairos-design-mapping/SKILL.md` section 6a (+ scaffold copy);
no code change — the capability already exists

### Context

#489 reported that "one source table can only map to one canonical domain", concluding that
columns outside the chosen domain are silently lost, and proposed multi-target bindings.

The premise is false. Nothing constrains a source relation to one binding:
`entity-binding.schema.json` places no uniqueness constraint on `source.relation`, and
`quality.py`'s `safety.artifact-collision` keys on binding **name** and artifact **path** only.
`compile <domain>` selects bindings by `metadata.domain`, so two bindings over one relation in
two domains are in different compile scopes and cannot collide. The real gap was that nothing
told the author this — not the schema, not the skill, not any diagnostic.

### Decision

Multi-domain source coverage is expressed as **multiple bindings over one source relation**, one
per canonical entity, each with its own grain, identity, load policy and quality. This is
documented with a worked example (`Qargo.orders` to booking at order grain, to party at customer
grain) in kairos-design-mapping section 6a, including the two constraints that make it safe:
differing grain per target, and the fact that two bindings for the same class in the *same* domain
require a `conformance:` block or fail `conformance.group-required`.

**Multi-target bindings are rejected.** Because each target needs its own grain/identity/load, a
multi-target document would have to nest N complete binding bodies — identical in content to N
documents, while breaking the DD-133 section 3 invariant ("One binding document authors **one**
canonical entity from **one** source relation", restated normatively at section 3d) and requiring
changes to `target.class` (string to array), four `by_target` maps in `kernel.py`/`quality.py`,
conformance regrouping, and per-target artifact paths and provenance. Large blast radius, no new
capability.

Requiring a dbt split model instead is also rejected as the default: that is for genuine
relational logic (aggregation, joins, grain change), not for separating entities that are already
separable by grain.

### Consequences

- #489 closes as a documentation gap, not a schema limitation.
- `audit-column-coverage` names bound tables whose affinity assigned them a domain nothing binds
  them to (DD-160), so the missing second binding is prompted rather than discovered late.
- This decision exists so the multi-target proposal is not re-raised without new evidence.
