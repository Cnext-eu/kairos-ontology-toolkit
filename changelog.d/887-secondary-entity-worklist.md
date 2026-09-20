### Fixed
- **A column the aligner put on another class is now reported as a decision, not counted
  as a missing property.** `generate-bindings` resolves properties against the anchor
  class's own inventory, so a column mapped to `Weight.weightValue` on a table anchored
  to `CargoItem` failed that lookup and was counted under "did not resolve in the anchor's
  module inventory" — the same bucket as a property that does not exist anywhere. On one
  real hub that was 18 of 25 mapped columns, silently absent from the binding and
  indistinguishable from a lookup failure. Binding them onto the anchor would have been
  worse: putting a weight value on a cargo-item row is a grain error dressed as coverage,
  and DD-190 is explicit that a same-grain cluster is properties of the primary. They now
  land on the secondary-entity worklist with the decision spelled out — a secondary entity
  at its own grain, or a hub-local property on the anchor — and the command says they are
  not in the binding.
- **`registered-extension`'s own documentation no longer points at a command that cannot
  serve it.** It named `register-concept`, which mints a *class* and rejects a URI the
  catalog already has; at column grain the decision is a hub-local *property* on an
  existing class, drafted by `scaffold-extensions`. Pointing at the wrong command is what
  left 501 such decisions with no consumer.
