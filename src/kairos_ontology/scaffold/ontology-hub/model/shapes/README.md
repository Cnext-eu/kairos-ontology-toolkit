# SHACL Shapes

This directory contains SHACL validation constraint files for domain ontologies.

## Naming convention

Each shapes file mirrors its ontology file:
- `customer.ttl` → `customer.shacl.ttl`
- `order.ttl` → `order.shacl.ttl`

## Usage

Shapes are automatically picked up by the validator:

```bash
kairos-ontology validate --shacl
```

## What does not belong here: relationship cardinality

Declare how many of something a relationship allows in OWL, on the class that holds the
object property (`owl:FunctionalProperty`, or an `owl:Restriction` with
`owl:minCardinality` / `owl:maxCardinality`). The class diagrams, the contract ERD and
`compile` read OWL; none of them reads SHACL. A `sh:minCount` / `sh:maxCount` on an
object property is a second copy that can drift, and `validate` warns about it
(`cardinality.shacl-duplicates-owl`, `cardinality.shacl-contradicts-owl`,
`cardinality.shacl-only`). See `docs/toolkit/how-to/declare-relationship-cardinality.md`.

Counts on datatype properties, like the required name below, are what SHACL is for.

## Example shape

```turtle
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix : <http://example.org/ontology/customer#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

:CustomerShape a sh:NodeShape ;
    sh:targetClass :Customer ;
    sh:property [
        sh:path :customerName ;
        sh:minCount 1 ;
        sh:datatype xsd:string ;
    ] .
```
