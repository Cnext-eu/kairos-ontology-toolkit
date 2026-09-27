### Fixed
- **`anchor-tables` routes a bound table to its EntityBinding's domain, unless the row is
  pinned (#1048, DD-249).** DD-247's routing (affinity, hub subclass, secondary affinity,
  first owner) never looked at the bindings a hub had already authored, so tables such as
  `cargowise.glbcompany` were anchored to a domain their binding contradicts. The
  precedence is now pin > binding > the DD-247 chain. An unpinned row read by bindings in
  one domain takes that domain (`domain_basis: binding`); several domains keep the
  chain's choice when it is one of them, and otherwise flag the row `binding-ambiguous`.
  A pinned (`confirmed`/`edited`) or `--only-new`-kept row is never changed; when its
  binding disagrees, the run warns (`cargowise.glbstaff: pinned to party, bound in
  fracht-company (cargowise-fracht-staff-member.binding.yaml)`). A binding's `dbtModel`
  counts the tables its SQL reads, but the walk stops at a model another binding selects,
  so a merge model that joins another entity in does not claim that entity's tables. New
  `load_binding_owners` in `core.source_disposition`.
- **`generate-bindings` no longer drafts a duplicate binding for a table another binding
  already reads.** The old guard only saw the generator's own
  `<system>-<table>-to-<domain>` file name, which most hand-authored bindings do not use.
  Such a table is now skipped with `already bound by <file>`, also under `--force`; the
  generator's own earlier draft still regenerates under `--force`.
