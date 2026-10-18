### Documentation
- **New how-to: Use reference data and code lists.** A code list is one of three kinds:
  - shipped by the reference models as individuals (UNECE Rec 19/20/21, ISO 3166);
  - loaded by the hub (UN/LOCODE locations);
  - owned by a client or source system (a TMS master; ISO 6346 container codes, which
    cannot be shipped).

  This matches the reference models from 1.41.0. The kind follows from where the class is
  defined and whether it has members, not from `isReferenceData`. Local extensions are
  seed rows unioned in with an `origin` column, not ontology individuals.

  Each kind reaches Silver through an ordinary binding, keyed on the code. The guide has
  worked examples for:
  - exporting a shipped list into a seed;
  - adding local extension rows (user-assigned codes such as `XK`) and extra columns;
  - mapping source codes to the list through left-joined crosswalk seeds.

  The `kairos-design-mapping` and `kairos-develop-dbt-transformation` skills point to it.

### Decisions
- **DD-257: a reference list is shipped, loaded by the hub, or owned by a source, and its
  extensions live with its rows.** It also corrects `kairos-ext:isReferenceData`'s
  description in `kairos-ext.ttl`: in v5 it changes neither the table name (no `ref_`
  prefix) nor the load policy. The binding decides both. Compiled output is unchanged.
