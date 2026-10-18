# Use reference data and code lists

**Skills:** `kairos-design-mapping`, `kairos-develop-dbt-transformation`

A code list (transport modes, countries, container types) reaches Silver like any other
entity, through a binding. What differs between lists is **where the rows come from**.
Decide that first; everything else follows from it ([DD-257](https://github.com/Cnext-eu/kairos-ontology-toolkit/blob/main/docs/dev/decisions/dd-257-a-reference-list-is-shipped-loaded-by-the-hub-or-owned-by-a-source-and-its-extensions.md)).

## 1. Decide the kind

| Kind | Rows come from | Examples | You author |
|---|---|---|---|
| **1. Shipped standard list** | the reference models, as individuals of the list class | UNECE Rec 19/20/21, Incoterms, currencies, party roles, ISO 3166 countries and subdivisions | a seed exported from the shipped members, a contracted model, a binding |
| **2. Hub-loaded standard list** | the standard's own release | UN/LOCODE locations (too large to ship) | a source import and a binding |
| **3. Client- or system-owned list** | your own source systems | a TMS container-type master, internal status codes, ISO 6346 container size/type codes | a binding to the source table |

The kind depends on where the class is defined and whether it has members. The
`kairos-ext:isReferenceData` annotation does not decide it: several shipped lists don't
carry it, and you may set it on your own list.
- **Kind 1:** the list has members in your closure. The export script in step 2 prints
  them.
- **Kind 2:** the class is defined under the reference models' `authoritative-ontologies/`
  but has no members. The export script writes only the header row. The module README
  says where to load from (for UN/LOCODE: `authoritative-ontologies/UNCEFACT/README.md`,
  "UN/LOCODE locations: load in the hub").
- **Kind 3:** everything else, such as a derived module's empty shell (`PartyRoleCode`) or
  your own class. When a standard exists but can't be shipped (ISO 6346), your list
  carries the standard's code as an attribute.

**Where a list ships twice, bind the one the reference models name.** Countries:
`unlcdv:Country`, not the OMG-LCC copy. Currencies: `iso4217:CurrencyCode`, taken from
SIX, the ISO 4217 maintenance agency. Don't use the UN/CEFACT copy (`unece:CurrencyCodeList`),
which lags ISO and doesn't mark withdrawn codes, or the IATA copy (DD-258).

Nothing appears in Silver until you bind it. A list you never bind, such as Rec 20's 1,828
units, costs nothing.

## 2. Kind 1: bind a shipped list

Take the shared list into your governed class. The subclass runs from the standard's list
to your class: your class means "the standard's codes plus our extensions", and an
extension never becomes a member of the standard's list:

```turtle
ref:TransportModeCode a owl:Class .
unece:TransportModeCodeList rdfs:subClassOf ref:TransportModeCode .
```

Write the members into a seed with `export-reference-list`. It reads the resolved closure,
so it sees exactly what your hub imports. Never copy members out of the `.ttl` by hand:
reading serialised RDF as text is what DD-103 rules out.

```bash
kairos-ontology export-reference-list ref:TransportModeCode --domain reference-data
```

Pass the list class (`unece:TransportModeCodeList`) or your governed class. With your
governed class, every list that subclasses it is collected. The command writes:

```text
# integration/transforms/dbt/seeds/reference/transport_mode_code.csv
code_list,code,name,iri,list_version,list_source,deprecated
TransportModeCodeList,0,Transport mode not specified,https://vocabulary.uncefact.org/TransportModeCodeList#0,2026-10-17,https://vocabulary.uncefact.org/,false
…
```

**What a row carries (DD-258).** After `code_list`, `code`, `name` and `iri`, every row has:
- **`list_version` and `list_source`.** These are its list's `owl:versionInfo` and
  `dcterms:source`. Bind `list_version` when your class has a version property, such as a
  code-list version that Gold shows. Never type the snapshot date into SQL: the next
  refresh changes the seed, but nothing would change the SQL.
- **`deprecated`.** It is `true` for a code the standard has withdrawn. The row stays,
  because older facts still point at it. Filter on it in a model that offers codes for new
  data, not in the governed list.
- **One column per fact the members carry.** Each `owl:DatatypeProperty` on the members
  becomes a column named after the property in snake_case. ISO 4217, for example, gives
  `numeric_code`, `minor_unit`, `withdrawal_date` and `is_fund`. Several values share one
  cell, sorted and separated by ` | `. A member without the fact leaves its cell empty.

It also writes `transport_mode_code.yml`, the seed docs:
- **Column docs.** Every column is described. A fact column names the property it came
  from.
- **Text types.** Every column is typed as text for your hub's adapter, so a code such as
  `02` keeps its leading zero.
- **Generated marker.** The command refuses to overwrite a seed it did not generate
  (`--force` overrides), and never touches `<name>_local`.
- **Keeping current.** The docs header records the class and domain the seed came from.
  - After a reference-models upgrade (`update --upgrade` or `update-refmodels`), run
    `kairos-ontology export-reference-list --all`. It regenerates every generated seed,
    and the change shows up as a diff in the hub PR.
  - `--all --check` writes nothing and fails when a seed is stale. The hub's
    `pr-validate` workflow runs it, so a forgotten regeneration fails the PR.
- **Where it goes (DD-260).** A new seed goes to `seeds/reference/`, or to the seeds
  root when your hub already keeps generated seeds there. `--dir` chooses another
  folder. A seed that exists is always regenerated in its own folder, wherever you
  moved it.
- **No members, no seed.** A list with no members (kind 2 or 3) is refused.

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

1. **Take the code from the user-assigned range, if the standard has one.** ISO 3166-1
   reserves AA, QM–QZ, XA–XZ and ZZ for local use, so a later ISO release can never give
   your code to another country. Most lists reserve nothing:
   - Rec 19 uses every code from 0 to 9;
   - ISO 4217's X-codes are mostly assigned;
   - Rec 20, Rec 21 and UN/LOCODE have no reserved range.

   For those, pick a code the standard doesn't use today, and rely on the `origin`
   column and the `unique` rule below.
2. **Add the row to an extension seed** named after the shipped one, in
   `seeds/extensions/` (step 8). It is a row, not an individual in your hub ontology:

   ```text
   # integration/transforms/dbt/seeds/extensions/country_local.csv
   code_list,code,name
   Country,XK,Kosovo
   ```

3. **Union the two in the contracted model** and say where each row came from:

   ```sql
   select code_list, code, name, iri, list_version, deprecated, 'shipped' as origin
   from {{ ref('country') }}
   union all
   select code_list, code, name, null as iri, null as list_version, 'false' as deprecated,
       'hub' as origin
   from {{ ref('country_local') }}
   ```

   Name the columns. A reference-models upgrade can add a fact column to the shipped seed,
   and a `select *` union then fails on the column count.

The binding's `unique` rule on `code` fails if a later snapshot ships a code you already
added locally. That failure is what you want: decide then whether to retire the local row.

**Rules:**
- **Never override a shipped row.** An extension only adds rows; it never renames or
  redefines a shipped one.
- **Deprecate a retired extension; don't delete it.** Facts already point at it.

The same steps apply to a kind 2 list: union the extension seed with the loaded source.
For a kind 3 list, the list is your own, so add the code in the source system's list
itself.

### Extra columns

First check the shipped seed's columns: a fact the reference models state, such as
ISO 4217's numeric code or minor unit, is already there and refreshes with the list. When
you need an attribute the standard does not carry, such as a TEU factor per container
type, keep it in a sibling seed keyed on the code. Join it in the contracted
model. Refreshing the shipped rows then never wipes it.

```text
# integration/transforms/dbt/seeds/extensions/container_type_teu.csv
code,teu_factor
22G1,1
42G1,2
45G1,2.25
```

## 4. Map source codes to the list (crosswalks)

Source systems use their own codes (`SEA`, `AIR`). Map them to the list's codes with a
hub seed per source and list:

```text
# integration/transforms/dbt/seeds/crosswalks/tms_transport_mode_rec19_map.csv
source_mode_code,rec19_code
SEA,1
ROA,3
AIR,4
```

In the crosswalk's seed docs, declare which list its codes come from, with dbt's own
`relationships` test. Point the test at **the list as Silver sees it**: the contracted
model from step 2, which unions the shipped seed with your extension seed. A test on the
generated seed alone fails at build as soon as a crosswalk maps to a local code. Name the
codes you leave unmapped on purpose:

```yaml
# integration/transforms/dbt/seeds/crosswalks/tms_transport_mode_rec19_map.yml
version: 2
seeds:
  - name: tms_transport_mode_rec19_map
    description: "TMS transport mode → UNECE Rec 19. COU (courier) and blank are not mapped, so their link stays empty."
    columns:
      - name: rec19_code
        data_tests:
          - relationships: {to: "ref('int_reference__transport_mode_code')", field: code}
```

`validate-dbt-contracts` reads that test and checks every code in the column against the
list, before anything is built. It reads a union model through the seeds it selects, and
a seed target together with its `<list>_local` extension:
- **A typo** such as `l` for `1` is an error (`dbt-contract.crosswalk-unknown-code`), with
  its line number.
- **An empty cell** is a code left unmapped on purpose, and is allowed.
- **A local code behind a test on the generated seed** is a warning
  (`dbt-contract.crosswalk-targets-shipped-only`): the code is valid, but dbt's test would
  fail. Point the test at the union model.
- **A model that reads a source or another model** can't be read offline, so the lint
  leaves it to dbt.
- **dbt runs the same test after the build,** so a later edit can't slip through.

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
- **Kind 3, a TMS master.** Bind the source table. Key on the source's code, scoped by
  source if two systems keep their own lists. When a second system will add its list,
  start from `int_merged__<entity>`
  ([Add a second source to a class](add-a-second-source-to-a-class.md)). Where a standard
  exists, keep its code as an attribute and crosswalk to it as in step 4.
- **Kind 3, ISO 6346 container size/type codes.** No list ships, because ISO publishes no
  free-reuse statement. Your equipment-type list, usually the TMS master, carries the code
  as an attribute. Map it to the ISO 6346 property the reference models provide: BSP
  `commercial:equipmentSizeType`, DCSA `equipment:isoEquipmentCode`, or MMT
  `equipment:equipmentSizeType`.

## 6. Never drop a row on a reference join

A fact or master model must not `inner join` a reference list. An unknown code then
silently removes the record. Left-join instead, and let the link stay empty, or map the
code to an explicit local "unknown" member.

## 7. Replace a list you used to load from a source

Perhaps you bound a list before the reference models shipped it, from a Bronze table you
imported (Rec 19 parsed from the UNECE document) or from an operational system's copy
(a TMS Incoterms table). Once you move the binding to the shipped list's seed, nothing
binds the old table any more. Its columns still hold business data, so the DD-169 gate
reports them:

```text
✗ 1 source column(s) in 'reference-data' carry real business data with no canonical home
  and no recorded decision:
    reference_data.transport_mode.name (varchar(8000)) [no-reference-property]
```

Record that another binding replaced the table (DD-259):

```bash
kairos-ontology source-disposition set --system reference_data --table transport_mode \
  --disposition superseded --superseded-by reference-data-transport-mode-code \
  --rationale "Rec 19 now comes from the shipped list's seed."
```

- **`--superseded-by` is a binding's `metadata.name`.** The command refuses a name no
  binding has, and a table a binding still reads, since that table still reaches Silver.
  Move the binding first.
- **The table's columns are decided with it.** `generate-bindings` drafts no binding for
  it.
- **The decision survives a re-import.** The source system's next `import-source` brings
  the table back into the vocabulary, and the ledger row still answers for it. Don't
  delete the vocabulary, samples and `_analysis` entries by hand: for an operational
  system, the next import restores them anyway.
- **The audit keeps checking.** If you delete or rename the replacing binding later,
  `validate` fails with `disposition.superseded-by-unknown-binding`
  until the row names a binding again.

The same disposition fits any table another binding replaced, such as an old system's
table after a migration.

## 8. Organise the seeds folder

Four kinds of seed sit under `integration/transforms/dbt/seeds/`, each owned by someone
different. Keep each kind in its own folder, so a reviewer sees which files must never be
edited by hand:

| Folder | Holds | Who edits |
|---|---|---|
| `reference/` | Seeds `export-reference-list` generated | nobody: regenerate with `--all` |
| `extensions/` | `<list>_local` rows and `<list>_<attribute>` columns (step 3) | data steward |
| `crosswalks/` | `<source>_<list>_map` (step 4) | data engineer |
| `hub-lists/` | Code lists the hub owns, with no standard behind them | business owner |

- **Only `reference/` is a toolkit convention.** `export-reference-list` writes a new seed
  there. The other three are a recommendation: nothing checks them.
- **dbt names a seed by its file name, not its folder.** `ref('transport_mode_code')`
  works wherever the file sits, so moving a seed changes no SQL. Two seeds with one name
  in different folders are an error (`dbt-contract.seed-duplicate-name`).
- **Move a seed with its docs.** Move `<name>.csv` and `<name>.yml` together.
  `export-reference-list --all` then regenerates the seed in its new folder.
- **Don't prefix the names by kind.** A prefix renames the dbt resource, and every
  `ref()` and `relationships` test that names it breaks.

Folders let `CODEOWNERS` route each kind to its owner:

```text
# .github/CODEOWNERS
/integration/transforms/dbt/seeds/reference/    @your-org/data-platform
/integration/transforms/dbt/seeds/extensions/   @your-org/data-stewards
/integration/transforms/dbt/seeds/crosswalks/   @your-org/data-engineering
/integration/transforms/dbt/seeds/hub-lists/    @your-org/business-owners
```

## Checklist

- [ ] Kind decided, and recorded in a decision record when it is not obvious.
- [ ] Bound through a contracted model or source; keyed on the code, not the IRI.
- [ ] A list version a class needs is bound from the seed's `list_version`, never
      typed into SQL (kind 1).
- [ ] Extensions are seed rows, not individuals. They take a user-assigned code where
      the standard reserves a range, are unioned in with an `origin` column, and never
      override a shipped row.
- [ ] Every crosswalk left-joins, keeps the raw value, documents its deliberate gaps, and
      declares its target with a `relationships` test.
- [ ] No inner join to a reference list in a fact or master model.
- [ ] A table the list replaced is recorded `superseded`, naming the binding that
      replaced it.
- [ ] Generated seeds sit in `seeds/reference/`, apart from the seeds people edit.
