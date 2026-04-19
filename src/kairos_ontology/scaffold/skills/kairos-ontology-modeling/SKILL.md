---
name: kairos-ontology-modeling
description: >
  Expert knowledge for designing and modifying OWL/Turtle ontologies.
  Covers class hierarchies, property design, naming, and common patterns.
---

# Ontology Modeling Skill

You are an expert in OWL 2 ontology modeling using Turtle (TTL) syntax.

## Before you start

0. **Quick toolkit version check** — run `kairos-ontology update --check` once
   at the start of the session.  If it reports outdated files, run
   `kairos-ontology update` and commit the refresh before doing any other work.
   See the kairos-toolkit-update skill for full upgrade steps.
1. **Create a feature branch** — never work directly on `main`.  Use the
   SC-feature-branch skill (e.g., `ontology/add-order-domain`).
2. **Read the hub README** — open `ontology-hub/README.md` and note the company
   name, company domain, namespace base, and the domain model overview table.
   All new ontologies MUST use the namespace pattern documented there.
3. **Check the domain model overview** — before creating a new `.ttl` file,
   verify that a row for the intended domain exists in the overview table.
   If it doesn't, add the domain to the table first and get agreement from the
   user.  This avoids fragmented, overlapping ontology files.
4. **Check the master ontology** — after creating a new domain file, add an
   `owl:imports` line for it in `ontology-hub/ontologies/_master.ttl`.

## Class design

- Every class is declared as `owl:Class` with `rdfs:label` and `rdfs:comment`.
- Use inheritance (`rdfs:subClassOf`) for IS-A relationships.
- Prefer flat hierarchies (max 3 levels deep) for business ontologies.
- Abstract base classes are useful for shared properties (e.g., `AuditableEntity`).

## Property design

- **Datatype properties** (`owl:DatatypeProperty`): link a class to a literal value.
  Common ranges: `xsd:string`, `xsd:integer`, `xsd:decimal`, `xsd:boolean`, `xsd:dateTime`, `xsd:date`.
- **Object properties** (`owl:ObjectProperty`): link two classes.
  Always specify `rdfs:domain` and `rdfs:range`.
- Use `rdfs:label` for human-friendly names and `rdfs:comment` for descriptions.

## Naming conventions

- **Classes**: PascalCase — `Customer`, `SalesOrder`, `VIPCustomer`.
- **Properties**: camelCase — `customerName`, `orderDate`, `belongsToCustomer`.
- **Namespaces**: Use HTTPS URIs matching the hub's namespace base —
  `https://<company-domain>/ont/<domain>#` (e.g., `https://contoso.com/ont/customer#`).

## Common patterns

### Enumeration (fixed set of values)
```turtle
:OrderStatus a owl:Class ;
    rdfs:label "Order Status" ;
    rdfs:comment "Possible states of an order" .
:statusPending a :OrderStatus .
:statusConfirmed a :OrderStatus .
:statusShipped a :OrderStatus .
```

### Composition (HAS-A relationship)
```turtle
:hasLineItem a owl:ObjectProperty ;
    rdfs:domain :Order ;
    rdfs:range :LineItem ;
    rdfs:label "has line item" .
```

### Metadata properties
```turtle
:createdAt a owl:DatatypeProperty ;
    rdfs:domain :AuditableEntity ;
    rdfs:range xsd:dateTime ;
    rdfs:label "Created At" .
:modifiedAt a owl:DatatypeProperty ;
    rdfs:domain :AuditableEntity ;
    rdfs:range xsd:dateTime ;
    rdfs:label "Modified At" .
```

## Ontology declaration

Every .ttl file MUST start with an ontology declaration:
```turtle
@prefix : <https://contoso.com/ont/domain#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<https://contoso.com/ont/domain> a owl:Ontology ;
    rdfs:label "Domain Ontology"@en ;
    rdfs:comment "Description of this domain"@en ;
    owl:versionInfo "1.0.0" .
```

## Anti-patterns to avoid

- Do NOT create classes without labels or comments.
- Do NOT use `xsd:string` for everything — use appropriate types (`xsd:dateTime`, `xsd:integer`, etc.).
- Do NOT create circular subclass hierarchies.
- Do NOT mix domains in a single .ttl file — one domain per file.
- Do NOT use `http://` in namespace URIs — always use `https://`.
- Do NOT forget to add new domains to `_master.ttl` and the hub README table.
