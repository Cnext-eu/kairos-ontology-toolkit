# SKOS Mapping Contracts

This directory contains source-to-domain alignments. SKOS states semantic
correspondence; named `kairos-map` v2 resources state the validated technical
contract. Normal mappings never contain SQL strings.

## Authoring rule

Use the **kairos-design-mapping** skill. Do not hand-edit mapping TTL outside that
workflow: it validates source ownership, types, null behavior, determinism, adapter
support, and transformation routing.

```turtle
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
@prefix map: <https://example.com/mapping/adminpulse-to-party#> .
@prefix bronze: <https://example.com/bronze/adminpulse#> .
@prefix party: <https://example.com/ontology/party#> .

bronze:tblClient skos:exactMatch party:Client .
map:client-table a kairos-map:TableMapping ;
    kairos-map:sourceTable bronze:tblClient ;
    kairos-map:targetClass party:Client ;
    kairos-map:mappingType "direct" ;
    kairos-map:matchType "exactMatch" .

bronze:tblClient_Name skos:exactMatch party:clientName .
map:client-name a kairos-map:ColumnMapping ;
    kairos-map:sourceColumn bronze:tblClient_Name ;
    kairos-map:targetProperty party:clientName ;
    kairos-map:matchType "exactMatch" .
```

Omitting `kairos-map:expression` derives a direct typed source-column reference.

## Typed scalar expressions

Non-trivial scalar logic uses named AST nodes and ordered RDF lists:

```turtle
bronze:tblClient_Email skos:exactMatch party:email .
map:client-email a kairos-map:ColumnMapping ;
    kairos-map:sourceColumn bronze:tblClient_Email ;
    kairos-map:targetProperty party:email ;
    kairos-map:matchType "exactMatch" ;
    kairos-map:expression map:email-fallback .

map:email-fallback a kairos-map:FunctionExpression ;
    kairos-map:function "coalesce" ;
    kairos-map:arguments ( map:email-input map:email-default ) ;
    kairos-map:outputType "string" ;
    kairos-map:nullable false ;
    kairos-map:nullPolicy "first-non-null" ;
    kairos-map:determinism "deterministic" ;
    kairos-map:requiresCapability "null-handling" .

map:email-input a kairos-map:SourceColumnExpression ;
    kairos-map:sourceColumn bronze:tblClient_Email ;
    kairos-map:outputType "string" ;
    kairos-map:nullable true ;
    kairos-map:nullPolicy "propagate" ;
    kairos-map:determinism "deterministic" ;
    kairos-map:requiresCapability "source-column" .

map:email-default a kairos-map:LiteralExpression ;
    kairos-map:literalValue "unknown@example.invalid" ;
    kairos-map:outputType "string" ;
    kairos-map:nullable false ;
    kairos-map:nullPolicy "never-null" ;
    kairos-map:determinism "deterministic" ;
    kairos-map:requiresCapability "typed-literal" .
```

Every expression node declares output type, nullability/null policy, deterministic
behavior, and one adapter capability. Source references are column IRIs, never
identifier strings.

Synchronized dbt virtual sources mint new columns with the Turtle-prefixable
`table__column` local-name convention. Legacy `#table/column` full IRIs remain valid;
use `migrate-column-iris` to preview and explicitly migrate them rather than editing
mapping references by hand.

Allowed operations are deterministic scalar operators/functions, CASE, COALESCE,
typed NULL/literals, and the approved `https://kairos.cnext.eu/mapping/macro#`
macros.

## Routing boundary

- Rename, trim, type parsing/cast, sentinel normalization, scalar JSON extraction,
  CDC normalization, and source-technical deduplication belong in
  `integration/preparation/` through **kairos-design-source**.
- Joins, windows, ranking, aggregation, cross-relation fallback, JSON expansion,
  merge, and grain changes require **kairos-develop-dbt-transformation**.
- Map a contracted transformation only through its synchronized virtual source
  after approval, evidence, tests, adapter support, and replacement readiness pass.

## Layout

```text
model/mappings/
├── adminpulse/
│   ├── adminpulse-to-party.ttl
│   └── adminpulse-to-client.ttl
└── erp-navision/
    └── erp-navision-to-order.ttl
```

Use `{source-system}/{source-system}-to-{domain}.ttl`.
