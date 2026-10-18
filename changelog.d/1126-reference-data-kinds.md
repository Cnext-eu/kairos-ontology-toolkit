### Documentation
- **New how-to: Use reference data and code lists.** A code list is one of three kinds:
  - shipped by the reference models as individuals (UNECE Rec 19/20/21, ISO 3166);
  - loaded by the hub (UN/LOCODE locations, ISO 6346 container codes);
  - owned by a source system (a TMS master).

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
