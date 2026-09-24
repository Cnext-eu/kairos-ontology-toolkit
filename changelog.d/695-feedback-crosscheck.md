### Added
- **`analyse-sources` names the tables that open feedback records discuss (#695).**
  After a run, every table the run assigned that an open `HUB-FB-*` record under
  `.import/modeling/feedback/` names is listed with the domain it was just given, for
  example `HUB-FB-…: tms.partyaddress -> party`. A re-run used to contradict a recorded
  human review silently: on one hub it did so in five places. The records are prose, so
  judging whether each assignment agrees is left to the reviewer. The durable override
  remains `integration/discovery/design-rulings.yaml` (DD-192).
