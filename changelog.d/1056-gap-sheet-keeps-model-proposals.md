### Fixed
- **A `draft-gap-decisions --suggest` proposal now survives a later rebuild of the gap
  sheet (#1056).** Every rebuild (a plain run, `--accept-proposals`) redrew each entry's
  proposal from the name rules and kept only `decision`, so the model's proposals and
  reasoning were paid for and then silently replaced, and `--accept-proposals` accepted
  the rule's drafts instead. A model answer is now stamped `proposed_by: model` with an
  `evidence` fingerprint of what it was answered from (closure candidates, Power BI
  demand, drafted properties and data types; for a family its members, BI members and
  candidates). A rebuild carries `proposed_disposition`, `reasoning`, `coherent`,
  `proposed_by` and `evidence` while the fingerprint still matches, and drops them the
  moment the evidence moves (a new closure candidate, say), so the rule's draft stands.
  `decided_by` now travels with a carried `decision`. A re-run of `--suggest` does not
  re-ask a name whose answer is still current.
- **`--accept-proposals --dry-run` is dry.** It wrote the sheet before accepting and
  counted only the decisions already on disk; it now accepts in memory, writes neither the
  sheet nor the ledger, and reports the full would-apply count.
- **`--suggest` is no longer silently dropped.** Combined with `--auto` or
  `--accept-proposals` it is a usage error naming the two-step flow (`--suggest`, read the
  sheet, then `--accept-proposals`); with `--dry-run` it prints each model proposal
  instead of discarding the answers it paid for.

### Changed
- **`--accept-proposals` holds every undecided entry with closure candidates (#1057,
  DD-248).** Before, an entry whose proposal was `deferred` or `blueprint-gap` was
  accepted over a candidate; now any candidate holds it (`held-for-closure-candidate`),
  whatever its score and whatever the rule or the model proposed. Expect a higher held
  count on hubs with weak candidates; they stay visible on the entry for the reviewer.
