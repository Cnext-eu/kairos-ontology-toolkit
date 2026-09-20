### Changed
- **`source-disposition set` now says what a table-grain decision just retired.** A
  disposition recorded against a whole table removes every one of its gap columns from
  the DD-169 pre-binding gate, permanently — and the command said only
  `✓ <table> recorded as 'deferred'`. The cascade appeared in one place, the help text
  for the `--column` flag, phrased as a convenience rather than a consequence, which
  nobody recording forty tables ever reads. Recording a disposition now reports the real
  column count: informational for `not-business-data` and `blueprint-gap`, where
  retiring the columns is the point, and a warning for the rest — `deferred` means "in
  scope, not modelled yet", which is precisely the state the gate exists to keep raising,
  and it had the widest blast radius of any option while sounding the mildest. Disposing
  of a table alignment has never covered warns too, because that decision answers for
  columns nothing has yet looked at. The `--disposition` help text spells out which
  values cascade and why.
