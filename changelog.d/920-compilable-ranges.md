### Fixed
- **A hub-local property can no longer be proposed with a type the compiler cannot emit.**
  `propose-alignment` asked the model for `"range": "<xsd type or class name>"` with no
  constraint, so it reasonably proposed `xsd:duration` for a duration column. That was
  accepted into the disposition ledger, rendered into the domain ontology by
  `scaffold-extensions`, passed `validate` clean, and failed three stages later at
  `compile` with `mapping.invalid-output-type` — after a human had already accepted it.

  The prompt now names the fifteen datatype ranges the compiler can emit and says to
  express a duration as a number with its unit in the rationale.

  `scaffold-extensions`' allow-list was hand-maintained beside the compiler's own XSD
  table and had drifted from it in both directions: it permitted `xsd:duration`, which has
  no canonical output type, and omitted `xsd:int`, `xsd:short`, `xsd:token` and
  `xsd:normalizedString`, which the compiler supports. It is now derived from that table,
  so the two cannot disagree, and a datatype the compiler cannot emit is reported as its
  own skip reason — distinct from a non-datatype range, and differently actionable: the
  modelling is fine, the type is not buildable.
