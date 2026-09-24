### Added
- **`owl:deprecated` in the reference models is now read, and reported where a hub builds
  on it (#938).** The reference models mark the role subclasses a normative pattern
  forbids (`Consignee`, `Carrier`, `NotifyParty`, … — 14 in one party module)
  `owl:deprecated true`, and name the replacement in the class comment. Until now the
  only protection was a hardcoded list of seven URIs, so a hub could anchor, subclass or
  bind to one of these classes and see no warning anywhere. Three warnings, all quoting
  the class's own comment:
  - `anchor-tables`: a `deprecated_anchor` note and a `deprecated-anchor` flag on the
    table.
  - `compile`: `binding.target-class-deprecated` when a binding targets a deprecated
    class or a subclass of one.
  - `validate`: `integrity.deprecated-reference-class` when a hub class subclasses, or a
    property's domain or range names, a deprecated class.

  Each points at `blueprints/patterns/qualified-role-assignment`: build on the durable
  identity class and assign the role instead. None of the three blocks.
