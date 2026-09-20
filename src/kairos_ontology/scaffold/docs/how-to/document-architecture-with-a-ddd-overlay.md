# Document the architecture with a DDD overlay

**Skill:** `kairos-design-architecture`

A context engineer's logical model is usually broader than anything the hub can bind today: it
names concepts with no source column behind them, it draws aggregate boundaries, and it separates
concerns the Silver layer keeps pragmatically merged. All of that can live in the hub without
touching Silver, because of one fact worth holding on to:

> **The ontology may run ahead of the sources. Growing it does not grow Silver. Only authoring an
> EntityBinding grows Silver.**

The Silver contract's entity set *is* the binding set. An `owl:Class` no binding targets never
enters the CompilePlan — not an error, not even a warning — so the Silver contract is a subset of
the architecture by construction. This guide is about making that subset *visible*, and about
carrying the rest of the architecture as reviewable documentation.

## Two kinds of file, both under `model/extensions/`

| File | Holds |
|---|---|
| `ddd-contexts-ext.ttl` (one per hub) | The **strategic** design: `kairos-ddd:BoundedContext` individuals (label, `subdomainType`, `publishedLanguage`, `designNote`) and the context map (`kairos-ddd:ContextRelationship` with a closed pattern). |
| `<domain>-ddd-ext.ttl` (one per domain) | The **tactical** design, on that domain's own classes: `boundedContext` (exactly one), `tacticalPattern`, `aggregateRoot`, `invariant`, `designNote`, and the language — `skos:scopeNote`, `skos:example`, `skos:altLabel`. |

The compiler never opens either file. It reads exactly one extension per domain,
`<domain>-gold-ext.ttl`, and `validate --ddd` fails any overlay that carries a
`kairos-ext:silver*` or `kairos-ext:gold*` predicate. Adding an overlay cannot change a contract, a
Silver model, a Gold table or an ERD.

```turtle
# model/extensions/ddd-contexts-ext.ttl
@prefix ctx:        <https://acme.example/ddd#> .
@prefix kairos-ddd: <https://kairos.cnext.eu/ddd#> .
@prefix rdfs:       <http://www.w3.org/2000/01/rdf-schema#> .

ctx:Billing a kairos-ddd:BoundedContext ;
    rdfs:label "Billing" ;
    kairos-ddd:subdomainType kairos-ddd:CoreDomain ;
    kairos-ddd:publishedLanguage true ;
    kairos-ddd:designNote "Owns invoicing, line items and settlement." .

ctx:Address a kairos-ddd:BoundedContext ;
    rdfs:label "Address" ;
    kairos-ddd:subdomainType kairos-ddd:GenericSubdomain .

ctx:BillingUsesAddress a kairos-ddd:ContextRelationship ;
    kairos-ddd:sourceContext ctx:Billing ;
    kairos-ddd:targetContext ctx:Address ;
    kairos-ddd:relationshipPattern kairos-ddd:Conformist .
```

```turtle
# model/extensions/party-ddd-ext.ttl
@prefix party:      <https://acme.example/ont/party#> .
@prefix ctx:        <https://acme.example/ddd#> .
@prefix kairos-ddd: <https://kairos.cnext.eu/ddd#> .
@prefix skos:       <http://www.w3.org/2004/02/skos/core#> .

party:PostalAddress
    kairos-ddd:boundedContext ctx:Address ;
    kairos-ddd:tacticalPattern kairos-ddd:ValueObject ;
    kairos-ddd:invariant "A postal address always carries a country." ;
    skos:altLabel "Delivery address"@en ;
    kairos-ddd:designNote "Physically resident in the party domain: one source, one consumer. The context boundary is architectural; revisit the physical split only on a physical trigger." .
```

## A bounded context and a physical domain are orthogonal

Nothing in the compiler derives a class's domain from the ontology graph; the binding's
`metadata.domain` and the `model/ontologies/<domain>.ttl` filename do. `kairos-ddd:boundedContext`
is a free annotation the compiler is blind to, so it can slice the class universe along entirely
different lines — several domains into one context, one domain across several contexts.

That is the answer when the architecture wants a boundary Silver does not want. **Annotate; do
not move.** The `PostalAddress` above stays in `party.ttl`, in the party Silver models and in the
party contract; the context map renders `Address` as its own context. Moving it would cost a new
domain file, a catalog entry, a `_master.ttl` import, a binding `metadata.domain` change, a
Silver model folder move, a new contract, a new Gold extension, `externalReference` blocks on
every referencing binding, version bumps and downstream dbt refs. Move a class only on a physical
trigger — a second source binds it, it acquires its own release cadence, the host file stops being
reviewable — never because the picture wants a box.

## Rules the overlay must respect

`validate --ddd` enforces these; each is a SHACL shape or a Python check.

1. Every `BoundedContext` has an `rdfs:label`.
2. `tacticalPattern` is one of `AggregateRoot`, `AggregateMember`, `Entity`, `ValueObject`,
   `DomainService`, `DomainEvent`, `Policy`; `subdomainType` one of `CoreDomain`,
   `SupportingSubdomain`, `GenericSubdomain`; a relationship pattern one of `SharedKernel`,
   `CustomerSupplier`, `Conformist`, `AnticorruptionLayer`, `OpenHostService`,
   `PublishedLanguage`, `SeparateWays`.
3. An `AggregateMember` declares its `aggregateRoot`, and the root resolves to a class in the
   merged graph — the domain, its import closure, the strategic file and the overlay. A
   cross-domain aggregate edge therefore validates only when the member's domain imports the
   root's; this is the one place the physical layering constrains the architectural one.
4. A `boundedContext` value is a declared context; an element has at most one; a relationship
   joins two different contexts.
5. An overlay annotates its own domain's classes; the strategic file carries no class-level
   predicate.
6. No `kairos-ext:silver*` / `gold*` predicate anywhere in a DDD file.
7. Across files: one context IRI declared twice with the same label is a warning
   (`ddd.context-redeclared` — move it to the strategic file); with different labels an error
   (`ddd.context-label-conflict`); one class in two contexts by two files an error
   (`ddd.class-in-two-contexts`).

Move contexts and their relationships into the strategic file **together**: a strategic file whose
relationships name contexts still declared only in overlays fails on its own, by design.

## Classes the architecture needs but Silver does not

Author them anyway, as ordinary classes with a label and a comment (the `kairos-design-domain`
skill), and record why they are not bound:

```bash
kairos-ontology class-disposition set --class party:PostalAddress \
  --disposition architecture-only \
  --rationale "Its own bounded context; physically resident in party, no separate source."
kairos-ontology class-disposition list --undecided
```

`deferred` when a binding is expected later, `abstract` for a grouping superclass. Binding a class
flips its status to `bound` with no ledger edit. Until the hub creates the ledger
(`class-disposition init`, or the first `set`), `validate` reports undecided classes as warnings;
afterwards an undecided class is an error, degradable with `--degraded`.

## Validate, project, review

```bash
kairos-ontology validate --ddd
kairos-ontology project --target ddd
```

Under `ontology-hub-publish/architecture/ddd/` — tracked and regenerated by the drift gate, so
commit the result and `git add` new files:

| File | What it is |
|---|---|
| `contexts/context-map.mmd` | every context and every relationship, whichever file declared it |
| `contexts/all-contexts.mmd` | one `classDiagram`, one `namespace` per context, every class stereotyped with its pattern and its Silver status |
| `contexts/<context>.mmd` | one diagram per context, neighbours drawn as stubs |
| `contexts/design-notes.md` | per context: subdomain, classes, Silver status (with the recorded disposition), invariants, language, design notes; then every hub class no context claims |
| `ubiquitous-language.ttl` | one SKOS concept per hub class, `skos:exactMatch` to the class IRI, synonyms, scope notes, examples, source names, Silver status; one collection per context |
| `concept-guide.md` | the concepts and how they relate, for the SMEs and the data engineer |
| `<domain>-aggregate-overview.mmd`, `<domain>-ddd-report.md` | the per-domain view |

Review the diagrams and the concept guide with the SMEs. Every open modelling question becomes a
decision record (`kairos-ontology decision new`), and every answer comes back as an overlay or
ontology edit — never as an edit to a generated file.

**Lucid, Miro or slides are a rendering, never a source.** A board is a snapshot that disagrees
with the hub the moment someone edits it. Regenerate; publish to an external tool as an explicit,
per-occasion decision, and bring annotations back as overlay edits.

## Carrying an external logical model

An Enterprise Architect export or a whiteboard model is evidence, not authority. The encoding that
has worked:

| Modelling construct | Encoded as | Where |
|---|---|---|
| Entity / class stereotype | `tacticalPattern kairos-ddd:Entity` (or `ValueObject`) | overlay |
| Composite or aggregation end | `AggregateRoot` on the owner; `AggregateMember` + `aggregateRoot` on the member | overlay |
| Subject area / package | a `BoundedContext` + `boundedContext` on its classes | strategic file + overlay |
| Class and attributes | `owl:Class` + `owl:DatatypeProperty`, bound or not | domain TTL |
| Generalisation | `rdfs:subClassOf` | domain TTL |
| Association | `owl:ObjectProperty` with domain and range | domain TTL |
| Multiplicity | `owl:Restriction` min/max cardinality — read by the ERD and context diagrams, ignored by compile | domain TTL |
| Enumeration | `skos:ConceptScheme` + `skos:Concept`, per the hub's closed-code-list pattern | domain TTL + SHACL |
| Open question or note | `kairos-ddd:designNote` + a decision record | overlay + `decisions/` |
| Synonym, scope, example | `skos:altLabel`, `skos:scopeNote`, `skos:example` | overlay |

Import in the order the toolkit validates: contexts and map first (strategic file), then the
classes that already exist (overlays), then extend the canonical TTLs with the classes the model
adds — unbound, with a disposition — and only then bind selectively where source evidence exists.
Steps one to three never touch Silver.

## Next

[Bind a source to an entity](bind-a-source-to-an-entity.md) grows Silver one class at a time; the
concept guide tells the data engineer what each class means first. For how the context engineer
and the data engineer share this work, see the
[practitioner workflow](https://github.com/Cnext-eu/kairos-ontology-toolkit/blob/main/docs/guide/practitioner/context-and-data-engineer-workflow.md).
