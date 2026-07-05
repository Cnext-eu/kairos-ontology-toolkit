# DDD Governance Overlay Implementation Plan

This plan turns the complementary DDD governance proposal into an actionable,
low-risk implementation path that fits the existing Kairos architecture.

## 1. Requirements

The implementation must satisfy these requirements:

| ID | Requirement |
|----|-------------|
| R1 | Keep core domain ontologies focused on durable business semantics. |
| R2 | Do not duplicate claim-registry governance for ownership, approval, materialization, deviations, or data-product certification. |
| R3 | Keep silver/gold projection-control annotations in the existing `kairos-ext:` extension model. |
| R4 | Make DDD metadata optional and additive. Hubs without DDD overlays must remain valid. |
| R5 | Use typed RDF resources and controlled IRIs, not raw strings, for DDD classifications and context objects. |
| R6 | Support context-map relationships with enough structure to express source context, target context, and relationship type. |
| R7 | Provide a validation path that actually loads `*-ddd-ext.ttl` overlays and the referenced domain ontologies together. |
| R8 | Start with one-way documentation projections only. Do not include XMI or Enterprise Architect round-trip in the MVP. |
| R9 | Make lifecycle placement explicit and compatible with discovery, source, domain, claims, mapping, silver, gold, validate, and project phases. |
| R10 | Package vocabulary, shapes, scaffold files, and catalog mappings so existing hubs can adopt the feature through normal update flows. |
| R11 | Add scenario coverage using synthetic non-proprietary examples. |
| R12 | Record the architectural decision before implementation is treated as accepted. |

## 2. Target Architecture

```text
model/ontologies/*.ttl
  durable business semantics

model/claims/*-claims.yaml
  governed source-evidence, approval, ownership, disposition, and materialization decisions

model/extensions/*-silver-ext.ttl
model/extensions/*-gold-ext.ttl
  delivery projection controls through kairos-ext

model/extensions/*-ddd-ext.ttl
  optional DDD design overlay for architecture reporting only

output/architecture/ddd/
  generated Mermaid diagrams and Markdown reports
```

The DDD overlay must not change silver, gold, dbt, or Power BI generation in the
MVP.

## 3. Vocabulary Design

### 3.1 New vocabulary file

Add a managed vocabulary file:

```text
src/kairos_ontology/scaffold/ontology-hub/model/vocab/kairos-ddd.ttl
```

If the hub scaffold does not currently have a vocabulary folder, introduce the
least disruptive managed location already used by the toolkit for vocabulary
files and register it consistently.

### 3.2 Core classes

Define these classes:

| Class | Purpose |
|-------|---------|
| `kairos-ddd:BoundedContext` | Named DDD bounded context. |
| `kairos-ddd:ContextRelationship` | Reified relationship between two bounded contexts. |
| `kairos-ddd:TacticalPattern` | Controlled class for tactical DDD pattern values. |
| `kairos-ddd:ContextRelationshipPattern` | Controlled class for context-map relationship values. |

### 3.3 Core properties

Define these properties:

| Property | Domain | Range | Purpose |
|----------|--------|-------|---------|
| `kairos-ddd:boundedContext` | ontology/class/property | `kairos-ddd:BoundedContext` | Assigns a semantic element to a bounded context. |
| `kairos-ddd:tacticalPattern` | class | `kairos-ddd:TacticalPattern` | Marks aggregate root, aggregate member, entity, value object, etc. |
| `kairos-ddd:aggregateRoot` | class | `owl:Class` | Links an aggregate member to its aggregate root class. |
| `kairos-ddd:publishedLanguage` | ontology/class/context | `xsd:boolean` | Marks concepts intentionally exposed across contexts. |
| `kairos-ddd:designNote` | ontology/class/property/context | `rdf:langString` or `xsd:string` | Separates architecture rationale from business definitions. |
| `kairos-ddd:sourceContext` | context relationship | `kairos-ddd:BoundedContext` | Source context in a context-map edge. |
| `kairos-ddd:targetContext` | context relationship | `kairos-ddd:BoundedContext` | Target context in a context-map edge. |
| `kairos-ddd:relationshipPattern` | context relationship | `kairos-ddd:ContextRelationshipPattern` | Pattern such as shared kernel or customer-supplier. |

### 3.4 Controlled individuals

Define tactical pattern individuals:

```text
kairos-ddd:AggregateRoot
kairos-ddd:AggregateMember
kairos-ddd:Entity
kairos-ddd:ValueObject
kairos-ddd:DomainService
kairos-ddd:DomainEvent
kairos-ddd:Policy
```

Define relationship pattern individuals:

```text
kairos-ddd:SharedKernel
kairos-ddd:CustomerSupplier
kairos-ddd:Conformist
kairos-ddd:AnticorruptionLayer
kairos-ddd:OpenHostService
kairos-ddd:PublishedLanguage
kairos-ddd:SeparateWays
```

## 4. Validation Design

### 4.1 Dedicated DDD validation path

Do not rely on the existing domain-ontology validation loop to pick up
`*-ddd-ext.ttl` files. It intentionally excludes `*-ext.ttl` files from domain
ontology validation.

Add a dedicated validation path that:

1. Discovers `model/extensions/*-ddd-ext.ttl`.
2. Loads the DDD overlay graph.
3. Loads the matching domain ontology graph.
4. Loads imported vocabulary graphs needed for offline validation.
5. Applies DDD SHACL shapes to the merged graph.
6. Reports DDD validation separately from core ontology syntax and SHACL results.

### 4.2 Validation behavior

| Case | Expected behavior |
|------|-------------------|
| No `*-ddd-ext.ttl` files exist | Validation passes with DDD validation skipped or marked not applicable. |
| DDD overlay exists and is well formed | Validation passes. |
| DDD overlay has syntax errors | Validation fails. |
| DDD overlay references an unknown aggregate root class | Validation fails. |
| DDD overlay uses an unknown tactical pattern | Validation fails. |
| DDD overlay contains silver/gold projection annotations | Validation fails. |

### 4.3 SHACL requirements

Add DDD shapes for:

| Rule | Severity |
|------|----------|
| `kairos-ddd:BoundedContext` resources must have `rdfs:label`. | Error |
| `kairos-ddd:tacticalPattern` values must be known tactical pattern individuals. | Error |
| `kairos-ddd:AggregateMember` classes must have `kairos-ddd:aggregateRoot`. | Error |
| `kairos-ddd:aggregateRoot` targets must be known `owl:Class` resources in the merged graph. | Error |
| `kairos-ddd:ContextRelationship` must have source context, target context, and relationship pattern. | Error |
| Context relationship endpoints must be typed `kairos-ddd:BoundedContext`. | Error |
| DDD overlays must not use `kairos-ext:silver*` or `kairos-ext:gold*` predicates. | Error |

The silver/gold predicate exclusion likely requires a SPARQL-based SHACL
constraint.

## 5. Projection Design

### 5.1 MVP output

Add a one-way documentation projection:

```text
output/architecture/ddd/
  {domain}-context-map.mmd
  {domain}-aggregate-overview.mmd
  {domain}-ddd-report.md
```

### 5.2 Projection inputs

The DDD projector loads:

1. Domain ontology TTL.
2. Matching `*-ddd-ext.ttl` overlay.
3. DDD vocabulary.
4. Optional labels/comments from imported local vocabularies where available.

It must not load silver/gold extension semantics for behavior-changing decisions.

### 5.3 Projection rules

| Input | Output |
|-------|--------|
| `kairos-ddd:BoundedContext` | Context node or Mermaid namespace. |
| `kairos-ddd:ContextRelationship` | Context-map edge. |
| `kairos-ddd:tacticalPattern` | Class stereotype or report badge. |
| `kairos-ddd:aggregateRoot` | Aggregate grouping. |
| `kairos-ddd:publishedLanguage true` | Published-language marker. |
| `kairos-ddd:designNote` | Report note. |

## 6. Lifecycle and Skill Integration

DDD overlay design should be split into two concerns:

| Concern | Lifecycle placement | Rationale |
|---------|---------------------|-----------|
| Strategic context discovery | After discovery/source and before or during domain modeling | Bounded contexts can influence how ontology modules are sliced. |
| Tactical aggregate annotation | After domain claims are approved and before architecture reporting | Aggregate roots and members need approved ontology classes. |

Recommended lifecycle wording:

```text
discovery -> source -> domain/claims -> optional DDD overlay -> mapping -> silver -> gold -> validate -> project/report
```

For the MVP, this can be documented as an optional design step. A dedicated skill
should only be added if the workflow becomes interactive enough to justify it.

## 7. Packaging and Scaffold Work

Implementation must update managed scaffold assets:

| Asset | Required action |
|-------|-----------------|
| DDD vocabulary TTL | Add managed scaffold copy. |
| DDD SHACL shapes | Add managed scaffold copy. |
| XML catalog | Register `https://kairos.cnext.eu/ddd#` for offline resolution. |
| Hub update flow | Ensure existing hubs receive the vocabulary and shapes through normal update behavior. |
| Help skill | Document the optional DDD overlay and projection if implemented. |
| Execute/project skill | Mention the architecture/DDD report target if exposed through projection. |

If any new skill is created or changed, also update the corresponding scaffold
skill copy.

## 8. Scenario and Unit Test Plan

### 8.1 Scenario fixture

Add synthetic DDD overlays to `tests/scenarios/acme-hub/model/extensions/`:

```text
client-ddd-ext.ttl
invoice-ddd-ext.ttl
```

Use only synthetic `acme` labels and namespaces.

### 8.2 Test coverage

Add tests for:

| Test area | Expected coverage |
|-----------|-------------------|
| Vocabulary loading | `kairos-ddd.ttl` is present and parseable. |
| Catalog resolution | DDD namespace resolves offline. |
| DDD validation pass | Valid scenario overlays pass. |
| DDD validation failure | Unknown tactical pattern fails. |
| Aggregate validation | Aggregate member without root fails. |
| Context relationship validation | Missing source/target/pattern fails. |
| Projection output | Mermaid and Markdown files are generated. |
| Projection isolation | DDD overlay does not alter silver/gold/dbt/Power BI outputs. |

## 9. Implementation Phases

### Phase 0: Decision record

Deliverables:

- Add a formal design decision for optional DDD overlays.
- State explicitly that data governance remains in the claim registry.
- State explicitly that XMI/EA round-trip is out of scope.

Acceptance criteria:

- Design decision is reviewed before code implementation starts.

### Phase 1: Vocabulary and examples

Deliverables:

- Add `kairos-ddd.ttl`.
- Add synthetic example overlay.
- Add managed scaffold copy.
- Add catalog mapping if required by existing vocabulary resolution.

Acceptance criteria:

- Vocabulary parses with `rdflib`.
- Example overlay parses with `rdflib`.

### Phase 2: Validation

Deliverables:

- Add DDD SHACL shapes.
- Add DDD overlay discovery.
- Add merged graph validation for domain ontology plus matching DDD overlay.
- Add unit and scenario tests.

Acceptance criteria:

- Hubs without DDD overlays remain valid.
- Valid DDD overlays pass.
- Invalid controlled values, missing aggregate roots, and malformed context relationships fail.

### Phase 3: Documentation projection

Deliverables:

- Add one-way DDD report or architecture projection.
- Generate Mermaid context maps and aggregate overviews.
- Add scenario tests for generated output.

Acceptance criteria:

- Projection output is deterministic.
- Projection output contains bounded contexts, context relationships, aggregate roots, and design notes.
- Existing silver/gold/dbt/Power BI scenario outputs remain unaffected.

### Phase 4: Skill and docs integration

Deliverables:

- Update `kairos-help`.
- Update relevant lifecycle/design skill documentation.
- Add scaffold skill copies if skill docs change.
- Update user-facing documentation.

Acceptance criteria:

- Users can discover when and how to create `*-ddd-ext.ttl`.
- Skill routing does not encourage direct editing that bypasses validation gates.

### Phase 5: Future XMI/EA evaluation

Deliverables:

- Separate draft design decision for XMI/EA export if still needed.
- Evaluate one-way XMI export before any round-trip sync.

Acceptance criteria:

- No EA round-trip behavior is added without a separate accepted design decision.

## 10. Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| DDD overlay becomes a second governance source | Keep ownership, approval, certification, and materialization out of DDD TTL. |
| DDD validation silently skips files | Use a dedicated DDD validation path with explicit overlay discovery. |
| Context maps cannot be generated | Reify context relationships with source, target, and pattern. |
| DDD annotations accidentally affect delivery projections | Keep MVP projection documentation-only and add isolation tests. |
| Scaffold drift | Add managed scaffold copies and packaging tests where appropriate. |
| Over-modeling behavior | Defer commands, events, workflows, invariants, and EA round-trip until concrete consumers exist. |

## 11. Done Definition

The MVP is done when:

1. The design decision is accepted.
2. `kairos-ddd.ttl` and DDD shapes are scaffolded and resolvable.
3. Optional `*-ddd-ext.ttl` overlays validate through a dedicated path.
4. Scenario tests cover valid and invalid DDD overlays.
5. A one-way DDD documentation projection produces deterministic Mermaid and Markdown output.
6. Existing claim governance and silver/gold projections remain unchanged.
7. Documentation and skill guidance explain the optional lifecycle step.
