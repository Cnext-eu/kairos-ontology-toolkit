# DD-106: Immutable Bronze and Mandatory Logical Source Preparation

**Status:** Accepted
**Date:** 2026-07-25
**Affects:** source onboarding, dbt projection, source vocabularies, JSON expansion,
scaffold layout, source/Silver skills
**Implementation:** `scaffold/kairos-prep.ttl`,
`integration/preparation/{source}-prep.ttl`, and the typed
`core/projections/dbt/{policy_normalize,shape,materialize,prep_renderers}.py` pipeline.
Normative companion: [`dd-106-medallion-engineering-policy-v1.md`](../dd-106-medallion-engineering-policy-v1.md)

### Context

DD-014 removed generated staging and made Silver read Bronze directly. In practice this
mixed physical source cleanup with semantic conformance and made repeated renames, casts,
sentinel handling, reserved identifiers, CDC normalization, and JSON extraction part of
Silver or mappings. DD-039 then added a special `bronze_expanded` exception rather than
a coherent preparation boundary.

### Decision

Supersede DD-014 and DD-039. Bronze remains immutable raw source evidence. Every mapped
source table has a source-owned prep contract under `integration/preparation/` and
declares exactly one mode:

- `passthrough` — no physical prep model, allowed only after fail-closed validation finds
  no normalization rule or known risk; or
- `normalize` — emit a physical `stg_{source}__{table}` model.

Prep may normalize physical names and types, trim values, handle evidenced sentinels,
normalize source CDC fields, create a source-scoped `_source_record_key`, and extract
JSON. It must not join sources, aggregate, assign business meaning, perform survivorship,
or assert cross-source entity equivalence. Parent prep preserves parent grain. Scalar
JSON may flatten into that row; arrays become separately keyed child relations with
declared grain. Raw payload or a replayable raw reference is retained.

The domain ontology remains JSON-agnostic. Source and prep contracts retain JSON
provenance because parsing and schema-drift behavior are physical source concerns.

### Rationale

A mandatory logical boundary gives every source the same review point without paying for
empty physical models. Explicit pass-through prevents absence of configuration from
being mistaken for safety. Technical consistency remains separate from reusable Silver
business semantics.

### Consequences

- Add a new prep vocabulary, shapes, scaffold folder, status evidence, and projection
  specs.
- Remove the standalone JSON-only `generate-staging` path, `bronze_expanded`, and
  ordinary-prep use of manual `silverSourceRef`.
- DD-006 remains valid for column-level JSON detection; processing moves to prep.
- DD-015 remains the raw Bronze authority; prep TTL becomes the technical-normalization
  authority.
- DD-018, DD-026, DD-038, DD-074, DD-092, DD-093, DD-104, and DD-105 are amended by this
  boundary as summarized in the companion policy.
- Existing hubs are not migrated; only fresh scaffold layout is supported.
