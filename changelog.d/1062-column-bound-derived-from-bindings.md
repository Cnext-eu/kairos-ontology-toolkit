### Changed
- **The DD-169 column gate reads the bindings (#1062, DD-250).** A source column an
  EntityBinding's `source.relation` names -- in a field expression, the identity keys, the
  grain, a relationship join, a quality rule or the incremental load -- is decided by that
  binding, the way a bound table has been decided for the DD-180 gate since #973. It no
  longer needs a hand-written column-grain `bound` row; `compile --check`, `validate`,
  `draft-gap-decisions` and `--apply` all ask one predicate, so they cannot disagree. On
  a hub whose bindings already consume hundreds of columns alignment called unmapped,
  those columns leave the gate and the sheet.
- **A `source.dbtModel` binding's chain is offered as evidence, never as a decision.** No
  column lineage exists at design time, so a chain that reads the column's table does not
  clear it. Instead, when a model in the binding's `ref()` chain names the column, the
  gate line says `named by <model>`, the sheet entry carries `read_by` and proposes
  `bound` with high confidence, and `--accept-proposals` records it with the model as
  evidence. When the reading stage says `select *` and nothing downstream names the
  column, the entry is `lineage_unconfirmed`: a rule may not draft `deferred` or
  `not-business-data` for it, and `--accept-proposals` holds it
  (`held-for-binding-read`) until a reviewer confirms the select list or binds it.
- The gate's resolution text opens with the binding route. `apply_decision_sheet` reports
  `skipped_bound_by_binding`, and the draft summary counts `with_binding_read` and
  `with_lineage_unconfirmed`.
- `audit-column-coverage` reads its column extraction from the new `core.bound_columns`
  module. Its keying by table name without system, which attaches a `dbtModel` binding's
  columns to an empty table, is unchanged and tracked as a follow-up.

### Decisions
- DD-250: a column a binding names is decided, and a dbt model that reads it is a
  suggestion.
