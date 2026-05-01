---
name: kairos-ontology-modeling
description: >
  Expert knowledge for designing and modifying OWL/Turtle ontologies.
  Covers class hierarchies, property design, naming, and common patterns.
---

# Ontology Modeling Skill

You are an expert in OWL 2 ontology modeling using Turtle (TTL) syntax.

## Before you start

0. **Quick toolkit version check** — run `python -m kairos_ontology update --check` once
   at the start of the session.  If it reports outdated files, run
   `python -m kairos_ontology update` and commit the refresh before doing any other work.
   See the kairos-ontology-toolkit-ops skill for full upgrade steps.
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
   `owl:imports` line for it in `ontology-hub/model/ontologies/_master.ttl`.
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
- Do NOT put projection annotations directly in the domain ontology `.ttl` —
  use separate extension files (see below).

---

## Extension annotations reference

The Kairos toolkit uses two custom annotation vocabularies that **drive code
generation** for the silver, gold, and dbt projections.  These annotations live
in **extension files** (`model/extensions/<domain>-silver-ext.ttl`,
`<domain>-gold-ext.ttl`) and **mapping files** (`model/mappings/<source>-to-<domain>.ttl`),
**never** inside the core domain `.ttl` files.

When modeling a domain, you MUST be aware of these annotations because they
determine how your ontology translates into DDL, dbt models, and Power BI
artifacts.  If an annotation is missing, the projector falls back to defaults —
which may not match the intended behavior.

### File layout

```
model/
  ontologies/
    client.ttl              ← pure domain model (no kairos-ext: annotations)
  extensions/
    client-silver-ext.ttl   ← silver layer projection annotations
    client-gold-ext.ttl     ← gold layer projection annotations
  mappings/
    adminpulse-to-client.ttl ← source-to-domain SKOS mappings + kairos-map: annotations
```

### `kairos-ext:` — Silver annotations (on ontology or class or property)

These go in `<domain>-silver-ext.ttl`.

#### Ontology-level (applied to the `owl:Ontology` resource)

| Annotation | Type | Default | Purpose |
|---|---|---|---|
| `silverSchema` | string | `silver_<domain>` | Warehouse schema name for silver tables |
| `namingConvention` | string | `camel-to-snake` | How OWL names become SQL names |
| `includeNaturalKeyColumn` | boolean | `true` | Include NK columns alongside SK |
| `auditEnvelope` | boolean | `true` | Add `_loaded_at`, `_source_file` audit columns |
| `inlineRefThreshold` | integer | `5` | Max enum members before creating a separate ref table |

#### Class-level (applied to an `owl:Class`)

| Annotation | Type | Default | Purpose |
|---|---|---|---|
| `silverTableName` | string | auto (snake_case of class name) | Override the generated table name |
| `scdType` | `"1"` or `"2"` | `"1"` | Slowly Changing Dimension type |
| `isReferenceData` | boolean | `false` | Mark as reference/enum table |
| `gdprSatelliteOf` | URI | — | Link a GDPR satellite to its parent class |
| `discriminatorColumn` | string | — | Column used for class-per-table inheritance splits |
| `partitionBy` | string | — | Fabric Warehouse partition column |
| `clusterBy` | string | — | Fabric Warehouse cluster column |
| `naturalKey` | string | — | Space-separated property names forming the natural key |
| `junctionTableName` | string | — | Physical M:N junction table name |
| `conditionalOnType` | string | — | Discriminator value that selects this subclass |

#### Property-level (applied to `owl:DatatypeProperty` or `owl:ObjectProperty`)

| Annotation | Type | Default | Purpose |
|---|---|---|---|
| `silverColumnName` | string | auto (snake_case) | Override column name in DDL/dbt |
| `silverDataType` | string | auto from `xsd:` range | Override SQL data type |
| `nullable` | boolean | `true` | Whether column allows NULL |
| `derivationFormula` | string | — | SQL expression for a computed column |
| `populationRequirement` | `"required"` / `"optional"` | `"optional"` | Maps to NOT NULL constraint |

### `kairos-ext:` — Gold annotations (on ontology or class or property)

These go in `<domain>-gold-ext.ttl`.

#### Ontology-level

| Annotation | Type | Default | Purpose |
|---|---|---|---|
| `goldSchema` | string | `gold_<domain>` | Warehouse schema for gold tables |
| `goldInheritanceStrategy` | `"class-per-table"` / `"single-table"` | `"single-table"` | How subclasses map to gold tables |
| `generateDateDimension` | boolean | `true` | Auto-generate `dim_date` |
| `generateTimeIntelligence` | boolean | `false` | Add DAX time-intelligence measures |

#### Class-level

| Annotation | Type | Default | Purpose |
|---|---|---|---|
| `goldTableType` | `"dimension"` / `"fact"` / `"bridge"` | auto-detected | Force table type |
| `goldTableName` | string | auto (`dim_` / `fact_` prefix) | Override gold table name |
| `goldExclude` | boolean | `false` | Exclude class from gold layer |
| `perspective` | string | — | Power BI perspective membership |
| `incrementalColumn` | string | — | Column for incremental materialization |

#### Property-level

| Annotation | Type | Default | Purpose |
|---|---|---|---|
| `goldColumnName` | string | auto | Override column name in gold |
| `goldDataType` | string | auto | Override SQL type in gold |
| `measureExpression` | string | — | DAX measure formula |
| `measureFormatString` | string | — | DAX format string for measure |
| `hierarchyName` | string | — | Power BI hierarchy group name |
| `hierarchyLevel` | integer | — | Position in hierarchy |
| `degenerateDimension` | boolean | `false` | Embed as degenerate dim in fact table |
| `olsRestricted` | boolean | `false` | Mark for Object-Level Security |
| `rolePlayingAs` | string | — | Role-playing dimension alias |

### `kairos-map:` — Mapping annotations (in mapping files)

These go in `model/mappings/<source>-to-<domain>.ttl` alongside SKOS mappings.

#### Table-level (on `skos:narrowMatch` or `skos:exactMatch` between source table and domain class)

| Annotation | Type | Purpose |
|---|---|---|
| `mappingType` | `"direct"` / `"split"` / `"merge"` | How source table(s) map to domain class |
| `filterCondition` | string | SQL WHERE clause for split patterns (e.g., `"source.type = 0"`) |
| `deduplicationKey` | string | Column(s) for dedup in merge patterns |
| `deduplicationOrder` | string | ORDER BY expression for dedup |

#### Column-level (on `skos:exactMatch` between source column and domain property)

| Annotation | Type | Purpose |
|---|---|---|
| `transform` | string | SQL expression (e.g., `"CAST(source.id AS STRING)"`) |
| `sourceColumns` | string | Space-separated source columns for composite mappings |
| `defaultValue` | string | Fallback value → generates `COALESCE(expr, default)` |

### Design rules for extensions

1. **Separate concerns**: domain ontology defines the *what* (classes, properties,
   relationships); extension files define the *how* (projection behavior).
2. **One extension file per layer per domain**: `client-silver-ext.ttl`,
   `client-gold-ext.ttl`.  Never mix silver and gold annotations in one file.
3. **Re-import the domain namespace**: extension files must `@prefix` and reference
   the same domain namespace as the ontology they extend.
4. **Annotate the ontology URI for ontology-level settings**: e.g.,
   ```turtle
   <https://acme.example/ontology/client> kairos-ext:silverSchema "silver_client" .
   ```
5. **Annotate class or property URIs for entity-level settings**: e.g.,
   ```turtle
   client:Client kairos-ext:scdType "2" ;
       kairos-ext:partitionBy "country" .
   ```
6. **Validate after editing**: run `kairos-ontology validate` to ensure the
   extension file parses correctly.
7. **Test the projection**: run `kairos-ontology project --target silver` (or `dbt`,
   `gold`) and inspect the generated output to verify annotations took effect.
