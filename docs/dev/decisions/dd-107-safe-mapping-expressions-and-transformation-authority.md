# DD-107: Safe Mapping Expressions and Transformation Authority

**Status:** Accepted
**Date:** 2026-07-25
**Affects:** `kairos-map`, mapping validation/rendering, contracted dbt transformations,
transformation readiness and skills
**Implementation:** `dbt/mapping_{specs,bind,normalize,renderers}.py` provides the
immutable v2 AST, graph-only binding, fail-closed semantic validation, approved macro
registry, Fabric/Databricks rendering, prep symbol binding, capability/release evidence,
and approved-contract transformation routing. `kairos-map` v2 and its SHACL shapes remove
the former raw-SQL terms; source-technical dedupe moved to `kairos-prep:TechnicalDedupe`.

### Context

Normal mappings currently accept free-form SQL transforms and filters. This can hide
adapter-specific behavior, unsafe quoting, nondeterminism, joins, subqueries, row loss,
or grain changes inside a surface intended for column alignment.

### Decision

Normal mapping expressions are typed, deterministic, column-bounded expressions or
approved namespaced macros. Validators resolve every identifier, literal, output type,
null behavior, and adapter capability. Literal values are rendered safely.

Mappings must reject arbitrary SQL, comments or statement separators, subqueries, joins,
windows, aggregation, nondeterministic functions, and undeclared row/grain changes.
Technical cleanup belongs in prep. Relational, grain-forming, complex fallback,
deduplication, and contribution-building logic belongs in DD-092 contracted dbt.

Contracted transformation authoring is iterative: profile evidence, define and approve
grain/identity/output contract, implement against representative fixtures or a working
flow, execute tests, then synchronize and map the proven virtual source. The approved
contract remains acceptance authority; working SQL alone does not establish semantics.

### Rationale

A constrained expression surface is portable and statically reviewable. dbt remains the
right execution language for relational logic without turning RDF annotations into a
second workflow engine.

### Consequences

- Replace free-form mapping SQL with a typed grammar; no compatibility parser is added.
- Amend DD-092, DD-093, and DD-105 to require the iterative evidence/execution order.
- Mapping/Silver readiness blocks unsafe expressions and unresolved transformation
  candidates.
