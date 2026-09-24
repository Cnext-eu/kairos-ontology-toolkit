# How the context engineer and the data engineer work together

> **Audience:** the two people who build a hub — the context engineer, who owns what the
> business *means*, and the data engineer, who owns what the sources *deliver* — and whoever
> reviews their pull requests. This page is the workflow recommendation; the
> [context-engineer](context-engineer-methodology-guide.md) and
> [data-engineer](data-engineer-methodology-guide.md) guides are each role's method.

## The one fact the whole workflow rests on

**The ontology may run ahead of the sources. Growing it does not grow Silver. Only authoring an
EntityBinding grows Silver.** The Silver contract's entity set *is* the binding set; a class no
binding targets never enters the CompilePlan. So the Silver contract is, by construction, a subset
of the architecture — and the toolkit now makes that subset visible rather than merely true.

Two consequences follow, and they are the two halves of the handshake:

- The context engineer can carry the whole logical model into the ontology — bounded contexts,
  aggregates, concepts with no source yet — and nothing downstream changes until someone binds.
- The data engineer grows Silver one class at a time, and the architecture shows, on every run,
  which boxes are filled and why the others are not.

## Who owns what

| | Context engineer | Data engineer |
|---|---|---|
| **Owns** | discovery with the SMEs; the canonical ontology; the DDD layer (strategic file, per-domain overlays); the class ledger; decision records for modelling questions | source import; EntityBindings; contracted dbt; the Silver contract; the source-table ledger |
| **Authors** | `businessdiscovery/*`, `model/ontologies/<domain>.ttl`, `model/extensions/ddd-contexts-ext.ttl`, `model/extensions/<domain>-ddd-ext.ttl`, `integration/discovery/class-dispositions.yaml`, `decisions/HUB-DD-*` | `integration/sources/<system>/*.ttl`, `integration/bindings/*.yaml`, `integration/transforms/dbt/`, `model/contracts/<domain>.contract.yaml`, `integration/sources/_analysis/src-<system>.table-dispositions.yaml` |
| **Skills** | `kairos-design-discovery`, `kairos-design-domain`, `kairos-design-architecture` | `kairos-design-source`, `kairos-design-mapping`, `kairos-develop-dbt-transformation`, `kairos-execute-*` |
| **Reads back** | `architecture/ddd/contexts/*`, `ubiquitous-language.ttl`, `concept-guide.md`, `architecture/erd/*`, `design-landscape` | `concept-guide.md` (meaning, context, synonyms, invariants), `class-disposition list` (what not to bind), `fit-report`, `compile --explain`, the contract and Silver ERDs |

Both are interactive design skills: the toolkit proposes, a human decides, and every AI-approved
choice is recorded with its rationale (DD-088).

## The handshake, step by step

1. **Discover together.** The context engineer runs `kairos-design-discovery` with the SMEs;
   the glossary and the conformance record are the shared starting vocabulary.
2. **Design the domain.** The context engineer authors classes and properties with
   `kairos-design-domain`, including concepts the sources cannot feed yet. Every class gets a
   label and a business comment — that comment becomes the definition in the concept guide.
3. **Draw the architecture.** With `kairos-design-architecture`: contexts and the context map in
   the strategic file; per domain, each class's context, pattern, aggregate root, invariants,
   scope notes, synonyms and examples. A class with no source gets a recorded disposition
   (`architecture-only` or `deferred`) so it never reads as forgotten.
4. **Regenerate and review.** `validate --ddd` then `project --target ddd`. The context engineer
   reviews `contexts/*.mmd` and `concept-guide.md` with the SMEs; open questions become
   decision records; answers come back as overlay or ontology edits, never as edits to a
   generated file.
5. **Bind selectively.** The data engineer reads the class's entry in `concept-guide.md` first —
   scope, synonyms, invariants — then binds with `kairos-design-mapping`. A class recorded as
   `architecture-only` or `deferred` is not a binding target until the context engineer
   withdraws that disposition. Binding a class flips its ledger status to `bound` automatically.
6. **Declare the contract together.** When a domain's Silver is stable enough to promise, the
   two agree the `<domain>.contract.yaml`; the context diagrams and the concept guide then mark
   those classes *in Silver contract*.
7. **Repeat.** Each pass leaves the architecture larger than Silver and the difference written
   down.

## Escalations, and where each one goes

| Situation | Route |
|---|---|
| The data engineer needs a class or property the model lacks | `kairos-design-domain` change by the context engineer — never a `purpose: carried` column that looks canonical and is not |
| A binding cannot express what the source holds (composite keys, value objects) | `kairos-develop-dbt-transformation`, and a decision record if the shape is a modelling question |
| The architecture wants a boundary Silver does not want (Address as its own context, physically in `party`) | Annotate with `boundedContext`; do **not** move the class. Move only on a physical trigger: a second source, its own release cadence, an unreviewable host file |
| An invariant should be enforced, not just documented | A SHACL shape in `model/shapes/` (validate time) or a `DataQualityRule` in the binding (runtime); the overlay keeps the prose |
| A class the architecture placed is now bound but its disposition still says `deferred` | `validate` reports `class-disposition.stale`; the context engineer clears it |
| Two overlays disagree about a context's label or a class's context | `validate --ddd` fails (`ddd.context-label-conflict`, `ddd.class-in-two-contexts`); resolve in the strategic file |

## What each stage leaves behind

| Stage | Owner | Authored | Generated, reviewed in the pull request |
|---|---|---|---|
| Discover | context engineer + SMEs | extractions, conformance judgments | `<company>-glossary.ttl`, conformance report |
| Design domain | context engineer | `<domain>.ttl`, class dispositions | `architecture/erd/*`, `architecture/ddd/ubiquitous-language.ttl`, `architecture/ddd/concept-guide.md` |
| Design architecture | context engineer | strategic file, `<domain>-ddd-ext.ttl` | `architecture/ddd/contexts/*`, `<domain>-ddd-report.md` |
| Import and bind | data engineer | source TTL, bindings, table dispositions | `compile --explain`, fit reports, Silver ERD; the concept guide gains source names and Silver status |
| Contract | both | `<domain>.contract.yaml` | `model/contracts/diagrams/*-contract-erd.mmd`; diagrams and guide mark *in Silver contract* |

Everything generated under `ontology-hub-publish/architecture/**` and
`ontology-hub/model/contracts/diagrams/` is tracked and regenerated by the drift gate: a reviewer
sees the architecture change in the diff, and a stale diagram fails CI rather than misleading
anyone. `git add` new generated files with the change; the gate does not see untracked additions.

## What the toolkit enforces, and what it only proposes

- **Enforced by `validate`:** the overlay rules and the cross-file audit (`--ddd`); undecided
  hub classes once the class ledger is adopted (warnings before); undecided source tables
  (DD-164); the DDD firewall — no `kairos-ext:silver*`/`gold*` in an overlay.
- **Enforced by the drift gate:** every tracked diagram and document is byte-identical to a fresh
  regeneration.
- **Proposed by `kairos-ontology next` / `kairos-flow`:** `design-architecture` when an overlay
  or the strategic file exists; `record-class-disposition` when hub classes have no recorded
  outcome; the usual design, bind, validate and compile actions.
- **Never automated:** where a boundary sits, which subdomain is core, whether a concept belongs
  to the business at all. Those are the context engineer's calls, with the SMEs.
