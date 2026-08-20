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

> **SHACL governance:** SHACL governance shapes are authored during domain design
> (kairos-design-domain) in `model/shapes/<domain>.shacl.ttl`, not during binding
> authoring. EntityBinding quality is enforced by the compiler's conformance
> checks, not by SHACL. Do not add SHACL shapes as part of a binding.

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
  <path>` or `--source <system>.<table>`. **`--source` mode requires a prior
  `kairos-ontology propose-alignment` run for that source** — it reads its evidence from
  `propose-alignment`'s output under `integration/sources/_analysis/`, never from the raw
  source vocabulary directly. Without that prior run, `--source` returns `Evidence: none`
  for every candidate — indistinguishable from a genuine negative result — so run
  `propose-alignment` first, or fall back to `--binding` mode or direct vocabulary
  reasoning (Gate 1 step 4 below already permits this alternative).

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

### Gate 0: AI provider preflight

Before entering the LLM judgment loop for a binding, run
`kairos-ontology check-ai-config --role alignment`.  If the role is
`not_configured` or `misconfigured`, stop and print the remediation — do not
substitute a heuristic, do not auto-degrade, do not produce a plausible-empty
binding (DD-159).  This gate does not block a deterministic-only pass (a user
who is not invoking the LLM yet), but it must be green before any LLM step.

### Gate 1: Complete, PII-safe evidence

Before proposing a binding:

1. read the selected source vocabulary or dbt output contract;
2. read the target ontology import closure;
3. verify the selected source contains the required relation and columns;
4. enumerate whether other Bronze sources under `integration/sources/` also
   plausibly target the same canonical class — check today either with
   `kairos-ontology fit-report --class <X> --source <system>.<table>` run
   against each candidate source (requires a prior `propose-alignment` run per
   the `fit-report` note above — without it, every candidate reports
   `Evidence: none`, not a real negative), or by reasoning over the hub's own
   source inventory; this is a workflow check, not a new tool;
5. use only already-redacted, masked, aggregated, or synthetic examples.

Never expose or persist raw PII, sensitive free text, proprietary samples, or
credentials. An unredacted sample blocks the workflow and must return to the
source privacy/redaction process.

**`example_values` in `*-alignment.yaml` is not pre-redacted by default
(issue #562, DD-205).** It used to always mask PII-shaped values; that
masking is now itself gated by `KAIROS_ALIGNMENT_SEND_RAW_SAMPLES` (default
on), so step 5's "already-redacted" examples cannot be assumed safe just
because they came from this field. Apply your own masked/redacted/synthetic
treatment before any such value reaches a generated artifact or conversation.

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

**If the target class already has an existing `EntityBinding`** (found via step 4
or by checking `integration/bindings/` directly), authoring a second
`source.relation` binding to it puts both bindings in the same DD-133 §3c
conformance group whether or not you declare `conformance:` explicitly —
`compile` requires it once a second binding targets the same class. Before
authoring, state this contract up front rather than discovering it only when
`compile --check` fails: **every binding in the group must share identical
grain type-kinds, an identical identity strategy and type-kinds, an identical
mapped-property type set, and the same load/SCD/relationship/conflict/union
policy.** Run `kairos-ontology plan-sources --class <IRI>` first (see below) to
see the existing binding's grain/identity type-kinds and confirm the new
source can actually satisfy that contract before hand-authoring 2+ bindings
worth of work. If the sources have heterogeneous key types (e.g. one string,
one integer natural key), raw conformance is structurally infeasible — route to
`int_merged__<entity>` (above) instead of a second `source.relation` binding.

**`plan-sources` — preview conformance before authoring.**
`kairos-ontology plan-sources --class <IRI> [--source <system>.<table>]` reports,
for a canonical class: its existing bindings' grain/identity type-kinds, and —
when `--source` is given — whether that candidate source's column types would
satisfy or violate the DD-133 §3c contract if bound directly. This runs the same
conformance-type comparison `compile` runs, one step earlier in the workflow, so
a raw-conformance-infeasible pairing (e.g. disjoint key types) is caught before
any bindings are hand-authored, not after.

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

Null policy is compiler-inferred from expression structure and target range; it
must not be authored at field level. The `null` literal and kind-specific
operators (`is-null`, `coalesce`, `nullif`) are the only null-control levers.
Do not add a `nullPolicy` key to a `fields:` entry.

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

`technicalFields:` with `purpose: identity` materializes a source column into
Silver output for identity use without asserting an ontology property. Use it
when a key column must reach Silver but has no canonical property (e.g. a
composite key component, or a surrogate FK). Do not double-map: a column that
appears in both `fields:` (as a `property:`) and `technicalFields:` raises
`identity.ambiguous-key-mapping` at compile time. See `exemplar-binding.yaml`
for a worked example with a composite grain and `purpose: identity`.

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

**Start from `kairos-ontology propose-relationships`, not from a blank block.**
It reads the accelerator blueprint's declared `cross_domain_relationships` (the
object property is *read*, not guessed) plus the hub's own `owl:ObjectProperty`
declarations, matches join columns against other bindings' `identity.sourceKey`,
and renders a pasteable entry including the `externalReference` key contract.
Anything it cannot derive is emitted as an explicit sentinel
(`<CONFIRM_JOIN_COLUMN>`, `<CONFIRM_KEY_TYPE>`) — confirm every one; a proposal
is a starting point, never authority. Endpoints matched by `local-name` rather
than `uri` mean the hub authored its own class instead of binding the
reference-model one; check it really is the same concept before accepting.

**A relationship-purpose technical field with no relationship is a warning, not
a plan.** If a binding carries `technicalFields:` entries with
`purpose: relationship` and `relationships: []`, `compile --check` emits
`relationship.unrealized-technical-field` (warning, never blocking). That is
legitimate while the parent domain is unbound — but it means the FK reaches
Silver as a raw column with no join, no surrogate key and no orphan window, so
downstream consumers must join by hand. Resolve it or record why you did not.

**Self-referential relationships (same class → same class) are not supported.**
A `relationships:` entry whose `target` resolves to the binding's own
`target.class` (e.g. a `party:Party` parent/child company hierarchy modeled as
`party:Party` → `party:Party`) fails compile with
`relationship.self-reference-unsupported` (`DD-133-safety`): the generated join
would emit `ref('<model>')` inside that same model (a dbt dependency cycle) and
a second `<model>_sk` column colliding with the model's own surrogate key. This
applies even though the same parent/child shape across two *different* classes
compiles fine. There is no supported construct for this today (real feature
support is a separate compiler change, not a workflow step). The documented
interim workaround: keep the foreign-key column materialized as a
`technicalFields:` entry with `purpose: relationship` (same mechanism already
used for not-yet-resolvable cross-domain FKs) instead of a `relationships:`
entry — this carries the raw key column into the silver output without
authoring the join Kairos cannot yet compile. Resolve the hierarchy with a
self-join **downstream in Gold**, where the parent side is a separate model and
no cycle exists. Note that a "thin alias model" does *not* solve this: an alias
selecting from the silver model would still be referenced by it
(`customer__self` → `customer` → `customer__self`), which is the same cycle.

### 6a. One source table, several canonical entities

**Nothing constrains a source relation to a single binding.** A wide operational
table routinely spans several domains — an `orders` table carries booking,
party, consignment and equipment concepts at once. Author **one binding per
canonical entity**, all over the same `source.relation`:

```yaml
# integration/bindings/Qargo-orders-to-booking.binding.yaml
metadata: { name: Qargo-orders-to-booking, domain: booking }
source:   { relation: Qargo.orders }
target:   { class: booking:Booking }
grain:    { columns: [order_id] }          # one row per order
```

```yaml
# integration/bindings/Qargo-orders-to-party.binding.yaml
metadata: { name: Qargo-orders-to-party, domain: party }
source:   { relation: Qargo.orders }        # same relation, different entity
target:   { class: party:Party }
grain:    { columns: [customer_company_id] } # one row per customer, NOT per order
```

Rules that make this safe:

- Each binding carries its **own** grain, identity, load policy and quality. The
  party binding's grain is the customer key, not the order key — otherwise the
  party model repeats once per order.
- `metadata.name` must be unique and the two land in different domains, so
  `compile <domain>` scopes them separately and no artifact collides.
- Two bindings for the **same** class in the **same** domain are a different
  case: they need a `conformance:` block or they fail
  `conformance.group-required`.
- `kairos-ontology audit-column-coverage` names bound tables whose affinity
  analysis assigned them a domain nothing binds them to — that is the prompt to
  author the second binding.

Do **not** reach for a dbt split model just to separate the entities; that is
only needed when relational logic (aggregation, joins, grain change) is
genuinely required.

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
- Reading a raw ontology serialization (`.ttl`/`.rdf`/`.owl`) as text; use
  `resolve-ontology`, `show-class-inventory`, `list-class-properties`, or
  `explain-term` instead.

## Related skills

- **kairos-design-domain** — create the bounded canonical ontology slice first.
- **kairos-design-source** — import source authority and PII-safe samples.
- **kairos-develop-dbt-transformation** — author ordinary contracted relational
  models when binding expressions are insufficient.
