# DD-138: Cross-domain Relationship Targets via External References

**Status:** Accepted
**Date:** 2026-07-28
**Affects:** V5 `EntityBinding` relationship declarations, compiler BuildScope resolution,
relationship diagnostics, provenance hashing, and generated dbt relationship tests
**Implementation:** Accepted. `RelationshipSpec` gains an external-reference field; the
compiler resolves the declared key contract. Physical cross-domain `ref()` emission is enabled
by the unified topology accepted in DD-140.

### Context

DD-133 §7 already allows a relationship target to be either another entity with a binding and
model in the current domain scope, or an explicitly declared external reference that the compiler
can treat as a resolvable parent without generating that parent. DD-133 §8 deliberately keeps
`compile <domain>` per-domain: the BuildScope includes bindings whose `metadata.domain` matches,
with stable ordering and one `by_target` binding per class. Earlier DD-019, DD-027, and DD-097
record historical demand for cross-domain foreign-key wiring, but they predate the v5 authoring
break and must not be treated as automatic v5 scope-widening requirements.

### Decision

Add an explicit external-reference declaration to a relationship target. The declaration names the
external parent and states its key contract: ordered key column name(s), canonical key type(s), and
optionally the expected package/model identifier once emit topology is decided. The compiler
resolves the relationship against that declared contract and does not generate a model for the
parent.

The contract is fail-closed:

- a missing target declaration remains a missing-target diagnostic;
- a relationship join column that cannot be mapped to an output column is a missing-key
  diagnostic;
- incompatible child and external key types are a type diagnostic;
- composite keys are ordered tuples, and cardinality, order, names, and types must all match;
- runtime names reserved for generated columns remain reserved for the child side of the join.

Resolution is deterministic. The compiler must not search peer-domain bindings or choose an
arbitrary binding from a class-local `by_target` map. The declared external-reference contract is
the authority, even when a peer hub happens to contain a binding for the same ontology class.

The naive alternative, resolving through a peer binding's key output, is rejected. It depends on
which peer bindings are loaded, on peer authoring order, and on `by_target` retaining only one
binding per class, so it can silently select the wrong physical parent. If maintainers ever choose
scope widening instead, that would be a separate decision coupled to the emit/dbt-package topology
in DD-140 because cross-domain `ref()` wiring is only reachable when the generated package layout
contains both domains in a deterministic project graph.

Provenance hashing should include the external-reference declaration because it affects the
compiled contract and generated tests. Peer inputs should not enter the BuildScope hash merely
because they exist elsewhere. They enter provenance only if a future accepted topology decision
explicitly widens scope to load peer bindings or package manifests as compiler inputs.

### Rationale

The explicit contract follows DD-133 §7 without weakening the per-domain BuildScope. It gives
relationship validation enough information to be deterministic and testable while keeping model
ownership clear: the child domain can assert how it references an external parent, but it does not
compile that parent.

### Consequences

- ISSUE-7 / Workstream C should implement the DD-133 external-reference route first.
- Tests should cover missing target, missing key, incompatible types, composite-key ordering, and
  deterministic behavior when peer bindings for the target class also exist.
- Generated docs and diagnostics must make clear that an external reference is a contract, not a
  discovered peer model.
- Cross-domain physical `ref()` generation remains blocked on DD-140 unless the external parent is
  made available by the selected dbt package topology.
