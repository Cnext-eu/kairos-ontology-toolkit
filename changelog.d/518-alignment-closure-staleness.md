### Added
- **An alignment artifact stale against its domain's import closure is now reported (issue
  #518).** `<domain>-alignment.yaml` recorded the `domain_uris` it was generated against
  and nothing ever compared them to anything, so a reference-models upgrade, blueprint
  change or added bridge left the file silently stale while downstream stages consumed it
  as current.

  The failure was invisible *and pointed the wrong way*: what surfaced was
  `integrity.managed-import-unused` — "this domain imports a module and references nothing
  from it" — which reads as a **sourcing** gap when the cause is a **staleness** gap. On a
  hub using those warnings as a sourcing backlog (DD-187), a stale file corrupts the
  backlog.

  `design-landscape` now names the modules added or removed since the alignment was
  generated, and says explicitly that an unused-import finding for an added module is
  staleness rather than missing data. Artifacts carry a `closure_sha256` fingerprint so
  the comparison has something durable to stand on.

### Notes
- Deliberately quiet where it cannot be sure: an unreadable artifact, one predating the
  fingerprint, or a closure that resolves to nothing is **not** reported as stale. This
  warns about a real difference; guessing would train readers to ignore it.
- The issue's third suggestion — having `integrity.managed-import-unused` itself
  distinguish "the alignment covered this module" from "the alignment never saw it" — is
  not done here, but the fingerprint it needs now exists.
