# Logistics Accelerator dbt Silver Design Plan

**Status:** Draft — toolkit prerequisites implemented by issue #226; accelerator package pending  
**Date:** 2026-07-21
**Scope:** Kairos Logistics Accelerator Pack  
**Target platforms:** Microsoft Fabric and Azure Databricks

## 1. Decision

The Logistics Accelerator should ship a first, source-neutral Silver design and a
runnable dbt reference implementation.

It should not ship a supposedly universal production transformation tied to one TMS,
ERP, carrier, or warehouse schema. The accelerator defines the canonical Silver
contract; a client hub binds that contract to real sources through Bronze vocabularies,
SKOS mappings, and, where necessary, contracted custom dbt transformations.

The accelerator package should therefore contain:

1. reviewed Silver defaults for selected logistics reference classes;
2. aspirational dbt model contracts generated from those defaults;
3. synthetic source vocabularies and mappings for a runnable example;
4. generated Fabric and Databricks reference output; and
5. conformance tests proving the example implements the canonical contract.

## 2. Goals

- Give adopters an immediately understandable logistics Silver target.
- Demonstrate how the industry models become practical dbt entities.
- Reuse natural keys, relationships, SCD policy, data types, and tests across hubs.
- Keep ontology and Silver annotations authoritative over generated artifacts.
- Allow client hubs to override defaults without modifying reference ontologies.
- Support an incremental adoption path instead of requiring the entire logistics graph.
- Provide equivalent semantic contracts for Fabric and Databricks.

## 3. Non-goals

- A universal mapping from every logistics source system.
- Production-ready business rules for a specific carrier, forwarder, or terminal.
- Customer-specific identifiers, PII, credentials, endpoints, or proprietary samples.
- Hand-maintained dbt SQL that duplicates ontology projection logic.
- Projection of every imported DCSA, MMT, BSP, TIC, IMO, WCO, and sustainability class.
- Gold facts, dimensions, measures, or Power BI models in the first delivery.
- Runtime MDM matching, survivorship, or stewardship workflows.

## 4. Design principles

### 4.1 Contract first, binding second

The accelerator defines stable target contracts before a client source is known.
Aspirational stubs may expose those contracts during design. A real source mapping
clears the aspirational state and causes projection to generate the bound model.

### 4.2 Selective materialisation

The full accelerator imports eight broad industry models. Only an opinionated,
high-value subset should become default Silver tables. Client domains should continue
to import only the modules they need, as prescribed by the logistics client-hub
blueprint.

### 4.3 Generated artifacts are derivative

OWL ontologies, Silver default annotations, source vocabularies, and SKOS mappings are
the source artifacts. Committed dbt output is a reference snapshot and must be
reproducible. It must not become a second design authority.

### 4.4 Portable semantics, adapter-specific SQL

Fabric and Databricks outputs share entity grain, keys, relationships, tests, and
documentation. Adapter-specific types, materialisations, and SQL remain separate
generated concerns.

### 4.5 Safe extension

Reference-model defaults provide fallback values. A client
`{domain}-silver-ext.ttl` remains the highest-priority authority and may override SCD
policy, natural keys, inclusion, physical names, or other supported annotations.

### 4.6 Promote evidence, not legacy shapes

Existing warehouses, report models, mapping workbooks, and hand-authored dbt are
important discovery evidence, but they are not automatically canonical contracts.
Classify each finding before promoting it:

| Evidence class | Governed destination |
|---|---|
| Industry-stable entity, grain, identifier, or relationship | Reference ontology and accelerator Silver defaults |
| Straight source-to-property equivalence | Bronze vocabulary and SKOS mapping |
| Source-specific joins, unions, windows, deduplication, parsing, or grain changes | Contracted intermediate dbt transformation |
| Organisation policy, alias, exclusion, survivorship, or local code | Client mapping, seed, hub extension, or governed MDM policy |
| Report role, current-state reduction, KPI, aggregation, or display classification | Gold |
| Diagnostic helper, duplicated logic, or mixed-grain compatibility shape | Staging/diagnostic output or reject |

The promotion test is portability: a default belongs in the accelerator only when its
meaning and grain remain valid for a structurally different logistics source and
organisation. Strong evidence from one source can justify an example implementation,
but not an industry-wide default.

### 4.7 Grain and identity precede columns

Every Silver entity must distinguish four identities:

1. **Business grain** -- the real-world occurrence represented by one row.
2. **Source identity** -- `source_system` plus an immutable `source_record_id`.
3. **Natural key** -- business properties that identify the occurrence within a stated
   scope; source-local keys must be labelled as such.
4. **Warehouse identity** -- generated surrogate key and projection-scoped IRI.

Do not merge records from different systems merely because display numbers overlap.
Cross-source survivorship is allowed only after an explicit equivalence or MDM decision.
Source priority may choose attributes for already matched identities; it must not be the
matching rule itself.

## 5. Proposed first vertical slice

The first release should cover the minimum cross-domain flow needed to explain a
logistics movement:

| Canonical entity | Business grain | Purpose |
|---|---|---|
| Party | One logistics party | Customer, shipper, consignee, carrier, or service provider |
| Location | One canonical location | Site, port, terminal, depot, or addressable place |
| TransportOrder | One transport service order | Commercial request for transport |
| Consignment | One consignment | Goods movement responsibility and commercial grouping |
| Shipment | One operational shipment | Execution unit moving cargo through a journey |
| TransportEquipment | One equipment item | Container, trailer, swap body, or similar asset |
| TransportMovement | One planned or actual movement leg | Movement between locations by a transport mode |
| TransportEvent | One event occurrence | What happened, when, where, and to which subject |

The exact class URIs must be selected from the imported DCSA, MMT, BSP, and
Supply Chain bridge ontologies before implementation. New accelerator classes should
only be introduced where the reference models have a documented semantic gap.

Customs, dangerous goods, terminal operations, demurrage and detention,
sustainability, invoicing, and MDM should follow as later vertical slices.

## 6. Silver policy to design

Every materialised class must have explicit, reviewed defaults rather than relying on
projector conventions.

| Concern | Initial policy |
|---|---|
| Silver inclusion | Explicit allow-list of first-slice classes |
| Schema ownership | Owning client domain, never one global logistics schema |
| Table naming | Plain entity names; reserve fact/dimension prefixes for Gold |
| Natural keys | Industry identifier where stable; otherwise require client override |
| Surrogate keys | Generated by the Kairos dbt projection |
| IRI lineage | Retained on every normal entity |
| SCD type | Type 2 for mutable business entities; Type 1 only where history has no value |
| Events | Append-only occurrence grain by default; derive current state downstream |
| Reference data | Explicitly identified and reviewed for safe inlining |
| Foreign keys | Explicit for imported object properties lacking cardinality |
| Temporal FK resolution | Join to the intended current or as-of parent version explicitly |
| Inheritance | Preserve semantic annotation; Silver projection may flatten subtypes |
| Nullability | Derived from SHACL and explicit overrides |
| PII | Isolate sensitive attributes in GDPR satellites where applicable |
| Row lineage | Retain source system, immutable source record ID, and ingestion/load context |
| Change detection | State explicitly whether relationship/FK changes create entity history |
| Audit envelope | Use the standard generated load, hash, and soft-delete columns |
| Multi-source conformance | Conform each source first; match and survive only under governed identity rules |

Natural keys and relationship direction are design checkpoints, not assumptions. A
reference default should be omitted when the industry models do not provide sufficient
evidence for a safe universal choice.

### 6.1 Findings from the generated-versus-legacy comparison

The July 2026 review compared the generated industry-model-based package in
`ontology-hub/output/medallion/dbt` with the hand-authored prototype and its Qargo
mapping notes. The two inputs serve different purposes:

| Concern | Generated accelerator-aligned package | Legacy prototype and mapping notes | Design conclusion |
|---|---|---|---|
| Authority | Traceable to ontologies, claims, extensions, mappings, and contracted transforms | Hand-authored report refactor | Keep generated artifacts derivative; use legacy only as evidence |
| Entity design | Separates Booking, TransportOrder, Consignment, TransportMovement, TransportStop, TransportLeg, allocation, Party, and reference-data grains | Contains useful entities but also report roles, helpers, duplicate leg shapes, and mixed grains | Prefer explicit industry grains and associations over one table per legacy report shape |
| Party | One `TradeParty` target with role semantics | Separate customer and carrier masters; supplier is actually order x subcontractor | Keep one Party identity; model roles and assignments separately |
| Location | `OperationalLocation`, `Address`, and `Country` are separate governed grains | Strong role-neutral location insight, but loading/unloading tables are order-role projections | Keep role-neutral Silver locations; derive loading/unloading views in Gold |
| Order and execution | Stable source ID for TransportOrder; explicit movement, stop, and adjacent-stop leg grains | Valuable `Or-*` admission, stop, route, and sailing evidence, but report-facing order/leg shapes differ | Preserve source admission in a contract; do not universalise Qargo naming rules |
| Events and state | Canonical event-oriented targets are planned | Empty-unit event history is reduced to run-date-dependent current availability | Keep immutable events in Silver and derive current state in Gold |
| Multi-source logic | Current executable slice is Qargo-first | Demonstrates namespace collision handling, source rollup, lineage, and priority survivorship | Retain the patterns, but require entity matching before survivorship |
| Transformation boundary | Complex admission, adjacency, associations, and conformance live in contracted intermediates with contracts and unit tests | Complex route fallback, geozone ranking, JSON expansion, and report parity are embedded repeatedly in Silver SQL | Reuse the knowledge in one governed transformation or seed, not duplicated entity SQL |
| Testing | PK/IRI tests and strong intermediate contracts/unit tests exist | Mostly manual build and post-build evidence; no declarative Silver model tests | Add grain, FK, status/code, temporal, and adapter conformance tests |
| Lineage | Mapping and ontology provenance are strong, but final Silver rows do not consistently retain source-row lineage | `source_system`, `source_record_id`, and source-file lineage are explicit | Add row-level lineage to the canonical contract without importing client labels |
| Physical quality | Generated SCD and FK patterns are consistent | Prototype includes practical same-day and survivorship guards | Treat generated SQL as testable output; do not assume projection implies correctness |

The legacy model disposition should therefore be:

| Disposition | Legacy concepts |
|---|---|
| Align to canonical Silver | `transport_order`; `shipment` into Consignment/TransportMovement; `transport_leg` plus `load_delivery_leg` into governed Stop/Leg grains; customer/carrier into Party roles; `location`; supplier into an assignment; `unit_type` into EquipmentType; charge and haulage lines into Financial entities; empty movements into immutable events |
| Keep provisional pending identity evidence | `shipping_route`, `vessel_departure`, equipment identity, cross-source Party survivorship |
| Move or derive in Gold | `loading_point`, `unloading_point`, `market`, `calendar`, `order_volume`, current empty-unit availability, transit-time KPI |
| Keep only as contracted helper or diagnostic | `transport_operation`, geozone candidate selection, route fallback, JSON expansion, `qargo_empty_movement` diagnostics |

### 6.2 Silver implementation rules generalised from the comparison

1. Write a one-sentence grain contract and key scope before selecting properties.
2. Require an immutable source identity even when a business number is present.
3. Namespace source-local identifiers; never solve collisions with an undocumented
   prefix embedded in a supposedly universal natural key.
4. Keep source admission, normalization, deduplication, and fan-out prevention in a
   contracted transform when they exceed ordinary mapping expressions.
5. Resolve Silver FKs against an explicit temporal view. For current-state loading,
   join only to current SCD2 parent rows; for as-of analysis, use effective-date logic.
6. Decide per relationship whether an FK change is part of the child's history and
   include it in change detection when it is.
7. Use timestamp precision or an explicit sequence when more than one valid change per
   entity per day is possible.
8. Store business aliases, port-code normalization, exclusion lists, and classifications
   as governed data or client rules, not accelerator-wide SQL `CASE` expressions.
9. Preserve intentional non-equivalence as metadata: an unmapped field stays null with
   a reason rather than being populated from a semantically similar field.
10. Test natural-key grain, source identity, current-row uniqueness, FK integrity,
    accepted status/code values, intentional-null assumptions, and cross-adapter contract
    equivalence.

The present generated snapshot also exposes release blockers that the accelerator
conformance suite must catch: unresolved target-first models must not emit null keys into
incremental SCD models; SCD2 parent joins must not fan out over historical rows; schema
names must be adapter-safe; and row-level source lineage must survive the final Silver
projection.

## 7. Package contents

The logistics accelerator should evolve toward the following structure:

```text
ontology-reference-models/
  accelerator-packs/
    logistics/
      current/
        logistics-accelerator.ttl
      silver-defaults/
        party-silver-defaults.ttl
        location-silver-defaults.ttl
        transport-order-silver-defaults.ttl
        consignment-silver-defaults.ttl
        shipment-silver-defaults.ttl
        equipment-silver-defaults.ttl
        movement-silver-defaults.ttl
        event-silver-defaults.ttl
      examples/
        synthetic-forwarder/
          integration/
            sources/
          model/
            ontologies/
            extensions/
            mappings/
          expected/
            fabric/
            databricks/
      contracts/
        logistics-silver-contract.yaml
      docs/
        silver-model.md
        silver-erd.mmd
```

The final locations should be reconciled with toolkit catalog discovery and packaging
rules before implementation. In particular, reference defaults must use the
`{ontology-stem}-silver-defaults.ttl` naming convention expected by the projector.

## 8. Reference implementation

The runnable example should model a fictitious freight forwarder and contain no client
data. It should include:

- small CSV or seed data for orders, consignments, shipments, equipment, legs, events,
  parties, and locations;
- Bronze vocabularies generated from those source structures;
- explicit table-to-entity and column-to-property mappings;
- at least one direct mapping, transformed value, deduplication rule, FK lookup, and
  multi-source union;
- a contracted intermediate dbt model only where the example genuinely needs joins,
  windows, aggregation, JSON expansion, fallback logic, or a grain change;
- projected Silver models for Fabric and Databricks; and
- dbt tests derived from SHACL plus explicit grain and referential-integrity tests.

The example SQL must remain source-conformance logic. The generated Silver boundary
continues to own ontology alignment, surrogate keys, IRIs, SCD behavior, supported FK
resolution, tests, and documentation.

## 9. Contract and compatibility

Create a machine-readable manifest describing each accelerator Silver entity:

- canonical class URI;
- business grain;
- natural-key properties, when universally safe;
- required and optional properties;
- FK targets and direction;
- SCD and reference-data policy;
- applicable industry standards;
- supported adapters; and
- maturity level: experimental, preview, or stable.

Compatibility rules:

1. Adding an optional entity or property is backward-compatible.
2. Changing grain, a natural key, FK direction, or SCD behavior is breaking.
3. Removing or renaming a stable model is breaking.
4. Generated output must record the accelerator and toolkit versions.
5. Client overrides are permitted but must be visible in generated documentation.

The first release should be marked **preview** until it has been validated against at
least two structurally different synthetic or public source shapes and both adapters.

## 10. Implementation phases

### Repository ownership and delivery sequence

Implementation is deliberately split across three repositories. A change belongs in
the lowest scope at which its behavior is valid:

| Repository | Owns | Must not contain |
|---|---|---|
| `kairos-ontology-toolkit` | Generic projection behavior, annotation support, temporal SCD/FK handling, unresolved-stub safeguards, adapter-safe naming, row-lineage generation, generated dbt tests, and cross-adapter conformance | CLdN/Qargo identifiers, filters, aliases, mappings, or business policy |
| `cldn-ontology-hub` | The executable CLdN pilot: Qargo vocabularies and mappings, contracted transformations, client Silver overrides, source admission, local aliases, survivorship policy, fixtures, and validation evidence | Claims that a CLdN-specific rule is an industry default |
| `ontology-reference-models` | Proven source-neutral logistics classes and relationships, accelerator Silver defaults, compatibility manifest, documentation, synthetic example, and expected reference output | Client data, proprietary rules, or production Qargo bindings |

#### Toolkit change requests

Raise the following change requests in `kairos-ontology-toolkit` before treating the
accelerator workflow as complete.

**CR-TK-01 -- Complete managed OWL imports**

When approved claims use classes or properties from an installed reference-model
module, `claims-to-silver-ext` and `kairos-design-domain` must ensure that the owning
domain ontology has a managed `owl:imports` triple for that module's ontology IRI.
Prefixes, catalog resolution, claims, and extension annotations are not substitutes for
OWL imports.

The change must:

- derive imports from approved imported claims and accelerator `data-domains.yaml`;
- use ontology document IRIs rather than term namespaces ending in `#`;
- preserve authored TTL outside the managed block;
- remove stale managed imports when no approved claim or configured module requires
  them;
- behave identically for scaffolded and already-existing domain ontologies; and
- add regression coverage for the current missing MMT Consignment and DCSA Booking
  import cases.

Validation must report an external class or property used by a domain ontology without
a matching direct or explicitly accepted transitive import. The warning should identify
the term, expected ontology IRI, and owning managed source.

**CR-TK-02 -- Reference-module activation without ontology copying**

An accelerator should be able to activate a reference-model module as a coherent design
surface. Activation means:

1. add and version-pin its `owl:imports` dependency;
2. expose the full imported class hierarchy, descendant subclasses, properties, named
   individuals, and provenance through the resolved import closure;
3. select a reviewed projection subset through claims and Silver/Gold defaults; and
4. emit a deterministic closure inventory showing what is available, selected,
   excluded, inherited, and projected.

Do **not** deep-copy reference classes or properties into the authored client-domain
TTL. OWL imports already provide their definitions and inheritance. Copying them with
the same IRIs creates duplicate ownership and version drift; minting new local IRIs
creates a fork that loses standard identity and interoperability.

If a self-contained artifact is required for deployment, offline validation, or release
inspection, the toolkit may generate a flattened ontology bundle as **derived output**.
That bundle must preserve original IRIs, record source module/version/provenance, include
a closure hash, be reproducible, and never become an editable design authority.

The proposed accelerator module profile should therefore contain:

| Field | Purpose |
|---|---|
| Module ontology IRI and version | Stable catalog-resolved dependency |
| Root classes | Reviewed entry points such as `dcsa-booking:Booking` |
| Descendant policy | Include all, include selected branches, or explicit exclusions |
| Projection policy | Explicit claimed classes; importing never implies materialising everything |
| Default annotations | Source-neutral natural-key, SCD, FK, and type guidance where safe |
| Closure inventory/hash | Reproducible account of inherited classes and properties |
| Local-extension boundary | Classes/properties the client owns rather than the module |

Recursive activation must not silently project the complete module. Imported semantics
may be broad while physical Silver materialisation remains an explicit allow-list.

**CR-TK-03 -- Canonical ontology closure and semantic index**

The current toolkit has multiple ontology lookup paths with different semantics. Some
parse one Turtle file, some load only first-level catalog imports, some receive a
caller-merged graph, and some skill instructions use `cat` or `grep`. An LLM must never
be expected to reconstruct Turtle abbreviation, blank-node axioms, inheritance, or an
import graph from serialized text.

Introduce one canonical ontology-loading service and require every semantic consumer to
use it. The service must return:

- an rdflib graph or dataset containing the complete catalog-resolved transitive
  `owl:imports` closure;
- an import manifest recording ontology IRI, resolved path, version, source hash,
  parent import, and closure hash;
- structured diagnostics for unresolved, ambiguous, cyclic, duplicate, or unsupported
  imports; and
- a deterministic semantic index suitable for projectors, validators, inventories, and
  LLM prompt builders.

The loader must use a worklist plus visited sets for both `owl:imports` and chained OASIS
`nextCatalog` files. It must detect RDF format from the resolved file, handle import
cycles without recursion failure, parse each resolved source once, and fail closed on a
missing required import unless an explicit degraded-mode override is recorded.

Parsing RDF syntax and applying ontology semantics are separate concerns. rdflib parses
Turtle correctly but does not by itself apply OWL entailment. Define supported semantic
profiles rather than claiming unrestricted OWL DL reasoning:

| Profile | Required interpretation |
|---|---|
| `asserted` | Parsed triples from the complete import closure |
| `rdfs` | Transitive subclasses/subproperties, inherited domain properties, and RDFS domain/range consequences |
| `kairos-design` | RDFS plus equivalent classes/properties, inverse properties, named individuals, and the OWL restrictions/cardinalities used by Kairos |
| `owl-rl` | Optional standards-based OWL RL closure for consumers that require it and can accept the cost |

The semantic index must preserve provenance for every result: directly asserted,
inherited, inferred, or imported from a named module. At minimum it must expose:

- classes, ancestors, descendants, and specialization distance;
- directly declared and inherited datatype/object properties;
- property domain, range, subproperty, equivalent-property, and inverse-property links;
- equivalent-class sets;
- named individuals and their classes;
- supported restriction expressions, including qualified and unqualified cardinality,
  `someValuesFrom`, `allValuesFrom`, intersections, and unions;
- ontology/version metadata; and
- import depth and source module for each term.

Inventories become serialized views of this semantic index, not independent single-file
parses. Their freshness check must include the closure hash so a changed transitive
dependency marks downstream inventories stale. Deduplication must use full term URIs,
never local names such as `Party`.

All semantic consumers must use the same service and declare their required profile:

| Consumer | Minimum profile |
|---|---|
| Inventory generation and class/property lookup | `kairos-design` |
| Source analysis and alignment prompts | `kairos-design` inventory/index |
| Domain, Silver, and Gold design skills | `kairos-design` inventory/index |
| Projection and FK/inheritance discovery | `kairos-design` |
| Semantic validation and SHACL data graph | `rdfs` or `kairos-design` as declared |
| Neo4j, prompt, report, and search projectors | Same preloaded closure as other projectors |
| Syntax validation of one authored file | `asserted`, single-file mode explicitly allowed |

LLM prompts must receive bounded structured data from the semantic index, never raw TTL
as the authoritative source. If context is truncated, the prompt must state the total
term count, included count, selection rule, omitted modules, import status, semantic
profile, and closure hash. The LLM may rank or explain already-resolved concepts; it may
not infer import traversal, inheritance, equivalence, restriction expansion, or term
identity.

Replace skill-level semantic text scanning with deterministic commands:

```text
kairos-ontology resolve-ontology <iri>
kairos-ontology show-class-inventory --domain <domain> --profile kairos-design
kairos-ontology show-source-schema --system <system>
kairos-ontology explain-term <iri>
```

`cat` and `grep` remain acceptable for debugging serialization, comments, or literal
text, but never as the source for class, property, import, mapping, or source-schema
decisions.

The audit identified these immediate defects to include in the CR:

1. catalog loading follows only first-level `owl:imports`;
2. chained `nextCatalog` traversal has no cycle guard;
3. inventories parse one file and omit inherited properties, named individuals,
   equivalence, restrictions, subproperties, inverses, and ontology version;
4. inventory freshness hashes only the root source file, not its import closure;
5. `propose-alignment` does not receive the hub inventory directory from its CLI path;
6. inventory merging deduplicates some classes by local name rather than URI;
7. source analysis exposes a bounded class-label list without complete properties or
   an explicit truncation disclosure;
8. prompt and Neo4j projectors reparse single files or filter cross-namespace terms;
9. unresolved imports can remain warnings while validation/projection continues on an
   incomplete graph; and
10. domain/status/Silver skill checks use raw `cat` or `grep` for semantic questions.

Required regression fixtures:

- three-level imports (`A -> B -> C`) with terms used from `C`;
- cyclic imports and cyclic `nextCatalog` references;
- an unresolved required import that blocks semantic validation/projection;
- mixed Turtle, RDF/XML, JSON-LD, and OWL files resolved through one catalog;
- inherited properties over a multi-level subclass chain;
- duplicate local names in different namespaces;
- equivalent/inverse/subproperty relationships;
- named-individual code lists;
- blank-node restrictions and RDF lists;
- a changed transitive import that invalidates the closure hash;
- identical semantic-index output for inventory, alignment, validation, and projection
  consumers; and
- prompt snapshots proving provenance, profile, closure completeness, and truncation are
  disclosed.

Use the following delivery order:

1. Fix generic projection blockers in `kairos-ontology-toolkit` and release the required
   toolkit version.
2. Implement and validate the first vertical slice in `cldn-ontology-hub` against real
   Qargo evidence using that toolkit version.
3. Classify the pilot findings using section 4.6 and promote only source-neutral
   contracts into `ontology-reference-models`.
4. Regenerate the accelerator's synthetic Fabric and Databricks examples and run the
   compatibility suite.
5. Reconsume the released accelerator defaults in `cldn-ontology-hub`; retain local
   overrides only where CLdN intentionally differs.

### Toolkit delivery status

Issue #226 implements the generic toolkit scope in this plan:

- CR-TK-01 now derives idempotent managed imports from approved imported claims and typed
  module activation, preserves authored Turtle, removes stale managed imports, and reports
  missing owning ontology imports before semantic projection.
- CR-TK-02 now supports version-pinned module profiles, deterministic activation
  inventories, reviewed roots and exclusions, explicit projection allow-lists, default
  annotation provenance, accepted transitive dependencies, and local-extension boundaries
  without copying imported definitions.
- Silver/dbt generation now rejects unresolved bound incremental keys, implements
  timestamp SCD1/SCD2 lifecycle for single- and multi-source models, prevents current-parent
  historical fan-out, requires explicit effective-time evidence for as-of joins, controls
  FK change detection, preserves Bronze-primary-key row lineage, validates portable
  identifiers, emits generated contract tests, and proves Fabric/Databricks semantic
  equivalence in scenarios.

CR-TK-03 remains owned by issue #224. The logistics class selection, accelerator defaults,
synthetic package, and client pilot remain intentionally outside issue #226 and in their
owning repositories.

Promotion into `ontology-reference-models` requires evidence from at least two
structurally different source or operating archetypes, or direct normative support from
an adopted industry standard. Until then, a candidate remains a client-hub decision.
For example, the current `Consignment` to `TransportOrder` relationship remains in
`cldn-ontology-hub` until its cardinality, direction, and applicability beyond the Qargo
model have been demonstrated.

### Phase 1: Class and grain selection

1. Resolve the concrete class URIs for the first vertical slice.
2. Document entity grain and lifecycle boundaries.
3. Identify overlaps between DCSA, MMT, BSP, and Supply Chain bridge concepts.
4. Reject duplicate entities or define explicit alignment.
5. Produce a reviewed canonical ERD.

**Exit criterion:** every selected entity has one unambiguous grain, owning domain, and
reference-model authority.

### Phase 2: Silver defaults

1. Add explicit inclusion, SCD, reference-data, and inheritance annotations.
2. Review natural keys and mark uncertain keys as requiring client configuration.
3. Declare imported-property FKs and parent-to-child FK direction.
4. Add data-type and nullability overrides only where semantically justified.
5. Add GDPR satellites for sensitive party or contact information.

**Exit criterion:** annotation completeness checks pass and no default relies on an
unsupported industry assumption.

### Phase 3: Synthetic source and mappings

1. Define the fictitious forwarder source model.
2. Generate Bronze vocabularies.
3. Map every in-scope source table and column.
4. Add realistic transformations and cross-entity joins.
5. Pass the pre-Silver claims gate without a warn-only override.

**Exit criterion:** all affinity-assigned source tables are mapped and mapping coverage
is complete for the example's declared scope.

### Phase 4: Projection and adapter validation

1. Generate Silver DDL, ERD, and dbt output for Fabric.
2. Generate equivalent output for Databricks.
3. Compile with each dbt adapter.
4. Execute the synthetic fixture where test infrastructure is available.
5. Run SHACL-derived tests, grain tests, and FK-shape tests.
6. Review offline Silver sample-audit findings.

**Exit criterion:** both adapters implement the same semantic contract and all
deterministic and runtime checks pass.

### Phase 5: Packaging and documentation

1. Add the Silver capability and maturity level to `manifest.yaml`.
2. Document adoption, override, and regeneration workflows.
3. Publish the canonical and physical ERDs.
4. Add a reproducibility check for committed generated reference output.
5. Document versioning and breaking-change rules.

**Exit criterion:** a new hub can consume the defaults, run the example, and replace the
synthetic binding with its own sources without editing accelerator ontologies.

### Phase 6: Pilot feedback

1. Test the package against a freight-forwarder-shaped source.
2. Test it against a carrier- or terminal-shaped source.
3. Compare required overrides and missing concepts.
4. Promote only broadly reusable corrections into the accelerator defaults.

**Exit criterion:** the preview contract has evidence from at least two materially
different source shapes.

## 11. Acceptance criteria

- The first-slice classes and properties trace to named industry/reference models.
- Every projected class has explicit applicable Silver annotations.
- Every external term used by an authored ontology is covered by a managed direct import
  or a documented accepted transitive dependency.
- Accelerator module activation exposes a reproducible import-closure inventory without
  duplicating reference definitions into authored hub TTL.
- Every semantic lookup declares its ontology profile and uses the canonical
  catalog-resolved closure/index rather than parsing serialized TTL text independently.
- Every natural key has documented evidence or is explicitly client-required.
- Every entity documents business grain, source identity, natural-key scope, surrogate
  key, and IRI convention separately.
- Every FK has reviewed cardinality and placement.
- Every SCD2 FK resolution declares current-state or as-of semantics and has a
  relationship test.
- Every SCD2 model defines sub-day change behavior and whether FK changes affect history.
- Every final Silver row retains source-system and immutable source-record lineage.
- The synthetic example contains no PII or proprietary content.
- Claims and mapping coverage pass for the declared example scope.
- Fabric and Databricks dbt projects compile.
- Runtime fixture tests prove grain uniqueness and expected relationships.
- Contract tests reject unresolved null-key incremental models and historical FK fan-out.
- Generated output is reproducible from committed source artifacts.
- Client extensions override defaults without modifying the accelerator package.
- Documentation clearly distinguishes canonical contracts, examples, and production
  source bindings.

## 12. Risks and mitigations

| Risk | Mitigation |
|---|---|
| The full industry graph produces an unusably large Silver layer | Materialise an explicit first-slice allow-list |
| DCSA and MMT concepts overlap | Select one authority per grain and document alignments |
| Natural keys differ by organisation | Default only evidence-backed keys; otherwise require an override |
| Example SQL becomes mistaken for production logic | Label it synthetic and keep mappings/contracts authoritative |
| Generated snapshots drift from source artifacts | Add deterministic regeneration checks |
| Fabric and Databricks behavior diverges | Validate the same semantic contract independently per adapter |
| Accelerator defaults constrain client design | Preserve hub-level override priority and document every override |
| Sensitive party data is flattened into general tables | Review GDPR satellites and use synthetic data only |
| Legacy report shapes become canonical entities | Apply the evidence-classification and promotion test before modeling |
| Source-priority survivorship merges different real-world entities | Require explicit matching/equivalence before survivorship |
| SCD2 parent history multiplies child rows during FK resolution | Require current/as-of join semantics and relationship tests |
| Source lineage is lost after semantic projection | Make source system and immutable source record ID part of the Silver contract |
| Source-local aliases leak into industry defaults | Keep aliases, filters, and code normalization in client mappings, seeds, or transforms |
| Deep-copied reference modules drift from upstream releases | Import by ontology IRI; allow only reproducible flattened bundles as derived output |
| Recursive module activation creates an unusably large Silver schema | Separate semantic import closure from an explicit projection allow-list |
| Different toolkit consumers see different ontology subsets | Route all semantic lookup through one versioned closure/index service |
| LLM decisions depend on Turtle serialization or truncated undisclosed context | Provide structured semantic-index slices with provenance and truncation metadata |
| A transitive dependency changes without inventory invalidation | Hash and persist the complete resolved import closure |

## 13. Open design decisions

1. Which exact DCSA/MMT/BSP class is authoritative for Shipment and TransportOrder?
2. Is Consignment distinct from Shipment in every supported archetype?
3. Which identifiers are safe universal natural keys versus example-only keys?
4. Should TransportEvent be one polymorphic table or separate event families?
5. Which small code lists may be safely inlined without harming interoperability?
6. Should generated adapter output be committed, release-attached, or produced only in
   CI?
7. Should the first slice include invoice and charge entities to demonstrate
   Buy-Ship-Pay, or defer them to the second release?
8. What maturity and compatibility metadata should be added to the existing accelerator
   manifest schema?
9. Which relationship changes must create a new SCD2 child version, and which are only
   consequences of parent versioning?
10. Should the accelerator mandate source-system and source-record columns physically,
    or expose them through a standard lineage satellite?
11. What manifest syntax should express module roots, descendant inclusion, exclusions,
    and version pins for accelerator module activation?
12. Which semantic profile should each existing projector and validation command require,
    and should unresolved imports ever be non-blocking outside explicit degraded mode?

## 14. Recommended delivery

Deliver this as a **preview Logistics Silver Starter** rather than a complete logistics
warehouse. Start with the eight-entity operational slice, one synthetic freight
forwarder binding, and both supported adapters. Use pilot feedback to refine the
contracts before adding customs, finance, terminal, sustainability, and MDM slices.

This creates immediate implementation value while preserving Kairos's central
principle: industry semantics define the reusable target, and each organisation's
source evidence determines the actual transformation.
