### Fixed
- **ER diagrams draw relationship cardinality instead of `||--o{` everywhere (DD-241).**
  Every edge in the Silver, master, contract and Gold ERDs used to read "parent exactly one,
  child zero or more", so an optional foreign key looked mandatory and a one-to-one link could
  not be drawn. Each diagram now draws what its layer guarantees:
  - The Silver and master ERDs: `||` when the foreign key is NOT NULL (`missingParent: error`),
    `|o` when it is nullable, and `o|` on the child end for a `cardinality: one-to-one` binding.
  - The contract ERD: read from the ontology's OWL bounds.
  - The Gold ERD: from the fact's key column and the relationship's own cardinality.

  **Expect a diagram diff on the next `compile --all --emit`** wherever a foreign key is
  optional. The dbt package itself is byte-identical unless a binding says one-to-one.
- **The DDD context diagram draws both ends of an association**, not only the target end, from
  the same derivation as the class diagram.
- **A binding's `cardinality: one-to-one` now reaches Silver.** It was dropped before; it is
  recorded on the foreign-key constraint as `relationship_cardinality`.

### Added
- **`compile` warns when a binding contradicts the ontology.**
  - `relationship.optional-but-ontology-requires`: OWL requires the parent, but the binding
    says `missingParent: null`.
  - `relationship.one-to-one-not-in-ontology`: the binding says one-to-one, but OWL lets a
    parent have many children.
- **`validate` warns about SHACL counts on relationships.** A hand-authored `sh:minCount` or
  `sh:maxCount` on an object property is reported as one of:
  - `cardinality.shacl-duplicates-owl`: it restates the OWL bound;
  - `cardinality.shacl-contradicts-owl`: it disagrees with the OWL bound;
  - `cardinality.shacl-only`: no OWL bound exists, so no diagram and no compile check sees it.

  All are warnings. Datatype-property counts are not affected.
- **A new how-to, "Declare relationship cardinality"**
  (`docs/toolkit/how-to/declare-relationship-cardinality.md`). Relationship cardinality is
  declared in OWL only. The how-to has worked examples and a table of which output reads which
  declaration. The `kairos-design-domain` and `kairos-design-mapping` skills and the managed
  `model/shapes/README.md` now say the same.
