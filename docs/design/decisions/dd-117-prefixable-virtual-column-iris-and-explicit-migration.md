# DD-117: Prefixable Virtual-Column IRIs and Explicit Migration

**Status:** Accepted
**Date:** 2026-07-26
**Affects:** synchronized dbt virtual vocabularies and source-column mapping references
**Implementation:** `core/dbt_contract_sync.py`, `core/column_iri_migration.py`, and
`migrate-column-iris`

### Context

Slash-delimited virtual-column IRIs such as `#orders/order_id` are valid full IRIs but
cannot be written as Turtle prefixed names because `/` is not allowed in `PN_LOCAL`.
Silently changing managed vocabularies would break existing mappings.

### Decision

New columns use `{virtual_source_iri}__{percent-encoded-column-name}`. The stable `__`
separator is valid in `PN_LOCAL`; dbt contract column names are restricted identifiers.
Synchronization preserves identities found in an existing managed vocabulary.

Legacy full IRIs remain resolvable during a deprecation window. Migration is a separate,
default-preview operation that rewrites source and mapping RDF references with `rdflib`.
Apply requires an explicit new backup directory, reports every old/new IRI, checks all
target collisions before writing, and preserves unrelated triples.

Compatibility is vocabulary-led: legacy mappings resolve against a preserved legacy
vocabulary, but no legacy aliases are added to a newly generated vocabulary. Mixed
new-vocabulary/old-mapping input remains an explicit resolution error. Migration
transitions the legacy vocabulary and its discovered mapping references together.

### Rationale

Double underscore is visually distinct, valid at every `PN_LOCAL` position used here,
and avoids the trailing-dot restrictions of the alternative `.` separator. Explicit
migration keeps compatibility and review separate from routine contract synchronization.

### Consequences

- New mappings can use compact prefixed names such as `virtual:orders__order_id`.
- Existing hubs retain slash IRIs until their owners run the migration.
- Serialized Turtle formatting may change on apply, while graph semantics and unrelated
  triples remain intact.
