### Added
- **`kairos-design-architecture`, the context engineer's skill.** Author the strategic file and
  the per-domain overlays (contexts, context map, aggregates, invariants, scope notes, synonyms,
  examples), record why a class is deliberately not in Silver, validate with `--ddd`, regenerate
  the context diagrams, the ubiquitous language and the concept guide, and review them with the
  SMEs. Shipped to every hub. `kairos-ontology next` / `kairos-flow` route two new actions to it:
  `design-architecture` (optional, when an overlay or the strategic file exists) and
  `record-class-disposition` (a human call per undecided hub class; blocking once the class
  ledger is adopted). `next` schema version 8.

### Documentation
- **The workflow between the context engineer and the data engineer is written down.** New
  practitioner page *How the context engineer and the data engineer work together* (ownership,
  the handshake step by step, escalation routes, what each stage leaves behind, what the toolkit
  enforces versus proposes), with matching sections in the context-engineer and data-engineer
  methodology guides.
- **New how-to, shipped to hubs:** *Document the architecture with a DDD overlay* — the subset
  invariant, the two kinds of file, "annotate, do not move", the overlay rules, the class ledger,
  the generated artifacts, the Lucid rule, and how to carry an external logical model.
- `kairos-help`, `kairos-flow`, `kairos-execute-validate`, `kairos-execute-project`,
  `kairos-design-domain` and `kairos-design-mapping` now name the architecture layer where it
  touches them; the user guide lists the DDD files and the class ledger among the authored
  inputs; *Design a domain* gains a "What you get" section.
