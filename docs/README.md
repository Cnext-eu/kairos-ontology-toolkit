# Documentation

Two audiences, two folders.

- **[`guide/`](guide/)** — how to *operate* a hub. Describes the toolkit as built. This is
  the set shipped into every scaffolded hub under `docs/toolkit/` and refreshed by
  `kairos-ontology update` (#739), so a hub operator has it locally without needing access
  to this repository.
- **[`dev/`](dev/)** — how the toolkit is *built*: the decisions behind it, the normative
  contracts, and the maintainer process. Stays here.

If you are deciding where a new document belongs: would a client hub operator who never
reads this repository need it? If yes, `guide/`. If it explains why the toolkit is the way
it is, `dev/`.

## guide/ — using the toolkit

| Document | Purpose |
|---|---|
| [User guide](guide/USER_GUIDE.md) | Authoring, stateless compile, adapters, and clean cutover |
| [How-to guides](guide/how-to/README.md) | Task recipes: create a hub, import a source, bind an entity, compile, consume downstream |
| [CLI reference](guide/CLI_REFERENCE.md) | Every command, generated from the command tree |
| [CompilePlan consumption](guide/CONSUMING_COMPILE_PLAN.md) | Dataplatform, Gold, and MDM consumption |
| [Logging & observability](guide/OBSERVABILITY.md) | Verbosity flags, JSON logs, optional OpenTelemetry bridge (DD-151) |
| [Demonstration guide](guide/demo.md) | A 45-minute walkthrough of the v5 contract |
| [Practitioner guides](guide/practitioner/) | Context-engineer and data-engineer methodology |

The first four are the ones shipped to hubs; the allowlist lives in
`scripts/sync_dev_skills.py`.

## dev/ — building the toolkit

| Document | Purpose |
|---|---|
| [Design decisions](dev/toolkit-design-decisions.md) | Status index; one file per decision under [`dev/decisions/`](dev/decisions/) |
| [Architecture](dev/ontology-dbt-dataplatform-design-architecture.md) | The system as it stands: boundaries, release safety, governance |
| [DD-133](dev/decisions/dd-133-v5-authoring-break--yaml-entitybinding--stateless-compile-companion.md) | Normative EntityBinding/compiler contract |
| [Diagnostic codes](dev/diagnostic-codes.md) | Every compile diagnostic, its severity and rule |
| [CLI behaviour notes](dev/cli-behaviour-notes.md) | Why particular commands behave as they do |
| [Quality policies](dev/quality-policies.md) | Safety-kernel and quality-rule reference |
| [Roadmap](dev/roadmap.md) | What is *not* built yet; phased plan |
| [Releasing](dev/RELEASING.md) | Maintainer publication process |
| [`dev/mdm/`](dev/mdm/) | Design material for a capability that is **not live** |

### The decision log has two tiers

`dev/decisions/dd-NNN-<slug>.md` is the record: status, date, what it affects, and why.
Some decisions also carry `dd-NNN-<slug>-companion.md` beside them — a longer document
working through the design in depth. The ADR is authoritative; the companion is background.

`dev/decisions/` is generated and split by `scripts/split_decision_log.py`; the index is
kept consistent by `tests/test_design_decisions_consistency.py`.

## A note on `docs/temp/`

`docs/temp/` is gitignored scratch space. Nothing tracked may link into it — those links
resolve only on the machine that wrote them, and
`tests/test_design_decisions_consistency.py` fails if one appears.
