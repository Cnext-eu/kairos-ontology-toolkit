# Diagnostic code catalog — `core/compiler/*.py`

> Companion to [DD-133](dd-133-v5-entity-binding-compile.md). This is the stable catalog
> of every `CompileDiagnostic.code` string literal constructed anywhere under
> `src/kairos_ontology/core/compiler/`. It exists so the code surface can drift-detect:
> `tests/test_diagnostic_catalog.py` parses the same source tree and fails the build if a
> new code is introduced (or an existing one renamed/removed) without this table being
> updated in the same change.

## How to read this table

- **Code** — the literal value assigned to `CompileDiagnostic.code`.
- **Default severity** — the severity used when the diagnostic is constructed, if the
  construction site never overrides `CompileDiagnostic.severity` (default: `error`).
  Recorded as `varies` when the same code is emitted at more than one call site with
  different severities.
- **Rule ID / DD citation** — the `rule_id` argument at the construction site. Most
  diagnostics never pass `rule_id` explicitly and fall back to the `CompileDiagnostic`
  dataclass default, `"DD-133"`; that is recorded as `DD-133 (default)`. Recorded as
  `varies` when the same code is constructed at multiple sites with different `rule_id`
  values.
- **Notes** — how the code is constructed, when it isn't a plain
  `CompileDiagnostic(code="...")` call (e.g. built through a local `_diagnostic`/`_diag`/
  `_reject`/`_add`/`_failure` helper that takes `code` as a parameter, or assigned through
  a lookup-table remap).

No diagnostic code in this codebase is built by string-formatting a dynamic value into
the `code` itself (no `code=f"...{var}..."` patterns exist as of this writing) — every
code below is a fixed literal. If a future change introduces one, add a row here
describing the static pattern (e.g. `technical-field.*`) and extend the AST scan in
`tests/test_diagnostic_catalog.py` to match a pattern instead of an exact literal.

### Out of scope: `dbt-contract.*` lint findings

The `dbt-contract.*` codes are **not** catalogued here, and deliberately so. They are
`DbtContractFinding` values produced by `core/dbt_contract_lint.py` — the offline
`validate-dbt-contracts` lint of the *hand-authored* transforms tree — not
`CompileDiagnostic` values from `core/compiler/`, so the drift guard above neither scans nor
admits them. Their reference lives with the command, in
[`docs/CLI_REFERENCE.md`](../CLI_REFERENCE.md#validate-dbt-contracts-vs-validate-dbt).
Adding one here would make `test_documented_codes_are_all_still_real` fail, since no
construction site for it exists under `core/compiler/`. As of #586 stage (b) that family
includes the seed findings `dbt-contract.seed-docs-unmatched` (warning),
`dbt-contract.seed-unreadable` (warning), and `dbt-contract.seed-model-collision` (error).
The compiler's own seed codes — `dbt-source.dependency-ambiguous` and
`dbt-source.dependency-unresolved` — *are* catalogued, under `dbt_source.py` below.

## `adapter.py` — binding/expression adapter (symbol resolution, type inference)

Constructed via `CompileDiagnostic(code=...)` directly, or through the local
`ExpressionBuilder._diag(expr, code, message)` helper (all default `rule_id`/severity).

| Code | Default severity | Rule ID / DD citation | Notes |
| --- | --- | --- | --- |
| `binding.ambiguous-class` | error | DD-133 (default) | |
| `binding.ambiguous-property` | error | DD-133 (default) | |
| `binding.bad-literal-type` | error | DD-133 (default) | via `_diag` |
| `binding.case-requires-else` | error | DD-133 (default) | via `_diag` |
| `binding.null-policy-incompatible` | error | DD-133 (default) | via `_diag` |
| `binding.object-property-in-fields` | error | DD-133 (default) | An `owl:ObjectProperty` under `fields:`. Remapped to `safety.relationship-endpoint` by `kernel.py`'s `code_map`, and mirrored pre-adapter in `_binding_safety_diagnostics` so `compile --check` reports it even when the binding is blocked before `adapt_binding` runs. Error, not warning: DD-133 §5 rule 3 requires a canonical scalar target type per field and an object property has none, so the emitted artifact is wrong (raw FK as a business attribute — no surrogate key, no join, no orphan window, no ERD edge). `relationships:` accepts an object property whose `rdfs:range` is absent or a class expression (DD-133 §7 — the `deferred-relationship` shape) because the join endpoint is authored explicitly via `target:`/`on:`; `fields:` rejects it because a scalar column has no such endpoint to carry. Explicit raw passthrough remains available as an authored `technicalFields:` entry (DD-139). |
| `binding.property-domain-incompatible` | error | DD-133 (default) | |
| `binding.quality-column-unmapped` | error | DD-133 (default) | |
| `binding.unknown-class` | error | DD-133 (default) | |
| `binding.unknown-column` | error | DD-133 (default) | two call sites; also via `_diag` |
| `binding.unknown-expression` | error | DD-133 (default) | via `_diag` |
| `binding.unknown-identity-strategy` | error | DD-133 (default) | |
| `binding.unknown-key-column` | error | DD-133 (default) | |
| `binding.unknown-macro` | error | DD-133 (default) | via `_diag` |
| `binding.unknown-property` | error | DD-133 (default) | |
| `binding.unknown-relation` | error | DD-133 (default) | |
| `identity.ambiguous-key-mapping` | error | DD-133 (default) | |
| `identity.authored-key-not-supplied` | error | DD-133 (default) | |
| `identity.key-column-in-expression` | error | DD-133 (default) | |
| `technical-field.type-incompatible` | error | DD-133 (default) | |

## `bindings.py` — YAML loader, schema validation, scalar-expression parser

`binding.*` rows come from `_schema_diagnostics`/`_contract_diagnostics`/
`load_entity_binding` (plain `CompileDiagnostic(code=...)`). `expression.*` rows all come
through the local `_reject(diagnostics, resolver, pointer, code, message)` helper used by
`_parse_expression`/`_parse_args`.

| Code | Default severity | Rule ID / DD citation | Notes |
| --- | --- | --- | --- |
| `binding.cdc-operation-ambiguous` | error | DD-133 (default) | |
| `binding.duplicate-key` | error | DD-133 (default) | |
| `binding.not-a-mapping` | error | DD-133 (default) | |
| `binding.scd-correction-incompatible` | error | DD-133 (default) | |
| `binding.schema` | error | DD-133 (default) | one row per Draft-7 JSON Schema violation |
| `binding.yaml` | error | DD-133 (default) | YAML parse failure |
| `expression.ambiguous` | error | DD-133 (default) | via `_reject` |
| `expression.args-empty` | error | DD-133 (default) | via `_reject` |
| `expression.args-missing` | error | DD-133 (default) | via `_reject` |
| `expression.case-branch` | error | DD-133 (default) | via `_reject` |
| `expression.case-empty` | error | DD-133 (default) | via `_reject` |
| `expression.empty-column` | error | DD-133 (default) | via `_reject` |
| `expression.function-not-allowed` | error | DD-133 (default) | via `_reject` |
| `expression.invalid` | error | DD-133 (default) | via `_reject` |
| `expression.literal-datatype` | error | DD-133 (default) | via `_reject` |
| `expression.macro-not-allowed` | error | DD-133 (default) | via `_reject` |
| `expression.null-policy` | error | DD-133 (default) | via `_reject` |
| `expression.operator-not-allowed` | error | DD-133 (default) | via `_reject` |
| `expression.too-deep` | error | DD-133 (default) | via `_reject` |
| `expression.unknown-field` | error | DD-133 (default) | via `_reject` |

## `conformance.py` — multi-source conformance planning

All rows are constructed through the local `_diagnostic(binding, code, message, pointer)`
helper, which always sets `rule_id="DD-133 §3c"`.

| Code | Default severity | Rule ID / DD citation | Notes |
| --- | --- | --- | --- |
| `conformance.api-version` | error | DD-133 §3c | |
| `conformance.conflict-incompatible` | error | DD-133 §3c | |
| `conformance.dedup-identity-incompatible` | error | DD-133 §3c | |
| `conformance.grain-contract-incomplete` | error | DD-133 §3c | |
| `conformance.grain-incompatible` | error | DD-133 §3c | |
| `conformance.group-mismatch` | error | DD-133 §3c | |
| `conformance.group-required` | error | DD-133 §3c | |
| `conformance.group-single-source` | error | DD-133 §3c | |
| `conformance.identity-contract-incomplete` | error | DD-133 §3c | |
| `conformance.identity-incompatible` | error | DD-133 §3c | |
| `conformance.load-incompatible` | error | DD-133 §3c | |
| `conformance.precedence-duplicate` | error | DD-133 §3c | |
| `conformance.property-contract-incomplete` | error | DD-133 §3c | |
| `conformance.property-incompatible` | error | DD-133 §3c | |
| `conformance.provenance-missing` | error | DD-133 §3c | |
| `conformance.relationship-incompatible` | error | DD-133 §3c | |
| `conformance.source-duplicate` | error | DD-133 §3c | |
| `conformance.source-missing` | error | DD-133 §3c | |
| `conformance.target-mismatch` | error | DD-133 §3c | |
| `conformance.type-contract-missing` | error | DD-133 §3c | |
| `conformance.union-incompatible` | error | DD-133 §3c | |

## `contract_conformance.py` — Gate A, per-binding contract conformance (DD-213)

One authored binding compared with one authored contract. Stateless: no Git history, no
prior release. Severity is a *parameter* — these ship at `warning` so a hub can adopt a
contract and see what would block before anything does, and are promoted to `error` once
contract-driven emission lands. A domain with no contract produces none of these.

Constructed through the local `contract_binding_diagnostics.report(code, message, pointer)`
closure, which stamps the caller-supplied severity and the binding's source path.

| Code | Default severity | Rule ID / DD citation | Notes |
| --- | --- | --- | --- |
| `contract.class-not-declared` | varies | DD-133 (default) | The binding's `target.class` is absent from a present domain contract. A governed domain cannot silently regrow ungoverned entities. |
| `contract.class-unresolved` | varies | DD-133 (default) | A contract `class` does not resolve in the ontology import closure, or resolves ambiguously. Needs the DD-103 semantic index, so it lives here rather than with the pure document rules in `contracts.py`. |
| `contract.grain-mismatch` | varies | DD-133 (default) | The binding's `grain.columns`, resolved to canonical properties via the DD-133 §8b source→output rule, differs from the contract's declared grain. |
| `contract.identity-mismatch` | varies | DD-133 (default) | The binding's identity `strategy` or resolved `businessKey` differs from the contract. |
| `contract.nullability-mismatch` | varies | DD-133 (default) | A mapped column's resolved nullability contradicts the contract. |
| `contract.optional-property-undeclared` | varies | DD-133 (default) | A `requirement: optional` property is neither mapped nor listed under `unmapped:`. Explicit rather than inferred: a silent gap and a reviewed gap must not look the same in a diff. |
| `contract.property-unresolved` | varies | DD-133 (default) | A contract `property` does not resolve in the ontology import closure, or resolves to more than one property URI. A contract may not declare a symbol a binding could never bind. |
| `contract.property-not-declared` | varies | DD-133 (default) | The binding maps a property the contract does not declare, on a `closed: true` entity. |
| `contract.relationship-not-declared` | varies | DD-133 (default) | A `relationships:` entry's `(property, target)` pair is undeclared, on a `closed: true` entity. |
| `contract.required-property-unmapped` | varies | DD-133 (default) | A `requirement: required` property has no `fields:` entry in this binding. The rule that makes the contract binding on every source. |
| `contract.technical-field-not-declared` | varies | DD-133 (default) | A `technicalFields:` entry is absent from `technicalColumns:`, on a `closed: true` entity. |
| `contract.type-mismatch` | varies | DD-133 (default) | A mapped column's resolved canonical type differs from the contract's. Canonical type is inferred from the source column and `cast` is excluded from the mapping grammar (DD-133 §4), so a diverging source type needs a contracted dbt model — the contract cannot coerce it. |
| `contract.unmapped-in-hash-inputs` | varies | DD-133 (default) | An `unmapped:` property's column feeds `load.incremental.canonicalHashInputs`. A padded NULL must never join the SCD2 canonical hash, or the entity re-versions wholesale the day the source starts supplying it. |
| `contract.unmapped-property-required` | varies | DD-133 (default) | `unmapped:` names a required property, an undeclared property, or one the same binding also maps. |

## `contracts.py` — declared Silver contract loader and contract-load rules (DD-213)

The document-level half of the declared Silver contract: YAML loading, closed-schema
validation, and the DD-213 §4 rules that need no ontology closure. Rules that *do* need
resolved symbols (`contract.property-unresolved`, `contract.class-unresolved`) and every
per-binding conformance rule live in `kernel.py` and are catalogued in that section.

Constructed via `CompileDiagnostic(code=...)` directly, or through the local
`_entity_diagnostics._diagnostic(code, message, pointer)` closure (all default
`rule_id`/severity).

| Code | Default severity | Rule ID / DD citation | Notes |
| --- | --- | --- | --- |
| `contract.closed-requires-preview` | error | DD-133 (default) | `closed: false` outside `stability: preview`. An open contract is a provisional state, not a permanent one. |
| `contract.column-name-collision` | error | DD-133 (default) | Two declared columns resolve to the same name, or one collides with a compiler-owned name. Reserved shapes are the `_` prefix (DD-104 audit envelope) and the `_sk` suffix (generated surrogate join key, emitted as `<model_name>_sk`). |
| `contract.deprecated-shape` | error | DD-133 (default) | A `lifecycle.deprecated` window is degenerate (`since` equals `removeIn`) or its `replacedBy` is not declared on the same entity. Shape only — version values are never compared against release history, which would make `compile --check` stateful. |
| `contract.duplicate-entity` | error | DD-133 (default) | Two entries declare the same `class`, or two entities pin the same `modelName`. |
| `contract.duplicate-key` | error | DD-133 (default) | Duplicate YAML mapping key. Same detection as `binding.duplicate-key`, re-coded for the contract document. |
| `contract.grain-not-required` | error | DD-133 (default) | A `grain.properties` or `identity.businessKey` entry is undeclared or not `requirement: required`. Keeping keys required makes them mapped-by-construction, so the DD-133 §8b source→output key resolution always applies. |
| `contract.not-a-mapping` | error | DD-133 (default) | The document root is not a YAML mapping. |
| `contract.optional-not-nullable` | error | DD-133 (default) | A `requirement: optional` property or technical column declares `nullable: false`. An unmapped optional column is padded with NULL for that source's rows, so `optional` implies nullable. |
| `contract.schema` | error | DD-133 (default) | Closed-schema violation (unknown field, missing required field, bad enum, or a `type` outside the canonical-type label grammar). |
| `contract.yaml` | error | DD-133 (default) | The document is not parseable YAML. |

## `dbt_source.py` — contracted dbt model source resolution

All rows are constructed through the local `_failure(binding, code, message, pointer)`
helper, which never overrides `rule_id`/`severity` (both fall back to the dataclass
default).

| Code | Default severity | Rule ID / DD citation | Notes |
| --- | --- | --- | --- |
| `dbt-source.columns-invalid` | error | DD-133 (default) | |
| `dbt-source.contract-invalid` | error | DD-133 (default) | |
| `dbt-source.contract-not-enforced` | error | DD-133 (default) | |
| `dbt-source.dependency-ambiguous` | error | DD-133 (default) | #586. A transitive `ref()` name matches both an authored model SQL file under `integration/transforms/dbt/models/` and an authored seed CSV under `integration/transforms/dbt/seeds/`. dbt models and seeds share one `ref()` namespace, so the compiler cannot pick; rename one of them. Constructed both here (filesystem walk, via `_failure`) and in `kernel.py`'s plan-authoritative `scope.inputs` walk (`_dbt_dependency_closures`), which applies identical rules. |
| `dbt-source.dependency-unresolved` | error | DD-133 (default) | A selected model's transitive `ref()` target is missing or ambiguous under `integration/transforms/dbt/models/` and (since #586) under `integration/transforms/dbt/seeds/` — a `ref()` may resolve to exactly one authored seed CSV leaf instead of a model; projection cannot emit a self-contained project otherwise. `ref()` names match authored file stems **case-exactly** (dbt's own semantics), and Jinja `{# ... #}` comments are stripped before extraction, so a commented-out `ref()` never triggers this. Also raised when a dependency file exists but cannot be read or decoded — dependency bytes (including seed CSVs) must be UTF-8. Constructed here (filesystem walk) and in `kernel.py` (the plan-authoritative `scope.inputs` walk and `resolve_scope`'s provenance reads). |
| `dbt-source.grain-invalid` | error | DD-133 (default) | |
| `dbt-source.grain-mismatch` | error | DD-133 (default) | |
| `dbt-source.identity-mismatch` | error | DD-133 (default) | |
| `dbt-source.missing` | error | DD-133 (default) | |
| `dbt-source.model-unresolved` | error | DD-133 (default) | |
| `dbt-source.path-unresolved` | error | DD-133 (default) | |
| `dbt-source.source-ambiguous` | error | DD-133 (default) | #584. A `{{ source('name', 'table') }}` pair in a contracted dbt dependency closure matches more than one distinct physical source-vocabulary table (e.g. two system labels whose snake_case renderings collide). Constructed in `kernel.py`'s `_contracted_source_tables` — like `dbt-source.virtual-source-duplicate`, it is a resolution-context verdict `dbt_source.py` cannot make; the code literal stays in the `dbt-source.*` family so contracted-model failures share one prefix. Binding-attributed with pointer `/source/dbtModel/sqlPath`. |
| `dbt-source.source-unresolved` | error | DD-133 (default) | #584. A `{{ source('name', 'table') }}` pair in a contracted dbt dependency closure matches no physical source-vocabulary table, so the shared `_<name>__sources.yml` catalog could not declare it and the emitted project would fail offline `dbt parse`. The source name must be the toolkit's snake_case rendering of the vocabulary system label (`uri_utils.dbt_source_name`, i.e. `camel_to_snake(label).replace(" ", "_")`) and the table must match its declared `tableName` exactly. Extraction (`dbt_source.extract_sources`) recognizes the positional form and dbt's keyword form (`source_name=`/`table_name=`, either order) and strips Jinja `{# ... #}` comments first, so a commented-out `source()` never triggers this; a call whose arguments cannot be read at all is `dbt-source.source-unparsed` instead. Constructed in `kernel.py`'s `_contracted_source_tables` (see `dbt-source.source-ambiguous` for why). |
| `dbt-source.source-unparsed` | error | DD-133 (default) | #584. An authored SQL file in the contracted dependency closure contains a `source(` call whose arguments static analysis cannot resolve — mixed positional/keyword arguments, `var()`/variable arguments, string concatenation, or a macro-generated name. Detected by comparing `source(` call sites against the spans `dbt_source.extract_sources` actually matched, which closes the whole class of unsupported forms instead of enumerating them; the `\b` anchor keeps a macro merely *ending* in `source` (`my_source(`) from counting as a call site, and Jinja comments are stripped before counting. Fails closed per #584's acceptance criterion that compilation must fail clearly when declarations are missing — the alternative is an emitted project that fails offline `dbt parse` with no compile diagnostic at all. Raised by the filesystem walk (via `_failure`) **and** by `kernel.py`'s plan walk, both from the one shared extraction helper so the verdicts cannot drift. |
| `dbt-source.target-mismatch` | error | DD-133 (default) | #503. The binding's resolved `target.class` URI differs from the contracted model's `meta.kairos.target_class`. Constructed in `dbt_source.py`'s `validate_contract_target_class` (via `_failure`), but **called** from `kernel.py`'s per-binding loop rather than from `resolve_dbt_model_source`: the comparison needs the binding's *resolved* class URI and `dbt_source.py` has no `ResolutionContext`. The code literal lives here so every `dbt-source.*` code stays in one module, matching this catalog's per-module table layout. Skipped (not passed) when `context.klass()` returns `None` — `_binding_safety_diagnostics` has already blocked that binding with `safety.class-unresolved`, so there is no resolved URI to compare against and a second diagnostic would add nothing. |
| `dbt-source.type-invalid` | error | DD-133 (default) | |
| `dbt-source.unsafe-path` | error | DD-133 (default) | |
| `dbt-source.virtual-source-duplicate` | error | DD-133 (default) | #503. Two `EntityBinding`s selecting **this domain** resolve contracted dbt models that declare the same `meta.kairos.virtual_source_iri`. The only `dbt-source.*` code **not** built through `_failure` — it is constructed directly in `kernel.py` (with the same `/source/dbtModel/contractPath` pointer) because it is a cross-binding verdict, not a single-binding resolution failure. Fed by a pre-pass (`_duplicate_virtual_sources`) that resolves every selected dbt-model binding up front, so both participants are named in the message and both are blocked, rather than only whichever binding the loop reaches second. Necessarily **domain-scoped**: a per-domain compile never loads peer domains' bindings, so hub-wide uniqueness is `validate-dbt-contracts`' job and the message says so. |

## `kernel.py` — scope resolution, safety canonicalization, technical-field/DD-139 checks

`safety.*`/`compiler.*` rows are plain `CompileDiagnostic(code=...)` constructions except
where noted. `safety.class-unresolved` and `safety.property-unresolved` are never built
from a `code="..."` literal directly — they only ever appear as **values** in the
`code_map` lookup table inside `_adapter_safety_diagnostic`, which
`dataclasses.replace(item, code=...)`s an adapter-stage `binding.*` diagnostic into its
canonical `safety.*` form. `technical-field.*` rows come from
`_technical_field_safety_diagnostics` (DD-139).

| Code | Default severity | Rule ID / DD citation | Notes |
| --- | --- | --- | --- |
| `compiler.render-failed` | error | DD-133 (default) | projection rendering raised |
| `field.duplicate-property` | error | DD-133-safety | #343. Two `fields:` entries resolving to the same property URI. `semantic_outputs` in `_technical_field_safety_diagnostics` is built with `setdefault` over `binding.fields`, so a second entry for the same property silently vanishes from the emitted model instead of erroring; dormant today only because the column matcher requires exact name equality, so nothing yet authors two `fields:` entries for one property. |
| `field.output-collision` | error | DD-133-safety | #343. Two `fields:` entries for *different* properties whose output columns collide case-insensitively (e.g. two ontology property local names that normalize to the same `column_name`). Same `setdefault`-silently-discards root cause as `field.duplicate-property`, checked over `binding.fields` the same way `technical-field.output-collision` is checked over `binding.technical_fields`. |
| `relationship.external-reference-same-domain` | error | DD-133-safety | #335. `externalReference` is the *cross*-domain escape hatch; a reference whose `domain` equals the binding's own bypasses every join guarantee at once (nothing checks that `ref('<external.name>')` resolves to a model that exists, `join.foreign` is never resolved against the parent binding's outputs, and `quality.py` skips the in-scope-target check whenever `external_reference is not None` — disabling `silently-dropped-relationship`, the one enforced normative pattern unit). Deliberately **not** `safety.relationship-endpoint`: ten sites already construct that code, so only a distinct literal is pinnable by a test. |
| `relationship.unrealized-technical-field` | warning | DD-139 | #491. A binding with one or more `technicalFields` entries of `purpose: relationship` but an empty `relationships:` list. The carrier is the documented way to keep a foreign-key column in Silver when the join cannot be authored yet (an unbound cross-domain parent, or the self-reference shape below), so authoring one is legal — but never following up leaves the FK in Silver as a raw column with no join, no surrogate key and no orphan window. Warning, not error: the binding is correct and emittable, and staging carriers ahead of the parent domain is legitimate; warnings never fail `CompileResult.succeeded`. Blind spot by construction — it cannot fire when the FK column was authored under a different `purpose` (the CLdN `Qlik-routes` binding marks every carrier `purpose: identity`); `kairos-ontology propose-relationships` covers that case by matching join keys against other bindings directly. |
| `relationship.self-reference-unsupported` | error | DD-133-safety | #334. A non-external relationship whose resolved target class is the binding's own class. `_wire_relationships` would emit `ref('<own model>')` inside that same model (a dbt dependency cycle) plus a second `<model>_sk` column colliding with the model's own surrogate key — the `safety.identity-role-collision` guard only reserves the generated FK name when `external_reference is not None`, so it never sees this case. |
| `safety.adapter-unsupported` | error | DD-133 (default) | also constructed defensively inside `_wire_relationships` (#338) for a composite (non-external) join with more than one column pair — `_relationship_diagnostics` already rejects that shape and blocks the whole binding before it is admitted here, so this site is unreachable via the normal compile path; it exists so a future weakening of that upstream gate cannot silently drop the relationship instead of erroring. |
| `safety.class-unresolved` | error | DD-133 (default) | via `code_map` remap only, see above |
| `safety.column-unresolved` | error | DD-133 (default) | |
| `safety.expression-unsafe` | error | DD-133 (default) | remap of `expression.*` via `_structural_safety_diagnostic` |
| `safety.grain-missing` | error | DD-133 (default) | remap of `binding.schema` (`/grain` pointer); also constructed directly in `quality.py` |
| `safety.identity-incomplete` | error | DD-133 (default) | remap of `binding.schema` (`/identity` pointer) and of `binding.unknown-identity-strategy`; also constructed directly in `quality.py` |
| `safety.identity-role-collision` | error | DD-133-safety | |
| `safety.incremental-identity-incomplete` | error | varies (DD-133 default via `binding.schema` remap, or `DD-109-incremental` when raised directly) | |
| `safety.prefix-ambiguous` | varies (error or warning) | DD-133 (default) | warning only for the cross-file ambiguous-imported-prefix case |
| `safety.property-unresolved` | error | DD-133 (default) | via `code_map` remap only, see above |
| `safety.relationship-endpoint` | error | DD-133 (default) | also constructed directly in `quality.py`, and (#338) twice more inside `_wire_relationships` — once for an unresolved target class/property/target-binding, once for a foreign join column the target binding doesn't map to exactly one output column. The foreign-join-column site is unreachable via the normal compile path (`_relationship_diagnostics` already checks and blocks that pre-wiring). The other site is unreachable **only** for the target-class/property sub-cases; the target-binding sub-case (target binding is `None`) is reachable when a relationship's target binding is later blocked for a reason unrelated to that relationship — `_relationship_diagnostics` resolves the target binding from a snapshot of every *selected* binding taken before blocking runs, while `_wire_relationships` resolves it from `valid_bindings` (post-blocking), so the two views can disagree. When that happens, `quality.py`'s independent, non-suppressible `run_safety_kernel` already blocks the same scenario with its own `safety.relationship-endpoint`, so the observable effect is a redundant second diagnostic with the same code, not a changed pass/fail outcome or a new silent drop. See `tests/test_wire_relationships_diagnostics.py::test_wire_relationships_endpoint_diagnostic_is_reachable_when_target_blocked_unrelated`. |
| `safety.source-unresolved` | error | DD-133 (default) | also constructed defensively inside `_wire_relationships` (#338) when the binding's source relation fails to re-resolve during wiring — unreachable via the normal compile path today because `adapt_binding` already requires the relation to resolve before a binding is admitted here; kept for the same forward-compatibility reason as the other `_wire_relationships` defensive sites above. |
| `safety.type-incompatible` | error | DD-133 (default) | |
| `scope.no-bindings-authored` | error | DD-133 (default) | ontology-only waypoint: a valid ontology slice exists but no EntityBinding is authored yet (or none selects the domain). Blocking, but distinct from `safety.source-unresolved` so a CI gate can tell an expected early stage from a broken source. |
| `technical-field.duplicate-source-ambiguous` | error | DD-139 | |
| `technical-field.output-collision` | error | DD-139 | three call sites |
| `technical-field.relationship-target-ambiguous` | error | DD-139 | #334. A relationship `join.foreign` whose parent source column is carried by more than one authored technical field. `(source column, purpose)` is the technical-field uniqueness key, so this is legal authoring with two distinct output names; the join has no rule to pick one, so it is rejected instead of resolved silently. |

## `load_policy.py` — DD-109 load-policy adapter

All rows are constructed through the local
`_diagnostic(binding, code, message, pointer, *, rule_id=_RULE)` helper, whose default
`rule_id` is `"DD-109-runtime"`.

| Code | Default severity | Rule ID / DD citation | Notes |
| --- | --- | --- | --- |
| `load-policy.ambiguous-cdc-value` | error | DD-109-cdc | |
| `load-policy.ambiguous-runtime-fields` | error | DD-109-time | |
| `load-policy.duplicate-cdc-value` | error | DD-109-cdc | |
| `load-policy.duplicate-value` | error | DD-109-runtime (default) | |
| `load-policy.full-refresh-details` | error | DD-109-runtime (default) | |
| `load-policy.incomplete` | error | DD-109-runtime (default) | two call sites |
| `load-policy.incomplete-cdc` | error | DD-109-cdc | |
| `load-policy.incremental-required` | error | DD-109-incremental | |
| `load-policy.invalid-lookback` | error | DD-109-lookback | |
| `load-policy.scd-correction-incompatible` | error | DD-109-correction | |
| `load-policy.scd-required` | error | DD-109-scd | |
| `load-policy.unsupported-action` | error | DD-109-runtime (default) | |
| `load-policy.unsupported-mode` | error | DD-109-runtime (default) | |

## `quality.py` — non-suppressible static safety kernel (DD-133 §5)

Plain `CompileDiagnostic(code=...)` constructions. The module also documents its own
closed `SAFETY_RULE_CODES` catalogue (13 `safety.*` codes, including the two that are
only ever produced via `kernel.py`'s `code_map` remap — see the `kernel.py` section
above).

| Code | Default severity | Rule ID / DD citation | Notes |
| --- | --- | --- | --- |
| `safety.artifact-collision` | error | DD-133 (default) | two call sites (duplicate binding name, duplicate artifact path) |

| `safety.grain-missing` | error | DD-133 (default) | also constructed via remap in `kernel.py` |
| `safety.identity-incomplete` | error | DD-133 (default) | also constructed via remap in `kernel.py` |
| `safety.relationship-endpoint` | error | DD-133 (default) | also constructed directly in `kernel.py` |

## `temporal.py` — Stage-2 relationship validation (DD-109 temporal lookups)

All rows are constructed through the local `_add(diagnostics, code, message, location)`
helper (used directly, and via the local `_enum_value(...)` helper), which always sets
`rule_id="DD-109-temporal-fk"`.

| Code | Default severity | Rule ID / DD citation | Notes |
| --- | --- | --- | --- |
| `temporal.ambiguous-action-invalid` | error | DD-109-temporal-fk | via `_enum_value` |
| `temporal.cardinality-invalid` | error | DD-109-temporal-fk | via `_enum_value` |
| `temporal.change-detection-invalid` | error | DD-109-temporal-fk | via `_enum_value` |
| `temporal.child-event-time-forbidden` | error | DD-109-temporal-fk | |
| `temporal.child-event-time-required` | error | DD-109-temporal-fk | |
| `temporal.join-missing` | error | DD-109-temporal-fk | |
| `temporal.late-action-invalid` | error | DD-109-temporal-fk | via `_enum_value` |
| `temporal.missing-action-invalid` | error | DD-109-temporal-fk | via `_enum_value` |
| `temporal.mode-invalid` | error | DD-109-temporal-fk | via `_enum_value` |
| `temporal.open-ended-invalid` | error | DD-109-temporal-fk | via `_enum_value` |
| `temporal.overlap-action-invalid` | error | DD-109-temporal-fk | via `_enum_value` |
| `temporal.parent-validity-collision` | error | DD-109-temporal-fk | |
| `temporal.parent-validity-incomplete` | error | DD-109-temporal-fk | |
| `temporal.policy-forbidden` | error | DD-109-temporal-fk | |
| `temporal.policy-required` | error | DD-109-temporal-fk | |
| `temporal.property-duplicate` | error | DD-109-temporal-fk | |
