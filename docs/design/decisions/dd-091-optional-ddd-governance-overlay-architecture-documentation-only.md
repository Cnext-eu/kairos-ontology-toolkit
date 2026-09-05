# DD-091: Optional DDD governance overlay (architecture documentation only)

**Status:** Accepted
**Date:** 2026-07-05
**Affects:** `src/kairos_ontology/scaffold/kairos-ddd.ttl`,
`src/kairos_ontology/scaffold/kairos-ddd-shapes.shacl.ttl`,
`src/kairos_ontology/ddd.py`,
`src/kairos_ontology/projections/ddd_projector.py`, `projector.py`
(`ddd` target), `cli/main.py` (`project --target ddd`, `validate --ddd`),
`tests/scenarios/acme-hub/model/extensions/*-ddd-ext.ttl`, `kairos-help` skill
**Implementation:** `kairos-ontology validate --ddd`,
`kairos-ontology project --target ddd`

### Context

Teams applying Domain-Driven Design want to record strategic (bounded contexts,
context maps) and tactical (aggregate roots, value objects, domain events)
design intent alongside the domain ontology. The core ontologies must stay
focused on durable business semantics (R1), and data governance — ownership,
approval, disposition, materialization, certification — already lives
authoritatively in the claim registry (R2). Silver/gold projection controls
already live in the `kairos-ext:` extension model (R3). A DDD overlay must be
purely additive design metadata, not a second governance source.

### Decision

Introduce an **optional, additive DDD design overlay** expressed in
`*-ddd-ext.ttl` files under `model/extensions/`, driven by a new managed
vocabulary `kairos-ddd` (namespace `https://kairos.cnext.eu/ddd#`). The overlay
uses typed RDF resources and controlled individuals (not raw strings) for
bounded contexts, tactical patterns, and context-map relationships (R5, R6).

- **Validation** runs through a dedicated path (`validate --ddd`, and as part of
  `validate --all`) that discovers `*-ddd-ext.ttl`, merges each overlay with its
  matching domain ontology plus the packaged `kairos-ddd` vocabulary, and applies
  DDD SHACL shapes (R7). Hubs with no overlay pass with DDD marked not-applicable
  (R4). The shapes reject silver/gold projection predicates inside an overlay to
  keep concerns separate.
- **Projection** adds a one-way documentation target `ddd` that writes Mermaid
  context maps, aggregate overviews, and a Markdown report to
  `output/architecture/ddd/`. It never changes silver, gold, dbt, or Power BI
  output (R8). XMI / Enterprise Architect round-trip is explicitly out of scope
  for the MVP.
- **Packaging:** the vocabulary and shapes are bundled with the package (the
  validator/projector load them from the installed package, so existing hubs work
  without a hub-local copy) and are also shipped in `scaffold/` for new hubs
  (R10). Consistent with the existing `kairos-ext` / `kairos-bronze` / `kairos-map`
  vocabularies, the DDD vocabulary is merged by file path rather than resolved via
  `owl:imports`/XML catalog, so no catalog entry is required.

### Rationale

Keeping the overlay optional and documentation-only preserves the claim registry
as the single governance authority and the `kairos-ext` extensions as the single
projection-control authority, avoiding a competing metadata source. Typed
resources and controlled individuals give context maps enough structure to render
deterministically and let SHACL validate controlled values. Loading vocabulary
and shapes from the package (not the hub) means the feature validates correctly
in hubs that predate it, while scaffold copies keep new hubs self-describing.

### Consequences

- New optional lifecycle step: `discovery → source → domain/claims → optional DDD
  overlay → mapping → silver → gold → validate → project/report`.
- `validate --all` now also runs the DDD path (skipped/not-applicable when no
  overlay exists), and `project --target ddd` is available.
- A DDD overlay that leaks `kairos-ext:silver*`/`gold*` predicates fails
  validation, enforcing the governance/design separation.
- One-way XMI/EA export is deferred to a future, separately-accepted DD.
