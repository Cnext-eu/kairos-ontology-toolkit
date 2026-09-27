### Added
- **A column-grain `deferred` is a visible backlog (#1062, DD-251).** It was defined as
  "stays visible as a known gap" and nothing showed it again: the DD-169 gate counted it
  decided, the decision sheet dropped it on every redraft, `next` raised no action for it
  and `alignment-report` never read the ledger. On one hub about 2,630 such rows held
  airline names, a party role qualifier and a container customs status. Now:
  - `kairos-ontology next` raises `review-deferred-columns` (optional, never blocking)
    while any exist, with counts per domain and how many an imported Power BI model uses,
    routed to kairos-design-domain; the JSON form carries `inputs.deferred_columns`.
    Schema version 9.
  - `alignment-report` lays the ledger and the bindings over the report: "Columns needing
    a decision" lists only what the gate still counts undecided, with the dbt-chain
    evidence beside each; "Coverage by domain" splits gap columns into undecided,
    deferred, ruled out, extension and bound; a new "Deferred backlog" section lists the
    backlog per domain, ranked by BI demand and table size, with each entry's rationale
    and date. JSON gains `undecided_columns`, `deferred_backlog` and
    `domains[].decisions`.
  - `draft-gap-decisions --include-deferred` re-lists deferred names on the sheet with
    `previous_decision`, `previous_rationale`, `previous_decided_by` and `recorded_on`;
    `--apply` overwrites exactly those rows, a blank leaves them deferred, and
    `--accept-proposals` refuses the flag (its fallback is `deferred`).
  - Every new ledger row carries `recorded_on` (UTC date). Rows written before keep their
    shape until replaced.
  - Ruling out a column a Power BI model uses now warns on the manual path too:
    `draft-gap-decisions --apply` prints the names, and
    `source-disposition set --column ... --disposition deferred|not-business-data` warns.

### Changed
- The kairos-design-domain skill no longer says a `deferred` column "has been ruled out";
  `not-business-data` and `blueprint-gap` are, and `deferred` is the modelling backlog.
  kairos-design-source gains the backlog step and names the evidence on the sheet that is
  not a decision (`bi_demand`, `read_by`); kairos-design-mapping says binding a deferred
  column is the intended outcome.
- `validate`'s pointer to the full list of undecided columns names the JSON key
  (`undecided_columns`) now that the report tells decided columns apart.

### Decisions
- DD-251: a deferred column is a backlog item the workflow keeps raising, not a decision.
