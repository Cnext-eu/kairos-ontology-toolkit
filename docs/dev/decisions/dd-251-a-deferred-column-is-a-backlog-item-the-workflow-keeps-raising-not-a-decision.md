# DD-251: A deferred column is a backlog item the workflow keeps raising, not a decision

**Status:** Accepted
**Date:** 2026-09-27
**Affects:** `next`, `alignment-report`, `draft-gap-decisions`, `source-disposition set`, the ledger; the kairos-design-domain, kairos-design-source and kairos-design-mapping skills
**Issue:** #1062
**Implementation:** `core/deferred_backlog.py` (`load_deferred_columns`, `DeferredBacklog`, `decision_overlay`, `DecisionOverlay`), `core/next_actions.py` (`DeferredColumnObservation`, `review-deferred-columns`), `core/hub_inspection.py` (`_deferred_column_status`), `core/alignment_report.py` (`render_markdown(overlay=...)`), `core/gap_decisions.py` (`build_decision_sheet(include_deferred=...)`, `apply_decision_sheet`, `accept_proposals`), `core/source_disposition.py` (`recorded_on`)

### Context

`source_disposition.DISPOSITIONS` defines `deferred` as "in scope and modelled later;
carries a reason and stays visible as a known gap". It is the only column-grain answer
that asserts neither that the data is junk nor that the reference model is defective, so
it is what an operator reaches for, and the toolkit reaches for it too:
`--accept-proposals` falls back to it, the rule proposer drafts it for JSON blobs, and
the DD-169 gate blocks compile until every column has some answer.

Nothing showed a column-grain `deferred` again. The gate counted it decided
(`column_decision` returns any column-grain row). The decision sheet dropped it on every
redraft. `generate-bindings` and `scaffold-extensions` acted on `registered-extension`
only. `next` raised domain-level and table-level and class-level dispositions, never a
column-level one. `alignment-report` never read the ledger at all: its "Columns needing a
decision" table listed every gap column whatever the ledger said, so a deferred column
appeared there unlabeled, beside undecided and ruled-out ones, and `validate` pointed at
that table as the full list of undecided columns. The only command that touched the
entries was `source-disposition clear`, which withdraws without listing. The
kairos-design-domain skill went further and told the designer that a column dispositioned
`deferred` "has been ruled out, and modelling it anyway re-opens a decision someone
already made".

On the Global-Data-Warehouse hub the ledger held about 2,630 column-grain `deferred`
rows. Before the finding they included airline names and codes, the party role qualifier
and the container customs status. #881 had fixed the table-grain form of the same defect,
a table `deferred` silently retiring its columns; the column-grain form was intact.

The ledger carried no date, so a backlog could not be read by age, and no domain, so it
could not be read per domain without a join.

### Decision

1. **`deferred` is a backlog.** Its definition now says so: "a backlog item the workflow
   keeps raising; carries a reason and a date, and stays visible until the column is
   modelled and bound". `core/deferred_backlog.py` is the one reader of that backlog. It
   joins the ledger's column-grain `deferred` rows with the anchors sheet (domain), the
   source vocabulary's `rowCount` (the textual read `validate` uses, not an rdflib parse)
   and the imported Power BI models (demand, #942), and ranks each domain's entries BI
   demand first, then largest table.
2. **`next` raises it.** `HubInputSnapshot.deferred_columns` observes the backlog
   (counts per domain and with BI demand, read without building the alignment report so
   `next` stays cheap on a cold hub), and `review-deferred-columns` is an OPTIONAL,
   never-blocking action routed to kairos-design-domain whose rationale names the three
   exits: model it, bind it (kairos-design-mapping), or re-decide it. Schema version 9.
3. **`alignment-report` reads the ledger.** A `DecisionOverlay`, built from the same
   predicate the gate uses (`is_gap_column_decided`, DD-250), tells an undecided column
   from a deferred, ruled-out, extension or bound one. With it, "Columns needing a
   decision" lists only what the gate still counts undecided, with the dbt-chain
   evidence beside it; "Coverage by domain" splits each domain's gap columns by state;
   and a "Deferred backlog" section lists the backlog per domain. The JSON form gains
   `undecided_columns`, `deferred_backlog` and `domains[].decisions`. Without an overlay
   (a foreign `--analysis` directory, an unreadable ledger) the report is byte-for-byte
   what it was.
4. **The sheet re-lists it on request.** `draft-gap-decisions --include-deferred` puts
   every deferred name back on the sheet with `previous_decision`,
   `previous_rationale`, `previous_decided_by` and `recorded_on`, so it is re-decided
   from what was known. `--apply` overwrites exactly the column-grain `deferred` rows of
   a re-listed name, checking the ledger and never the sheet's claim, and never another
   disposition or a table-grain row. A carried sheet decision equal to the previous
   one is not carried. `--accept-proposals` holds such entries
   (`held-previously-deferred`) and refuses to combine with the flag: its fallback is
   `deferred`, which would only re-stamp the row.
5. **Every new row carries `recorded_on`.** The UTC date, written by `_ledger_entry`;
   rows written before the key existed keep their shape until they are replaced.
6. **Ruling out a demanded column warns on the manual path.** `apply_decision_sheet`
   returns `ruled_out_with_bi_demand`, the CLI prints it, and `source-disposition set
   --column ... --disposition deferred|not-business-data` warns when an imported Power BI
   model uses the column. Reported, never refused: the reviewer may know the report no
   longer needs it.
7. **The skills say the same.** kairos-design-domain: `not-business-data` and
   `blueprint-gap` are ruled out, `deferred` is the opposite and modelling it is the
   expected outcome. kairos-design-source: the backlog step, and the three kinds of
   evidence on the sheet that are not decisions. kairos-design-mapping: binding a
   deferred column is the intended outcome.

### Rejected alternatives

- **An expiry on `deferred` (re-open after N days or on the next toolkit version).** It
  would re-block compile on a schedule nobody chose and put the same 2,630 rows back in
  front of a reviewer at once. A ranked, visible backlog and an explicit re-listing flag
  keep the gate deterministic and the review sized by a human.
- **Make the gate count `deferred` as undecided.** That is the table-grain rule after
  #881, and at column grain it would remove the one honest answer that unblocks compile
  without an ontology change; hubs would answer `not-business-data` instead, which is
  worse.
- **Read the ledger inside the memoized alignment report.** The report is the gate's
  cached input, keyed on the alignment files; folding the ledger in would either widen
  the cache key or serve stale decisions. The overlay is computed per render.

### Consequences

- `next` schema version 9; `deferred cols:` line in the text form,
  `inputs.deferred_columns` in the JSON form.
- Ledger rows gain `recorded_on`; a hub diffing its ledger in git sees the key appear on
  new or replaced rows only.
- The class grain has the same blind spot (`record-class-disposition` fires only for
  undecided classes; a class-level `deferred` is counted decided) and is left for a
  follow-up issue.
- The backlog's domain is the alignment domain when the column is a gap column there,
  else the anchors sheet's; a hub without anchors sees its backlog under "(no domain)".
