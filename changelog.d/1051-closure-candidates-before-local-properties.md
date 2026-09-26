### Fixed
- **The gap pipeline no longer drafts a hub-local property for a column whose property
  already exists in the import closure (#1051, DD-248).** The aligner sees a bounded pool,
  so a column whose property sat past the cut was reported as `no-reference-property` and
  `draft-gap-decisions` drafted `registered-extension` for it; on a 15-domain hub that was
  204 of 223 open names. Every custom column is now looked up deterministically against
  the whole closure after the model answers. A hit is recorded on the column as
  `closure_candidates`, `alignment-report` counts it under the new reason
  `closure-candidate-not-shown` (a gap reason, listed first), the gap sheet proposes
  nothing for it and names the candidates, `--suggest` shows them to the model and forbids
  `registered-extension` without a stated reason, and `--accept-proposals` holds such
  entries for a human (`held-for-closure-candidate`). Two shortlist defects fixed on the
  way: the class scorer now sees every property, not the first 60, and the DD-244
  disclosure line now counts the classes the shortlist cut as well as the properties.
  `ALIGNMENT_POOL_CONTRACT` is 4, so recorded alignments re-run once after upgrading.

### Added
- **`core.closure_lookup`**, the one deterministic name-to-closure matcher (exact, or a
  token-subset near match; generic names such as `code` match exactly only), shared by
  alignment and the gap sheet now and by `validate`, `scaffold-extensions` and `find-term`
  in the follow-up PRs.
