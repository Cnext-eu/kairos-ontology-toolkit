# Source preparation contracts

Every mapped Bronze table must have exactly one policy in
`integration/preparation/{source}-prep.ttl`.

- `passthrough` means validation found no normalization operation or known risk.
- `normalize` creates a physical `stg_{source}__{table}` model.
- Silver routing is automatic: normalized inputs use `ref('stg_...')`; verified
  passthrough inputs use `source()`. Do not duplicate prep routing with a manual
  `silverSourceRef`.
- Prep may rename physical identifiers, perform lossless cleanup, parse explicit
  types, normalize evidenced sentinels and CDC fields, create
  `_source_record_key`, extract scalar JSON, and create keyed array-child
  relations.
- Incremental/SCD Silver entities require `normalize` and a complete canonical CDC
  mapping: operation code map plus distinct source-update, business-effective,
  ingestion, and complete total-order sequence fields. Projection fails closed if
  any linked source identity cannot supply those facts.
- `*=snapshot` is the explicit operation fallback for a governed complete-snapshot
  source. It is never inferred.
- Prep must not join independent relations, aggregate, classify business data,
  perform survivorship, assert cross-source equivalence, or silently change
  parent grain.

Start with `source-prep.ttl.template`; use `source-prep.example.ttl` as a complete
passthrough reference. Validation uses the packaged `kairos-prep` vocabulary and
SHACL shapes.
