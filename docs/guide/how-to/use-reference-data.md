# Use reference data and code lists

**Skills:** `kairos-design-mapping`, `kairos-develop-dbt-transformation`

A code list (transport modes, countries, container types) reaches Silver like any other
entity, through a binding. What differs between lists is **where the rows come from**.
Decide that first; everything else follows from it ([DD-257](https://github.com/Cnext-eu/kairos-ontology-toolkit/blob/main/docs/dev/decisions/dd-257-a-reference-list-is-shipped-loaded-by-the-hub-or-owned-by-a-source-and-its-extensions.md)).

## 1. Decide the kind

| Kind | Rows come from | Examples | You author |
|---|---|---|---|
| **1. Shipped list** | the reference models, as individuals of the list class | UNECE Rec 19/20/21, Incoterms, currencies, ISO 3166 countries and subdivisions | a seed copied from the shipped members, a contracted model, a binding |
| **2. Hub-loaded standard** | the standard's own release, or your licensed copy | UN/LOCODE locations (too large to ship), ISO 6346 container size/type codes (licence) | a source import and a binding |
| **3. Source-owned list** | your own source systems | a TMS container-type master, internal status codes | a binding to the source table |

The reference models' module READMEs list every shipped list with its code count (for
UN/CEFACT: `authoritative-ontologies/UNCEFACT/README.md`, "Contents"), and say which lists
are deliberately not shipped. In the graph:
- **Kind 1:** the list class carries `kairos-ext:isReferenceData true` and has members.
- **Kind 2:** the class carries `isReferenceData true`, has no members, and its
  `dcterms:source` says where to load from.
- **Kind 3:** a list the reference models do not mention, or ship only as an empty governed
  class (such as `PartyRoleCode`), unless you adopt a standard for it.

The export script in step 2 writes only the header row for a list with no members.

Nothing appears in Silver until you bind it. A list you never bind, such as Rec 20's 1,828
units, costs nothing.

## 2. Kind 1: bind a shipped list

Take the shared list into your governed class. The subclass runs from the standard's list
to your class, so your class can hold extensions without making them members of the
standard:

```turtle
ref:TransportModeCode a owl:Class .
unece:TransportModeCodeList rdfs:subClassOf ref:TransportModeCode .
```

Copy the members into a seed. Until the toolkit generates it (#1126), export them from the
resolved closure. Don't copy them out of the `.ttl` by hand: reading serialised RDF as text
is what DD-103 rules out, and the closure is what your hub actually imports.

```python
# export_list.py <ontology.ttl> <catalog-v001.xml> <list class IRI> <out.csv>
import csv
import sys
from pathlib import Path

from rdflib import URIRef

from kairos_ontology import load_ontology

ontology, catalog, list_iri, out = sys.argv[1:5]
graph = load_ontology(Path(ontology), catalog_path=Path(catalog)).graph
rows = graph.query(
    "SELECT ?code ?name ?iri WHERE { ?iri a ?list ; rdf:value ?code . "
    "OPTIONAL { ?iri rdfs:label ?name } } ORDER BY ?code",
    initBindings={"list": URIRef(list_iri)},
)
with open(out, "w", newline="", encoding="utf-8") as handle:
    writer = csv.writer(handle)
    writer.writerow(["code", "name", "iri"])
    writer.writerows([str(code), str(name or ""), str(iri)] for code, name, iri in rows)
```

Run it on your reference-data domain ontology with the hub's catalog. Record the snapshot
(`owl:versionInfo`) and `dcterms:source` in the seed docs, and re-run it after each
reference-models upgrade so the change shows up as a diff in the hub PR:

```text
# integration/transforms/dbt/seeds/transport_mode_code.csv
code,name,iri
1,Maritime transport,https://vocabulary.uncefact.org/TransportModeCodeList#1
3,Road transport,https://vocabulary.uncefact.org/TransportModeCodeList#3
4,Air transport,https://vocabulary.uncefact.org/TransportModeCodeList#4
```

Read it from a contracted model
([Write a contracted dbt model](write-a-contracted-dbt-model.md)) and bind the model.
**Key on the code, not the IRI.** The IRI scheme is changing upstream, and source data
carries codes:

```yaml
apiVersion: kairos.eu/v5
kind: EntityBinding
metadata:
  name: reference-data-transport-mode-code
  domain: reference-data
source:
  dbtModel:
    name: int_reference__transport_mode_code
    sqlPath: integration/transforms/dbt/models/intermediate/reference-data/int_reference__transport_mode_code.sql
    contractPath: integration/transforms/dbt/models/intermediate/reference-data/int_reference__transport_mode_code.yml
target:
  class: https://example.com/ont/reference-data#TransportModeCode
grain:
  columns: [code]
identity:
  strategy: source-natural
  sourceKey: [code]
load:
  mode: full-refresh
fields:
  - {property: https://example.com/ont/reference-data#code, expression: code}
  - {property: https://example.com/ont/reference-data#name, expression: name}
  - {property: https://example.com/ont/reference-data#upstreamIri, expression: iri}
relationships: []
quality:
  - {kind: not-null, columns: [code, name]}
  - {kind: unique, columns: [code]}
```

The Silver model takes its name from the class (`transportmodecode`).
`isReferenceData` does not add a `ref_` prefix in v5.

## 3. Add local extensions

Extensions live where the rest of the list's rows live.

### Extra rows

Example: a country your sources use that ISO 3166-1 does not list yet, such as Kosovo,
which the European Commission and others code `XK`.

1. **Take the code from the user-assigned range.** ISO 3166-1 reserves AA, QM–QZ, XA–XZ
   and ZZ for local use, so a later ISO release can never give your code to another
   country.
2. **Declare the member (kind 1 only).** In your hub ontology, make it an individual of
   *your* governed class, never of the standard's list:

   ```turtle
   ref:country-XK a owl:NamedIndividual, ref:Country ;
       rdf:value "XK" ;
       rdfs:label "Kosovo" ;
       rdfs:comment "User-assigned ISO 3166-1 code, pending an official assignment."@en .
   ```

3. **Add the row to an extension seed** next to the shipped one:

   ```text
   # integration/transforms/dbt/seeds/country_code_local.csv
   code,name
   XK,Kosovo
   ```

4. **Union the two in the contracted model** and say where each row came from:

   ```sql
   select code, name, 'iso' as origin from {{ ref('country_code') }}
   union all
   select code, name, 'hub' as origin from {{ ref('country_code_local') }}
   ```

The binding's `unique` rule on `code` fails if a later snapshot ships a code you already
added locally. That failure is what you want: decide then whether to retire the local row.

**Rules:**
- **Never override a shipped row.** An extension only adds rows; it never renames or
  redefines a shipped one.
- **Deprecate a retired extension; don't delete it.** Facts already point at it.

For a kind 2 list, steps 1, 3 and 4 apply. Skip step 2, because the rows are not
individuals. For a kind 3 list, add the code in the source system's list itself.

### Extra columns

When you need an attribute the standard does not carry, such as a TEU factor per
container type, keep it in a sibling seed keyed on the code. Join it in the contracted
model. Refreshing the shipped rows then never wipes it.

```text
# integration/transforms/dbt/seeds/container_type_teu.csv
code,teu_factor
22G1,1
42G1,2
45G1,2.25
```

## 4. Map source codes to the list (crosswalks)

Source systems use their own codes (`SEA`, `AIR`). Map them to the list's codes with a
hub seed per source and list:

```text
# integration/transforms/dbt/seeds/tms_transport_mode_rec19_map.csv
source_mode_code,rec19_code
SEA,1
ROA,3
AIR,4
```

Name the codes you leave unmapped on purpose in the seed's column docs, for example
"COU (courier) and blank are not mapped, so their link stays empty".

In the contracted model for the record that carries the code, **left-join** the
crosswalk, and keep the raw value:

```sql
select
    leg.leg_transport_mode_code,                  -- raw source value, kept
    tm.rec19_code as transport_mode_rec19_code    -- governed code, or null
from {{ ref('stg_tms__transport_leg') }} as leg
left join {{ ref('tms_transport_mode_rec19_map') }} as tm
    on tm.source_mode_code = upper(trim(leg.leg_transport_mode_code))
```

In the binding, map the raw value to a property, and link the governed code through a
relationship that tolerates a missing parent:

```yaml
fields:
  - {property: https://example.com/ont/consignment#legTransportModeCode, expression: leg_transport_mode_code}
technicalFields:
  - {name: transport_mode_rec19_code, expression: transport_mode_rec19_code, type: string, nullable: true, purpose: relationship}
relationships:
  - property: https://example.com/ont/consignment#hasTransportModeCode
    target: https://example.com/ont/reference-data#TransportModeCode
    externalReference:
      name: transportmodecode
      domain: reference-data
      key:
        - column: code
          type: string
    join:
      - local: transport_mode_rec19_code
        foreign: code
    cardinality: many-to-one
    mode: non-temporal
    missingParent: null
    ambiguousParent: error
```

**Variations:**
- **Fragment crosswalks.** A crosswalk may key on part of a structured code. The first
  character of an ISO 6346 size/type code gives the length (`2` → 20 ft, `4` → 40 ft,
  `L` → 45 ft). Say so in the seed docs.
- **Mappings between two standards** (IATA ONE Record codes to UNECE codes) are shared,
  not per hub. Take them from the reference models instead of authoring a seed.

## 5. Kind 2 and kind 3

- **Kind 2, UN/LOCODE.** Import the release as a source ([Import a source
  system](import-a-source-system.md)) and bind it, keyed on the 5-character code. Join to
  the shipped countries, subdivisions and functions (kind 1). The reference models'
  UNCEFACT README lists the suggested columns.
- **Kind 2, ISO 6346.** No class ships, because of the licence. Take the rows from your own
  licensed copy, or from a TMS master that already carries the code. Store the code in the
  ISO 6346 property the reference models provide.
- **Kind 3, a TMS master.** Bind the source table. Key on the source's code, scoped by
  source if two systems keep their own lists. When a second system will add its list,
  start from `int_merged__<entity>`
  ([Add a second source to a class](add-a-second-source-to-a-class.md)). Where a standard
  exists, keep its code as an attribute and crosswalk to it as in step 4.

## 6. Never drop a row on a reference join

A fact or master model must not `inner join` a reference list. An unknown code then
silently removes the record. Left-join instead, and let the link stay empty, or map the
code to an explicit local "unknown" member.

## Checklist

- [ ] Kind decided, and recorded in a decision record when it is not obvious.
- [ ] Bound through a contracted model or source; keyed on the code, not the IRI.
- [ ] Snapshot version and `dcterms:source` in the seed docs (kind 1).
- [ ] Extensions use a user-assigned code range, union in with an `origin` column, and
      never override a shipped row.
- [ ] Every crosswalk left-joins, keeps the raw value, and documents its deliberate gaps.
- [ ] No inner join to a reference list in a fact or master model.
