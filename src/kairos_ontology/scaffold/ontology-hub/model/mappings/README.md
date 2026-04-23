# SKOS Mappings

This directory contains SKOS mapping files that link concepts across
vocabularies. Each mapping file can serve **both** purposes below — SKOS
predicates express the semantic relationship while `kairos-map:` annotations
add the technical detail needed for dbt code generation. This dual-purpose
design avoids redundancy: one file per source×domain is the single source
of truth for alignment **and** transformation.

## 1. External vocabulary alignment

Link your domain ontology terms to external standards (Schema.org, FIBO):

```turtle
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix cust: <http://example.org/ontology/customer#> .
@prefix schema: <http://schema.org/> .

cust:Customer skos:exactMatch schema:Person .
cust:customerName skos:exactMatch schema:name .
cust:customerEmail skos:exactMatch schema:email .
```

## 2. Bronze-to-Silver data mappings (for dbt projection)

Map source system columns to silver domain properties. Use SKOS match
properties to express semantic correspondence, and `kairos-map:` annotations
for technical transformation details:

```turtle
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
@prefix bronze-ap: <https://example.com/bronze/adminpulse#> .
@prefix party: <https://example.com/ont/party#> .

# Table-level: which source table feeds which silver entity
bronze-ap:tblClient skos:exactMatch party:Client ;
    kairos-map:mappingType "direct" .

# Column-level: 1:1 with type cast
bronze-ap:tblClient_ClientID skos:exactMatch party:clientId ;
    kairos-map:transform "CAST(source.ClientID AS STRING)" .

# Column-level: needs cleaning
bronze-ap:tblClient_Name skos:closeMatch party:clientName ;
    kairos-map:transform "TRIM(source.Name)" .

# Computed column: derived from multiple source columns
bronze-ap:tblClient_FullAddress skos:narrowMatch party:addressLine1 ;
    kairos-map:transform "CONCAT(source.Street, ' ', source.Nr, ', ', source.City)" ;
    kairos-map:sourceColumns "Street Nr City" .

# With default value for NULLs
bronze-ap:tblClient_Country skos:exactMatch party:country ;
    kairos-map:transform "COALESCE(source.Country, 'BE')" ;
    kairos-map:defaultValue "BE" .
```

### Folder structure

Organise mapping files by source system:

```
model/mappings/
├── adminpulse/
│   ├── adminpulse-to-party.ttl
│   └── adminpulse-to-client.ttl
├── erp-navision/
│   └── erp-navision-to-order.ttl
└── README.md
```

### Naming convention for bronze-to-silver mappings

```
{source-system}/{source-system}-to-{domain}.ttl
```

Examples: `adminpulse/adminpulse-to-party.ttl`, `erp-navision/erp-navision-to-client.ttl`

### SKOS property semantics

| SKOS Property | Meaning |
|---------------|---------|
| `skos:exactMatch` | 1:1 mapping, same semantics |
| `skos:closeMatch` | 1:1 but needs transformation |
| `skos:narrowMatch` | Source is more specific → maps to broader silver concept |
| `skos:broadMatch` | Source is broader → filter/split to silver concept |
| `skos:relatedMatch` | Indirect — needs business logic / lookup |
