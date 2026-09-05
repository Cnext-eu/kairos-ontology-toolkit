# DD-213: The Silver contract is declared, not derived — bindings conform to it

**Status:** Accepted — Gate A implemented; Gate B not built
**Date:** 2026-09-01
**Affects:** a new `model/contracts/<domain>.contract.yaml` authored input and its packaged JSON
Schema; `core/compiler/kernel.py` (new `contract.*` safety rules), `core/compiler/adapter.py`
(contract-supplied model/column name, set, order, type), `core/compiler/conformance.py`
(identical-property-set rule relaxed for governed classes), `core/compiler/bindings.py` (new
optional `unmapped:` key), `core/compiler/scope.py` (foreign-domain contract resolution); a new
`scaffold-contract` command; `kairos-design-domain` and `kairos-design-mapping`. Amends DD-133 §2, §3, §3c, §5 and revisits DD-020's deferral of Silver
stability to an unbuilt release process.
**Implementation:** design only — see
[`dd-213-silver-entity-contract.md`](../dd-213-silver-entity-contract.md) for the closed schema,
the full rule table, the release-time classification table, and the adoption path.

### Context

The ontology hub is meant to give each data domain a canonical, source-agnostic Silver model
that new sources *bind to* and that stays stable because upstream data products and existing
bindings depend on it. The v5 compiler does not provide that, because the Silver contract is
never declared anywhere — it is computed from whatever the bindings happen to say.

Every physical fact about an emitted Silver model comes from the bindings: the model name is
`_slug(class local name)` (`adapter.py:779`), the column name is
`camel_to_snake(property local name)` (`kernel.py:682`), the column set is only the properties
some binding explicitly maps (DD-133 §8b: "inherited semantic breadth never widens physical
breadth"), and the column order is the authored `fields:` list order (`adapter.py:787`). DD-133
§2 calls the domain TTL the "authoritative canonical Silver model," but that authority is
semantic only.

The result is that ordinary authoring actions silently change a published contract: deleting a
`fields:` entry drops a column; reordering `fields:` reorders columns and changes the parity
fingerprint; renaming an ontology property renames the physical column. Worse for the stated
goal, onboarding a *second* source cannot leave the model alone —
`conformance.property-incompatible` (`conformance.py:172`) requires every binding in a
conformance group to declare an **identical** property set, so a new source either gets
mutilated to match the incumbent or forces an edit to every existing binding. None of DD-133
§5's ten safety rules is a stability rule; all ten check one binding's internal consistency.
SHACL, which could express coverage, is validated by a separate `validate` command and has
never been in the compile path. `kairos-ext:silverColumnName` and `silverTableName` exist but
are read only by the retired v4 projector, so no name decoupling is available at all.

DD-020 accepted the ontology-identifier-to-physical-name coupling knowingly and deferred
breaking-change management to "the hub release process." That release process is Phases 5–6 of
[the architecture document](../ontology-dbt-dataplatform-design-architecture.md) and is not built —
and even when it is, a comparator with no declared contract only reports diffs in an artifact
nobody ever agreed to, after the fact.

### Decision

Introduce a third authored input, `model/contracts/<domain>.contract.yaml`, as a closed,
JSON-Schema-validated document sitting between the ontology (meaning) and the bindings (source
fulfilment). It declares, per canonical entity: a stable `modelName`; the ordered property list
with stable `columnName`, canonical `type`, `nullable`, and `requirement: required | optional`;
governed technical and relationship columns; the canonical grain and identity contract; a
per-entity `stability` and `closed` flag; and per-column `lifecycle.deprecated` metadata. Column
name and model name default to today's derivation rules, so decoupling is opt-in per column.

Bindings then **conform to** the contract rather than constitute it, enforced by two gates:

- **Gate A — compile-time, stateless.** A new `contract.*` diagnostic family extends DD-133 §5:
  every `required` property must be mapped by every binding for the class; a `closed` entity
  rejects any property, relationship, or technical field it did not declare; resolved canonical
  type, nullability, grain, and identity must *match* the contract rather than define it; and a
  contract-optional property a source cannot supply must be named explicitly in a new
  `EntityBinding` key, `unmapped:`, rather than silently absent. For a governed class the
  contract supplies the emitted column set, order, names, and types — an `unmapped` property
  still emits its column as a typed NULL for that source's rows.
- **Gate B — release-time, stateful, outside compile.** The architecture document's
  two-manifest comparator, with the contract file diff as the primary reviewable unit and a
  *contract-relevant projection* of the parity manifest as corroborating evidence, against a
  fixed change-classification table. The full manifest hashes all 15 `ColumnSpec` fields, of
  which the contract governs 5, so comparing it unfiltered would read every binding edit as a
  contract change. Comparator-assisted, human-approved, unknown changes block.

Gate A is ordered before Gate B, reversing the current roadmap. Gate A prevents the break during
the ordinary act of onboarding a source; Gate B only reports it afterwards.

Adoption is incremental, not a clean break: a domain with no contract file compiles exactly as
it does today with one advisory warning, and `scaffold-contract <domain>` generates a contract
from the current `CompilePlan` whose adoption is a provable no-op emit (`SilverModelSpec`
already carries the resolved columns, order, types, nullability, grain, and identity). Once a
contract file is present it is authoritative for every class it names.

### Consequences

A new source can bind to an existing Silver model without reshaping it, which is the point.
Because the contract fixes the column set, `conformance.property-incompatible`'s
identical-property-set requirement is **replaced** for governed classes by contract conformance
— a genuinely partial source can now join a conformance group by declaring its gaps, which is
the largest authoring improvement here and a deliberate behavior change. Reordering a binding's
`fields:` becomes fingerprint-neutral. An ontology rename becomes a relabelling rather than a
downstream break, restoring inside a governed artifact the intent of the v4-only
`kairos-ext:silverColumnName`.

The costs are real: a third artifact to author and review, a new mandatory `unmapped:`
declaration on partial bindings, and a governed change process for what is today a one-line YAML
edit. That friction is the deliverable — it is what makes the model a contract.

Not addressed, deliberately: dbt `versions:` remains the separate deferred design, though this
answers its first open question (stable logical identity across a rename); coverage/completeness
state stays retired per DD-133 §9 — `required`/`optional` is an interface declaration, never a
progress metric; and Gold/MDM contracts are a separate question, though both inherit Silver's
new stability for free.

On acceptance, DD-133 §2's layout block, §3's closed binding schema, §3c's conformance rules,
and §5's rule list all require amendment, and `kairos-design-domain` becomes the contract's
owner while `kairos-design-mapping`'s brief narrows to "satisfy this contract from this source."
The `contract.*` rows are added to `diagnostic-codes.md` by the implementing change, not by this
one — `tests/test_diagnostic_catalog.py` fails on any documented code with no construction site.

This design was challenged against the compiler before acceptance, and five findings changed it.
The union model currently takes its column set from `base_model` — the binding that sorts first
by *filename* (`kernel.py:1487-1497`) — which is harmless only while identical property sets are
enforced; the relaxation therefore had to make the contract the column authority for source-branch
*and* union models, padding every branch, or it would have emitted invalid `union all` SQL.
Padded columns must carry `include_in_change_detection: False`, or a source that later starts
supplying the column would trigger a mass SCD2 re-versioning. Cross-domain relationship FK names
embed the *parent's* model name, so `BuildScope` must resolve foreign-domain contracts rather
than leaving it to a naming default. The declared column order was corrected to
properties → technical → relationships, matching actual emission, and the contract's scope is
decided by `SilverColumnRole` (`business`/`business-natural-key`, plus `foreign-key`) rather
than by position -- `SilverModelSpec.columns` interleaves compiler-owned generated keys and
envelope columns with the author-declared ones. And canonical type is *not*
contract-stabilised — a diverging source type still requires a contracted dbt model, since `cast`
is deliberately excluded from DD-133 §4's allow-list. A cheaper alternative — treating the
previous release's parity manifest as the contract — was considered and rejected as descriptive
rather than prescriptive, unable to gate a class's first binding, and fatal to `compile --check`
statelessness.

Two questions are left open for review in the companion document: NULL semantics for `unmapped`
properties under `prefer-precedence` and `deduplicate` union policies; and one contract file per
domain versus one per entity.
