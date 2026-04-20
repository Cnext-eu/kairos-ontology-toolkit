---
name: kairos-ontology-validation
description: >
  Expertise for validating RDF/OWL ontologies using syntax checks and SHACL shapes.
  Covers common errors, SHACL shape patterns, and remediation steps.
---

# Ontology Validation Skill

You help users validate ontologies and fix issues.

## Validation levels

1. **Syntax validation** — Can the .ttl file be parsed as valid Turtle/RDF?
   - Common errors: missing semicolons, unclosed URIs, invalid prefixes, encoding issues.
2. **SHACL validation** — Does the ontology conform to shape constraints?
   - Requires a .shacl.ttl file in `shapes/`.
   - Checks cardinality, value types, required properties.

## Common syntax errors and fixes

| Error | Cause | Fix |
|-------|-------|-----|
| "Bad syntax (expected directive)" | Missing `@prefix` or `@base` | Add missing prefix declaration |
| "Unresolved prefix" | Using prefix not declared | Add `@prefix ex: <...> .` |
| "Unexpected end of file" | Missing final `.` | Add period after last triple |
| "Invalid IRI" | Spaces or special chars in URI | URL-encode or fix the namespace |

## SHACL shape patterns

### Required property
```turtle
:CustomerShape a sh:NodeShape ;
    sh:targetClass :Customer ;
    sh:property [
        sh:path :customerName ;
        sh:minCount 1 ;
        sh:datatype xsd:string ;
    ] .
```

### String length constraint
```turtle
sh:property [
    sh:path :customerEmail ;
    sh:minLength 5 ;
    sh:maxLength 254 ;
    sh:pattern "^[^@]+@[^@]+\\.[^@]+$" ;
] .
```

### Relationship cardinality
```turtle
sh:property [
    sh:path :hasOrder ;
    sh:class :Order ;
    sh:minCount 0 ;
] .
```

## Remediation workflow

1. Run `python -m kairos_ontology validate` on the hub.
2. If syntax fails: fix Turtle syntax errors first.
3. If SHACL fails: review each violation and either fix the data or update the shape.
4. Re-validate until both pass.
5. Only then generate projections: `python -m kairos_ontology project`.
