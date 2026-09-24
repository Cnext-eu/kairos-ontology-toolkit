# DD-241: Relationship cardinality is declared in OWL, and each diagram draws what its layer guarantees

**Status:** Accepted
**Date:** 2026-09-25
**Affects:** `core/projections/shared.py` (`er_edge`), `core/projections/erd_projector.py`
(`edge_multiplicities`, `declared_inverse`), `medallion_silver_projector.py`,
`contract_erd_projector.py`, `ddd_context_projector.py`, `dbt/gold_render.py`,
`dbt/specs.py` (`optional_field`), `dbt/silver_contract.py` (`canonical_data`),
`dbt/policy_specs.py`, `dbt/policy_normalize.py`, `dbt/shape.py`, `dbt/materialize.py`,
`compiler/adapter.py` (`ResolutionContext.relationship_bounds`), `compiler/kernel.py`, new
`core/cardinality_audit.py`, `core/validator.py`, `cli/compile.py`, `core/projector.py`, the
`kairos-design-domain` and `kairos-design-mapping` skills, the managed shapes README, a new
how-to
**Issue:** #999 (extends DD-209, DD-212 and DD-216)

### Context

All four ER renderers hard-coded the relationship token `||--o{`: the Silver domain ERD, the
master ERD, the contract ERD and the Gold ERD. So every relationship was drawn as "parent
exactly one, child zero or more", whatever the ontology or the binding said. An optional
foreign key was drawn as mandatory, and a one-to-one link could not be drawn. On one 15-domain
hub, all 272 edges read `||--o{`. The DDD context diagram drew only the target end of each
association.

Nothing said where relationship cardinality is declared. The domain skill listed "role
cardinality" as a SHACL governance constraint, while every projection reads OWL. The hub had
declared all 29 relationship bounds twice, once in OWL and once in SHACL, and nothing checked
that the two agreed.

There are two declarations, and they are not the same thing:
- the ontology says what the relationship *means*;
- the binding's `missingParent` and `cardinality` say how Silver *loads* it.

The v5 compiler is graph-free past `resolve_scope`. It built Silver foreign keys from the
binding, and dropped the authored `cardinality: one-to-one` altogether.

### Decision

**OWL is the one place relationship cardinality is declared.** That means `owl:FunctionalProperty`,
class restrictions (`owl:minCardinality`, `owl:maxCardinality`, `owl:cardinality`, and their
qualified forms) on the class holding the property or a subclass, and `owl:inverseOf` partners.
SHACL keeps data-quality rules and does not restate an object-property bound.

**One derivation.** `erd_projector.edge_multiplicities` computes both ends of an edge from OWL.
The class diagram, the DDD context diagram, the contract ERD and the compiler's cross-check all
call it, so none can read the ontology differently. The class diagram's output is byte-identical.

**Each diagram draws what its layer guarantees.** One helper, `er_edge`, renders every token,
so the domain and master ERDs produce the same string for the same edge.

| Output | Parent end (`\|\|` or `\|o`) | Child end (`o{` or `o\|`) |
|---|---|---|
| Class diagram, DDD diagram | OWL target bound | OWL source bound |
| Contract ERD | OWL: required → `\|\|`. A contract declares no relationship cardinality, and a relationship column can't be declared as a contract column (`contract.column-name-collision`) | OWL inverse bounded to one → `o\|` |
| Silver domain and master ERD | FK column NOT NULL (`missingParent: error`) → `\|\|` | binding `cardinality: one-to-one` → `o\|` |
| Gold ERD | fact key column NOT NULL → `\|\|` | the relationship's own cardinality |

An edge with no known bound is drawn `|o--o{`, the weakest claim and never a false one.

**The binding is checked against OWL, at compile.** `resolve_scope` precomputes the OWL bounds
of every relationship a binding in scope names, as `ResolutionContext.relationship_bounds`,
the same "computed where the graph is" pattern as `prefix_alternatives`. `_wire_relationships`
then warns:
- `relationship.optional-but-ontology-requires`: OWL requires the parent, but
  `missingParent: null`.
- `relationship.one-to-one-not-in-ontology`: the binding says one-to-one, but OWL does not bound
  the inverse to one.

These are warnings, because the binding may be right and the ontology stale.

**SHACL is checked against OWL, at validate.** `cardinality_audit` compares every hand-authored
`sh:minCount`/`sh:maxCount` on an object property (managed `kairos-*-shapes` excluded) with the
OWL bound on its `sh:targetClass`, and reports one of:
- `cardinality.shacl-duplicates-owl`
- `cardinality.shacl-contradicts-owl`
- `cardinality.shacl-only`

All three are warnings. Datatype-property counts are SHACL's job and are never reported.

**The authored one-to-one reaches Silver without churning every hub.** It is carried as
`relationship_cardinality` through the temporal-relationship fact and spec, `SilverForeignKeySpec`
and `SilverConstraintPhysicalPlan`. These specs are hashed into every model's
`DD-110-SILVER-SPEC-SHA256` and serialized into the constraints JSON that dataplatforms pin, so
the new fields use `optional_field()`. That field metadata makes `canonical_data` leave them out
while they hold their default. A hub that binds nothing one-to-one keeps byte-identical dbt
package output.

### Consequences

- **Diagram diffs on the next emit.** Every hub's `model/contracts/diagrams/*-erd.mmd` changes
  wherever a foreign key is nullable (`||` becomes `|o`). The contract ERD changes wherever OWL
  does not require the property. This is the bug fix, and the only generated change a hub without
  one-to-one bindings sees.
- **`_drop_resolved_externals`** matches any ER token (`ER_EDGE_PATTERN`) instead of the literal
  `||--o{`, which it had silently depended on.
- **Rejected: a cardinality field on contract relationships.** It would be a second source of
  truth for what OWL already declares.
- **Rejected: drawing the Silver ERD from OWL.** It would show a relationship as mandatory while
  the binding loads rows with no parent. The compile warning surfaces that disagreement instead
  of hiding it in a diagram.
- **Out of scope, noted:**
  - `shared._max_cardinality_classes` ignores an exact `owl:cardinality 1`. It is on the legacy
    graph path; v5 builds foreign-key facts from bindings.
  - `medallion_dbt_projector.py` turns SHACL `min 1 + max 1` into a dbt `unique` test. That is a
    legacy projector.
