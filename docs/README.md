# Documentation

## Current v5 guidance

| Document | Purpose |
|---|---|
| [User guide](USER_GUIDE.md) | Authoring, stateless compile, adapters, and clean cutover |
| [CLI reference](CLI_REFERENCE.md) | Exact retained command surface and compiler modes |
| [CompilePlan consumption](CONSUMING_COMPILE_PLAN.md) | Dataplatform, Gold, and MDM consumption |
| [Logging & observability](OBSERVABILITY.md) | Verbosity flags, JSON logs, optional OpenTelemetry bridge (DD-151) |
| [Architecture](design/ontology-dbt-dataplatform-design-architecture.md) | The system as it stands: boundaries, release safety, governance |
| [Roadmap](design/roadmap.md) | What is *not* built yet; phased plan |
| [DD-133](design/dd-133-v5-entity-binding-compile.md) | Normative EntityBinding/compiler contract |
| [Design decisions](design/toolkit-design-decisions.md) | Status index; one file per decision under [`design/decisions/`](design/decisions/) |
| [Releasing](RELEASING.md) | Maintainer publication process; not evidence of a published release |

The active architecture is the lean v5 hub: ontology/source TTL, one closed EntityBinding
per source, optional ordinary contracted dbt SQL/YAML, optional Gold/MDM policy, and derived
output. Historical claim, preparation, Silver-extension, lifecycle/readiness, and release
orchestration decisions are retained only as labeled records in the ADR log.

## Other maintained material

- [MDM documentation](mdm/)
- [Practitioner guides](instruction-guides/)
- [Demo](demo/)

## Historical material

- [`design/dd-014-architecture.md`](design/dd-014-architecture.md) describes the retired v4
  medallion lane and is kept as provenance, not guidance.
- Superseded decisions stay in [`design/decisions/`](design/decisions/) with a
  `~~Superseded by DD-XXX~~` status rather than being deleted.

When historical text conflicts with the current documents above, DD-133 and the implemented
compiler behavior take precedence.
