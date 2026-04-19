# SKOS Mappings

This directory contains SKOS synonym and alignment mappings that link your
domain ontology terms to external vocabularies (e.g., Schema.org, FIBO).

## Usage

Mappings use `skos:exactMatch`, `skos:closeMatch`, or `skos:broadMatch` to
express relationships between your ontology concepts and external standards.

## Example mapping

```turtle
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix cust: <http://example.org/ontology/customer#> .
@prefix schema: <http://schema.org/> .

cust:Customer skos:exactMatch schema:Person .
cust:customerName skos:exactMatch schema:name .
cust:customerEmail skos:exactMatch schema:email .
```
