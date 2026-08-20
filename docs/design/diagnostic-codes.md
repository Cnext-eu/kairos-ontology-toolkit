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

## `dbt_source.py` — contracted dbt model source resolution

All rows are constructed through the local `_failure(binding, code, message, pointer)`
helper, which never overrides `rule_id`/`severity` (both fall back to the dataclass
default).

| Code | Default severity | Rule ID / DD citation | Notes |
| --- | --- | --- | --- |
| `dbt-source.columns-invalid` | error | DD-133 (default) | |
| `dbt-source.contract-invalid` | error | DD-133 (default) | |
| `dbt-source.contract-not-enforced` | error | DD-133 (default) | |
| `dbt-source.dependency-unresolved` | error | DD-133 (default) | A selected model's transitive `ref()` target is missing or ambiguous under `integration/transforms/dbt/models/`; projection cannot emit a self-contained project. |
| `dbt-source.grain-invalid` | error | DD-133 (default) | |
| `dbt-source.grain-mismatch` | error | DD-133 (default) | |
| `dbt-source.identity-mismatch` | error | DD-133 (default) | |
| `dbt-source.missing` | error | DD-133 (default) | |
| `dbt-source.model-unresolved` | error | DD-133 (default) | |
| `dbt-source.path-unresolved` | error | DD-133 (default) | |
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
