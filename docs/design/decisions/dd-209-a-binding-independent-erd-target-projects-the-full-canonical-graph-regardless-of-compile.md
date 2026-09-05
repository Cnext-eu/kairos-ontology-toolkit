# DD-209: A binding-independent `erd` target projects the full canonical graph regardless of compile-plan coverage

**Status:** Accepted
**Date:** 2026-08-29
**Affects:** new `core/projections/erd_projector.py`, `core/projector.py` (new `TargetSpec("erd",
"architecture/erd", ...)`), CLI `projection_target_choices()`, new `tests/test_erd_projector.py`

### Context

Every existing `project --target` output is either a compile-plan projection (`dbt`, `silver`,
`gold`/`powerbi`, `mdm-profile` — visible only for classes actually bound via an `EntityBinding`) or,
for `ddd`, a graph projection gated by explicit DDD-overlay vocabulary (`DDD.BoundedContext`,
`tacticalPattern`, `aggregateRoot`, etc. — `_has_content()` in `ddd_projector.py`). No target renders
a general class/relationship ERD straight off the ontology graph for a class or relationship that has
no binding and no DDD annotation, so the canonical model's actual shape — including everything not yet
bound to a source — is invisible in every diagram-like output (issue #631).

### Decision

Add `core/projections/erd_projector.py`, sitting alongside `ddd_projector.py` in shape and contract:
deterministic, sorted output, no `CompilePlan`/`EntityBinding` dependency. It receives the same
already-loaded graph the rest of the per-domain projection loop already produces via
`ontology_loader.load_ontology` (the `run_projections` orchestrator loads each domain once and hands
every target the same graph -- ``ddd_projector.py`` follows the identical contract, no target
re-loads its own copy), walks `owl:Class`/`owl:ObjectProperty` directly, resolves relationship
endpoints from `rdfs:domain`/`rdfs:range` (via `effective_domain_classes`, the DD-131 multi-class
domain-resolution authority the silver/dbt projectors already share), reads
`owl:Restriction`/`owl:cardinality`/`owl:minCardinality`/`owl:maxCardinality` where present, and emits
one Mermaid `erDiagram` per domain. It is registered as `TargetSpec("erd", "architecture/erd",
OutputCategory.ARCHITECTURE, ...)` — mirroring `ddd`'s `architecture/ddd` placement — and, because
`projection_target_choices()`/`projection_targets_for_all()` already derive purely from the target
registry, requires no separate CLI wiring: `--target erd` and `--target all` both work as soon as the
`TargetSpec` is registered.

### Consequences

A class or relationship modeled in the ontology but never bound to a source is now visible in at
least one diagram output. `erd` never influences `silver`/`gold`/`dbt`/Power BI generation, the same
non-interference guarantee `ddd` already provides. The new target adds one more entry to every
`--target all` run's output.
