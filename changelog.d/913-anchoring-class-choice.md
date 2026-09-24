### Changed
- **Anchoring reads the accelerator's canonical class registry (#913).** When two
  reference classes share a name (`bsp/commercial#TransportLeg`,
  `mmt/consignment#TransportLeg`) and the table's columns do not separate them,
  `anchor-tables` now prefers the copy the pack's
  `current/blueprint/canonical-class-registry.yaml` names as canonical. On one hub the
  wrong copy was chosen, and 33 extension properties were then authored onto it.
  - A table's own columns still take precedence over the registry: they are direct
    evidence about this table.
  - For a duplicated name, the anchor file now records `anchor_copy_basis`, the rule that
    picked the copy.
  - The design skills now say to read the blueprint dossier (canonical registry, overlap
    register, source-shape stress cases) before re-deriving its judgement.
  - A pack without a dossier behaves exactly as before.
- **An abstract class shared by unrelated tables is named as such (#927).** Several code
  lists in one source can legitimately anchor to an abstract "code list element" class.
  The compile gate then demanded a conformance group, which would union unrelated lists
  at different grains. Now:
  - `anchor-tables` reports tables of one system on one class with different key arity,
    and suggests a hub-local subclass per table.
  - When the bindings' keys differ in arity, `conformance.group-required` says the same
    instead of pointing only at conformance.
- **`import-tmdl` proposes `reference_model_match` against the hub's activated modules
  (#863),** the same scope `design-landscape` resolves in. Names duplicated elsewhere in
  the catalog (Shipment, Terminal, Contact) are no longer withheld as ties when only one
  copy is activated. `design-landscape` also accepts `module:Class` in the worksheet
  (`consignment:TransportLeg`), so a genuine tie can be settled by the modeller.
