# DD-109: Temporal Execution, Canonical Hashing, and FK Resolution

**Status:** Accepted
**Date:** 2026-07-25
**Affects:** incremental dbt models, SCD, CDC, row hashes, temporal FKs, runtime
determinism and generated tests
**Implementation:** complete for the shared typed/dbt runtime authority: fail-closed
`HistorySpec`/incremental/CDC policy, canonical hash codec v1 and golden vectors,
`TemporalRelationshipSpec`, Fabric/Databricks physical plans, dedicated SCD1/SCD2
renderers, generated dbt tests/quarantine artifacts, and release evidence. Shared
Silver DDL parity remains DD-110 follow-on debt.

### Context

DD-025 defined SCD1/SCD2 but not late events, corrections, deletes, replay, backfill,
same-time ordering, or valid time versus load time. Current row hashing conflates values
under adapter-specific casts, and temporal FK joins do not define zero/multiple-match
behavior.

### Decision

Supersede DD-025. Each incremental entity declares CDC operation, source update/effective
time, ingestion time, total-order tie-breaker, lookback, delete, late-arrival,
correction, replay, backfill, and schema-change behavior. SCD2 explicitly declares
`business-valid` or `load-history`; generated run time must not be presented as business
validity. `_loaded_at` comes from one injected run clock.

Hash input uses a versioned, ordered, typed, length-delimited canonical encoding with an
explicit null representation and SHA-256. Changes to the hash contract require a
backfill/migration decision for generated data even though old hub configuration is not
supported.

Windows and deduplication require a complete total order. Temporal relationships declare
interval boundaries, time-zone normalization, expected lookup cardinality, and
missing/ambiguous/late-parent behavior: fail, quarantine, retry, or explicit unknown
member. Multiple matches are never resolved by silently choosing one.

The normalized relationship inventory remains complete for Gold analysis. Silver
temporal policy applies only to relationships that canonically qualify for Silver
on the materialized source class: explicit `silverForeignKeyOn`,
`silverForeignKey`, or `silverColumnName`, `owl:FunctionalProperty`, or an
applicable max-cardinality-one restriction. A complete domain/range-only object
property is not a materialized Silver FK.

### Rationale

Incremental correctness depends on time and ordering semantics, not merely a unique key
and row hash. Canonical serialization and explicit FK failures are required for
cross-adapter reproducibility.

### Consequences

- Amend DD-019 and the Silver runtime provisions of DD-104.
- Generate tests for replay idempotency, insert/update/no-op/delete/reinsert, late
  correction, natural-key change, interval integrity, one current row, and temporal FK
  ambiguity.
- Artifact determinism and runtime determinism are reported separately.
- Silver temporal completeness, capability, DQ scope, and authority generation
  consume the Silver-qualified relationship view; Gold retains the unfiltered
  descriptor inventory.

### Implemented contract

- `canonical_hash.py` defines the reference bytes:
  `KAIROS-CANONICAL-HASH|v1|` followed by ordered
  `{type}:N:0:;` or `{type}:V:{utf8-byte-length}:{utf8-hex};` fields, prevalidated
  NFC text,
  exact fixed-scale decimals, UTC microsecond timestamps, canonical supported JSON,
  binary hex, and lowercase SHA-256. Binary-float and adapter-ambiguous SQL JSON
  inputs are rejected.
- `SilverRuntimeAuthoritySpec` is normalized once and carried into
  `RuntimeModelSpec` and `RuntimePhysicalPlan`. Bind retains relationship/model
  structure only; render consumes typed plans and creates content only.
- SCD1 uses total-order current-state merge. SCD2 recomputes affected history with
  replay deduplication, correction ranking, explicit tombstones, separate
  `_business_valid_from/to` and `_system_from/to`, half-open intervals, and one
  deterministic `is_current` row. `_loaded_at` is only the injected run clock.
- A captured normalized CDC `operation='delete'` is a hard-delete event.
  `hardDeletePolicy='tombstone'` retains an explicit deleted row and `ignore` drops
  that event. Physical deletion, including absence inference from snapshots, is not
  expressible by the current source contract and fails closed rather than being
  reported as applied. A source soft-delete flag is distinct: preparation must map it
  to `operation='soft-delete'`; `softDeletePolicy='apply-operation'` materializes a
  logical tombstone, while `ignore` drops it. Unsupported block/quarantine actions fail
  before rendering.
- SCD2 `append-correction` is rejected with
  `history.scd2-append-correction-unsupported` until a renderer can preserve separate,
  non-overlapping half-open valid/system intervals. It never falls through to
  replace-by-total-order behavior.
- Fabric canonical hashing uses UTF-8 `VARCHAR(MAX)`/`VARBINARY(MAX)` throughout,
  including the `HASHBYTES` input, so values beyond 4 KB and 8 KB are not truncated.
  Databricks packages pin the SQL session to UTC with `SET TIME ZONE 'UTC'`; timestamp
  lexical formatting therefore does not depend on the caller's session time zone.
  Frozen >8 KB text/binary vectors and macro-versus-Python renderer parity tests guard
  both adapter implementations.
- Byte-identical replay is collapsed. Contradictory values or operations at the exact
  same complete event order fail closed in the Python reference and SCD2 SQL runtime
  (adapter-native error guard); generated runtime tests also require the authored total
  order to remain unique. Sources must add a deterministic sequence tie-breaker rather
  than relying on arrival order.
- Bounded lookback is mandatory. Range replay and full rebuild require their
  respective authored approvals; unauthorized dbt variables fail at compile time.
- Temporal joins count matches rather than choosing one. `current`, business-valid
  `as-of`, and `none` modes generate explicit cardinality tests and fail,
  quarantine/retry, or unknown-member behavior. As-of is UTC, microsecond,
  closed-open and never receives a blanket current-row predicate.
- Release data exposes effective ordering/time/hash/delete/replay/backfill/
  correction/schema and temporal-FK actions with DD-109 rule IDs, adapter
  dispositions, and authored/registry evidence.
