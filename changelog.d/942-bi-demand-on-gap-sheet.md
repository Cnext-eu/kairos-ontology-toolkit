### Changed
- **The gap-decision sheet shows which columns an imported Power BI model uses (#942).**
  The DD-169 gate decides which source columns reach Silver, but it never read the BI
  models `import-tmdl` had already recorded. On one hub a sailing date the headline
  weekly report is grained on was auto-deferred like any other timestamp, and the report
  became unbuildable, with no diagnostic anywhere. Now a column whose name a concept
  mapping uses (as a model column, a relationship key, or a column a measure's DAX
  reads) is handled as follows:
  - it carries `bi_demand` on its decision row, naming the model, table and use;
  - it is never drafted as `deferred` or `not-business-data` by a name rule. The rule's
    reading stays in the reasoning, so both are visible;
  - `--accept-proposals` leaves it for a human, counted as `held-for-bi-demand`;
  - `--auto` withholds it from `not-business-data`, through the existing conflict
    mechanism;
  - the AI suggestion prompts are told a report depends on it.

  Matching is by name, ignoring case and separators. It is evidence for a reviewer,
  never a decision.
