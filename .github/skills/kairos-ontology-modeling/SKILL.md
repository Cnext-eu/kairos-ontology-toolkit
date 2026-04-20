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
5. **Check for standard model alignment** — if the user mentions basing the
   domain on an industry standard (e.g. FIBO, DCSA, GS1, PROV-O, schema.org),
   follow the steps in the [Standard model alignment](#standard-model-alignment)
   section below before designing any classes or properties.

---

## Standard model alignment

When a user wants to model a domain based on — or aligned with — an industry
standard ontology (FIBO, DCSA, GS1, PROV-O, schema.org, etc.):

### Step 1 — Confirm which standard

Ask the user to confirm:
- The exact standard or vocabulary (name + version/edition if relevant).
- Whether they want **full alignment** (extend standard classes directly) or
  **loose alignment** (model independently, use `owl:equivalentClass` /
  `rdfs:seeAlso` mappings).

### Step 2 — Check ontology-reference-models/

Look inside `ontology-reference-models/` for the standard:

```bash
ls ontology-reference-models/
```

- If a folder or catalog entry for the standard **exists** → use it as the
  alignment target.  Import it via the catalog in your domain TTL:
  ```turtle
  owl:imports <catalog-uri-for-the-standard> ;
  ```
- If the standard is **not present**, do NOT download or inline it manually.
  Instead, inform the user:

  > "The `<standard>` reference model is not yet in `ontology-reference-models/`.
  > If you plan to reuse this standard across multiple projects, the recommended
  > approach is to add it to the reference models repo first
  > (`Cnext-eu/kairos-ontology-referencemodels`) so it becomes available to all
  > hubs via `update-referencemodels.ps1`.  Alternatively, for a one-off
  > alignment you can reference the public URI directly without importing the
  > full model."

  Then ask: **"Should we add it to the reference models first, or proceed with
  a direct URI reference for now?"**

### Step 3 — Alignment patterns

#### Extend a standard class (full alignment)

```turtle
@prefix fibo-be: <https://spec.edmcouncil.org/fibo/ontology/BE/LegalEntities/LegalPersons/> .

:LegalEntity rdfs:subClassOf fibo-be:LegalEntity ;
    rdfs:label "Legal Entity"@en ;
    rdfs:comment "A legal entity as defined in FIBO, specialised for this domain."@en .
```

#### Map to a standard class (loose alignment)

```turtle
:Customer a owl:Class ;
    rdfs:label "Customer"@en ;
    rdfs:comment "A party that purchases goods or services."@en ;
    owl:equivalentClass schema:Person ;    # or rdfs:seeAlso
    rdfs:seeAlso <https://spec.edmcouncil.org/fibo/...> .
```

#### Reuse a standard property by reference

```turtle
:carrierSCAC a owl:DatatypeProperty ;
    rdfs:domain :Carrier ;
    rdfs:range xsd:string ;
    rdfs:label "Carrier SCAC"@en ;
    rdfs:comment "Standard Carrier Alpha Code as defined by DCSA."@en ;
    rdfs:seeAlso <https://dcsa.org/standards/> .
```

### Known standards and their reference model status

| Standard | Domain | In reference models? | Notes |
|----------|--------|---------------------|-------|
| FIBO | Financial / legal entities | Check folder | Large; import selectively |
| DCSA | Shipping / container logistics | Check folder | eBL, Track & Trace |
| GS1 | Supply chain / product IDs | Check folder | GLN, GTIN, EPCIS |
| PROV-O | Data provenance | Check folder | W3C standard |
| schema.org | General-purpose web semantics | Check folder | Broad vocabulary |
| Dublin Core (DC) | Metadata | Usually included | Small; safe to import |

> **Rule:** Never hardcode a downloaded copy of a standard model inside the hub
> repo.  Always reference it via the catalog or a public URI.

---

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
