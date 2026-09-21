### Fixed
- **A same-domain relationship proposal names the parent's source column again.** The
  join-column fix in 5.20.0 made `propose-relationships` emit the parent's *output* column
  for every proposal. That is right for a cross-domain join, where `join.foreign` must
  equal the `externalReference` key and the emitter uses it verbatim — and wrong for a
  same-domain one, where the compiler resolves `join.foreign` against the parent's
  *source* relation and rejects anything else with `safety.column-unresolved`, translating
  it to the output column itself. A same-domain proposal against a parent that renames its
  key on the way into Silver therefore could not be pasted: it named a column the compiler
  would not resolve. Measured on one hub, a proposal read `foreign: internal_location_id`
  where the only accepted value was `locid`.

  Both rules are now stated at the point of decision, each naming the diagnostic that
  enforces it, so the next reader does not have to rediscover that the two shapes differ.
  The existence check is unchanged and still applies to both: a parent key that reaches no
  output column at all is unjoinable whichever shape the join takes.
