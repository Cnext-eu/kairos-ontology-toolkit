### Added
- **`validate-dbt-contracts` now rejects a canonical type name used as a SQL cast target
  (`dbt-contract.dialect-uncastable-type`, refs #778).** `cast(x as timestamp)` and
  `cast(x as boolean)` parse cleanly, pass `compile --check`, emit, and then fail against a real
  Fabric warehouse -- and a hub whose CI runs `validate-dbt --structural-only` never connects to
  one, so they reach `main` green. The confusion is narrow and real: `boolean` and `timestamp`
  are legitimate canonical kinds, correct in a binding's `externalReference.key[].type` and
  correct in a dbt contract's `data_type` (dbt-fabric translates `boolean` to `bit`) -- they are
  wrong only in a cast, and the two fields sit next to each other in the same authored file. The
  finding says so, so the fix is not to "correct" a `data_type` that was already right. A
  denylist of known-wrong spellings rather than an allowlist from the adapter type registry:
  T-SQL has many valid types the registry never names (`nvarchar`, `uniqueidentifier`,
  `datetimeoffset`), and flagging those would drown the real findings.
