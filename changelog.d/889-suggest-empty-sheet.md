### Fixed
- **`draft-gap-decisions --suggest` no longer crashes on a hub whose gap gate is fully
  closed.** Its early-exit path returned a narrower dict than its success path, and the
  CLI read both keys, so the command raised `KeyError: 'flagged_incoherent'` exactly when
  there was nothing left to suggest — that is, when every gap column had been decided and
  the DD-169 gate was satisfied. It now reports "no families left to describe — every gap
  column is decided".
