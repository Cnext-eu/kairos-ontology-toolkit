---
name: kairos-design-mapping
description: >
  Interactive v5 workflow for authoring one closed YAML EntityBinding from a
  source relation or contracted dbt model to one canonical ontology entity.
  Iterates with compile --check and compile --explain. NOT for ontology design,
  relational SQL authoring, or artifact emission.
---
<!-- kairos-ontology-toolkit:managed v2.35.0 -->

# V5 Entity Binding Design

Use this skill after a bounded canonical ontology slice is accepted. Author
`integration/bindings/<source>-to-<domain>.binding.yaml` as the single
source-to-canonical execution authority.

This is the DD-133 v5 clean break. Work only with the authoritative v5 inputs
below. `compile` diagnostics are ephemeral; persist only accepted binding and
ordinary contracted dbt changes.

## Design fleet mode (DD-088)

Default is interactive. Ask the user to confirm the source-to-entity alignment,
grain, identity, every field/expression batch, relationships, quality checks,
and binding patch.

If the user explicitly requests design fleet mode for this invocation:

- announce that AI will make checkpoint decisions;
- apply every schema, evidence, privacy, and compiler gate below;
- mark decisions **AI-approved**, not user-confirmed;
- record rationale, confidence, and evidence references in the in-session review;
- stop for low confidence, ambiguous identity or grain, policy-sensitive choices,
  proprietary/PII risk, unsafe/lossy expressions, or complex relational logic.

The override applies only to this skill invocation. It expires when the skill
ends or pauses, is never inherited by another skill or later resume, and does
not authorize another design skill.

## Fast path: scaffold-binding and fit-report

Most bindings start with a mechanical structure that automation can handle. Two tools
accelerate the common case:

- **`scaffold-binding`** generates a first-draft binding YAML automatically from source
  metadata and target class shape. It supports five standard archetypes (passthrough,
  single-source-master, merged-master, event-stream, line-item-child) and respects the
  core principle below: `target.class` points directly at an accelerator class with **no
  local subclass** — local subclasses are needed only for genuine deviations, not as the
  default. The `passthrough` archetype is fully automatic and ready to compile unedited;
  the four canonical archetypes generate skeletons with sentinel placeholders for
  irreducible human judgment (grain, identity, survivorship) that compilation rejects
  until confirmed. Use: `kairos-ontology scaffold-binding --system <sys> --table <tbl>
  --archetype <type> --target-class <IRI>`.

- **`fit-report`** shows (deterministically, without any LLM call) which properties an
  accelerator class already models and which a binding's fields already populate. It
  reports populated properties, unpopulated ones (what you can still choose from), and
  orphan columns that don't map anywhere. Use it to inspect coverage before hand-authoring
  a complex binding: `kairos-ontology fit-report --class <IRI> --binding
  <path>` or `--source <system>.<table>`.

**When to reach for scaffold-binding vs. hand-authoring:** Use scaffold-binding for
mechanical, single-source patterns. Hand-author (this skill) when you need complex joins,
aggregation, survivorship policy, or multi-source fusion — scaffold is a skeleton, not a
finished design. Both paths share the same compiler gates and YAML contract.

**Core principle — direct accelerator targeting:** An `EntityBinding`'s `target.class` can
now resolve directly to an accelerator or reference-model class (via the compiler's
semantic-index closure, DD-144). A local subclass is needed only when you are genuinely
deviating from the accelerator's shape, not as boilerplate. This simplification applies
to all bindings, scaffolded or hand-authored.

## Decision Log materiality

If a mapping choice resolves a genuine tension or real gap, persist it with
`kairos-ontology decision new --title "<concise>" --domain <domain>` and one
or more `--source <evidence-resource>` references. Never log routine
confirmations, successful validations, or mechanical binding choices.

## Authority and scope

One binding document maps:

- exactly one source relation **or** one contracted dbt model;
- to exactly one class in `model/ontologies/<domain>.ttl`;
- at one explicit materialized grain and identity;
- with closed scalar expressions, relationship behavior, and focused checks.

The binding references source columns and ontology terms; it never copies their
definitions. Source vocabularies/contracts remain Bronze authority. The
ontology remains canonical semantic authority. Ordinary dbt SQL/YAML owns
joins, windows, aggregation, ranking, deduplication, JSON expansion,
multi-relation fallback, survivorship, row-level filtering/subsetting of a
mixed-row-type source table, or a grain change.

Work on one source system, one domain, and one entity binding at a time.

## Hard gates

### Gate 1: Complete, PII-safe evidence

Before proposing a binding:

1. read the selected source vocabulary or dbt output contract;
2. read the target ontology import closure;
3. verify the selected source contains the required relation and columns;
4. enumerate whether other Bronze sources under `integration/sources/` also
   plausibly target the same canonical class — check today either with
   `kairos-ontology fit-report --class <X> --source <system>.<table>` run
   against each candidate source, or by reasoning over the hub's own source
   inventory; this is a workflow check, not a new tool;
5. use only already-redacted, masked, aggregated, or synthetic examples.

Never expose or persist raw PII, sensitive free text, proprietary samples, or
credentials. An unredacted sample blocks the workflow and must return to the
source privacy/redaction process.

If step 4 finds more than one plausible source for the same canonical class,
do not bind `source.relation` directly to a single source, even if only one
source is being wired up in this pass. Route straight to the
`int_merged__<entity>` pattern via **kairos-develop-dbt-transformation** from
the start, so the second source's eventual arrival is a union, not a rewrite.

**Decision rule — when multi-source matters.** Default to `int_merged__<entity>`
from day one for any canonical class that is (or subclasses) a master/
business-entity accelerator class — for example Party, Location,
TransportOrder, or Equipment — because these predictably accrete additional
Bronze sources over an enterprise's system-migration lifecycle. Skip the
merged pattern for genuinely closed reference/governed-code-list classes —
for example an `EquipmentTypeCode`-style governed vocabulary, a seed
dimension, or a date spine — since these structurally will not gain a second
source, and the extra model/YAML/test/decision-record ceremony is pure
overhead with no future payoff. This overhead is authoring/maintenance cost
only, not runtime cost: `int_merged__*` models are materialized as a `view`
by this toolkit's own dbt template convention, so an unused single-source
union costs nothing at query time.

### Gate 2: Explicit confirmation

Interactive mode requires explicit approval for source→class alignment, grain,
identity, fields/expressions, relationship actions, quality checks, and the
exact YAML patch. Silence is not approval. Fleet mode may approve only under its
invocation-scoped rules.

### Gate 3: Closed EntityBinding

Use only the DD-133 `kairos.eu/v5` schema. Unknown or duplicate keys, unresolved
prefixes, raw SQL, copied source/ontology definitions, governance metadata, and
arbitrary extension fields are prohibited.

Each compiler iteration must leave a complete schema-valid document. Do not run
the compiler against syntactically partial YAML.

### Gate 4: Compiler check after every batch

After each accepted proposal batch that changes the binding, run:

```powershell
$env:KAIROS_SKILL_CONTEXT = "1"
uv run kairos-ontology compile <domain> --check --format text
```

`--check` is stateless and must not write hub files. Treat every error as
blocking for the affected entity. Present all ordered diagnostics, revise only
with user confirmation (or a valid fleet decision), and rerun until the entity
passes. Never suppress a static-safety diagnostic.

### Gate 5: Explain before completion

After a successful check, run:

```powershell
$env:KAIROS_SKILL_CONTEXT = "1"
uv run kairos-ontology compile <domain> --explain --format text
```

`--explain` must not write hub files. Present normalized fields, selected scope,
inferred types/null behavior, identity, relationships, blocked behavior,
capabilities, and planned artifacts. If explain reveals an unintended result,
return to the proposal/check loop.

Do not call `compile --emit` from this design skill — it is hard-gated behind
`--confirm-emit`, which only **kairos-execute-project** passes, so a bare
`--emit` here fails immediately with a `UsageError`.

## Closed YAML contract

Use this shape; optional sections remain closed:

```yaml
apiVersion: kairos.eu/v5
kind: EntityBinding
metadata:
  name: <stable-binding-id>
  domain: <domain>
source:                         # exactly one
  relation: <source>.<relation>
  # dbtModel:
  #   name: <contracted_model_name>
  #   sqlPath: integration/transforms/dbt/models/<model>.sql
  #   contractPath: integration/transforms/dbt/models/<model>.yml
target:
  class: <prefix:Class>
grain:
  columns: [<source-column>]
identity:
  strategy: source-natural     # or surrogate
  sourceKey: [<source-column>]
  # businessKey: [<source-column>]
load:
  mode: full-refresh
fields:
  - property: <prefix:property>
    expression: <source-column-or-expression-node>
relationships:
  - property: <prefix:objectProperty>
    target: <prefix:Class>
    # externalReference:          # required for a cross-domain physical parent
    #   name: <parent_dbt_model>
    #   domain: <owning-domain>
    #   key:
    #     - column: <parent-key-column>
    #       type: <canonical-key-type>
    join:
      - local: <source-column>
        foreign: <parent-key-column>
    cardinality: many-to-one   # or one-to-one
    mode: non-temporal
    missingParent: error       # or null
    ambiguousParent: error     # or first
quality:
  - kind: not-null             # unique | reconcile-rowcount | referential
    columns: [<source-column>]
```

Slice 1 supports `full-refresh` and non-temporal relationships. Do not invent
incremental/SCD policy that is not in the active schema.

### Scalar expressions

A bare string means `{ column: <name> }`. Structured nodes are limited to:

- `{ column: <name> }`
- `{ literal: <value>, datatype: <type> }`
- `null`
- `{ op: <name>, args: [...] }`
- `{ fn: <name>, args: [...] }`
- `{ case: [{ when: ..., then: ... }], else: ... }`
- `{ macro: <prefix:name>, args: [...] }`

Allowed operators:
`add`, `subtract`, `multiply`, `divide`, `modulo`, `negate`, `equal`,
`not-equal`, `less-than`, `less-or-equal`, `greater-than`,
`greater-or-equal`, `and`, `or`, `not`, `is-null`, `is-not-null`.

Allowed functions:
`abs`, `round`, `concat`, `upper`, `lower`, `length`, `coalesce`, `nullif`.

Allowed macros:
`concat`, `dayOfWeek`, `monthName`, `quarter`.

Use only a kind-compatible declared null policy:
`propagate`, `never-null`, `three-valued`, `first-non-null`,
`null-if-equal`, `branch`, or `explicit-null`. The compiler infers output type
and capabilities and requires deterministic bounded expressions.

Raw SQL and technical-cleanup functions such as `cast`, `trim`, `replace`, and
`json-*` are not binding expressions.

## Binding loop

### 1. Select one entity scope

Identify the hub from `kairos.yaml`, source system, domain, source relation or
contracted dbt model, target class, and mode. Confirm that the accepted canonical
slice exists before mapping it.

### 2. Present source-to-entity evidence

Show a PII-safe alignment:

| Source relation/model | Target class | Business meaning | Grain clues | Evidence | Confidence |
|---|---|---|---|---|---|

Use identifiers, types, constraints, and masked examples. Explicitly identify
unmapped relations as out of this one-entity scope; do not create a persisted
backlog.

### 3. Confirm grain and identity

Keep these concepts separate:

- `grain.columns` — one materialized output row;
- `identity.sourceKey` — source-record identity;
- optional `identity.businessKey` — business identity;
- ontology individual IRI — semantic identity, not authored as a source key;
- generated surrogate — warehouse identity when strategy is `surrogate`.

Do not infer identity solely from a column name. Require evidence for uniqueness
and nullability, and add focused `not-null`/`unique` checks when supported.

### 4. Propose fields in bounded batches

For each field show:

| Source column/expression | Target property | Source type | Target range | Null behavior | Evidence | Confidence |
|---|---|---|---|---|---|---|

Prefer direct columns. Use a closed scalar expression only when deterministic,
type-compatible, and semantically transparent. Obtain confirmation for the
batch, update the complete YAML, then run Gate 4.

Unknown columns/properties, incompatible types, unsafe functions, excessive
nesting, or ambiguous null behavior must be corrected rather than waived.

### 5. Route relational complexity

If correct meaning requires joins, windows, aggregation, ranking, deduplication,
JSON expansion, multi-relation fallback, survivorship, row-level
filtering/subsetting of a mixed-row-type source table, or a grain change, stop
binding that physical relation and invoke
**kairos-develop-dbt-transformation**. The handoff must author ordinary dbt
SQL plus an authoritative YAML output contract. It must not create a candidate
inventory, separate virtual-source artifact, or registry. The required
`meta.kairos.virtual_source_iri` field is only a stable identifier for the
contracted model output; it is not another authored source or execution
authority.

After the dbt model is accepted, return here and reference it with
`source.dbtModel`; do not duplicate its relational logic in the binding.

### 6. Define relationships and checks

For every relationship confirm target, join keys, cardinality, non-temporal
mode, and both missing/ambiguous parent actions. The target must resolve to
another materializable binding or a declared external reference with a key
contract.

For cross-domain targets, author `externalReference` explicitly. Its `name` is
the parent dbt model in the unified medallion project, `domain` is the owning
domain, and `key` is the ordered parent-side key contract. Each `key[].column`
is the parent's **materialized output column** (not the child's source column),
and each `key[].type` is a canonical type token whose kind must match the local
source column's kind. Canonical kinds are `string`, `boolean`, `int16`, `int32`,
`int64`, `decimal`, `float64`, `date`, `time`, `timestamp`, `binary`, and
`json`; common SQL aliases (`bigint`, `int`, `varchar(n)`, `decimal(p,s)`,
`datetime`, …) are also accepted and normalized by kind. The ordered
`join[].foreign` values must exactly match `externalReference.key[].column`,
and each child `join[].local` source type must be compatible with the declared
key type. Do not inspect or depend on peer-domain bindings to infer these
values; the declaration is the contract. See `example-entity-binding.yaml`
(`party:hasAccount → billing:Account`) for a worked cross-domain example.

Every relationship `join[].local` column must **also** be mapped as a scalar
`fields:` entry. The join-local FK column is not auto-materialized into the
silver projection; omitting its `fields:` mapping fails compilation with
`mapping.unresolved-join-input` (`DD-107-source-ownership`).

Use `quality:` only for focused evidence-backed dbt tests. It is not execution
authority and does not replace compiler safety.

### 7. Review and persist the YAML patch

Before writing anything, snapshot the workspace scope:

```powershell
$env:KAIROS_SKILL_CONTEXT = "1"
uv run kairos-ontology guard-scope --snapshot
```

Keep the printed token — it is compared at step 9. Present the complete
closed YAML and a focused diff. In interactive mode, wait for explicit
approval before writing. In fleet mode, record rationale, confidence, and
evidence for the AI approval.

Write only the accepted
`integration/bindings/<source>-to-<domain>.binding.yaml` change. Never write an
intermediate RDF representation.

### 8. Iterate check and explain

Run Gate 4 after every accepted binding edit. Feed all diagnostics back into the
next bounded proposal. Once check passes, run Gate 5 and compare normalized
meaning with the approved mapping.

When PII-safe sample evidence exists, run only focused existing sample/dbt checks
that cover identity, reconciliation, and referential assumptions. Present
failures as evidence, not as a new Kairos runtime contract. Do not persist check
or explain output.

### 9. Complete

Reread the saved YAML, rerun `compile --check`, then `compile --explain`, and
confirm the workspace guard passes:

```powershell
$env:KAIROS_SKILL_CONTEXT = "1"
uv run kairos-ontology guard-scope --check-since <token> --allow "*integration/bindings/<source>-to-<domain>.binding.yaml"
```

Completion requires:

- the entity passes the static safety kernel;
- explain output matches the approved semantics;
- source samples exposed to the LLM were PII-safe;
- only accepted binding/dbt authoring changes remain;
- the workspace guard reports no unexpected file changes (a non-zero exit
  names every offending path — not a self-report).

Report the binding path, compiler result, focused checks, and any unresolved
out-of-scope work. Artifact generation is a separate execution step.

## Anti-patterns

- Guessing table, column, grain, identity, or relationship behavior.
- Copying source schema or ontology definitions into the binding.
- Treating sample checks as authority or suppressing compiler findings.
- Embedding arbitrary/raw SQL or relational logic in scalar expressions.
- Running `compile --emit` while designing a binding.
- Writing anything except accepted binding or dbt authoring changes.
- Exposing unredacted samples to the LLM or committed files.

## Related skills

- **kairos-design-domain** — create the bounded canonical ontology slice first.
- **kairos-design-source** — import source authority and PII-safe samples.
- **kairos-develop-dbt-transformation** — author ordinary contracted relational
  models when binding expressions are insufficient.
