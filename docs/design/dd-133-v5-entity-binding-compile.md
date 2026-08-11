# DD-133 companion — v5 EntityBinding + `compile` contract

> Detailed specification for [DD-133](toolkit-design-decisions.md#dd-133-v5-authoring-break--yaml-entitybinding--stateless-compile).
> This is the **authoritative contract** for the v5 compiler. It is
> normative for the closed YAML schema, the scalar-expression grammar, the stateless
> `compile` command, the atomic emission contract, and the minimal static safety kernel.
> The clean-break implementation and documentation consolidation are complete. GA
> publication is a separate release operation and is not claimed by this document.

## 1. No backwards compatibility

V5 is a clean authoring break. There is **no** v4 hub compatibility, dual-format
authoring, migration command, or automated upgrade path. Existing hubs are **rebuilt
from fresh** as v5 hubs. This decision removes migration/compat scope from every stage.

## 2. Authoritative v5 hub layout

```text
model/
  ontologies/<domain>.ttl              # authoritative canonical Silver model (OWL/TTL)
  shapes/                              # optional SHACL
integration/
  bindings/<source>-to-<domain>.binding.yaml   # the single execution authority
  discovery/                           # confirmed business context/glossary only
  sources/<source>/*.ttl               # Bronze schema + redacted samples (authoritative)
  transforms/dbt/
    models/**/*.sql                    # only when relational logic is required
    models/**/*.yml                    # dbt output contracts + tests (authoritative)
kairos.yaml                            # namespace, catalog, adapters, selected roots
output/                                # derived artifacts only
```

There are **no** claims, Silver-extension, preparation, planning, readiness, evidence,
governance, or phase-state directories in a v5 hub.

## 3. EntityBinding YAML schema (closed)

One binding document authors **one** canonical entity from **one** source relation (or
one contracted dbt model). Unknown fields are rejected. Duplicate keys are rejected
(loader-level). Each binding is validated with a packaged JSON Schema, then converted
directly into frozen dataclasses and the existing mapping AST — **never** into RDF.

```yaml
apiVersion: kairos.eu/v5              # required, pinned; drives schema version in provenance
kind: EntityBinding                   # required literal
metadata:
  name: <stable-binding-id>           # required; unique within domain
  domain: <domain>                    # required; must match model/ontologies/<domain>.ttl
source:                               # exactly one of relation | dbtModel
  relation: <source>.<relation>       # references a source vocabulary relation (not defined here)
  # dbtModel: <model_name>            # references a contracted dbt model for complex logic
target:
  class: <prefix:ClassLocalName>      # resolved against the ontology import closure
grain:                                # explicit materialized grain
  columns: [<source-column>, ...]
identity:
  strategy: source-natural | surrogate   # slice-1 supports these two
  sourceKey: [<source-column>, ...]   # strict: SOURCE columns; source-record identity/conformance
  businessKey: [<source-column>, ...] # optional; SOURCE columns; distinct from sourceKey
load:
  mode: full-refresh | incremental    # closed discriminated union; see §3a
fields:                               # field -> property mappings
  - property: <prefix:propertyLocalName>   # resolved against the semantic-index closure (rdfs)
    expression: <expression-node>     # see §4; may be a bare source-column shorthand
relationships:                        # optional; zero or more
  - property: <prefix:objectPropertyLocalName>
    target: <prefix:ClassLocalName>   # must be a materializable entity or external ref (§7)
    join: [{ local: <source-column>, foreign: <parent-key-column> }, ...]
    cardinality: many-to-one | one-to-one
    mode: non-temporal | current | as-of  # temporal modes require `temporal`; see §3b
    missingParent: error | null       # required explicit action
    ambiguousParent: error | first    # required explicit action
quality:                              # optional focused checks (evidence, not authority)
  - kind: not-null | unique | reconcile-rowcount | referential
    columns: [<source-column>, ...]   # kind-specific
```

> **YAML footgun:** relationship join columns use the key `join:` (not `on:`) — under YAML
> 1.1 an unquoted `on` parses as the boolean `True`, so `on` is deliberately avoided.

### 3a. Stage 2 load contract

`load` is a closed discriminated union. `full-refresh` permits only `mode`.
`incremental` requires explicit `scd: 1 | 2` and every runtime fact below; no SCD or
incremental behavior is inferred:

```yaml
load:
  mode: incremental
  scd: 2
  incremental:
    mergeIdentity: [customer_id]
    canonicalHashInputs: [customer_id, display_name, country]
    cdcOperation:
      column: operation
      insertValues: [I]
      updateValues: [U]
      deleteValues: [D]
    sourceUpdatedAt: source_updated_at
    businessEffectiveAt: effective_at
    ingestedAt: ingested_at
    totalOrder: [source_updated_at, sequence_number]
    lookback: { value: 2, unit: days }
    delete: error | hard-delete | soft-delete | ignore
    lateArrival: error | accept
    correction: error | overwrite | new-version
    replay: error | idempotent
    backfill: error | merge | replace-window
    schemaEvolution: fail | append-compatible
```

The three CDC value sets are non-empty, unique, and pairwise disjoint. Hash inputs and
ordering are explicit ordered lists. The compiler adapter must reuse the DD-109/DD-110
typed, length-delimited SHA-256 contract; this document does not define a second hash.
SCD1 permits correction `overwrite | error`; SCD2 permits `new-version | error`. The loader
rejects cross-mode correction actions rather than silently changing their meaning.

### 3b. Stage 2 temporal relationships

`non-temporal` forbids `temporal`. `current` and `as-of` require parent validity columns,
open-ended semantics, overlap handling, late-parent handling, and change-detection
participation. `as-of` additionally requires the child event-time column:

```yaml
mode: as-of
temporal:
  childEventTime: effective_at       # as-of only
  parentValidFrom: valid_from
  parentValidTo: valid_to
  openEnded: null | max-value
  overlap: error | latest-start
  lateParent: error | null | defer
  changeDetection: include | exclude
```

Cardinality, missing-parent, and ambiguous-parent actions remain required on every
relationship. These declarations are immutable compiler input; downstream adapters may
reject unsupported actions but may not choose defaults.

### 3c. Stage 2 multi-source conformance

The one-binding-per-source rule is invariant: one document binds exactly one source relation
or exactly one contracted dbt model. Bindings that materialize the same class must
declare the same explicit conformance `group`, unique positive `sourcePrecedence`, compatible
grain/identity/property contracts, an explicit conflict action, and one closed union policy:

```yaml
conformance:
  group: party-customer
  sourcePrecedence: 1
  conflict: error | prefer-precedence
  union:
    mode: union-all
    # or:
    # mode: deduplicate
    # deduplicateBy: [customer_id]
    # orderBy: [{ column: source_updated_at, direction: descending }]
```

Deduplication requires non-empty identity and total ordering declarations. Binding/source
ordering in explain output and provenance is canonical, never filesystem-discovery order.

### 3d. Stage 2 contracted dbt source

`source` is an exactly-one union. A relation uses `source.relation`; complex relational logic
uses immutable metadata for an ordinary SQL model and its authoritative dbt YAML contract:

```yaml
source:
  dbtModel:
    name: int_customer
    sqlPath: integration/transforms/dbt/models/int_customer.sql
    contractPath: integration/transforms/dbt/models/schema.yml
```

All three fields are required and unknown metadata is rejected. The completed source adapter
resolves the ordinary SQL model and authoritative dbt YAML contract directly, then checks
output columns, types, grain, and deterministic identity. The binding never embeds SQL,
joins, windows, aggregation, or transformation evidence. There is no intermediate virtual
source, evidence record, candidate inventory, or contract-synchronization authority.

## 4. Scalar-expression grammar (maps 1:1 to the existing closed AST)

The grammar mirrors `MappingExpressionKind` in
`src/kairos_ontology/core/projections/dbt/mapping_specs.py` and converts directly to
`AuthoredExpressionFact` (already a graph-free structural copy). Authors provide the
**structure, source columns, literals, operation/macro identifiers, and null policy**;
the compiler **infers** `output_type` (from ontology property range + source type),
`capabilities`, and validates `determinism` (must be `deterministic`). Raw SQL is
prohibited. Max nesting depth is `MAX_MAPPING_AST_DEPTH` (64).

| YAML node | Kind | Author provides | Compiler infers/validates |
|---|---|---|---|
| `{ column: <c> }` or bare `<c>` | `source-column` | source column | source type, nullability |
| `{ literal: <v>, datatype: <t> }` | `literal` | lexical + datatype | typed-literal capability |
| `null` | `null` | — | explicit-null policy |
| `{ op: <name>, args: [...] }` | `operator` | operator name, args | type compat, null propagation |
| `{ fn: <name>, args: [...] }` | `function` | function name, args | supported-function, capability |
| `{ case: [{when,then}...], else: ...}` | `case` | branches, else | branch typing, null policy |
| `{ macro: <prefix:name>, args:[...] }` | `macro` | namespaced macro IRI | namespaced-macro capability |

Null policy (`MappingNullPolicy`) is author-declarable per node (`propagate`,
`never-null`, `three-valued`, `first-non-null`, `null-if-equal`, `branch`,
`explicit-null`); the compiler rejects a node whose declared policy is inconsistent
with its kind/arguments.

Supported operators/functions are an **explicit allow-list** owned by the compiler and kept
a **subset of what the downstream DD-107 normalizer accepts** (canonical names, not sugar):
operators `add, subtract, multiply, divide, modulo, negate, equal, not-equal, less-than,
less-or-equal, greater-than, greater-or-equal, and, or, not, is-null, is-not-null`; functions
`abs, round, concat, upper, lower, length, coalesce, nullif`; macros `concat, dayOfWeek,
monthName, quarter`. **Technical-cleanup functions (`cast`, `trim`, `replace`, `json-*`) are
deliberately excluded** — they belong in kairos-prep, not a mapping expression. Anything
outside the allow-list is rejected with a source-located diagnostic — complex logic must move
to a contracted dbt model referenced via `source.dbtModel`.

## 5. Minimal static safety kernel (non-suppressible)

`--emit` produces SQL only when **all** of these pass. They are compiler safety, distinct
from authored data-quality checks:

1. source relation + every referenced source column resolve;
2. target class + every referenced property resolve in the ontology import closure **through
   the DD-103 versioned semantic index under the `rdfs` profile, so direct and
   subclass-inherited cross-namespace imported properties resolve; an authored field ref that
   resolves to more than one distinct property URI is an ambiguity diagnostic**;
3. canonical source→target type compatibility for every field;
4. every expression is deterministic, bounded, allow-listed, with explicit null/error
   behavior;
5. explicit materialized grain, identity strategy, key scope, and load mode;
6. strict separation of source identity, business identity, ontology IRI, surrogate key;
7. (incremental only — stage 2) complete merge identity + CDC/SCD before incremental SQL;
8. every relationship declares mode, cardinality, `missingParent`, `ambiguousParent`, and
   resolves to a materializable target + key (or a declared external reference, §7);
9. adapter capability support for every negotiated capability;
10. deterministic artifact planning + rendering (no wall-clock in artifact content).

Focused **data-assisted** checks (`quality:`) are evidence only and are emitted as
ordinary generated dbt tests — never as a Kairos-specific runtime result contract.

## 6. Atomic emission contract

- **Ownership boundary:** `--emit` owns exactly the generated dbt target subtree for
  the selected domain, at the fixed canonical location
  `<repo>/ontology-hub-publish/medallion/dbt` (not configurable). A **manifest** lists every
  owned file; only manifest-owned files are created, replaced, or removed. Files outside the
  manifest/target subtree are never touched.
- **Path containment:** the resolved destination must be inside that fixed target; path-escape and
  cross-target collisions are rejected before any write.
- **Atomicity:** build the complete in-memory plan first; stage into a temporary sibling
  directory **on the same volume**; validate; then swap into place with a backup, removing
  stale manifest-owned files. Windows directory replacement is not portably atomic — the
  same-volume stage-then-swap with rollback is the portable strategy.
- **Blocking granularity:** compilation reports project-level and entity-level status. A
  blocked entity is filtered **before** materialize/render; other safe entities in scope may
  still emit. Stale artifacts for a now-blocked entity are removed via the manifest.
- **Interruption/concurrency:** swap uses a recoverable sibling backup; the next invocation
  restores an orphaned backup before planning. Dead-process locks are reclaimed, while a
  live concurrent emitter is rejected.

## 7. Reference/relationship entities

A relationship target must be either (a) another entity with its own binding + generated
model in scope, or (b) an explicitly declared **external reference** (name + key contract)
that the compiler treats as a resolvable parent without generating it. The slice tests
missing target, missing key, and incompatible key types.

**Object properties belong under `relationships:`, never under `fields:`.** `fields:`
materializes scalar attributes only, and an `owl:ObjectProperty` has no canonical scalar
target type (§5 rule 3), so a `fields:` entry whose property resolves to an object property
is rejected — `binding.object-property-in-fields`, surfaced as
`safety.relationship-endpoint`. Materializing it as a scalar would silently emit the raw
reference value as a business attribute, losing the surrogate key, the join, the
orphan-detection window, and the ERD relationship edge. If the raw reference value really is
wanted as a column, author it explicitly as a `technicalFields:` entry (DD-139).

**A `relationships:` entry does not require the object property to declare a named
`rdfs:range`.** The property's range is checked against the authored `target:` class only
when a named range actually resolves; an absent `rdfs:range`, or a range that is a class
expression (`owl:unionOf` / `owl:Restriction` / `owl:oneOf` — a blank node, which the DD-103
semantic index does not surface as a named class), leaves the range unconstrained and the
relationship is validated on its authored endpoint (`target:` + `on:`) alone. This is
deliberate: it is exactly the shape the reference-model `deferred-relationship` pattern
prescribes, where the object property is declared before its target class conforms. The
compiler must never fabricate a scalar range (e.g. `xsd:string`) for an object property to
fill that gap — doing so both defeats this check and makes the property indistinguishable
from a real string attribute.

## 8. Scope resolution & provenance

- `compile <domain>` resolves a single immutable `BuildScope` from the hub root (located by
  walking up to `kairos.yaml`), the domain's ontology import closure, and every
  `integration/bindings/*.binding.yaml` whose `metadata.domain` matches. Binding order is stable
  (sorted by path). Duplicate `metadata.name` within a domain is rejected.
- Adapter/catalog/namespace come only from `kairos.yaml` — no implicit global fallback.
- The `BuildScope` provenance hash covers: schema version (`apiVersion`), adapter,
  ontology + source closure, binding contents, templates/macros, and toolkit version. It
  **excludes** wall-clock values so repeat emission is byte-deterministic.

## 8a. Seam-proven constraints (verified by the v5-seam-spike, 2026-07-27)

A hand-built graph-free `BoundSources` was proven to flow through
`normalize_contract → shape_project → plan_materialization → render_project` and emit valid
Fabric Silver SQL with **no** RDF input. Findings that bind the v5 compiler design:

- **Entry point:** `build_compile_plan(...)` returns one immutable, graph-free `CompilePlan`
  after `normalize_contract → shape_project → plan_materialization` and before byte rendering.
  It carries the selected `BuildScope`, parsed bindings, normalized contract, shaped project
  and Silver registry, physical plan, planned paths, and entity/project blocking diagnostics.
  `BoundSources` remains an internal adapter transport and is not the public compiler seam.
  `compile_plan_result(...)` and `render_compile_plan(...)` provide explicit write-free result
  and rendering views so Gold/MDM consumers reuse the plan without resolution or rebuilding.
- **Retired from the compiler seam:** claim-driven eligibility, aspirational/stub emission,
  and completeness-policy authority. `binding_observations` now records only source-bound or
  ontology-folded facts needed by the shared normalizer. Contracts, virtual-source replacement,
  coverage, and release authoring remain outside the v5 authority.
- **Still load-bearing — the compiler MUST synthesize these internally** (they are retired
  from *authoring* but required by the downstream normalizer):
  - a **neutral passthrough DD-106 preparation policy** for every mapped physical table
    (empty prep fails `prep.missing-policy` at `policy_normalize.py:1220-1231`), carrying
    **exactly one source-record key**, `schema-change=fail`, and no cleanup/cast/CDC;
  - an **identity policy** for governed source/natural identity (a missing one becomes a
    policy issue at `policy_normalize.py:5850-5868`).
  The YAML author never writes preparation TTL; the `compiler/adapter.py` `adapt_binding()`
  entry derives the neutral prep + identity facts from the binding's `identity` + `grain`
  declarations, converts each field expression into an `AuthoredExpressionFact` (metadata
  inferred with the downstream DD-107 type helpers so the normalizer re-validation is exact),
  and hand-constructs the complete `BoundSources` consumed by `normalize_contract`.
- `render_project` returns a `dict` of artifact-path→content plus a `__release_data__` entry;
  the v5 emit contract owns only the file-path artifacts (the non-file keys are ignored/not
  persisted as hub files).
- Layering confirmed: importing the dbt pipeline does not load `kairos_ontology.mdm`.

## 8b. Amendment (2026-07-28): semantic-index resolution + output-column identity

Two coupled compile-time corrections (see the DD-108 amendment 2026-07-28 and DD-103):

- **Symbol resolution uses the DD-103 semantic index under the `rdfs` profile.**
  `kernel._ontology_symbols` loads the closure with `SemanticProfile.RDFS` and resolves each
  bound hub class's **direct and subclass-inherited** properties via
  `SemanticIndex.class_properties`, including properties whose `rdfs:domain` is an ancestor in an
  imported namespace. Inherited resolved properties are made applicable to the bound subclass in
  the resolved-symbol layer (the bound class URI is added to `domain_uris`); the graph is never
  rewritten. The exact-domain/namespace helpers in `ontology_ops`
  (`list_classes`/`list_properties`) do **not** walk `rdfs:subClassOf` and must not be used for
  structure-aware binding resolution — they remain for inventory/non-binding uses only. Binding
  targets remain hub-namespace classes. An authored field ref that resolves to more than one
  distinct property URI (a cross-namespace local-name alias collision) is a
  `binding.ambiguous-property` diagnostic; qualify the field with the owning namespace to
  disambiguate. Consistent with DD-103, inherited *semantic* breadth never widens *physical*
  breadth: an inherited property is materialized only when a field explicitly binds it.
- **Identity keys are resolved to target OUTPUT columns.** `identity.sourceKey`/`businessKey`
  enumerate SOURCE columns, but `EntityIdentityFact.naturalKey` (which drives generated keys,
  business grain, identity roles, and render) now carries the **mapped target OUTPUT column
  names**, resolved from the field whose expression is exactly that source column. Emitted
  silver/dbt column names are the snake-cased target property local name (matching the graph
  path and `naturalKey` normalization). `sourceKey` is unchanged for `_source_record_key` and
  conformance. An identity key with no field mapping, an ambiguous mapping, or one buried in a
  multi-column expression is a specific diagnostic (`identity.authored-key-not-supplied`,
  `identity.ambiguous-key-mapping`, `identity.key-column-in-expression`).

## 9. Superseded-for-v5-path decisions (historical cutover record)

At DD-133 acceptance, the following were superseded **only for the v5 `compile` path** and
remained operative on v4 command paths. Stage 4 has since retired those operational paths
under DD-135, DD-136, and the deterministic
[`stage4-retirement-import-inventory.json`](stage4-retirement-import-inventory.json).
The original decisions remain in the consolidated log as history; their implementations are
not a compatibility or migration surface.

- Lifecycle/readiness/release: DD-080, DD-101, DD-114, DD-116, DD-120.
- Claims & synchronization: DD-082, DD-083, DD-094, DD-095, DD-122.
- Preparation / virtual-source / contract-identity authority: DD-105, DD-106, DD-107
  (mandatory-preparation portions), DD-117, DD-118, DD-119. **Note:** DD-106 preparation is
  retired from *authoring* only — the compiler still synthesizes a neutral passthrough
  preparation policy internally (see §8a).

DD-107's **graph-free scalar-expression AST is retained and reused** — only its
RDF-authored, preparation-routed acquisition path is superseded.

## 9a. Implemented clean-break architecture

- The strict kernel implements the closed incremental/SCD, canonical hash, temporal
  relationship, conformance, contracted-dbt-source, adapter, and deterministic planning
  rules above.
- Immutable `CompilePlan` is the sole canonical Silver/dbt planning authority. The compiler
  creates it once after normalize/shape/materialize; check, explain, emit, Gold, and MDM
  consume plan views rather than rebuilding scope or policy.
- The retained architecture is ontology/source/reference loading, source analysis, typed
  scalar expressions and policies, immutable compiler phases, canonical hashing, adapter
  capability negotiation, deterministic dbt rendering, and optional Gold/MDM consumers.
- The retired architecture is lifecycle/readiness/release state, claims and completeness,
  aspirational stubs, authored preparation/Silver RDF policy, virtual-source and
  transformation-evidence synchronization, persisted projection/import session evidence,
  release baselines, and their commands/tests/scaffold assets.
- The lean scaffold and active documentation expose only canonical v5 inputs and stateless
  compile/consumption guidance. There is no v4 compatibility, dual authoring, migration
  command, or automated upgrade path.
- Documentation completion is not GA publication. Versioning, tagging, release assets, and
  publication verification remain a separate maintainer operation.

## 10. Canonical example

```yaml
apiVersion: kairos.eu/v5
kind: EntityBinding
metadata:
  name: crm-customer-to-party
  domain: party
source:
  relation: crm.customers
target:
  class: party:Customer
grain:
  columns: [customer_id]
identity:
  strategy: source-natural
  sourceKey: [customer_id]
load:
  mode: full-refresh
fields:
  - property: party:customerId
    expression: customer_id
  - property: party:displayName
    expression:
      fn: upper
      args: [{ column: full_name }]
  - property: party:countryCode
    expression:
      fn: upper
      args: [{ column: country }]
    # null policy inferred as propagate; output_type from party:countryCode range
relationships:
  - property: party:hasCountry
    target: ref:Country
    join: [{ local: country, foreign: iso2 }]
    cardinality: many-to-one
    mode: non-temporal
    missingParent: error
    ambiguousParent: error
quality:
  - kind: not-null
    columns: [customer_id]
  - kind: unique
    columns: [customer_id]
```
