# Declare relationship cardinality

**Skill:** `kairos-design-domain` (the ontology), `kairos-design-mapping` (the binding).

How many of something a relationship allows is declared **once, in OWL**. SHACL is for
data-quality rules OWL cannot carry, and the binding is how Silver implements the relationship.
Every diagram reads one of those two declarations, and `validate` and `compile` warn when they
disagree (DD-241).

## The rule

| Declare | Where | Not in |
|---|---|---|
| Relationship cardinality: at most one, required, exactly one, one-to-one | OWL, on the class that holds the object property | SHACL `sh:minCount` / `sh:maxCount` on the object property |
| Data-quality rules: a required identifier literal, a closed code list, a pattern, a severity | SHACL, in `model/shapes/<domain>.shacl.ttl` | OWL |
| How Silver loads the relationship: whether a missing parent fails, one-to-one or many-to-one | The EntityBinding, `missingParent` and `cardinality` | the ontology |

The binding must agree with OWL. `compile` warns when it does not:

- `relationship.optional-but-ontology-requires`: OWL requires the parent, but the binding
  says `missingParent: null`.
- `relationship.one-to-one-not-in-ontology`: the binding says `one-to-one`, but OWL lets a
  parent have many children.

`validate` warns about a SHACL count on an object property:

- `cardinality.shacl-duplicates-owl`: it restates the OWL bound.
- `cardinality.shacl-contradicts-owl`: it disagrees with the OWL bound.
- `cardinality.shacl-only`: no OWL bound exists, so no diagram and no compile check sees it.

## Worked examples

```turtle
@prefix :     <https://example.org/ontology/shop#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

# At most one: an order ships to at most one address.
:shipsTo a owl:ObjectProperty, owl:FunctionalProperty ;
    rdfs:domain :Order ; rdfs:range :Address .

# Required: every order is placed by a customer.
:Order rdfs:subClassOf [
    a owl:Restriction ; owl:onProperty :placedBy ; owl:minCardinality 1 ] .

# Exactly one: every invoice has exactly one issuer.
:Invoice rdfs:subClassOf [
    a owl:Restriction ; owl:onProperty :issuedBy ; owl:cardinality 1 ] .

# One-to-one: a customer has one loyalty account, and an account belongs to one customer.
:hasLoyaltyAccount a owl:ObjectProperty ;
    rdfs:domain :Customer ; rdfs:range :LoyaltyAccount .
:accountHolder a owl:ObjectProperty, owl:FunctionalProperty ;
    owl:inverseOf :hasLoyaltyAccount .

# A bound for one subclass only: a key account always has an account manager.
:KeyAccount rdfs:subClassOf :Customer , [
    a owl:Restriction ; owl:onProperty :managedBy ; owl:minCardinality 1 ] .
```

The binding that implements the required relationship above:

```yaml
relationships:
  - property: shop:placedBy
    target: shop:Customer
    cardinality: many-to-one
    mode: non-temporal
    missingParent: error      # required in OWL, so a missing parent fails
    ambiguousParent: error
```

## Which output reads what

| Output | Reads | Parent end | Child end |
|---|---|---|---|
| Class diagram (`project --target erd`) | OWL | the restriction or functional property | the inverse's bound, or inverse-functional |
| DDD context diagram (`project --target ddd`) | OWL | same derivation as the class diagram | same derivation as the class diagram |
| Contract ERD (`compile --emit`, `project --target contract-erd`) | OWL, because a contract declares no relationship cardinality | `\|\|` when OWL requires the property, else `\|o` | `o\|` when OWL bounds the inverse to one, else `o{` |
| Silver domain and master ERD (`compile --emit`) | The binding, through Silver | `\|\|` when the foreign key is NOT NULL (`missingParent: error`), else `\|o` | `o\|` for `cardinality: one-to-one`, else `o{` |
| Gold ERD and Power BI relationships (`emit-gold`) | The Gold product | `\|\|` when the fact's key column is NOT NULL, else `\|o` | the relationship's own cardinality |
| dbt `not_null` test on the foreign key | The binding | `missingParent: error` | — |

When the class diagram and the Silver ERD draw the same relationship differently, the
binding and the ontology disagree, and `compile` has already warned about it.
