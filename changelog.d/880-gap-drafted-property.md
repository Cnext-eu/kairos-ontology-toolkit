### Fixed
- **The gap decision sheet now shows the extension property alignment already drafted,
  and proposes registering it.** `propose-alignment` drafts a full hub-local property —
  name, range, owning class and rationale — for every column it cannot map.
  `draft-gap-decisions` read those proposals under the wrong key (`suggested_property`,
  which belongs to a sibling field, rather than `name`), so the list came back empty for
  every group and the drafted property never reached the sheet. A reviewer therefore
  faced a blank `decision:` with no proposal, while the answer sat in the alignment file
  next door. On a five-domain hub slice that was 371 of 373 entries with no proposal at
  all; it is now 188, with 183 drafted as `registered-extension` and the property spelled
  out in the reasoning. Where the aligner read the same column name differently in
  different tables, both readings are shown and the entry says to pick one — never
  averaged. A proposal is still never a decision: `decision` stays empty, and the
  existing rule branches (JSON blob, free text, recurring identifier) keep precedence
  over the extension proposal while still showing what was drafted.
