# DD-213 companion — the declared Silver entity contract

> Detailed specification for [DD-213](toolkit-design-decisions.md#dd-213-the-silver-contract-is-declared-not-derived--bindings-conform-to-it).
> **Status: Proposed.** Nothing in this document is implemented. It is normative for the
> proposed closed `SilverContract` schema, the `contract.*` compile-time rules (Gate A), and
> the release-time classification table (Gate B). It amends, but does not yet supersede,
> [DD-133](dd-133-v5-entity-binding-compile.md) §2, §3, §3c, and §5.

## 1. The inversion this fixes

DD-133 §2 names `model/ontologies/<domain>.ttl` the "authoritative canonical Silver model."
That is true *semantically* and false *physically*. Every physical fact about an emitted
Silver model is computed from the bindings:

| Physical fact | Derived from | Site |
|---|---|---|
| Model name | `_slug(class local name)` | `compiler/adapter.py:779` |
| Column name | `camel_to_snake(property local name)` | `compiler/kernel.py:682` |
| Column set | only properties an `EntityBinding` explicitly maps | DD-133 §8b |
| Column order | authored `fields:` list order | `compiler/adapter.py:787` |
| Column type | canonical type inferred from source type + property range | DD-133 §4 |

The ontology declares meaning; the bindings *constitute* the contract. The dependency runs
the wrong way: a contract should constrain its implementations, but here each implementation
redefines the contract. Six observable consequences:

1. **Silent column loss.** Deleting a `fields:` entry drops a Silver column. None of
   DD-133 §5's ten safety rules is a stability rule — all ten check one binding's internal
   consistency.
2. **Silent column reordering.** Reordering `fields:` in YAML reorders the emitted columns
   and changes the parity fingerprint (`silver_parity_fields` hashes `columns.{index}.*`,
   `projections/dbt/silver_contract.py:76`), with no semantic change whatsoever.
3. **First-binding-wins, then the contract fights back.**
   `conformance.property-incompatible` (`compiler/conformance.py:172`) requires every binding
   in a group to declare an **identical** property set. Onboarding a second source therefore
   either mutilates the new binding or forces an edit to every existing one — a source
   onboarding event rewriting the canonical model. This is the exact inverse of "a new source
   binds to a stable Silver model."
4. **Ontology renames are breaking physical renames.** Renaming a property in TTL renames the
   Silver column, breaking every downstream `ref()`, Gold model, and BI model. DD-020
   accepted this coupling explicitly and deferred stability to "the hub release process" —
   which is Phases 5–6 of the architecture document and is not built.
5. **The decoupling annotations are dead on the v5 path.** `kairos-ext:silverColumnName` and
   `kairos-ext:silverTableName` are read only by the retired v4 projector
   (`projections/medallion_dbt_projector.py:249`, `projections/dbt/bind.py:264`). The v5
   compiler never consults them, so there is currently *no* way to decouple a physical name
   from an ontology local name.
6. **No release has a predecessor.** `silver_parity_fields` proves internal consistency of
   one emit. There is no baseline, no comparator, no deprecation window.

Note that (1)–(3) are *authoring-time* breakages: they happen in the ordinary course of
onboarding a source, before any release process could observe them. A release-time comparator
alone would report the diff after the fact, in an artifact no one ever agreed to.

## 2. The missing artifact

A third authored input, between ontology and bindings:

| Artifact | Answers | Changes when | Owner |
|---|---|---|---|
| `model/ontologies/<domain>.ttl` | What does this *mean*? | the business meaning changes | domain / business |
| **`model/contracts/<domain>.contract.yaml`** | What does Silver *expose*, stably? | a governed release decides | data architecture |
| `integration/bindings/*.binding.yaml` | How does *this source* fulfil it? | a source is onboarded or changes | source onboarding |

Two properties keep this compatible with the v5 architecture:

- It is an **interface declaration** (what the contract *is*), not readiness/coverage/claim
  state (how far along you are). DD-133 §9 retired the latter; this does not reintroduce it.
  There is no completeness percentage, no claim registry, no phase state.
- It is **authored input, not derived history**. `compile --check` stays stateless and
  independent of Git history, satisfying the architecture document's Phase 5 constraint that
  no generated baseline may live under `model/`. The contract is hand-authored and reviewed
  like an ontology, not emitted like a manifest.

### Alternative considered: the previous release's manifest as the contract

Rejected, but recorded so review does not re-litigate it. Instead of a new authored artifact,
treat **the previous release's parity manifest under `ontology-hub-publish/`** as the contract.
That sibling tree is already the derived-output location DD-206 tracks a release allowlist in, so
it sidesteps the architecture document's "no generated baseline under `model/`" rule, needs no new
schema or authoring burden, and reuses the Phase 5 comparator wholesale. It is markedly cheaper.

It loses on three counts. It is *descriptive, not prescriptive*: it records what was emitted, so
it cannot express `required` versus `optional`, a deprecation window, or a `columnName` pinned
ahead of an anticipated ontology rename. It cannot gate the **first** binding of a class — which
is precisely when the shape is decided and where first-binding-wins does its damage. And it makes
`compile --check` depend on release history, breaking the statelessness the architecture document
requires and that DD-133 §8 builds the `BuildScope` around.

A declared contract is more expensive to author and is the only option that can say what Silver
*promises* rather than what it *happens to contain*. What it does **not** promise is covered in
§4's "What the contract does not stabilise" — canonical type remains source-derived.

### Why closed YAML rather than TTL or SHACL

- **Not TTL.** v5's established direction is to move execution-relevant declarations out of
  RDF into closed, JSON-Schema-validated documents (DD-133 §3). RDF's open-world default is
  the wrong semantics for an artifact whose entire value is "unknown fields are rejected."
- **Not SHACL.** `model/shapes/` is validated by a separate `validate` command
  (`core/design_validation.py`) and has never been in the compile path. SHACL can express
  cardinality but not physical column naming, declared column order, canonical type labels,
  or deprecation lifecycle — the majority of what this contract carries. SHACL keeps its
  current job: semantic validity.

## 3. Proposed `SilverContract` schema (closed)

One document per domain. Unknown fields rejected; duplicate keys rejected at loader level;
validated by a packaged JSON Schema, then converted to frozen dataclasses — never into RDF.

```yaml
apiVersion: kairos.eu/v5          # required, pinned
kind: SilverContract              # required literal
metadata:
  domain: party                   # required; must match model/ontologies/<domain>.ttl
entities:
  - class: party:Customer         # required; resolved against the ontology import closure
    modelName: customer           # optional; default `_slug(<class local name>)`
    stability: preview | stable | deprecated   # required
    closed: true                  # required; `false` permitted only while stability=preview
    grain:
      columns: [customer_id]                   # EMITTED column names (see note below)
    identity:
      strategy: source-natural | surrogate     # required
      businessKey: [customer_id]               # optional; emitted column names
    properties:                                # declared order IS emitted column order
      - property: party:customerId             # QName or absolute IRI; both occur in real hubs
        columnName: customer_id                # optional; default camel_to_snake(local name)
        type: string(64)                       # canonical type label (canonical_type_label)
        requirement: required                  # required | optional
        nullable: false                        # required; `optional` implies `nullable: true`
      - property: party:displayName
        type: string(256)
        requirement: optional
        nullable: true
      - property: party:legacyRating
        type: string(16)
        requirement: optional
        nullable: true
        lifecycle:
          deprecated:
            since: "3.2.0"
            removeIn: "4.0.0"
            replacedBy: party:creditRating     # optional
    technicalColumns:                          # DD-139 passthrough outputs, governed
      - name: source_batch_id
        type: string(64)
        requirement: optional
        nullable: true
    relationships:                             # FK columns emitted by `relationships:`
      - property: party:hasAccount
        target: party:Account
        columnName: has_account_account        # optional; default kernel.py:1808 rule
```

`EntityBinding` gains exactly one new optional key — an additive change to the closed schema,
visible through `apiVersion`:

```yaml
unmapped: [party:displayName]     # contract-optional properties this source cannot supply
```

Declaring `unmapped:` is mandatory rather than inferred, matching v5's standing rule that
nothing load-bearing is defaulted (DD-133 §3a "no SCD or incremental behavior is inferred";
§3b's required `missingParent`/`ambiguousParent`). A silent gap and a reviewed gap must not
look the same in a diff.

### Grain and identity are stated as emitted column names

Both are lists of **emitted column names**, not canonical property tokens. Two reasons, both
found by running `scaffold-contract` against a real client hub rather than a synthetic
fixture:

- A materialized grain is a *physical* statement about the table, and real bindings routinely
  grain on a DD-139 **technical** column that is no semantic property at all — in
  fracht-client-ontology-hub, `source_record_id` is both the grain and a `technicalFields:`
  entry. A properties-only grain could not express that, and refused to scaffold 3 of 4
  domains.
- The compiler already resolves identity this way: DD-133 §8b has `EntityIdentityFact.naturalKey`
  carry mapped target *output* column names. Stating grain in the same terms is more consistent
  with the existing compiler, not less.

Column names stay source-agnostic — the contract declares them. `contract.grain-not-required`
requires each grain/business-key column to be declared under `properties:` **or**
`technicalColumns:`, and to be `requirement: required`, which keeps it
supplied-by-construction so the §8b source→output resolution always applies.

A key column is matched to its emitted column by three routes, because real bindings use all
three: a `fields:` entry whose expression is exactly that source column; a `technicalFields:`
entry whose expression is exactly that source column (its emitted name often differs — fracht
grains on `BL_PK` through a technical column named `source_record_id`); or a technical entry
whose name equals the source column.

### Term references accept both authoring forms

`class`, `property`, `target`, and `replacedBy` accept a prefixed QName (`party:Customer`) or
an absolute IRI (`https://fracht.com/ont/party#FrachtParty`). Real hubs author full IRIs; a
QName-only schema made the scaffolder emit documents its own loader rejected. The default
column name takes the local part after `#`, else after the last `/`, else after `:` — a bare
`split(":")` mangles an IRI into `//fracht.com/ont/party#partyReference`.

### Reserved names outside the contract

The DD-104 audit envelope — `_source_system`, `_source_record_key`, `_loaded_at` — plus the
generated surrogate/integration/IRI columns are compiler-owned and always emitted. They are
outside the contract's `closed` scope; the leading `_` prefix and the generated-key names stay
reserved and a contract that declares one is rejected.

### Cross-domain relationship targets

Relationship FK columns are named `{property_column}_{target_model}` (`kernel.py:1808`),
embedding the **parent's** model name — while `compile <domain>` resolves only bindings whose
`metadata.domain` matches the selected domain (DD-133 §8). So when domain A's contract pins a
`modelName` other than `_slug(class)`, domain B's child models must read **domain A's contract**
to name their FK columns correctly, and a parent `modelName` change silently breaks a child
domain that is never recompiled in the same run.

Settled here rather than left to the default: `BuildScope` resolves the contracts of foreign
domains for every cross-domain relationship target and folds them into the provenance hash, and
the parent's declared `modelName` is authoritative for the child's FK column name. Gate B must
correspondingly classify a `modelName` change as breaking for **dependent domains**, not only
for the domain that owns the entity. This makes contract loading scope-aware from the start
(§10 slice 1) rather than a later correction.

## 4. Gate A — compile-time rules (stateless, non-suppressible)

These extend DD-133 §5's safety kernel. They are `error` severity, entity-level blocking, and
run before materialize/render like every other §5 rule. Codes use a new `contract.*` family.

### Contract-load rules (whole file blocks on failure)

| Code | Condition |
|---|---|
| `contract.property-unresolved` | A declared property does not resolve in the ontology import closure through the DD-103 semantic index under the `rdfs` profile, or resolves to more than one distinct URI. |
| `contract.class-unresolved` | A declared `class` does not resolve, or is not a hub-namespace class. |
| `contract.column-name-collision` | Two declared properties, technical columns, or relationships resolve to the same `columnName` (case-insensitive), or collide with a reserved name from §3. |
| `contract.grain-not-required` | A `grain.properties` or `identity.businessKey` entry is not also declared in `properties:` with `requirement: required`. This makes grain and identity columns mapped-by-construction, so the DD-133 §8b source→output resolution always applies. |
| `contract.closed-requires-preview` | `closed: false` on an entity whose `stability` is not `preview`. |
| `contract.optional-not-nullable` | A `requirement: optional` property declares `nullable: false`. A source may leave it unmapped, in which case the column carries a padded NULL for that source's rows, so `optional` implies `nullable: true`. |
| `contract.duplicate-entity` | Two entries declare the same `class`. |
| `contract.deprecated-shape` | A `lifecycle.deprecated` block is missing `since` or `removeIn`, or `replacedBy` does not resolve. Version *values* are validated for shape only — never compared against release history, which would make `compile --check` stateful. |

### Per-binding rules

| Code | Condition |
|---|---|
| `contract.class-not-declared` | The binding's `target.class` is absent from a present contract file for its domain. |
| `contract.required-property-unmapped` | A `requirement: required` property has no `fields:` entry in this binding. |
| `contract.property-not-declared` | The binding maps a property absent from the contract, and the entity is `closed: true`. |
| `contract.optional-property-undeclared` | A `requirement: optional` property is neither mapped in `fields:` nor listed in `unmapped:`. |
| `contract.unmapped-property-required` | `unmapped:` names a `required` property, an undeclared property, or a property the same binding also maps. |
| `contract.type-mismatch` | The canonical type resolved for a mapped field differs from the contract's declared `type` for that column. This is the rule that stops a new source silently widening or retyping an existing column. |
| `contract.nullability-mismatch` | A mapped field's resolved nullability contradicts the declared `nullable`. |
| `contract.grain-mismatch` | The binding's `grain.columns`, resolved to output columns, differs from the contract's declared grain. |
| `contract.identity-mismatch` | The binding's `identity.strategy`, or its `businessKey` resolved to output columns per DD-133 §8b, differs from the contract's declared identity. |
| `contract.unmapped-in-hash-inputs` | An `unmapped:` property's source column also appears in `load.incremental.canonicalHashInputs`. Padded NULLs must never participate in the SCD2 canonical hash. |
| `contract.relationship-not-declared` | The binding declares a `relationships:` entry whose `(property, target)` pair is absent from the contract, and the entity is `closed: true`. |
| `contract.technical-field-not-declared` | The binding declares a `technicalFields:` entry absent from `technicalColumns:`, and the entity is `closed: true`. |

### What changes in emission

**The governing invariant:** *the emitted column set of a governed class is a pure function of
its contract — independent of how many bindings exist, and independent of their filenames.*

That last clause is not decoration. Today the conformance union is built as
`replace(base_model, columns=tuple(... for column in base_model.columns))`
(`kernel.py:1487-1497`), where `base_model` is `conformance_bases.setdefault(target_class, model)`
— **the first binding in path-sorted order** (DD-133 §8). It is harmless only because
`conformance.property-incompatible` currently forces identical property sets. The relaxation
below removes that guarantee, so without this invariant the union would take its columns from
whichever binding sorts first by *filename*, and a `union all` across branches with differing
column counts would emit invalid SQL.

The contract is therefore the column authority for **both** model kinds of a governed class —
the `SOURCE_BRANCH` models and the `UNION` model (and the single `ENTITY` model in the
one-source case). `conformance_bases`/`base_model` ceases to be a column source entirely.
Concretely, the contract — not the binding — supplies:

- the model name (`modelName`, defaulting to today's `_slug` rule);
- the column **set**: every declared property is emitted on **every branch**, including ones a
  branch's binding listed under `unmapped:`, which are padded as a typed `NULL` for that source's
  rows. Padding at the branch level, not only in the union, is what keeps `union all` well-formed.
  *This is the mechanism that makes a partial new source bindable without reshaping Silver;*
- the column **order**: `properties:` declared order, then `technicalColumns:`, then
  `relationships:` — matching today's actual emission order (`adapter.py:874` then
  `adapter.py:940`, with relationship FK columns added later at `kernel.py:1808`). Reordering
  a binding's `fields:` becomes fingerprint-neutral;
- the column **name** (`columnName`, defaulting to today's `camel_to_snake` rule), decoupling
  ontology renames from physical renames and restoring the intent of the v4-only
  `kairos-ext:silverColumnName` inside a governed artifact;
- the column **type** and **nullability**, which the binding must match rather than determine.

**Which columns the contract governs is decided by `SilverColumnRole`, not by position.**
`SilverModelSpec.columns` interleaves author-declared columns with compiler-owned ones: a
generated surrogate join key (`surrogate-join-key`, emitted as `<model_name>_sk`) leads the
list, and `_source_identity_ref` (`source-identity`) and `_loaded_at` (`audit`) follow the
mapped columns. Only the `business` and `business-natural-key` roles are author-declared, plus
`foreign-key` for relationships; those are the contract's scope. The rest are emitted
unconditionally and sit outside `closed`. Two envelope columns — `_source_system` and
`_source_record_key` — really are template-only and never appear in `SilverModelSpec.columns`
at all, which is why `materialize.py:120-126` has to union them back in before validating
quality-rule column references. Partitioning by role rather than by name or index is what
keeps this correct as the envelope grows.

Every other `ColumnSpec` field stays binding-derived, and deliberately so — `expression`,
`mapping_resource_uri`, `mapping_expression`, `description`, `tests`, `role`, `provenance`,
`generated_after_mapping`, `runtime_generated`, and `include_in_change_detection` are
implementation, not contract. The contract governs 5 of `ColumnSpec`'s 15 fields; see §5 for why
that distinction matters to Gate B.

**Padded columns are excluded from change detection.** `ColumnSpec.include_in_change_detection`
defaults to `True`, so a naively padded NULL column would participate in the SCD2 canonical hash.
The day that source *began* supplying the column, every row's hash would change at once — a mass
re-versioning event across the whole entity. Padded columns are therefore emitted with
`include_in_change_detection: False`, and `contract.unmapped-in-hash-inputs` (§4) rejects a
binding that names an `unmapped` property's source column in
`load.incremental.canonicalHashInputs`.

### What the contract does not stabilise

Shape, names, order, and nullability are contract-governed. **Canonical type is not fully
so.** A field's canonical type is *inferred* from the source column's type and the property's
range (DD-133 §4), and `cast` is deliberately excluded from the expression allow-list — it
belongs in kairos-prep, not a mapping expression. So a source whose column is `varchar(100)`
cannot satisfy a contract declaring `string(64)`: `contract.type-mismatch` blocks it, and the
only remedy is a contracted dbt model via `source.dbtModel`.

Stated plainly: a new source binds to a stable *shape* without reshaping it, but a source whose
*types* diverge still needs a contracted intermediate. Adding coercion machinery would reopen a
deliberate DD-133 §4 exclusion and require per-adapter capability negotiation for widening
safety; that is out of scope here and is not smuggled in.

### Consequent relaxation of `conformance.property-incompatible`

For contract-governed classes, `conformance.property-incompatible`'s identical-property-set
requirement is **replaced** by the rules above: each binding's property set must be a subset
of the contract, `required` must be covered by every binding, and the gaps must be explicit.
The identical-set rule remains in force for classes with no contract entry, and
`conformance.grain-incompatible` / `identity-incompatible` remain in force unchanged (the
contract makes them redundant rather than wrong — every member matches the contract, so every
member matches every other member). This is a deliberate behavior change and is the single
largest authoring improvement in this proposal: it is what lets a genuinely partial source
join a conformance group.

## 5. Gate B — release-time classification (stateful, outside compile)

Gate B is the architecture document's two-manifest comparator, with one addition: the
**contract file diff is the primary reviewable unit**, and the parity-manifest diff is the
corroborating evidence that the emit matches the contract. Classification stays
comparator-assisted and human-approved, per the architecture document's existing stance.

**The full parity manifest is the wrong comparison surface for this.** `silver_parity_fields`
hashes *every* field of `ColumnSpec` per column (`columns.{index}.{field}`,
`projections/dbt/silver_contract.py:76`), and `ColumnSpec` has 15 fields
(`projections/dbt/specs.py:315-333`) of which the contract governs 5. The other 10 —
`expression`, `mapping_resource_uri`, `mapping_expression`, `description`, `tests`, `role`,
`provenance`, `generated_after_mapping`, `runtime_generated`, `include_in_change_detection` —
are binding-derived implementation. Two releases with an *identical* contract therefore produce
*different* parity manifests whenever any binding's expression changes, so an unfiltered manifest
diff reads every ordinary binding edit as a contract change.

Gate B must therefore compare a **contract-relevant projection** of the manifest — model
identity plus the contract-governed `ColumnSpec` fields (`name`, canonical/physical type,
`nullable`, ordinal position) — and classify against the table below. The full 15-field
fingerprint keeps its own separate job: proving release *reproducibility* (that a rebuild of the
same commit yields the same bytes), which is a different question from contract compatibility and
must not be conflated with it.

| Contract change | Class | Minimum bump |
|---|---|---|
| Add `optional` property | additive-compatible | MINOR |
| Add `required` property | breaking — every existing binding now fails `contract.required-property-unmapped` | MAJOR |
| Remove any property | breaking | MAJOR |
| Change `columnName` or `modelName` | breaking | MAJOR |
| Reorder `properties:` | breaking — `select *` and positional consumers | MAJOR |
| `optional` → `required` | breaking | MAJOR |
| `required` → `optional` | behavior-sensitive — downstream nullability | MAJOR |
| Narrow `type` | breaking | MAJOR |
| Widen `type` | behavior-sensitive — safe on one adapter, breaking on another | MAJOR unless adapter-proven |
| `nullable: false` → `true` | behavior-sensitive | MAJOR |
| `closed: false` → `true` | breaking — bindings mapping undeclared properties now fail | MAJOR |
| Mark `lifecycle.deprecated` | additive-compatible | MINOR |
| `stability: preview` → `stable` | no shape change | PATCH |
| Anything unclassified | **unknown** | blocks |

Deprecation is declaration-only until dbt model versioning exists (deferred by the
architecture document): `lifecycle.deprecated` propagates into the emitted dbt column
description and the parity manifest so consumers can see the intent and CI can detect it, but
the column is still removed by a single coordinated MAJOR release.

## 6. Adoption path

The contract must be adoptable incrementally or no existing hub will adopt it.

1. **Absent contract file → today's behavior, exactly.** A domain with no
   `model/contracts/<domain>.contract.yaml` compiles as it does now (derived shape, existing
   conformance rules), with one advisory `contract.domain-ungoverned` warning. No clean break,
   no migration command, no dual authoring.
2. **`kairos-ontology scaffold-contract <domain>`** generates the contract from the current
   `CompilePlan`. This is cheap and exact: `SilverModelSpec` already carries the resolved
   columns, order, canonical types, nullability, grain, and identity
   (`projections/dbt/specs.py:452`), and `canonical_type_label` already produces the stable
   labels the schema needs. The generated contract is byte-reproducible from the plan, so
   adopting it is provably a no-op emit — the parity manifest must be unchanged, which is the
   acceptance test. That test must cover the `SOURCE_BRANCH` and `UNION` models of a
   conformance group, not only the single-source `ENTITY` model: the branch/union split is
   exactly where the column authority moves (§4), so an entity-only assertion would pass while
   the interesting case regressed.
3. **Author intent on top.** The generated contract is a starting point recording *what is*;
   the reviewed edit that follows records *what is promised* — marking `required` vs
   `optional`, setting `stability`, pinning `columnName` where a rename is anticipated.
4. **Once present, it is authoritative** for every class it names. A class in the domain with
   no contract entry blocks under `contract.class-not-declared`, so a governed domain cannot
   silently regrow ungoverned entities.

## 7. Workflow and skill impact

No skill produces a contract today. On acceptance:

- **`kairos-design-domain`** owns contract authoring — the contract is a domain-level artifact
  decided with the ontology, not per source.
- **`kairos-design-mapping`**'s brief changes from "define this entity from this source" to
  "satisfy this contract from this source," which is a strictly better-specified task: the
  target column set, names, types, and nullability are all given rather than invented.
- **`kairos-diagnose-status`** reports contract governance per domain (governed / ungoverned /
  partially governed).
- **`kairos-execute-validate`** gains the contract-load rules as a fast pre-compile check.

## 8. Deliberately out of scope

- **dbt `versions:`.** Unchanged — still the separate design effort the architecture document
  describes. This proposal makes it *tractable* by answering its first open question ("what
  stable logical identity survives a model rename?" — the contract's `class` plus `modelName`),
  but does not attempt it.
- **Coverage, completeness, or readiness state.** Retired by DD-133 §9 and staying retired.
  `required`/`optional` is an interface declaration, not a progress metric, and nothing
  aggregates it into a score or a phase.
- **Gold and MDM contracts.** Gold consumes the `CompilePlan` and would inherit Silver's new
  stability for free; whether Gold needs its own declared contract is a separate question.
- **The `contract.*` diagnostic catalog rows.** `docs/design/diagnostic-codes.md` is drift-
  guarded by `tests/test_diagnostic_catalog.py`, which fails on any documented code with no
  construction site under `core/compiler/`. The rows in §4 are added to that catalog in the
  implementing change, not on acceptance of this design.

## 9. Open questions for review

1. **`unmapped:` NULL semantics under `union-all`.** When one source supplies
   `party:displayName` and another declares it `unmapped`, the union produces real values and
   typed NULLs in one column. That is the intended behavior, but it interacts with
   `conformance.conflict: prefer-precedence` and with `deduplicate` ordering in ways worth
   settling before implementation: should a NULL from a higher-precedence source lose to a
   real value from a lower-precedence one?
2. **One file per domain, or one per entity?** One file per domain matches
   `model/ontologies/<domain>.ttl` and keeps the reviewable unit whole; one file per entity
   produces cleaner diffs and less merge contention on a busy domain.

## 9a. Defect found by Gate A on first contact

Implementing Gate A immediately surfaced a **pre-existing** contract-stability defect,
independent of anything in this design:

> The conformance `UNION` model drops the string length its `SOURCE_BRANCH` models keep.
> A column typed `string(50)` on every branch emits as unsized `string` on the union.

So a class's consumer-facing column type silently widens the moment it gains a second
source — no ontology change, no binding change, no review. Verified with two fully-mapped
sources and no contract present at all, so it is not caused by padding or by contract-driven
emission.

`contract.type-mismatch` is deliberately **not** relaxed to accommodate this. The widening is
real, a downstream consumer would feel it, and a check weakened to hide a defect is worse
than the defect. The consequence is that a governed class gaining its second source reports a
type mismatch until an operator either accepts the widening (edit the contract to `string`,
which Gate B classifies as breaking) or the underlying width loss is fixed.

Root cause, traced by instrumenting `merge_bound_sources` and `shape_project`: both the union
and its branches leave `merge_bound_sources` unparameterized, and the type *parameters* are
restored later from each column's mapping resource. The union's columns have
`mapping_resource_uri` blanked when it is constructed (`replace(column,
mapping_resource_uri="", expression=column.name)` in `kernel.py`) — deliberately, since a union
selects from its branches rather than a source relation — so nothing is left to resolve the
declared width from, and only the branches recover theirs.

Fixing it — carrying the resolved `canonical_type` forward at that point, which is safe because
`conformance.property-incompatible` already requires identical type contracts across a group —
is a change to pre-existing normalization semantics, outside this design's scope. Tracked as
[issue #681](https://github.com/Cnext-eu/kairos-ontology-toolkit/issues/681).
`tests/test_compiler_contracts.py::test_gaining_a_second_source_widens_the_column_type` pins the
current behaviour so the fix has a failing test waiting for it.

## 10. Implementation slices

Four slices, strictly ordered. Each is independently shippable and independently revertible.
The ordering is load-bearing: slice 4 before slice 3 reintroduces the filename-ordering defect
§4 exists to close, and slice 3 before slice 2 makes the emission change unreviewable.

### Slice 1 — schema, loader, `scaffold-contract` (no behaviour change)

- `core/compiler/schema/silver-contract.schema.json`, following the closed-schema conventions of
  the existing `entity-binding.schema.json` (unknown fields rejected, duplicate keys rejected at
  loader level).
- `core/compiler/contracts.py`: frozen dataclasses plus loader, shaped like `bindings.py`. Reuse
  `_canonical_type` (`projections/dbt/mapping_normalize.py:171`) to parse `type:` labels and
  `canonical_type_label` (`projections/dbt/silver_contract.py:17`) for the inverse — no new type
  parsing code is needed.
- The §4 contract-load rules only.
- `scaffold-contract <domain>`, following the `scaffold-binding` click-command pattern in
  `cli/scaffold_binding.py`, reading `CompilePlan.silver_registry`/`shaped_project`
  (`compiler/plan.py`).
- Scope-aware loading per §3's cross-domain rule: `compiler/scope.py` resolves foreign-domain
  contracts and folds them into the provenance hash.
- No kernel wiring — a contract file present in a hub changes nothing yet.
- Tests: new `tests/test_compiler_contracts.py`; a scaffold→parse round-trip; a cross-domain test
  asserting the foreign contract is in scope and in the provenance hash.

### Slice 2 — Gate A rules, warning-only

- Wire contract resolution into `kernel.py` scope resolution; add the §4 per-binding rules at
  **warning** severity.
- Add the optional `unmapped:` key to `entity-binding.schema.json` and `bindings.py`, plus
  `contract.unmapped-in-hash-inputs`.
- Add the `contract.*` rows to `diagnostic-codes.md` in this same change —
  `tests/test_diagnostic_catalog.py` fails both on a documented code with no construction site
  and on a construction site with no row.
- Tests: extend `tests/test_compiler_bindings.py`; every rule fires on a crafted hub, and no
  existing fixture changes its emitted bytes.

### Slice 3 — contract-driven emission

- Make the contract the column authority in `adapter.py` and `kernel.py` for governed classes:
  set, order, names, types, nullability, across `SOURCE_BRANCH`, `UNION`, and `ENTITY` models.
- Pad branches with typed NULLs carrying `include_in_change_detection: False`; build the union
  from the contract, retiring `conformance_bases`/`base_model` as a column source
  (`kernel.py:1487-1497`).
- Leave the other ten `ColumnSpec` fields binding-derived (§4).
- Promote the slice 2 rules from warning to error.
- Tests: byte-identical adoption across entity, branch, and union models; renaming a binding file
  cannot change the emitted column set; a source that later begins supplying a previously-padded
  column triggers no SCD2 re-versioning.

### Slice 4 — conformance relaxation

- Replace `conformance.property-incompatible`'s identical-property-set requirement with contract
  conformance for governed classes only (`conformance.py:172`), leaving it in force for
  ungoverned classes.
- Tests: extend `tests/test_compiler_conformance.py` — a genuinely partial source joins a group
  by declaring `unmapped:`, and the union's columns are unchanged.
