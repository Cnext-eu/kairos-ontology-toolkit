### Added
- **`project --target erd` now writes a hub-wide `master-class-diagram.mmd` (issue #753).**
  The bound Silver and Gold ERD families already merge their per-domain diagrams into a
  master; the canonical target did not, so reading the whole canonical surface meant
  opening every domain file and holding them in your head.

  A class drawn by several domains appears once. That is the actual work: an imported class
  is drawn in *every* domain that reaches it, so naive concatenation emits the same block
  repeatedly. The owning domain's drawing wins — in a per-domain diagram a stereotype marks
  a class as imported *from that domain's view*, but in the merged hub-wide diagram every
  domain is local, so the importer's stereotype would be misleading.

  It is merged from the files the same run just wrote, so the master can never disagree
  with them, and the drift gate already regenerates it (`project --target erd`, added with
  #774).

### Notes
- `medallion_silver_projector.generate_master_erd` is deliberately **not** reused: it emits
  and merges `erDiagram` bodies while this target emits `classDiagram`, so feeding one into
  the other produces a file Mermaid cannot parse. Its cross-domain block is also synthesised
  from `*-silver-constraints.json`, which is compile-plan-derived, while this target is
  binding-independent by construction (DD-209).
- The SVG half of #753 is **declined**, per DD-211 — see the issue for the reasoning.
