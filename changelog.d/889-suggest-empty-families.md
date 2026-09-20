### Fixed
- **`draft-gap-decisions --suggest` no longer crashes with `KeyError: 'flagged_incoherent'` when all gap columns are decided (#889).**
  `suggest_family_dispositions` returned a narrower dict without `flagged_incoherent` on its early-return
  path for an empty sheet. The early return now carries the full stats shape, the CLI reads
  `flagged_incoherent` defensively with `.get()`, and reports `🧠 no families left to describe — every gap column is decided`
  instead of failing at the DD-169 success state.
