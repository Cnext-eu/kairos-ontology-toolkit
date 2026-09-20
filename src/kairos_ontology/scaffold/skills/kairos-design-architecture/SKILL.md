---
name: kairos-design-architecture
description: >
  Author strategic and tactical DDD design over the canonical ontology — bounded contexts,
  the context map, aggregates, invariants, the ubiquitous language — as documentation that
  never changes Silver, and record why a class is deliberately not bound.
---

# Kairos Architecture Design (the context engineer's skill)

The ontology may run ahead of the sources. Growing it does not grow Silver; only authoring
an EntityBinding grows Silver (the contract's entity set *is* the binding set). This skill
owns the layer that makes a larger, deliberately-designed ontology legible: bounded
contexts, the context map, aggregates and their invariants, the language the business uses,
and the ledger that says why a class is not in Silver yet. Everything it writes is
documentation — the compiler never opens a DDD file (DD-091, DD-229) — so it is safe to
iterate on with the SMEs.

Use it after **kairos-design-domain** has authored or extended a domain, before or alongside
**kairos-design-mapping**. Do not author classes, bindings or dbt here; route those.

## Design fleet mode (DD-088)

Default is interactive. An explicit fleet override applies only to this skill invocation
and is never inherited. Record rationale, confidence, and references for every AI-approved
choice. Stop for ambiguity, low confidence, sensitive or proprietary data, a boundary
decision that moves a class between domains, or any destructive action. Context boundaries
and subdomain types are business judgements (Tier 3): propose, never decide.

## Authoritative inputs

- `model/ontologies/<domain>.ttl` — canonical meaning; read only through
  `show-class-inventory`, `list-class-properties`, `explain-term`, `resolve-ontology`
  (DD-103: never read a `.ttl` as text).
- `businessdiscovery/*-glossary.ttl` and `integration/discovery/` — confirmed terms and
  context from **kairos-design-discovery**.
- An external logical model (an EA/XMI export, a whiteboard, a workshop transcript) is
  **evidence, not authority**: it names concepts and boundaries; the hub decides what to
  author. Never copy it in wholesale.
- `integration/bindings/*.binding.yaml` and `model/contracts/*.contract.yaml` — what Silver
  promises today; read them to know which boxes are already filled.

## What you author

| File | Holds | Rule |
|---|---|---|
| `model/extensions/ddd-contexts-ext.ttl` (one per hub) | `kairos-ddd:BoundedContext` individuals with `rdfs:label`, `kairos-ddd:subdomainType` (`CoreDomain` / `SupportingSubdomain` / `GenericSubdomain`), `publishedLanguage`, `designNote`; `kairos-ddd:ContextRelationship` edges with a closed pattern | Strategic design, declared once. No class-level predicates here. |
| `model/extensions/<domain>-ddd-ext.ttl` (one per domain) | On that domain's own classes: `kairos-ddd:boundedContext` (exactly one), `tacticalPattern` (AggregateRoot, AggregateMember, Entity, ValueObject, DomainService, DomainEvent, Policy), `aggregateRoot`, `invariant` (repeatable prose), `designNote`, and the language — `skos:scopeNote`, `skos:example`, `skos:altLabel` | Tactical design. Never `rdfs:label`/`rdfs:comment` (those are the domain's), never `kairos-ext:silver*`/`gold*`. |
| `integration/discovery/class-dispositions.yaml` | Per class the hub declares and no binding targets: `deferred`, `architecture-only`, `abstract`, with rationale and `decided_by` | Written only through `kairos-ontology class-disposition set`. |
| `decisions/HUB-DD-*.md` | Each open modelling question and each boundary decision | `kairos-ontology decision new`. |

## Workflow

### 1. Establish scope

Name the contexts in play and the domains they touch. Run `kairos-ontology next --format json`
and `kairos-ontology design-landscape --format json` to see what is modelled, bound and
demanded. If the hub has an external logical model, list its subject areas and note which are
already classes in the hub (`show-class-inventory --domain <d>`) and which are not.

### 2. Strategic design → `ddd-contexts-ext.ttl`

For each bounded context: label, subdomain type, whether it is a published language, one
design note stating what it owns and why the boundary sits there. For each relationship: the
two contexts and one closed pattern (SharedKernel, CustomerSupplier, Conformist,
AnticorruptionLayer, OpenHostService, PublishedLanguage, SeparateWays). Confirm every boundary
with the human — a context is a business agreement about meaning, not a folder.

**A bounded context and a physical domain are orthogonal.** A class stays in the domain file
and the Silver folder it lives in; the overlay draws the box. Move a class between domains only
on a physical trigger (a second source binds it, its own release cadence, an unreviewable host
file) — never because the architecture picture wants a box. Record the reasoning as a
`designNote` on the class.

### 3. Tactical design → `<domain>-ddd-ext.ttl`

Per class the domain declares: its context, its tactical pattern, its aggregate root where it
is a member (a member with a root and no context inherits the root's), its invariants in
prose, and the language the business uses *in this context* — `skos:scopeNote` for a meaning
that differs from the canonical comment, `skos:altLabel` for synonyms, `skos:example` for a
recognisable instance (never a real personal identifier). A cross-domain aggregate edge
validates only when the member's domain imports the root's; if it does not, record the
disagreement as a design note rather than forcing an import.

### 4. Classes the architecture needs but Silver does not

A concept from the logical model with no source behind it is still authored — by
**kairos-design-domain**, as an ordinary class with label and comment — and then recorded
here:

```powershell
$env:KAIROS_SKILL_CONTEXT = "1"
uv run kairos-ontology class-disposition set --class <prefix:Local> `
  --disposition architecture-only --rationale "<why it is a concept and not yet a table>"
```

`deferred` when a binding is expected, `abstract` for a grouping superclass. Binding a class
later flips it to `bound` with no ledger edit. `kairos-ontology class-disposition init` adopts
the ledger: from then on an undecided class fails `validate`, which is the point.

### 5. Validate and project

```powershell
$env:KAIROS_SKILL_CONTEXT = "1"
uv run kairos-ontology validate --ddd
uv run kairos-ontology project --target ddd
```

`validate --ddd` checks the strategic file alone, every overlay merged with its domain and the
strategic file, and the whole set for cross-file disagreement (`ddd.context-redeclared`,
`ddd.context-label-conflict`, `ddd.class-in-two-contexts`, `ddd.tactical-in-strategic-file`).
`project --target ddd` writes, under `ontology-hub-publish/architecture/ddd/`:

- `contexts/context-map.mmd`, `contexts/all-contexts.mmd`, one `contexts/<context>.mmd` per
  context, `contexts/design-notes.md` — the architecture, with each class's Silver status;
- `ubiquitous-language.ttl` — one SKOS concept per hub class, linked by `skos:exactMatch`;
- `concept-guide.md` — the concepts and how they relate, for the SMEs and the data engineer;
- `<domain>-aggregate-overview.mmd`, `<domain>-ddd-report.md` per domain with an overlay.

All of it is tracked and drift-gated; `git add` new files with the change. Review the
diagrams and the concept guide **with the SMEs**, then turn every open question into
`kairos-ontology decision new`.

### 6. Hand off

Tell the data engineer what changed: which classes are `architecture-only` or `deferred`
(not binding targets), which invariants want a `DataQualityRule` or a SHACL shape, which
synonyms and scope notes will help column matching. Point them at `concept-guide.md`.

## Stage checklist

| After | The review artifact is |
|---|---|
| a domain design | `concept-guide.md` and `ubiquitous-language.ttl` |
| an architecture design | `contexts/*.mmd` and `contexts/design-notes.md` |
| a binding lands | the class's Silver status in both, with no ledger edit |

## Guardrails

- The firewall: overlays never carry `kairos-ext:silver*`/`gold*`; the compiler reads one
  extension file per domain (`<domain>-gold-ext.ttl`) and never a DDD file. Adding an overlay
  cannot change a contract, a Silver model, a Gold table or an ERD.
- Lucid, Miro, PowerPoint: a rendering, never a source. Regenerate from the hub; workshop
  annotations come back as overlay edits. Publishing to an external board is an explicit,
  per-occasion decision.
- Sample values in `concept-guide.md` stay off unless the hub set
  `projections.concept_guide.samples: true` in `kairos.yaml`.
- Never read a `.ttl`/`.rdf`/`.owl` as text to answer a semantic question (DD-103).

## Related skills

- **kairos-design-discovery** — the confirmed terms this layer builds on.
- **kairos-design-domain** — authors the classes; the architecture only annotates them.
- **kairos-design-mapping** — grows Silver one binding at a time; reads the concept guide.
- **kairos-execute-validate** / **kairos-execute-project** — `validate --ddd`, `project --target ddd`.
