### Fixed
- **A system-versioning column no longer becomes part of an entity's identity.**
  `anchor-tables` put operational columns in `grain_columns` — on one real hub it proposed
  `natural_key: [KLMEMO, SETNR]` and `grain_columns: [KLMEMO, SETNR, ttSysStartTime]` —
  and `generate-bindings` turns every grain column into a `purpose: identity` technical
  field. Five of seven generated bindings carried a SQL Server row-validity timestamp as
  part of identity, which silently changes the Silver grain from *one row per consignment*
  to *one row per consignment per version*: counts become version counts, uniqueness tests
  pass that should fail, and a join on the entity fans out.

  The grain is now filtered with the toolkit's own `_is_operational_column` predicate,
  conservatively: a column the model itself placed in `natural_key` is never dropped, and
  the grain is never emptied — a table with no grain is not a safer answer than one with a
  questionable grain.

- **`generate-bindings` no longer emits bindings its own compiler rejects.** Identity
  technical fields were typed `string` unconditionally, because the alignment only carries
  a type for columns it *mapped* and an identity column is often one it did not. `compile`
  then failed with `technical-field.type-incompatible`. The physical type is now read from
  the source vocabulary — the same place the compiler reads it from — when neither the
  profile nor the alignment knows it.
