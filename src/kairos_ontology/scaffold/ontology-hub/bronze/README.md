# Bronze Source System Descriptions

This directory contains **bronze-layer vocabulary files** — lightweight TTL
descriptions of source system schemas (tables, columns, data types).

These are NOT domain ontologies. They describe the physical structure of
source systems (AdminPulse, ERP, CRM, etc.) so the dbt projector can
generate staging models automatically.

## Naming convention

```
{system-name}.ttl        # e.g. adminpulse.ttl, erp-navision.ttl
```

## Required namespace

Use the `kairos-bronze:` vocabulary to describe source schemas:

```turtle
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
```

## Structure

Each file describes:

1. **SourceSystem** — the system itself (name, connection type, database)
2. **SourceTable** — each table/view to extract
3. **SourceColumn** — each column with its data type and nullability

## Example

```turtle
@prefix bronze-ap: <https://example.com/bronze/adminpulse#> .
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .

bronze-ap:AdminPulse a kairos-bronze:SourceSystem ;
    rdfs:label "AdminPulse" ;
    kairos-bronze:connectionType "jdbc" ;
    kairos-bronze:database "AdminPulse_Prod" ;
    kairos-bronze:schema "dbo" .

bronze-ap:tblClient a kairos-bronze:SourceTable ;
    rdfs:label "tblClient" ;
    kairos-bronze:sourceSystem bronze-ap:AdminPulse ;
    kairos-bronze:tableName "tblClient" ;
    kairos-bronze:primaryKeyColumns "ClientID" ;
    kairos-bronze:incrementalColumn "ModifiedDate" .

bronze-ap:tblClient_ClientID a kairos-bronze:SourceColumn ;
    kairos-bronze:sourceTable bronze-ap:tblClient ;
    kairos-bronze:columnName "ClientID" ;
    kairos-bronze:dataType "int" ;
    kairos-bronze:nullable "false"^^xsd:boolean ;
    kairos-bronze:isPrimaryKey "true"^^xsd:boolean .
```

## Workflow

1. Create a bronze TTL per source system in this directory
2. Create SKOS mappings in `../mappings/` to link bronze → silver
3. Run `python -m kairos_ontology project --target dbt` to generate dbt models
