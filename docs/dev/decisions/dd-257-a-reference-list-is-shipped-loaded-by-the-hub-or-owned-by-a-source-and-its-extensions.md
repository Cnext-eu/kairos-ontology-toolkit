# DD-257: A reference list is shipped, loaded by the hub, or owned by a source, and its extensions live with its rows

**Status:** Accepted
**Date:** 2026-10-18
**Affects:** `core/reference_lists.py` and `cli/reference_lists.py`
(`export-reference-list`), `core/dbt_contract_lint.py` (crosswalk check),
`scaffold/kairos-ext.ttl` (`isReferenceData` comment), the
`kairos-design-mapping` and `kairos-develop-dbt-transformation` skills, the how-to
[Use reference data and code lists](../../guide/how-to/use-reference-data.md)
**Issue:** #1126. The reference models state the same three kinds from 1.41.0
(Cnext-eu/kairos-ontology-referencemodels#125).

### Context

The reference models now ship reference data: the members of standards-body code lists
(UNECE Rec 19/20/21, Incoterms, currencies, party roles, ISO 3166 countries and
subdivisions). Each code is an `owl:NamedIndividual` of its list class, with the code in
`rdf:value`. #1126 asked the toolkit to turn those members into rows.

Testing that request against a production logistics hub showed three different kinds of
list in one hub, each with its rows in a different place:

- **Countries and subdivisions** were hand-copied seeds that duplicate what the reference
  models now ship.
- **UN/LOCODE locations** (~116,000 rows) came from a source. The reference models
  deliberately ship only the target shape, because of volume.
- **The container-type list** was the transport management system's own master table,
  with the ISO 6346 code as an attribute. ISO 6346 cannot be shipped, because ISO publishes
  no free-reuse statement.

The hub mapped operational codes (`SEA`) to standard codes (Rec 19 `1`) through
hand-authored crosswalk seeds. It also inner-joined source addresses to its country seed,
so an address with an unlisted code dropped out of the model without a warning.

Two facts about the compiler shaped the decision:

- In v5 a Silver table exists only because an EntityBinding binds a source relation or a
  contracted dbt model. Seeds already work as `ref()` leaves of a contracted model,
  column docs included (#586).
- The v5 compiler names a model after its target class (`class.name.lower()`).
  `kairos-ext:isReferenceData` does not change that name. The `ref_` prefix and SCD type 1
  that `kairos-ext.ttl` described belonged to the retired projectors. Hubs already write
  the v5 names into their bindings: a cross-domain `externalReference: {name:
  transportmodecode}` would break if the prefix appeared now.

### Decision

**A reference list is one of three kinds, decided by where its rows come from. Every kind
reaches Silver through an ordinary binding, and a local extension lives where the rest of
the list's rows live.**

1. **Three kinds.** The kind is decided by where the class is defined and whether it has
   members, never by `isReferenceData`. That annotation is unset on several shipped lists
   (IATA, OMG-LCC), and a hub may set it on its own list.

   | Kind | Rows come from | Examples | Recognised by |
   |---|---|---|---|
   | 1. Shipped standard list | the reference models' individuals | Rec 19/20/21, Incoterms, currencies, party roles, ISO 3166 | members present in the closure |
   | 2. Hub-loaded standard list | the hub, from the standard's own release | UN/LOCODE locations | defined under the reference models' `authoritative-ontologies/`, no members |
   | 3. Client- or system-owned list | the client's own source systems | a TMS container-type master, internal status codes, ISO 6346 size/type codes | everything else: derived-module shells, hub classes |

   - **Members ship only for kind 1, and only kind 1 is refreshed upstream.** The
     reference models ship shapes for all three kinds.
   - **ISO 6346 is kind 3.** Where a standard exists but cannot be shipped, the client's list
     carries the standard's code as an attribute.
   - **Where a list ships twice, bind the one the reference models name.** Countries:
     `unlcdv:Country`, not the OMG-LCC copy. Currencies: `unece:CurrencyCodeList`, not the
     IATA copy.
   - **No new annotation is defined.** A marker is added to `kairos-ext.ttl` only when a
     toolkit reader acts on it (#1126 P2).

2. **Every kind is bound.** Compile never emits a reference table that no binding asks for.
   A hub that does not bind Rec 20 never gets its 1,828 rows.
   - **Kind 1:** a seed under `integration/transforms/dbt/seeds/`, read by a contracted
     model, bound to the hub's governed class. `export-reference-list` generates the
     seed from the resolved closure.
   - **Kind 2:** a source relation bound like any other source.
   - **Kind 3:** the source's table, bound like any other source. Use
     `int_merged__<entity>` when a second system will add its own list.

3. **The code is the key, not the IRI.** A list's business key is its code, plus the list
   name when one hub class takes in more than one list. The upstream IRI is an ordinary
   column. UN/CEFACT has announced path IRIs, and a key built from the IRI would change
   every surrogate key and foreign key on that switch.

4. **Extensions live with the list's rows.**
   - **Rows.** For kinds 1 and 2, an extension is a row in a hub extension seed. The
     contracted model unions it with the shipped or loaded rows and adds an `origin`
     column. It is not an individual in the hub ontology. For kind 3, the list is the
     client's own, and an extension belongs in it.
   - **Codes.** Take an extension code from the standard's user-assigned range where it has
     one. ISO 3166-1 reserves AA, QM–QZ, XA–XZ and ZZ. Most lists reserve nothing:
     - Rec 19 uses every code from 0 to 9;
     - ISO 4217's X-codes are mostly assigned;
     - Rec 20, Rec 21 and UN/LOCODE reserve no range.

     There, the `origin` column and the binding's `unique` quality rule are the protection.
     A later release that reuses an extension's code fails the build instead of merging
     silently.
   - **No overrides.** An extension only adds rows. It never renames or redefines a shipped
     row.
   - **Retirement.** A retired extension is deprecated, not deleted, because facts point at
     it.
   - **Columns.** A hub-owned attribute of a shipped code, such as a TEU factor per
     container type, lives in a sibling seed joined on the code. Refreshing the shipped
     rows never touches it.

5. **Crosswalks are hub seeds, and the raw value stays.** A mapping from one source
   system's codes to a list's codes is source-specific:
   - It is a hub seed named `<source>_<list>_map`.
   - A contracted model left-joins it.
   - The binding keeps the raw source value as a property and links the mapped code
     through a relationship with `missingParent: null`.
   - Codes left unmapped on purpose are named in the seed's column docs.
   - A mapping between two *standards* is shared and belongs in the reference models.
   - A crosswalk may read a fragment of a structured code, such as the first character of
     an ISO 6346 size/type code for the length, as long as its docs say so.

6. **A reference join never drops a row.** A model that reads a fact or master record
   left-joins its reference lists. An unknown code becomes a null link, or a link to an
   explicit local "unknown" member, never a missing row.

7. **`isReferenceData` does not name tables and does not decide the kind.** Its comment in
   `kairos-ext.ttl` now says so. Physical naming and load policy come from the binding.

### Consequences

- **`kairos-ontology export-reference-list` writes a kind-1 list's seed** (#1126 P2):
  - It reads the members from the resolved closure and keys them on `(code_list, code)`.
  - It writes seed docs that record each list's snapshot and source and type every column
    as the adapter's text type.
  - It refuses to overwrite a seed it did not generate, and refuses a class with no
    members.
  - A hub re-runs it after each reference-models upgrade, so the change shows up as a diff;
    `--check` reports drift without writing.
  - It never writes `<name>_local`, so extensions survive a refresh.
  - Each generated seed's docs record the class and domain it came from.
    `export-reference-list --all` regenerates every generated seed after an upgrade, and
    `update --upgrade` names that command first. The hub's `pr-validate` workflow runs
    `--all --check`, so a seed left behind by an upgrade fails the PR.
  - It writes no binding: the binding maps seed columns onto the hub's own properties,
    which only the hub knows.
- **`validate-dbt-contracts` checks crosswalk seeds** (#1126 P3):
  - A crosswalk declares its target with dbt's own `relationships` test in its seed docs.
  - When that target is an authored seed, every non-empty code must occur in it, or the
    lint reports `dbt-contract.crosswalk-unknown-code` (an error).
  - An empty cell is a code left unmapped on purpose.
  - A target that names no seed or model is a warning.
  - A target that is a model is left to dbt, which runs the same test after the build.

  Chained with `export-reference-list --check`, the crosswalk is checked against the
  shipped individuals without the lint loading the ontology.
- No compiled output changes. Hubs that bound reference tables under the v5 names keep
  them.

### Alternatives rejected

| Option | Why rejected |
|---|---|
| Compile emits a `ref_*` seed for every list class with members | It would create tables no binding asked for. That is a second way for Silver to appear, and it emits lists the hub never uses. |
| Apply the `ref_` prefix in the v5 compiler | It renames tables that hubs already reference by name, and every `externalReference` breaks. |
| Decide the kind by `isReferenceData` | Shipped IATA and OMG-LCC lists do not carry it, and a hub may set it on its own list. Kind 1 lists would then read as kind 3, and kind 3 as kind 2. |
| Key reference rows on the upstream IRI | The IRI scheme is changing upstream. Codes are what source data carries. |
| Declare kind-1 extensions as hub-local individuals | The binding reads rows, so every extension would be declared twice. And kind-2 rows are not individuals at all. |
| ISO 6346 as kind 2 | Nothing ships for it, not even a class. The real lists are client masters that carry the code as an attribute. |
