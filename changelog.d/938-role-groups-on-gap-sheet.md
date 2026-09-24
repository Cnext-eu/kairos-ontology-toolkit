### Changed
- **Role groups reach the gap-decision sheet, with the governing pattern named (#938).**
  A table carrying three party roles as flattened columns (consignee, shipper, notify:
  name, street, city, zip, …) was ruled one column name at a time. On one hub 78 such
  columns ended up `deferred`, and no command mentioned that
  `blueprints/patterns/qualified-role-assignment` is normative for exactly that shape.
  - `propose-alignment` already detected the role groups for its prompt. It now keeps
    them: the alignment file records `role_groups` per table, and each unmapped member
    carries its `role_group`.
  - On the sheet, such a name or family carries `role_groups` and
    `governing_pattern: blueprints/patterns/qualified-role-assignment`, and its reasoning
    says to model the party once and link it through the module's role-assignment class,
    rather than deciding each attribute on its own.
  - Tables without role groups produce exactly the same files as before.
