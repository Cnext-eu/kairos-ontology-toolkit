### Fixed
- **`anchor-tables` no longer routes a table to the alphabetically first owner of its
  anchor.** When several domains own the anchor class's module and affinity names none of
  them, the first owner won, which meant the domain id that sorts first. In the logistics
  pack that sent every table anchored to a OneRecord `cargo` class (Address, Company, Person,
  CodeListElement, …) to `booking`, overloading its alignment pool. The tie is now broken on
  evidence (DD-247):
  1. a hub domain whose ontology subclasses the anchor (`domain_basis: hub-subclass`);
  2. otherwise one of the table's affinity `secondary_domains` that is an owner
     (`owner+secondary`);
  3. otherwise the first owner is kept, flagged `owner-ambiguous` and listed in the run
     output, so the choice can be ruled on by editing the row (`status: edited`).

  A single owner still wins over affinity, as before (#1040).

### Decisions
- **DD-247: a shared-owner tie is broken on evidence, not on domain order.**
