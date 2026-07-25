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

Fresh hubs include toolkit policy shapes:

- `kairos-prep-shapes.shacl.ttl` validates mandatory source preparation.
- `kairos-ext-shapes.shacl.ttl` validates Silver/Gold medallion policy.
- `kairos-map-shapes.shacl.ttl` validates named typed scalar mapping contracts.

Keep these files enabled: missing policy is intentionally fail-closed.

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
