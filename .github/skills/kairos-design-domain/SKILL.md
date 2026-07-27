---
name: kairos-design-domain
description: >
  Interactive v5 workflow for designing a bounded, source-grounded OWL/Turtle
  canonical model patch. Uses confirmed business context, selected industry
  references, PII-safe source evidence, and optional downstream demand. NOT for
  authoring EntityBinding YAML or generating dbt artifacts.
---
<!-- kairos-ontology-toolkit:managed v2.35.0 -->

# V5 Canonical Domain Design

Use this skill to create or amend `model/ontologies/<domain>.ttl`. OWL/Turtle is
the authority for canonical classes, properties, relationships, labels, and
definitions. Produce the **smallest useful canonical slice** as a reviewable
ontology patch; do not design an entire enterprise model in one pass.

This is the DD-133 v5 clean break. Work only with the v5 layout. Do not create or
consult legacy phase logs, proposal databases, governance registries, readiness
reports, mapping/preparation/Silver-extension TTL, or virtual-source registries.
Existing v4 hubs must be rebuilt as v5 hubs rather than migrated or
dual-authored.

## Design fleet mode (DD-088)

Default is interactive. Ask the user to confirm source completeness, business
terminology, reference-model choices, the bounded slice, and the ontology patch
before writing it.

If the user explicitly requests design fleet mode for this invocation:

- announce that AI will make checkpoint decisions;
- apply every evidence, privacy, scope, and validation gate below;
- mark decisions **AI-approved**, not user-confirmed;
- record rationale, confidence, and evidence references in the in-session review;
- stop for low confidence, missing source evidence, naming ambiguity,
  policy-sensitive choices, proprietary/PII risk, or destructive changes.

The override applies only to this skill invocation. It expires when the skill
ends or pauses, is never inherited by another skill or later resume, and does
not authorize lifecycle-wide autopilot.

## Authoritative inputs

Read only the inputs relevant to the requested domain:

1. `integration/discovery/` — confirmed business context and glossary.
2. `integration/sources/<source>/*.ttl` — Bronze schema and already-redacted
   representative samples.
3. Selected ontology-reference modules and their catalog-resolved import closure.
4. Existing `model/ontologies/<domain>.ttl`, when amending a domain.
5. Optional TMDL/PBIP or Gold demand supplied by the user.

Keep the four evidence roles distinct:

| Role | Meaning |
|---|---|
| Business authority | Confirmed concepts, meaning, terminology, and boundaries |
| Industry inspiration | Reusable classes/properties and alignment patterns |
| Source feasibility | Relations, columns, types, nullability, and masked examples |
| Downstream demand | Optional analytical fields or relationships; never business authority |

An input may support more than one role, but never silently promote source shape
or downstream demand into a business fact.

## Hard gates

### Gate 0: Scoped reference-inventory freshness

Before proposing or editing a class/property, run the scoped pre-flight:

```powershell
$env:KAIROS_SKILL_CONTEXT = "1"
uv run kairos-ontology check-inventory --domains <active-domain> --explain-scope
```

This is the only freshness authority for selected reference inventories. Missing
or stale in-scope inventories are blocking: **STOP**. Unrelated repository-wide
failures are non-blocking when the scoped command exits zero. Report the
installed/current local reference-model version from
`ontology-reference-models/VERSION`, or `unknown` when absent. Never silently
update reference models. Route an approved update through **kairos-toolkit-ops**
and rerun the same check.

### Gate 1: Source completeness

Run this gate on every modeling pass, including the first:

1. list imported and analysed sources under `integration/sources/`;
2. identify which sources appear relevant to the requested domain;
3. ask whether additional or newer sources must be imported first.

If no relevant source vocabulary exists, or the user says more evidence is
needed, stop and invoke **kairos-design-source**. Offer
**kairos-design-discovery** when confirmed business context is absent. Return
here only after the evidence is available. Never model against an empty source
set.

### Gate 2: PII-safe, source-grounded evidence

Read relevant source relations and columns before proposing classes or
properties. If TMDL/PBIP input is present, read its relevant tables, columns, and
relationships too.

Expose only masked, redacted, aggregated, or synthetic examples to the model.
Never reveal or persist raw names, emails, addresses, identifiers, free text, or
other sensitive values. Treat an unredacted sample as blocking and route it back
through the source privacy/redaction workflow.

Every proposed class/property must cite one or more of:

- confirmed business context or user statement;
- a selected reference-model term;
- a specific source relation/column and type;
- optional downstream demand.

General domain knowledge may appear only as a clearly labeled low-confidence
suggestion and cannot enter the accepted patch without confirmation.

### Gate 3: Bounded ontology patch

One invocation works on one domain and one coherent canonical slice:

- one primary entity or one tightly related amendment;
- only directly required reference/value classes and relationships;
- only source-feasible or explicitly confirmed properties;
- no speculative neighboring domains or bulk ontology generation.

If the request spans multiple slices, propose an order and complete one slice
before starting the next.

### Gate 4: Explicit confirmation

Interactive mode requires explicit confirmation of:

1. business term and technical class/property names;
2. reuse, specialization, or local-definition choices;
3. class boundaries and relationships;
4. the exact bounded patch.

Silence is not approval. Do not write draft TTL for review before these
checkpoints. Fleet mode may make these decisions only under its invocation-scoped
rules.

### Gate 5: Ontology integrity

Before applying a patch, parse the complete candidate graph in memory with
`rdflib.Graph`; do not validate Turtle by string inspection alone. Confirm:

- one `owl:Ontology` declaration with `rdfs:label` and `owl:versionInfo`;
- every new class has `rdfs:label` and `rdfs:comment`;
- every new property has `rdfs:label`, `rdfs:domain`, and `rdfs:range`;
- PascalCase classes and camelCase properties;
- catalog-resolved imports and terms;
- no duplicate local term or accidental reference-model specialization;
- source types can feasibly populate proposed property ranges.

Do not apply a candidate with syntax or convention errors.

## Canonical design loop

### 1. Establish scope and mode

Identify the hub root from `kairos.yaml`, domain, requested slice, and whether
this invocation is interactive or fleet. If the request is ambiguous, remain
interactive.

### 2. Complete source pre-flight

Run Gate 1 and wait for the user's source-completeness answer in interactive
mode. Read all relevant source vocabularies, optional TMDL/PBIP demand, and
confirmed discovery context. Never infer completeness from filenames alone.

### 3. Inspect selected industry references

Run Gate 0. Read the relevant import closure and surface the specialization tree,
including SUBCLASSES of the parent and subclass-specific properties. Mark
specializations as `(subclass)` in proposals. Prefer justified reuse over
accidental local duplication, while keeping business meaning authoritative.

### 4. Build an in-session evidence matrix

Present only PII-safe evidence:

| Candidate term | Business authority | Industry inspiration | Source feasibility | Downstream demand | Confidence |
|---|---|---|---|---|---|

Use relation/column identifiers and types; examples must remain masked. State
conflicts and missing evidence explicitly. This matrix is ephemeral conversation
context, not a hub artifact.

### 5. Propose the smallest useful slice

Present:

- primary class and any required superclass;
- properties with domain, range, definition, and evidence;
- object relationships with target and intended cardinality;
- terms deliberately excluded from this slice;
- unresolved questions and confidence.

Keep source representation details out of the canonical model. Source keys,
grain, load policy, expressions, and relationship failure actions belong in the
v5 EntityBinding authored by **kairos-design-mapping**.

### 6. Review naming and structure

Obtain explicit decisions for every item in Gate 4. When evidence conflicts,
prefer confirmed business meaning, explain the trade-off, and do not hide
source-feasibility limitations.

### 7. Prepare and validate the patch

Create a reviewable unified diff limited to
`model/ontologies/<domain>.ttl`. Parse the full post-patch graph in memory and run
Gate 5. Summarize added, changed, and intentionally omitted terms plus their
evidence.

In interactive mode, show the validated diff and wait for final approval. In
fleet mode, record the AI approval with rationale, confidence, and evidence.

### 8. Apply and verify

Apply only the approved diff. Reread and parse the saved ontology, repeat Gate 5,
and confirm no other authored file changed. If validation fails, restore the
pre-patch content and report the failure.

### 9. Hand off

Report the accepted slice and remaining questions. The next step is
**kairos-design-mapping**, which authors one closed YAML `EntityBinding` per
source relation or contracted dbt model and canonical entity. Do not generate
bindings or dbt artifacts in this skill.

## Quick amendments

A minor amendment may use a shortened loop only when it changes at most three
existing properties, introduces no class or import, and does not alter domain
boundaries. Source completeness, PII safety, confirmation/fleet rules, bounded
diff review, and ontology integrity still apply.

## Anti-patterns

- Designing from general knowledge before reading source evidence.
- Treating a physical table as proof of a canonical class.
- Copying source columns wholesale into the ontology.
- Treating TMDL or Gold demand as business authority.
- Exposing raw sample values to the LLM or committed files.
- Writing unconfirmed or unparsed Turtle.
- Combining ontology design with EntityBinding or generated SQL authoring.
- Persisting conversational decisions as state, reports, or proposal records.

## Related skills

- **kairos-design-discovery** — confirm business context and terminology.
- **kairos-design-source** — import/analyse source vocabularies and redact samples.
- **kairos-design-mapping** — author v5 YAML entity bindings.
- **kairos-develop-dbt-transformation** — author ordinary contracted dbt models
  for relational or grain-changing logic.
- **kairos-toolkit-ops** — explicitly update selected reference models.
