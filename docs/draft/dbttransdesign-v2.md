# Contracted dbt Transformation Extensibility — Revised Design

**Status:** Revised draft

**Scope:** Kairos ontology-to-dbt projection

**Targets:** Microsoft Fabric and Azure Databricks

**Supersedes:** `docs/draft/dbttransdesign.md` when approved

## 1. Decision summary

Kairos should support advanced Bronze-to-Silver transformations by bundling contracted,
handwritten dbt models into the generated hub dbt package.

The custom model owns relational logic that is not suitable for RDF authoring: joins,
windows, aggregations, JSON expansion, source-specific fallback rules, source unions, and
grain changes. The generated Silver model remains the ontology-aligned public boundary and
owns surrogate keys, IRIs, supported foreign-key resolution, SCD behavior, tests, and
documentation.

This revision makes the following decisions:

1. Reuse `kairos-ext:silverSourceRef`; do not add `silverTransformationRef`.
2. Treat the dbt model contract YAML as the authoritative physical output schema.
3. Generate the virtual-source Turtle vocabulary deterministically from that contract.
4. Commit the generated vocabulary for mapping, review, and reporting, but reject manual
   drift.
5. Bundle custom models, schema YAML, data tests, unit tests, and namespaced macros.
6. Permit only toolkit-approved dbt package dependencies in the first delivery.
7. Support Microsoft Fabric and Azure Databricks from the first delivery.
8. Validate all custom inputs before writing generated output; defer atomic directory
   replacement.
9. Keep publication policy with the ontology-hub owner. The toolkit assembles the package
   but does not automatically publish organization-specific SQL.
10. Regenerate managed virtual-source vocabularies only through
    `kairos-ontology sync-dbt-contracts`; projection validates freshness without writing
    source artifacts.
11. Select one adapter per projection with `project --platform fabric|databricks`, preserving
    `output/medallion/dbt/`. Dual-adapter CI uses separate temporary output roots.
12. Validate generated packages with `validate-dbt --platform ...`; `dbt parse` is the
    offline gate, while connection-dependent compile failures are reported as
    environment-blocked.
13. Provide an interactive `kairos-develop-dbt-transformation` skill for evidence-grounded
    authoring and updates.

The design must not:

- encode a SQL execution graph or SQL AST in RDF;
- inject arbitrary SQL fragments into generated templates;
- create a second source-to-property mapping mechanism;
- create a second Silver source-routing annotation;
- depend on models that exist only in an unknown consuming project;
- allow custom files to override toolkit-owned resources;
- claim that `dbt parse` or `dbt compile` proves runtime grain or data quality; or
- require a major toolkit release unless implementation introduces a breaking change.

## 2. Problem

Existing Kairos mappings handle direct columns, expressions, filters, deduplication,
standard foreign-key lookups, and independently normalized sources combined with
`UNION ALL`.

Some Silver entities require substantially richer conformance logic. A Shipment example
may combine orders, stops, bookings, resources, companies, JSON-expanded values, and
legacy reporting data using:

- bridge construction;
- multi-table joins;
- conditional aggregation;
- window ranking and preferred-record selection;
- route fallback rules;
- reusable macros;
- multiple grain changes; and
- cross-system conformance.

Encoding this implementation in RDF would duplicate dbt while weakening SQL authoring,
compilation, debugging, and testing. Making the final Silver entity entirely handwritten
would instead bypass ontology-driven guarantees.

Kairos therefore needs a governed boundary between:

1. native dbt source conformance; and
2. generated ontology-aligned Silver projection.

## 3. Design principles

### 3.1 One concern, one authority

| Concern | Authority |
|---|---|
| Relational transformation logic | Custom dbt SQL |
| Physical output names, data types, grain assertion, and key columns | dbt model contract YAML |
| Business meaning | Ontology and glossary |
| Semantic grain and natural-key properties | Ontology and Silver extension |
| Virtual-source RDF vocabulary | Deterministically generated from the dbt contract |
| Source-to-domain semantics | Existing SKOS mapping |
| Silver routing | Existing `kairos-ext:silverSourceRef` |
| Silver keys, IRI, SCD, supported FKs | Silver extension plus generated model |
| Decision rationale, evidence, confidence, and approval | `meta.kairos.decisions` |
| Expected behavior | dbt unit and data tests |
| Runtime truth | Materialized warehouse relation |

No two user-authored artifacts may independently define the same physical schema.

The distinction between semantic and physical identity is intentional. The Silver
extension identifies the ontology properties that form the business natural key. The dbt
contract identifies the custom model columns that realize that key at its output boundary.
Kairos validates their alignment through SKOS mappings rather than treating either
representation as a substitute for the other.

### 3.2 Source-conformed to business-conformed

Custom models belong in an `intermediate` layer. They convert source-specific structures
into a stable relation at a declared grain. The generated Silver model converts that
relation into the ontology-aligned business entity.

This follows dbt's recommended progression from source-conformed staging through
purpose-specific intermediate logic to business-conformed models.

### 3.3 Portable guarantees and adapter-specific guarantees

Fabric and Databricks share the same semantic contract, but their SQL dialects,
materializations, type systems, and supported constraints differ.

The design separates:

- deterministic checks that Kairos runs without a warehouse;
- dbt graph and compilation checks run per adapter; and
- runtime assertions executed on each supported adapter.

Support for an adapter means the custom transformation passes all three applicable layers.

## 4. Semantic prerequisite: resolve grain and identity

No custom transformation may be registered until its output grain and identity are
approved.

For each transformation, confirm:

1. the target ontology class;
2. one canonical row grain;
3. the natural key at that grain;
4. whether records from different source systems can represent the same entity;
5. deduplication or survivorship rules when identities overlap;
6. null behavior for every natural-key component; and
7. whether the output is an entity or an association.

For example, a row identified by shipment plus order may represent `ShipmentOrder` or
`ShipmentMovement`, not `Shipment`. Projection must fail when the declared key shape does
not match the approved grain contract.

## 5. Repository layout and ownership

```text
integration/
  transforms/
    dbt/
      models/
        intermediate/
          shipment/
            int_shipment_conformed.sql
            int_shipment_conformed.yml
      macros/
        shipment/
          logistics__company_description.sql
      tests/
        shipment/
          assert_int_shipment_conformed_grain.sql

  sources/
    custom-transformations/
      int_shipment_conformed.vocabulary.ttl

model/
  mappings/
    custom-transformations/
      int_shipment_conformed-to-logistics.ttl
  extensions/
    logistics-silver-ext.ttl

output/
  medallion/
    dbt/
      models/
        intermediate/
          shipment/
            int_shipment_conformed.sql
            int_shipment_conformed.yml
        silver/
          logistics/
            shipment.sql
      macros/
        shipment/
          logistics__company_description.sql
      tests/
        shipment/
          assert_int_shipment_conformed_grain.sql
```

Ownership rules:

| Location | Owner | Projection behavior |
|---|---|---|
| `integration/transforms/dbt/**` | Hub developer | Read-only; never overwritten |
| Generated custom vocabulary | Toolkit-managed, committed | Regenerated deterministically; drift rejected |
| `model/mappings/**` | Design workflow | Read-only during projection |
| `model/extensions/**` | Design workflow | Read-only during projection |
| `output/medallion/dbt/**` | Toolkit | Generated and replaceable |

The generated vocabulary must contain a managed-file marker and generation metadata. A
developer must not edit it manually. Changes originate in the dbt contract and are applied
through the contract synchronization workflow.

## 6. Authoritative dbt contract

Each bundled model requires a dbt properties file containing:

- model name;
- description;
- `config.contract.enforced`;
- materialization;
- every output column name and `data_type`;
- `meta.kairos.target_class`;
- `meta.kairos.virtual_source_iri`;
- `meta.kairos.grain`;
- `meta.kairos.supported_adapters`;
- optional `meta.kairos.replaces_sources` with canonical Bronze table IRIs when the
  contract is the governed replacement for an unsafe direct source path;
- physical natural-key columns corresponding to the semantic key in the Silver extension;
- required packages and macros; and
- decision provenance for non-trivial business rules;
- tests appropriate to the declared grain and semantics.

Example:

```yaml
version: 2

models:
  - name: int_shipment_conformed
    description: Canonical shipment-order transformation consumed by Kairos Silver.
    config:
      materialized: table
      contract:
        enforced: true
    meta:
      kairos:
        target_class: https://example.com/ont/logistics#ShipmentOrder
        virtual_source_iri: https://example.com/source/custom#shipmentConformed
        grain: one row per source system, shipment, and order
        supported_adapters:
          - fabric
          - databricks
        natural_key:
          - source_system
          - canonical_shipment_id
        required_packages:
          - dbt-labs/dbt_utils
        required_macros:
          - example_logistics__company_description
        replaces_sources:
          - table_iri: https://example.com/source/transport#booking
          - table_iri: https://example.com/source/transport#stop
        decisions:
          - id: route-fallback
            statement: Use booking route, then stops, then shipment header.
            evidence:
              - artifact: businessdiscovery/glossary.ttl
                subject: https://example.com/glossary#ShippingRoute
              - artifact: integration/sources/transport/transport.vocabulary.ttl
            confidence: high
            status: ai_approved
            approval:
              actor: copilot
              timestamp: 2026-07-18T17:47:20+02:00
            implemented_by:
              model: int_shipment_conformed
            verified_by:
              - unit_test_route_fallback
    columns:
      - name: source_system
        description: Stable identifier of the contributing source system.
        data_type: string
        data_tests:
          - not_null

      - name: canonical_shipment_id
        description: Canonical shipment identity within the source system.
        data_type: string
        data_tests:
          - not_null

      - name: order_number
        description: Business order number associated with the shipment.
        data_type: string

      - name: load_status
        description: Normalized load status.
        data_type: string
        data_tests:
          - accepted_values:
              arguments:
                values: ["Full", "Empty"]
```

### 6.1 Contract rules

1. Every selected output column must appear exactly once in the contract.
2. Contracted models may use `table`, `view`, or `incremental` only where supported by
   dbt contracts and the selected adapter.
3. Contract constraints are adapter-dependent. Data tests remain required for semantic
   assertions such as uniqueness, accepted values, and referential integrity.
4. Numeric types must declare precision and scale where business behavior depends on them.
5. Contracted incremental models must use `on_schema_change: append_new_columns` or
   `on_schema_change: fail`; `sync_all_columns` is not permitted because removal is a
   breaking contract change.
6. A contract-breaking column removal, rename, or incompatible type change requires an
   explicit migration and package version decision.

### 6.2 Governed source replacement

`meta.kairos.replaces_sources` is an optional governance assertion that the contracted
model replaces the listed canonical Bronze tables for `target_class`. It is not verified
SQL lineage. Each entry contains exactly one absolute HTTP(S) `table_iri`; synchronization
fails when the IRI is unknown, generated, or defined by conflicting source vocabularies.
Equivalent monolithic and split RDF views of the same table are reconciled by canonical
IRI and table-subgraph equality; divergent views remain blocking.

Replacement coverage is deliberately stricter than ordinary table coverage. It requires:

1. an approved source-table class claim whose `class_uri` equals `target_class`;
2. current synchronized contract RDF;
3. a table-level `skos:exactMatch` from the virtual table to `target_class`;
4. `kairos-ext:silverSourceRef` routing that class to the contracted model; and
5. no competing direct or second replacement authority for the same domain/source.

The original Bronze tables remain available as dbt `source()` inputs through the contract
declaration, so they must not receive unsafe direct SKOS mappings merely to generate
`_sources.yml`.

### 6.3 Decision provenance

`meta.kairos.decisions` records why a non-trivial transformation rule exists and which
artifacts support it. It is descriptive governance metadata, not executable configuration.
Kairos must never translate a decision statement into SQL or use it to override the
ontology, mappings, Silver extension, contract columns, or authored model.

Each decision contains:

| Field | Requirement |
|---|---|
| `id` | Required stable identifier, unique within the model |
| `statement` | Required concise description of the chosen behavior |
| `evidence` | Required non-empty list of repository artifacts and optional RDF subjects |
| `confidence` | Required controlled value: `low`, `medium`, or `high` |
| `status` | Required controlled lifecycle value |
| `approval` | Required for an approved status; identifies actor and timestamp |
| `implemented_by.model` | Required dbt model resource implementing the decision |
| `verified_by` | Required non-empty list of dbt unit or data-test resource names |

Supported lifecycle values are:

- `proposed` for an inference or recommendation that has not been approved;
- `ai_approved` only when design fleet mode explicitly authorizes AI checkpoint decisions;
- `developer_approved` for implementation-owner approval;
- `stakeholder_approved` for business-owner approval;
- `rejected`; and
- `superseded`.

`ai_inferred` is not an approval state. An AI-inferred decision starts as `proposed` with
its confidence recorded. Approval changes the status and adds an approval record; it does
not erase the original evidence or decision history. If preserving a complete approval
history becomes necessary, the schema should add append-only approval events rather than
overloading a single status field.

Evidence rules:

1. `artifact` is a repository-relative path, not a machine-specific absolute path.
2. `subject` is used when evidence refers to a specific RDF resource and must be a valid,
   resolvable IRI in that artifact.
3. Evidence must not embed sample values, secrets, PII, or proprietary content.
4. A missing artifact or RDF subject is a validation error.

`implemented_by` references a stable dbt model resource. It must not identify an internal
CTE because CTE names are not dbt graph resources and may change during harmless SQL
refactoring.

`verified_by` references existing dbt test resources. Tests provide executable evidence
for selected examples and runtime assertions; they do not constitute a formal proof that a
business rule is universally correct. Every referenced test must be present in the
assembled project and select or depend on the implementing model.

## 7. Generated virtual-source vocabulary

Kairos generates the virtual-source vocabulary from the contract. The model and column IRIs
are deterministic:

- table IRI: `meta.kairos.virtual_source_iri`;
- column IRI: `{virtual_source_iri}/{encoded-column-name}`.

Illustrative output:

```turtle
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
@prefix custom: <https://example.com/source/custom#> .

custom:shipmentConformed
    a kairos-bronze:Table ;
    kairos-bronze:physicalName "int_shipment_conformed" .

<https://example.com/source/custom#shipmentConformed/source_system>
    a kairos-bronze:Column ;
    kairos-bronze:belongsToTable custom:shipmentConformed ;
    kairos-bronze:physicalName "source_system" ;
    kairos-bronze:dataType "string" .
```

The exact RDF terms must use the established Kairos Bronze vocabulary. Generation must use
`rdflib.Graph`; Turtle must not be assembled with string concatenation.

The synchronization operation:

1. parses the dbt YAML safely;
2. validates required Kairos metadata;
3. generates the RDF graph;
4. validates Turtle syntax;
5. compares it with the committed managed vocabulary;
6. writes it only when explicitly synchronizing; and
7. fails projection or CI if the committed vocabulary is missing or stale.

Projection may construct the same graph in memory, but the committed managed vocabulary
remains available to mapping and reporting tools.

## 8. Reuse existing SKOS mappings

The generated virtual columns use the existing mapping vocabulary:

```turtle
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix custom: <https://example.com/source/custom#> .
@prefix log: <https://example.com/ont/logistics#> .

custom:shipmentConformed
    skos:exactMatch log:ShipmentOrder .

<https://example.com/source/custom#shipmentConformed/canonical_shipment_id>
    skos:exactMatch log:canonicalShipmentId .

<https://example.com/source/custom#shipmentConformed/load_status>
    skos:exactMatch log:loadStatus .
```

No output-binding vocabulary is introduced. Internal Bronze-column lineage may be
documented separately, but it must not be presented as mechanically verified unless a
lineage engine has parsed and resolved the SQL.

## 9. Reuse `silverSourceRef`

The Silver extension points the ontology class to the custom model:

```turtle
log:ShipmentOrder
    kairos-ext:silverSourceRef "int_shipment_conformed" ;
    kairos-ext:naturalKey "canonicalShipmentId" ;
    kairos-ext:scdType "1" .
```

Resolution rules:

1. If the referenced name matches a bundled contracted model, Kairos treats it as a custom
   transformation source.
2. If it matches an existing generated staging model, current `silverSourceRef` behavior
   remains unchanged.
3. If it matches neither, projection fails with an unresolved-reference error.
4. The custom model name must be unique across the assembled dbt graph.
5. Source-column resolution uses the generated virtual-source vocabulary associated with
   the matching contract.

This is an extension of DD-039, not a parallel routing mechanism.

## 10. Generated Silver wrapper

The generated Silver model references the custom intermediate model:

```sql
with source as (
    select *
    from {{ ref('int_shipment_conformed') }}
)

select
    {{ kairos_surrogate_key([
        'source_system',
        'canonical_shipment_id'
    ]) }} as shipment_order_sk,
    source_system,
    canonical_shipment_id,
    order_number,
    load_status
from source
```

The wrapper owns only behavior that Kairos can generate safely:

- ontology-aligned names;
- surrogate key and IRI generation;
- configured SCD behavior;
- supported FK lookups;
- generated descriptions; and
- SHACL- and mapping-derived tests.

The custom model owns:

- source joins and bridges;
- ranking and fallback precedence;
- source-specific normalization;
- JSON extraction;
- aggregation and source union;
- grain formation; and
- canonical business-key derivation.

## 11. Foreign keys and grain safety

Foreign-key generation must not silently change model grain.

### 11.1 Offline hard failures

Projection fails when:

- a target FK entity has no declared natural key;
- a required FK natural-key component is absent from the custom contract;
- mappings cannot resolve custom output columns to the required properties;
- FK key arity differs between source and target;
- a referenced target model is absent from the assembled package; or
- configured key generation is incompatible with the target key contract.

### 11.2 Runtime requirements

Runtime tests must verify:

- natural-key uniqueness and non-nullness;
- FK relationship integrity;
- absence of join fan-out;
- expected row grain after wrapper joins; and
- compatibility with previously published surrogate-key behavior where migration is
  required.

An FK that cannot satisfy these requirements remains the custom model's explicit
responsibility. Such an exception must be declared in contract metadata and reported as a
reduced Kairos guarantee.

## 12. Bundle policy and supply-chain controls

The first delivery may bundle:

- `.sql` models under `models/`;
- model properties and unit-test YAML under `models/`;
- singular data tests under `tests/`; and
- custom macros under `macros/`.

It must reject:

- path traversal, absolute paths, links escaping the input root, and unsupported files;
- duplicate dbt resource names;
- macros using the reserved `kairos_` prefix;
- custom resources that shadow generated models or toolkit macros;
- hard-coded credentials, tokens, or connection profiles;
- package declarations not present in the toolkit allow-list; and
- `ref()` dependencies that resolve only in an unknown consumer project.

Custom macros must use a hub-specific prefix in the form
`<hub-or-domain>__<macro-name>`. Generated SQL should use explicit package/project
namespacing where dbt resolution supports it.

Package versions remain pinned by the toolkit. Custom transformations declare which
approved packages they require but do not rewrite `packages.yml`.

## 13. Fabric and Databricks compatibility

Each custom transformation declares the non-empty subset of adapters it supports. Hub
projection configuration selects the active adapter; selecting an adapter outside that
subset is a validation error.

Adapter compatibility requires:

1. portable SQL or adapter-dispatched macros;
2. valid type mappings for every declared adapter;
3. successful `dbt parse` for each declared adapter's generated project;
4. successful adapter-specific `dbt compile`;
5. contract-compatible materialization on each adapter; and
6. runtime tests on each adapter in integration CI.

Kairos must maintain an adapter capability matrix covering at least:

- supported contract materializations;
- column name and type enforcement;
- supported physical constraints;
- incremental contract behavior;
- SQL type aliases;
- macro dispatch; and
- known unit-test limitations.

Physical constraints must never be assumed equivalent across Fabric and Databricks.
Portable data tests are the cross-adapter semantic guarantee.

The current hub validation dependency group covers dbt Core and dbt-fabric. Supporting
Databricks in this design requires an equivalent pinned validation environment or CI matrix
for `dbt-databricks`.

## 14. Validation lifecycle

### 14.1 Pre-write deterministic validation

Before writing to `output/medallion/dbt/`, Kairos validates:

- permitted paths and file types;
- unique model, macro, test, and source names;
- contract YAML structure;
- required Kairos metadata;
- unique decision IDs and controlled confidence/status values;
- resolvable decision evidence, implementing models, and verifying tests;
- approval actor and timestamp for approved decisions;
- adapter declarations;
- approved package dependencies;
- contract-to-vocabulary synchronization;
- `silverSourceRef` resolution;
- target ontology class and property existence;
- SKOS mapping resolution;
- natural-key completeness;
- FK key shape;
- generated resource collisions; and
- statically resolvable `ref()` and `source()` dependencies.

A failure writes no custom transformation artifacts or generated Silver wrappers.

This release does not promise atomic replacement of the entire existing dbt output
directory. Atomic temporary assembly and directory replacement remain a later,
project-wide improvement.

### 14.2 dbt graph validation

For both adapters:

- run `dbt deps` using toolkit-approved pinned dependencies;
- run `dbt parse`;
- attempt `dbt compile`;
- inspect `manifest.json` for unresolved or unexpected dependencies; and
- verify the generated Silver wrapper references the contracted model.

Compilation proves graph and SQL/Jinja validity, not runtime output grain or quality.
`dbt parse` is mandatory offline. If compile requires credentials, a driver, a connection,
or warehouse introspection, `validate-dbt` reports it as environment-blocked rather than as
an artifact defect. SQL, Jinja, contract, and dependency compile failures remain blocking.

### 14.3 Runtime validation

The generated package includes hooks and tests for warehouse-backed CI:

- contract enforcement where supported;
- natural-key `unique` and `not_null` data tests;
- accepted-value tests;
- relationship tests;
- singular grain and fan-out tests;
- source-branch reconciliation tests; and
- adapter parity tests for representative fixtures.

Unit tests are strongly recommended for window functions, fallback rules, complex
`CASE` expressions, date logic, and regressions. dbt unit tests run while the generated
package is the current root project; consumers must not be assumed to execute dependency
package unit tests.

Live Fabric and Databricks execution is outside the first delivery. These runtime tests are
required before a hub owner publishes a transformation as production-ready, but they are
not toolkit implementation completion gates.

## 15. Publication and versioning

Kairos assembles custom SQL only into the generated hub dbt package. The hub owner decides
whether and how that package is published.

Before publication, the hub owner must verify that custom SQL, comments, tests, and fixture
values contain no secrets, PII, proprietary examples, or prohibited organization-specific
content.

Versioning rules:

- additive optional support is a toolkit minor release;
- fixes that preserve generated interfaces are patch releases;
- breaking changes to existing mapping semantics, generated package layout, public APIs,
  or contracted Silver interfaces require a major release;
- a custom model contract breaking change requires an explicit downstream migration even
  when the toolkit release itself is non-major.

This feature alone does not require a new major toolkit version.

## 16. Incremental delivery

### Phase 1 — Contract synchronization and routing

- Extend `silverSourceRef` resolution for bundled contracted models.
- Parse and validate custom model contracts.
- Validate decision provenance without interpreting it as executable transformation logic.
- Generate and verify managed virtual-source vocabularies.
- Reuse existing SKOS mapping resolution.
- Copy permitted artifacts into generated output.
- Reject collisions, unresolved references, and unapproved packages.
- Add unit and scenario coverage for simple and error paths.

### Phase 2 — Generated wrapper guarantees

- Generate Silver wrappers from virtual-source mappings.
- Enforce natural-key and FK shape checks.
- Generate required portable data tests.
- Report reduced guarantees for explicit custom-key exceptions.
- Add Shipment-like regression coverage to the scenario hub.

### Phase 3 — Dual-adapter validation

- Add pinned Fabric and Databricks validation environments.
- Generate each adapter package into a separate temporary output root.
- Require parse and attempt compile for both adapters.
- Add runtime-test hooks for warehouse-backed contract, grain, relationship, and
  adapter-parity CI without requiring live credentials in toolkit CI.
- Publish and maintain the adapter capability matrix.

### Phase 4 — Assisted authoring skill

Add `kairos-develop-dbt-transformation` as an interactive, evidence-grounded authoring
workflow. It:

- assembles only relevant glossary, ontology, source, mapping, Silver, contract, dbt graph,
  adapter, and validation evidence;
- requires explicit approval of grain, identity, contract, decision provenance, mappings,
  and Silver policy before writing;
- creates or updates custom SQL, contracts, namespaced macros, unit tests, and data tests;
- routes ontology, SKOS, and Silver changes through `kairos-design-domain`,
  `kairos-design-mapping`, and `kairos-design-silver` rather than bypassing their gates;
- records decisions and resume state under
  `.kairos-state/phases/dbt-transformation/<model>.md`;
- runs `sync-dbt-contracts`, projection, and `validate-dbt` in that order; and
- preserves user-authored SQL unless replacement is explicitly approved.

Design fleet mode remains explicit opt-in. It retains every evidence and validation gate,
marks decisions `ai_approved`, records rationale and confidence, and stops for ambiguity,
low confidence, policy-sensitive choices, destructive changes, or proprietary/PII risk.

### Phase 5 — Operational hardening

- Add manifest-based dependency reporting.
- Add transformation-boundary coverage reporting.
- Consider atomic dbt output assembly and replacement.
- Evaluate verified SQL column-lineage tooling separately.

## 17. Acceptance criteria

The first delivery is complete when:

1. existing hubs without custom transformations produce unchanged dbt behavior;
2. existing `silverSourceRef` staging use cases remain compatible;
3. one contracted custom model generates a deterministic managed vocabulary;
4. modifying the contract without synchronizing the vocabulary fails validation;
5. a generated Silver wrapper resolves the custom model and mapped output columns;
6. duplicate resources and reserved macro names are rejected;
7. unapproved packages and consumer-only refs are rejected;
8. missing natural-key or FK components fail before output is written;
9. Fabric and Databricks parse jobs pass and compile either passes or is classified as
   environment-blocked;
10. runtime test hooks cover contract, grain, key, accepted-value, and relationship
    assertions for both adapters;
11. decision metadata resolves to repository evidence, an implementing model, and existing
    dbt tests without influencing generated SQL;
12. a governed replacement can cover a wrong-grain source without an unsafe direct mapping,
    but only when claims, exact virtual mapping, synchronized RDF, and Silver routing agree;
13. scenario tests cover a complex transformation containing joins, ranking, fallback
    logic, aggregation, and a generated Silver wrapper; and
14. `kairos-develop-dbt-transformation` enforces interactive evidence, semantic handoff,
    state, synchronization, and validation checkpoints.

## 18. Best practices adopted

This design adopts the following dbt practices:

- consistent staging/intermediate/business-conformed layering;
- contracts for stable model interfaces;
- explicit numeric precision and scale;
- safe `on_schema_change` behavior for contracted incremental models;
- data tests for runtime semantic guarantees;
- unit tests for complex transformation logic and regressions;
- pinned and approved package dependencies;
- namespaced custom macros;
- `source()` and `ref()` instead of hard-coded physical relations; and
- adapter-specific CI rather than assuming SQL portability.

## 19. References

- dbt model contracts:
  <https://docs.getdbt.com/reference/resource-configs/contract>
- dbt project structure best practices:
  <https://docs.getdbt.com/best-practices/how-we-structure/1-guide-overview>
- dbt data tests:
  <https://docs.getdbt.com/docs/build/data-tests>
- dbt unit tests:
  <https://docs.getdbt.com/docs/build/unit-tests>
- dbt packages:
  <https://docs.getdbt.com/docs/build/packages>
- Existing Kairos source routing: DD-039 in
  `docs/design/toolkit-design-decisions.md`
