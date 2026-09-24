### Fixed
- **`build-glossary` no longer destroys a hand-authored glossary (#906).** It used to
  overwrite the target file with whatever the extractions produced. With no extractions
  yet, that was an empty glossary, reported with a green check. With extractions, it
  replaced the file instead of merging: on one hub, 37 of 52 hand-written terms were
  lost. Now:
  - It refuses to write when the build yields no concepts and the file already holds
    some. `--allow-empty` overrides this; it is a registered gate escape, for humans only.
  - A concept a person wrote is carried over and marked (`dcterms:provenance`), so every
    later rebuild keeps it too.
  - Where a hand-written concept and a generated one share an IRI, the hand-written one
    wins.
  - The command reports how many hand-written concepts it kept.
- **`validate` reports staged business evidence on a hub with no domain ontology yet
  (#903).** The DD-233 check sat inside the ontology-validation block, so it said nothing
  in the one state it was written for: sources imported, nothing modelled yet. It now
  always runs.
- **The engineering pack's cross-check note no longer runs into the next heading
  (#905).**
- **The glossary gate declares the evidence it actually reads.** It listed
  `businessdiscovery/glossary/*.ttl`; the check reads `businessdiscovery/*.ttl`.

### Changed
- **A handled model-parameter rejection now says it was handled (#911).** When a model
  rejects a parameter such as `temperature`, the toolkit drops or weakens it and retries.
  The only visible output used to be the provider's bare `Error code: 400`, repeated once
  per parallel call, which read as four failures. Now one line per model and parameter
  says the rejection was handled.
- **The scaffolded `release-projections.yml` recognises every pre-release tag spelling
  (#864).** Its pattern missed a bare `…rc` and the PEP 440 forms (`1.0.0b1`, `1.0.0a1`),
  which were published as full releases. `update --refresh-workflows` delivers the fix.
  The previous generation is registered as superseded, so an unmodified copy is replaced.
