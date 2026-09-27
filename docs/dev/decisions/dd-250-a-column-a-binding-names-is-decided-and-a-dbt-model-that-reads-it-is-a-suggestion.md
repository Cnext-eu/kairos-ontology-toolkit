# DD-250: A column a binding names is decided, and a dbt model that reads it is a suggestion

**Status:** Accepted
**Date:** 2026-09-27
**Affects:** `compile --check` and `validate` (the DD-169 gate), `draft-gap-decisions`, `audit-column-coverage`
**Issue:** #1062
**Implementation:** `core/bound_columns.py` (`load_bound_columns`, `is_gap_column_decided`, `binding_referenced_columns`, `sql_identifiers`, `reads_star`), `core/alignment_report.py` (`undecided_gap_columns`, `annotate_read_by`, `GAP_RESOLUTIONS`), `core/gap_decisions.py` (`_apply_binding_evidence`, `accept_proposals`, `apply_decision_sheet`)

### Context

DD-169 stops the workflow on a source column that carries real business data and has no
canonical home and no recorded decision. DD-180's table gate learned in #973 that a table
an EntityBinding reads is decided by that binding: the ledger refuses a table-grain
`bound` row because "authoring the binding is what states it", and `compile` and
`validate` agree through one authority, `load_bound_relations`.

The column gate never learned it. `undecided_gap_columns` read the alignment files and the
ledger only. A column a binding already mapped to Silver, whether through a
`source.relation` field expression or through the `source.dbtModel` chain of a merge model,
was listed as a gap until someone wrote a column-grain `bound` row by hand, and the gate's
own resolution text did not mention authoring a binding as a way out. On the
Global-Data-Warehouse hub, closing the gate on 5.24.0 put 575 columns in 208 decisions in
front of a reviewer. Among them: `unlocode.name` and `unlocode.status`, bound as
`locationName` and `locationStatusCode`; `cargowise.refairline.rm_airline_name1`, reaching
`carrierName` through `int_merged__carrier_code`; `PARTY_QUALIFIER`, reaching
`consignmentPartyRoleCode` through a role code map. A reviewer cannot tell such a false gap
from a real one without reading SQL, so real gaps got the same blanket answer as false
ones, and that answer was `deferred` (#1062, part 2 of the finding is DD-251).

Two facts shape the answer.

- **A relation binding names its columns.** `fields[].expression`, `technicalFields`, the
  identity keys, the grain, a relationship's join, a quality rule, the incremental load
  columns: each names a source column outright. `audit-column-coverage` (#353) already
  extracts them, in `_binding_referenced_columns`, and nothing else used that extraction.
- **A dbtModel binding does not.** Its fields name the contracted model's *output*
  columns. No column lineage exists at design time: dbt's `manifest.json` carries
  model-level edges only and is not present before a build (`dbt_lineage.py` declines it
  for that reason), `catalog.json` has no lineage at all, and the hub examples above are
  not name-preserving. What can be read from the SQL is whether the column's *name* occurs
  as an identifier in the model that calls `source()` on its table, or in a closure model
  downstream of it. Under the three-layer rule (#949) the `stg_` model that reads the
  table says `select *` and the `int_` model above it is where the column is named.

### Decision

1. **A column a `source.relation` binding names is decided.** `load_bound_columns` walks
   `integration/bindings/`, parses each relation binding with the compiler and records,
   per `(system, table)`, every column `binding_referenced_columns` finds, keyed by the
   binding file. `is_gap_column_decided(recorded, bound, system, table, column)` answers
   `"ledger"`, `"binding"` or `""`, and is the one predicate the DD-169 gate, the decision
   sheet, `--auto` and `--apply` share (#948: two definitions of "decided" once let the
   sheet say 0 while the gate blocked). No ledger row is written; the binding is the
   record, as at table grain. A binding the compiler rejects decides nothing.
2. **A `source.dbtModel` chain is evidence, not a decision.** The `ref()` closure is
   walked as `load_bound_relations` walks it (a `ref()` matching no model or several ends
   the branch). For every table a closure model reads with `source()`, the identifiers of
   that model and of every closure model downstream of it are attributed to the table's
   columns, lower-cased, after Jinja blocks, comments and string literals are removed and
   a short keyword stoplist is applied. The gate carries the result on each undecided
   column as `read_by`; nothing in this walk clears a column.
3. **The sheet turns the evidence into a proposal.** A name every occurrence of which a
   chain model names is proposed `bound` with `confidence: high` and the models in its
   reasoning; a reviewer confirms it, or `--accept-proposals` does, and the ledger row
   carries `read-by:<model>` as evidence. A name on a table the direct reader takes with
   `select *` (or a star macro), which nothing downstream names, is `lineage_unconfirmed`:
   a rule proposal that would take it out of Silver (`deferred`, `not-business-data`) is
   withdrawn the way BI demand withdraws it (#942), and `--accept-proposals` holds it as
   `held-for-binding-read`. The column may already reach Silver; ruling it out on a name
   rule would be the omission DD-169 exists to stop.
4. **The gate says so.** `GAP_RESOLUTIONS` opens with the binding route, and the gate line
   and `validate` message carry `named by <model>` or `read by <model> (lineage
   unconfirmed: select *)` when a chain touches the column.

### Rejected alternatives

- **Every column of a table a chain reads is decided.** #973's rule lifted to columns
  unchanged. A `select *` stage feeding a five-column `int_` model would retire the other
  hundred columns without anyone deciding, which is the #881 failure mode with a binding
  in place of a table-grain `deferred`. The user's steer was explicit: the relation case
  is a fact and toolkit functionality; the dbtModel case is a re-run situation, since dbt
  models rarely exist before modelling, and is a suggestion.
- **A name in the chain SQL clears the gate.** Cheaper for the reviewer, but an identifier
  in a `where` clause or a join key that is dropped two models up is not a mapping, and
  the difference is invisible without lineage. A proposal the reviewer confirms costs one
  keystroke and leaves a ledger row that names the model; a silent clear leaves nothing.
- **SQL column lineage (sqlglot) or the dbt manifest.** Neither is available at design
  time; the manifest has no column edges; the mappings that matter on the hub are code
  maps and sign changes that no lineage tool would name-match either.

### Consequences

- `UnmappedColumn` gains `read_by` and `lineage_unconfirmed`, emitted in `to_dict` only
  when set; the memoized alignment report never carries them, `undecided_gap_columns`
  attaches them on the way out.
- The sheet's `loose_evidence_fingerprint` includes `read_by` only when non-empty, so
  every carried `--suggest` answer on every existing hub survives the upgrade (#1056).
- `apply_decision_sheet` reports `skipped_bound_by_binding`; an old sheet decision typed
  for a column a binding now names is left alone and counted, never written.
- `audit-column-coverage` imports `binding_referenced_columns` from here. Its keying by
  table name without system, which attaches every dbtModel binding's columns to table
  `""`, is a separate defect left for a follow-up issue.
- A hand-written column-grain `bound` row is still accepted; on a column a relation
  binding names it is now redundant.
- A ledger cannot hold column lineage that does not exist. A hub whose stages all say
  `select *` sees its gap columns annotated, not cleared, and confirms them from the sheet.
