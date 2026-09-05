# DD-139: Authored Passthrough Technical Columns — DD-107 Amendment

**Status:** Accepted (implemented; auto-materialization stays rejected)
**Date:** 2026-07-28
**Affects:** DD-107 materialization authority, v5 `EntityBinding` schema, source-column
ownership, Silver contract parity, manifest/parity hashing, and mapping diagnostics
**Implementation:** Implemented. The closed-schema `technicalFields:` construct is authored
alongside `fields:` (`entity-binding.schema.json` / `TechnicalField` in `bindings.py`) with a
`name`/`expression`/`type`/`nullable`/`purpose` contract (`purpose` one of `identity`, `quality`,
`relationship`). `adapter.py` materializes each technical field exactly like a semantic field
(participates in the Silver schema contract, dbt SQL, and manifest/parity hash) under a synthetic
non-property marker URI, so it is never emitted as OWL and never asserts an ontology property.
Case-insensitive output-name collisions (against semantic fields, other technical fields, and
reserved runtime names) and ambiguous duplicate-source-column reuse are rejected in
`kernel.py`'s `_binding_safety_diagnostics` (`technical-field.output-collision` /
`technical-field.duplicate-source-ambiguous`); a technical field's declared type incompatible
with its bound physical source column is rejected in `adapter.py`
(`technical-field.type-incompatible`). `identity.sourceKey`/`quality.columns`/relationship
`join.local`/`join.foreign` now resolve against authored technical fields exactly as they do
against `fields:`, so the previous "map the FK join column as a scalar field" workaround is no
longer required. **Correction (#334):** the `join.foreign` half of that sentence was aspirational
when this decision was first recorded — `kernel.py`'s `_relationship_output_column` iterated
`binding.fields` only, so a parent join column carried by a technical field was rejected with
`safety.relationship-endpoint` ("relationship foreign column '…' is not mapped by the target
binding"). Any surrogate technical primary key was therefore unauthorable as a parent endpoint
and every relationship pointing at one was silently dropped. That resolution is implemented as
of #334: the lookup falls back to authored technical fields with **no `purpose` filter**
(`adapter.py` materializes every technical field regardless of purpose, so every one is a valid
join target), mapped `fields:` keep precedence, and the match is made on the technical field's
bound source `expression` column while the value returned into the join predicate is its output
`name` — a technical field renames, so returning `join.foreign` verbatim would reference a column
the parent model never emits under that name. Because `(source column, purpose)` is the
technical-field uniqueness key, one source column may legally carry two technical fields with two
output names; that case is rejected as `technical-field.relationship-target-ambiguous` rather than
resolved silently. Two adjacent holes the same change closes: a non-external relationship whose
target class is the binding's own is rejected (`relationship.self-reference-unsupported` — it would
otherwise emit `ref('<own model>')` inside that very model and a duplicate `<model>_sk`), and an
`externalReference` whose `domain` equals the binding's own is rejected
(`relationship.external-reference-same-domain` — it bypasses join validation, model-existence
checking, and the `silently-dropped-relationship` pattern check all at once). Validating that a
referenced *foreign* domain resolves stays deliberately unimplemented: the only available
mechanism ("a domain with bindings exists in this hub") would break the out-of-hub parent case
DD-138 explicitly preserves. `compile --explain` labels technical outputs separately
(`ExplainEntity.technical_fields`), distinct from the semantic `fields` pairs. As originally
decided, implicit auto-materialization remains rejected: the compiler never creates a technical
field on its own — every one must be explicitly authored in the binding YAML.
**Correction (#338, items 1 and 4):** two real dogfood gaps in this construct's boundary are
closed. First, `purpose` gains a fourth enum value, `carried`, for a plain materialized column
that is honestly none of `identity`/`quality`/`relationship` (e.g. an alternate external code
space) — previously an author had to pick a value known to be wrong. Second, `fields:` no longer
requires at least one entry unconditionally: `entity-binding.schema.json` now allows `fields: []`
when `relationships:` is non-empty (`allOf`/`if`/`then`), unblocking a class whose only property is
an object property (a pure junction/link entity, e.g. a many-to-many association row) — its own
identity and any relationship `join.local` columns are still carried via `technicalFields:` exactly
as already described above, no compiler change beyond the schema was needed. `fields: []` alone,
with no `relationships:` entry, still maps nothing at all and remains rejected.

### Context

DD-107 makes source ownership explicit: a source column becomes a materialized Silver output only
when a `fields:` expression references it. Identity, quality, and relationship join columns are
therefore expected to be mapped fields today. That rule is intentional because the `fields:` set is
the deterministic column contract used by parity checks, generated schema, and review.

However, identity keys, quality check columns, and relationship join keys are sometimes technical
columns whose materialization is needed for runtime checks but whose meaning should not invent a
synthetic ontology property. ISSUE-4/5 / Workstream B2 asks whether authors need an ergonomic,
explicit way to carry those columns through.

### Decision

Amend DD-107 to allow an explicit authored passthrough/technical field construct that materializes
a source column without asserting a new ontology property. The construct should be closed-schema,
reviewable, and distinguishable from semantic `fields:` entries. It names the source expression,
the output column, the output type, nullability, and its technical purpose such as identity,
quality, or relationship support.

Implicit auto-materialization is rejected. Automatically adding `identity.sourceKey`,
`quality.columns`, or relationship join columns would change the deterministic parity/manifest
column set behind the author's back, make compiler output depend on policy side effects rather
than the declared projection, and risk exposing PII or other sensitive source columns that were
not intentionally selected for Silver.

Validation rules should include:

- case-insensitive output-name collision checks against semantic fields, other passthrough fields,
  and reserved runtime/generated names;
- duplicate source use checks, allowing the same source column only when outputs and purposes are
  explicitly distinct and non-ambiguous;
- required output names and types, with adapter-normalized types participating in the same Silver
  schema contract as semantic fields;
- fail-closed diagnostics when a passthrough is referenced by identity, quality, or relationships
  but is missing or type-incompatible.

Passthrough columns are materialized Silver outputs and therefore affect the downstream Silver
contract, dbt schema YAML, manifest/parity hash, emitted SQL bytes, and any release evidence that
compares expected and actual columns. They are not ontology properties, are not emitted as OWL, and
must be labelled in explanations as technical outputs.

### Rationale

An explicit construct preserves DD-107's source-ownership rule while avoiding ontology pollution.
It keeps the reviewer in control of which physical columns leave Bronze/prep and makes sensitive
column exposure a conscious authored decision.

### Consequences

- Workstream B1 can remain limited to clearer diagnostics and documentation for the current rule.
- Workstream B2 requires binding-schema, normalization, render, contract, and parity-hash changes
  before authors can rely on passthrough technical outputs.
- Any implementation must treat passthrough outputs as first-class dbt contract columns but not as
  canonical ontology facts.
