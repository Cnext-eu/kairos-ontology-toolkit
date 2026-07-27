# DD-133 companion — v5 EntityBinding + `compile` contract

> Detailed specification for [DD-133](toolkit-design-decisions.md#dd-133-v5-authoring-break--yaml-entitybinding--stateless-compile).
> This is the **authoritative contract** for the v5 first vertical slice. It is
> normative for the closed YAML schema, the scalar-expression grammar, the stateless
> `compile` command, the atomic emission contract, and the minimal static safety kernel.
> Stages 2–8 (see `docs/draft/plan.md`) extend but must not weaken this contract.

## 1. No backwards compatibility

V5 is a clean authoring break. There is **no** v4 hub compatibility, dual-format
authoring, migration command, or automated upgrade path. Existing hubs are **rebuilt
from fresh** as v5 hubs. This decision removes migration/compat scope from every stage.

## 2. Authoritative v5 hub layout

```text
model/
  ontologies/<domain>.ttl              # authoritative canonical Silver model (OWL/TTL)
  bindings/<source>-to-<domain>.binding.yaml   # the single execution authority
  shapes/                              # optional SHACL
integration/
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
  sourceKey: [<source-column>, ...]   # strict: source identity, distinct from IRI/surrogate
  businessKey: [<source-column>, ...] # optional; distinct from sourceKey
load:
  mode: full-refresh                  # slice-1 is full-refresh only; incremental/SCD in stage 2
fields:                               # field -> property mappings
  - property: <prefix:propertyLocalName>   # resolved against the ontology closure
    expression: <expression-node>     # see §4; may be a bare source-column shorthand
relationships:                        # optional; zero or more
  - property: <prefix:objectPropertyLocalName>
    target: <prefix:ClassLocalName>   # must be a materializable entity or external ref (§7)
    join: [{ local: <source-column>, foreign: <parent-key-column> }, ...]
    cardinality: many-to-one | one-to-one
    mode: non-temporal                # slice-1; current/as-of temporal FK in stage 2
    missingParent: error | null       # required explicit action
    ambiguousParent: error | first    # required explicit action
quality:                              # optional focused checks (evidence, not authority)
  - kind: not-null | unique | reconcile-rowcount | referential
    columns: [<source-column>, ...]   # kind-specific
```

> **YAML footgun:** relationship join columns use the key `join:` (not `on:`) — under YAML
> 1.1 an unquoted `on` parses as the boolean `True`, so `on` is deliberately avoided.

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
2. target class + every referenced property resolve in the ontology import closure;
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

- **Ownership boundary:** `--emit <dir>` owns exactly the generated dbt target subtree for
  the selected domain. A **manifest** lists every owned file; only manifest-owned files are
  created, replaced, or removed. Files outside the manifest/target subtree are never touched.
- **Path containment:** the resolved destination must be inside `<dir>`; path-escape and
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

- **Entry point:** the compiler builds a `BoundSources` and calls the existing
  `normalize_contract(...)` chain — no second renderer. A thin **`normalize_v5(facts)`**
  constructor (adapter over `BoundSources`) is preferred over exposing the 26-field
  `BoundSources` ABI to compiler code.
- **Not load-bearing for a simple full-refresh entity (set empty/neutral):**
  `emit_aspirational_stubs`, claim-driven `binding_observations` eligibility, `contracts`,
  `virtual_table_uris`, `replacement_input_uris`, `foreign_key_facts`, `parent_relations`,
  `coverage`, `silver_outcomes`, release authoring input. This confirms none of the
  claims/stub/release/virtual-source machinery is required by the v5 path.
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

## 9. Superseded-for-v5-path decisions (deprecated-but-operative)

The following are superseded **only for the v5 `compile` path**. Their v4 command paths
remain operative until stages 4–5 remove them; they are not deleted from this log.

- Lifecycle/readiness/release: DD-080, DD-101, DD-114, DD-116, DD-120.
- Claims & synchronization: DD-082, DD-083, DD-094, DD-095, DD-122.
- Preparation / virtual-source / contract-identity authority: DD-105, DD-106, DD-107
  (mandatory-preparation portions), DD-117, DD-118, DD-119. **Note:** DD-106 preparation is
  retired from *authoring* only — the compiler still synthesizes a neutral passthrough
  preparation policy internally (see §8a).

DD-107's **graph-free scalar-expression AST is retained and reused** — only its
RDF-authored, preparation-routed acquisition path is superseded.

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
