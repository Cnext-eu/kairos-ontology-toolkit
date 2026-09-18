### Fixed
- **Two classes sharing a local name no longer collide on one ERD node (issue #806).**
  `project --target erd` derived every Mermaid node id from the class's local name alone,
  so two distinct IRIs with the same fragment became the same node. The canonical case is
  the modelling style `kairos-design-domain` recommends — a local subclass named after the
  reference-model class it specialises — which rendered two `class SeaLeg` blocks that
  Mermaid merged, plus an inheritance edge from the node to itself, making the diagram
  assert something the ontology does not. A contested name now takes the source-model
  label as a suffix (`SeaLeg_imo_port_call`); a name claimed by one class is untouched, so
  existing tracked diagrams stay byte-identical.
