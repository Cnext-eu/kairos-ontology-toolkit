### Added
- **`scaffold-extensions` renders the accepted `registered-extension` decisions as draft
  OWL.** Closing the DD-169 gate honestly is expensive — on one hub, 701 column-grain
  decisions, 501 of them accepting a hub-local property the aligner had already drafted
  in full — and nothing consumed them. The disposition's own definition points at
  `register-concept`, which registers a *class* the archetype catalog lacks, while these
  are *columns* wanting *properties* on classes that already exist, so the properties had
  to be re-derived by hand from a second file. The new command writes what the ledger
  already records: name, range, owning class and rationale, one declaration per property,
  grouped by class. It makes no judgement of its own. Output is a DRAFT written outside
  `model/ontologies/` so the validator does not load it, the same contract
  `suggest-shapes` uses (DD-076). A non-datatype range, a non-camelCase name, or one name
  accepted with two different class or range readings is reported and skipped rather than
  guessed, and no source-system, table or column name reaches an `rdfs:comment`, which
  `validate --syntax` rejects.
